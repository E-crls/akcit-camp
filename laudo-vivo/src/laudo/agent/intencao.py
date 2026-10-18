"""Intenção da fala do fiscal, sem LLM: pressão (com grau de certeza), ruído do ASR e comandos humanos.

Três perguntas determinísticas, feitas antes do LLM:

1. **Pressão (POL-07).** A fala pede para alterar um valor ou status já checado sem nova evidência?
   `classificar_pressao` devolve:
   - `forte`: pedido claro, com verbo de alteração e alvo de valor ou status ("marca 40", "bota o número do
     projeto", "coloca como verificado"), dispensa da divergência ("deixa passar essa diferença"), aprovação a
     pedido ("aprova aí") ou laudo com valor imposto ("gera o rascunho com as 40 cabeças");
   - `incerta`: há sinal, mas falta o alvo ou o contexto é ambíguo ("o gerente já aprovou", "corrige a
     contagem", "o certo é quarenta", "vou marcar 40 no caderno", "não precisa filmar");
   - `None`: não é pressão ("o banco pediu as fotos", "vou marcar 3 pontos de GPS", "a cooperativa quer saber
     quando fica pronto").
   Só `forte` grava a ocorrência "pressao" na cadeia imutável. `incerta` só pede esclarecimento: nada é
   gravado como pressão (um falso positivo na cadeia imutável não se apaga).
2. **Ruído.** Transcrição sem conteúdo (silêncio, "[inaudível]", hesitações, fragmentos) ou com confiança baixa
   do ASR: o agente pede para repetir e não interpreta nada (nem alegação, nem ação).
3. **Comando humano.** Emitir o rascunho e enviar para assinatura são ações exclusivamente humanas: só
   acontecem por comando explícito reconhecido aqui (ou pelo botão da interface), nunca por decisão do LLM.

Texto normalizado (minúsculas, sem acento) em todas as regras. Na dúvida entre `forte` e `incerta`, a regra
escolhe `incerta`: pedir esclarecimento custa uma frase; gravar pressão falsa custa a credibilidade do laudo.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from laudo.agent.declaracoes import norm

Grau = Literal["forte", "incerta"]

# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------

_UNID = (r"(?:dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|quatorze|catorze|quinze|"
         r"dezesseis|dezessete|dezoito|dezenove)")
_DEZ = r"(?:vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa)"
_CEM = (r"(?:cem|cento|duzent[oa]s|trezent[oa]s|quatrocent[oa]s|quinhent[oa]s|seiscent[oa]s|setecent[oa]s|"
        r"oitocent[oa]s|novecent[oa]s|mil)")
_PAL = rf"(?:{_CEM}|{_DEZ}|{_UNID})"
# "um/uma" ficam de fora: são artigos na maior parte das falas ("coloca uma observação").
NUMERO = rf"(?:\d+(?:[.,]\d+)?|{_PAL}(?:\s+e\s+(?:{_PAL}|um|uma))*)"

# Verbos de alteração (imperativo, infinitivo e subjuntivo: "marca", "marcar", "marque").
_VERBO = (
    r"(?:marca|marcar|marque|coloca|colocar|coloque|poe|ponha|bota|botar|bote|lanca|lancar|lance|escreve|"
    r"escrever|escreva|registra|registrar|registre|anota|anotar|anote|considera|considerar|considere|deixa|"
    r"deixar|deixe|muda|mudar|mude|altera|alterar|altere|troca|trocar|troque|atualiza|atualizar|atualize|"
    r"corrige|corrigir|corrija|arredonda|arredondar|arredonde|ajusta|ajustar|ajuste|aumenta|aumentar|aumente|"
    r"sobe|subir|suba|completa|completar|complete|iguala|igualar|iguale|fecha|fechar|feche|passa|passar|"
    r"passe|preenche|preencher|preencha|digita|digitar|digite|informa|informar|informe|joga|jogar|jogue|"
    r"crava|cravar|crave)"
)
# "pôr" perde o acento na normalização e vira a preposição "por": só conta depois de um modal.
_VERBO_POR = r"(?:pode|manda|mandou|mandaram|quer|queria|tem que|e so|da pra|da para|vai|vou|vamos) por"

_ALVO_STATUS = (
    r"(?:verificad\w*|aprovad\w*|regularizad\w*|tudo certo|tudo ok|ok\b|sem divergencia|sem pendencia\w*|"
    r"conforme\b(?!\s+(?:o|a|os|as|esta|ta|foi|mostr\w*|diz|pede|manda|combinad\w*|aparece|o video)))"
)
_STATUS_COMO = (r"como\s+(?:verificad\w*|conforme|aprovad\w*|ok\b|cert[oa]|regular\w*|conferid\w*|concluid\w*|"
                r"resolvid\w*|corret[oa]|complet[oa]|valid[oa]|batid[oa]|liberad\w*)")
_ALVO_REF = (
    r"(?:(?:numero|valor|quantidade|total|contagem|qtd)\s+(?:certo\s+|correto\s+)?(?:do|da|de|que esta no|"
    r"que ta no|que veio n[oa])\s+(?:projeto|nota|nf-?e|gta|financiamento|contrato|cedula|sicor|banco|"
    r"cooperativa)"
    r"|\b(?:o|a)\s+(?:do|da)\s+(?:projeto|nota|nf-?e|gta|contrato|cedula|sicor)\b"
    r"|(?:numero|valor|quantidade|total)\s+(?:financiad[oa]|contratad[oa]|esperad[oa]|projetad[oa])"
    r"|o que (?:esta|ta|foi|veio) (?:no projeto|na nota|financiado|contratado))"
)
# Substantivos que, logo depois de um número, mostram que ele não é valor checado ("3 pontos de GPS").
_NEUTRO = (r"(?:pontos?|fotos?|imagens?|videos?|filmage\w+|minutos?|min\b|horas?|h\b|segundos?|vezes|dias?|"
           r"semanas?|km\b|quilometros?|coordenadas?|angulos?|lados?|fios?|mouroes|mourao|estacas?|graus?|"
           r"passos?|copias?|paginas?|folhas?|tentativas?|porteiras?|lotes?|cantos?|pontas?)")
_UNIDADE = (r"(?:cabecas?|animais|animal|bois|boi|vacas?|novilh\w+|garrot\w+|bezerr\w+|reses|bovinos?|"
            r"matrizes|%|por cento|metros?|m\b|hectares?|ha\b|reais|mil reais)")
_DESTINO_NEUTRO = re.compile(
    rf"^\s*(?:{_UNIDADE}\s+)?(?:(?:no|na|nos|nas|pro|pra|pelo|pela|para o|para a|ate o|ate a)\s+"
    r"(?:brete|corredor|curral|tronco|fila|caminhao|embarcadouro|balanca|seringa|mangueira)\b"
    r"|(?:pra|para)\s+(?:filmar|fotografar|contar|conferir|passar|gravar))"
)
_ANTES_AUTOALEGACAO = re.compile(
    r"\b(?:contei|contamos|vi|vimos|medi|medimos|filmei|conferi|deu|sao|tem|tinha|havia|estavam|tinham)\s+"
    r"(?:\w+\s+)?$"
)
_PRIMEIRA_PESSOA = re.compile(r"\b(?:eu|vou|vamos|a gente vai|preciso|precisamos|tenho que|temos que)\s+"
                              r"(?:\w+\s+)?$")
_AUTOCORRECAO = re.compile(
    r"\b(?:o que eu (?:disse|falei)|minha fala|eu errei|me enganei|me confundi|falei errado|disse errado|"
    r"corrigindo o que)\b"
)
_NEG_ANTES = re.compile(r"\b(?:nao|nem|nunca)\s+(?:\w+\s+)?$")

# Padrões completos (texto normalizado)
_RX_VERBO = re.compile(rf"\b{_VERBO}\b|\b{_VERBO_POR}\b")
_RX_ALVO = re.compile(rf"(?P<num>(?<![\w.,]){NUMERO}\b)|(?P<status>{_STATUS_COMO}|{_ALVO_STATUS})|(?P<ref>{_ALVO_REF})")
_FORTES: list[tuple[str, re.Pattern]] = [
    ("dispensa_divergencia", re.compile(
        r"\b(?:deixa|deixar|deixe|pode)\s+(?:isso\s+|essa diferenca\s+|a diferenca\s+|essa divergencia\s+)?"
        r"passar\b")),
    ("dispensa_divergencia", re.compile(
        r"\b(?:ignora|ignorar|ignore|esquece|esquecer|esqueca|releva|relevar|releve|desconsidera|desconsiderar|"
        r"desconsidere|abona|abonar|abone|perdoa|perdoar)\s+(?:a\s+|essa\s+|esta\s+|o\s+|esse\s+)?"
        r"(?:diferenca|divergencia|pendencia\w*|falta)")),
    ("aprovacao_a_pedido", re.compile(
        r"\b(?:aprova|aprove|aprovar|libera|libere|liberar|valida|valide|validar|homologa|homologue)\s+"
        r"(?:ai|logo|assim|mesmo assim|isso|esse item|o item|a contagem|a quantidade|tudo|sem\b)")),
    ("aprovacao_a_pedido", re.compile(
        r"\b(?:da|dar|de|dou|considera\w*|tom[ae]|tomar|conclui\w*|conclua|finaliza\w*|fecha\w*|marca\w*|"
        rf"coloca\w*|bota\w*|registra\w*|deixa\w*|poe|ponha)\s+(?:\w+\s+){{0,2}}{_STATUS_COMO}")),
    ("ordem_de_autoridade", re.compile(
        r"\b(?:gerente|diretor|chefe|superintendente|coordenador|banco|cooperativa|agencia|supervisor)\b"
        r"[^.?!;]{0,25}\bmand(?:ou|aram|a)\s+(?:passar|liberar|aprovar|fechar|considerar|deixar passar)")),
    ("laudo_com_valor", re.compile(
        rf"\b(?:laudo|rascunho|relatorio|sistema)\s+(?:com|marcando|dizendo|constando|mostrando)\s+"
        rf"(?:as\s+|os\s+|o\s+|a\s+)?(?:{NUMERO}\b|{_ALVO_STATUS})")),
]
_INCERTAS: list[tuple[str, re.Pattern]] = [
    ("autoridade_sem_alvo", re.compile(
        r"\b(?:gerente|diretor|chefe|superintendente|coordenador|banco|cooperativa|agencia|analista|supervisor|"
        r"dono|patrao|produtor)\b[^.?!;]{0,25}\b(?:autorizou|autorizaram|aprovou|aprovaram|liberou|liberaram|"
        r"dispensou|ja (?:conferiu|viu|checou|aprovou|liberou|sabe)|disse que (?:pode|ta|esta|e) (?:ok|certo|"
        r"bom|tranquilo|liberado))")),
    ("alteracao_sem_alvo", re.compile(
        r"\b(?:corrige|corrigir|corrija|muda|mudar|mude|altera|alterar|altere|troca|trocar|troque|atualiza|"
        r"atualizar|atualize|ajusta|ajustar|ajuste|arredonda|arredondar|arredonde)\s+(?:a\s+|o\s+|esse\s+|"
        r"essa\s+|este\s+|esta\s+)?(?:contagem|quantidade|numero|valor|total|status|resultado|campo|"
        r"divergencia|laudo)")),
    ("valor_alternativo", re.compile(
        rf"\b(?:o|a)\s+(?:certo|correto|real|verdadeiro|numero certo|valor certo|quantidade certa|numero "
        rf"correto|valor correto|quantidade correta)\s+(?:mesmo\s+)?(?:e|sao|seria)\s+(?:{NUMERO}\b|"
        rf"{_ALVO_REF})"
        rf"|\bna verdade\s+(?:sao|e|tem|tinha|havia|deu)\s+{NUMERO}\b"
        r"|\b(?:vale|valeria)\s+o\s+(?:do|da)\s+(?:projeto|nota|financiamento|contrato)\b|\be o que vale\b")),
    ("dispensa_de_coleta", re.compile(
        r"\b(?:nao precisa|nem precisa|sem precisar|dispensa|dispensar|nao tem que|nao e preciso)\s+(?:de\s+)?"
        r"(?:conferir|checar|verificar|contar|justificar|filmar|fotografar|foto|video|refazer|conferencia|"
        r"checagem|verificacao|justificativa)")),
    ("dispensa_de_coleta", re.compile(r"\bdeixa\s+(?:quieto|assim|pra la|como esta)\b")),
]


class Pressao(BaseModel):
    grau: Grau
    tipo: str
    trecho: str


def _fim_de_frase(t: str, i: int) -> int:
    m = re.search(r"[.?!;]", t[i:])
    return i + m.start() if m else len(t)


def _alvo_valido(t: str, m: re.Match) -> bool:
    """O alvo numérico é valor da fiscalização? (não é "3 pontos de GPS", nem "contei 40", nem destino
    neutro como "40 no brete para filmar")."""
    if not m.group("num"):
        return True
    depois = t[m.end():m.end() + 40]
    if re.match(rf"^\s*(?:de\s+)?{_NEUTRO}", depois) or _DESTINO_NEUTRO.match(depois):
        return False
    return not _ANTES_AUTOALEGACAO.search(t[max(0, m.start() - 25):m.start()])


def _pedido_com_alvo(t: str) -> tuple[Grau, str] | None:
    """Verbo de alteração seguido (na mesma frase, até 40 caracteres) de valor, status ou referência."""
    autocorrecao = bool(_AUTOCORRECAO.search(t))
    achado: tuple[Grau, str] | None = None
    for v in _RX_VERBO.finditer(t):
        if autocorrecao and v.group(0).startswith("corr"):
            continue  # "corrigindo o que eu disse: contei 35" é nova alegação, não pressão
        if _NEG_ANTES.search(t[max(0, v.start() - 15):v.start()]):
            continue  # "não marca 40" / "nem coloca nada"
        janela = t[v.end():min(_fim_de_frase(t, v.end()), v.end() + 45)]
        for a in _RX_ALVO.finditer(janela):
            if not _alvo_valido(janela, a):
                continue
            trecho = t[v.start():v.end() + a.end()]
            grau: Grau = "incerta" if _PRIMEIRA_PESSOA.search(t[max(0, v.start() - 20):v.start()]) else "forte"
            if v.group(0).startswith(("anota", "anote", "registra", "registre")) and a.group("num"):
                grau = "incerta"  # "anota 40 cabeças": pode ser a contagem do próprio fiscal; pergunta
            if grau == "forte":
                return "forte", trecho
            achado = achado or (grau, trecho)
            break
    return achado


def classificar_pressao(texto: str) -> Pressao | None:
    """Pressão para alterar valor ou status sem nova evidência (POL-07), com grau `forte` ou `incerta`."""
    t = norm(texto)
    if not t:
        return None
    for tipo, rx in _FORTES:
        m = rx.search(t)
        if m and not _NEG_ANTES.search(t[max(0, m.start() - 12):m.start()]):
            return Pressao(grau="forte", tipo=tipo, trecho=m.group(0))
    pedido = _pedido_com_alvo(t)
    if pedido and pedido[0] == "forte":
        return Pressao(grau="forte", tipo="alterar_valor", trecho=pedido[1])
    if pedido:
        return Pressao(grau="incerta", tipo="alterar_valor_primeira_pessoa", trecho=pedido[1])
    for tipo, rx in _INCERTAS:
        if m := rx.search(t):
            if tipo == "alteracao_sem_alvo" and _AUTOCORRECAO.search(t):
                continue
            return Pressao(grau="incerta", tipo=tipo, trecho=m.group(0))
    return None


ESCLARECIMENTO = {
    "autoridade_sem_alvo": (
        "Entendi que alguém aprovou ou autorizou. Isso não muda a checagem: o laudo registra o que foi "
        "verificado. Se há algo a corrigir, envie nova evidência; se é justificativa, diga o motivo com as "
        "suas palavras."
    ),
    "valor_alternativo": (
        "Você discorda do número? O valor do laudo vem da checagem, não da fala. Se a contagem estiver errada, "
        "filme o lote de novo; se for justificativa da divergência, diga o motivo com as suas palavras."
    ),
    "dispensa_de_coleta": (
        "Sem a evidência, o campo fica pendente. Se não der para coletar, explique o motivo com as suas "
        "palavras e a decisão fica com a instituição."
    ),
}
ESCLARECIMENTO_PADRAO = (
    "Só para confirmar: você quer mudar um valor ou status? Eu não altero resultado a pedido; o valor só muda "
    "com nova evidência (vídeo, foto ou documento). Se for justificativa, diga o motivo com as suas palavras."
)


def pedido_de_esclarecimento(p: Pressao) -> str:
    return ESCLARECIMENTO.get(p.tipo, ESCLARECIMENTO_PADRAO)


# ---------------------------------------------------------------------------
# Ruído e baixa confiança do ASR
# ---------------------------------------------------------------------------

LIMIAR_CONFIANCA_ASR = 0.35  # o mesmo da interface para pedir confirmação (api/servico.py)
_TAG_RUIDO = re.compile(r"\[[^\]]*\]|\([^)]*(?:inaudivel|ruido|vento|silencio|musica|risos?|barulho)[^)]*\)")
_HESITACAO = {
    "e", "eh", "ah", "ahn", "aham", "hum", "humm", "hmm", "hm", "uh", "uhm", "ta", "ne", "entao", "assim",
    "tipo", "oi", "opa", "bom", "pois", "ai", "la", "o", "a", "de", "da", "do", "que", "so", "mm", "mmm",
    "ha", "hein", "ein", "uai", "ue", "eita", "oxe", "ahm", "ehh", "ahh",
}
_RX_PALAVRA = re.compile(r"[a-z0-9]+")


def eh_ruido(texto: str, confianca_asr: float | None = None) -> str | None:
    """Motivo, se a fala é ruído ou tem confiança baixa demais para ser interpretada; senão None."""
    if confianca_asr is not None and confianca_asr < LIMIAR_CONFIANCA_ASR:
        return (f"confiança do ASR {confianca_asr:.2f} abaixo de {LIMIAR_CONFIANCA_ASR}".replace(".", ","))
    t = norm(texto)
    tinha_tag = bool(_TAG_RUIDO.search(t))
    limpo = _TAG_RUIDO.sub(" ", t)
    palavras = _RX_PALAVRA.findall(limpo)
    conteudo = [p for p in palavras if p not in _HESITACAO]
    reticencias = limpo.count("...") + limpo.count("…")
    if not conteudo:
        return "fala sem conteúdo (silêncio, hesitação ou ruído)"
    if tinha_tag and len(conteudo) < 4:
        return "trecho inaudível com fragmentos soltos"
    if reticencias >= 2 and len(conteudo) <= 3:
        return "fragmentos sem frase completa"
    return None


PEDIDO_REPETICAO = "Não entendi a fala (áudio com ruído ou cortado). Pode repetir, mais perto do microfone?"

# ---------------------------------------------------------------------------
# Comandos humanos: emitir o rascunho e enviar para assinatura
# ---------------------------------------------------------------------------

Comando = Literal["emitir_rascunho", "solicitar_assinatura"]
_CMD_LAUDO = re.compile(
    r"\b(?:emit\w*|ger[ae]\w*|gere|faca|faz|fazer|produz\w*|prepar\w*|mont\w*|fech\w*|finaliz\w*|sai|sair|"
    r"solta|soltar)\b[^.?!;]{0,20}\b(?:o\s+|um\s+|a\s+)?(?:laudo|rascunho)\b"
)
_CMD_ASSINATURA = re.compile(
    r"\b(?:mand\w*|envi\w*|encaminh\w*|pass\w*|lev\w*|bota|coloca)\b[^.?!;]{0,25}\b(?:assinatura|assinar)\b"
)
# Pergunta ou finalidade antes do verbo ("o que falta para fechar o laudo?", "quando posso emitir?") não é
# comando; negação também não ("não gera o laudo ainda").
_NAO_COMANDO = re.compile(
    r"(?:\b(?:o que|oque|quanto|quando|como|falta|faltam|antes de|para|pra|depois de|se|porque|por que|"
    r"nao|nem|ainda nao)\b[^.?!;]{0,30})$"
)


def comando_humano(texto: str) -> tuple[Comando, str] | None:
    """Comando explícito do fiscal para emitir o rascunho ou enviar para assinatura (determinístico)."""
    t = norm(texto)
    for rx, acao in ((_CMD_ASSINATURA, "solicitar_assinatura"), (_CMD_LAUDO, "emitir_rascunho")):
        for m in rx.finditer(t):
            inicio = max(t.rfind(x, 0, m.start()) for x in ".?!;") + 1
            if _NAO_COMANDO.search(t[inicio:m.start()]):
                continue
            if acao == "solicitar_assinatura" and re.search(r"assin\w*\s+(?:por mim|no meu lugar)", t):
                continue  # pedido para o agente assinar: é da guarda POL-03
            return acao, m.group(0)  # type: ignore[return-value]
    return None
