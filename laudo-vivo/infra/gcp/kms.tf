# Cloud KMS: chaves de criptografia gerenciadas pela instituição (CMEK), na região dos dados.
#
# - "dados": cifra em repouso o bucket de dados (estado, trilha, evidências, laudos) e o de arquivo.
# - "cofre": cifra o bucket das chaves por fiscalização do cofre (src/laudo/audit/cofre.py), separado
#   dos dados.
#   O expurgo de uma fiscalização apaga a chave dela nesse bucket (crypto-shredding); destruir as versões
#   desta chave do KMS torna ilegíveis todas as chaves do cofre de uma vez (encerramento da instalação).
#
# Chaves do KMS não são apagadas pelo terraform destroy (o recurso sai do state; as versões podem ser
# destruídas à parte, com o prazo de destroy_scheduled_duration).

resource "google_kms_key_ring" "laudo" {
  name     = "${var.prefixo}-chaves"
  location = var.regiao

  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "dados" {
  name            = "dados"
  key_ring        = google_kms_key_ring.laudo.id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = var.kms_rotacao

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = var.kms_nivel_protecao
  }
}

resource "google_kms_crypto_key" "cofre" {
  name            = "cofre"
  key_ring        = google_kms_key_ring.laudo.id
  purpose         = "ENCRYPT_DECRYPT"
  rotation_period = var.kms_rotacao

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = var.kms_nivel_protecao
  }
}

# O agente de serviço do Cloud Storage usa as chaves para cifrar e decifrar os objetos dos buckets.
resource "google_kms_crypto_key_iam_member" "gcs_dados" {
  crypto_key_id = google_kms_crypto_key.dados.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_kms_crypto_key_iam_member" "gcs_cofre" {
  crypto_key_id = google_kms_crypto_key.cofre.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}
