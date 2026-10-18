provider "google" {
  project = var.projeto
  region  = var.regiao

  # O orçamento (Cloud Billing Budget API) exige projeto de cota quando a credencial é de usuário (ADC).
  user_project_override = true
  billing_project       = var.projeto

  default_labels = local.labels
}
