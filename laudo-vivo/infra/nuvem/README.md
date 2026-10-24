# Demo pública na nuvem (Terraform)

Um site no Cloud Run, sem GPU, que qualquer pessoa abre pelo QR code e usa sozinha, com **dados sintéticos**.
É diferente de [`infra/gcp`](../gcp/README.md), que descreve a arquitetura de produção (LLM na região, KMS, cofre).
Aqui fica só o mínimo para a plateia testar.

## O que roda ao vivo e o que vem pronto

| Parte | Na demo da nuvem |
|---|---|
| Agente (condutor), passos do roteiro | replay da gravação: custo zero, mesma resposta do ensaio |
| Agente, texto livre | Gemini 3.1 Flash-Lite no Vertex AI (endpoint global), com teto diário de tokens; se cair ou estourar o teto, o condutor segue com o plano mínimo e a fala por template |
| Voz | Whisper pequeno na CPU da própria instância |
| Assinatura com PIN e selo | ao vivo (determinístico) |
| Vídeo do brete, satélite, GPS, leitura do papel | presets do caso de demonstração, com o resultado já calculado (precisariam de boi, mato ou GPU) |

Política, verificador e selo são os mesmos do produto: o Gemini só propõe, e a regra decide.

O texto livre vai ao endpoint **global** do Gemini, porque os modelos Flash-Lite não estão disponíveis em
southamerica-east1 neste projeto. Como o provedor é `externo=True`, o condutor mascara PII antes do envio,
e os dados da demo são sintéticos. O produto em campo usa LLM local (ver `docs/adr/001-modelo-local.md`).

## Recursos (todos com a etiqueta `centro-custo=laudo-vivo-demo`)

| Arquivo | Recurso |
|---|---|
| `main.tf` | APIs; Artifact Registry (guarda só as 2 imagens mais novas); bucket das fontes do build (apaga em 1 dia); 2 contas de serviço sem chave (build e serviço) com o mínimo de papéis |
| `servico.tf` | Cloud Run público: 4 vCPU, 8 GiB, cobrança por requisição, mínimo 0 e máximo 1 instância, afinidade de sessão; verificação de disponibilidade de 3 regiões a cada 5 min (também mantém a instância aquecida) |
| `observabilidade.tf` | métricas de log (eventos, tokens, custo, áudio); painel do Cloud Monitoring; orçamento mensal de R$ 50 com alertas de 10% a 100%, filtrado só para este projeto |

## Custo

Preços do catálogo do Cloud Billing, consultado em 24/10/2026:
- **Cloud Run** (southamerica-east1, Tier 2, cobrança por requisição): US$ 0,0000336 por vCPU-s e US$ 0,0000035 por GiB-s.
- **Gemini 3.1 Flash-Lite** (global): US$ 0,25 por milhão de tokens de entrada e US$ 1,50 por milhão de saída.

| Situação | Estimativa |
|---|---|
| Sem acesso (madrugada) | ~US$ 0,01 por dia (só as verificações de disponibilidade; a CPU ociosa não é cobrada) |
| Instância atendendo sem parar | US$ 0,58 por hora (4 × 0,0000336 + 8 × 0,0000035 por segundo) |
| Turno de texto livre | ~11 mil tokens (até 3 chamadas) ≈ US$ 0,003 |
| Dia de evento (50 visitantes, 500 turnos, 200 falas) | Cloud Run ~US$ 0,5 + Gemini ~US$ 1,5 ≈ **US$ 2 (~R$ 11)** |
| Teto de LLM | 5 milhões de tokens por dia ≈ US$ 1,40, em fatias de 1,25 milhão por hora (um abuso derruba só a hora) |
| Pior caso (instância ocupada 24 h + teto do LLM) | ~US$ 15 por dia |
| Registro (2 imagens) | ~US$ 0,10 por GB-mês acima de 0,5 GB |

O orçamento não corta gasto. O teto real vem de três lugares:
- a instância única;
- o teto de tokens no app;
- os limites por visitante e o número máximo de cópias vivas, que vêm do servidor em modo público.

## Uso

```bash
cd laudo-vivo/infra/nuvem
cp terraform.tfvars.example terraform.tfvars   # projeto e conta de faturamento
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
terraform init
terraform apply                                # base: APIs, registro, contas, métricas, painel, orçamento
bash publicar.sh                               # build no Cloud Build + serviço + conferência
bash verificar.sh                              # conferência a qualquer momento (só lê)
```

O `verificar.sh` sai com erro quando encontra um destes problemas:
- o Terraform tem diferença pendente;
- algum recurso está duplicado ou sem a etiqueta de custo;
- o Cloud Run saiu da configuração de custo (cobrança por requisição, teto de 1 instância, sem GPU);
- o site não responde.

Além disso, ele imprime o custo estimado das últimas 24 h.

## Observabilidade

- **Painel** (`terraform output painel`):
  - visitantes, turnos e requisições por classe de resposta;
  - chamadas de LLM por origem (replay, Gemini ou teto atingido);
  - tokens e custo estimado do Gemini, e custo estimado do Cloud Run;
  - latência p50 e p95, instâncias, recusas por limite, erros, segundos de voz e disponibilidade.
- **Eventos:** o app imprime uma linha JSON por evento (`{"laudo_evento": ...}`), só em modo público e sem texto
  de conversa. O Cloud Logging guarda essas linhas, e as métricas de log contam e somam.
- **Faturamento oficial:** Console → Faturamento → Relatórios, filtrado pelo rótulo `centro-custo=laudo-vivo-demo`.

## Depois do evento

Com mínimo de 0 instância, o site parado custa perto de zero. Para apagar tudo:

```bash
rm -f imagem.auto.tfvars && terraform apply    # tira só o site do ar
terraform destroy                              # apaga tudo (as APIs continuam ligadas, sem custo)
```
