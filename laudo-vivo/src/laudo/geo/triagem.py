"""Regras de triagem da carteira: prioridade de verificação com motivos legíveis.

Nada aqui rotula operação como "suspeita" ou "fraude". Cada sinal só aumenta a prioridade de
verificação (Res. CMN 5.267/2025, MCR 2-7: a IF escolhe a amostra e o método; item 12 admite
amostragem estatística) e vem com um motivo em texto, para que o fiscal saiba o que olhar.

Os limiares são parâmetros de triagem, não normas: ficam em `LIMIARES` e vão para o data card.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

LIMIARES: dict[str, float] = {
    # lotação implícita (quantidade financiada / área do empreendimento informada), cab ou UA por ha
    "lot_inv_1": 2.0,  # compra de matrizes/reprodutores para povoamento (pasto)
    "lot_inv_2": 3.0,
    "lot_inv_3": 5.0,
    "lot_cust_1": 3.0,  # custeio de aquisição e manutenção (recria/engorda; pode ser semiconfinado)
    "lot_cust_2": 5.0,
    "lot_vs_densidade": 4.0,  # menção no motivo quando a lotação passa de N vezes a densidade municipal
    # sobreposição de glebas entre operações diferentes da mesma safra
    "sobrep_frac_alta": 0.5,
    "sobrep_frac_baixa": 0.1,
    "sobrep_min_ha": 0.5,
    # área dos polígonos vs área informada
    "area_razao_max": 2.0,
    "area_razao_min": 0.5,
    # fração do rebanho municipal (IBGE) financiada numa única operação
    "frac_rebanho_mun": 0.05,
    # sensoriamento remoto obrigatório (MCR 2-7 item 5, Res. 5.267): área total > 300 ha
    "sr_area_ha": 300.0,
}

DATA_INICIO_5267 = date(2026, 3, 1)

NIVEIS = [(4, "alta"), (2, "media"), (1, "baixa"), (0, "sem_sinal")]


def ano_agricola(d: date | datetime | None) -> str | None:
    """Ano agrícola (julho a junho) da data de emissão: 05/2026 -> '2025/26', 08/2026 -> '2026/27'."""
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return None
    try:
        y, m = d.year, d.month
    except AttributeError:
        return None
    ini = y if m >= 7 else y - 1
    return f"{ini}/{(ini + 1) % 100:02d}"


def nivel(pontos: int) -> str:
    for minimo, nome in NIVEIS:
        if pontos >= minimo:
            return nome
    return "sem_sinal"


def _num(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def fmt(x: float | None, casas: int = 1) -> str:
    if x is None:
        return "n/d"
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Resultado:
    pontos: int = 0
    motivos: list[str] = field(default_factory=list)
    codigos: list[str] = field(default_factory=list)
    observacoes: list[str] = field(default_factory=list)

    def soma(self, pontos: int, codigo: str, texto: str) -> None:
        self.pontos += pontos
        self.codigos.append(codigo)
        self.motivos.append(f"{texto} (+{pontos})")


def classe_lotacao(lot: float | None, compra: str | None) -> tuple[int, str | None]:
    """Pontos e rótulo da lotação implícita conforme o tipo de compra de gado."""
    if lot is None:
        return 0, None
    L = LIMIARES
    if compra == "investimento":
        if lot > L["lot_inv_3"]:
            return 3, f"acima de {fmt(L['lot_inv_3'], 0)}"
        if lot > L["lot_inv_2"]:
            return 2, f"acima de {fmt(L['lot_inv_2'], 0)}"
        if lot > L["lot_inv_1"]:
            return 1, f"acima de {fmt(L['lot_inv_1'], 0)}"
        return 0, None
    if compra == "custeio":
        if lot > L["lot_cust_2"]:
            return 2, f"acima de {fmt(L['lot_cust_2'], 0)}"
        if lot > L["lot_cust_1"]:
            return 1, f"acima de {fmt(L['lot_cust_1'], 0)}"
    return 0, None


def pontuar(op: dict[str, Any]) -> Resultado:
    """Calcula prioridade e motivos de uma operação (dicionário com as colunas do bench)."""
    r = Resultado()
    L = LIMIARES
    compra = op.get("compra_gado_tipo")
    compra = compra if isinstance(compra, str) and compra else None
    unid = op.get("unidade_qtd_bovinos")
    unid = unid if isinstance(unid, str) and unid else "cab"
    lot = _num(op.get("lotacao_implicita_cab_ha"))
    confinamento = bool(op.get("confinamento"))

    # 1) lotação implícita
    if compra and lot is not None and not confinamento:
        p, rot = classe_lotacao(lot, compra)
        if p:
            dens = _num(op.get("densidade_bovina_mun_cab_ha"))
            extra = ""
            if dens and dens > 0 and lot / dens >= L["lot_vs_densidade"]:
                extra = (f"; {fmt(lot / dens, 0)} vezes a densidade bovina do município "
                         f"({fmt(dens, 2)} cab/ha, IBGE PPM)")
            tipo = "compra de matrizes/reprodutores" if compra == "investimento" else "aquisição para recria/engorda"
            r.soma(p, "LOTACAO_ALTA",
                   f"lotação implícita de {fmt(lot, 1)} {unid}/ha na {tipo} ({rot}){extra}")
    elif compra and confinamento:
        r.observacoes.append("engorda em confinamento: lotação por área não se aplica")
    elif compra and lot is None:
        r.observacoes.append("sem área informada: lotação implícita indeterminada")

    # 2) sobreposição de glebas com outra operação da mesma safra
    frac = _num(op.get("sobreposicao_max_frac"))
    n_sob = int(op.get("n_ops_sobrepostas") or 0)
    if n_sob and frac is not None:
        p = 2 if frac >= L["sobrep_frac_alta"] else (1 if frac >= L["sobrep_frac_baixa"] else 0)
        if p:
            outra_if = bool(op.get("sobrepoe_outra_if"))
            if outra_if:
                p += 1
            ha = _num(op.get("sobreposicao_ha"))
            r.soma(p, "SOBREPOSICAO_GLEBAS",
                   f"gleba sobreposta em {fmt(100 * frac, 0)}% ({fmt(ha, 1)} ha) com {n_sob} outra(s) "
                   f"operação(ões) da mesma safra" + ("; inclui operação de outra IF" if outra_if else ""))

    # 3) área dos polígonos muito diferente da área informada
    ag, ai = _num(op.get("area_glebas_ha")), _num(op.get("area_informada_ha"))
    if ag and ai and ag > 0 and ai > 0:
        razao = ag / ai
        if razao > L["area_razao_max"] or razao < L["area_razao_min"]:
            r.soma(1, "AREA_DIVERGENTE",
                   f"área dos polígonos ({fmt(ag, 1)} ha) difere da área informada ({fmt(ai, 1)} ha)")

    # 4) valor por cabeça fora da faixa da carteira (mesma modalidade e unidade)
    if op.get("valor_cabeca_fora_faixa"):
        vpc = _num(op.get("valor_por_cabeca_rs"))
        r.soma(1, "VALOR_CABECA_ATIPICO",
               f"valor financiado por {unid} (R$ {fmt(vpc, 0)}) fora da faixa p1–p99 das operações "
               f"semelhantes ({op.get('faixa_valor_cabeca') or 'n/d'})")

    # 5) fração relevante do rebanho municipal
    fr = _num(op.get("frac_rebanho_mun"))
    if compra and fr is not None and fr >= L["frac_rebanho_mun"]:
        r.soma(1, "FRACAO_REBANHO_MUNICIPAL",
               f"quantidade financiada equivale a {fmt(100 * fr, 1)}% do rebanho bovino do município "
               f"(IBGE PPM)")

    # observações de método (não pontuam)
    if op.get("exige_sensoriamento_remoto"):
        r.observacoes.append("área acima de 300 ha em operação contratada a partir de 01/03/2026: "
                             "sensoriamento remoto obrigatório (MCR 2-7 item 5, Res. CMN 5.267)")
    if compra and not op.get("tem_poligono"):
        r.observacoes.append("sem polígono público: verificação remota indisponível (método documental "
                             "ou presencial)")
    return r
