# Contatos do formulário da página do produto: um objeto JSON por contato, num bucket privado, apagado em 180 dias
# (LGPD: só para responder ao contato). O serviço só cria objetos; ler é com a conta da equipe:
#   gcloud storage cat "gs://<projeto>-<nome>-contatos/contatos/*" --project <projeto>

resource "google_storage_bucket" "contatos" {
  name                        = "${var.projeto}-${var.nome}-contatos"
  location                    = var.regiao
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = 180
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "servico_grava_contatos" {
  bucket = google_storage_bucket.contatos.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.servico.email}"
}
