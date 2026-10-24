# Variáveis da demo pública. Só `projeto` e `conta_faturamento` não têm padrão.

variable "projeto" {
  description = "ID do projeto do GCP"
  type        = string
}

variable "regiao" {
  description = "Região de tudo (Cloud Run, Artifact Registry, Vertex AI e bucket de fontes)"
  type        = string
  default     = "southamerica-east1"
}

variable "nome" {
  description = "Nome do serviço do Cloud Run e prefixo dos demais recursos"
  type        = string
  default     = "laudo-vivo-demo"
}

variable "conta_faturamento" {
  description = "ID da conta de faturamento, para o orçamento (filtrado só para este projeto)"
  type        = string
}

variable "orcamento_brl" {
  description = "Orçamento mensal do projeto em reais; os alertas vão por e-mail aos administradores da conta"
  type        = number
  default     = 50
}

variable "imagem" {
  description = "Imagem do contêiner no Artifact Registry. Vazia: cria só a base (APIs, registro, contas, painel)"
  type        = string
  default     = ""
}

variable "cpu" {
  description = "vCPUs da instância (a voz roda na CPU)"
  type        = string
  default     = "4"
}

variable "memoria" {
  description = "Memória da instância"
  type        = string
  default     = "8Gi"
}

variable "instancias_minimas" {
  description = "Instâncias sempre ligadas. 0 = custo zero sem acesso (a verificação de disponibilidade mantém uma aquecida)"
  type        = number
  default     = 0
}

variable "instancias_maximas" {
  description = "Teto de instâncias. 1: as sessões dos visitantes ficam na memória de uma instância só, e o custo tem teto"
  type        = number
  default     = 1
}

variable "concorrencia" {
  description = "Requisições simultâneas por instância"
  type        = number
  default     = 40
}

variable "modelo_gemini" {
  description = "Modelo do Gemini no Vertex AI para o texto livre (os passos gravados saem do replay, sem custo)"
  type        = string
  default     = "gemini-3.1-flash-lite"
}

variable "local_gemini" {
  description = "Local do endpoint do Gemini. Os Flash-Lite não estão em southamerica-east1 neste projeto: global"
  type        = string
  default     = "global"
}

variable "tokens_llm_por_dia" {
  description = "Teto diário de tokens do Gemini na instância; acima dele o condutor usa o caminho determinístico"
  type        = number
  default     = 5000000
}

variable "tokens_llm_por_hora" {
  description = "Fatia por hora do teto de tokens: quem gira cookies para gastar o teto derruba só a hora corrente"
  type        = number
  default     = 1250000
}

variable "timeout_gemini_s" {
  description = "Espera máxima por uma resposta do Gemini; estourou, o condutor responde pelo template"
  type        = number
  default     = 12
}

variable "intervalo_verificacao" {
  description = "Intervalo da verificação de disponibilidade (mantém a instância aquecida; cada chamada custa ~0)"
  type        = string
  default     = "300s"
}

# Preço do Cloud Run em southamerica-east1 (Tier 2, cobrança por requisição), do catálogo do Cloud Billing
# (serviço 152E-C115-5142, consultado em 24/10/2026). Usado só para o custo estimado no painel.
variable "preco_vcpu_s" {
  description = "US$ por vCPU-segundo (Services CPU Tier 2, request-based)"
  type        = number
  default     = 0.0000336
}

variable "preco_gib_s" {
  description = "US$ por GiB-segundo (Services Memory Tier 2, request-based)"
  type        = number
  default     = 0.0000035
}
