provider "google" {
  project = var.projeto
  region  = var.regiao

  # O orçamento (Cloud Billing Budget API) exige projeto de cota quando a credencial é de usuário.
  user_project_override = true
  billing_project       = var.projeto

  # Etiqueta de custo em todo recurso que aceita rótulo: o relatório de faturamento filtra por elas.
  default_labels = local.rotulos
}
