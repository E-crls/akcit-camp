output "url" {
  description = "Endereço público da demo (vai no QR code)"
  value       = local.com_servico ? google_cloud_run_v2_service.site[0].uri : ""
}

output "repositorio" {
  description = "Prefixo das imagens no Artifact Registry"
  value       = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.imagens.repository_id}"
}

output "bucket_fontes" {
  value = google_storage_bucket.fontes.name
}

output "conta_build" {
  value = google_service_account.build.id
}

output "painel" {
  description = "Painel de acessos e custos no Cloud Monitoring"
  value       = "https://console.cloud.google.com/monitoring/dashboards/builder/${element(split("/", google_monitoring_dashboard.painel.id), 3)}?project=${var.projeto}"
}

output "url_curta" {
  description = "Link curto (vai no QR): redireciona para a demo"
  value       = local.com_servico ? "https://${google_firebase_hosting_site.curto[0].site_id}.web.app" : ""
}
