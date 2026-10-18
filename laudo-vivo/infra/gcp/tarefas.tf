# Jobs do Cloud Run e agendamentos (Cloud Scheduler), na região dos dados.
#
# - "<prefixo>-expurgo": `scripts/expurgo_lgpd.py vencidos --dias N --executar`, o mesmo comando da máquina
#   da cooperativa, sobre os mesmos volumes da API. Cifra os brutos ainda em claro das fiscalizações seladas
#   há mais de N dias e apaga a chave delas no bucket do cofre (crypto-shredding; docs/privacidade.md,
#   seção 4).
# - "<prefixo>-arquivamento": copia para o bucket de arquivo os pacotes de exibição (pacote.zip com manifest
#   sha256) dos laudos selados, sem sobrescrever o que já está lá. O pacote só existe depois da assinatura
#   humana e do pedido de pacote na interface.

resource "google_cloud_run_v2_job" "expurgo" {
  name                = "${var.prefixo}-expurgo"
  location            = var.regiao
  deletion_protection = var.protecao_exclusao

  template {
    task_count = 1

    template {
      service_account       = google_service_account.expurgo.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = "3600s"
      max_retries           = 1

      containers {
        image       = local.imagem_api
        working_dir = var.api_diretorio_trabalho
        args = concat(var.api_comando, [
          "scripts/expurgo_lgpd.py",
          "--dados", local.dir_dados_api,
          "vencidos",
          "--dias", tostring(var.dias_retencao_brutos),
          "--executar",
        ])

        dynamic "env" {
          for_each = local.env_produto
          content {
            name  = env.key
            value = env.value
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        volume_mounts {
          name       = "config"
          mount_path = local.dir_config
        }

        dynamic "volume_mounts" {
          for_each = local.volumes_gcs
          content {
            name       = volume_mounts.key
            mount_path = volume_mounts.value.caminho
          }
        }
      }

      volumes {
        name = "config"
        secret {
          secret = google_secret_manager_secret.instalacao.secret_id
          items {
            path    = "instalacao.json"
            version = google_secret_manager_secret_version.instalacao.version
          }
        }
      }

      dynamic "volumes" {
        for_each = local.volumes_gcs
        content {
          name = volumes.key
          gcs {
            bucket    = volumes.value.bucket
            read_only = false
            mount_options = concat(
              ["implicit-dirs"],
              volumes.value.prefixo == null ? [] : ["only-dir=${volumes.value.prefixo}"],
              local.opcoes_dono,
            )
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.instalacao_expurgo,
    google_storage_bucket_iam_member.dados_expurgo,
    google_storage_bucket_iam_member.cofre_expurgo,
  ]
}

locals {
  # Copia só api/laudos/<fis>/pacote/*.zip; o resto da pasta do laudo é excluído pela expressão regular.
  script_arquivamento = <<-EOT
    set -eu
    origem="gs://${google_storage_bucket.dados.name}/api/laudos"
    destino="gs://${google_storage_bucket.arquivo.name}/pacotes"
    if ! gcloud storage ls "$origem/" >/dev/null 2>&1; then
      echo "nenhum laudo no bucket de dados ainda"
      exit 0
    fi
    gcloud storage rsync "$origem" "$destino" --recursive --no-clobber \
      --exclude='^(?!.+/pacote/[^/]+[.]zip$).*'
  EOT
}

resource "google_cloud_run_v2_job" "arquivamento" {
  name                = "${var.prefixo}-arquivamento"
  location            = var.regiao
  deletion_protection = var.protecao_exclusao

  template {
    task_count = 1

    template {
      service_account = google_service_account.arquivamento.email
      timeout         = "1800s"
      max_retries     = 1

      containers {
        image   = local.imagem_gcloud
        command = ["/bin/sh", "-c"]
        args    = [local.script_arquivamento]

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.dados_arquivamento,
    google_storage_bucket_iam_member.arquivo_leitura,
    google_storage_bucket_iam_member.arquivo_criacao,
  ]
}

# --- agendamentos ----------------------------------------------------------------------------------------

locals {
  agendamentos = merge(
    var.expurgo_agendado ? {
      expurgo = { job = google_cloud_run_v2_job.expurgo.name, agenda = var.agenda_expurgo }
    } : {},
    var.arquivamento_agendado ? {
      arquivamento = { job = google_cloud_run_v2_job.arquivamento.name, agenda = var.agenda_arquivamento }
    } : {},
  )
}

resource "google_cloud_run_v2_job_iam_member" "agendador" {
  for_each = local.agendamentos

  name     = each.value.job
  location = var.regiao
  role     = "roles/run.invoker"
  member   = local.sa_agendador
}

resource "google_cloud_scheduler_job" "jobs" {
  for_each = local.agendamentos

  name             = "${var.prefixo}-${each.key}"
  region           = var.regiao
  schedule         = each.value.agenda
  time_zone        = var.fuso
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri = join("", [
      "https://run.googleapis.com/v2/projects/${var.projeto}/locations/${var.regiao}/jobs/",
      "${each.value.job}:run",
    ])
    oauth_token {
      service_account_email = google_service_account.agendador.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.agendador]
}
