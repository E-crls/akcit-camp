# Observabilidade e custo.
#
# - Logs: o Cloud Run e a VM mandam stdout/stderr ao Cloud Logging; aqui eles vão para um bucket de logs na
#   região dos dados, com retenção própria, e saem do bucket _Default (global).
# - Trace: o Cloud Run registra no Cloud Trace o trace das requisições. A trilha de auditoria do produto
#   continua sendo o trace OpenTelemetry por fiscalização (JSONL com máscara de PII e cadeia de hash, em
#   api/traces/ no bucket de dados), que o laudo e o pacote de exibição citam por span_id.
# - Orçamento: alerta de gasto do projeto (opcional), com limiares de 50%, 90% e 100%.

locals {
  filtro_logs = join(" OR ", [
    "(resource.type=\"cloud_run_revision\" AND resource.labels.service_name=~\"^${var.prefixo}-\")",
    "(resource.type=\"cloud_run_job\" AND resource.labels.job_name=~\"^${var.prefixo}-\")",
    join("", [
      "(resource.type=\"gce_instance\" AND ",
      "labels.\"compute.googleapis.com/resource_name\"=\"${local.nome_modelo}\")",
    ]),
  ])
}

resource "google_logging_project_bucket_config" "regional" {
  count = var.logs_regionais ? 1 : 0

  project        = var.projeto
  location       = var.regiao
  bucket_id      = "${var.prefixo}-logs"
  retention_days = var.dias_retencao_logs
  description    = "Logs do Laudo Vivo na região dos dados"

  depends_on = [google_project_service.apis]
}

resource "google_logging_project_sink" "regional" {
  count = var.logs_regionais ? 1 : 0

  name                   = "${var.prefixo}-logs-regionais"
  destination            = "logging.googleapis.com/${google_logging_project_bucket_config.regional[0].id}"
  filter                 = local.filtro_logs
  unique_writer_identity = true
}

resource "google_project_iam_member" "sink_escreve_logs" {
  count = var.logs_regionais ? 1 : 0

  project = var.projeto
  role    = "roles/logging.bucketWriter"
  member  = google_logging_project_sink.regional[0].writer_identity
}

resource "google_logging_project_exclusion" "fora_do_default" {
  count = var.logs_regionais && var.excluir_logs_do_default ? 1 : 0

  name        = "${var.prefixo}-fora-do-default"
  description = "Logs do Laudo Vivo ficam só no bucket regional"
  filter      = local.filtro_logs

  depends_on = [google_logging_project_sink.regional]
}

resource "google_billing_budget" "mensal" {
  count = local.criar_orcamento ? 1 : 0

  billing_account = var.conta_faturamento
  display_name    = "Laudo Vivo (${var.projeto})"

  budget_filter {
    projects        = ["projects/${data.google_project.atual.number}"]
    calendar_period = "MONTH"
  }

  amount {
    specified_amount {
      currency_code = var.moeda_orcamento
      units         = tostring(floor(var.orcamento_mensal))
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  depends_on = [google_project_service.apis]
}
