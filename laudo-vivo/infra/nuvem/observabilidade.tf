# Observabilidade e custo, sem nada para manter:
#
# - O app imprime uma linha JSON por evento ({"laudo_evento": ..., ...}); o Cloud Logging guarda e as métricas
#   de log abaixo contam (acessos, turnos, falas, assinaturas, selos, recusas por limite, erros) e somam
#   (tokens e custo estimado do Gemini, segundos de áudio).
# - O painel do Cloud Monitoring junta essas métricas às do próprio Cloud Run (requisições, latência,
#   instâncias, tempo faturável e o custo estimado dele).
# - O orçamento manda alerta por e-mail aos administradores da conta. Ele não corta o gasto: o teto real é o
#   max de 1 instância no Cloud Run e o teto diário de tokens no app.

locals {
  filtro_servico = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${var.nome}\"",
  ])

  # métricas de log que somam um campo numérico (distribuição)
  somas = {
    laudo_llm_tokens = {
      descricao = "Tokens do LLM por chamada (entrada + saída)"
      evento    = "llm"
      campo     = "tokens"
      escala    = 1
    }
    laudo_llm_custo_usd = {
      descricao = "Custo estimado do LLM por chamada, em US$ (tabela de preço no provedor)"
      evento    = "llm"
      campo     = "custo_usd"
      escala    = 0.000001
    }
    laudo_asr_audio_s = {
      descricao = "Segundos de áudio transcritos por fala"
      evento    = "asr"
      campo     = "audio_s"
      escala    = 0.5
    }
  }
}

resource "google_logging_metric" "eventos" {
  name        = "laudo_eventos"
  description = "Eventos da demo pública (sessão nova, turno, fala, upload, assinatura, selo, recusa, erro, llm)"
  filter      = "${local.filtro_servico} AND jsonPayload.laudo_evento:*"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key        = "evento"
      value_type = "STRING"
    }
    labels {
      key         = "detalhe"
      value_type  = "STRING"
      description = "canal do turno, provedor do LLM, tipo do upload, limite atingido ou código do erro"
    }
  }

  label_extractors = {
    evento  = "EXTRACT(jsonPayload.laudo_evento)"
    detalhe = "EXTRACT(jsonPayload.detalhe)"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "somas" {
  for_each = local.somas

  name        = each.key
  description = each.value.descricao
  filter      = "${local.filtro_servico} AND jsonPayload.laudo_evento=\"${each.value.evento}\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "1"
    labels {
      key        = "detalhe"
      value_type = "STRING"
    }
  }

  value_extractor = "EXTRACT(jsonPayload.${each.value.campo})"
  label_extractors = {
    detalhe = "EXTRACT(jsonPayload.detalhe)"
  }

  bucket_options {
    exponential_buckets {
      num_finite_buckets = 24
      growth_factor      = 2
      scale              = each.value.escala
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_dashboard" "painel" {
  dashboard_json = templatefile("${path.module}/painel.json.tftpl", {
    nome      = var.nome
    cpu       = tonumber(var.cpu)
    memoria   = tonumber(trimsuffix(var.memoria, "Gi"))
    preco_cpu = var.preco_vcpu_s
    preco_mem = var.preco_gib_s
  })

  depends_on = [google_logging_metric.eventos, google_logging_metric.somas]
}

resource "google_billing_budget" "demo" {
  billing_account = var.conta_faturamento
  display_name    = "${var.nome} (projeto ${var.projeto})"

  budget_filter {
    projects = ["projects/${data.google_project.atual.number}"]
  }

  amount {
    specified_amount {
      currency_code = "BRL"
      units         = tostring(var.orcamento_brl)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  depends_on = [google_project_service.apis]
}
