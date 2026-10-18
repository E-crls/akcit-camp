# Versões do Terraform e dos provedores.
# 1.11 ou mais nova: o sal da instalação e o PIN vão ao Secret Manager por atributo "write-only"
# (secret_data_wo), gerados por recurso efêmero, e não ficam gravados no state.
terraform {
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 8.4, < 9.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.7, < 4.0"
    }
  }
}
