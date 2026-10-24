# Demo pública do Laudo Vivo: um site no Cloud Run, sem GPU, com dados sintéticos.
#
# Só roda na nuvem o que a plateia consegue usar na hora: o agente em conversa (passos gravados em replay, sem
# custo, e texto livre no Gemini do Vertex AI, com teto de tokens), a voz (Whisper pequeno na CPU) e a
# assinatura com PIN. Vídeo do brete, satélite, GPS e leitura do papel vêm prontos do caso de demonstração.
#
# Custo: o Cloud Run cobra só enquanto atende requisição (cpu_idle) e tem teto de 1 instância; o registro
# guarda só as 2 imagens mais novas; o bucket de fontes apaga tudo em 1 dia. Estimativa em README.md.

locals {
  rotulos = {
    produto        = "laudo-vivo"
    ambiente       = "demo-publica"
    evento         = "akcit-camp-2026"
    centro-custo   = "laudo-vivo-demo"
    gerenciado-por = "terraform"
  }

  apis = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])
}

data "google_project" "atual" {
  project_id = var.projeto
}

resource "google_project_service" "apis" {
  for_each = local.apis

  project = var.projeto
  service = each.value
  # Desligar uma API no destroy pode quebrar outros usos do projeto; ligada e sem uso, não custa nada.
  disable_on_destroy = false
}

# --- Registro das imagens ------------------------------------------------------------------------------------

resource "google_artifact_registry_repository" "imagens" {
  location      = var.regiao
  repository_id = var.nome
  description   = "Imagens da demo pública do Laudo Vivo"
  format        = "DOCKER"

  # Armazenamento cobra por GB: ficam só as 2 versões mais novas.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "manter-2-mais-novas"
    action = "KEEP"
    most_recent_versions {
      keep_count = 2
    }
  }
  cleanup_policies {
    id     = "apagar-o-resto"
    action = "DELETE"
    condition {
      tag_state  = "ANY"
      older_than = "3600s"
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Fontes do build (o Cloud Build lê daqui) -----------------------------------------------------------------

resource "google_storage_bucket" "fontes" {
  name                        = "${var.projeto}-${var.nome}-fontes"
  location                    = var.regiao
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Contas de serviço (uma para o build, outra para o serviço; nenhuma chave é criada) -----------------------

resource "google_service_account" "servico" {
  account_id   = "${var.nome}-run"
  display_name = "Laudo Vivo demo: Cloud Run"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "build" {
  account_id   = "${var.nome}-build"
  display_name = "Laudo Vivo demo: Cloud Build"
  depends_on   = [google_project_service.apis]
}

# O serviço chama o Gemini e escreve logs e métricas; nada além disso.
resource "google_project_iam_member" "servico" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.projeto
  role    = each.value
  member  = "serviceAccount:${google_service_account.servico.email}"
}

resource "google_project_iam_member" "build_logs" {
  project = var.projeto
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_artifact_registry_repository_iam_member" "build_escreve" {
  location   = google_artifact_registry_repository.imagens.location
  repository = google_artifact_registry_repository.imagens.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "build_le_fontes" {
  bucket = google_storage_bucket.fontes.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}
