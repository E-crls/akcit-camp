# Cloud Storage: os diretórios de dados do produto, montados na API pelo Cloud Storage FUSE.
#
# | Bucket  | Conteúdo                                                  | Chave KMS | Versões | Retenção |
# |---------|-----------------------------------------------------------|-----------|---------|----------|
# | dados   | estado append-only, trilha (trace), evidências, áudio,    | dados     | sim     | não      |
# |         | laudos, índices de hash (api/) e cache do satélite        |           |         |          |
# | cofre   | uma chave por fiscalização (crypto-shredding)             | cofre     | não     | não      |
# | arquivo | pacotes de exibição dos laudos selados (BCB/Justiça)      | dados     | sim     | opcional |
# | modelos | pesos do modelo (só no modo cloud_run; dado público)      | Google    | não     | não      |
#
# O bucket de dados não tem política de retenção porque a API reescreve o próprio estado (gravação atômica
# por arquivo temporário e renomeação); a guarda imutável fica no bucket de arquivo. O bucket do cofre não
# tem versionamento nem soft delete: apagar a chave de uma fiscalização precisa ser definitivo.

resource "google_storage_bucket" "dados" {
  name                        = "${local.nome_global}-dados"
  location                    = upper(var.regiao)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = var.dias_soft_delete_dados * local.dias_em_segundos
  }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = var.dias_versoes_antigas
      with_state                 = "ARCHIVED"
    }
    action {
      type = "Delete"
    }
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.dados.id
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_dados]
}

resource "google_storage_bucket" "cofre" {
  name                        = "${local.nome_global}-cofre"
  location                    = upper(var.regiao)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = false
  }

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.cofre.id
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_cofre]
}

resource "google_storage_bucket" "arquivo" {
  name                        = "${local.nome_global}-arquivo"
  location                    = upper(var.regiao)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  dynamic "retention_policy" {
    for_each = var.dias_retencao_arquivo > 0 ? [1] : []
    content {
      retention_period = tostring(var.dias_retencao_arquivo * local.dias_em_segundos)
      is_locked        = var.travar_retencao_arquivo
    }
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.dados.id
  }

  depends_on = [google_kms_crypto_key_iam_member.gcs_dados]
}

resource "google_storage_bucket" "modelos" {
  count = local.modelo_cloud_run ? 1 : 0

  name                        = "${local.nome_global}-modelos"
  location                    = upper(local.regiao_modelo)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  depends_on = [google_project_service.apis]
}
