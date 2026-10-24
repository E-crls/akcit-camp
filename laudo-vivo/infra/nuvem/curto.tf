# Link curto do QR: <site_curto>.web.app (Firebase Hosting, grátis). A página do produto fica em /site/ no próprio domínio;
# o resto redireciona (302) para a demo no Cloud Run, onde ficam a sessão, o cookie e a senha.

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

# O conteúdo e o redirecionamento (versão e release do Hosting) são publicados por publicar_site.py: a página do
# produto vai como arquivo estático e o resto redireciona para a demo.
