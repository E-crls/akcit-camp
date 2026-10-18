# Servidor do modelo (Ollama com qwen3.5:4b), só com acesso interno. Duas formas, pela variável
# servidor_modelo:
#
# - gce (padrão): VM com GPU numa zona da região dos dados, sem IP público, ligada e desligada por agenda.
#   Só a API chega à porta do Ollama (regra de firewall pela tag de rede da saída Direct VPC).
# - cloud_run: serviço do Cloud Run com GPU, escala a zero, ingress só interno e invocação só pela conta de
#   serviço da API (a borda da API põe o token de identidade). Os pesos ficam num bucket montado só leitura e
#   são baixados uma vez pelo job "<prefixo>-carga-modelo".
#
# O condutor (OLLAMA_HOST) e a leitura de foto falam com http://127.0.0.1:11434 dentro da instância da API;
# a borda leva essas chamadas ao servidor escolhido aqui.

# --- modo cloud_run --------------------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "modelo" {
  count = local.modelo_cloud_run ? 1 : 0

  name                = local.nome_modelo
  location            = local.regiao_modelo
  description         = "Laudo Vivo: servidor do modelo (Ollama) com GPU"
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.protecao_exclusao

  template {
    service_account                  = google_service_account.modelo.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    timeout                          = var.api_timeout
    max_instance_request_concurrency = 4
    gpu_zonal_redundancy_disabled    = var.modelo_sem_redundancia_zonal

    scaling {
      min_instance_count = 0
      max_instance_count = var.modelo_max_instancias
    }

    node_selector {
      accelerator = var.modelo_gpu
    }

    containers {
      name  = "ollama"
      image = local.imagem_ollama

      ports {
        container_port = local.porta_modelo
      }

      env {
        name  = "OLLAMA_HOST"
        value = "0.0.0.0:${local.porta_modelo}"
      }
      env {
        name  = "OLLAMA_MODELS"
        value = "/modelos"
      }
      env {
        name  = "OLLAMA_KEEP_ALIVE"
        value = "-1"
      }
      env {
        name  = "OLLAMA_NOPRUNE"
        value = "true"
      }

      resources {
        limits = {
          cpu              = var.modelo_cpu
          memory           = var.modelo_memoria
          "nvidia.com/gpu" = "1"
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      startup_probe {
        period_seconds    = 5
        failure_threshold = 36
        tcp_socket {
          port = local.porta_modelo
        }
      }

      volume_mounts {
        name       = "modelos"
        mount_path = "/modelos"
      }
    }

    volumes {
      name = "modelos"
      gcs {
        bucket    = google_storage_bucket.modelos[0].name
        read_only = true
      }
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.modelos_leitura,
    google_artifact_registry_repository_iam_member.leitura_cloud_run,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "api_invoca_modelo" {
  count = local.modelo_cloud_run ? 1 : 0

  name     = google_cloud_run_v2_service.modelo[0].name
  location = local.regiao_modelo
  role     = "roles/run.invoker"
  member   = local.sa_api
}

# Baixa os pesos do modelo para o bucket (rodar uma vez depois do apply; ver README).
resource "google_cloud_run_v2_job" "carga_modelo" {
  count = local.modelo_cloud_run ? 1 : 0

  name                = "${var.prefixo}-carga-modelo"
  location            = local.regiao_modelo
  deletion_protection = var.protecao_exclusao

  template {
    task_count = 1

    template {
      service_account       = google_service_account.carga_modelo[0].email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = "3600s"
      max_retries           = 1

      containers {
        image   = local.imagem_ollama
        command = ["/bin/sh", "-c"]
        args = [join(" ", [
          "ollama serve & until ollama list >/dev/null 2>&1; do sleep 1; done;",
          "ollama pull ${var.modelo_llm} && ollama list",
        ])]

        env {
          name  = "OLLAMA_MODELS"
          value = "/modelos"
        }

        resources {
          limits = {
            cpu    = "2"
            memory = "8Gi"
          }
        }

        volume_mounts {
          name       = "modelos"
          mount_path = "/modelos"
        }
      }

      volumes {
        name = "modelos"
        gcs {
          bucket    = google_storage_bucket.modelos[0].name
          read_only = false
        }
      }
    }
  }

  depends_on = [
    google_storage_bucket_iam_member.modelos_carga,
    google_artifact_registry_repository_iam_member.leitura_cloud_run,
  ]
}

# --- modo gce --------------------------------------------------------------------------------------------

resource "google_compute_address" "modelo" {
  count = local.modelo_gce ? 1 : 0

  name         = "${local.nome_modelo}-interno"
  region       = var.regiao
  subnetwork   = google_compute_subnetwork.principal.id
  address_type = "INTERNAL"
}

# Agenda de liga/desliga: o agente de serviço do Compute Engine precisa poder iniciar e parar a VM.
resource "google_project_iam_member" "agenda_compute" {
  count = local.modelo_gce && var.gce_agenda != null ? 1 : 0

  project = var.projeto
  role    = "roles/compute.instanceAdmin.v1"
  member  = "serviceAccount:${local.agente_compute}"
}

resource "google_compute_resource_policy" "agenda_modelo" {
  count = local.modelo_gce && var.gce_agenda != null ? 1 : 0

  name        = "${local.nome_modelo}-agenda"
  region      = var.regiao
  description = "Liga e desliga a VM do modelo na jornada da equipe de campo"

  instance_schedule_policy {
    time_zone = var.fuso
    vm_start_schedule {
      schedule = var.gce_agenda.ligar
    }
    vm_stop_schedule {
      schedule = var.gce_agenda.desligar
    }
  }

  depends_on = [google_project_iam_member.agenda_compute]
}

resource "google_compute_instance" "modelo" {
  count = local.modelo_gce ? 1 : 0

  name                      = local.nome_modelo
  zone                      = local.gce_zona
  machine_type              = var.gce_tipo_maquina
  tags                      = [local.rede_tag_vm]
  allow_stopping_for_update = true
  deletion_protection       = var.protecao_exclusao
  resource_policies         = google_compute_resource_policy.agenda_modelo[*].self_link

  boot_disk {
    initialize_params {
      image = var.gce_imagem
      size  = var.gce_disco_gb
      type  = "pd-balanced"
    }
  }

  # Sem access_config: sem IP público. A instalação sai pelo Cloud NAT.
  network_interface {
    subnetwork = google_compute_subnetwork.principal.id
    network_ip = google_compute_address.modelo[0].address
  }

  guest_accelerator {
    type  = var.gce_acelerador
    count = 1
  }

  scheduling {
    on_host_maintenance         = "TERMINATE"
    automatic_restart           = !var.gce_spot
    preemptible                 = var.gce_spot
    provisioning_model          = var.gce_spot ? "SPOT" : "STANDARD"
    instance_termination_action = var.gce_spot ? "STOP" : null
  }

  # O driver NVIDIA compilado pelo instalador não é assinado: inicialização segura desligada.
  shielded_instance_config {
    enable_secure_boot          = false
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  service_account {
    email  = google_service_account.modelo.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
    startup-script = templatefile("${path.module}/modelos/ollama-vm.sh.tftpl", {
      versao_ollama = var.ollama_versao
      modelo        = var.modelo_llm
      porta         = local.porta_modelo
    })
  }

  depends_on = [google_compute_router_nat.principal]
}
