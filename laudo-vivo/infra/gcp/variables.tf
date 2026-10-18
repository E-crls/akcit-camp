# Variáveis da implantação gerenciada do Laudo Vivo no Google Cloud.
# Valores de exemplo comentados em terraform.tfvars.example; o README desta pasta explica cada decisão.

# ---------------------------------------------------------------------------------------------------------
# Projeto, região e nomes
# ---------------------------------------------------------------------------------------------------------

variable "projeto" {
  description = "ID do projeto do Google Cloud dedicado ao Laudo Vivo da instituição (um por instalação)."
  type        = string
}

variable "regiao" {
  description = <<-EOT
    Região dos dados e da API. Padrão São Paulo (southamerica-east1): evidências, laudos, chaves, segredos e
    logs ficam no Brasil (LGPD e sigilo bancário).
  EOT
  type        = string
  default     = "southamerica-east1"
}

variable "prefixo" {
  description = "Prefixo dos nomes dos recursos (minúsculas, dígitos e hífen; 2 a 15 caracteres)."
  type        = string
  default     = "laudo"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,14}$", var.prefixo))
    error_message = "Use de 2 a 15 caracteres: minúsculas, dígitos e hífen, começando por letra."
  }
}

variable "ambiente" {
  description = "Nome do ambiente, vai no label 'ambiente' de todos os recursos (ex.: producao, homologacao)."
  type        = string
  default     = "producao"
}

variable "labels" {
  description = "Labels extras aplicados a todos os recursos (ex.: centro de custo da cooperativa)."
  type        = map(string)
  default     = {}
}

variable "protecao_exclusao" {
  description = <<-EOT
    Proteção contra exclusão acidental dos serviços Cloud Run, dos jobs e dos segredos. Desligue só para
    desmontar um ambiente de homologação.
  EOT
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------------------------------------
# Imagens
# ---------------------------------------------------------------------------------------------------------

variable "imagem_api" {
  description = <<-EOT
    Imagem completa da API e da interface (construída com o Dockerfile do repositório). Se nula, usa
    <regiao>-docker.pkg.dev/<projeto>/<prefixo>-imagens/laudo-vivo:<imagem_api_tag>.
  EOT
  type        = string
  default     = null
}

variable "imagem_api_tag" {
  description = "Tag da imagem da API no Artifact Registry do projeto, quando imagem_api é nula."
  type        = string
  default     = "r4.1"
}

variable "api_comando" {
  description = <<-EOT
    Começo da linha de comando da API e do job de expurgo. Roda pelo ENTRYPOINT da imagem do Dockerfile, que
    ativa o ambiente conda; o resto dos argumentos é montado em api.tf e tarefas.tf.
  EOT
  type        = list(string)
  default     = ["python"]
}

variable "api_diretorio_trabalho" {
  description = <<-EOT
    Diretório de trabalho da imagem da API (a raiz do repositório dentro dela; /app no Dockerfile). Nulo usa
    o WORKDIR da imagem. O job de expurgo roda scripts/expurgo_lgpd.py relativo a ele.
  EOT
  type        = string
  default     = null
}

variable "api_uid" {
  description = <<-EOT
    UID e GID do usuário da imagem da API, donos dos volumes do Cloud Storage (a imagem não roda como root).
    Padrão 57439: o usuário mambauser da imagem base mambaorg/micromamba do Dockerfile. Nulo: dono padrão.
  EOT
  type        = number
  default     = 57439
}

variable "imagem_borda" {
  description = <<-EOT
    Imagem do proxy de borda (Envoy) no Docker Hub, puxada pelo repositório remoto do Artifact Registry.
    Atualize para o patch mais recente da linha antes de aplicar.
  EOT
  type        = string
  default     = "envoyproxy/envoy:v1.39.2"
}

variable "imagem_ollama" {
  description = "Imagem do Ollama no Docker Hub para o modo cloud_run (a mesma do docker-compose.yml)."
  type        = string
  default     = "ollama/ollama:0.32.4"
}

variable "imagem_gcloud" {
  description = "Imagem com a CLI gcloud no Docker Hub, usada pelo job que arquiva os pacotes selados."
  type        = string
  default     = "google/cloud-sdk:587.0.0-slim"
}

# ---------------------------------------------------------------------------------------------------------
# API e interface (Cloud Run)
# ---------------------------------------------------------------------------------------------------------

variable "api_cpu" {
  description = "vCPUs do contêiner da API (ASR, contagem de bovinos e leitura de vídeo rodam em CPU)."
  type        = string
  default     = "4"
}

variable "api_memoria" {
  description = "Memória do contêiner da API."
  type        = string
  default     = "8Gi"
}

variable "api_min_instancias" {
  description = <<-EOT
    Instâncias sempre ligadas da API. 0 escala a zero (paga só pelo uso; a primeira requisição espera a
    subida). 1 elimina essa espera em troca de custo fixo.
  EOT
  type        = number
  default     = 0

  validation {
    condition     = contains([0, 1], var.api_min_instancias)
    error_message = "A API roda com no máximo uma instância (estado em arquivo, escritor único): use 0 ou 1."
  }
}

variable "api_timeout" {
  description = "Tempo máximo de uma requisição (upload e contagem de vídeo longo, turno com o modelo frio)."
  type        = string
  default     = "900s"
}

variable "api_cpu_sempre_alocada" {
  description = "Cobrança por instância (CPU também fora das requisições). Falso: cobrança por requisição."
  type        = bool
  default     = false
}

variable "ferramentas" {
  description = "Ferramentas da API: reais (produção), mistas ou falsas (desenvolvimento)."
  type        = string
  default     = "reais"

  validation {
    condition     = contains(["reais", "mistas", "falsas"], var.ferramentas)
    error_message = "Use reais, mistas ou falsas."
  }
}

variable "caso_demo" {
  description = "Caso aberto pelo botão de demonstração da interface (caso sintético do golden set)."
  type        = string
  default     = "DEMO-0001"
}

variable "perfil" {
  description = "Perfil do agente (campo, escritorio ou lote; ver docs/adr/001-modelo-local.md)."
  type        = string
  default     = "campo"

  validation {
    condition     = contains(["campo", "escritorio", "lote"], var.perfil)
    error_message = "Use campo, escritorio ou lote."
  }
}

variable "asr" {
  description = <<-EOT
    Reconhecimento de fala na API: desligado (fala digitada, como no CMD do Dockerfile) ou cpu (a API não
    tem GPU). cpu exige o faster-whisper e o modelo do Whisper no cache do Hugging Face dentro da imagem.
  EOT
  type        = string
  default     = "desligado"

  validation {
    condition     = contains(["cpu", "desligado"], var.asr)
    error_message = "Use cpu ou desligado."
  }
}

variable "modo_llm" {
  description = <<-EOT
    Modo do condutor: ollama (servidor de modelo desta implantação) ou replay (demonstração gravada, sem GPU).
    Nulo: ollama quando há servidor de modelo; replay quando servidor_modelo = "nenhum".
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.modo_llm == null || contains(["ollama", "replay"], coalesce(var.modo_llm, "ollama"))
    error_message = "Use ollama, replay ou deixe nulo."
  }
}

variable "acesso_api" {
  description = <<-EOT
    Quem abre a interface: iap (login Google pelo Identity-Aware Proxy, para a fiscal no celular) ou iam
    (só chamadas autenticadas com token, para integração entre sistemas).
  EOT
  type        = string
  default     = "iap"

  validation {
    condition     = contains(["iap", "iam"], var.acesso_api)
    error_message = "Use iap ou iam."
  }
}

variable "membros_acesso" {
  description = <<-EOT
    Quem pode abrir a API, no formato do IAM (ex.: "group:fiscais@example.com",
    "user:<seu e-mail>"). Recebe roles/iap.httpsResourceAccessor (iap) ou roles/run.invoker (iam).
  EOT
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------------------------------------
# Servidor do modelo (qwen3.5:4b no Ollama)
# ---------------------------------------------------------------------------------------------------------

variable "servidor_modelo" {
  description = <<-EOT
    Onde roda o modelo: gce (VM com GPU na região dos dados, ligada por agenda), cloud_run (Cloud Run com
    GPU, escala a zero, na região de regiao_modelo) ou nenhum (sem GPU: a API usa a demonstração gravada).
  EOT
  type        = string
  default     = "gce"

  validation {
    condition     = contains(["gce", "cloud_run", "nenhum"], var.servidor_modelo)
    error_message = "Use gce, cloud_run ou nenhum."
  }
}

variable "modelo_llm" {
  description = "Modelo do Ollama usado pelo condutor e pela leitura de foto (o mesmo da máquina da equipe)."
  type        = string
  default     = "qwen3.5:4b"
}

variable "regiao_modelo" {
  description = <<-EOT
    Região do serviço de modelo no modo cloud_run. Nula usa a região dos dados. Confira na documentação do
    Cloud Run (GPU) quais regiões têm a GPU escolhida antes de aplicar: a lista muda e, em 17/10/2026, não
    incluía southamerica-east1. Fora do Brasil, a fala e a foto do documento passam pela região escolhida
    durante a inferência: avalie com o encarregado de dados (LGPD, art. 33) antes de usar.
  EOT
  type        = string
  default     = null
}

variable "modelo_gpu" {
  description = "Acelerador do Cloud Run no modo cloud_run (ex.: nvidia-l4)."
  type        = string
  default     = "nvidia-l4"
}

variable "modelo_cpu" {
  description = "vCPUs do serviço de modelo no Cloud Run (a GPU L4 exige no mínimo 4)."
  type        = string
  default     = "8"
}

variable "modelo_memoria" {
  description = "Memória do serviço de modelo no Cloud Run (a GPU L4 exige no mínimo 16Gi)."
  type        = string
  default     = "32Gi"
}

variable "modelo_max_instancias" {
  description = "Máximo de instâncias com GPU (abaixo da cota de GPU do projeto na região)."
  type        = number
  default     = 1
}

variable "modelo_sem_redundancia_zonal" {
  description = "Desliga a reserva de GPU em outras zonas (mais barato; failover só por melhor esforço)."
  type        = bool
  default     = true
}

variable "gce_zona" {
  description = <<-EOT
    Zona da VM do modelo no modo gce, dentro da região dos dados. Nula usa <regiao>-a. Confira na tabela de
    GPUs por zona do Compute Engine se o acelerador existe na zona.
  EOT
  type        = string
  default     = null
}

variable "gce_tipo_maquina" {
  description = "Tipo de máquina da VM do modelo (a T4 se liga a máquinas N1)."
  type        = string
  default     = "n1-standard-4"
}

variable "gce_acelerador" {
  description = <<-EOT
    GPU da VM do modelo. Padrão nvidia-tesla-t4 (16 GB): em 17/10/2026 a tabela de GPUs do Compute Engine
    listava N1+T4 nas três zonas de southamerica-east1 e não listava L4 (G2) nessa região. Em região com
    G2, use nvidia-l4 com gce_tipo_maquina = "g2-standard-8".
  EOT
  type        = string
  default     = "nvidia-tesla-t4"
}

variable "gce_imagem" {
  description = "Imagem do disco da VM do modelo (Ubuntu LTS; o instalador do Ollama põe o driver NVIDIA)."
  type        = string
  default     = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"
}

variable "gce_disco_gb" {
  description = "Tamanho do disco da VM do modelo, em GB (sistema, driver e pesos do modelo)."
  type        = number
  default     = 60
}

variable "gce_spot" {
  description = "VM spot (mais barata, pode ser interrompida a qualquer momento). Não use em dia de campo."
  type        = bool
  default     = false
}

variable "gce_agenda" {
  description = <<-EOT
    Agenda da VM do modelo (cron, fuso de 'fuso'). Fora da janela a VM fica desligada e não cobra GPU; a
    API continua no ar e a fiscal segue por texto e formulário. Nula: VM sempre ligada.
  EOT
  type = object({
    ligar    = string
    desligar = string
  })
  default = {
    ligar    = "0 6 * * 1-6"
    desligar = "0 20 * * 1-6"
  }
}

variable "ollama_versao" {
  description = "Versão do Ollama instalada na VM do modelo (modo gce; a mesma da imagem_ollama)."
  type        = string
  default     = "0.32.4"
}

variable "ssh_via_iap" {
  description = "Abre a porta 22 da VM do modelo só para o túnel do IAP (administração, sem IP público)."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------------------------------------

variable "cidr_subrede" {
  description = "Faixa da sub-rede da API e da VM do modelo (saída Direct VPC do Cloud Run usa IPs daqui)."
  type        = string
  default     = "10.20.0.0/24"
}

# ---------------------------------------------------------------------------------------------------------
# Dados, retenção e expurgo
# ---------------------------------------------------------------------------------------------------------

variable "dias_retencao_brutos" {
  description = <<-EOT
    Dias depois do selo em que o job de expurgo cifra os brutos da fiscalização e apaga a chave
    (crypto-shredding). Proposta de 90 dias (docs/privacidade.md, seção 4); a instituição define o prazo.
  EOT
  type        = number
  default     = 90
}

variable "dias_versoes_antigas" {
  description = <<-EOT
    Dias que uma versão sobrescrita ou apagada fica no bucket de dados (versionamento). Soma-se ao prazo do
    expurgo: o bruto em claro some de vez só depois disso e do soft delete.
  EOT
  type        = number
  default     = 7
}

variable "dias_soft_delete_dados" {
  description = "Dias de soft delete do bucket de dados (recuperação de exclusão acidental). 0 desliga."
  type        = number
  default     = 7

  validation {
    condition = (
      var.dias_soft_delete_dados == 0 ||
      (var.dias_soft_delete_dados >= 7 && var.dias_soft_delete_dados <= 90)
    )
    error_message = "O Cloud Storage aceita soft delete de 0 (desligado) ou de 7 a 90 dias."
  }
}

variable "dias_retencao_arquivo" {
  description = <<-EOT
    Retenção (WORM) do bucket de arquivo, que guarda os pacotes de exibição dos laudos selados: nenhum
    objeto pode ser apagado ou trocado antes do prazo. 0 desliga. A instituição define o prazo de guarda.
  EOT
  type        = number
  default     = 0
}

variable "travar_retencao_arquivo" {
  description = "Trava a retenção do arquivo (irreversível: nem o dono do projeto encurta o prazo)."
  type        = bool
  default     = false
}

variable "expurgo_agendado" {
  description = "Cria o agendamento diário do job de expurgo dos brutos vencidos."
  type        = bool
  default     = true
}

variable "agenda_expurgo" {
  description = "Horário do job de expurgo (cron, fuso de 'fuso')."
  type        = string
  default     = "0 3 * * *"
}

variable "arquivamento_agendado" {
  description = "Cria o agendamento diário do job que copia os pacotes selados para o bucket de arquivo."
  type        = bool
  default     = true
}

variable "agenda_arquivamento" {
  description = "Horário do job de arquivamento (cron, fuso de 'fuso')."
  type        = string
  default     = "30 2 * * *"
}

variable "fuso" {
  description = "Fuso dos agendamentos e da data de referência da API."
  type        = string
  default     = "America/Sao_Paulo"
}

variable "persistir_cache_satelite" {
  description = "Guarda o cache do Sentinel-2 no bucket de dados (sem ele, cada subida baixa a série)."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------------------------------------
# Chaves (Cloud KMS) e segredos (Secret Manager)
# ---------------------------------------------------------------------------------------------------------

variable "kms_rotacao" {
  description = "Período de rotação das chaves do Cloud KMS (segundos com sufixo s; padrão 90 dias)."
  type        = string
  default     = "7776000s"
}

variable "kms_nivel_protecao" {
  description = "Nível de proteção das chaves do Cloud KMS: SOFTWARE ou HSM."
  type        = string
  default     = "SOFTWARE"

  validation {
    condition     = contains(["SOFTWARE", "HSM"], var.kms_nivel_protecao)
    error_message = "Use SOFTWARE ou HSM."
  }
}

variable "sal_instalacao" {
  description = <<-EOT
    Sal de uma instalação existente (64 hex, o campo 'sal' de dados_locais/config/instalacao.json), para
    migrar a instalação sem perder a comparação com hashes antigos. Nulo: gera um sal novo. Não fica no state.
  EOT
  type        = string
  default     = null
  sensitive   = true
  ephemeral   = true

  validation {
    condition = (
      var.sal_instalacao == null ||
      can(regex("^[0-9a-f]{64}$", coalesce(var.sal_instalacao, "-")))
    )
    error_message = "O sal tem 64 caracteres hexadecimais minúsculos."
  }
}

variable "pin_assinatura" {
  description = <<-EOT
    PIN da assinatura humana do laudo. Nulo: gera um PIN de 6 dígitos (leia com o comando do output
    comando_ler_pin). Não fica no state.
  EOT
  type        = string
  default     = null
  sensitive   = true
  ephemeral   = true
}

variable "versao_pin" {
  description = "Aumente para gravar um PIN novo no Secret Manager (troca de PIN)."
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------------------------------------
# Observabilidade e custo
# ---------------------------------------------------------------------------------------------------------

variable "logs_regionais" {
  description = "Envia os logs dos serviços para um bucket do Cloud Logging na região dos dados."
  type        = bool
  default     = true
}

variable "dias_retencao_logs" {
  description = "Retenção do bucket regional de logs, em dias."
  type        = number
  default     = 30
}

variable "excluir_logs_do_default" {
  description = "Tira os logs dos serviços do bucket _Default (global): ficam só no bucket regional."
  type        = bool
  default     = true
}

variable "conta_faturamento" {
  description = "ID da conta de faturamento (XXXXXX-XXXXXX-XXXXXX) para o orçamento. Nulo: sem orçamento."
  type        = string
  default     = null
}

variable "orcamento_mensal" {
  description = "Valor do orçamento mensal do projeto, na moeda da conta de faturamento. 0: sem orçamento."
  type        = number
  default     = 0
}

variable "moeda_orcamento" {
  description = "Moeda do orçamento (a mesma da conta de faturamento)."
  type        = string
  default     = "BRL"
}
