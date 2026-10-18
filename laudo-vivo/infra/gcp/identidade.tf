# Contas de serviço, uma por papel, com o mínimo de permissão (no recurso, não no projeto, sempre que dá).
#
# | Conta        | Faz                                  | Pode                                              |
# |--------------|--------------------------------------|---------------------------------------------------|
# | api          | API e interface                      | ler e gravar dados e cofre; ler sal e PIN;        |
# |              |                                      | invocar o modelo (cloud_run); escrever logs       |
# | modelo       | servidor do modelo (Cloud Run ou VM) | ler os pesos do modelo (cloud_run); logs          |
# | expurgo      | job de expurgo LGPD                  | ler e gravar dados e cofre; ler o sal             |
# | arquivamento | job que copia os pacotes selados     | ler dados; criar no arquivo (sem apagar)          |
# | carga-modelo | job que baixa o modelo (cloud_run)   | gravar no bucket de modelos                       |
# | agendador    | Cloud Scheduler                      | disparar os dois jobs                             |

resource "google_service_account" "api" {
  account_id   = "${var.prefixo}-api"
  display_name = "Laudo Vivo: API e interface"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "modelo" {
  account_id   = "${var.prefixo}-modelo"
  display_name = "Laudo Vivo: servidor do modelo"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "expurgo" {
  account_id   = "${var.prefixo}-expurgo"
  display_name = "Laudo Vivo: expurgo LGPD (crypto-shredding)"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "arquivamento" {
  account_id   = "${var.prefixo}-arquivamento"
  display_name = "Laudo Vivo: arquivamento dos pacotes selados"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "carga_modelo" {
  count = local.modelo_cloud_run ? 1 : 0

  account_id   = "${var.prefixo}-carga-modelo"
  display_name = "Laudo Vivo: carga dos pesos do modelo"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "agendador" {
  account_id   = "${var.prefixo}-agendador"
  display_name = "Laudo Vivo: agendamento dos jobs"

  depends_on = [google_project_service.apis]
}

locals {
  sa_api          = "serviceAccount:${google_service_account.api.email}"
  sa_modelo       = "serviceAccount:${google_service_account.modelo.email}"
  sa_expurgo      = "serviceAccount:${google_service_account.expurgo.email}"
  sa_arquivamento = "serviceAccount:${google_service_account.arquivamento.email}"
  sa_agendador    = "serviceAccount:${google_service_account.agendador.email}"
}

# Logs, métricas e trace das requisições: papéis de escrita, no projeto (não há recurso mais estreito).
resource "google_project_iam_member" "escrita_observabilidade" {
  for_each = {
    for par in setproduct(
      ["api", "modelo", "expurgo", "arquivamento"],
      ["roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"],
    ) : "${par[0]}|${par[1]}" => par
  }

  project = var.projeto
  role    = each.value[1]
  member = {
    api          = local.sa_api
    modelo       = local.sa_modelo
    expurgo      = local.sa_expurgo
    arquivamento = local.sa_arquivamento
  }[each.value[0]]
}

# Dados e cofre: a API e o expurgo leem e gravam objetos (sem administrar o bucket).
resource "google_storage_bucket_iam_member" "dados_api" {
  bucket = google_storage_bucket.dados.name
  role   = "roles/storage.objectUser"
  member = local.sa_api
}

resource "google_storage_bucket_iam_member" "cofre_api" {
  bucket = google_storage_bucket.cofre.name
  role   = "roles/storage.objectUser"
  member = local.sa_api
}

resource "google_storage_bucket_iam_member" "dados_expurgo" {
  bucket = google_storage_bucket.dados.name
  role   = "roles/storage.objectUser"
  member = local.sa_expurgo
}

resource "google_storage_bucket_iam_member" "cofre_expurgo" {
  bucket = google_storage_bucket.cofre.name
  role   = "roles/storage.objectUser"
  member = local.sa_expurgo
}

# Arquivamento: lê os dados; no arquivo, lista e cria, mas não apaga nem sobrescreve.
resource "google_storage_bucket_iam_member" "dados_arquivamento" {
  bucket = google_storage_bucket.dados.name
  role   = "roles/storage.objectViewer"
  member = local.sa_arquivamento
}

resource "google_storage_bucket_iam_member" "arquivo_leitura" {
  bucket = google_storage_bucket.arquivo.name
  role   = "roles/storage.objectViewer"
  member = local.sa_arquivamento
}

resource "google_storage_bucket_iam_member" "arquivo_criacao" {
  bucket = google_storage_bucket.arquivo.name
  role   = "roles/storage.objectCreator"
  member = local.sa_arquivamento
}

# Pesos do modelo: o serviço de modelo só lê; o job de carga grava.
resource "google_storage_bucket_iam_member" "modelos_leitura" {
  count = local.modelo_cloud_run ? 1 : 0

  bucket = google_storage_bucket.modelos[0].name
  role   = "roles/storage.objectViewer"
  member = local.sa_modelo
}

resource "google_storage_bucket_iam_member" "modelos_carga" {
  count = local.modelo_cloud_run ? 1 : 0

  bucket = google_storage_bucket.modelos[0].name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.carga_modelo[0].email}"
}
