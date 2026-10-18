# Artifact Registry, na região dos dados:
# - "<prefixo>-imagens": a imagem da API e da interface, construída com o Dockerfile do repositório;
# - "<prefixo>-dockerhub": repositório remoto (cache) do Docker Hub para as imagens de terceiros fixadas por
#   versão (Envoy, Ollama, CLI gcloud). O Cloud Run puxa tudo de dentro do projeto.

resource "google_artifact_registry_repository" "imagens" {
  repository_id = "${var.prefixo}-imagens"
  location      = var.regiao
  format        = "DOCKER"
  description   = "Imagens do Laudo Vivo (API e interface)"

  docker_config {
    immutable_tags = true
  }

  cleanup_policies {
    id     = "manter-recentes"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "dockerhub" {
  repository_id = "${var.prefixo}-dockerhub"
  location      = var.regiao
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"
  description   = "Cache do Docker Hub para as imagens de terceiros fixadas por versão"

  remote_repository_config {
    description = "Docker Hub"
    docker_repository {
      public_repository = "DOCKER_HUB"
    }
  }

  depends_on = [google_project_service.apis]
}

# O agente de serviço do Cloud Run puxa as imagens dos dois repositórios.
resource "google_artifact_registry_repository_iam_member" "leitura_cloud_run" {
  for_each = {
    imagens   = google_artifact_registry_repository.imagens.name
    dockerhub = google_artifact_registry_repository.dockerhub.name
  }

  location   = var.regiao
  repository = each.value
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${local.agente_cloud_run}"
}
