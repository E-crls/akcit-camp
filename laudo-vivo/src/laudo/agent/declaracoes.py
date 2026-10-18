"""Leitura determinística de declarações do fiscal na fala (sem LLM).

O fiscal atesta fatos que só um humano em campo pode atestar: que não presta assistência técnica ao
mutuário (MCR 2-7-15), que a obra está concluída (MCR 2-7-16-a), ou a justificativa de uma divergência
(POL-02). O agente não redige nada disso: só reconhece a frase dita e a liga ao campo, sempre com o trecho
literal. Na dúvida, não reconhece (devolve None), e o pedido continua pendente. Só vale a parte da fala
que o fiscal afirma por conta própria (`atestacao_propria`): relato de terceiro, texto citado, pergunta e
hipótese não são atestação.
"""

from __future__ import annotations

import re
import time
import unicodedata

from laudo.contracts import Envelope, Fiscalizacao


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", t).strip()


def frases(texto: str) -> list[str]:
    """Frases do texto original (para usar como trecho literal)."""
    return [f.strip() for f in re.split(r"(?<=[.!?;])\s+", texto or "") if f.strip()]


# ---------------------------------------------------------------------------
# Atestação própria do fiscal
# ---------------------------------------------------------------------------

# Saem da fala: o texto entre aspas; a frase que é pergunta ou que atribui o conteúdo a outra fonte
# ("segundo X", "de acordo com X", "conforme o produtor", "pelo que ele falou", "consta"); o que vem depois de
# verbo de relato com sujeito que não é o fiscal ("X disse/garantiu que", "X está dizendo que", "diz o produtor
# que"), de relato ouvido ("ouvi do produtor que", "fiquei sabendo que") ou de marcador de leitura ("li na nota",
# "está escrito", "no recibo está:"); e o trecho entre vírgulas que é condição, hipótese ou futuro ("se...",
# "quando... estiver", "vai ficar"). Limite: pergunta sem "?" e leitura sem aspas (o ASR nem sempre pontua)
# passam como fala do fiscal.
_ASPAS = re.compile(r"\"[^\"]*\"|“[^”]*”|«[^»]*»|(?<!\w)'[^'\n]*'(?!\w)")
_ASPA_ABRE = re.compile(r"[\"“«]")
_ASPA_FECHA = re.compile(r"[”»]")
# "O que eu vi é que a cerca está pronta" não é pergunta (a interrogativa no início com "é que" é ênfase).
_PERGUNTA_PROPRIA = re.compile(r"\?\s*$|^(?:por que|o que|qual|quais|quanto|quantos|quantas|sera que|onde)\b"
                               r"(?!.*\b(?:e|foi|era) que\b)")
_PESSOA = r"(?:o|a|os|as|ele|ela|eles|elas|seu|sua|meu|minha|um|uma|dona|me|nos)"
_VERBOS_RELATO_3P = (
    r"falou|falaram|disse|disseram|contou|contaram|informou|informaram|garantiu|garantiram|afirmou|afirmaram|"
    r"explicou|explicaram|passou|passaram|avisou|avisaram|jurou|juraram"
)
_ATRIBUIDA = re.compile(
    rf"\bsegundo (?:o|a|os|as|ele|ela|eles|elas|seu|sua|meu|minha|um|uma)\b|\bde acordo com\b"
    # "conforme o produtor, ...", mas não "conforme o projeto" (modo de fazer, não fonte da informação)
    rf"|(?:^|, ?)conforme {_PESSOA}\b(?! (?:projeto|planejad|combinad|previst|contrat|cronograma|orcament|"
    r"plano|norma|especifica|exigid|padrao|croqui|desenho|mcr|manual|memorial)\w*)"
    rf"|\bpelo que (?:\w+ ){{0,3}}?(?:{_VERBOS_RELATO_3P}|ouvi|soube)\b"
    r"|\bconsta(?:m|va|vam)?\b"  # "na nota a cerca consta como concluída": quem afirma é o papel
)
_LEITURA = re.compile(r"\b(?:li|leio) (?:no|na|nos|nas|num|numa|em|aqui)\b|\b(?:esta|ta|estava) escrito\b|"
                      r"\bdiz aqui\b|\baqui diz\b|\b(?:esta|ta|estava|dizia|constava) ?:")
_RELATO = re.compile(
    r"\b(?:disse|disseram|dizia|diziam|diz|dizem|falou|falaram|fala|falam|afirmou|afirmaram|afirma|afirmam|"
    r"garantiu|garantiram|garante|garantem|contou|contaram|conta|contam|informou|informaram|informa|informam|"
    r"jurou|juraram|jura|juram|assegurou|asseguraram|declarou|declararam|alegou|alegaram|alega|alegam|"
    r"confirmou|confirmaram|relatou|relataram|avisou|avisaram|comentou|comentaram|explicou|explicaram|"
    r"passou|passaram|repassou|repassaram|escreveu|escreveram|mandou dizer|mandaram dizer|"
    # gerúndio ("o vizinho tá falando que"); "eu tô falando que" é o próprio fiscal (_EU_ANTES)
    r"dizendo|falando|afirmando|garantindo|contando|informando|jurando|alegando|comentando|avisando|relatando)\b"
    r"(?: (?:me|nos|pra mim|para mim|a mim|pra gente|aqui|ontem|hoje|antes|tambem))* ?(?:que\b|:)"
    # sujeito depois do verbo: "diz o produtor que", "garantiu ele que"
    r"|\b(?:diz|disse|dizem|disseram|falou|falaram|garante|garantiu|afirma|afirmou|conta|contou|informa|"
    r"informou|jura|jurou|alega|alegou|avisou|explicou) (?:o|a|os|as|seu|sua|dona|um|uma|ele|ela|eles|elas)\b"
    r"(?: \w+){0,2} (?:que\b|:)"
)
# Relato ouvido em 1ª pessoa ("ouvi do produtor que", "fiquei sabendo que"): é de outra pessoa, mesmo com "eu".
_OUVIDO = re.compile(r"\b(?:ouvi|ouvimos|escutei|escutamos|soube|soubemos|fiquei sabendo|ficamos sabendo)\b"
                     r"(?: \w+){0,4}? ?(?:(?<!\bo )que\b|:)")
# "eu disse que", "eu já disse que", "eu tô falando que": é o próprio fiscal
_EU_ANTES = re.compile(r"\b(?:eu(?: \w+)?|(?:eu )?(?:estou|to|tou)(?: \w+)?) ?$")
_SUBJUNTIVO = (r"(?:estiver|estiverem|estivesse|esteja|estejam|ficar|ficarem|ficasse|fique|fiquem|for|"
               r"forem|fosse|seja|sejam|tiver|tiverem|tivesse|terminar|terminarem|acabar|acabarem|concluir|"
               r"concluirem)")
_HIPOTESE = re.compile(
    r"^ ?(?:e |mas |ou |so )?(?:se|caso)\b"
    rf"|\b(?:se|caso|quando|assim que|logo que|depois que|ate que|antes que)\b.{{0,40}}\b{_SUBJUNTIVO}\b"
    r"|\b(?:vai|vao|ira|irao|deve|devem|deveria|deveriam|pode|podem) (?:ficar|estar|ser)\b"
    r"|\b(?:ficara|ficarao|estara|estarao|sera|serao)\b|\b(?:talvez|provavelmente|acho que|parece que)\b"
)


def _sem_aspas(texto: str) -> str:
    """O texto com cada trecho entre aspas trocado por espaços (mesmo comprimento: as posições valem)."""
    return _ASPAS.sub(lambda m: " " * len(m.group(0)), texto)


def _parte_propria(frase: str) -> str:
    """Parte de UMA frase (já sem os trechos entre aspas) atribuível ao fiscal, normalizada; "" se nada é
    dele."""
    if m := _ASPA_FECHA.search(frase):  # citação que vem da frase anterior e termina nesta
        frase = frase[m.end():]
    if m := _ASPA_ABRE.search(frase):  # citação que começa nesta frase e não fecha
        frase = frase[: m.start()]
    t = norm(frase)
    if not t or _PERGUNTA_PROPRIA.search(t) or _ATRIBUIDA.search(t):
        return ""
    for rx in (_LEITURA, _OUVIDO, _RELATO):
        for m in rx.finditer(t):
            if rx is _RELATO and _EU_ANTES.search(t[: m.start()]):
                continue
            t = t[: m.start()]
            break
    return ",".join(s for s in t.split(",") if not _HIPOTESE.search(s)).strip(" ,")


def partes_proprias(texto: str) -> list[tuple[str, str]]:
    """(frase literal, parte dela atribuível ao próprio fiscal, normalizada) para cada frase da fala."""
    texto = texto or ""
    sem = _sem_aspas(texto)
    saida: list[tuple[str, str]] = []
    pos = 0
    for f in frases(texto):
        i = texto.find(f, pos)
        pos = i + len(f)
        saida.append((f, _parte_propria(sem[i:pos])))
    return saida


def atestacao_propria(fala: str) -> str:
    """Só a parte da fala atribuível ao próprio fiscal (normalizada: minúsculas, sem acento). Sai o texto
    entre aspas, a pergunta, a condição, a hipótese, o futuro, o relato de terceiro e o que ele leu de um
    papel."""
    return " ".join(p for _, p in partes_proprias(fala) if p)


# ---------------------------------------------------------------------------
# Independência do fiscal (MCR 2-7-15)
# ---------------------------------------------------------------------------

_SEM_NEGACAO = r"(?:(?!\b(?:nao|nunca|nem)\b).)"
_INDEP_SEM_CONFLITO = re.compile(
    r"\bdeclaro\b.{0,40}\b(?:nao|nunca)\b.{0,30}\b(?:presto|prestei|prestamos|tenho|temos|sou)\b.{0,50}"
    r"\b(?:assistencia tecnica|vinculo|participacao|socio|empresa)"
)
_INDEP_COM_CONFLITO = re.compile(
    rf"\bdeclaro\b{_SEM_NEGACAO}{{0,40}}\b(?:presto|prestei|sou|tenho)\b{_SEM_NEGACAO}{{0,50}}"
    r"\b(?:assistencia tecnica|responsavel tecnico|socio|participacao)"
)
# Ressalva ou vínculo declarado na mesma fala ("..., mas minha empresa faz o projeto dele"): a declaração não
# é reconhecida e o campo fica pendente (decisão da IF).
_INDEP_RESSALVA = re.compile(r"\b(?:mas|porem|so que|exceto|salvo|contudo|entretanto|todavia)\b")
_INDEP_VINCULO = re.compile(
    rf"\b(?:minha|nossa) (?:empresa|firma|consultoria|escritorio|cooperativa)\b{_SEM_NEGACAO}{{0,40}}"
    r"\b(?:presta|prestou|faz|fez|atende|atendeu|elabora|elaborou|cuida)\b"
    rf"|(?<!nao )(?<!nunca )(?<!nem )\bsou\b{_SEM_NEGACAO}{{0,30}}"
    r"\b(?:dele|dela|do produtor|da produtora|do mutuario|da mutuaria)\b|\bsomos socios\b"
)


def declaracao_independencia(texto: str) -> bool | None:
    """None: a fala não é declaração de independência (ou vem com ressalva ou vínculo). False: declara que NÃO
    há conflito. True: declara conflito (fiscal vedado pelo MCR 2-7-15). Lê só a parte própria da fala."""
    t = atestacao_propria(texto)
    if _INDEP_COM_CONFLITO.search(t):
        return True
    if m := _INDEP_SEM_CONFLITO.search(t):
        if _INDEP_RESSALVA.search(t, m.start()) or _INDEP_VINCULO.search(t):
            return None
        return False
    return None


# ---------------------------------------------------------------------------
# Conclusão da obra (MCR 2-7-16-a)
# ---------------------------------------------------------------------------

# Negação explícita da conclusão ("não está pronta", "inacabada", "em construção"): divergente. A 1ª
# pessoa ("ainda não terminei a vistoria", "não concluí") fala do fiscal, não da obra.
_OBRA_NEGATIVA = re.compile(
    r"\b(?:nao|ainda nao)\b.{0,25}\b(?:conclu(?!i\b)|pront|termin(?!ei\b)|finaliz(?!ei\b)|acabad)|"
    r"\b(?:inacabad\w*|em construcao|em andamento)"
)
# Falta algo na obra. Os marcadores de falta ("incompleta", "faltando", "falta terminar/colocar...") valem
# sozinhos (divergente); os de ressalva ("ainda não", "até a metade", "parcial", "falta(m) + complemento") só
# impedem o "ok".
# Junto com o positivo, qualquer um deixa a declaração indeterminada (pendente, com pedido), nunca divergente:
# "pronta, só falta..." não é atestação de obra inacabada. Os dois só contam quando a oração deles fala da obra
# e não do processo ("ainda não mandei a foto", "falta a nota fiscal", "falta você gerar o rascunho").
_OBRA_FALTA = re.compile(r"\b(?:incomplet\w*|faltando|falta (?:terminar|concluir|colocar|instalar|fazer))")
_OBRA_RESSALVA = re.compile(r"\b(?:ainda nao|ate a metade|parcia\w*)\b|(?<!sem )(?<!nao )\bfaltam? (?!nada\b)\w")
_PROCESSO = re.compile(
    r"\b(?:fotos?|fotograf\w*|imagens?|videos?|film\w*|grav\w*|notas?|nf-?e?|documento\w*|documentac\w*|"
    r"papel\w*|gta|guias?|recibos?|comprovantes?|assin\w*|rascunho|laudo|relatorio|sistema|aplicativo|app|"
    r"voce|eu|gado|animais|cabecas|bois?|vacas?|bezerr\w*|garrot\w*|novilh\w*|lote|contage\w*|contar|contei|"
    r"vistoria|visita|mandar|mandei|enviar|enviei|tirar|tirei|subir|carregar|pagamento|pago|parcelas?|"
    r"liberac\w*|banco|credito)\b"
)
_ORACAO = re.compile(r"[,;:.!?]| e | mas | porem | so que ")
_OBRA_POSITIVA = re.compile(
    r"\b(?:conclu\w*|pront[ao]s?|terminad[ao]s?|finalizad[ao]s?|acabad[ao]s?|construid[ao]s?|instalad[ao]s?|"
    r"feit[ao]s? por completo)\b"
)
_TIPOS_BENFEITORIA = {"cerca": r"\bcercas?\b", "curral": r"\bcurra(?:l|is)\b", "galpao": r"\bgalp(?:ao|oes)\b"}
_OBRA_CITADA = re.compile(r"\b(?:cercas?|curra(?:l|is)|galp(?:ao|oes)|obras?|benfeitori\w*|estruturas?)\b")
# Retirada em 1ª pessoa do que o fiscal declarou antes: a declaração anterior deixa de valer. Só conta quando a
# frase fala da obra ("me enganei, a cerca não está pronta") ou não fala de mais nada ("me enganei, retiro o que
# eu disse"); "errei a contagem" ou "me enganei de arquivo" falam de outra coisa.
_RETIRADA = re.compile(
    r"\b(?:me enganei|me equivoquei|retiro o que (?:eu )?(?:disse|falei|declarei)|retiro (?:a|minha) declaracao|"
    r"volto atras|corrijo|errei|eu estava errad[oa])\b"
)
_ENCHIMENTO = re.compile(
    r"\b(?:desculp\w*|perdao|foi mal|opa|nossa|olha|na verdade|entao|sobre isso|nisso|isso|tudo|"
    r"(?:sobre |n)?o que (?:eu )?(?:disse|falei|declarei)(?: antes| agora ha pouco| ha pouco)?)\b"
)


def _na_obra(rx: re.Pattern, t: str) -> bool:
    """O marcador `rx` aparece numa oração de `t` que fala da obra (e não do processo: foto, nota, rascunho...)."""
    for m in rx.finditer(t):
        ini = max((x.end() for x in _ORACAO.finditer(t, 0, m.start())), default=0)
        fim = _ORACAO.search(t, m.end())
        if not _PROCESSO.search(t[ini: fim.start() if fim else len(t)]):
            return True
    return False


def _situacao(trecho: str) -> tuple[str, bool]:
    """(status, misto): ok, divergente ou indeterminado; misto quando diz que está pronta mas que algo falta."""
    t = norm(trecho)
    if _OBRA_NEGATIVA.search(t):
        return "divergente", False
    positiva = bool(_OBRA_POSITIVA.search(t))
    falta = _na_obra(_OBRA_FALTA, t)
    if positiva and (falta or _na_obra(_OBRA_RESSALVA, t)):
        return "indeterminado", True
    if falta:
        return "divergente", False
    return ("ok" if positiva else "indeterminado"), False


def status_conclusao(trecho: str) -> str:
    """ok (obra concluída), divergente (inacabada) ou indeterminado (sem afirmação clara, ou pronta mas com
    algo faltando)."""
    return _situacao(trecho)[0]


def _fala_da_obra(t: str) -> bool:
    """A parte própria `t` afirma algo sobre a situação da obra (é candidata a declaração de conclusão)."""
    return bool(_OBRA_NEGATIVA.search(t) or _OBRA_POSITIVA.search(t) or _na_obra(_OBRA_FALTA, t))


FERRAMENTA_CONCLUSAO = "declaracao_conclusao"  # nome lido pelo rulebook (MCR-2-7-item16-benfeitorias-conclusao)
REGRA_CONCLUSAO = "MCR-2-7-item16-benfeitorias-conclusao"
VERSAO_CONCLUSAO = "declaracao-conclusao@0.1.0"
RETIROU = "o fiscal retirou a declaração anterior"
PEDIDO_RETIRADA = "diga o que você viu ou envie a foto da estrutura"
MISTO = ("a fala diz que a obra está pronta, mas também que algo falta ou ainda não foi feito: diga se a obra "
         "está concluída ou envie a foto da estrutura")


def envelope_conclusao(item_id: str, trecho: str, substitui: list[str] | None = None) -> Envelope:
    """Resultado da declaração de conclusão no formato de ferramenta (vira `Checagem` no condutor).

    Não é uma ferramenta do REGISTRO: é ação interna do condutor (`registrar_conclusao_obra`), porque o
    insumo é a fala do fiscal, conferida literalmente pela política (POL-02, que lê o trecho na frase inteira
    em que foi dito). O status sai só da parte própria do trecho. Na retirada, `substitui` lista as
    declarações anteriores do item, que deixam de contar."""
    t0 = time.perf_counter()
    status, misto = _situacao(atestacao_propria(trecho))
    motivo = {
        "ok": "o fiscal atestou em campo que a obra está concluída",
        "divergente": "o fiscal atestou em campo que a obra não está concluída",
        "indeterminado": MISTO if misto else
        "a fala não afirma se a obra está concluída; pedir declaração clara ou foto da obra",
    }[status]
    if substitui:
        motivo = (f"{RETIROU}: {PEDIDO_RETIRADA}" if status == "indeterminado" and not misto
                  else f"{RETIROU}; {motivo}")
    data = {"status": status, "item_id": item_id, "trecho": trecho, "motivo": motivo,
            "regra_id": REGRA_CONCLUSAO, "metodo": "declaração do fiscal no local (presencial)"}
    if substitui:
        data["substitui"] = list(substitui)
    return Envelope.sucesso(FERRAMENTA_CONCLUSAO, data, fonte_versao=VERSAO_CONCLUSAO, t0=t0)


def _benfeitorias(fis: Fiscalizacao) -> list:
    return [i for i in fis.operacao.itens if i.tipo in _TIPOS_BENFEITORIA or i.tipo == "benfeitoria"]


def _cita(item, t: str) -> bool:
    return bool(re.search(_TIPOS_BENFEITORIA.get(item.tipo, r"\bbenfeitori\w*\b"), t))


def _declaracoes(partes: list[tuple[str, str]], benf: list) -> list[tuple[str, str, str]]:
    """(item_id, frase literal, parte própria) da 1ª frase de `partes` em que o fiscal atesta cada benfeitoria."""
    saida: list[tuple[str, str, str]] = []
    for f, t in partes:
        if not _fala_da_obra(t):
            continue
        citados = [i for i in benf if _cita(i, t)]
        if not citados and len(benf) == 1 and re.search(r"\b(?:obra|benfeitori\w*)\b", t):
            citados = benf
        for i in citados:
            if i.id not in {x for x, _, _ in saida}:
                saida.append((i.id, f, t))
    return saida


def declaracoes_conclusao(texto: str, fis: Fiscalizacao) -> list[tuple[str, str]]:
    """(item_id, trecho literal) para cada frase em que o próprio fiscal atesta a situação de uma benfeitoria
    da operação (item e status lidos só na parte própria da frase)."""
    benf = _benfeitorias(fis)
    if not benf:
        return []
    return [(i, f) for i, f, _ in _declaracoes(partes_proprias(texto), benf)]


def conclusao_no_contexto(fala: str, trecho: str, fis: Fiscalizacao) -> dict[str, str]:
    """{item_id: status} do que o próprio fiscal atesta nas frases da fala que contêm o trecho. O trecho que o
    LLM recorta é lido na frase inteira em que foi dito: a oração depois de "o produtor disse que", o texto entre
    aspas ou a pergunta sem o "?" do fim não viram atestação só porque foram recortados."""
    nt = norm(trecho)
    partes = partes_proprias(fala)
    ctx = [(f, t) for f, t in partes if nt and (nt in norm(f) or norm(f) in nt)] or partes
    return {i: status_conclusao(t) for i, _, t in _declaracoes(ctx, _benfeitorias(fis))}


def _situacao_da_obra(t: str) -> bool:
    """Alguma oração de `t` afirma a situação de uma obra (pronta, não está pronta, falta terminar) sem falar do
    processo: "me enganei, ela não está pronta" fala da obra mesmo sem citá-la; "o laudo não está pronto", não."""
    return any((_OBRA_NEGATIVA.search(o) or _OBRA_POSITIVA.search(o) or _OBRA_FALTA.search(o))
               and not _PROCESSO.search(o) for o in _ORACAO.split(t))


def _retirada(texto: str) -> tuple[str, str] | None:
    """(frase literal, parte própria) da retirada da fala, ou None. Frase que retira e fala da obra (pelo nome ou
    pela situação) vale; retirada pura ("me enganei", "retiro o que eu disse") vale se a fala não tratar de
    outro campo (contagem, GTA, nota, foto, localização, prazo) sem citar a obra."""
    partes = partes_proprias(texto)
    pura = None
    for f, t in partes:
        if not _RETIRADA.search(t):
            continue
        if _OBRA_CITADA.search(t) or _situacao_da_obra(t):
            return f, t
        resto = _ENCHIMENTO.sub(" ", _RETIRADA.sub(" ", t))
        if pura is None and not re.sub(r"[\W_]+", "", resto):
            pura = (f, t)
    if pura is None:
        return None
    if any(_OBRA_CITADA.search(t) for _, t in partes) or not any(_OUTRO_CAMPO.search(t) for _, t in partes):
        return pura
    return None


def eh_retirada(trecho: str) -> bool:
    """O fiscal retira, em 1ª pessoa, o que declarou sobre a obra ("me enganei", "retiro o que eu disse")."""
    return _retirada(trecho) is not None


def declaracoes_ativas(fis: Fiscalizacao, item_id: str) -> list[str]:
    """Ids das declarações de conclusão do item que ainda valem (não substituídas)."""
    subst = {s for c in fis.checagens for s in (c.resultado.get("substitui") or [])}
    return [c.id for c in fis.checagens
            if c.ferramenta == FERRAMENTA_CONCLUSAO and c.item_id == item_id and c.id not in subst]


def retiradas_conclusao(texto: str, fis: Fiscalizacao) -> list[tuple[str, str]]:
    """(item_id, trecho literal) da retirada (`_retirada`), quando a benfeitoria já tem declaração de conclusão
    que vale. Vale para os itens citados na frase ou, sem item citado, para todos os que têm declaração; a
    checagem nova substitui a anterior (`envelope_conclusao`)."""
    com_decl = [i for i in _benfeitorias(fis) if declaracoes_ativas(fis, i.id)]
    if not com_decl or (r := _retirada(texto)) is None:
        return []
    f, t = r
    trecho = f if len(norm(f)) >= 10 else (texto or "").strip()
    return [(i.id, trecho) for i in ([i for i in com_decl if _cita(i, t)] or com_decl)]


# ---------------------------------------------------------------------------
# Justificativa de divergência (POL-02)
# ---------------------------------------------------------------------------

# Só fala que se refere à divergência ("confirmo a divergência...", "justifico...", "discordo da contagem:
# ...") conta: "confirmo que recebi a GTA" não pode virar justificativa de uma GTA divergente.
_MARCADOR_JUSTIFICATIVA = re.compile(r"\b(?:justific\w*|diverg\w*|discord\w*)\b")
# Pergunta não é justificativa ("por que a contagem deu diferente?").
_PERGUNTA = re.compile(r"\?\s*$|^(?:por que|porque|o que|qual|quais|quando|como|quanto|sera que)\b")
_PALAVRAS_DO_CAMPO = {
    "quantidade": r"\b(?:contage\w*|contei|contad\w*|cabecas?|animais|vacas?|bois?|novilh\w*|garrot\w*|lote)\b",
    "gta": r"\b(?:gta|guia de transito)\b",
    "comprovante_nfe": r"\b(?:nota fiscal|nota|nf-?e)\b",
    "nfe": r"\b(?:nota fiscal|nota|nf-?e)\b",
    "localizacao": r"\b(?:gleba|localizacao|gps|coordenada\w*)\b",
    "integridade_foto": r"\b(?:foto|imagem)\b",
    "conclusao": r"\b(?:obra|conclus\w*)\b",
    "prazo_cronograma": r"\b(?:prazo|cronograma)\b",
}
# Assunto de outro campo (retirada pura: "me enganei, a contagem é 48" não retira a conclusão da obra).
_OUTRO_CAMPO = re.compile("|".join(v for k, v in _PALAVRAS_DO_CAMPO.items() if k != "conclusao"))


def eh_pergunta(texto: str) -> bool:
    return bool(_PERGUNTA.search(norm(texto)))


def cita_campo(texto: str, campo: str) -> bool:
    """A fala menciona o assunto do campo (contagem, GTA, nota, foto, obra...)?"""
    rx = _PALAVRAS_DO_CAMPO.get(campo.rsplit(":", 1)[-1])
    return bool(rx and re.search(rx, norm(texto)))


def contexto_do_trecho(fala: str, trecho: str) -> str:
    """Frases da fala que contêm o trecho (a justificativa é lida no contexto em que foi dita)."""
    nt = norm(trecho)
    ctx = [f for f in frases(fala) if nt and (nt in norm(f) or norm(f) in nt)]
    return " ".join(ctx) or fala


def campo_justificado(texto: str, fis: Fiscalizacao) -> str | None:
    """Campo divergente (em abstenção, ou pendente justificável) sem justificativa ao qual a fala claramente se
    refere; None se a fala não é justificativa (sem marcador, ou é pergunta) ou se cita mais de um campo (aí a
    escolha fica com o fiscal/LLM). Pedido de alterar valor é barrado antes, pela política (POL-07)."""
    from laudo.agent.verificador import campo_justificavel  # import local: o verificador não depende daqui

    t = norm(texto)
    if len(t) < 15 or not _MARCADOR_JUSTIFICATIVA.search(t) or eh_pergunta(texto):
        return None
    candidatos = []
    for c in fis.campos.values():
        if not campo_justificavel(c) or c.justificativa_humana or c.campo.count(":") < 2:
            continue
        if cita_campo(t, c.campo):
            candidatos.append(c.campo)
    return candidatos[0] if len(candidatos) == 1 else None
