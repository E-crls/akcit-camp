# Implantação gerenciada do Laudo Vivo no Google Cloud: valores derivados, APIs e dados do projeto.
# O mesmo produto da máquina da cooperativa (laudo.api + Ollama), com os arquivos de dados em Cloud Storage,
# as chaves no Cloud KMS e os segredos no Secret Manager. Ver README.md desta pasta.

locals {
  labels = merge(
    {
      produto        = "laudo-vivo"
      ambiente       = var.ambiente
      gerenciado-por = "terraform"
    },
    var.labels,
  )

  modelo_cloud_run = var.servidor_modelo == "cloud_run"
  modelo_gce       = var.servidor_modelo == "gce"
  tem_modelo       = var.servidor_modelo != "nenhum"
  regiao_modelo    = coalesce(var.regiao_modelo, var.regiao)
  gce_zona         = coalesce(var.gce_zona, "${var.regiao}-a")
  modo_llm         = coalesce(var.modo_llm, local.tem_modelo ? "ollama" : "replay")

  # Nomes globais (buckets) levam o ID do projeto para não colidir com outros projetos.
  nome_global = "${var.prefixo}-${var.projeto}"

  # Imagens: a da API no repositório padrão do projeto; as de terceiros pelo repositório remoto
  # (cache do Docker Hub dentro do projeto, na região dos dados).
  registro = "${var.regiao}-docker.pkg.dev/${var.projeto}"
  imagem_api = coalesce(
    var.imagem_api,
    "${local.registro}/${var.prefixo}-imagens/laudo-vivo:${var.imagem_api_tag}",
  )
  imagem_borda  = "${local.registro}/${var.prefixo}-dockerhub/${var.imagem_borda}"
  imagem_ollama = "${local.registro}/${var.prefixo}-dockerhub/${var.imagem_ollama}"
  imagem_gcloud = "${local.registro}/${var.prefixo}-dockerhub/${var.imagem_gcloud}"
  rede_tag_api  = "${var.prefixo}-api"
  rede_tag_vm   = "${var.prefixo}-modelo"
  porta_modelo  = 11434
  porta_api     = 8000
  porta_entrada = 8080
  dir_dados_api = "/dados/api"
  dir_config    = "/config"
  dir_cache     = "/cache"
  pastas_estado = [
    "fiscalizacoes", "ui", "traces", "laudos", "evidencias", "audio", "indices", "gravacoes",
  ]
  opcoes_dono      = var.api_uid == null ? [] : ["uid=${var.api_uid}", "gid=${var.api_uid}"]
  nome_api         = "${var.prefixo}-api"
  nome_modelo      = "${var.prefixo}-modelo"
  dias_em_segundos = 86400

  apis = concat(
    [
      "artifactregistry.googleapis.com",
      "cloudkms.googleapis.com",
      "cloudresourcemanager.googleapis.com",
      "cloudscheduler.googleapis.com",
      "cloudtrace.googleapis.com",
      "compute.googleapis.com",
      "iam.googleapis.com",
      "logging.googleapis.com",
      "monitoring.googleapis.com",
      "run.googleapis.com",
      "secretmanager.googleapis.com",
      "storage.googleapis.com",
    ],
    var.acesso_api == "iap" ? ["iap.googleapis.com"] : [],
    local.criar_orcamento ? ["billingbudgets.googleapis.com"] : [],
  )

  criar_orcamento = var.conta_faturamento != null && var.orcamento_mensal > 0
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  project            = var.projeto
  service            = each.value
  disable_on_destroy = false
}

data "google_project" "atual" {
  project_id = var.projeto

  depends_on = [google_project_service.apis]
}

# Agentes de serviço do Google que recebem permissão aqui (Cloud Run, Compute Engine e IAP).
locals {
  numero_projeto   = data.google_project.atual.number
  agente_cloud_run = "service-${local.numero_projeto}@serverless-robot-prod.iam.gserviceaccount.com"
  agente_compute   = "service-${local.numero_projeto}@compute-system.iam.gserviceaccount.com"
  agente_iap       = "service-${local.numero_projeto}@gcp-sa-iap.iam.gserviceaccount.com"
}

# Agente de serviço do Cloud Storage (precisa da chave do KMS para a CMEK dos buckets).
data "google_storage_project_service_account" "gcs" {
  project = var.projeto

  depends_on = [google_project_service.apis]
}

check "zona_do_modelo_na_regiao_dos_dados" {
  assert {
    condition     = !local.modelo_gce || startswith(local.gce_zona, "${var.regiao}-")
    error_message = "No modo gce, a VM do modelo fica na região dos dados: use uma zona de var.regiao."
  }
}

check "replay_exige_caso_gravado" {
  assert {
    condition     = local.modo_llm != "replay" || var.caso_demo == "DEMO-0001"
    error_message = "O modo replay (sem servidor de modelo) só tem gravação para o caso DEMO-0001."
  }
}
