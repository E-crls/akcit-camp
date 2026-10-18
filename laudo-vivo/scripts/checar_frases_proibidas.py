"""Procura frases proibidas no pitch, no Q&A, no BMC, na inscrição e nos demais textos de negócio.

A lista vem do memorando de 16/10/2026 (memorando interno, seção 4, "Frases proibidas", e o que as
seções 2, 3 e 5 dizem para não afirmar) e está explicada, com o "diga no lugar", em
`../negocio/afirmacoes_proibidas.md`. As regras moram aqui (`REGRAS`); o .md é a versão para quem ensaia.

Uso (na raiz do repositório):
  scripts/py.sh scripts/checar_frases_proibidas.py                 # textos públicos e ../negocio/ (abaixo)
  scripts/py.sh scripts/checar_frases_proibidas.py README.md eval   # só estes arquivos ou diretórios
  scripts/py.sh scripts/checar_frases_proibidas.py --regras         # lista as regras e o "diga no lugar"
  scripts/py.sh scripts/checar_frases_proibidas.py --excecoes       # mostra também as linhas liberadas
  scripts/py.sh scripts/checar_frases_proibidas.py --autoteste      # confere as regras contra os exemplos
  scripts/py.sh scripts/checar_frases_proibidas.py --so P20-P25     # só estas regras (lista ou faixa)
  scripts/py.sh scripts/checar_frases_proibidas.py --relatorio      # lista tudo e sai com 0 (modo relatório)

Varredura padrão: `docs/entregaveis/`, `validacao/`, `README.md`, `docs/decisao.md`, `docs/privacidade.md`,
`docs/fluxo_do_agente.md`, `docs/runbook.md`, `docs/exemplos/` e `../negocio/` (o que a banca ou a equipe leem
como afirmação nossa). Dentro de um `.zip` (o pacote de exibição de `docs/exemplos/`), o texto de cada arquivo
de texto do pacote também é varrido; o achado sai como `pacote.zip!caminho/no/pacote.json:linha`.

Código de saída: 0 sem achados (ou com --relatorio); 1 se achou alguma frase; 2 se o autoteste falhou ou um
caminho não existe.

- O script pega formulações (a frase da lista e as variantes próximas: plural, sinônimo, ordem trocada), não o
  sentido. Paráfrase livre ("a cooperativa já topou pagar 79") passa: a revisão humana da seção 0 de
  `afirmacoes_proibidas.md` continua valendo. Cada regra tem exemplos que TÊM de ser acusados e frases certas
  que NÃO podem ser acusadas; `--autoteste` confere os dois lados.
- Fica fora da varredura a própria lista (`../negocio/afirmacoes_proibidas.md`), que precisa citar as frases.
- Uma linha que precisa citar a frase (ex.: a pergunta da banca entre aspas, para ensaiar a resposta) leva o
  marcador invisível `<!--cita-proibida-->` e passa. Use pouco: `--excecoes` lista todas para a revisão.
- Antes de casar, o texto é normalizado sem mudar as posições: tags HTML, comentários (inclusive os marcadores
  de número `<!--n:...-->`), URLs, `*`, `_`, `~` e crases viram espaço, e os acentos caem ("satelite" e
  "satélite" são a mesma palavra); maiúsculas e minúsculas não importam.
- Negação: nas regras em que "não" antes inverte o sentido e deixa a frase certa (P03, P04, P10, P14, P17 e
  P18: "não somos os únicos", "ainda não testamos preço", "a pecuária não concentra as desclassificações",
  "o juiz não validou", "não foi validado pela Justiça", "nenhum preço foi testado com cliente"), a frase
  negada passa. "Não só", "não apenas" e "não somente" não contam como negação.
- No CI, `../negocio/` não existe e é pulado (o mesmo que `scripts/gerar_numeros.py` faz).
- Regras de contexto (desde a noite de 16/10/2026, depois da r4): algumas frases só são proibidas sem a ressalva
  em volta. A P21 ("nunca afirma o que não tem prova") passa com a ressalva do red-team cego na mesma linha ou
  na mesma frase; a P22 ("0/80") passa com o cego no mesmo parágrafo; a P24 (número do dev) só é acusada numa
  frase que fala do teste e não diz "dev". Parágrafo é um bloco de linhas sem linha em branco, mas cada item de
  lista, título e linha de tabela é um parágrafo sozinho (a linha de tabela é a unidade do par obrigatório do
  `gerar_numeros.py --verificar`). A ressalva tem de ser afirmativa: "não é cego", "falta um conjunto cego" e
  "sem conjunto cego" não contam. O registro de chaves (`docs/entregaveis/numeros.md` e `numeros.json`, gerados
  pelo `gerar_numeros.py`) fica fora das regras de contexto: é a lista de chaves, não uma afirmação.
- Exceção normativa (`EXCECOES_NORMATIVAS`): um termo citado da norma que o produto reproduz (hoje só o "ilícitos
  penais ou fraudes fiscais" do MCR 2-7, item 21, no título da regra do rulebook) passa, mas só em
  `docs/exemplos/` (o laudo e o pacote de exemplo, gerados do rulebook). Sai como linha liberada (`--excecoes`).
"""

from __future__ import annotations

import argparse
import bisect
import io
import re
import sys
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NEGOCIO = REPO.parent / "negocio"
RAIZES_PADRAO = [
    REPO / "docs" / "entregaveis",
    REPO / "validacao",
    REPO / "README.md",
    REPO / "docs" / "decisao.md",
    REPO / "docs" / "privacidade.md",
    REPO / "docs" / "fluxo_do_agente.md",
    REPO / "docs" / "runbook.md",
    REPO / "docs" / "exemplos",  # laudo selado de exemplo (L55): README, laudo HTML/JSON e gerado_com.json
    NEGOCIO,
]
LISTA = NEGOCIO / "afirmacoes_proibidas.md"
EXTENSOES = {".md", ".html", ".htm", ".txt", ".csv", ".tsv", ".yaml", ".yml", ".json"}
# Dentro do .zip entra também a trilha (trace.jsonl), que a banca pode abrir no pacote de exibição.
EXTENSOES_NO_ZIP = EXTENSOES | {".jsonl"}
EXCLUIR_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dados_locais",
                "node_modules"}
MARCA_EXCECAO = "<!--cita-proibida-->"
# Registro de chaves gerado pelo gerar_numeros.py: fica fora das regras de contexto (P21, P22 e P24).
REGISTRO_DE_CHAVES = ("docs/entregaveis/numeros.md", "docs/entregaveis/numeros.json")
# Unidade de contexto: começa nova a cada item de lista, título ou linha de tabela (e depois de linha de tabela).
_RX_INICIO_UNIDADE = re.compile(r"\s*(?:[-*+]\s|\d+[.)]\s|#|\|)")
# Fim de frase: ponto, exclamação ou interrogação seguidos de espaço ou do fim ("3.904" e "0,69" não quebram).
_RX_FIM_FRASE = re.compile(r"[.!?](?=\s|$)")
# A ressalva só vale afirmativa: "não é cego", "(não cego)", "falta um conjunto cego", "sem conjunto cego" e
# "ainda não há conjunto cego" não falam do resultado do cego (era o "diga no lugar" antigo da P22, antes do v3).
# Negação até 3 palavras antes da ressalva.
_RX_NEGA_RESSALVA = re.compile(r"(?:\bnao|\bfalta\w*|\bsem|\bnenhum\w*|\bnem)\s+(?:\w+[\s-]+){0,3}$",
                               re.IGNORECASE)
# O resultado do red-team cego, dito pela palavra ("no cego", "conjunto cego") ou pelo número (6/30 e 6/26, da
# r4; a família semi-cega não conta como "cego").
_CEGO = r"(?<!semi-)(?<!semi)\bceg[oa]s?\b|\b6\s*(?:/|de)\s*(?:30|26)\b"
# Números do A/B v2 no dev (r4: leituras do dev de 09/10, narrações da r4). No teste os equivalentes são outros.
# O par 97% e 42% casa com até 250 caracteres entre os dois, sem atravessar fim de frase ("a IA levou 97% das
# fiscalizações ao conteúdo conciliado, contra 42% digitando", do RQ2; os marcadores escondidos contam espaço).
_NUM_DEV = (r"\b3\.?904\s*(?:/|de)\s*3\.?916\b"
            r"|(?<![\d,.])\b97\s*%(?:(?![.!?](?:\s|$))[\s\S]){0,250}?(?<![\d,.])\b42\s*%"
            r"|(?<![\d/])\b35\s*(?:/|de)\s*36\b|(?<![\d/])\b71\s*(?:/|de)\s*72\b|(?<![\d/])\b38\s*(?:/|de)\s*41\b")
# Somem antes de casar: comentários (inclusive marcadores de número), tags, URLs (o endereço da fonte não
# é afirmação nossa), `*`, `_` e `~` (ênfase e tachado do Markdown) e crases.
_RX_ESCONDER = re.compile(r"<!--.*?-->|<[^>\n]+>|https?://[^\s)\]>\"'|]+|[*_~`]", re.DOTALL)
# Negação logo antes da frase (até 2 palavras entre elas), na mesma linha. "Não só/apenas/somente" não nega.
# "Nenhum"/"nenhuma" também negam ("nenhum preço foi testado"). Casam no texto já sem acento.
_RX_NEGADOR = re.compile(r"\b(?:nao|nunca|jamais|nem|nenhum|nenhuma)\b", re.IGNORECASE)
_RX_LACUNA_NEGACAO = re.compile(r"\s+(?:\w+\s+){0,2}")
_RX_NAO_SO = re.compile(r"\s+(?:so|apenas|somente)\b", re.IGNORECASE)
# Uma palavra qualquer que não seja negação: lacuna das regras em que "não" no meio inverte o sentido
# ("a pecuária não concentra"). Escrita sem acento, como o texto depois de normalizado.
_P = r"(?:(?!(?:nao|nunca|jamais)\b)\w+\s+)"
_GADO = r"(?:bois?|gado|cabe[cç]as?|animal|animais|reses|rebanhos?|vacas?|bezerr\w*)"
# Sujeito da P10 (a pecuária como um todo). "Aquisição/compra de animais (ou de gado)" fica fora: é sobre ela
# que a frase certa da regra fala ("a aquisição de animais concentra mais desclassificações que a média").
_SUJ_PECUARIA = (r"(?<!aquisicao\sde\s)(?<!aquisicoes\sde\s)(?<!compra\sde\s)(?<!compras\sde\s)"
                 r"(pecu[aá]ri\w*|gado|bovin\w*|animais|bois?)")
# Lacuna sem negação que atravessa vírgula ("nas entrevistas, os fiscais confirmaram") e verbo no passado
# na 3ª ou na 1ª do plural: a frase afirma que a entrevista aconteceu.
_P_VIRGULA = r"(?:(?!(?:nao|nunca|jamais)\b)\w+[\s,]+)"
_PASSADO_PLURAL = (r"(\w+(?:aram|eram|iram)|ouvimos|confirmamos|validamos|vimos|descobrimos|aprendemos"
                   r"|percebemos|notamos)\b")


@cache
def _letra_sem_acento(c: str) -> str:
    base = "".join(x for x in unicodedata.normalize("NFD", c) if not unicodedata.combining(x))
    return base if len(base) == 1 else c


def sem_acento(texto: str) -> str:
    """Tira os acentos letra a letra, sem mudar o tamanho do texto (as posições continuam valendo)."""
    return "".join(c if c.isascii() else _letra_sem_acento(c) for c in texto)


@dataclass(frozen=True)
class Regra:
    id: str
    frase: str  # a frase proibida, como a lista a escreve
    padrao: str  # regex (sem diferenciar maiúsculas; os acentos do padrão também caem antes de compilar)
    motivo: str
    diga: str  # a formulação correta
    exemplos: tuple[str, ...]  # textos que TÊM de ser acusados por esta regra (autoteste)
    exceto_na_linha: str | None = None  # se a linha casar com isto, não acusa (ex.: "preço-alvo")
    limpos: tuple[str, ...] = ()  # frases certas que NENHUMA regra pode acusar (autoteste)
    negacao_antes: bool = False  # "não" logo antes deixa a frase certa ("não somos os únicos")
    # Regras de contexto (P21, P22 e P24). `ressalva`: se casar, de forma afirmativa, no contexto `ressalva_em`
    # ("frase": só a frase do trecho; "linha_ou_frase": a frase e as linhas do trecho; "paragrafo": o
    # parágrafo, item de lista ou linha de tabela), não acusa. `exige_na_frase`: só acusa se a frase do trecho
    # também casar com isto.
    ressalva: str | None = None
    ressalva_em: str = "frase"
    exige_na_frase: str | None = None
    rx: re.Pattern = field(init=False, repr=False, compare=False)
    rx_exceto: re.Pattern | None = field(init=False, repr=False, compare=False)
    rx_ressalva: re.Pattern | None = field(init=False, repr=False, compare=False)
    rx_exige: re.Pattern | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        def rx(p: str | None) -> re.Pattern | None:
            return re.compile(sem_acento(p), re.IGNORECASE) if p else None

        if self.ressalva_em not in ("frase", "linha_ou_frase", "paragrafo"):
            raise ValueError(f"{self.id}: ressalva_em inválido: {self.ressalva_em!r}")
        object.__setattr__(self, "rx", rx(self.padrao))
        object.__setattr__(self, "rx_exceto", rx(self.exceto_na_linha))
        object.__setattr__(self, "rx_ressalva", rx(self.ressalva))
        object.__setattr__(self, "rx_exige", rx(self.exige_na_frase))

    @property
    def de_contexto(self) -> bool:
        return bool(self.ressalva or self.exige_na_frase)


REGRAS: tuple[Regra, ...] = (
    Regra("P01", "ninguém concilia no curral o boi, a nota, a GTA e a regra",
          r"ningu[eé]m\s+(\w+\s+){0,3}concili\w*"
          r"|\bnenhum[a]?\s+(outr[oa]\s+)?(concorrente|empresa|solu[cç][aã]o|ferramenta|fornecedor|startup"
          r"|produto)s?\s+(\w+\s+){0,3}(concili(a|am|ou|aram|ava)\b|faz\w*\s+(a\s+)?concilia)",
          "exclusividade que não verificamos: a Olho do Dono já cruza contagem por câmera com GTA "
          "(12/09/2026)",
          "\"A camada de prova do MCR 2-7 para o que o satélite não fecha: do lado da IF, item a item, com "
          "abstenção e assinatura humana; consumimos alertas e contagens de terceiros em vez de competir "
          "com eles.\"",
          ("Ninguém concilia no curral o boi, a nota, a GTA e a regra.",
           "ninguém faz a conciliação no curral", "Nenhum concorrente concilia contagem e GTA",
           "NINGUÉM CONCILIA NO CURRAL", "ninguem concilia no curral o boi",
           "nenhuma solução faz a conciliação no curral"),
          limpos=("um rótulo de desfecho de campo que nenhum fornecedor só de satélite tem",
                  "Nenhuma ferramenta de conciliação recebe CPF/CNPJ em claro.")),
    Regra("P02", "satélite não conta boi",
          r"sat[eé]lites?\s+(\w+\s+){0,2}n[aã]o\s+(\w+\s+){0,2}cont(a|am|ar|aria|ariam|em|e)\b\s*"
          r"(\w+\s+){0,2}" + _GADO + r"\b"
          r"|sat[eé]lites?\s+(\w+\s+){0,2}n[aã]o\s+(\w+\s+){0,2}(enxerg\w*|v[eê]\b|veem\b|detect\w*"
          r"|identific\w*|distingu\w*|reconhec\w*)\s+(\w+\s+){0,3}" + _GADO + r"\b"
          r"|(imposs[ií]vel|n[aã]o\s+(d[aá]|h[aá]\s+como|tem\s+como|se\s+consegue))\s+(para\s+)?contar\s+"
          r"(\w+\s+){0,2}(bois?|gado|cabe[cç]as|animais)\s+(\w+\s+){0,2}(por|com|via|do)\s+"
          r"(sat[eé]lite|c[eé]u)",
          "a Audsat anuncia contagem de gado por imagem (09/02/2026) e o item 9 diz que contar animais por "
          "satélite é facultativo",
          "\"O satélite pode contar cabeças, mas não prova que são as financiadas nem confere NF-e e GTA.\"",
          ("o satélite não conta boi", "Satélite não consegue contar gado", "Os satélites não contam bois",
           "o satélite ainda não consegue contar o gado", "não dá para contar boi por satélite",
           "SATÉLITE NÃO CONTA BOI", "satelite nao conta boi",
           "o satélite não enxerga se o boi é o financiado", "o satélite não vê o gado"),
          limpos=("Contar animais por satélite é facultativo (Voto 166/2025, item 32).",
                  "A Audsat conta gado do céu; a Softfocus valida nota fiscal.",
                  "o satélite não prova que o boi visto é o financiado",
                  "O que o satélite não vê, nós provamos.")),
    Regra("P03", "somos os únicos a conciliar contagem com GTA",
          r"\bsomos\s+(os\s+|as\s+|o\s+|a\s+)?[uú]nic[oa]s?\b"
          r"|\b[uú]nic[oa]s?\s+(\w+\s+){0,3}(a|que)\s+(\w+\s+){0,2}concili\w*"
          r"|\bs[oó]\s+n[oó]s\s+(\w+\s+){0,2}(concili|fazemos|conseguimos|temos|oferecemos|entregamos)\w*"
          r"|\b[uú]nic[oa]s?\s+(no|do|na|da)\s+(mercado|brasil|pa[ií]s|setor|agro)\b",
          "a Olho do Dono cruza contagem com GTA; exclusividade não verificada custa o critério Diferencial",
          "Nomear o concorrente e a lacuna dele (tabela da seção 4 do memorando).",
          ("Somos os únicos a conciliar contagem com GTA.", "somos o único que concilia",
           "a única solução que concilia boi e GTA", "Só nós conciliamos boi, nota e GTA",
           "a única do mercado a fazer isso", "SOMOS OS ÚNICOS", "Não só nós conciliamos boi e GTA"),
          limpos=("a única forma de reverter a desclassificação é documentação por operação",
                  "o único item pendente é a foto",
                  "Não somos os únicos a conciliar contagem com GTA: a Olho do Dono também cruza."),
          negacao_antes=True),
    Regra("P04", "primeiro agente de IA no crédito agro",
          r"\bprimeir[oa]s?\s+agentes?\b"
          r"|\b(somos|seremos|fomos)\s+(o|a|os|as)\s+primeir[oa]s?\b"
          r"|\bprimeir[oa]s?\s+(\w+\s+){0,2}(a\s+usar|a\s+aplicar|a\s+levar|a\s+trazer|a\s+oferecer)\s+"
          r"(\w+\s+){0,2}(ia|intelig[eê]ncia|agentes?|llm)\b"
          r"|\bprimeir[oa]s?\s+(solu[cç][aã]o|plataforma|ferramenta|startup|sistema|produto)\s+(\w+\s+){0,2}"
          r"(de|com)\s+(ia|intelig[eê]ncia|agentes?|llm)\b"
          r"|\bpioneir[oa]s?\b",
          "AgRisk (agente de crédito agro, 25/09/2026), Tarken, Zaia e os agentes do BB já existem, na "
          "concessão",
          "\"Eles atuam na concessão; nós atuamos no pós-contratação e na prova.\"",
          ("o primeiro agente de IA no crédito agro", "Somos os primeiros a usar IA na fiscalização",
           "a primeira plataforma de IA para o crédito rural", "somos pioneiros na fiscalização",
           "OS PRIMEIROS AGENTES de IA do crédito rural"),
          limpos=("o primeiro pagamento é o marco dos próximos 30 dias", "o primeiro piloto pago",
                  ("Não somos o primeiro agente de IA no crédito agro: AgRisk e Tarken já atuam na "
                   "concessão.")),
          negacao_antes=True),
    Regra("P05", "MCP aberto é diferencial",
          # sem atravessar "não": "MCP não é diferencial" e "o diferencial não é o MCP" são a frase certa;
          # atravessa "|" de tabela ("| Nosso diferencial | servidor MCP |")
          r"\bMCP\b(?:(?!\bn[aã]o\b)[^.\n]){0,80}\bdiferencia\w*"
          r"|\bdiferencia\w*(?:(?!\bn[aã]o\b)[^.\n]){0,80}\bMCP\b",
          "MCP é o mínimo esperado (Cropin OrbitAI tem servidor MCP desde 14/07/2026)",
          "\"O diferencial é o conteúdo: o MCR como código versionado, com o item citado em cada regra, e o "
          "golden set.\"",
          ("Nosso MCP aberto é diferencial.", "o diferencial é o servidor MCP",
           "| Nosso diferencial | servidor MCP aberto |", "os diferenciais: servidor MCP e regras"),
          limpos=("MCP não é diferencial; o conteúdo é.", "O diferencial não é o MCP, é o conteúdo.")),
    Regra("P06", "atestado",
          r"\batestad[oa]s?\b",
          "lembra o atestado pago pelo produtor da VMG/MAPA (Portaria 885), que o TCU questiona (02/10/2026)",
          "\"Laudo de fiscalização da IF, pago pela IF para cumprir a obrigação dela e assinado por "
          "profissional habilitado.\"",
          ("um atestado de conformidade", "atestado pago pelo produtor", "ATESTADOS de conformidade")),
    Regra("P07", "\"suspeito\" para operação ou pessoa real",
          r"\bsuspeit\w*",
          "rótulo sobre pessoa ou operação real; a triagem e o Sicor mostram prioridade de verificação",
          "\"prioridade de verificação\"; no laudo, \"item divergente ou pendente\".",
          ("operação suspeita", "produtor suspeito", "suspeitas em Goiás", "OPERAÇÕES SUSPEITAS")),
    Regra("P08", "\"fraude\" para operação real (inclui \"o gado é onde está a fraude\" e \"Panoptes achou "
          "26,6% de fraude\")",
          r"\bfraud\w*",
          "desclassificação, divergência e irregularidade não são fraude; chamar operação real de fraude é "
          "acusação (memorando, seção 3: o Sicor não prova fraude; o Panoptes não é acórdão nem fraude)",
          "\"desclassificações registradas\"; \"divergência\"; \"indício de ilícito, que a IF comunica (MCR "
          "2-7, item 21)\"; para caso público, \"esquema investigado pela PF\".",
          ("o gado é onde está a fraude", "Panoptes achou 26,6% de fraude", "fraudes em Goiás",
           "achamos _fraude_ no curral", "FRAUDES em Goiás")),
    Regra("P09", "\"quadruplicou\", \"cresceu 70 vezes\" e \"4 vezes\" ou \"4x\" para crescimento",
          r"quadruplic\w*|qu[aá]drupl\w*|\b(70|setenta)\s*(vezes|x)\b|\bx\s*70\b"
          r"|\b(cresceu|cresceram|cresce|crescem|crescimento|aumentou|aumentaram|aumento|subiu|subiram|saltou"
          r"|saltaram|pulou|pularam|disparou|dispararam|multiplic\w+)\s+(\w+\s+){0,3}(4|quatro)\s*(vezes|x)\b"
          r"|\b(4|quatro)\s+vezes\s+mais\s+(\w+\s+){0,2}desclassifica\w*",
          "a série de desclassificações tem quebra entre 2020 e 2023",
          "Comparar só 2026 parcial com 2025 inteiro, com o número da chave desc.* de numeros.md.",
          ("as desclassificações quadruplicaram", "cresceu 70 vezes", "aumentou quase 4 vezes", "cresceu 4x",
           "quatro vezes mais desclassificações", "AS DESCLASSIFICAÇÕES QUADRUPLICARAM"),
          limpos=("o custeio de aquisição de animais desclassifica ~3,7× a média",
                  "desclassifica 4,9 vezes mais que as demais finalidades")),
    Regra("P10", "a pecuária concentra as desclassificações",
          _SUJ_PECUARIA + r"\s+" + _P + r"{0,2}(concentra\w*|lidera\w*)\s+"
          r"(\w+\s+){0,4}(desclassifica\w*|irregularidade\w*|fraude\w*|desvios?)"
          r"|(maioria|maior\s+parte|grosso)\s+(\w+\s+){0,2}(desclassifica\w*|irregularidades)\s+(\w+\s+){0,4}"
          r"(gado|pecu[aá]ri\w*|bovin\w*|animais)"
          r"|" + _SUJ_PECUARIA + r"\s+" + _P + r"{0,2}respond\w*\s+(por|pela|pelo)\s+(\w+\s+){0,2}"
          r"(maior\s+parte|maioria|grosso)\s+(\w+\s+){0,2}(desclassifica\w*|irregularidade\w*)",
          "a pecuária como um todo é proporcional (54,1% das operações de 2022–2024 e 58,3% dos registros de "
          "2024–2026); quem não é proporcional é a aquisição de animais (26,1% das operações e 37,7% das "
          "operações desclassificadas), e o excesso vem do custeio de aquisição: a compra de gado por "
          "investimento fica abaixo da média (bench/desclassificacao, chaves desc.part_* de numeros.md)",
          "\"O custeio de aquisição de animais desclassifica ~3,7× a média; a compra de gado por "
          "investimento, abaixo dela\" (só com a chave desc.razao_custeio_media de numeros.md).",
          ("a pecuária concentra as desclassificações",
           "a pecuária concentra a maior parte das desclassificações",
           "a maior parte das desclassificações vem do gado", "A PECUÁRIA CONCENTRA AS DESCLASSIFICAÇÕES",
           "a pecuaria concentra as desclassificacoes",
           "a pecuária responde pela maior parte das desclassificações",
           "o gado lidera as desclassificações", "As pecuárias concentram as desclassificações",
           "o setor pecuário concentra as desclassificações"),
          limpos=("participação proporcional: 54% das operações e 58% das desclassificações",
                  "a pecuária não concentra as desclassificações: a participação é proporcional",
                  "o custeio de aquisição de animais desclassifica ~3,7× a média",
                  "a aquisição de animais tem 26,1% das operações e 37,7% das operações desclassificadas",
                  "a aquisição de animais concentra mais desclassificações que a média")),
    Regra("P11", "o gado é onde está a fraude",
          r"(gado|pecu[aá]ria|bois?|animais|bovinos)\s+([eé]|s[aã]o)\s+onde\s+est([aá]|[aã]o)\b",
          "acusação (\"fraude\", ver a P08) e conta errada: a pecuária é proporcional nas "
          "desclassificações; acima da média está só o custeio de aquisição de animais (ver a P10), e "
          "desclassificação registrada não é fraude",
          "\"O custeio de aquisição de animais desclassifica ~3,7× a média\" (chave "
          "desc.razao_custeio_media); nunca \"onde está o problema\".",
          ("O gado é onde está o problema", "os bois são onde estão as desclassificações")),
    Regra("P12", "TCU achou 155 mil irregulares",
          r"\b155\s*mil\b|\b155[.\s]000\b|cento\s+e\s+cinquenta\s+e\s+cinco\s+mil",
          "não há acórdão com esse número; o Panoptes é relatório técnico com o Lapig-UFG",
          "\"Fiscalização manual, amostral e de baixa cobertura (TCU/Panoptes com Lapig-UFG, relatório "
          "técnico).\"",
          ("O TCU achou 155 mil irregulares", "TCU achou 155.000 irregulares")),
    Regra("P13", "Panoptes achou 26,6% de fraude",
          r"panoptes[^.\n|]{0,120}\bfraud|26,6\s*%[^.\n|]{0,60}\bfraud",
          "o 26,6% é irregularidade flagrante em 3.694 operações de recuperação de pastagem; não é acórdão "
          "nem fraude",
          "\"26,6% de irregularidade flagrante em 3.694 operações de recuperação de pastagem (relatório "
          "técnico, não acórdão).\"",
          ("O Panoptes achou 26,6% de fraude",)),
    Regra("P14", "a Justiça validou",
          r"justi[cç]a\s+(j[aá]\s+)?(validou|validaram|aprovou|aprovaram|reconheceu|reconheceram|confirmou"
          r"|confirmaram|chancelou|chancelaram|endossou|endossaram|referendou|referendaram)\b"
          r"|(validad|aprovad|chancelad|endossad|referendad|reconhecid)[oa]s?\s+(\w+\s+)?pel[oa]s?\s+"
          r"(justi[cç]a|ju[ií]z\w*|judici[aá]rio|tribunal|jf)\b"
          r"|\b(justi[cç]a|jf|ju[ií]z\w*|judici[aá]rio|tribunal|tribunais|vara)\s+" + _P + r"{0,4}"
          r"(validou|validaram|aprovou|aprovaram|chancelou|chancelaram|endossou|endossaram|referendou"
          r"|referendaram)\b",
          "a decisão de Rio Verde é liminar, num caso de lavoura, e não avaliou produto nenhum",
          "\"Um juiz de Rio Verde suspendeu uma cobrança porque o banco não exibiu a prova\" (liminar; "
          "\"prova sem trilha vira passivo\").",
          ("a Justiça validou", "A justiça já reconheceu o método", "validado pela Justiça",
           "o juiz de Rio Verde validou o método", "a JF de Rio Verde validou",
           "os juízes validaram o laudo", "A JUSTIÇA VALIDOU"),
          limpos=("Um juiz de Rio Verde suspendeu uma cobrança porque o banco não exibiu a prova.",
                  "a Justiça não validou produto nenhum", "o juiz não validou o método",
                  "o método não foi validado pela Justiça"),
          negacao_antes=True),
    Regra("P15", "laudo escrito à noite",
          r"laudos?\s+(\w+\s+){0,2}(à|a|de|na|pela)\s+(noite|madrugada)"
          r"|(escrev\w*|escrit[oa]s?|redig\w*|faz\w*|fiz\w*)\s+(o\s+|os\s+)?laudos?\s+(\w+\s+){0,2}"
          r"(à|a|de|na|pela)\s+(noite|madrugada)"
          r"|(noite|madrugada)\s+(\w+\s+){0,2}(escrevendo|redigindo|fazendo)\s+(o\s+|os\s+)?laudos?",
          "persona sem fonte",
          "Cortar. Para a rotina da fiscal, só o que tem fonte (ex.: pesquisa MAPA \"Perfil dos Peritos\": "
          "76% relatam intimidação, peritos de perda, coleta de 2021).",
          ("escreve o laudo à noite", "um laudo escrito à noite", "laudo escrito de madrugada",
           "passa a noite escrevendo laudo", "LAUDOS ESCRITOS À NOITE"),
          limpos=("calcular o teste de 72 h à noite",)),
    Regra("P16", "roda de 50 a 200 km",
          r"\b50\s+a\s+200\s*(km|quil)|\bdezenas\s+de\s+(km|quil[oô]metros)"
          r"|\broda\w*\s+(at[eé]\s+|cerca\s+de\s+|mais\s+de\s+)?\d+(\s+a\s+\d+)?\s*(km|quil)",
          "persona sem fonte",
          "Cortar.",
          ("roda de 50 a 200 km por visita", "roda dezenas de quilômetros por visita",
           "roda 150 km por visita", "dirige dezenas de km")),
    Regra("P17", "\"conversamos com N pessoas\", o slide \"O que ouvimos\", \"entrevistamos\" e "
          "\"testamos preço\"",
          r"\bconversamos\s+com\b|\bj[aá]\s+conversamos\b|\bouvimos\b|\bentrevistamos\b"
          r"|\bfalamos\s+com\s+(\w+\s+){0,2}(pessoas|fiscais|t[eé]cnic[oa]s|gerentes|cooperativas"
          r"|credenciadas|agr[oô]nom[oa]s|produtores|bancos|clientes|especialistas|peritos|analistas)\b"
          r"|\btestamos\s+(\w+\s+){0,2}pre[cç]os?\b"
          r"|\b(testamos|validamos)\s+(\w+\s+){0,3}com\s+(\w+\s+)?(clientes?|cooperativas?"
          r"|credenciadas?|fiscais|usu[aá]rios|t[eé]cnic[oa]s|bancos?|mercado)\b(?!\s+simulad)"
          r"|\b(em|nas?)\s+(toda|todas\s+as|cada|nossas)\s+entrevistas?\s+(\w+\s+){0,2}"
          r"(test|pergunt|ouv|mostr|valid|confirm)\w*"
          r"|\b(fizemos|realizamos|conduzimos|tivemos|completamos|conclu[ií]mos|registramos|aplicamos)\s+"
          r"(\w+\s+){0,2}entrevistas?\b"
          r"|\b(nas|nossas|pelas|das)\s+(nossas\s+)?entrevistas?\b[\s,]+" + _P_VIRGULA + r"{0,3}"
          + _PASSADO_PLURAL
          + r"|\bentrevistas?\s+" + _P_VIRGULA + r"{0,3}(confirmaram|validaram|mostraram|apontaram"
          r"|revelaram|indicaram|comprovaram)\b"
          r"|\b(fiscais|t[eé]cnic[oa]s|gerentes|cooperativas|pessoas|produtores|agr[oô]nom[oa]s|credenciadas"
          r"|clientes|peritos)\s+(que\s+)?entrevistad[oa]s\b",
          "não há entrevista registrada (negocio/kit_validacao/registro_entrevistas.csv sem conversas); A/B "
          "com fiscal simulado, golden set, red-team e persona não são validação com usuário",
          "S2: \"O que o regulador, o auditor e o juiz escreveram, e o que os microdados do BCB "
          "mostram\". No "
          "Q&A: \"Não houve tempo para entrevistas registradas. Por isso só afirmamos o que está em registro "
          "oficial, e o script que gera cada número está no repositório.\"",
          ("Já conversamos com N pessoas que fiscalizam", "S2. O que ouvimos",
           "Por isso testamos preço em toda entrevista", "entrevistamos 12 fiscais", "falamos com 10 fiscais",
           "validamos o preço com cooperativas", "em cada entrevista confirmamos a dor",
           "ENTREVISTAMOS 12 FISCAIS", "Não só ouvimos fiscais como testamos preço",
           "Fizemos 12 entrevistas com fiscais", "Realizamos entrevistas com cooperativas",
           "nas entrevistas, os fiscais confirmaram a dor", "as entrevistas com fiscais mostraram a dor",
           "os fiscais entrevistados confirmaram a dor"),
          limpos=("Ainda não testamos preço com cliente: R$ 79 é preço-alvo.",
                  "toda entrevista termina pedindo 2 nomes (pergunta 14 do roteiro)",
                  "num teste com fiscal simulado, 97% das fiscalizações conciliadas",
                  "Hoje validamos coerência (datas, quantidades) contra NF-e e projeto.",
                  "Não conversamos com nenhum fiscal até agora.", "Nós não entrevistamos ninguém.",
                  "nunca testamos preço com cliente", "Ainda não fizemos entrevistas.",
                  "nas entrevistas que ainda não aconteceram, vamos perguntar o preço",
                  "Nas entrevistas, pergunte pelo preço."),
          negacao_antes=True),
    Regra("P18", "\"preço validado\", \"preço de lista\", \"preço testado com cliente\" ou \"aceito em "
          "entrevista\"",
          r"\bpre[cç]os?\s+" + _P + r"{0,2}(validad|confirmad|aprovad)[oa]s?\b"
          r"|\bpre[cç]os?\s+de\s+lista\b"
          r"|\bpre[cç]os?\s+" + _P + r"{0,2}(testad|aceit)[oa]s?\s+(com|em|por|pel[oa]s?|n[ao]s?)\s+"
          r"(\w+\s+)?"
          r"(clientes?|cooperativas?|credenciadas?|fiscais|entrevistas?|bancos?|IFs?|mercado|pilotos?"
          r"|usu[aá]rios)\b",
          "nenhum preço foi testado com cliente (\"preço testado\" só com o teste registrado)",
          "\"preço-alvo\"",
          ("preço validado com cooperativas", "preço de lista de R$ 79", "preço testado com cooperativas",
           "Preço aceito em entrevista: R$ 60", "PREÇOS VALIDADOS", "o preço foi validado com cooperativas",
           "o preço já foi testado com cooperativas"),
          limpos=("R$ 79 por fiscalização (preço-alvo, ainda não testado com cliente)",
                  "Os dois são preço-alvo: nenhum foi testado com cliente.",
                  "Não temos preço validado com cliente.", "o preço ainda não foi validado com cliente",
                  "Nenhum preço foi testado com cliente e não houve entrevistas registradas."),
          negacao_antes=True),
    Regra("P19", "R$ 79 sem \"preço-alvo\" na mesma linha",
          r"R\$\s*79(,00)?\b(?![.,]\d)(?!\s*(mil|mi\b|bi\b|milh|bilh))|\b79\s+reais\b"
          r"|\bsetenta\s+e\s+nove\s+reais\b",
          "R$ 79 é hipótese de preço, não preço validado",
          "\"preço-alvo de R$ 79 por fiscalização\"",
          ("Quem paga é a cooperativa: 79 reais por fiscalização", "| Preço | R$ 79 |",
           "R$ 79,00 por fiscalização", "R$79/fiscalização"),
          exceto_na_linha=r"pre[cç]os?[- ]alvo",
          limpos=("R$ 79,5 milhões em crédito", "R$ 79 mil de CAC", "preço-alvo de R$ 79 por fiscalização",
                  "PREÇO-ALVO DE R$ 79")),
    # P20 a P25 (noite de 16/10/2026, depois da r4): o texto que a r4 desmentiu não pode voltar. Fonte: plano
    # pós-r4, pacote P6 (dados_locais/plano/plano_pos_r4.json), com os diagnósticos e as contraprovas.
    Regra("P20", "\"concilia mais (fiscalizações) que o formulário\" e \"a IA concilia mais\"",
          r"\bconcili(?:a|am|ou|aram|aria|ariam)\s+mais\b"
          r"|\bmais\s+fiscaliza[cç](?:ao|oes)\s+conciliadas\b"
          r"|\bconcilia[cç][aã]o\s+maior\s+(?:do\s+)?que\s+(?:a\s+)?(?:do\s+)?formul[aá]rio",
          "no teste congelado (A/B v2 da r4), o agente não conciliou mais fiscalizações que o formulário: 19/24 "
          "contra 21/24 na comparação principal, sem a menção a item não financiado (p = 0,69), e 17/24 contra "
          "14/24 na completa (p = 0,51); o 35/36 do dev, conjunto em que o A/B foi desenvolvido, não se repetiu",
          "\"Contra um formulário digitado, com fiscal simulado e documentos e narrações sintéticos, o agente não "
          "conciliou mais fiscalizações no teste\" (números com as chaves ab2_teste.* de numeros.md); o ganho que "
          "se sustenta é no trabalho da fiscal, com o tempo modelado.",
          ("a IA concilia mais fiscalizações que o formulário",
           "O agente concilia mais fiscalizações que o formulário digitado.", "a IA concilia mais",
           "e \"concilia mais fiscalizações que o formulário\" vale nas duas comparações da tela",
           "confira que \"concilia mais\n   fiscalizações que o formulário\" continua valendo",
           "o agente conciliou mais fiscalizações no teste", "CONCILIA MAIS FISCALIZAÇÕES QUE O FORMULÁRIO",
           "mais fiscalizações conciliadas que o formulário"),
          limpos=("Contra um formulário digitado, o agente não conciliou mais fiscalizações no teste.",
                  "a IA não concilia mais que o formulário no teste congelado",
                  "o agente concilia a nota, a GTA e a contagem do curral"),
          negacao_antes=True),
    Regra("P21", "\"(nunca|não) afirma o que não tem prova\" sem a ressalva do cego na mesma linha ou frase",
          r"\b(?:nunca|n[aã]o|jamais)\s+(?:\w+\s+)?afirm(?:a|am|ou)\s+(?:nada\s+)?(?:o\s+|aquilo\s+)?(?:que\s+)?"
          r"(?:n[aã]o\s+(?:tem|t[eê]m|h[aá])\s+|sem\s+)(?:\w+\s+)?(?:provas?|evid[eê]ncias?|lastro)\b",
          "no red-team cego (v3, r4), três declarações viraram 'verificado' sem prova: um relato de terceiro, uma "
          "declaração retirada e um bilhete lido em voz alta; a frase absoluta é desmentida por um resultado "
          "publicado",
          "\"Não emite laudo sem evidência mínima e se abstém no ambíguo; no red-team cego, declarações de "
          "terceiro, retiradas ou lidas em voz alta viraram 'verificado' sem prova, e isso está publicado.\"",
          ("O agente nunca afirma o que não tem prova, se abstém quando deve.",
           "O agente não afirma o que não tem prova, se abstém e não emite laudo sem evidência mínima.",
           "nunca afirma nada sem prova", "NUNCA AFIRMA O QUE NÃO TEM PROVA",
           "O agente não afirma o que não tem prova.\nNo red-team cego, três declarações viraram 'verificado'.",
           "O agente nunca afirma o que não tem prova (o red-team não é cego)."),
          limpos=(("O agente não afirma o que não tem prova, com a ressalva do red-team cego: três declarações "
                   "viraram 'verificado' sem prova."),
                  "O agente nunca afirma o que não tem prova,\nexceto nas falhas publicadas do conjunto cego.",
                  "Não emite laudo sem evidência mínima e se abstém no ambíguo."),
          ressalva=_CEGO + r"|declara[cç](?:ao|oes)\s+(?:\w+\s+){0,4}(?:vir|pass)\w*"
                           r"|verificado\W{0,3}\s*sem\s+prova",
          ressalva_em="linha_ou_frase"),
    Regra("P22", "\"0/80\" ou \"red-team 0%\" sem o red-team cego no mesmo parágrafo",
          r"(?<![\d/.,])\b0\s*(?:/|de|em)\s*80\b(?![.,]\d)"
          r"|\bred[\s-]?teams?\b\s*:?\s+(?:\w+\s+){0,3}0\s*%"
          r"|(?<![\d.,])\b0\s*%\s+(?:de\s+|dos\s+)?ataques\b",
          "o 0/80 é do red-team escrito pela equipe junto com as correções; no conjunto cego, escrito de "
          "forma isolada e rodado uma vez, passaram 6/30 (6/26 sem a família semi-cega; 5/30 só com as "
          "guardas determinísticas): mostrar só o 0/80 é seletivo",
          "\"0/80 no red-team escrito pela equipe; no conjunto cego, escrito de forma isolada e rodado uma "
          "vez, 6/30 (6/26 sem a família semi-cega)\", com as chaves redteam.ataques e redteam.cego_* de "
          "numeros.md no mesmo parágrafo ou linha de tabela.",
          ("No red-team, 0 de 80 ataques passaram.", "Red-team: 0/80 ataques passaram.",
           "red-team 0% [0–5%] de ataques bem-sucedidos",
           "0/80 ataques passaram num red-team escrito pela equipe; falta um conjunto cego.",
           "O red-team também não é cego: 0/80 ataques passaram.",
           "Red-team da equipe: 0/80.\n\nNo red-team cego, 6/30.",
           "| Red-team da equipe | 0/80 |\n| Red-team cego | 6/30 |",
           "red-team <!--n:redteam.ataques.kn-->0/80<!--/n--> ataques",
           "red-team 0/80 ataques; red-team escrito pela equipe (não cego)",
           "0/80 ataques bem-sucedidos (casos escritos pela equipe, não cegos)"),
          limpos=(("0/80 no red-team da equipe; no conjunto cego, rodado uma vez, 6/30 (6/26 sem a família "
                   "semi-cega)."),
                  "Red-team da equipe: 0/80 ataques.\nNo red-team cego, passaram 6 de 30.",
                  "| Red-team | equipe 0/80; cego 6/30 |", "R$ 0,80 por foto; 10/80 páginas; 0/800 erros"),
          ressalva=_CEGO, ressalva_em="paragrafo"),
    Regra("P23", "\"papel e fala reais\"",
          r"\bpap[eé](?:l|is)\s+e\s+(?:a\s+)?falas?\s+reais\b"
          r"|\bfalas?\s+e\s+(?:o\s+)?pap[eé](?:l|is)\s+reais\b"
          r"|\b(?:fotos?|documentos?)\s+e\s+(?:falas?|narra[cç](?:ao|oes)|[aá]udios?)\s+reais\b"
          r"|\bpap[eé]l\s+real\s+e\s+(?:a\s+)?fala\s+real\b",
          "as fotos são desenhadas, os documentos são sintéticos (CNPJ e nomes de marcador) e as narrações são "
          "texto gerado (eval/golden/gerador/gerar_baguncados.py), sem áudio nem ASR; o fiscal é simulado "
          "(eval/README.md, Limitações)",
          "\"Papel fotografado e fala livre, sintéticos: fotos desenhadas, documentos e narrações gerados, com "
          "fiscal simulado.\"",
          ("Papel e fala reais: A/B v2, fiscal simulado", "Com papel e fala reais: o agente concilia",
           "fotos e falas reais", "PAPEL E FALA REAIS",
           "| A/B de centralidade (fiscal simulado; papel e fala reais) |"),
          limpos=("papel fotografado e fala livre, sintéticos, com fiscal simulado",
                  "não são papel e fala reais: as fotos são desenhadas e as narrações, geradas",
                  "documentos e narrações sintéticos"),
          negacao_antes=True),
    Regra("P24", "número do dev (3904/3916, 97% × 42%, 35/36, 71/72, 38/41) numa frase que fala do teste (\"no "
          "teste\", \"num teste\", \"teste congelado\") e sem \"dev\"",
          _NUM_DEV,
          "esses números são do dev, conjunto em que o A/B v2 foi desenvolvido; no teste congelado, os "
          "equivalentes são 2533/2541 (campos aceitos certos), 40/46 × 32/46 (fala), 31/32 (residual) e 19/24 × "
          "21/24 (conciliação sem a menção); o número do dev numa frase sobre o teste é o texto seletivo que a r4 "
          "desmentiu",
          "O número do teste, com a chave ab2_teste.* de numeros.md (\"no teste congelado, dos campos que as "
          "regras aceitaram, 2533 de 2541 estavam certos\"); o do dev, só com \"dev\" na mesma frase.",
          ("dos campos aceitos no teste, 3904/3916 estavam certos", "No teste congelado, 97% × 42%.",
           ("No teste congelado, <!--n:ab2.residual.valor-->97%<!--/n--> × "
            "<!--n:ab2.formulario.valor-->42%<!--/n-->."),
           "no teste, o LLM deu o status certo a 71/72 alegações",
           "Num teste com fiscal simulado, 97% contra 42%.",
           "38/41 dos documentos com pedido fecharam no teste", "No teste: conciliado em 35 de 36.",
           ("Num teste com fiscal simulado, a IA levou <!--n:ab2.residual.valor-->97%<!--/n--> das fiscalizações"
            " ao\n   conteúdo conciliado, contra <!--n:ab2.formulario.valor-->42%<!--/n--> digitando.")),
          limpos=("No dev, 97% × 42%; no teste congelado, 19/24 contra 21/24.",
                  "No teste congelado, dos campos aceitos, 2533 de 2541 estavam certos (no dev, 3904/3916).",
                  "3904/3916 dos campos aceitos estavam certos no dev.",
                  "O 35 de 36 do dev não se repetiu no teste.",
                  "Leitura: 3904/3916. Isso foi antes do teste congelado."),
          ressalva=r"\bdev\b|\bdesenvolv\w*", ressalva_em="frase",
          # "teste" como palavra ("no teste", "num teste com fiscal simulado", "Teste com fiscal simulado:",
          # "teste congelado"); "testado" e "testamos" não contam
          exige_na_frase=r"\btestes?\b"),
    Regra("P25", "\"por desenho, o LLM não escolhe\" (as checagens) e \"o plano determinístico escolhe as "
          "checagens\"",
          r"\bpor\s+desenho,?\s+(?:o\s+llm|ele|o\s+modelo|a\s+ia)\s+n[aã]o\s+escolhe"
          r"|\b(?:llm|modelo)\s+n[aã]o\s+escolhe\s+(?:as\s+|quais\s+)?(?:checagens|ferramentas)"
          r"|\bplano\s+(?:m[ií]nimo\s+)?determin[ií]stico\s+(?:\w+\s+)?(?:escolhe|decide)\w*\b"
          r"|\bquem\s+(?:escolhe|decide)\s+(?:as\s+|quais\s+)?checagens\s+[eé]\s+o\s+plano",
          "contradiz o condutor: o LLM recebe as ferramentas de checagem da etapa (fsm.nomes_permitidos) e as "
          "chama; o plano mínimo determinístico só roda quando ele não chama a checagem óbvia; por desenho, o que "
          "não é do LLM é o status, que vem sempre das regras e do verificador (armadilha A-16)",
          "\"O LLM pode chamar as checagens da etapa; quando não chama a óbvia, o plano mínimo determinístico "
          "chama; o status vem sempre das regras e do verificador, e o humano assina.\"",
          ("Por desenho, o LLM não escolhe as checagens nem dá o status",
           "isso, por desenho, ele não escolhe: o plano determinístico decide as checagens",
           "o plano determinístico escolhe as checagens a partir do que chega",
           "o plano determinístico decide o que checar a partir do que chega",
           "quem escolhe as checagens é o plano determinístico", "o LLM não escolhe as checagens",
           "\"o plano determinístico escolhe, o verificador dá o status, o humano assina\""),
          limpos=(("O LLM pode chamar as checagens da etapa; quando não chama a óbvia, o plano mínimo "
                   "determinístico chama."),
                  "o LLM não decide o status: ele vem das regras e do verificador", "o LLM não escolhe o status")),
)


@dataclass(frozen=True)
class ExcecaoNormativa:
    """Termo citado da norma que o produto reproduz: passa só nos caminhos de `onde` (e nos .zip deles)."""

    regra: str
    padrao: str  # o termo, como a norma e o rulebook o escrevem (os acentos caem antes de compilar)
    onde: tuple[str, ...]  # prefixos do caminho relativo (o mesmo de `_relativo`)
    motivo: str
    rx: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rx", re.compile(sem_acento(self.padrao), re.IGNORECASE))


EXCECOES_NORMATIVAS: tuple[ExcecaoNormativa, ...] = (
    # O rulebook (src/laudo/rulebooks/mcr_2_7.yaml, regra MCR-2-7-item21-comunicacao-ilicitos) tem o título
    # "Ilícito penal ou fraude fiscal: IF comunica MP/autoridade tributária", e o laudo e o pacote de exemplo o
    # reproduzem. É o texto do MCR 2-7, item 21 ("ilícitos penais ou fraudes fiscais", docs/normas/mcr_2_7.md), e
    # não uma acusação a operação; o src/ não muda depois da r4 (plano pós-r4, P6 e P7).
    ExcecaoNormativa("P08", r"il[ií]citos?\s+pena(?:l|is)\s+ou\s+(?:de\s+)?fraudes?\s+fisca(?:l|is)",
                     ("docs/exemplos/",),
                     "termo normativo do MCR 2-7, item 21, citado do rulebook no exemplo gerado"),
)


@dataclass(frozen=True)
class Achado:
    arquivo: str
    linha: int
    regra: Regra
    trecho: str
    liberado: bool  # linha com <!--cita-proibida-->, ou termo normativo (`EXCECOES_NORMATIVAS`)
    nota: str = ""  # por que foi liberado, quando não foi pelo marcador


def _esconder(texto: str) -> str:
    """Troca tags, comentários, URLs, `*`, `_`, `~` e crases por espaços do mesmo tamanho."""
    return _RX_ESCONDER.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), texto)


def normalizar(texto: str) -> str:
    """O texto em que as regras casam: escondido (`_esconder`) e sem acento, com as posições de antes."""
    return sem_acento(_esconder(texto))


def _negada(texto: str, ini: int, fim: int) -> bool:
    """A frase `texto[ini:fim]` vem logo depois de uma negação ("não", "nunca", "jamais", "nem", "nenhum",
    "nenhuma", com até 2 palavras entre elas)? `texto` começa no início da linha. "Não só", "não apenas" e
    "não somente" não contam."""
    antes = texto[:ini]
    for n in _RX_NEGADOR.finditer(antes):
        if _RX_LACUNA_NEGACAO.fullmatch(antes, n.end()) and not _RX_NAO_SO.match(texto[:fim], n.end()):
            return True
    return False


def _unidades(linhas: list[str]) -> list[tuple[int, int]]:
    """(primeira, última) linha da unidade de contexto de cada linha: o parágrafo (linhas seguidas sem linha em
    branco), mas cada item de lista e cada título abrem uma unidade nova, e a linha de tabela é uma sozinha."""
    grupos: list[list[int]] = []
    aberto = ant_tabela = False
    for k, ln in enumerate(linhas):
        if not ln.strip():
            grupos.append([k])
            aberto = ant_tabela = False
            continue
        tabela = ln.lstrip().startswith("|")
        if not aberto or tabela or ant_tabela or _RX_INICIO_UNIDADE.match(ln):
            grupos.append([k])
            aberto = True
        else:
            grupos[-1].append(k)
        ant_tabela = tabela
    lim = [(0, 0)] * len(linhas)
    for g in grupos:
        for k in g:
            lim[k] = (g[0], g[-1])
    return lim


def _frase(plano: str, u0: int, u1: int, ini: int, fim: int) -> str:
    """A frase do trecho `plano[ini:fim]`, dentro da unidade `plano[u0:u1]`."""
    a = u0
    for f in _RX_FIM_FRASE.finditer(plano, u0, ini):
        a = f.end()
    f = _RX_FIM_FRASE.search(plano, fim, u1)
    return plano[a:f.end() if f else u1]


def _tem_ressalva(rx: re.Pattern, contexto: str) -> bool:
    """A ressalva aparece no contexto sem negação logo antes? ("não é cego" e "falta um conjunto cego" não valem.)"""
    return any(not _RX_NEGA_RESSALVA.search(contexto[max(0, m.start() - 60):m.start()])
               for m in rx.finditer(contexto))


def _excecao_normativa(r: Regra, arquivo: str, plano: str, a: int, b: int, ini: int,
                       fim: int) -> ExcecaoNormativa | None:
    """O trecho `plano[ini:fim]` está dentro de um termo normativo aceito para este arquivo (linha `plano[a:b]`)?"""
    for ex in EXCECOES_NORMATIVAS:
        if (ex.regra == r.id and arquivo.startswith(ex.onde)
                and any(m.start() <= ini and fim <= m.end() for m in ex.rx.finditer(plano, a, b))):
            return ex
    return None


def achados_no_texto(texto: str, arquivo: str = "<texto>") -> Iterator[Achado]:
    """Os achados de `texto`; `arquivo` é o caminho relativo (decide as exceções por caminho). Um achado por
    linha, regra e situação (acusado ou liberado)."""
    linhas = texto.split("\n")
    inicio = [0]
    for ln in linhas:
        inicio.append(inicio[-1] + len(ln) + 1)
    visivel = _esconder(texto)  # para mostrar o trecho com acento
    plano = sem_acento(visivel)
    planas = plano.split("\n")
    uni: list[tuple[int, int]] | None = None  # só calculadas se uma regra de contexto casar
    vistos: set[tuple[int, str, bool]] = set()
    for r in REGRAS:
        for m in r.rx.finditer(plano):
            i = bisect.bisect_right(inicio, m.start()) - 1
            j = bisect.bisect_right(inicio, max(m.end() - 1, m.start())) - 1
            if r.rx_exceto and any(r.rx_exceto.search(planas[k]) for k in range(i, j + 1)):
                continue
            if r.negacao_antes and _negada(plano[inicio[i]:m.end()], m.start() - inicio[i],
                                           m.end() - inicio[i]):
                continue
            if r.de_contexto:
                if arquivo in REGISTRO_DE_CHAVES:
                    continue
                if uni is None:
                    uni = _unidades(planas)
                u0, u1 = inicio[uni[i][0]], inicio[uni[j][1] + 1] - 1
                frase = _frase(plano, u0, u1, m.start(), m.end())
                if r.rx_exige and not r.rx_exige.search(frase):
                    continue
                if r.rx_ressalva:
                    ctx = {"paragrafo": plano[u0:u1], "frase": frase,
                           "linha_ou_frase": frase + "\n" + plano[inicio[i]:inicio[j + 1] - 1]}[r.ressalva_em]
                    if _tem_ressalva(r.rx_ressalva, ctx):
                        continue
            liberado, nota = any(MARCA_EXCECAO in linhas[k] for k in range(i, j + 1)), ""
            if not liberado:
                ex = _excecao_normativa(r, arquivo, plano, inicio[i], inicio[j + 1] - 1, m.start(), m.end())
                if ex:
                    liberado, nota = True, ex.motivo
            if (i, r.id, liberado) in vistos:
                continue
            vistos.add((i, r.id, liberado))
            a, b = max(m.start() - 40, inicio[i]), min(m.end() + 40, inicio[j + 1] - 1)
            trecho = " ".join(visivel[a:b].split())
            yield Achado(arquivo, i + 1, r, trecho, liberado, nota)


def arquivos(raizes: list[Path]) -> Iterator[Path]:
    for raiz in raizes:
        if raiz.is_file():
            yield raiz
            continue
        for p in sorted(raiz.rglob("*")):
            if (p.is_file() and (p.suffix.lower() in EXTENSOES or p.suffix.lower() == ".zip")
                    and not EXCLUIR_DIRS.intersection(p.relative_to(raiz).parts)
                    and p.resolve() != LISTA.resolve()):
                yield p


def _relativo(p: Path) -> str:
    p = p.resolve()
    for base, prefixo in ((REPO, ""), (REPO.parent, "../")):
        try:
            return prefixo + p.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return p.as_posix()


def textos_do_zip(fonte: Path | io.BytesIO, nome: str) -> Iterator[tuple[str, str]]:
    """(`nome!caminho`, texto) de cada arquivo de texto dentro do .zip; imagens e binários ficam de fora. Um .zip
    ilegível levanta zipfile.BadZipFile (o `main` sai com 2: o portão não passa sem ler o pacote)."""
    with zipfile.ZipFile(fonte) as z:
        for info in z.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in EXTENSOES_NO_ZIP:
                continue
            try:
                yield f"{nome}!{info.filename}", z.read(info).decode("utf-8")
            except UnicodeDecodeError:
                continue


def textos(raizes: list[Path]) -> Iterator[tuple[str, str]]:
    """(caminho relativo, texto) de cada arquivo varrido; um .zip entra pelo texto de dentro."""
    for p in arquivos(raizes):
        nome = _relativo(p)
        if p.suffix.lower() == ".zip":
            yield from textos_do_zip(p, nome)
            continue
        try:
            yield nome, p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def varrer(raizes: list[Path]) -> list[Achado]:
    out: list[Achado] = []
    for nome, texto in textos(raizes):
        out += achados_no_texto(texto, nome)
    return sorted(out, key=lambda a: (a.arquivo, a.linha, a.regra.id))


def autoteste() -> list[str]:
    """Cada exemplo é acusado pela sua regra; nenhum "diga no lugar" nem frase certa (`limpos`) é acusado."""
    erros = []
    ids = [r.id for r in REGRAS]
    if len(set(ids)) != len(ids):
        erros.append("ids de regra repetidos")
    for r in REGRAS:
        for ex in r.exemplos:
            if not any(a.regra.id == r.id for a in achados_no_texto(ex)):
                erros.append(f"{r.id}: o exemplo não foi acusado: {ex!r}")
        for a in achados_no_texto(r.diga.replace("R$ 79", "R$ 79 (preço-alvo)")):
            erros.append(f"{r.id}: o \"diga no lugar\" foi acusado pela {a.regra.id}: {a.trecho!r}")
        for limpo in r.limpos:
            for a in achados_no_texto(limpo):
                erros.append(f"{r.id}: a frase certa {limpo!r} foi acusada pela {a.regra.id}")
    if not any(a.liberado for a in achados_no_texto(f"pergunta: \"quantas fraudes?\" {MARCA_EXCECAO}")):
        erros.append("o marcador de exceção não libera a linha")
    if list(achados_no_texto("preço-alvo de R$ 79 por fiscalização")):
        erros.append("P19 acusou R$ 79 com preço-alvo na linha")
    if list(achados_no_texto("<!--n:x-->1,00<!--/n--> em 24 casos; prioridade de verificação")):
        erros.append("texto limpo acusado")
    if list(achados_no_texto("([fonte](https://exemplo.invalid/boi-de-papel-fraude-deixa-prejuizo/))")):
        erros.append("URL da fonte acusada")
    if not list(achados_no_texto("ninguém **concilia** no curral")):
        erros.append("negrito no meio da frase escondeu a P01")
    amostra = "Ação, conciliação e satélite: ÇÃO 🐄 ñ"
    if len(normalizar(amostra)) != len(amostra) or "satelite" not in normalizar(amostra):
        erros.append("a normalização mudou o tamanho do texto ou não tirou o acento")
    erros += _autoteste_zip_e_excecoes()
    if LISTA.exists():  # a lista para quem ensaia tem de trazer as mesmas regras (no CI ela não existe)
        texto = LISTA.read_text(encoding="utf-8")
        erros += [f"{r.id} não aparece em {_relativo(LISTA)}" for r in REGRAS if f"| {r.id} |" not in texto]
    return erros


def _autoteste_zip_e_excecoes() -> list[str]:
    """O texto de dentro do .zip é varrido, a exceção normativa vale só em docs/exemplos/ e só para o termo, e o
    registro de chaves fica fora das regras de contexto."""
    erros = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fundamento/f.json", '{"t": "a prova que falta nas fraudes do tipo boi de papel"}')
        z.writestr("evidencias/foto.jpg", "fraude")
    buf.seek(0)
    achados = [(a.arquivo, a.regra.id) for nome, t in textos_do_zip(buf, "docs/exemplos/x.zip")
               for a in achados_no_texto(t, nome)]
    if achados != [("docs/exemplos/x.zip!fundamento/f.json", "P08")]:
        erros.append(f"o texto de dentro do .zip não foi varrido como devia: {achados}")
    norma = "Ilícito penal ou fraude fiscal: IF comunica MP/autoridade tributária"
    no_exemplo = list(achados_no_texto(norma, "docs/exemplos/x.zip!pacote.json"))
    if not no_exemplo or not all(a.liberado and a.nota for a in no_exemplo):
        erros.append("o termo normativo do MCR 2-7, item 21, não foi liberado em docs/exemplos/")
    if not any(a.regra.id == "P08" and not a.liberado for a in achados_no_texto(norma, "docs/entregaveis/x.md")):
        erros.append("o termo normativo foi liberado fora de docs/exemplos/")
    if not any(not a.liberado for a in achados_no_texto(norma + "; fraudes do tipo boi de papel",
                                                         "docs/exemplos/laudo.html")):
        erros.append("a exceção normativa liberou outra 'fraude' na mesma linha")
    if list(achados_no_texto("| `redteam.ataques` | 0% [0–5%] (0/80) | 0 de 80 |", REGISTRO_DE_CHAVES[0])):
        erros.append("o registro de chaves foi acusado por regra de contexto")
    return erros


def ids_de(spec: str) -> set[str]:
    """IDs de regra de uma lista com faixas ("P20-P25,P08"); ValueError se algum não existir."""
    existentes = {r.id for r in REGRAS}
    out: set[str] = set()
    for parte in filter(None, (p.strip().upper() for p in spec.split(","))):
        if "-" in parte:
            a, b = (int(x.strip().lstrip("P")) for x in parte.split("-", 1))
            out |= {f"P{n:02d}" for n in range(a, b + 1)}
        else:
            out.add(parte)
    if not out or out - existentes:
        faltam = ", ".join(sorted(out - existentes)) or repr(spec)
        raise ValueError(f"regra que não existe: {faltam}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caminhos", nargs="*",
                    help="arquivos ou diretórios (padrão: os textos públicos e ../negocio)")
    ap.add_argument("--regras", action="store_true", help="lista as regras e sai")
    ap.add_argument("--excecoes", action="store_true",
                    help="mostra também as linhas liberadas (<!--cita-proibida--> e termo normativo)")
    ap.add_argument("--autoteste", action="store_true", help="confere as regras contra os exemplos e sai")
    ap.add_argument("--so", metavar="IDS", help="só estas regras, em lista e faixas (ex.: P20-P25,P08)")
    ap.add_argument("--relatorio", action="store_true",
                    help="modo relatório: lista os achados, resume por regra e por arquivo e sai com 0")
    a = ap.parse_args(argv)
    try:
        so = ids_de(a.so) if a.so else None
    except ValueError as e:
        ap.error(str(e))
    if a.regras:
        for r in REGRAS:
            if so is None or r.id in so:
                ctx = ""
                if r.de_contexto:
                    onde = {"frase": "na frase", "linha_ou_frase": "na linha ou na frase",
                            "paragrafo": "no parágrafo (ou na linha de tabela)"}[r.ressalva_em]
                    exige = "só numa frase que fala do teste; " if r.exige_na_frase else ""
                    ctx = f"\n      contexto: {exige}passa com a ressalva {onde}"
                print(f"{r.id}  {r.frase}\n      por quê: {r.motivo}\n      diga: {r.diga}{ctx}")
        return 0
    if a.autoteste:
        erros = autoteste()
        for e in erros:
            print("ERRO:", e)
        print(f"autoteste: {len(REGRAS)} regras, {sum(len(r.exemplos) for r in REGRAS)} exemplos que têm de "
              f"ser acusados, {sum(len(r.limpos) for r in REGRAS)} frases certas que não podem ser; "
              f"{len(erros)} erro(s)")
        return 2 if erros else 0
    if a.caminhos:
        raizes = [Path(c) if Path(c).is_absolute() else Path.cwd() / c for c in a.caminhos]
        faltam = [str(p) for p in raizes if not p.exists()]
        if faltam:
            print("caminho não existe:", *faltam, file=sys.stderr)
            return 2
    else:
        raizes = [p for p in RAIZES_PADRAO if p.exists()]
        pulados = [_relativo(p) for p in RAIZES_PADRAO if not p.exists()]
        if pulados:
            print("pulado (não existe aqui):", ", ".join(pulados))
    try:
        lidos = list(textos(raizes))
    except zipfile.BadZipFile as e:
        print(f"ERRO: .zip ilegível; a varredura não passa sem ler o pacote: {e}", file=sys.stderr)
        return 2
    todos = sorted((x for nome, texto in lidos for x in achados_no_texto(texto, nome)
                    if so is None or x.regra.id in so),
                   key=lambda x: (x.arquivo, x.linha, x.regra.id))
    achados = [x for x in todos if not x.liberado]
    liberados = [x for x in todos if x.liberado]
    for x in achados:
        print(f"{x.arquivo}:{x.linha}: [{x.regra.id}] {x.regra.frase}\n    trecho: {x.trecho}\n"
              f"    diga: {x.regra.diga}")
    if a.excecoes:
        for x in liberados:
            por = f": {x.nota}" if x.nota else ""
            print(f"(liberado{por}) {x.arquivo}:{x.linha}: [{x.regra.id}] {x.trecho}")
    if a.relatorio:
        print("\nresumo por regra:")
        for r in REGRAS:
            n = sum(x.regra.id == r.id for x in achados)
            if n:
                print(f"  {r.id}: {n} linha(s)")
        print("resumo por arquivo:")
        por_arquivo: dict[str, list[str]] = {}
        for x in achados:
            por_arquivo.setdefault(x.arquivo, []).append(f"{x.linha} [{x.regra.id}]")
        for nome, ls in por_arquivo.items():
            print(f"  {nome}: {', '.join(ls)}")
    n_regras = len(so) if so is not None else len(REGRAS)
    print(f"{len(lidos)} texto(s) varrido(s), {n_regras} regras: {len(achados)} frase(s) proibida(s); "
          f"{len(liberados)} linha(s) liberada(s) (com {MARCA_EXCECAO} ou termo normativo)")
    return 0 if a.relatorio or not achados else 1


if __name__ == "__main__":
    sys.exit(main())
