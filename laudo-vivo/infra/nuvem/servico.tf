# O site: Cloud Run sem GPU, público, com teto de instâncias. Só existe depois que há imagem (var.imagem).

locals {
  com_servico = var.imagem != ""
}

resource "google_cloud_run_v2_service" "site" {
  count = local.com_servico ? 1 : 0

  name                = var.nome
  location            = var.regiao
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    labels                           = local.rotulos
    service_account                  = google_service_account.servico.email
    timeout                          = "300s"
    max_instance_request_concurrency = var.concorrencia
    # As cópias da fiscalização de cada visitante ficam na memória: o mesmo visitante volta à mesma instância.
    session_affinity      = true
    execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = var.instancias_minimas
      max_instance_count = var.instancias_maximas
    }

    containers {
      image = var.imagem

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memoria
        }
        # Cobrança por requisição: sem acesso, a CPU não é cobrada.
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "LAUDO_DEMO_PUBLICA"
        value = "1"
      }
      env {
        name  = "LAUDO_VERTEX_PROJETO"
        value = var.projeto
      }
      env {
        name  = "LAUDO_VERTEX_LOCAL"
        value = var.local_gemini
      }
      env {
        name  = "LAUDO_VERTEX_MODELO"
        value = var.modelo_gemini
      }
      env {
        name  = "LAUDO_LLM_TOKENS_DIA"
        value = tostring(var.tokens_llm_por_dia)
      }
      env {
        name  = "LAUDO_LLM_TOKENS_HORA"
        value = tostring(var.tokens_llm_por_hora)
      }
      env {
        name  = "LAUDO_VERTEX_TIMEOUT_S"
        value = tostring(var.timeout_gemini_s)
      }
      env {
        name  = "LAUDO_CONTATO_BUCKET"
        value = google_storage_bucket.contatos.name
      }
      dynamic "env" {
        for_each = var.senha_demo != "" ? [1] : []
        content {
          name  = "LAUDO_DEMO_SENHA"
          value = var.senha_demo
        }
      }

      startup_probe {
        http_get {
          path = "/api/saude"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 48
      }
    }
  }

  depends_on = [google_project_iam_member.servico]
}

# Público: quem tem o link (QR code no slide) usa sem login.
resource "google_cloud_run_v2_service_iam_member" "publico" {
  count = local.com_servico ? 1 : 0

  location = google_cloud_run_v2_service.site[0].location
  name     = google_cloud_run_v2_service.site[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Disponibilidade: de 3 regiões a cada 5 min. Além de alimentar o painel, mantém uma instância aquecida (a
# chamada a /api/saude leva milissegundos e, com cobrança por requisição, o custo é desprezível).
resource "google_monitoring_uptime_check_config" "saude" {
  count = local.com_servico ? 1 : 0

  display_name     = "${var.nome} /api/saude"
  timeout          = "10s"
  period           = var.intervalo_verificacao
  selected_regions = ["SOUTH_AMERICA", "USA_VIRGINIA", "EUROPE"]
  user_labels      = local.rotulos

  http_check {
    path         = "/api/saude"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.projeto
      host       = trimprefix(google_cloud_run_v2_service.site[0].uri, "https://")
    }
  }
}
