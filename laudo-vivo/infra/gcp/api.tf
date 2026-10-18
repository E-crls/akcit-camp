# API e interface web (FastAPI de laudo.api) no Cloud Run, na região dos dados.
#
# Uma instância, dois contêineres:
# - "borda" (Envoy, contêiner de entrada): recebe o tráfego do Cloud Run em HTTP/2 (h2c), repassa ao uvicorn
#   e oferece em 127.0.0.1:11434 a ponte para o servidor do modelo (modelos/borda.yaml.tftpl);
# - "api": `python -m laudo.api`, o mesmo comando da máquina da cooperativa, na porta 8000. O Cloud Run só
#   publica a porta da borda; a 8000 fica visível apenas dentro da instância (e às sondas de saúde).
#
# Os diretórios de dados do produto são volumes do Cloud Storage (FUSE) nos mesmos caminhos relativos de
# dados_locais/api: cada subpasta é montada do prefixo api/<pasta> do bucket de dados, e chaves/ vem do bucket
# do cofre (chave do KMS separada). O estado fica em arquivo, com um escritor: no máximo uma instância.

locals {
  tipo_envoy = "type.googleapis.com/envoy.extensions"

  host_modelo = (
    local.modelo_cloud_run ? trimprefix(one(google_cloud_run_v2_service.modelo[*].uri), "https://") :
    local.modelo_gce ? one(google_compute_address.modelo[*].address) : ""
  )

  borda_config = templatefile("${path.module}/modelos/borda.yaml.tftpl", {
    porta_entrada  = local.porta_entrada
    porta_api      = local.porta_api
    porta_modelo   = local.porta_modelo
    tempo_limite   = var.api_timeout
    modo_modelo    = var.servidor_modelo
    host_modelo    = local.host_modelo
    tipo_hcm       = "${local.tipo_envoy}.filters.network.http_connection_manager.v3.HttpConnectionManager"
    tipo_router    = "${local.tipo_envoy}.filters.http.router.v3.Router"
    tipo_gcp_authn = "${local.tipo_envoy}.filters.http.gcp_authn.v3.GcpAuthnFilterConfig"
    tipo_audience  = "${local.tipo_envoy}.filters.http.gcp_authn.v3.Audience"
    tipo_tls       = "${local.tipo_envoy}.transport_sockets.tls.v3.UpstreamTlsContext"
  })

  args_api = [
    "-m", "laudo.api",
    "--host", "0.0.0.0",
    "--porta", tostring(local.porta_api),
    "--llm", local.modo_llm,
    "--ferramentas", var.ferramentas,
    "--caso", var.caso_demo,
    "--perfil", var.perfil,
    "--modelo", var.modelo_llm,
    "--asr", var.asr,
    "--dados", local.dir_dados_api,
  ]

  # Variáveis de ambiente lidas pelo produto (src/laudo): diretórios, servidor do modelo e fuso.
  env_produto = merge(
    {
      LAUDO_DADOS_DIR  = local.dir_dados_api
      LAUDO_CONFIG_DIR = local.dir_config
      OLLAMA_HOST      = "http://127.0.0.1:${local.porta_modelo}"
      LAUDO_MODELO     = var.modelo_llm
      TZ               = var.fuso
      PYTHONUNBUFFERED = "1"
    },
    var.persistir_cache_satelite ? { LAUDO_DADOS_LOCAIS = local.dir_cache } : {},
  )

  # Volumes do Cloud Storage: nome do volume => (bucket, prefixo montado, caminho no contêiner).
  volumes_gcs = merge(
    {
      for p in local.pastas_estado : "dados-${p}" => {
        bucket  = google_storage_bucket.dados.name
        prefixo = "api/${p}"
        caminho = "${local.dir_dados_api}/${p}"
      }
    },
    {
      cofre = {
        bucket  = google_storage_bucket.cofre.name
        prefixo = null
        caminho = "${local.dir_dados_api}/chaves"
      }
    },
    var.persistir_cache_satelite ? {
      cache = {
        bucket  = google_storage_bucket.dados.name
        prefixo = "cache"
        caminho = local.dir_cache
      }
    } : {},
  )
}

resource "google_cloud_run_v2_service" "api" {
  name                = local.nome_api
  location            = var.regiao
  description         = "Laudo Vivo: API e interface web"
  ingress             = "INGRESS_TRAFFIC_ALL"
  iap_enabled         = var.acesso_api == "iap"
  deletion_protection = var.protecao_exclusao

  template {
    service_account                  = google_service_account.api.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    timeout                          = var.api_timeout
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = var.api_min_instancias
      max_instance_count = 1
    }

    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.principal.name
        tags       = [local.rede_tag_api]
      }
    }

    containers {
      name       = "borda"
      image      = local.imagem_borda
      args       = ["envoy", "--config-yaml", local.borda_config, "--log-level", "warn"]
      depends_on = ["api"]

      # Roda como o usuário do contêiner (sem a troca de usuário do docker-entrypoint.sh da imagem).
      env {
        name  = "ENVOY_UID"
        value = "0"
      }

      ports {
        name           = "h2c"
        container_port = local.porta_entrada
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = !var.api_cpu_sempre_alocada
      }

      startup_probe {
        period_seconds    = 2
        failure_threshold = 30
        tcp_socket {
          port = local.porta_entrada
        }
      }
    }

    containers {
      name        = "api"
      image       = local.imagem_api
      args        = concat(var.api_comando, local.args_api)
      working_dir = var.api_diretorio_trabalho

      resources {
        limits = {
          cpu    = var.api_cpu
          memory = var.api_memoria
        }
        cpu_idle          = !var.api_cpu_sempre_alocada
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.env_produto
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "LAUDO_PIN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pin.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 2
        period_seconds        = 5
        timeout_seconds       = 4
        failure_threshold     = 48
        http_get {
          path = "/api/saude"
          port = local.porta_api
        }
      }

      liveness_probe {
        period_seconds    = 30
        timeout_seconds   = 10
        failure_threshold = 5
        http_get {
          path = "/api/saude"
          port = local.porta_api
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

  depends_on = [
    google_secret_manager_secret_iam_member.instalacao_api,
    google_secret_manager_secret_iam_member.pin_api,
    google_secret_manager_secret_version.pin,
    google_storage_bucket_iam_member.dados_api,
    google_storage_bucket_iam_member.cofre_api,
    google_artifact_registry_repository_iam_member.leitura_cloud_run,
  ]
}

# Acesso à interface: login Google pelo IAP (o agente do IAP invoca o serviço) ou só IAM.
resource "google_cloud_run_v2_service_iam_member" "iap_invoca_api" {
  count = var.acesso_api == "iap" ? 1 : 0

  name     = google_cloud_run_v2_service.api.name
  location = var.regiao
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.agente_iap}"
}

resource "google_iap_web_cloud_run_service_iam_member" "acesso" {
  for_each = var.acesso_api == "iap" ? toset(var.membros_acesso) : toset([])

  cloud_run_service_name = google_cloud_run_v2_service.api.name
  location               = var.regiao
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}

resource "google_cloud_run_v2_service_iam_member" "acesso_iam" {
  for_each = var.acesso_api == "iam" ? toset(var.membros_acesso) : toset([])

  name     = google_cloud_run_v2_service.api.name
  location = var.regiao
  role     = "roles/run.invoker"
  member   = each.value
}
