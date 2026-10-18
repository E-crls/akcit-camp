# Implantação

O Laudo Vivo se implanta de duas formas, com o mesmo código, a mesma imagem (`Dockerfile`) e os mesmos
controles de privacidade: na máquina da cooperativa ou da credenciada, ou gerenciado num projeto do Google
Cloud da instituição. Nas duas, o modelo (`qwen3.5:4b` no Ollama) roda numa GPU da própria instalação, o
status de cada item vem das ferramentas determinísticas e do verificador, e a assinatura é humana.

| | Máquina da cooperativa | Gerenciada (GCP) |
|---|---|---|
| Para quem | equipe que quer tudo no próprio equipamento, inclusive sem internet no campo (com o cache do satélite) | instituição que prefere serviço gerenciado e acesso pelo celular de qualquer lugar |
| Onde roda | um computador com GPU NVIDIA de 8 a 16 GB (o `qwen3.5:4b` somou +4,5 GB de VRAM no pico medido; [ADR 001](adr/001-modelo-local.md)) | Cloud Run (API e interface) e GPU no projeto: VM com T4 em São Paulo ou Cloud Run com L4 |
| Dados | `dados_locais/` (estado, trilha, evidências, laudos), fora do git | buckets do Cloud Storage em `southamerica-east1`, com chave do Cloud KMS da instituição |
| Sal e PIN | `dados_locais/config/instalacao.json` e `LAUDO_PIN` | Secret Manager, réplica só na região |
| Cofre e expurgo | `dados_locais/api/chaves/`; `scripts/expurgo_lgpd.py` por comando | bucket do cofre com chave KMS própria; job agendado com o mesmo script |
| Acesso | `127.0.0.1`, ou a rede local com HTTPS (`scripts/rodar_demo.sh --https`) | HTTPS do Cloud Run e login Google pelo IAP para quem a instituição autorizar |
| Como subir | `scripts/rodar_demo.sh` ou `docker compose` ([`COMO_RODAR.md`](COMO_RODAR.md), [`runbook.md`](runbook.md)) | Terraform em [`infra/gcp/`](../infra/gcp/README.md) |

A forma gerenciada não muda o produto: a API sobe com o mesmo `python -m laudo.api`, os diretórios de dados
têm os mesmos caminhos (volumes do Cloud Storage FUSE) e o endereço do Ollama continua `127.0.0.1:11434`
dentro da instância, levado ao servidor do modelo por um proxy de borda. O desenho, o passo a passo, o custo
por componente e o mapa entre os controles de privacidade e os serviços estão em
[`infra/gcp/README.md`](../infra/gcp/README.md).

Nas duas formas, as saídas de rede do produto são as descritas em [`privacidade.md`](privacidade.md), seção 5:
a série do satélite (catálogo STAC e imagens Sentinel-2) e os tiles do mapa, sem nome, documento, foto nem
fala.
