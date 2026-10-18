# Secret Manager: o sal da instalação e o PIN da assinatura, replicados só na região dos dados.
#
# - Sal (LGPD): o mesmo arquivo instalacao.json que a máquina da cooperativa cria em dados_locais/config/
#   (src/laudo/privacidade.py), montado como arquivo em LAUDO_CONFIG_DIR. Gerado uma vez por recurso efêmero e
#   gravado por atributo write-only: não passa pelo state do Terraform. Trocar o sal invalida a comparação com
#   hashes antigos (índices de fotos e documentos), por isso a versão do segredo é fixa.
# - PIN: variável LAUDO_PIN da API (src/laudo/api/servico.py). Gerado com 6 dígitos se não for informado;
#   para trocar, informe pin_assinatura (ou deixe gerar) e aumente versao_pin.

ephemeral "random_bytes" "sal" {
  length = 32
}

ephemeral "random_password" "pin" {
  length  = 6
  lower   = false
  upper   = false
  special = false
  numeric = true
}

locals {
  # Mesmo formato do arquivo criado na primeira execução local (versão 1, sal de 256 bits em hexadecimal).
  instalacao_json = jsonencode({
    versao = 1
    sal    = coalesce(var.sal_instalacao, ephemeral.random_bytes.sal.hex)
    aviso = join(" ", [
      "Sal da instalação do Laudo Vivo (LGPD). Não versionar, não copiar para outra instalação;",
      "trocar o sal invalida a comparação com hashes antigos.",
    ])
  })
}

resource "google_secret_manager_secret" "instalacao" {
  secret_id           = "${var.prefixo}-instalacao"
  deletion_protection = var.protecao_exclusao

  replication {
    user_managed {
      replicas {
        location = var.regiao
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "instalacao" {
  secret                 = google_secret_manager_secret.instalacao.id
  secret_data_wo         = local.instalacao_json
  secret_data_wo_version = 1
}

resource "google_secret_manager_secret" "pin" {
  secret_id           = "${var.prefixo}-pin"
  deletion_protection = var.protecao_exclusao

  replication {
    user_managed {
      replicas {
        location = var.regiao
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "pin" {
  secret                 = google_secret_manager_secret.pin.id
  secret_data_wo         = coalesce(var.pin_assinatura, ephemeral.random_password.pin.result)
  secret_data_wo_version = var.versao_pin
}

# A API lê os dois; o expurgo só o sal (os scripts carregam a mesma configuração da instalação).
resource "google_secret_manager_secret_iam_member" "instalacao_api" {
  secret_id = google_secret_manager_secret.instalacao.id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.sa_api
}

resource "google_secret_manager_secret_iam_member" "pin_api" {
  secret_id = google_secret_manager_secret.pin.id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.sa_api
}

resource "google_secret_manager_secret_iam_member" "instalacao_expurgo" {
  secret_id = google_secret_manager_secret.instalacao.id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.sa_expurgo
}
