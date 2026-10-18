output "url_api" {
  description = "Endereço da interface e da API (HTTPS; com acesso iap, abre com login Google)."
  value       = google_cloud_run_v2_service.api.uri
}

output "repositorio_imagens" {
  description = "Repositório para o docker push da imagem da API (ver README)."
  value       = "${local.registro}/${google_artifact_registry_repository.imagens.repository_id}"
}

output "imagem_api" {
  description = "Imagem que o serviço da API e o job de expurgo usam."
  value       = local.imagem_api
}

output "bucket_dados" {
  description = "Bucket do estado, da trilha, das evidências e dos laudos (prefixo api/) e do cache (cache/)."
  value       = google_storage_bucket.dados.name
}

output "bucket_cofre" {
  description = "Bucket das chaves por fiscalização do cofre (crypto-shredding)."
  value       = google_storage_bucket.cofre.name
}

output "bucket_arquivo" {
  description = "Bucket de arquivo dos pacotes de exibição dos laudos selados."
  value       = google_storage_bucket.arquivo.name
}

output "chave_kms_dados" {
  description = "Chave do Cloud KMS dos buckets de dados e de arquivo."
  value       = google_kms_crypto_key.dados.id
}

output "chave_kms_cofre" {
  description = "Chave do Cloud KMS do bucket do cofre."
  value       = google_kms_crypto_key.cofre.id
}

output "servidor_modelo" {
  description = "Onde o modelo roda e o endereço interno dele (a API chega por 127.0.0.1:11434, pela borda)."
  value = {
    modo     = var.servidor_modelo
    endereco = local.host_modelo
    regiao   = local.modelo_cloud_run ? local.regiao_modelo : var.regiao
    zona     = local.modelo_gce ? local.gce_zona : null
  }
}

output "conta_servico_api" {
  description = "Conta de serviço da API."
  value       = google_service_account.api.email
}

output "comando_ler_pin" {
  description = "Comando para ler o PIN da assinatura no Secret Manager (o valor não fica no state)."
  value = join(" ", [
    "gcloud secrets versions access latest",
    "--secret=${google_secret_manager_secret.pin.secret_id} --project=${var.projeto}",
  ])
}

output "comando_carregar_modelo" {
  description = "No modo cloud_run, baixa os pesos do modelo para o bucket (uma vez, depois do apply)."
  value = local.modelo_cloud_run ? join(" ", [
    "gcloud run jobs execute ${google_cloud_run_v2_job.carga_modelo[0].name}",
    "--region=${local.regiao_modelo} --project=${var.projeto} --wait",
  ]) : null
}

output "comando_expurgo_manual" {
  description = "Roda o expurgo agora (o agendamento roda todo dia)."
  value = join(" ", [
    "gcloud run jobs execute ${google_cloud_run_v2_job.expurgo.name}",
    "--region=${var.regiao} --project=${var.projeto} --wait",
  ])
}
