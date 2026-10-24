# Versões do Terraform e do provedor.
terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.20, < 9.0"
    }
  }
}
