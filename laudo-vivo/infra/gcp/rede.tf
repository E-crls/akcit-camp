# Rede privada: a API sai pela VPC (Direct VPC egress, todo o tráfego), fala com o servidor do modelo só por
# endereço interno e chega às APIs do Google pelo Private Google Access. A saída para a internet (catálogo
# STAC e imagens Sentinel-2, instalação do Ollama na VM) passa pelo Cloud NAT, com IP de saída do projeto.

resource "google_compute_network" "vpc" {
  name                    = "${var.prefixo}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "principal" {
  name                     = "${var.prefixo}-${var.regiao}"
  region                   = var.regiao
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.cidr_subrede
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.2
    metadata             = "EXCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "principal" {
  name    = "${var.prefixo}-roteador"
  region  = var.regiao
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "principal" {
  name                               = "${var.prefixo}-nat"
  region                             = var.regiao
  router                             = google_compute_router.principal.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Servidor do modelo na VM: só a API (tag de rede da saída Direct VPC) chega à porta do Ollama.
resource "google_compute_firewall" "api_para_modelo" {
  count = local.modelo_gce ? 1 : 0

  name        = "${var.prefixo}-api-para-modelo"
  network     = google_compute_network.vpc.id
  direction   = "INGRESS"
  priority    = 1000
  source_tags = [local.rede_tag_api]
  target_tags = [local.rede_tag_vm]

  allow {
    protocol = "tcp"
    ports    = [tostring(local.porta_modelo)]
  }
}

# Administração da VM pelo túnel do IAP (faixa publicada pelo Google para o IAP TCP forwarding).
resource "google_compute_firewall" "ssh_iap" {
  count = local.modelo_gce && var.ssh_via_iap ? 1 : 0

  name          = "${var.prefixo}-ssh-iap"
  network       = google_compute_network.vpc.id
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [local.rede_tag_vm]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
