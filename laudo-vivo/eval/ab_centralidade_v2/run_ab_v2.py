"""A/B de centralidade v2: entradas do mundo real (papel fotografado e fala livre), formulário × agente.

Pergunta do edital (Solução e Uso de IA): "se o agente fosse removido, a solução ainda entregaria seu valor
principal?". No golden original as entradas eram estruturadas (XML da NF-e, JSON da GTA, contagem simulada) e o
checklist sem LLM empatava com o agente. Aqui as entradas são as que a fiscal recebe: DANFE impresso, GTA em
papel ou PDF de scan e a própria fala no curral (`eval/golden/baguncados/`, gerado por
`eval/golden/gerador/gerar_baguncados.py`).

Braços (mesmas ferramentas determinísticas de conciliação e o mesmo validador nos dois):
- **formulário** (sem LLM): a fiscal DIGITA no celular os campos do papel (chave de 44 dígitos, CNPJ/CPF, datas,
  NCM, CFOP, quantidades, valores, grade da GTA, código do estabelecimento) e a própria contagem/metragem. O
  formulário valida como o agente (DV, aritmética, totais) e pede para redigitar o que não valida (até 3 vezes).
  Erro humano de digitação e tempo vêm de parâmetros citados (`PARAM`, `FONTES`);
- **agente**: foto do papel → `ler_documento_foto` (VLM local + validação; leituras REAIS do qwen3.5:4b gravadas
  por `avaliar_leitura.py`) com até 2 fotos (a 2ª só se algum campo crítico não validou); fala livre → extrator
  de alegações do condutor (LLM real, gravado por `avaliar_narracoes.py`) → `conciliar_alegacoes`;
- **agente + residual** (rodada 3: implementação REAL, `laudo.docs_fiscais.residual`, a mesma do condutor e da
  ferramenta `completar_leitura_documento`): o que não validou nas fotos o agente pede campo a campo, com
  instrução específica (só os críticos indeterminados; chave de acesso em grupos de 4 dígitos); a fiscal fala
  (CPF/CNPJ e código do estabelecimento digitados), com o mesmo modelo de erro humano por caractere; a resposta passa
  pelas mesmas regras determinísticas (DV, coerência, somas) e o que não valida volta em novo pedido (até 3);
- **agente + residual simulado** (o braço da rodada 2, mantido para registrar a diferença): o que não validou em 2
  fotos a fiscal digita no formulário (todos os campos do formulário que ficaram sem valor).

Uso (na raiz; depois de `avaliar_leitura.py --split dev` e `avaliar_narracoes.py --split dev --rotulo final`):
  scripts/py.sh eval/ab_centralidade_v2/run_ab_v2.py
Saída: `eval/reports/<data>_ab_centralidade_v2.md|json`.

No split de TESTE congelado (L07; preparado, rodar uma vez no sha256(src/) final, um modelo por vez):
  scripts/py.sh eval/ab_centralidade_v2/avaliar_leitura.py --split test --final --motivo "L07 AB v2 no teste r4"
  scripts/py.sh eval/ab_centralidade_v2/avaliar_narracoes.py --split test --rotulo r4 --modos llm regex llm_bruto
      regex_bruto llm_bruto_v0 --final --motivo "L07 AB v2 no teste r4"        (numa linha só)
  ollama stop qwen3.5:4b
  scripts/py.sh eval/ab_centralidade_v2/run_ab_v2.py --split test --narracoes dados_locais/eval/narracoes_test_r4.jsonl
      --final --motivo "L07 AB v2 no teste r4" --sufixo _r4_teste                (numa linha só)
  scripts/py.sh eval/gerar_slide.py --data AAAA-MM-DD --sufixo _r4             (dev e teste lado a lado)
Cada passo que toca o teste exige `--final` e `--motivo` e fica no `golden/casos/registro_teste.jsonl` (L41). O
`config` do relatório traz sha256(src/), sha256(eval/), o sha256 dos arquivos de leituras e narrações e as sessões
de gravação deles (modelo, digest, versão do Ollama, opções; `.meta.json` ao lado de cada um; L59).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import yaml

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(AQUI))

import harness as H
import metrics as M
from avaliar_narracoes import checagens_verdadeiras

from laudo.contracts import ItemFinanciado
from laudo.docs_fiscais import leitura as L
from laudo.docs_fiscais import residual as R
from laudo.docs_fiscais.comum import hash_documento
from laudo.docs_fiscais.sintetico import por_extenso
from laudo.tools import documentos as D
from laudo.tools import leitura_documentos as LD
from laudo.tools.alegacoes import conciliar as conciliar_alegacoes

MANIFESTO = REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml"
DIR_CASOS = REPO / "eval" / "golden" / "casos"
HOJE = date(2026, 10, 8)

# ---------------------------------------------------------------------------
# Parâmetros (explícitos; fonte em FONTES ou marcados como hipótese)
# ---------------------------------------------------------------------------

PARAM: dict[str, Any] = {
    "p_erro_caractere": 0.0054,  # [WCC2011] 1 erro não corrigido a cada 23,08 números de 8 dígitos (iPad)
    "p_erro_sensibilidade": [0.0029, 0.0054, 0.0234],  # [G2025] 0,29%/campo (piso); [P2019] 2,34%/caractere
    "tipos_erro": {"substituicao": 0.79, "transposicao": 0.102, "omissao": 0.054, "insercao": 0.054},  # [V1969]
    "t_K": 0.39,  # s por toque, teclado numérico de celular, mediana [H2007]
    "t_K_letra": 0.33,  # s por caractere em teclado de celular (36,17 palavras/min × 5 caracteres) [P2019]
    "t_M": 1.35,  # s de preparação mental por campo [CMN1980]
    "t_S_macro": 0.36,  # s para olhar do celular ao papel ou de volta [H2007]
    "bloco_leitura": 4,  # caracteres lidos do papel por olhada (hipótese; o DANFE agrupa a chave de 4 em 4)
    "t_selecao": 1.35 + 2 * 0.39,  # escolher UF/espécie/finalidade/unidade numa lista: M + 2 toques (hipótese)
    "t_foto": 1.00 + 1.23,  # P (levar o celular ao alvo) + A_picture (posicionar e focar) [H2007]; A4 é hipótese
    "fala_palavras_s": 130.09 / 60,  # palavras/s em fala semiespontânea do português brasileiro [S2019]
    "t_confirmacao": 1.35 + 1.0,  # responder "sim" ao "Entendi 29 cabeças. Confirma?" (hipótese)
    "max_tentativas_campo": 3,  # o formulário pede redigitação até 3 vezes (hipótese)
    "max_fotos": 2,
    "dist_foto_danfe": {"leve": 0.5, "media": 0.35, "pesada": 0.15},  # 1ª foto da fiscal (hipótese)
    "dist_foto_gta": {"scan": 0.3, "media": 0.5, "pesada": 0.2},  # PDF recebido do vendedor ou foto (hipótese)
    "melhor_nivel": {"pesada": "media", "media": "leve", "leve": None, "scan": None},  # refazer a foto
    "melhor_nivel_gta": {"pesada": "media", "media": "scan", "scan": None},
    "replicacoes": 50,
    # residual REAL (rodada 3): erro por caractere lido em voz alta (dígito, letra) = o mesmo da digitação (hipótese:
    # leitura em voz alta + ASR erram na mesma ordem de grandeza que o teclado numérico; ver sensibilidade)
    "p_erro_voz_caractere": 0.0054,
    "t_preparo_campo_residual": 1.35,  # M do KLM antes de cada campo pedido [CMN1980]
}
FONTES = {
    "WCC2011": "Wiseman S, Cairns P, Cox A (2011). A Taxonomy of Number Entry Error. Proc. HCI 2011, BCS eWiC. "
               "doi:10.14236/ewic/hci2011.46",
    "G2025": "Garza MY et al. (2025). Error rates of data processing methods in clinical research: systematic "
             "review and meta-analysis. Int J Med Inform 195:105749, Tabela 2. doi:10.1016/j.ijmedinf.2024.105749",
    "P2019": "Palin K, Feit AM, Kim S, Kristensson PO, Oulasvirta A (2019). How do People Type on Mobile Devices? "
             "MobileHCI '19, Tabela 3. doi:10.1145/3338286.3340120",
    "V1969": "Verhoeff J (1969). Error Detecting Decimal Codes. Mathematical Centre Tracts 29, seções 0.5–0.6",
    "H2007": "Holleis P, Otto F, Hussmann H, Schmidt A (2007). Keystroke-level model for advanced mobile phone "
             "interaction. CHI '07, Tabela 1. doi:10.1145/1240624.1240851",
    "CMN1980": "Card SK, Moran TP, Newell A (1980). The keystroke-level model for user performance time with "
               "interactive systems. CACM 23(7):396–410, Fig. 1. doi:10.1145/358886.358895",
    "S2019": "Santos LP et al. (2019). Velocidade da fala de adultos pessoenses sem transtornos da fluência. Rev. "
             "Bras. Ciências da Saúde 23(2)",
}

CONTEUDO = ["item:{b}:nfe_especie", "item:{b}:nfe_quantidade", "item:{b}:nfe_valor", "item:{b}:nfe_data",
            "item:{b}:nfe_partes", "item:{b}:nfe_operacao", "documento:gta:formato", "item:{b}:gta_especie",
            "item:{b}:gta_quantidade", "item:{b}:gta_destino", "item:{b}:gta_origem", "item:{b}:gta_finalidade",
            "item:{b}:gta_data"]
SELECAO = {"emitente_uf", "destinatario_uf", "tp_nf", "uf_emissao", "especie", "finalidade", "unidade"}
PICKER = {"origem.municipio", "destino.municipio", "emitente_municipio"}  # escolhido numa lista: traz IBGE e UF juntos
NAO_DIGITADOS = {"origem.ibge", "destino.ibge", "origem.uf", "destino.uf", "chave_nfe", "quantidades_por_faixa",
                 "total_machos", "total_femeas", "observacao"}  # observação: texto livre do papel, sem campo  # vêm do picker, são opcionais ou o formulário calcula


# ---------------------------------------------------------------------------
# Valores por campo (espaço dos rótulos) ↔ texto impresso ↔ documento validado
# ---------------------------------------------------------------------------


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def impresso(campo: str, v: Any) -> str:
    """Como o valor aparece no papel (o que a fiscal lê e digita)."""
    if v is None:
        return ""
    folha = campo.rsplit(".", 1)[-1]
    if folha in ("data_emissao", "validade"):
        partes = str(v)[:10].split("-")
        if len(partes) != 3:
            return str(v)
        a, m, d = partes
        return f"{d}/{m}/{a}"
    if folha in ("valor_unitario", "valor_total", "v_prod"):
        return _br(float(v))
    if folha == "quantidade":
        return _br(float(v), 0) if float(v).is_integer() else _br(float(v), 4)
    if campo in ("numero",) and isinstance(v, int):
        return f"{v:09d}"
    if campo == "serie" and isinstance(v, int):
        return f"{v:03d}"
    return str(v)


def bruto_de_valores(tipo: str, v: dict[str, Any]) -> dict[str, Any]:
    """Valores (aceitos, digitados ou verdadeiros) → dicionário "como impresso" para `leitura.validar_*`. A versão
    usada pelo sistema é `residual.bruto_de_campos` (idêntica); esta fica para reproduzir a rodada 2."""
    if tipo == "danfe":
        n_itens = 1 + max([int(k[4:k.index(".")]) for k in v if k.startswith("item") and "." in k] or [0])
        itens = [{"descricao": "ITEM", **{f: impresso(f, v.get(f"item{i}.{f}"))
                                         for f in ("ncm", "cfop", "unidade", "quantidade", "valor_unitario",
                                                   "valor_total")}} for i in range(1, n_itens)]
        b = {k: impresso(k, v.get(k)) for k in ("chave", "numero", "serie", "data_emissao", "tp_nf", "emitente_doc",
                                                "destinatario_doc", "emitente_uf", "destinatario_uf", "v_prod")}
        b.update(itens=itens, v_nf=b["v_prod"], emitente_nome="X", destinatario_nome="X",
                 emitente_municipio=v.get("emitente_municipio") or "")
        return b
    q = v.get("quantidades_por_faixa") or {}
    linhas = [f"{fx} | {m or '-'} | {f or '-'} | {(m + f) or '-'}" for fx, (m, f) in q.items()]
    for fx in L.FAIXAS:
        if fx not in q and q:
            linhas.append(f"{fx} | - | - | -")
    tot = v.get("total")
    if tot is not None and v.get("total_machos") is not None and v.get("total_femeas") is not None:
        linhas.append(f"TOTAL | {v['total_machos']} | {v['total_femeas']} | {tot}")

    def loc(lado: str) -> dict[str, Any]:
        return {"nome": "X", "doc": v.get(f"{lado}.doc") or "", "estabelecimento": "X",
                "codigo_estabelecimento": v.get(f"{lado}.codigo_estabelecimento") or "",
                "municipio": v.get(f"{lado}.municipio") or "", "ibge": v.get(f"{lado}.ibge") or "",
                "uf": v.get(f"{lado}.uf") or ""}

    return {"uf": v.get("uf_emissao") or "", "serie": v.get("serie") or "", "numero": v.get("numero") or "",
            "especie": v.get("especie") or "", "linhas_quantidade": linhas,
            "total_por_extenso": por_extenso(int(tot)) if tot is not None and 0 <= tot < 1000 else "",
            "origem": loc("origem"), "destino": loc("destino"), "finalidade": v.get("finalidade") or "",
            "data_emissao": impresso("data_emissao", v.get("data_emissao")),
            "validade": impresso("validade", v.get("validade")), "local_emissao": "X",
            "chave_nfe": v.get("chave_nfe") or "", "emitente": "X", "observacoes": v.get("observacao") or ""}


def validar(tipo: str, v: dict[str, Any]) -> L.ResultadoLeitura:
    f = L.validar_danfe if tipo == "danfe" else L.validar_gta
    return f(bruto_de_valores(tipo, v), HOJE)


def valores_de_resultado(res: L.ResultadoLeitura, rotulos: dict[str, Any]) -> dict[str, Any]:
    """Campos aceitos (status ok) no espaço dos rótulos; o resto None."""
    out = {}
    for k in rotulos:
        c = res.campos.get(k)
        out[k] = c.valor if c is not None and c.status == "ok" else None
    if "observacao" in rotulos:  # texto livre lido (não validado): só serve à regra de carga parcial
        out["observacao"] = res.documento.get("observacao")
    return out


def igual(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.005
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: list(x) for k, x in a.items()} == {k: list(x) for k, x in b.items()}
    return str(a) == str(b)


# ---------------------------------------------------------------------------
# Braço formulário: digitação com erro humano e redigitação
# ---------------------------------------------------------------------------


def _errar(s: str, rng: random.Random, p: float) -> str:
    out, i = [], 0
    alfabeto = "0123456789" if s.isdigit() else "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
    while i < len(s):
        c = s[i]
        if rng.random() < p:
            r, acc = rng.random(), 0.0
            for tipo, w in PARAM["tipos_erro"].items():
                acc += w
                if r < acc:
                    break
            if tipo == "substituicao":
                out.append(rng.choice([x for x in alfabeto if x != c]))
            elif tipo == "transposicao" and i + 1 < len(s):
                out += [s[i + 1], c]
                i += 1
            elif tipo == "omissao":
                pass
            else:
                out += [c, rng.choice(alfabeto)]
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _digitavel(campo: str, v: Any) -> str:
    """O que se digita: só os caracteres significativos (o formulário põe a máscara)."""
    t = impresso(campo, v)
    folha = campo.rsplit(".", 1)[-1]
    if folha in ("chave", "doc", "emitente_doc", "destinatario_doc", "ncm", "cfop", "numero", "data_emissao",
                 "validade", "quantidade", "valor_unitario", "valor_total", "v_prod", "total", "serie_danfe"):
        return L.digitos(t) if folha not in ("doc", "emitente_doc", "destinatario_doc") else L.so_alnum(t)
    return t


def _de_digitado(campo: str, digitado: str, verdadeiro: Any) -> Any:
    """Texto digitado → valor no espaço dos rótulos (o formulário reaplica a máscara)."""
    folha = campo.rsplit(".", 1)[-1]
    if folha in ("data_emissao", "validade"):
        if len(digitado) != 8:
            return "invalida"
        return f"{digitado[4:]}-{digitado[2:4]}-{digitado[:2]}"
    if folha in ("valor_unitario", "valor_total", "v_prod"):
        return int(digitado) / 100 if digitado.isdigit() else None
    if folha in ("quantidade", "total"):
        return float(digitado) if folha == "quantidade" and digitado.isdigit() else (
            int(digitado) if digitado.isdigit() else None)
    if campo in ("numero", "serie") and isinstance(verdadeiro, int):
        return int(digitado) if digitado.isdigit() else None
    return digitado


def _selecao(campo: str) -> bool:
    return campo.rsplit(".", 1)[-1] in SELECAO


def t_digitar(campo: str, v: Any) -> tuple[float, int]:
    """(segundos, toques) para digitar o campo lendo do papel (KLM)."""
    if _selecao(campo):
        return PARAM["t_selecao"], 2
    if campo in PICKER:
        return PARAM["t_M"] + 4 * PARAM["t_K_letra"] + PARAM["t_K"] + 2 * PARAM["t_S_macro"], 5
    s = _digitavel(campo, v)
    n = len(s)
    k = PARAM["t_K"] if s.isdigit() else PARAM["t_K_letra"]
    blocos = math.ceil(n / PARAM["bloco_leitura"]) if n else 0
    return PARAM["t_M"] + 2 * PARAM["t_S_macro"] * blocos + n * k, n


def campos_formulario(tipo: str, rot: dict[str, Any]) -> list[str]:
    campos = [k for k in rot if k not in NAO_DIGITADOS and not k.endswith(".ibge") and not k.endswith(".uf")]
    if tipo == "gta":
        campos = [k for k in campos if k not in ("total",)] + ["grade"]
    return campos


def _digitar_grade(rot: dict[str, Any], rng: random.Random, p: float) -> tuple[dict[str, Any], float, int]:
    """Células não vazias da grade + o TOTAL impresso; o formulário confere a soma (como o agente)."""
    t, toques = 0.0, 0
    q = {}
    for fx, (m, f) in (rot.get("quantidades_por_faixa") or {}).items():
        cel = []
        for x in (m, f):
            if x:
                d = _errar(str(x), rng, p)
                tt, n = t_digitar("total", x)
                t, toques = t + tt, toques + n
                cel.append(int(d) if d.isdigit() else 0)
            else:
                cel.append(0)
        q[fx] = cel
    tot_d = _errar(str(rot["total"]), rng, p)
    tt, n = t_digitar("total", rot["total"])
    t, toques = t + tt, toques + n
    tot = int(tot_d) if tot_d.isdigit() else None
    soma_m, soma_f = sum(m for m, _ in q.values()), sum(f for _, f in q.values())
    v = {"quantidades_por_faixa": {k: x for k, x in q.items() if any(x)}, "total": tot,
         "total_machos": soma_m, "total_femeas": soma_f}
    if tot is None or soma_m + soma_f != tot:
        v["total"] = -1  # não fecha: o formulário pede redigitação
    return v, t, toques


def formulario(tipo: str, rot: dict[str, Any], rng: random.Random, p: float,
               fixos: dict[str, Any] | None = None, so: list[str] | None = None) -> dict[str, Any]:
    """Digita os campos (todos ou só `so`), valida como o agente e redigita o que não validou."""
    fixos = dict(fixos or {})
    alvo = so if so is not None else campos_formulario(tipo, rot)
    v = {k: fixos.get(k) for k in rot}
    for k in ("origem.ibge", "destino.ibge", "origem.uf", "destino.uf"):  # picker do município
        if f"{k.split('.')[0]}.municipio" in alvo:
            v[k] = rot.get(k)
    tempo, toques, interacoes = 0.0, 0, 0
    pendentes = list(alvo)
    for _tent in range(PARAM["max_tentativas_campo"]):
        for campo in pendentes:
            interacoes += 1
            if campo == "grade":
                g, t, n = _digitar_grade(rot, rng, p)
                v.update(g)
            elif _selecao(campo) or campo in PICKER:
                t, n = t_digitar(campo, rot[campo])
                v[campo] = rot[campo]
                if campo in PICKER:
                    v[campo.replace("municipio", "ibge")] = rot.get(campo.replace("municipio", "ibge"))
            else:
                t, n = t_digitar(campo, rot[campo])
                v[campo] = _de_digitado(campo, _errar(_digitavel(campo, rot[campo]), rng, p), rot[campo])
            tempo, toques = tempo + t, toques + n
        res = validar(tipo, v)
        ruins = {k for k, c in res.campos.items() if c.critico and c.status != "ok"}
        if tipo == "gta" and ruins & {"total", "total_machos", "total_femeas", "quantidades_por_faixa"}:
            ruins |= {"grade"}
        pendentes = [c for c in alvo if c in ruins]
        if not pendentes:
            break
    final = valores_de_resultado(validar(tipo, v), rot)
    return {"valores": final, "tempo_s": tempo, "toques": toques, "interacoes": interacoes}


# ---------------------------------------------------------------------------
# Braço agente: leituras gravadas do VLM (reprocessadas com o código atual)
# ---------------------------------------------------------------------------


def reprocessar(reg: dict[str, Any], k_max: int = 3, so_primeira: bool = False,
                validar_leitura: bool = True) -> tuple[L.ResultadoLeitura | None, int]:
    """Refaz consenso + validação sobre as respostas do VLM gravadas (2 recortes por leitura)."""
    resp = reg.get("respostas_vlm") or []
    nomes = [n for n, *_ in LD.RECORTES[reg["tipo"]]]
    leituras = [LD.montar_bruto(reg["tipo"], dict(zip(nomes, resp[i:i + 2], strict=True)))
                for i in range(0, len(resp) - len(resp) % 2, 2)]
    if not leituras:
        return None, 0
    if so_primeira:
        leituras = leituras[:1]
    brutos = leituras[:2] if len(leituras) >= 2 else leituras
    res, _, disc = LD.consolidar(brutos, reg["tipo"], HOJE)
    if disc and len(leituras) >= 3 and k_max >= 3:
        brutos = leituras[:3]
        res, _, _ = LD.consolidar(brutos, reg["tipo"], HOJE)
    return res, len(brutos)


def valores_brutos(tipo: str, reg: dict[str, Any], rot: dict[str, Any]) -> dict[str, Any]:
    """1ª leitura do VLM SEM consenso e SEM validação, no espaço dos rótulos (o "aceita tudo")."""
    nomes = [n for n, *_ in LD.RECORTES[tipo]]
    resp = reg.get("respostas_vlm") or []
    if len(resp) < 2:
        return {k: None for k in rot}
    b = LD.montar_bruto(tipo, dict(zip(nomes, resp[:2], strict=True)))
    v: dict[str, Any] = {}
    if tipo == "danfe":
        d = L.data_br(b.get("data_emissao"))
        v = {"chave": L.so_alnum(b.get("chave")) or None, "numero": int(L.digitos(b.get("numero")) or -1),
             "serie": int(L.digitos(b.get("serie")) or -1), "data_emissao": d.isoformat() if d else None,
             "tp_nf": b.get("tp_nf") or None, "emitente_doc": L.so_alnum(b.get("emitente_doc")) or None,
             "destinatario_doc": L.so_alnum(b.get("destinatario_doc")) or None,
             "emitente_uf": L.so_alnum(b.get("emitente_uf")) or None,
             "destinatario_uf": L.so_alnum(b.get("destinatario_uf")) or None, "v_prod": L.valor_br(b.get("v_prod"))}
        for i, it in enumerate(b.get("itens") or [], 1):
            v.update({f"item{i}.ncm": L.digitos(it.get("ncm")) or None, f"item{i}.cfop": L.digitos(it.get("cfop")),
                      f"item{i}.unidade": L.so_alnum(it.get("unidade")),
                      f"item{i}.quantidade": L.valor_br(it.get("quantidade")),
                      f"item{i}.valor_unitario": L.valor_br(it.get("valor_unitario")),
                      f"item{i}.valor_total": L.valor_br(it.get("valor_total"))})
    else:
        grade, tot, _ = L._linhas_grade(b.get("linhas_quantidade") or [])
        de, dv = L.data_br(b.get("data_emissao")), L.data_br(b.get("validade"))
        v = {"uf_emissao": L.so_alnum(b.get("uf")) or None, "numero": L.digitos(b.get("numero")) or None,
             "serie": L.sem_acento(b.get("serie")).replace(" ", "") or None,
             "especie": "bovina" if L.sem_acento(b.get("especie")).startswith("BOVIN") else None,
             "total": tot[2] if tot else None, "total_machos": tot[0] if tot else None,
             "total_femeas": tot[1] if tot else None,
             "quantidades_por_faixa": {fx: [m, f] for fx, (m, f, _) in grade.items() if m or f} or None,
             "finalidade": L.sem_acento(b.get("finalidade")).replace(" ", "_") or None,
             "data_emissao": de.isoformat() if de else None, "validade": dv.isoformat() if dv else None,
             "chave_nfe": L.so_alnum(b.get("chave_nfe")) or None}
        for lado in ("origem", "destino"):
            x = b.get(lado) or {}
            v.update({f"{lado}.doc": L.so_alnum(x.get("doc")) or None, f"{lado}.uf": L.so_alnum(x.get("uf")) or None,
                      f"{lado}.ibge": L.digitos(x.get("ibge")) or None,
                      f"{lado}.municipio": L.sem_acento(x.get("municipio")) or None,
                      f"{lado}.codigo_estabelecimento": (str(x.get("codigo_estabelecimento") or "").replace(" ", "")
                                                         .upper() or None)})
    return {k: v.get(k) for k in rot}


def mesclar(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Campo aceito numa foto e não na outra: fica; aceito nas duas com valores diferentes: some."""
    out = {}
    for k in a:
        x, y = a.get(k), b.get(k)
        out[k] = y if x is None else x if y is None else (x if igual(x, y) else None)
    return out


# ---------------------------------------------------------------------------
# Conciliação de um braço
# ---------------------------------------------------------------------------


def conciliar_caso(caso: dict[str, Any], danfes: list[dict[str, Any]], gtas: list[dict[str, Any]],
                   ) -> dict[str, str]:
    """Status dos campos de conteúdo com os documentos de um braço (lista de valores por documento)."""
    ent_n = {k: v for k, v in caso["entradas_ferramentas"]["conciliar_nfe"].items() if k != "caminhos"}
    ent_g = {k: v for k, v in caso["entradas_ferramentas"]["conciliar_gta"].items()
             if k not in ("caminhos", "nfe_caminhos")}
    docs_n = [validar("danfe", v).documento for v in danfes]
    docs_g = [validar("gta", v).documento for v in gtas]
    out: dict[str, str] = {}
    en = D.conciliar_nfe(D.EntradaConciliarNFe(**ent_n, leituras_foto=docs_n))
    eg = D.conciliar_gta(D.EntradaConciliarGTA(**ent_g, leituras_foto=docs_g, nfe_leituras_foto=docs_n))
    b = next(i["id"] for i in caso["operacao"]["itens"] if i["tipo"] == "bovinos")
    for env in (en, eg):
        campos = (env.data or {}).get("campos") or {}
        for c in CONTEUDO:
            nome = c.format(b=b)
            if nome in campos:
                out[nome] = campos[nome]["status"]
            elif ("nfe_" in nome and env is en) or ("gta" in nome and env is eg):
                out[nome] = "erro" if not env.ok else "ausente"
    return out


# ---------------------------------------------------------------------------
# Fala: formulário (campos tipados) × agente (narração livre, extração gravada)
# ---------------------------------------------------------------------------


def fala_formulario(caso: dict[str, Any], nar: dict[str, Any], rot_danfe: list[dict[str, Any]],
                    rng: random.Random, p: float) -> dict[str, Any]:
    itens = [ItemFinanciado.model_validate(i) for i in caso["operacao"]["itens"]]
    bov = next(i for i in itens if i.tipo == "bovinos")
    benf = next(i for i in itens if i.tipo != "bovinos")
    n = nar["crenca_fiscal"]["contagem"]
    als, t, toques = [], 0.0, 0
    dn = _errar(str(n), rng, p)
    tt, k = t_digitar("total", n)
    t, toques = t + tt, toques + k
    if dn.isdigit():
        als.append({"grandeza": "quantidade", "valor": int(dn), "item_id": bov.id, "trecho": f"contei {dn} cabeças"})
    if benf.tipo == "cerca":
        esp = next((e for e in nar["alegacoes_esperadas"] if e["grandeza"] == "comprimento"), None)
        m = int(esp["valor"]) if esp else int(benf.quantidade or 0)  # campo obrigatório: sem medir, vai o projeto
        dm = _errar(str(m), rng, p)
        tt, k = t_digitar("total", m)
        t, toques = t + tt, toques + k
        if dm.isdigit():
            als.append({"grandeza": "comprimento", "valor": int(dm), "item_id": benf.id,
                        "trecho": f"cerca {dm} metros"})
    res = conciliar_alegacoes(als, itens, checagens_verdadeiras(caso, rot_danfe))["alegacoes"]
    corretas = []
    for e in nar["alegacoes_esperadas"]:
        if e["status"] == "registro":
            corretas.append(False)  # item não financiado: não há campo; fica no texto livre, sem conciliação
            continue
        r = next((x for x in res if x["grandeza"] == e["grandeza"]), None)
        corretas.append(bool(r) and r["valor"] == e["valor"] and r["status"] == e["status"])
    return {"corretas": corretas, "tempo_s": t, "toques": toques, "interacoes": 1 + (benf.tipo == "cerca")}


def fala_agente(nar_reg: dict[str, Any] | None, nar: dict[str, Any]) -> dict[str, Any]:
    if nar_reg is None:
        return {"corretas": [False] * len(nar["alegacoes_esperadas"]), "tempo_s": 0.0, "maquina_s": 0.0,
                "interacoes": 0, "nocivas": 0}
    t = nar["palavras"] / PARAM["fala_palavras_s"]
    conf = nar_reg.get("numeros_criticos", 0) > 0
    return {"corretas": [e["correta"] for e in nar_reg["esperadas"]],
            "tempo_s": t + (PARAM["t_confirmacao"] if conf else 0.0), "maquina_s": nar_reg["ms"] / 1000,
            "interacoes": 1 + conf, "nocivas": sum(1 for x in nar_reg["espurias"] if x["status"] != "registro")}


# ---------------------------------------------------------------------------
# Episódio
# ---------------------------------------------------------------------------


def _sortear(dist: dict[str, float], rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for k, w in dist.items():
        acc += w
        if r < acc:
            return k
    return k


def agente_documento(tipo: str, k: int, rot: dict[str, Any], leit: dict[tuple, dict], cid: str,
                     rng: random.Random, residual: bool, p: float, dist: dict[str, float]) -> dict[str, Any]:
    nivel = _sortear(dist, rng)
    melhor = PARAM["melhor_nivel"] if tipo == "danfe" else PARAM["melhor_nivel_gta"]
    valores: dict[str, Any] | None = None
    tempo, maquina, fotos = 0.0, 0.0, 0
    niveis = []
    while nivel and fotos < PARAM["max_fotos"]:
        reg = leit.get((cid, tipo, k, nivel))
        if reg is None:
            break
        res, _ = reprocessar(reg)
        v = valores_de_resultado(res, rot) if res else {x: None for x in rot}
        valores = v if valores is None else mesclar(valores, v)
        fotos += 1
        niveis.append(nivel)
        tempo += PARAM["t_foto"]
        maquina += reg["ms"] / 1000
        faltam = [c for c in campos_formulario(tipo, rot) if c != "grade" and valores.get(c) is None]
        if tipo == "gta" and valores.get("total") is None:
            faltam.append("grade")
        if not faltam:
            break
        nivel = melhor.get(nivel)
    valores = valores or {x: None for x in rot}
    out = {"valores": valores, "tempo_s": tempo, "maquina_s": maquina, "fotos": fotos, "niveis": niveis,
           "interacoes": fotos, "toques": 0}
    if residual:
        faltam = [c for c in campos_formulario(tipo, rot) if c != "grade" and valores.get(c) is None]
        if tipo == "gta" and valores.get("total") is None:
            faltam.append("grade")
        if faltam:
            f = formulario(tipo, rot, rng, p, fixos=valores, so=faltam)
            out.update(valores=f["valores"], tempo_s=tempo + f["tempo_s"], toques=f["toques"],
                       interacoes=fotos + f["interacoes"], residuais=faltam)
    return out


def leitura_real(reg: dict[str, Any]) -> dict[str, Any] | None:
    """Saída de `ler_documento_foto` (a do sistema, com `pedido_residual`) reprocessada das respostas gravadas."""
    resp = reg.get("respostas_vlm") or []
    nomes = [n for n, *_ in LD.RECORTES[reg["tipo"]]]
    leituras = [LD.montar_bruto(reg["tipo"], dict(zip(nomes, resp[i:i + 2], strict=True)))
                for i in range(0, len(resp) - len(resp) % 2, 2)]
    if not leituras:
        return None
    brutos = leituras[:2] if len(leituras) >= 2 else leituras
    res, concord, disc = LD.consolidar(brutos, reg["tipo"], HOJE)
    if disc and len(leituras) >= 3:
        brutos = leituras[:3]
        res, concord, _ = LD.consolidar(brutos, reg["tipo"], HOJE)
    return LD.saida_leitura(res, brutos, concord, reg["tipo"])


def valores_de_saida(saida: dict[str, Any], rot: dict[str, Any]) -> dict[str, Any]:
    """Campos aceitos de uma saída do sistema (leitura ou completação) no espaço dos rótulos. CPF/CNPJ saem só
    como hash: o valor é o do rótulo se o hash confere (senão, um documento que não é o do papel)."""
    campos = saida.get("campos") or {}
    out = {k: ((campos.get(k) or {}).get("valor") if (campos.get(k) or {}).get("status") == "ok" else None)
           for k in rot}
    doc = saida.get("documento") or {}
    partes = ({"emitente_doc": "emitente", "destinatario_doc": "destinatario"} if saida.get("tipo_documento") == "danfe"
              else {"origem.doc": "origem", "destino.doc": "destino"})
    for nome, parte in partes.items():
        if nome not in rot:
            continue
        p = doc.get(parte) if isinstance(doc.get(parte), dict) else {}
        h = (p or {}).get("doc_sha256") or (p or {}).get("documento_sha256")
        out[nome] = (rot[nome] if h == hash_documento(rot[nome]) else "DOCUMENTO-DIFERENTE") if h else None
    if "observacao" in rot:
        out["observacao"] = doc.get("observacao")
    return out


def _palavras_faladas(fala: str) -> float:
    """Palavras ditas: número por extenso ~ uma palavra a cada 2 dígitos (≥ 1); dígitos soltos, uma cada."""
    n = 0.0
    for tok in fala.replace(",", " ").split():
        dig = L.digitos(tok)
        n += max(1.0, math.ceil(len(dig) / 2)) if len(dig) > 1 else 1.0
    return n


def residual_real(tipo: str, saida: dict[str, Any], rot: dict[str, Any], rng: random.Random, p_tecla: float,
                  p_voz: float) -> dict[str, Any]:
    """A fiscal responde ao pedido do sistema (real), lendo o papel com erro humano; o sistema valida (real) e
    pede de novo o que não validou, até `residual.MAX_TENTATIVAS`."""
    tempo, toques, interacoes, falas = 0.0, 0, 0, 0
    leitura = saida
    pedidos: list[list[str]] = []
    while (ped_d := leitura.get("pedido_residual")) is not None:
        ped = R.PedidoResidual.model_validate(ped_d)
        if not ped.campos:
            break
        pedidos.append(ped.nomes)
        texto, dig = R.resposta_do_papel(ped, rot)
        # erro humano: cada caractere falado/digitado pode sair errado (mesmo modelo de erro da digitação)
        texto_err = " ".join(_errar(tok, rng, p_voz) if any(ch.isdigit() for ch in tok) else tok
                             for tok in texto.split(" "))
        dig_err = {k: _errar(L.so_alnum(v) if k.endswith("doc") else v, rng, p_tecla) for k, v in dig.items()}
        # (dupla digitação do código do estabelecimento: as duas cópias erram de forma independente)
        n_voz = sum(1 for c in ped.campos if c.modo != "digitacao")
        tempo += PARAM["t_preparo_campo_residual"] * len(ped.campos) + 2 * PARAM["t_S_macro"] * len(ped.campos)
        tempo += _palavras_faladas(texto) / PARAM["fala_palavras_s"] if n_voz else 0.0
        for k, v in dig.items():
            t, n = t_digitar(k, v)
            tempo, toques = tempo + t, toques + n
        falas += 1 if n_voz else 0
        interacoes += len(ped.campos)
        env = LD.completar_leitura_documento(LD.EntradaCompletarLeitura(
            leitura=leitura, texto=texto_err or None, respostas=dig_err, data_referencia=HOJE))
        if not env.ok:
            break
        leitura = {**leitura, **env.data}
    return {"saida": leitura, "tempo_s": tempo, "toques": toques, "interacoes": interacoes, "falas": falas,
            "pedidos": pedidos, "tentativas": len(pedidos)}


def agente_documento_real(tipo: str, k: int, rot: dict[str, Any], leit: dict[tuple, dict], cid: str,
                          rng: random.Random, p: float, dist: dict[str, float]) -> dict[str, Any]:
    """Braço agente + residual REAL: fotos como no braço agente (a 2ª só se algum crítico não validou); depois o
    pedido do sistema para o que restou da última foto, respondido pela fiscal e validado pelo sistema."""
    nivel = _sortear(dist, rng)
    melhor = PARAM["melhor_nivel"] if tipo == "danfe" else PARAM["melhor_nivel_gta"]
    valores: dict[str, Any] | None = None
    tempo, maquina, fotos, niveis = 0.0, 0.0, 0, []
    saida = None
    while nivel and fotos < PARAM["max_fotos"]:
        reg = leit.get((cid, tipo, k, nivel))
        if reg is None:
            break
        s = leitura_real(reg)
        if s is None:
            break
        v = valores_de_saida(s, rot)
        valores = v if valores is None else mesclar(valores, v)
        saida = s
        fotos += 1
        niveis.append(nivel)
        tempo += PARAM["t_foto"]
        maquina += reg["ms"] / 1000
        if not R.criticos_indeterminados(s):
            break
        nivel = melhor.get(nivel)
    valores = valores or {x: None for x in rot}
    out = {"valores": valores, "tempo_s": tempo, "maquina_s": maquina, "fotos": fotos, "niveis": niveis,
           "interacoes": fotos, "toques": 0, "residual": None}
    if saida is not None and saida.get("pedido_residual"):
        p_voz = PARAM["p_erro_voz_caractere"] * p / PARAM["p_erro_caractere"]  # acompanha a sensibilidade
        r = residual_real(tipo, saida, rot, rng, p, p_voz)
        final = valores_de_saida(r["saida"], rot)
        out.update(valores=mesclar(valores, final) if fotos > 1 else final,
                   tempo_s=tempo + r["tempo_s"], toques=r["toques"], interacoes=fotos + r["interacoes"],
                   residual={"tentativas": r["tentativas"], "pedidos": r["pedidos"],
                             "status": r["saida"].get("status")})
    return out


def episodio(c: dict[str, Any], leit: dict[tuple, dict], nar_regs: dict[str, dict], rep: int,
             p: float, dist_danfe: dict[str, float], dist_gta: dict[str, float]) -> dict[str, Any]:
    caso = yaml.safe_load((DIR_CASOS / c["id"] / "caso.yaml").read_text(encoding="utf-8"))
    rot_n, rot_g = c["rotulos"]["danfe"], c["rotulos"]["gta"]
    out: dict[str, Any] = {"id": c["id"], "classe": c["classe"], "codigo": c["codigo"], "rep": rep}
    oraculo = conciliar_caso(caso, rot_n, rot_g)
    out["oraculo"] = oraculo
    bracos = {}
    for braco in BRACOS:
        rng = random.Random(f"ab_v2:{c['id']}:{rep}:{braco if braco == 'formulario' else 'agente'}")
        docs_n, docs_g, tempo, maquina, inter, toques, fotos = [], [], 0.0, 0.0, 0, 0, 0
        campos = []
        residuais: list[dict[str, Any]] = []
        for tipo, rots, docs in (("danfe", rot_n, docs_n), ("gta", rot_g, docs_g)):
            for k, rot in enumerate(rots, 1):
                if braco == "formulario":
                    r = formulario(tipo, rot, rng, p)
                    r["maquina_s"], r["fotos"] = 0.0, 0
                elif braco == "agente_residual":
                    r = agente_documento_real(tipo, k, rot, leit, c["id"], rng, p,
                                              dist_danfe if tipo == "danfe" else dist_gta)
                    if r.get("residual"):
                        residuais.append({"tipo": tipo, "doc": k, **r["residual"]})
                else:
                    r = agente_documento(tipo, k, rot, leit, c["id"], rng, braco == "agente_residual_simulado", p,
                                         dist_danfe if tipo == "danfe" else dist_gta)
                docs.append(r["valores"])
                tempo, maquina = tempo + r["tempo_s"], maquina + r["maquina_s"]
                inter, toques, fotos = inter + r["interacoes"], toques + r.get("toques", 0), fotos + r["fotos"]
                for campo in campos_formulario(tipo, rot):
                    nomes = ["total", "total_machos", "total_femeas"] if campo == "grade" else [campo]
                    for nm in nomes:
                        val = r["valores"].get(nm)
                        campos.append({"tipo": tipo, "campo": nm, "certo": igual(val, rot.get(nm)),
                                       "aceito_errado": val is not None and not igual(val, rot.get(nm))})
        status = conciliar_caso(caso, docs_n, docs_g)
        nar = c["narracao"]
        if braco == "formulario":
            fala = fala_formulario(caso, nar, rot_n, rng, p)
            fala["maquina_s"], fala["nocivas"] = 0.0, 0
        else:
            fala = fala_agente(nar_regs.get(c["id"]), nar)
        tempo, maquina, inter = tempo + fala["tempo_s"], maquina + fala["maquina_s"], inter + fala["interacoes"]
        iguais = {k: status.get(k) == v for k, v in oraculo.items()}
        bracos[braco] = {
            "status": status, "campos": campos, "conteudo_ok": all(iguais.values()),
            "div_esperadas": sum(1 for v in oraculo.values() if v == "divergente"),
            "div_detectadas": sum(1 for k, v in oraculo.items() if v == "divergente" and status.get(k) == v),
            "falsas_div": sum(1 for k, v in status.items() if v == "divergente" and oraculo.get(k) != "divergente"),
            "pendentes_a_mais": sum(1 for k, v in status.items() if v in ("indeterminado", "erro", "ausente")
                                    and oraculo.get(k) not in ("indeterminado",)),
            "alegacoes_corretas": fala["corretas"], "alegacoes_nocivas": fala["nocivas"],
            "completa": all(iguais.values()) and all(fala["corretas"]),
            # sem as menções a item não financiado (o formulário não tem campo para elas, por construção)
            "completa_sem_registro": all(iguais.values()) and all(
                c for c, e in zip(fala["corretas"], nar["alegacoes_esperadas"], strict=True)
                if e["status"] != "registro"),
            "tempo_fiscal_s": round(tempo, 1), "tempo_maquina_s": round(maquina, 1), "interacoes": inter,
            "toques": toques, "fotos": fotos, "residuais": residuais,
        }
    out["bracos"] = bracos
    return out


# ---------------------------------------------------------------------------
# Métricas de leitura (por campo, por nível) e quanto a validação barrou
# ---------------------------------------------------------------------------


def metricas_leitura(man: dict[str, Any], leit_regs: list[dict[str, Any]]) -> dict[str, Any]:
    rot_por = {}
    for c in man["casos"]:
        for tipo in ("danfe", "gta"):
            for k, r in enumerate(c["rotulos"][tipo], 1):
                rot_por[(c["id"], tipo, k)] = r
    por_campo: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    por_nivel: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    barragem = defaultdict(int)
    docs = defaultdict(lambda: defaultdict(int))
    tipo_auto = defaultdict(int)
    lat = defaultdict(list)
    for reg in leit_regs:
        rot = rot_por.get((reg["id"], reg["tipo"], reg["doc"]))
        if rot is None or "respostas_vlm" not in reg:
            continue
        res, _ = reprocessar(reg)
        res1, _ = reprocessar(reg, so_primeira=True)
        v = valores_de_resultado(res, rot) if res else {k: None for k in rot}
        v1 = valores_de_resultado(res1, rot) if res1 else {k: None for k in rot}
        cru = valores_brutos(reg["tipo"], reg, rot)
        tipo_auto[("certo" if reg.get("tipo_auto") == reg["tipo"] else "errado")] += 1
        lat[reg["tipo"]].append(reg["ms"] / 1000)
        crit = [k for k in rot if k not in ("chave_nfe", "quantidades_por_faixa", "observacao", "emitente_municipio")]
        docs[(reg["tipo"], reg["nivel"])]["n"] += 1
        docs[(reg["tipo"], reg["nivel"])]["todos_criticos_ok"] += all(igual(v[k], rot[k]) for k in crit)
        docs[(reg["tipo"], reg["nivel"])]["algum_aceito_errado"] += any(
            v[k] is not None and not igual(v[k], rot[k]) for k in crit)
        for k in [x for x in rot if x != "observacao"]:
            nome = k.split(".", 1)[1] if k.startswith("item") else k
            ok, errado = igual(v[k], rot[k]), v[k] is not None and not igual(v[k], rot[k])
            for d in (por_campo[(reg["tipo"], nome)], por_nivel[(reg["tipo"], reg["nivel"])]):
                d["n"] += 1
                d["certo"] += ok
                d["aceito_errado"] += errado
                d["barrado"] += v[k] is None
            cru_ok = igual(cru.get(k), rot[k])
            barragem["n"] += 1
            barragem["cru_errado"] += not cru_ok and cru.get(k) is not None
            barragem["cru_vazio"] += cru.get(k) is None
            barragem["cru_errado_barrado"] += (not cru_ok and cru.get(k) is not None) and v[k] is None
            barragem["cru_errado_corrigido"] += (not cru_ok and cru.get(k) is not None) and ok
            barragem["cru_errado_aceito"] += (not cru_ok and cru.get(k) is not None) and errado
            barragem["cru_certo_barrado"] += cru_ok and v[k] is None
            barragem["k1_validado_errado"] += v1[k] is not None and not igual(v1[k], rot[k])
            barragem["k1_validado_certo"] += igual(v1[k], rot[k])
    return {"por_campo": {f"{t}:{n}": dict(d) for (t, n), d in sorted(por_campo.items())},
            "por_nivel": {f"{t}:{n}": dict(d) for (t, n), d in sorted(por_nivel.items())},
            "documentos": {f"{t}:{n}": dict(d) for (t, n), d in sorted(docs.items())},
            "barragem": dict(barragem), "tipo_auto": dict(tipo_auto),
            "latencia_s": {t: {"p50": M.percentil(x, 0.5), "p95": M.percentil(x, 0.95), "n": len(x)}
                           for t, x in lat.items()}}


# ---------------------------------------------------------------------------
# Resumo e relatório
# ---------------------------------------------------------------------------


def _mcnemar(b: int, c: int) -> float | None:
    n = b + c
    if n == 0:
        return None
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


BRACOS = ("formulario", "agente", "agente_residual", "agente_residual_simulado")


def resumir(eps: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for braco in BRACOS:
        bs = [e["bracos"][braco] for e in eps]
        campos = [x for b in bs for x in b["campos"]]
        al = [x for b in bs for x in b["alegacoes_corretas"]]
        out[braco] = {
            "n": len(bs),
            "campos_certos": M.proporcao(sum(x["certo"] for x in campos), len(campos)),
            "campos_aceitos_errados": M.proporcao(sum(x["aceito_errado"] for x in campos), len(campos)),
            "conteudo_igual_oraculo": M.proporcao(sum(b["conteudo_ok"] for b in bs), len(bs)),
            "divergencias_detectadas": M.proporcao(sum(b["div_detectadas"] for b in bs),
                                                   sum(b["div_esperadas"] for b in bs)),
            "falsas_divergencias": sum(b["falsas_div"] for b in bs),
            "campos_pendentes_a_mais": sum(b["pendentes_a_mais"] for b in bs),
            "alegacoes_corretas": M.proporcao(sum(al), len(al)),
            "alegacoes_nocivas": sum(b["alegacoes_nocivas"] for b in bs),
            "completas": M.proporcao(sum(b["completa"] for b in bs), len(bs)),
            "completas_sem_registro": M.proporcao(sum(b["completa_sem_registro"] for b in bs), len(bs)),
            "tempo_fiscal_s_mediana": M.percentil([b["tempo_fiscal_s"] for b in bs], 0.5),
            "tempo_fiscal_s_media": sum(b["tempo_fiscal_s"] for b in bs) / len(bs),
            "tempo_maquina_s_mediana": M.percentil([b["tempo_maquina_s"] for b in bs], 0.5),
            "interacoes_media": sum(b["interacoes"] for b in bs) / len(bs),
            "toques_media": sum(b["toques"] for b in bs) / len(bs),
            "fotos_media": sum(b["fotos"] for b in bs) / len(bs),
            "documentos_com_residual": sum(len(b.get("residuais") or []) for b in bs),
            "residual_tentativas_media": (sum(r["tentativas"] for b in bs for r in b.get("residuais") or [])
                                          / max(1, sum(len(b.get("residuais") or []) for b in bs))),
            "residual_completo": M.proporcao(sum(1 for b in bs for r in b.get("residuais") or []
                                                 if r.get("status") == "ok"),
                                             sum(len(b.get("residuais") or []) for b in bs)),
        }
    pares = {}
    for alvo in ("agente", "agente_residual", "agente_residual_simulado"):
        for chave, sufixo in (("completa", ""), ("completa_sem_registro", "_sem_registro")):
            so_a = sum(1 for e in eps if e["bracos"][alvo][chave] and not e["bracos"]["formulario"][chave])
            so_f = sum(1 for e in eps if e["bracos"]["formulario"][chave] and not e["bracos"][alvo][chave])
            pares[alvo + sufixo] = {"so_agente": so_a, "so_formulario": so_f, "mcnemar_p_exato": _mcnemar(so_a, so_f)}
    out["pareado"] = pares
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--leituras", default=None)
    ap.add_argument("--narracoes", default=None)
    ap.add_argument("--saida", default=str(REPO / "eval" / "reports"))
    ap.add_argument("--replicacoes", type=int, default=PARAM["replicacoes"])
    ap.add_argument("--sufixo", default="", help="sufixo do nome do relatório (não sobrescreve o do mesmo dia)")
    ap.add_argument("--final", action="store_true", help="autoriza o split de teste congelado (exige --motivo)")
    ap.add_argument("--motivo", default=None)
    a = ap.parse_args()
    man = yaml.safe_load(MANIFESTO.read_text(encoding="utf-8"))
    split_golden = H.carregar_split()
    toca = H.toca_teste(split_golden, {"alvo": [c["id"] for c in man["casos"] if c["split"] == a.split]})
    erros = H.checar_uso_do_teste(toca, a.final, a.motivo, split_golden)
    if erros:
        print("execução recusada:")
        for e in erros:
            print("  " + e)
        return 2
    arq_l = Path(a.leituras or REPO / "dados_locais" / "eval" / f"leitura_v2_{a.split}.jsonl")
    arq_n = Path(a.narracoes or REPO / "dados_locais" / "eval" / f"narracoes_{a.split}_final.jsonl")
    faltam = [str(p) for p in (arq_l, arq_n) if not p.exists()]
    if faltam:  # antes do registro: sem as gravações, nada do teste é usado
        print("gravações ausentes (rode avaliar_leitura.py e avaliar_narracoes.py antes):", *faltam)
        return 2
    extra = {"split": a.split, "sufixo": a.sufixo, "sha256_src": H.hash_src(),
             "gravacoes": {"leituras": arq_l.name, "narracoes": arq_n.name}}
    with H.uso_do_teste(toca and a.final, script="eval/ab_centralidade_v2/run_ab_v2.py", alvo="ab_v2_test",
                        motivo=a.motivo, argv=sys.argv[1:], extra=extra) as uso:
        return _rodar(a, man, uso, toca, arq_l, arq_n)


def _gravacao(arq: Path) -> dict[str, Any]:
    """Arquivo de respostas gravadas (leituras do VLM ou narrações): sha256 e as sessões do `.meta.json` ao lado
    (modelo, digest, versão do Ollama, opções). Gravação anterior ao L59 não tem `.meta.json`: "n/a"."""
    meta = arq.with_name(arq.stem + ".meta.json")
    return {"arquivo": arq.name, "sha256": H.sha256_arquivo(arq) if arq.exists() else H.NA,
            "meta": json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else H.NA}


def _rodar(a: argparse.Namespace, man: dict[str, Any], uso: dict[str, Any] | None, toca: bool, arq_l: Path,
           arq_n: Path) -> int:
    leit_regs = [json.loads(x) for x in arq_l.read_text(encoding="utf-8").splitlines() if x.strip()]
    leit = {(r["id"], r["tipo"], r["doc"], r["nivel"]): r for r in leit_regs if "respostas_vlm" in r}
    nar_regs = {}
    nar_todos = [json.loads(x) for x in arq_n.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in nar_todos:
        if r["modo"] == "llm":
            nar_regs[r["id"]] = r
    casos = [c for c in man["casos"] if c["split"] == a.split
             and all((c["id"], f["tipo"], f["doc"], f["nivel"]) in leit for f in c["arquivos"])]
    p = PARAM["p_erro_caractere"]
    dd, dg = PARAM["dist_foto_danfe"], PARAM["dist_foto_gta"]
    eps1 = [episodio(c, leit, nar_regs, 0, p, dd, dg) for c in casos]
    principal = resumir(eps1)
    # estabilidade: médias sobre réplicas (sorteio da foto e dos erros de digitação)
    reps = [resumir([episodio(c, leit, nar_regs, r, p, dd, dg) for c in casos]) for r in range(1, a.replicacoes)]

    def media(braco: str, chave: str) -> float | None:
        xs = [r[braco][chave]["p"] if isinstance(r[braco][chave], dict) else r[braco][chave] for r in reps]
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    chaves_estab = ("campos_certos", "completas", "completas_sem_registro", "alegacoes_corretas",
                    "divergencias_detectadas", "tempo_fiscal_s_media")
    estab = {b: {k: media(b, k) for k in chaves_estab} for b in BRACOS} if reps else {}
    # sensibilidade: taxa de erro de digitação e qualidade da 1ª foto
    sens = {}
    for pp in PARAM["p_erro_sensibilidade"]:
        sens[f"p_erro={pp}"] = {b: {k: (v["p"] if isinstance(v, dict) else v) for k, v in s.items()
                                    if k in ("campos_certos", "completas", "completas_sem_registro",
                                             "tempo_fiscal_s_media")}
                                for b, s in resumir([episodio(c, leit, nar_regs, 0, pp, dd, dg)
                                                     for c in casos]).items() if b != "pareado"}
    for nome, d1, d2 in (("foto_boa", {"leve": 1.0}, {"scan": 1.0}), ("foto_ruim", {"pesada": 1.0},
                                                                       {"pesada": 1.0})):
        sens[nome] = {b: {k: (v["p"] if isinstance(v, dict) else v) for k, v in s.items()
                          if k in ("campos_certos", "completas", "completas_sem_registro", "tempo_fiscal_s_media")}
                      for b, s in resumir([episodio(c, leit, nar_regs, 0, p, d1, d2) for c in casos]).items()
                      if b != "pareado"}
    leitura = metricas_leitura(man, [r for r in leit_regs if r["split"] == a.split])
    sanidade = sanidade_oraculo(eps1)
    llm = H.info_llm(None) | {"nota": "este script não chama LLM: usa as respostas gravadas (ver gravacoes)"}
    res = {"config": {"data": H.data_rodada(), "split": a.split,
                      "n_casos": len(casos), "param": PARAM, "fontes": FONTES, "leituras": str(arq_l.name),
                      "narracoes": str(arq_n.name), "manifesto_sha256_conteudo": man["sha256_conteudo"],
                      "sha256_src": H.hash_src(), "argv": H.argv_seguro(sys.argv[1:]),
                      "final": bool(toca and a.final), "motivo": a.motivo if toca and a.final else None,
                      "execucao_registro": (uso or {}).get("execucao"),
                      "gravacoes": {"leituras": _gravacao(arq_l), "narracoes": _gravacao(arq_n)}}
                      | H.config_reprodutivel(llm=llm),
           "principal": principal, "estabilidade_replicacoes": estab, "sensibilidade": sens,
           "leitura": leitura, "fala": metricas_fala(nar_todos), "sanidade_oraculo": sanidade, "episodios": eps1}
    out = Path(a.saida)
    nome = f"{res['config']['data']}_ab_centralidade_v2{a.sufixo}"
    (out / f"{nome}.json").write_text(json.dumps(_arredondar(res), ensure_ascii=False, indent=1, default=str),
                                      encoding="utf-8")
    md = relatorio(res)
    (out / f"{nome}.md").write_text(md, encoding="utf-8")
    if uso is not None:
        r = principal["agente_residual"]
        f = principal["formulario"]
        uso["resultado"] = {"relatorio": H.argv_seguro([str(out / f"{nome}.json")])[0],
                            "relatorio_sha256": H.sha256_arquivo(out / f"{nome}.json"),
                            "resumo": {"n_casos": len(casos),
                                       "residual_completas": f"{r['completas']['k']}/{r['completas']['n']}",
                                       "formulario_completas": f"{f['completas']['k']}/{f['completas']['n']}"}}
    print(md)
    return 0


def metricas_fala(regs: list[dict[str, Any]]) -> dict[str, Any]:
    """Extração de alegações da narração livre, por modo (com/sem LLM, com/sem normalização de números)."""
    out: dict[str, Any] = {}
    for modo in dict.fromkeys(r["modo"] for r in regs):
        rs = [r for r in regs if r["modo"] == modo]
        esp = [e for r in rs for e in r["esperadas"]]
        dp = [e for e in esp if e["status"] in ("divergente", "pendente")]
        out[modo] = {
            "alegacoes_corretas": M.proporcao(sum(e["correta"] for e in esp), len(esp)),
            "divergencias_pendencias": M.proporcao(sum(e["correta"] for e in dp), len(dp)),
            "narracoes_inteiras": M.proporcao(sum(all(e["correta"] for e in r["esperadas"])
                                                  and not any(x["status"] != "registro" for x in r["espurias"])
                                                  for r in rs), len(rs)),
            "espurias_nocivas": sum(1 for r in rs for x in r["espurias"] if x["status"] != "registro"),
            "latencia_s_p50": M.percentil([r["ms"] / 1000 for r in rs], 0.5),
        }
    return out


def _arredondar(x: Any) -> Any:
    """Floats com 4 casas: dízimas longas parecem CPF/CNPJ para o `checar_pii.py` (e não informam nada)."""
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, dict):
        return {k: _arredondar(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_arredondar(v) for v in x]
    return x


def sanidade_oraculo(eps: list[dict[str, Any]]) -> dict[str, Any]:
    """O oráculo (papel lido perfeitamente) reproduz os rótulos do golden nos campos de conteúdo?"""
    iguais = total = 0
    difs = []
    for e in eps:
        caso = yaml.safe_load((DIR_CASOS / e["id"] / "caso.yaml").read_text(encoding="utf-8"))
        mapa = {"ok": "verificado", "divergente": "divergente", "indeterminado": "pendente"}
        for campo, st in e["oraculo"].items():
            esp = (caso["esperado"]["campos"].get(campo) or {}).get("status_esperado")
            if esp is None:
                continue
            total += 1
            if mapa.get(st) == esp or (esp == "abstencao" and st == "indeterminado"):
                iguais += 1
            else:
                difs.append(f"{e['id']} ({e['codigo']}) {campo}: oráculo {st}, golden {esp}")
    return {"iguais": iguais, "total": total, "diferencas": difs}


def relatorio(res: dict[str, Any]) -> str:
    s, cfg = res["principal"], res["config"]
    f, ag, ar, asim = s["formulario"], s["agente"], s["agente_residual"], s["agente_residual_simulado"]

    def num(x: Any, casas: int = 1) -> str:
        return "n/d" if x is None else f"{x:.{casas}f}".replace(".", ",")

    def lin(nome: str, chave: str, pct: bool = True, casas: int = 1) -> str:
        if pct:
            return (f"| {nome} | {M.fmt(f[chave], True)} | {M.fmt(ag[chave], True)} | {M.fmt(ar[chave], True)} | "
                    f"{M.fmt(asim[chave], True)} |")
        return (f"| {nome} | {num(f[chave], casas)} | {num(ag[chave], casas)} | {num(ar[chave], casas)} | "
                f"{num(asim[chave], casas)} |")

    pa, pr = s["pareado"]["agente"], s["pareado"]["agente_residual"]
    pas, prs = s["pareado"]["agente_sem_registro"], s["pareado"]["agente_residual_sem_registro"]
    psim = s["pareado"]["agente_residual_simulado"]
    L_ = res["leitura"]
    b = L_["barragem"]
    linhas = [
        f"# A/B de centralidade v2 — papel e fala do mundo real ({cfg['data']})", "",
        (f"- Split **{cfg['split']}**, {cfg['n_casos']} casos (todos os do {cfg['split']} com as fotos lidas); leituras REAIS do "
         f"qwen3.5:4b (`{cfg['leituras']}`) e extração de alegações real (`{cfg['narracoes']}`); erro de digitação e "
         "tempo por parâmetros citados (abaixo). Gerado por `scripts/py.sh eval/ab_centralidade_v2/run_ab_v2.py`."),
        ("- Os braços usam as MESMAS ferramentas de conciliação e o MESMO validador determinístico; o "
         "formulário também pede redigitação do que não valida. O oráculo é o papel lido sem erro."),
        ("- **Agente + residual** usa a implementação REAL (`laudo.docs_fiscais.residual` / ferramenta "
         "`completar_leitura_documento`, a mesma do condutor): o sistema pede só os campos críticos que não validaram, "
         "a fiscal lê no papel (voz; CPF/CNPJ digitados) com erro humano por caractere e o sistema revalida (até 3 "
         "tentativas). A última coluna é a simulação da rodada 2 (digitação de todos os campos do formulário que "
         f"ficaram vazios), mantida para registrar a diferença. `sha256(src/)={cfg.get('sha256_src', '')[:16]}…`."),
        "",
        ("| Medida (réplica 0; IC 95% de Wilson) | Formulário (sem LLM) | Agente (só fotos) | "
         "Agente + residual (real) | Agente + residual simulado (rodada 2) |"), "|---|---|---|---|---|",
        lin("Campos do papel corretos ao final", "campos_certos"),
        lin("Campos aceitos com valor ERRADO", "campos_aceitos_errados"),
        lin("Conciliação igual à do oráculo (por caso)", "conteudo_igual_oraculo"),
        lin("Divergências documentais detectadas", "divergencias_detectadas"),
        (f"| Divergências falsas (campos) | {f['falsas_divergencias']} | {ag['falsas_divergencias']} | "
         f"{ar['falsas_divergencias']} | {asim['falsas_divergencias']} |"),
        (f"| Campos pendentes a mais que o oráculo | {f['campos_pendentes_a_mais']} | "
         f"{ag['campos_pendentes_a_mais']} | {ar['campos_pendentes_a_mais']} | {asim['campos_pendentes_a_mais']} |"),
        lin("Alegações da fala com status certo", "alegacoes_corretas"),
        (f"| Alegações espúrias nocivas (viraram divergência/pendência) | {f['alegacoes_nocivas']} | "
         f"{ag['alegacoes_nocivas']} | {ar['alegacoes_nocivas']} | {asim['alegacoes_nocivas']} |"),
        # "completa" = conciliação (NF-e, GTA, alegações da fala) igual à do papel lido sem erro; não é laudo emitível
        # (a foto do DANFE não prova autenticidade: assinatura e protocolo só no XML)
        lin("**Conteúdo conciliado igual à referência (papel e fala)**", "completas"),
        lin("Idem, sem a menção a item não financiado (o formulário não tem campo para ela)", "completas_sem_registro"),
        lin("Tempo da fiscal por fiscalização, mediana (s)", "tempo_fiscal_s_mediana", False),
        lin("Tempo de máquina (VLM/LLM) por fiscalização, mediana (s)", "tempo_maquina_s_mediana", False),
        lin("Interações por fiscalização (campos, fotos, falas)", "interacoes_media", False),
        lin("Toques na tela por fiscalização", "toques_media", False, 0),
        lin("Fotos por fiscalização", "fotos_media", False), "",
        (f"Pareado (completa): agente × formulário — só o agente {pa['so_agente']}, só o formulário "
         f"{pa['so_formulario']}, McNemar exato p = {num(pa['mcnemar_p_exato'], 4)}; agente + residual × "
         f"formulário — {pr['so_agente']} × {pr['so_formulario']}, p = {num(pr['mcnemar_p_exato'], 4)}. Sem as "
         f"menções a item não financiado: agente × formulário {pas['so_agente']} × {pas['so_formulario']} (p = "
         f"{num(pas['mcnemar_p_exato'], 4)}); agente + residual × formulário {prs['so_agente']} × "
         f"{prs['so_formulario']} (p = {num(prs['mcnemar_p_exato'], 4)}). Residual simulado (rodada 2) × "
         f"formulário: {psim['so_agente']} × {psim['so_formulario']} (p = {num(psim['mcnemar_p_exato'], 4)})."), "",
        (f"**Residual real:** {ar['documentos_com_residual']} documento(s) com pedido; completos (todos os críticos "
         f"validados) depois da fala da fiscal: {M.fmt(ar['residual_completo'], True)}; tentativas por documento "
         f"(média): {num(ar['residual_tentativas_media'], 2)}. **Diferença para a simulação da rodada 2:** o pedido "
         "real vem do validador (só campos críticos indeterminados, agrupados: a linha de produtos inteira, a linha "
         "TOTAL da GTA, o município com o código IBGE), a chave de acesso é pedida em grupos de 4 dígitos (os 3 últimos "
         "grupos sempre, porque o VLM erra igual nas leituras; o resto vem dos campos validados), a fiscal fala em vez de "
         "digitar (só CPF/CNPJ e código do estabelecimento são digitados), a resposta é revalidada junto com o que a "
         "foto já validou (a chave tem de fechar com UF, data, série, número e CNPJ) e a tabela de produtos ilegível "
         "não tem residual (só nova foto ou o XML). A simulação digitava todos os campos do formulário que ficaram vazios "
         "e aceitava o que o formulário validava isoladamente."), "",
        f"## Leitura de documento por foto (todas as fotos do {cfg['split']}, 3 níveis de degradação)", "",
        (f"Validação determinística: dos {b.get('n', 0)} campos lidos, a 1ª leitura crua do VLM errou "
         f"{b.get('cru_errado', 0)} (e deixou {b.get('cru_vazio', 0)} vazios). Desses erros, o pipeline (consenso + "
         f"validação) **barrou {b.get('cru_errado_barrado', 0)}**, corrigiu {b.get('cru_errado_corrigido', 0)} "
         f"pelo consenso e **aceitou {b.get('cru_errado_aceito', 0)}** errados. Custo da rigidez: "
         f"{b.get('cru_certo_barrado', 0)} campos que a 1ª leitura acertou ficaram indeterminados. Só com 1 "
         f"leitura + validação (sem autoconsistência): {b.get('k1_validado_errado', 0)} aceitos errados."), "",
    ]
    tot = {k: sum(d[k] for d in L_["por_nivel"].values()) for k in ("n", "certo", "aceito_errado", "barrado")}
    linhas += [(f"No total: {tot['n']} campos; **aceitos e certos {M.fmt(M.proporcao(tot['certo'], tot['n']), True)}**; "
                f"aceitos errados {M.fmt(M.proporcao(tot['aceito_errado'], tot['n']), True)}; barrados "
                f"(indeterminado, pedem nova foto) {M.fmt(M.proporcao(tot['barrado'], tot['n']), True)}. Precisão dos "
                "campos aceitos (certos ÷ aceitos): "
                f"{M.fmt(M.proporcao(tot['certo'], tot['certo'] + tot['aceito_errado']), True)}."), "",
              "| Documento:nível | campos | aceitos e certos | aceitos errados | barrados | precisão dos aceitos |",
              "|---|---|---|---|---|---|"]
    for k, d in L_["por_nivel"].items():
        linhas.append(f"| {k} | {d['n']} | {M.fmt(M.proporcao(d['certo'], d['n']), True)} | {d['aceito_errado']} | "
                      f"{d['barrado']} | {M.fmt(M.proporcao(d['certo'], d['certo'] + d['aceito_errado']), True)} |")
    linhas += ["", "| Documento:nível | n | todos os campos críticos certos | algum campo crítico aceito errado |",
               "|---|---|---|---|"]
    for k, d in L_["documentos"].items():
        linhas.append(f"| {k} | {d['n']} | {M.fmt(M.proporcao(d['todos_criticos_ok'], d['n']), True)} | "
                      f"{M.fmt(M.proporcao(d['algum_aceito_errado'], d['n']), True)} |")
    linhas += ["", "| Campo | n | certo | aceito errado | barrado (indeterminado) |", "|---|---|---|---|---|"]
    for k, d in L_["por_campo"].items():
        linhas.append(f"| {k} | {d['n']} | {M.fmt(M.proporcao(d['certo'], d['n']), True)} | {d['aceito_errado']} | "
                      f"{d['barrado']} |")
    ta = L_["tipo_auto"]
    linhas += ["", (f"Classificação automática DANFE × GTA: {ta.get('certo', 0)}/{ta.get('certo', 0) + ta.get('errado', 0)}."
                    f" Latência da leitura (k = 2 a 3 leituras × 2 recortes): " + "; ".join(
                        f"{t} p50 {num(x['p50'])} s / p95 {num(x['p95'])} s (n = {x['n']})"
                        for t, x in L_["latencia_s"].items())), ""]
    rot_modo = {"llm": "LLM + extrator determinístico, fala normalizada (como na API de voz)",
                "regex": "só o extrator determinístico (condutor sem LLM), fala normalizada",
                "llm_bruto": "LLM + determinístico, texto sem normalizar números",
                "regex_bruto": "só determinístico, texto sem normalizar",
                "llm_bruto_v0": "condutor antes da rodada 2 (número por extenso descartado), sem normalizar"}
    linhas += ["## Fala livre → alegações (isolada, com a evidência verdadeira do caso)", "",
               ("| Extrator | alegações com status certo | divergências/pendências certas | narrações inteiras certas | "
                "espúrias nocivas | latência p50 (s) |"), "|---|---|---|---|---|---|"]
    for modo, d in res["fala"].items():
        linhas.append(f"| {rot_modo.get(modo, modo)} | {M.fmt(d['alegacoes_corretas'], True)} | "
                      f"{M.fmt(d['divergencias_pendencias'], True)} | {M.fmt(d['narracoes_inteiras'], True)} | "
                      f"{d['espurias_nocivas']} | {num(d['latencia_s_p50'])} |")
    linhas += ["", "## Estabilidade e sensibilidade", "",
               f"Média sobre {cfg['param']['replicacoes'] - 1} réplicas (sorteio da qualidade da foto e dos erros de "
               "digitação): " + "; ".join(f"{b_}: completas {num((v['completas'] or 0) * 100)}% (sem registro "
                                          f"{num((v['completas_sem_registro'] or 0) * 100)}%), campos certos "
                                          f"{num((v['campos_certos'] or 0) * 100)}%, tempo {num(v['tempo_fiscal_s_media'])} s"
                                          for b_, v in res["estabilidade_replicacoes"].items()) + ".", "",
               ("| Cenário | Formulário: completas (sem registro) / campos / tempo (s) | Agente | Agente + residual "
                "(real) | Agente + residual simulado |"),
               "|---|---|---|---|---|"]
    for nome, d in res["sensibilidade"].items():
        linhas.append(f"| {nome} | " + " | ".join(
            f"{num((d[b_]['completas'] or 0) * 100)}% ({num((d[b_]['completas_sem_registro'] or 0) * 100)}%) / "
            f"{num((d[b_]['campos_certos'] or 0) * 100)}% / "
            f"{num(d[b_]['tempo_fiscal_s_media'])}" for b_ in BRACOS) + " |")
    so = res["sanidade_oraculo"]
    linhas += ["", (f"Sanidade: o oráculo (papel lido sem erro) reproduz {so['iguais']}/{so['total']} rótulos de "
                    "conteúdo do golden; as diferenças são esperadas (DANFE não prova integridade nem autorização: "
                    "XML adulterado ou com DV errado só aparece no XML) — " + "; ".join(so["diferencas"][:8])), "",
               "## Parâmetros e fontes", ""]
    for k, v in cfg["param"].items():
        linhas.append(f"- `{k}` = {v}")
    linhas.append("")
    for k, v in cfg["fontes"].items():
        linhas.append(f"- [{k}] {v}")
    return "\n".join(linhas) + "\n"


if __name__ == "__main__":
    sys.exit(main())
