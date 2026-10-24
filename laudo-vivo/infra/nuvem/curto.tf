# Link curto do QR: <site_curto>.web.app (Firebase Hosting, grátis) redireciona para a demo no Cloud Run, com o caminho.
# Só redireciona (302): a demo, a sessão e o cookie continuam no domínio do Cloud Run.

resource "google_project_service" "firebase" {
  for_each = toset(["firebase.googleapis.com", "firebasehosting.googleapis.com"])

  project            = var.projeto
  service            = each.value
  disable_on_destroy = false
}

resource "google_firebase_project" "atual" {
  provider = google-beta
  project  = var.projeto

  depends_on = [google_project_service.firebase]
}

resource "google_firebase_hosting_site" "curto" {
  count    = local.com_servico ? 1 : 0
  provider = google-beta
  project  = var.projeto
  site_id  = var.site_curto

  depends_on = [google_firebase_project.atual]
}

resource "google_firebase_hosting_version" "curto" {
  count    = local.com_servico ? 1 : 0
  provider = google-beta
  site_id  = google_firebase_hosting_site.curto[0].site_id

  config {
    redirects {
      regex       = "^/(.*)$"
      status_code = 302
      location    = "${google_cloud_run_v2_service.site[0].uri}/:1"
    }
  }
}

resource "google_firebase_hosting_release" "curto" {
  count        = local.com_servico ? 1 : 0
  provider     = google-beta
  site_id      = google_firebase_hosting_site.curto[0].site_id
  version_name = google_firebase_hosting_version.curto[0].name
  message      = "link curto da demo"
}
