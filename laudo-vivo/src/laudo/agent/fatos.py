"""Fatos por template e consistência semântica da fala do LLM (POL-09).

O LLM conduz a conversa (pede a próxima evidência, explica o que falta, responde dúvidas), mas **não afirma
resultado de checagem**. As frases que afirmam resultado (contagem, documentos, localização, satélite, status,
emissão) são geradas aqui, por template, a partir do estado e do verificador.

`analisar_fala` lê a fala do LLM frase a frase e:
- aponta **violações** de consistência semântica: direção da contagem (falta × excesso), posição da foto (dentro
  × fora da gleba), status do campo (verificado × divergente × pendente), consequência que não está no estado
  ("impede a liberação do crédito": a fiscalização é posterior à liberação), qualificação de ilícito (fraude,
  irregularidade), juízo sobre o pasto ("boa saúde") sem rótulo de ferramenta e **ação afirmada sem lastro**
  ("registrei o contato", "comparei o CPF", "enviei ao banco": a ação precisa ter acontecido no turno ou estar
  no estado; assinar, aprovar, alterar valor e falar com terceiros nunca acontecem). Com violação, o condutor
  troca a fala inteira pelo template e registra a decisão POL-09 no trace;
- separa as frases que **afirmam resultado** (removidas: o fato vem do template) das frases de **condução**
  (mantidas, depois do grounding numérico do POL-05).

Antes da análise, `limpar_marcacoes` tira da fala marcações internas que o modelo às vezes ecoa (`<dado>`,
`<contexto>`, `<hash>`, `<tool_call>`, `<think>`).

Texto normalizado (minúsculas, sem acento) nas regras.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from laudo.agent.declaracoes import norm
from laudo.contracts import CampoLaudo, Checagem, Fiscalizacao

REGRA_SEMANTICA = "POL-09"

ROTULO_CAMPO = {
    "quantidade": "Quantidade de animais",
    "comprovante_nfe": "NF-e da compra",
    "nfe": "NF-e da compra",
    "gta": "GTA",
    "integridade_foto": "Integridade da foto",
    "localizacao": "Localização da foto",
    "existencia": "Foto da benfeitoria",
    "conclusao": "Conclusão da obra",
    "prazo_cronograma": "Prazo do cronograma",
    "ndvi": "Satélite",
    "lotacao": "Lotação",
    "metadados_sensoriamento": "Metadados do satélite",
    "independencia_fiscal": "Independência do fiscal",
    "metodo": "Método",
}
STATUS_FALADO = {
    "verificado": "verificado",
    "divergente": "divergente",
    "pendente": "pendente",
    "abstencao": "em abstenção (decisão humana)",
}


def _num(v: Any, casas: int = 2) -> str:
    """Número para a fala, em pt-BR, com o arredondamento que o grounding (POL-05) aceita."""
    if isinstance(v, bool) or v is None:
        return str(v)
    f = float(v)
    if f.is_integer():
        return str(int(f))
    return f"{f:.{casas}f}".rstrip("0").rstrip(".").replace(".", ",")


def _limpar_motivo(m: str, n: int = 170) -> str:
    m = re.sub(r"\bitem:[\w]+:[\w]+:\s*(?:divergente|pendente|ok|verificado)?\s*\(?", "", m or "")
    m = re.sub(r"\s+", " ", m).strip(" ;:(")
    while m.endswith(")") and m.count(")") > m.count("("):
        m = m[:-1].rstrip()
    return m[:n].rstrip() + ("…" if len(m) > n else "")


_ERRO_FALADO = {
    "ENTRADA_INVALIDA": "arquivo ilegível ou corrompido",
    "TIMEOUT": "a ferramenta não respondeu a tempo",
    "SEM_DADOS": "sem dados para conferir",
    "FORA_DO_ESCOPO": "fora do escopo da ferramenta",
    "NUVEM": "nuvem nas imagens",
    "ERRO_INTERNO": "erro interno da ferramenta",
}


def motivo_erro(chk: Checagem) -> str:
    """Motivo de erro de ferramenta para a fala (sem a mensagem técnica crua)."""
    e = chk.resultado.get("erro") or {}
    return _ERRO_FALADO.get(str(e.get("code") or ""), "erro da ferramenta")


def sufixo(campo: str) -> str:
    return campo.rsplit(":", 1)[-1]


def rotulo(campo: str) -> str:
    return ROTULO_CAMPO.get(sufixo(campo), sufixo(campo).replace("_", " "))


# ---------------------------------------------------------------------------
# Fatos por template
# ---------------------------------------------------------------------------


Faixa = tuple[float | None, float | None, float | None]


def _intervalo(valor: Any, chk: Checagem | None, motivo: str = "") -> Faixa:
    """(contagem, mínimo, máximo) do campo: o valor do verificador (soma dos lotes, na regra provisória) tem
    precedência sobre a última checagem."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        m = re.search(r"intervalo (\d+(?:[.,]\d+)?) a (\d+(?:[.,]\d+)?)", motivo or "")
        if m:
            return float(valor), float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        return float(valor), float(valor), float(valor)
    n = lo = hi = None
    fontes = [valor if isinstance(valor, dict) else {}, chk.resultado if chk else {}]
    for f in fontes:
        if n is None and isinstance(f.get("contagem"), (int, float)):
            n = float(f["contagem"])
        iv = f.get("intervalo")
        if lo is None and isinstance(iv, (list, tuple)) and len(iv) == 2:
            lo, hi = float(iv[0]), float(iv[1])
    if lo is None and n is not None:
        lo = hi = n
    return n, lo, hi


def direcao_contagem(fis: Fiscalizacao, campos: dict[str, CampoLaudo]) -> set[str]:
    """Direções sustentadas pelo estado: "falta" (contagem abaixo do financiado), "excesso" (acima)."""
    dirs: set[str] = set()
    for nome, c in campos.items():
        if sufixo(nome) != "quantidade" or nome.count(":") < 2:
            continue
        item = next((i for i in fis.operacao.itens if i.id == nome.split(":")[1]), None)
        fin = (c.valor or {}).get("financiado") if isinstance(c.valor, dict) else None
        fin = fin if fin is not None else (item.quantidade if item else None)
        chk = next((x for x in reversed(fis.checagens) if x.id in c.checagens), None)
        n, lo, hi = _intervalo(c.valor, chk, c.motivo)
        if fin is None or n is None:
            continue
        if n < fin or (hi is not None and hi < fin):
            dirs.add("falta")
        if n > fin or (lo is not None and lo > fin):
            dirs.add("excesso")
    return dirs


def fato_quantidade(c: CampoLaudo, chk: Checagem | None, fis: Fiscalizacao) -> str:
    item = next((i for i in fis.operacao.itens if i.id == c.campo.split(":")[1]), None)
    n, lo, hi = _intervalo(c.valor, chk, c.motivo)
    fin = (c.valor or {}).get("financiado") if isinstance(c.valor, dict) else None
    fin = fin if fin is not None else (item.quantidade if item else None)
    if chk is not None and chk.status == "erro":
        return f"A contagem do vídeo falhou ({motivo_erro(chk)}): envie o vídeo de novo."
    if n is None or c.status in ("abstencao", "pendente") and (chk is None or chk.status == "indeterminado"):
        return f"Contagem do vídeo inconclusiva: {_limpar_motivo(c.motivo)}. Quantidade: {STATUS_FALADO[c.status]}."
    n_videos = sum(1 for x in fis.checagens if x.id in c.checagens and x.ferramenta == "contar_bovinos_video")
    rotulo_c = f"Contagem somada dos {n_videos} vídeos" if n_videos > 1 and not isinstance(c.valor, dict) \
        else "Contagem do vídeo"
    faixa = f" (intervalo de {_num(lo)} a {_num(hi)})" if lo is not None and hi is not None and lo != hi else ""
    partes = [f"{rotulo_c}: {_num(n)} animais{faixa}"]
    if fin is not None:
        partes[0] += f"; financiados: {_num(fin)}"
        if hi is not None and hi < fin:
            partes.append("a contagem fica abaixo do financiado (faltam animais)")
        elif lo is not None and lo > fin:
            partes.append("a contagem passa do financiado (há animais a mais)")
        else:
            partes.append("o financiado está dentro do intervalo da contagem")
    return ". ".join(p[0].upper() + p[1:] for p in partes) + f". Quantidade: {STATUS_FALADO[c.status]}."


def posicao_geofence(chk: Checagem) -> str:
    """dentro, fora ou indeterminado: `posicao` (geofence ≥ 0.1.1), status legado da ferramenta ou o status
    comum (ok → dentro, divergente → fora), como em `regras._posicao_geofence`."""
    r = chk.resultado
    for chave in ("posicao", "status_ferramenta", "status"):
        if r.get(chave) in ("dentro", "fora", "indeterminado"):
            return str(r[chave])
    return {"ok": "dentro", "divergente": "fora"}.get(chk.status, "indeterminado")


def fato_localizacao(c: CampoLaudo | None, chk: Checagem) -> str:
    r = chk.resultado
    pos = posicao_geofence(chk)
    d = r.get("distancia_borda_m")
    if chk.status == "erro":
        base = f"A checagem de localização falhou ({motivo_erro(chk)})"
    elif r.get("depende_de_integridade"):
        base = ("Localização indeterminada: a foto não passou na integridade, então o GPS não vale para ela; "
                "refaça a foto pelo app")
    elif pos == "dentro":
        base = "A foto foi tirada dentro da gleba"
    elif pos == "fora" and isinstance(d, (int, float)):
        base = f"A foto foi tirada fora da gleba, a {_num(d, 1)} m da borda"
    elif pos == "fora":
        base = "A foto foi tirada fora da gleba"
    else:
        base = f"Localização da foto indeterminada ({_limpar_motivo(str(r.get('motivo') or ''), 140)})"
    st = f"; {rotulo(c.campo).lower()}: {STATUS_FALADO[c.status]}" if c is not None else ""
    return f"{base}{st}."


def fato_ndvi(chk: Checagem) -> str:
    r = chk.resultado
    if chk.status != "ok":
        motivo = motivo_erro(chk) if chk.status == "erro" else _limpar_motivo(str(r.get("motivo") or chk.status), 150)
        return f"Satélite sem resultado utilizável ({motivo}); o campo segue por outro método."
    res = r.get("resumo") or {}
    partes = []
    if isinstance(r.get("n_obs_limpas"), (int, float)) and isinstance(r.get("n_datas_lidas"), (int, float)):
        partes.append(f"{_num(r['n_obs_limpas'])} datas sem nuvem de {_num(r['n_datas_lidas'])}")
    if isinstance(res.get("ndvi_p50_mediana"), (int, float)):
        txt = f"NDVI mediano {_num(res['ndvi_p50_mediana'])}"
        if isinstance(res.get("ndvi_p50_min"), (int, float)) and isinstance(res.get("ndvi_p50_max"), (int, float)):
            txt += f" (de {_num(res['ndvi_p50_min'])} a {_num(res['ndvi_p50_max'])})"
        partes.append(txt)
    corpo = "; ".join(partes) or _limpar_motivo(str(r.get("motivo") or ""), 150)
    return (f"Satélite Sentinel-2: {corpo}. O NDVI só mede o verde da vegetação; o sistema não dá nota à saúde "
            "do pasto.")


def fato_campo(c: CampoLaudo, chk: Checagem | None, fis: Fiscalizacao) -> str:
    suf = sufixo(c.campo)
    if suf == "quantidade":
        return fato_quantidade(c, chk, fis)
    if suf == "localizacao" and chk is not None and chk.ferramenta == "geofence":
        return fato_localizacao(c, chk)
    if chk is not None and chk.status == "erro":
        return f"{rotulo(c.campo)}: a checagem falhou ({motivo_erro(chk)}); repita o envio."
    txt = f"{rotulo(c.campo)}: {STATUS_FALADO[c.status]}"
    if c.status != "verificado" and c.motivo:
        txt += f" ({_limpar_motivo(c.motivo)})"
    if c.justificativa_humana and c.status in ("divergente", "abstencao"):
        txt += ", com justificativa do fiscal"
    return txt + "."


def fato_leitura(chk: Checagem) -> str:
    """Leitura de DANFE/GTA por foto (`ler_documento_foto`) ou completação pela fiscal
    (`completar_leitura_documento`): o que validou e o pedido do residual, se houver."""
    r = chk.resultado
    doc, de_doc = {"danfe": ("A nota (DANFE)", "da nota"), "gta": ("A GTA", "da GTA")}.get(
        str(r.get("tipo_documento")), ("O documento", "do documento"))
    pedido = (r.get("pedido_residual") or {}).get("texto") or ""
    if chk.status == "erro":
        return f"{doc}: a leitura falhou ({motivo_erro(chk)}); envie de novo ou mande o XML/e-GTA."
    if r.get("tipo_documento") == "outro":
        return "A foto não parece DANFE nem GTA: fotografe o documento inteiro, de cima."
    if chk.ferramenta == "ler_documento_foto":
        if chk.status == "ok":
            return (f"{doc} foi lida pela foto: todos os campos críticos validaram (dígito verificador, somas e "
                    "datas).")
        if not pedido:  # nada que a fiscal possa ler no papel resolve (tabela ilegível): nova foto ou o XML
            pedido = "Refaça a foto do papel inteiro, de cima, sem sombra, ou envie o XML (ou a e-GTA)."
        return f"{doc} foi lida pela foto, mas alguns campos não validaram. {pedido}".strip()
    aceitos = ", ".join(r.get("aceitos_rotulos") or [])
    partes = []
    if aceitos:
        partes.append(f"Aceitei o que você leu {de_doc}: {aceitos} (validado pelas mesmas regras da leitura; "
                      "origem: lido de foto e completado pela fiscal).")
    for x in (r.get("recusados") or [])[:3]:
        rot = x.get("rotulo") or x.get("campo")
        partes.append(f"Não aceitei {rot}: {_limpar_motivo(str(x.get('motivo')), 120)}.")
    if chk.status == "ok":
        partes.append("Todos os campos críticos do documento validaram.")
    elif pedido:
        partes.append(pedido)
    else:
        partes.append(f"{doc} continua com campos sem validação depois das tentativas: peça o XML da NF-e ou a "
                      "e-GTA.")
    return " ".join(partes)


def fato_classificacao(chk: Checagem, c: CampoLaudo | None) -> str:
    """classificar_foto (VLM) na foto da benfeitoria: a foto mostra a estrutura do item?"""
    r = chk.resultado
    if chk.status == "erro":
        return f"A classificação da foto pelo VLM falhou ({motivo_erro(chk)}); a conclusão da obra segue pendente."
    esperada = r.get("classe_esperada") or "estrutura"
    base = (f"O VLM confere que a foto mostra a {esperada}" if chk.status == "ok"
            else f"O VLM não confirmou a {esperada} na foto ({_limpar_motivo(str(r.get('motivo') or ''), 120)})")
    st = f"; conclusão da obra: {STATUS_FALADO[c.status]}" if c is not None else ""
    return f"{base}{st}."


def fato_checagem(chk: Checagem, campo: str | None, campos: dict[str, CampoLaudo], fis: Fiscalizacao) -> str:
    """Frase que afirma o resultado de uma checagem deste turno (sempre a partir do estado)."""
    if chk.ferramenta == "serie_ndvi":
        return fato_ndvi(chk)
    if chk.ferramenta == "classificar_foto":
        return fato_classificacao(chk, campos.get(campo or ""))
    c = campos.get(campo or "")
    if chk.ferramenta == "geofence":
        return fato_localizacao(c, chk)
    if c is not None:
        return fato_campo(c, chk, fis)
    motivo = _limpar_motivo(str(chk.resultado.get("motivo") or ""))
    nome = {"checar_lotacao": "Lotação", "carregar_operacao": "Triagem"}.get(chk.ferramenta, chk.ferramenta)
    return f"{nome}: {chk.status}" + (f" ({motivo})." if motivo else ".")


# Palavras da pergunta do fiscal → campo cujo fato o template repete (resposta a dúvida sobre resultado).
_PERGUNTA_CAMPO = {
    "quantidade": r"\b(?:contage\w*|quantidade|animais|cabecas?|bois|vacas?|novilh\w+|gado|lote)\b",
    "comprovante_nfe": r"\b(?:nota|nf-?e)\b",
    "gta": r"\bgta\b",
    "localizacao": r"\b(?:localizacao|geofence|(?:fora|dentro) da gleba)\b",
    "integridade_foto": r"\b(?:integridade|foto)\b",
    "conclusao": r"\b(?:obra|conclus\w+|concluid\w+)\b",
    "ndvi": r"\b(?:pasto|pastagem|ndvi|satelite|vegetacao)\b",
    "prazo_cronograma": r"\b(?:prazo|cronograma)\b",
}
_PERGUNTA = re.compile(r"\?|^(?:por que|porque|como|qual|quais|quanto|quantos|o que|deu|ficou|esta|ta)\b")


def fatos_da_pergunta(texto: str, fis: Fiscalizacao, campos: dict[str, CampoLaudo], maximo: int = 2) -> list[str]:
    """Pergunta do fiscal sobre um resultado ("por que a contagem deu diferente?"): o fato vem do template."""
    t = norm(texto)
    if not t or not _PERGUNTA.search(t):
        return []
    saida: list[str] = []
    for suf, rx in _PERGUNTA_CAMPO.items():
        if not re.search(rx, t):
            continue
        if suf == "ndvi":
            chk = next((x for x in reversed(fis.checagens) if x.ferramenta == "serie_ndvi"), None)
            if chk is not None:
                saida.append(fato_ndvi(chk))
            continue
        for nome, c in campos.items():
            if sufixo(nome) != suf or nome.count(":") < 2 or not c.checagens:
                continue
            chk = next((x for x in reversed(fis.checagens) if x.id in c.checagens), None)
            frase = fato_campo(c, chk, fis) if not (suf == "localizacao" and chk and chk.ferramenta == "geofence") \
                else fato_localizacao(c, chk)
            if frase not in saida:
                saida.append(frase)
        if len(saida) >= maximo:
            break
    return saida[:maximo]


# ---------------------------------------------------------------------------
# Consistência semântica da fala do LLM (POL-09)
# ---------------------------------------------------------------------------


class Violacao(BaseModel):
    tipo: str
    trecho: str
    motivo: str


class AnaliseFala(BaseModel):
    violacoes: list[Violacao] = Field(default_factory=list)
    conducao: list[str] = Field(default_factory=list)  # frases mantidas (sem afirmação de resultado)
    removidas: list[str] = Field(default_factory=list)  # frases que afirmavam resultado (o fato vem do template)

    @property
    def ok(self) -> bool:
        return not self.violacoes


_NEGADO = re.compile(r"\b(?:nao|nem|nunca|sem|nenhum\w*|jamais)\b(?:\s+\w+){0,4}\s*$")

_PROIBIDOS: list[tuple[str, re.Pattern, str]] = [
    ("consequencia_credito", re.compile(
        r"\b(?:impede|impedem|impedir|impedindo|bloqueia|bloqueiam|bloquear|trava|travam|travar|suspende|"
        r"suspender|cancela|cancelar|garante|garantir|atrasa|atrasar|compromete|comprometer)\b[^.!?]{0,25}"
        r"\b(?:liberacao|credito|financiamento|emprestimo|pagamento|recursos?)\b"),
     "consequência sobre o crédito que não está no estado (a fiscalização é posterior à liberação)"),
    ("consequencia_credito", re.compile(
        r"\bliberacao d[oa]s? (?:credito|financiamento|emprestimo|recursos?)\b"
        r"|\b(?:credito|financiamento|emprestimo)\b[^.!?]{0,20}\b(?:negad|liberad|bloquead|suspens|cancelad|"
        r"recusad|cortad|devolvid|vencid)\w*"),
     "consequência sobre o crédito que não está no estado (decisão da instituição, não do agente)"),
    ("consequencia_credito", re.compile(
        r"\b(?:impacto|efeito|consequencia|reflexo|prejuizo|risco)s?\s+(?:\w+\s+){0,2}(?:na|no|nas|nos|sobre a|"
        r"sobre o|para a|para o)\s+(?:decisao de credito|decisao do credito|credito|financiamento|liberacao|"
        r"emprestimo|operacao de credito|pagamento)\b"),
     "efeito sobre o crédito (positivo ou negativo) não está no estado: a decisão é da instituição"),
    ("qualificacao_ilicito", re.compile(
        r"\b(?:fraude\w*|fraudulent\w*|ilicit\w*|crime\w*|criminos\w*|desvio\w*|golpe\w*|ma-?fe|"
        r"irregularidade\w*|irregular(?:es)?|sonegac\w+|falsific\w+|falsidade)\b"),
     "qualificação de fato como ilícito (MCR 2-7-21 e 2-8: decisão da instituição)"),
]
_PASTO = re.compile(r"\b(?:pasto|pastos|pastage\w+|vegetacao|capim|forragem|cobertura vegetal|ndvi|biomassa)\b")
_JUIZO = re.compile(
    r"\b(?:saude|saudave\w*|boa|bom|bons|boas|otim[oa]s?|excelente\w*|ruim|ruins|pessim\w+|degradad\w+|"
    r"vigoros\w+|bem (?:formad|conservad|cuidad|manejad)\w*|mal (?:formad|conservad|cuidad|manejad)\w*|"
    r"frac[oa]s?|fortes?|sec[oa]s?|verdes?|verdinh\w+|vicos\w+|estressad\w+|condicoes|bom estado|mau estado|"
    r"adequad\w+|inadequad\w+|deficient\w+|suficiente\w*|insuficiente\w*|preocupante\w*|critic[oa]s?)\b"
)
_QTD = r"(?:animais|animal|cabecas?|bovinos?|bois?|vacas?|novilh\w+|garrot\w+|bezerr\w+|reses|gado)"
_EXCESSO = re.compile(
    rf"\b(?:excesso|excedent\w*|a mais|sobr(?:a|am|ando|aram|ou)|ultrapass\w+|mais {_QTD} (?:do )?que|"
    rf"(?:contagem|quantidade|numero)\s+(?:\w+\s+){{0,2}}(?:maior|superior|acima)|acima d[oa]s?\s+"
    rf"(?:\d+\s+)?(?:{_QTD}\s+)?(?:financiad\w*|esperad\w*|contratad\w*|projeto|limite))\b"
)
_FALTA = re.compile(
    rf"\b(?:falt(?:a|am|aram|ou|ando)\s+(?:\d+\s+|uns\s+|alguns\s+|cerca de\s+\d+\s+)?{_QTD}|{_QTD}\s+"
    rf"(?:a menos|faltando|faltantes)|falta de {_QTD}|menos {_QTD}|a menos|"
    rf"(?:contagem|quantidade|numero)\s+(?:\w+\s+){{0,2}}(?:menor|inferior|abaixo)|abaixo d[oa]s?\s+"
    rf"(?:\d+\s+)?(?:{_QTD}\s+)?(?:financiad\w*|esperad\w*|contratad\w*|projeto|limite))\b"
)
_LUGAR = r"(?:gleba|poligono|perimetro|area financiada|area do projeto|area|pasto|propriedade|limite)"
_DENTRO = re.compile(rf"(?<!de )\bdentro d[aoe]s?\s+(?:\w+\s+)?{_LUGAR}\b")
_FORA = re.compile(rf"\bfora d[aoe]s?\s+(?:\w+\s+)?{_LUGAR}\b")
_IMPERATIVO = re.compile(
    r"\b(?:tire|tira|refaca|refaz|refazer|faca|faz|envie|envia|mande|manda|fotografe|capture|registre|tirar|"
    r"fotografar|precis\w+|peco|peca|pedir|pede|solicit\w+|reenvi\w+|nova foto|outra foto)\b"
)
_CAMPO_KW: dict[str, re.Pattern] = {
    "quantidade": re.compile(rf"\b(?:contagem|quantidade|{_QTD})\b"),
    "comprovante_nfe": re.compile(r"\b(?:nf-?e|nota fiscal|nota|comprovante_nfe)\b"),
    "gta": re.compile(r"\bgta\b"),
    "integridade_foto": re.compile(r"\b(?:integridade|integridade_foto|fotos?|imagem)\b"),
    "localizacao": re.compile(r"\b(?:localizacao|geofence|posicao)\b"),
    "conclusao": re.compile(r"\b(?:conclusao|obra|concluid[oa]s?|benfeitoria)\b"),
    "independencia_fiscal": re.compile(r"\bindependencia\b"),
}
_ST: dict[str, re.Pattern] = {
    "verificado": re.compile(
        r"\b(?:verificad[oa]s?|confirmad[oa]s?|conferid[oa]s?|confere|conferem|ok|valid[oa]s?|integr[oa]s?|"
        r"aprovad[oa]s?|regular(?:es)?|corret[oa]s?|atestad[oa]s?|sem divergencia|sem problemas?|em ordem)\b"),
    "divergente": re.compile(
        r"\b(?:divergen\w+|nao confere\w*|nao bate\w*|inconsistent\w+|incorret[oa]s?|reprovad[oa]s?|"
        r"com problemas?|errad[oa]s?)\b"),
    "pendente": re.compile(r"\b(?:pendente\w*|inconclusiv\w+|indeterminad\w+)\b"),
    "abstencao": re.compile(r"\babsten\w+"),
}
_ACAO_FEITA = re.compile(
    r"\b(?:registrad[oa]s?|registrei|enviad[oa]s?|enviei|emitid[oa]s?|emiti|gerad[oa]s?|gerei|anotad[oa]s?|"
    r"anotei|salv[oa]s?|salvei|recebid[oa]s?|recebi|atualizad[oa]s?|atualizei|selad[oa]s?|assinad[oa]s?|"
    r"conciliando|verificando|conferindo|checando|analisando|processando|contando|calculando|comparando)\b"
)
_PRONTO = re.compile(
    r"\b(?:laudo|rascunho)\b[^.!?]{0,25}\b(?:complet[oa]|pront[oa]|liberad[oa]|pode ser emitid[oa]|"
    r"pode ser gerad[oa])\b|\b(?:posso|podemos|pode|ja da para|ja pode)\s+(?:emitir|gerar)\b"
    r"|\btodos os (?:requisitos|itens|campos)\b[^.!?]{0,30}\b(?:verificad|atendid|ok|cumprid|complet)"
)
_NUM_QTD = re.compile(rf"\b\d+(?:[.,]\d+)?\s*(?:{_QTD}|m\b|metros?|ha\b|hectares?|cab/ha)")
_RESULTADO = [
    re.compile(r"\bcontagem\s+(?:foi|deu|de\s+\d|ficou|resultou|registrou|indica|mostra|apontou)\b"),
    re.compile(r"\b(?:ndvi|datas? (?:limpas?|sem nuvem))\b"),
    re.compile(r"\b\d+[\d.,]*\s*(?:m|metros?)\s+(?:da|de)\s+(?:borda|gleba)\b"),
    re.compile(r"\b(?:fora|dentro|acima|abaixo|alem)\s+(?:d[aoe]s?|dess[ea]|dest[ea])\s+(?:\w+\s+)?"
               r"(?:margem|tolerancia|limite|intervalo|prazo)"),
    re.compile(r"\bdiferenca\s+(?:entre|de)\s+\d"),
    re.compile(r"\bemitid[oa]s?\s+(?:\d+\s+dias?\s+)?(?:antes|depois)\b"),
]


# ---------------------------------------------------------------------------
# Marcações internas que não podem chegar ao fiscal
# ---------------------------------------------------------------------------

_MARCACAO_BLOCO = re.compile(r"<(dado|contexto|think|tool_call|resultado)\b[^>]*>.*?</\1\s*>",
                             re.DOTALL | re.IGNORECASE)
_MARCACAO_TAG = re.compile(r"</?(?:dado|contexto|think|tool_call|resultado|hash|fala|sistema)\b[^>]*>",
                           re.IGNORECASE)


def limpar_marcacoes(texto: str) -> str:
    """Tira da fala do LLM blocos e tags internas (`<dado ...>...</dado>`, `<contexto>`, `<hash>`...)."""
    t = _MARCACAO_BLOCO.sub(" ", texto or "")
    t = _MARCACAO_TAG.sub(" ", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


# ---------------------------------------------------------------------------
# Ação afirmada × ação executada (POL-09)
# ---------------------------------------------------------------------------


class ContextoAcoes(BaseModel):
    """O que aconteceu de fato no turno: a fala do LLM só pode afirmar ação que está aqui ou no estado."""

    acoes: list[str] = Field(default_factory=list)  # ações permitidas e sem erro no turno (nome)
    checagens: list[str] = Field(default_factory=list)  # ferramentas que geraram checagem no turno
    upload: str | None = None  # tipo da evidência recebida no turno
    alegacoes: int = 0  # alegações registradas no turno


_VERBOS_ACAO: dict[str, str] = {
    "registr": "registrar", "anot": "registrar", "salv": "registrar", "guard": "registrar",
    "receb": "receber",
    "envi": "enviar", "encaminh": "enviar", "mand": "enviar",
    "emit": "emitir", "ger": "emitir",
    "compar": "conferir", "confer": "conferir", "confirm": "conferir", "verific": "conferir", "chequ": "conferir",
    "chec": "conferir", "analis": "conferir", "calcul": "conferir", "concili": "conferir", "consult": "conferir",
    "atualiz": "conferir",
    "ped": "pedir", "solicit": "pedir",
    "assin": "humana", "sel": "humana", "aprov": "humana", "liber": "humana",
    "lig": "terceiros", "contat": "terceiros", "contact": "terceiros",
    "notific": "terceiros", "notifiqu": "terceiros", "avis": "terceiros", "comunic": "terceiros",
    "comuniqu": "terceiros", "inform": "terceiros", "agend": "terceiros",
    "alter": "alterar", "corrig": "alterar", "mud": "alterar", "ajust": "alterar", "marc": "alterar",
    "marqu": "alterar", "apag": "alterar", "apagu": "alterar", "exclu": "alterar", "remov": "alterar",
    "cancel": "alterar",
}
# Pretérito em -ei/-i com mudança ortográfica: verifiquei, chequei, marquei, liguei, apaguei, notifiquei.
_VERBOS_ACAO.update({"verifiqu": "conferir", "ligu": "terceiros"})
_RAIZES = "|".join(sorted(_VERBOS_ACAO, key=len, reverse=True))
# 1ª pessoa do pretérito ("registrei", "enviei", "corrigi", "li a nota") ou particípio com auxiliar ("foi
# registrada", "já está enviado", "acabei de conferir").
_RX_ACAO_1P = re.compile(rf"\b(?:{_RAIZES})(?:ei|i)\b|\bli\s+(?:a|o|as|os)\b")
_RX_ACAO_PART = re.compile(
    rf"\b(?:foi|foram|esta|estao|ja|ficou|ficaram|tem sido)\s+(?:\w+\s+)?(?:{_RAIZES})(?:ad|id)[oa]s?\b"
    rf"|^(?:{_RAIZES})(?:ad|id)[oa]s?\b|\bacab(?:ei|ou|amos) de (?:{_RAIZES})(?:ar|er|ir)\b")
_OBJ_LAUDO = re.compile(r"\b(?:laudo|rascunho|relatorio)\b")
_OBJ_VALOR = re.compile(r"\b(?:valor|contagem|quantidade|status|numero|campo|resultado|como verificad\w*|"
                        r"como conforme|como ok)\b")
_RX_COMO_DISSE = re.compile(r"\bcomo (?:ja )?(?:informei|avisei|comuniquei|disse|falei|expliquei)\b")
_OBJ_CONTATO = re.compile(r"\b(?:contatos?|telefones?|e-?mails?|whats(?:app)?|zap|mensage\w+|ligac\w+)\b")
_DESTINO_TERCEIRO = re.compile(
    r"\b(?:ao|a|para o|para a|pro|pra|com o|com a)\s+(?:banco|cooperativa|gerente|produtor|produtora|vendedor|"
    r"agrodefesa|instituicao|analista|orgao|ministerio|policia|cartorio|tomador|mutuario|veterinari\w+)\b")
_OBJETOS_ACAO: list[tuple[re.Pattern, set[str], set[str]]] = [
    # (objeto no texto, ferramentas que sustentam "conferir", tipos de evidência que sustentam "receber")
    (re.compile(r"\b(?:cpf|cnpj|documentos? d[aoe]s? (?:partes|vendedor|comprador|tomador)|partes)\b"),
     {"conciliar_nfe", "conciliar_gta", "ler_documento_foto", "completar_leitura_documento"}, {"documento"}),
    (re.compile(r"\b(?:nota|nf-?e|danfe|chave|xml)\b"),
     {"conciliar_nfe", "ler_documento_foto", "completar_leitura_documento"}, {"nfe_xml", "documento"}),
    (re.compile(r"\bgta\b|\bguia de transito\b"),
     {"conciliar_gta", "ler_documento_foto", "completar_leitura_documento"}, {"gta", "documento"}),
    (re.compile(r"\b(?:contage\w*|video|filmage\w*|animais|cabecas?|lote|bois?|vacas?|novilh\w*|gado)\b"),
     {"contar_bovinos_video"}, {"video"}),
    (re.compile(r"\b(?:fotos?|localizacao|gleba|gps|imagem|cerca|curral|benfeitoria)\b"),
     {"integridade_foto", "geofence", "classificar_foto"}, {"foto"}),
    (re.compile(r"\b(?:satelite|ndvi|pasto|pastagem|sentinel)\b"), {"serie_ndvi"}, {"satelite"}),
    (re.compile(r"\b(?:regra|norma|mcr|resolucao)\b"), {"explicar_regra"}, set()),
]
_REGISTRO_NO_ESTADO: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:ocorrencia|pressao|injecao)\b"), "ocorrencia"),
    (re.compile(r"\bjustificativa\b"), "justificativa"),
    (re.compile(r"\b(?:declaracao|independencia)\b"), "declaracao"),
    (re.compile(r"\b(?:alegac\w+|o que (?:voce|vc) (?:disse|falou|informou)|sua contagem)\b"), "alegacao"),
    (re.compile(r"\b(?:conclusao|obra)\b"), "conclusao"),
]
_ACOES_DE_REGISTRO = {"registrar_justificativa", "registrar_conclusao_obra", "registrar_ocorrencia",
                      "declaracao_independencia", "completar_leitura_documento"}


def _tipo_do_verbo(trecho: str) -> str | None:
    palavras = trecho.split()
    if len(palavras) >= 2 and palavras[0] == "li":
        return "conferir"
    alvo = palavras[-1] if palavras else trecho
    for r in sorted(_VERBOS_ACAO, key=len, reverse=True):
        if alvo.startswith(r):
            return _VERBOS_ACAO[r]
    return None


def _no_estado(fis: Fiscalizacao, chave: str) -> bool:
    if chave == "ocorrencia":
        return bool(fis.ocorrencias)
    if chave == "justificativa":
        return any(c.justificativa_humana for c in fis.campos.values())
    if chave == "declaracao":
        return any(e.tipo == "declaracao" and e.meta.get("assunto") for e in fis.evidencias)
    if chave == "alegacao":
        return bool(fis.alegacoes)
    if chave == "conclusao":
        return any(c.ferramenta == "declaracao_conclusao" for c in fis.checagens)
    return False


def acao_sustentada(tipo: str, frase: str, fis: Fiscalizacao, ctx: ContextoAcoes, primeira_pessoa: bool = True
                    ) -> bool:
    """A ação que a frase normalizada afirma (registrar, receber, enviar, emitir, conferir, pedir, humana,
    terceiros, alterar) aconteceu no turno (`ctx`) ou está no estado? `primeira_pessoa`: "registrei" (o agente
    diz que fez) × "foi registrado" (passiva: só conta como ação do agente com o objeto típico)."""
    if tipo == "emitir" and not primeira_pessoa and not _OBJ_LAUDO.search(frase):
        return True  # "a GTA foi emitida antes da NF-e": emissão do documento, não ação do agente
    if tipo == "alterar" and not primeira_pessoa and not _OBJ_VALOR.search(frase):
        return True  # "a gleba está marcada no mapa": descrição, não alteração de valor
    if tipo == "humana" and not primeira_pessoa and fis.aprovacoes and _OBJ_LAUDO.search(frase):
        return True  # "o laudo foi assinado" depois da assinatura humana registrada
    if tipo in ("humana", "terceiros", "alterar"):
        return False  # o agente nunca assina/aprova, nunca fala com terceiros e nunca altera valor
    contato = bool(_OBJ_CONTATO.search(frase))
    terceiro = bool(_DESTINO_TERCEIRO.search(frase))
    if tipo in ("enviar", "pedir") and (contato or terceiro):
        return False
    if tipo == "registrar" and contato:
        return False
    ferrs_estado = {c.ferramenta for c in fis.checagens} | set(ctx.checagens) | set(ctx.acoes)
    tipos_ev = {e.tipo for e in fis.evidencias}
    objetos = [(ferrs, evs) for rx, ferrs, evs in _OBJETOS_ACAO if rx.search(frase)]
    if tipo == "registrar":
        if ctx.alegacoes or ctx.upload or set(ctx.acoes) & _ACOES_DE_REGISTRO:
            return True
        regs = [chave for rx, chave in _REGISTRO_NO_ESTADO if rx.search(frase)]
        if regs:
            return any(_no_estado(fis, k) for k in regs)
        return any(evs & tipos_ev for _, evs in objetos)
    if tipo == "receber":
        return bool(ctx.upload) or any(evs & tipos_ev for _, evs in objetos)
    if tipo == "enviar":
        return "solicitar_assinatura" in ctx.acoes or fis.estado_fsm in ("ASSINATURA", "SELADO")
    if tipo == "emitir":
        return "emitir_rascunho" in ctx.acoes or any(e.meta.get("laudo") for e in fis.evidencias)
    if tipo == "conferir":
        if objetos:
            return any(ferrs & ferrs_estado for ferrs, _ in objetos)
        return bool(ctx.checagens or fis.checagens)
    return tipo == "pedir"


def acoes_afirmadas(t: str) -> list[tuple[str, str, bool]]:
    """(tipo da ação, trecho, 1ª pessoa?) de cada ação que a frase normalizada afirma ter acontecido
    ("registrei", "foi enviado", "acabei de conferir"). Negação ("não registrei") e "como informei" não contam."""
    t = _RX_COMO_DISSE.sub(" ", t)
    saida = []
    for rx, primeira in ((_RX_ACAO_1P, True), (_RX_ACAO_PART, False)):
        for m in rx.finditer(t):
            if _negado(t, m.start()):
                continue
            tipo = _tipo_do_verbo(m.group(0))
            if tipo is not None:
                saida.append((tipo, m.group(0), primeira or m.group(0).startswith("acab")))
    return saida


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", texto or "") if f.strip()]


def _clausulas(t: str) -> list[str]:
    return [c.strip() for c in re.split(r"[,;:()—–]|\s-\s|\s+(?:e|mas|porem|enquanto)\s+", t) if c.strip()]


def _negado(t: str, inicio: int) -> bool:
    return bool(_NEGADO.search(t[max(0, inicio - 30):inicio]))


def _status_por_sufixo(campos: dict[str, CampoLaudo]) -> dict[str, set[str]]:
    saida: dict[str, set[str]] = {}
    for nome, c in campos.items():
        if nome.count(":") < 2 and not nome.startswith("laudo:"):
            continue
        saida.setdefault(sufixo(nome), set()).add(c.status)
    return saida


def _posicoes(fis: Fiscalizacao) -> tuple[str | None, set[str]]:
    pos = [posicao_geofence(c) for c in fis.checagens if c.ferramenta == "geofence"]
    return (pos[-1] if pos else None), set(pos)


def analisar_fala(
    texto: str, fis: Fiscalizacao, campos: dict[str, CampoLaudo], pendencias: Iterable[Any] = (),
    acoes: ContextoAcoes | None = None,
) -> AnaliseFala:
    """Consistência semântica (violações) e separação entre afirmação de resultado e condução. `acoes`: o que
    aconteceu no turno (sem ele, só o estado sustenta ação afirmada)."""
    out = AnaliseFala()
    ctx_acoes = acoes or ContextoAcoes()
    texto = limpar_marcacoes(texto)
    dirs = direcao_contagem(fis, campos)
    st_suf = _status_por_sufixo(campos)
    ultima_pos, todas_pos = _posicoes(fis)
    ha_pendencia = bool(list(pendencias))
    rotulos_ndvi = {str(c.resultado.get(k)) for c in fis.checagens if c.ferramenta == "serie_ndvi"
                    for k in ("rotulo", "classe", "classificacao") if c.resultado.get(k)}

    def violar(tipo: str, trecho: str, motivo: str) -> None:
        out.violacoes.append(Violacao(tipo=tipo, trecho=trecho[:160], motivo=motivo))

    for frase in _frases(texto):
        t = norm(frase)
        resultado = False
        for tipo, rx, motivo in _PROIBIDOS:
            for m in rx.finditer(t):
                if tipo == "qualificacao_ilicito" and _negado(t, m.start()):
                    continue
                violar(tipo, frase, motivo)
                resultado = True
                break
        mp = _PASTO.search(t)
        if mp:
            resultado = True
            for mj in _JUIZO.finditer(t):
                if abs(mj.start() - mp.start()) <= 45 and mj.group(0) not in rotulos_ndvi:
                    violar("juizo_pasto", frase, "juízo sobre o pasto sem rótulo de ferramenta (o NDVI é só um "
                           "índice)")
                    break
        tem_qtd = bool(re.search(rf"\b(?:contagem|quantidade|{_QTD})\b", t))
        for claim, rx in (("excesso", _EXCESSO), ("falta", _FALTA)):
            m = rx.search(t)
            if not m or _negado(t, m.start()):
                continue
            if claim == "falta" and m.group(0) == "a menos" and not tem_qtd:
                continue
            if not tem_qtd and claim == "excesso" and "acima" in m.group(0) and "limite" not in m.group(0):
                continue
            resultado = True
            if claim not in dirs:
                sustentado = ", ".join(sorted(dirs)) or "nenhuma contagem"
                violar("direcao_contagem", frase, f"a fala diz {claim}; o estado sustenta: {sustentado}")
        for claim, rx in (("dentro", _DENTRO), ("fora", _FORA)):
            m = rx.search(t)
            if not m or _negado(t, m.start()):
                continue
            if claim == "dentro" and _IMPERATIVO.search(t[:m.start()]):
                continue  # "tire outra foto de dentro da gleba" é instrução, não afirmação
            resultado = True
            historico = bool(re.search(r"\b(?:primeira|anterior\w*|antes|estava\w*|tinha sido|foram)\b", t))
            ok = claim in todas_pos if historico else claim == ultima_pos
            if not ok:
                violar("posicao_foto", frase, f"a fala diz {claim} da gleba; o geofence diz: {ultima_pos or 'nada'}")
        for cl in _clausulas(t):
            campos_cl = [s for s, rx in _CAMPO_KW.items() if rx.search(cl)]
            sts = [(s, m) for s, rx in _ST.items() for m in [rx.search(cl)] if m]
            if _IMPERATIVO.search(cl):
                continue  # pedido ao fiscal ("reenvie uma nota válida") não afirma status
            if campos_cl and sts:
                resultado = True
            if len(campos_cl) != 1 or len(sts) != 1:
                continue
            suf, (st, m) = campos_cl[0], sts[0]
            if suf == "integridade_foto" and "localizacao" in st_suf and re.search(r"\b(?:local|gleba)", cl):
                continue
            reais = st_suf.get(suf) or (st_suf.get("nfe") if suf == "comprovante_nfe" else None)
            if not reais:
                continue
            negado = _negado(cl, m.start())
            aceitos = {"pendente": {"pendente", "abstencao"}}.get(st, {st})
            consistente = (not (reais <= {st})) if negado else bool(reais & aceitos)
            if not consistente:
                violar("status_campo", frase, f"a fala diz {'não ' if negado else ''}{st} para {suf}; o estado "
                       f"diz {', '.join(sorted(reais))}")
        mpr = _PRONTO.search(t)
        if mpr and not _negado(t, mpr.start()) and not re.search(r"\b(?:nao|nem)\b", mpr.group(0)):
            resultado = True
            if ha_pendencia:
                violar("prontidao", frase, "a fala diz que o laudo está pronto ou pode ser emitido, mas há "
                       "pendências")
        for tipo, trecho, primeira in acoes_afirmadas(t):
            resultado = True
            if not acao_sustentada(tipo, t, fis, ctx_acoes, primeira):
                nunca = " (o agente nunca faz isso)" if tipo in ("humana", "terceiros", "alterar") else ""
                violar("acao_nao_executada", frase,
                       f"a fala afirma ação ({trecho!r}) que não aconteceu no turno nem está no estado{nunca}")
                break
        if (_ACAO_FEITA.search(t) or _NUM_QTD.search(t) or any(rx.search(t) for rx in _RESULTADO)
                or (tem_qtd and re.search(r"\d", t))):
            resultado = True
        (out.removidas if resultado else out.conducao).append(frase)
    return out
