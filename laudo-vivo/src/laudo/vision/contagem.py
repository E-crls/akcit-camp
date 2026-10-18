"""Contagem de bovinos a partir das trilhas, com intervalo de incerteza e abstenção.

Antes de contar, as trilhas são **costuradas em cadeias**: se uma trilha some e outra nasce pouco
depois perto de onde a primeira estaria (posição extrapolada pela velocidade), as duas viram uma
cadeia (o mesmo animal após oclusão ou falha do detector). Cada costura é uma fonte de incerteza.

Dois modos:

- ``linha`` (recomendado: corredor/brete). Conta cadeias cujo centro passa de um lado ao outro de
  uma linha (com histerese), em termos líquidos (ida e volta não conta). Intervalo: o limite inferior
  descarta cruzamentos fracos (a troca de lado aconteceu numa costura, poucas observações de um dos
  lados ou score baixo); o superior soma cadeias interrompidas perto da linha sem cruzar.
- ``ids_unicos`` (lote parado, câmera parada ou quase). Conta cadeias com duração mínima. Intervalo:
  o inferior desconta pares de cadeias que ainda parecem o mesmo animal (critério mais frouxo) e
  nunca fica abaixo do máximo de animais simultâneos num quadro; o superior soma as costuras feitas
  (se alguma estiver errada, havia mais animais) e as cadeias curtas e confiantes.

O intervalo é uma faixa de plausibilidade por contagem de eventos duvidosos, não um intervalo de
confiança estatístico. Os limiares são iniciais e devem ser calibrados no conjunto de dev.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from laudo.vision.rastreador import Observacao, Trilha

Modo = Literal["linha", "ids_unicos"]
Sentido = Literal["auto", "a_para_b", "b_para_a"]


@dataclass
class ParametrosContagem:
    modo: Modo = "linha"
    linha: tuple[float, float, float, float] | None = None  # x1, y1, x2, y2 normalizados; None = auto
    sentido: Sentido = "auto"
    banda_rel: float = 0.02  # histerese: fração da diagonal do quadro
    zona_interrupcao_rel: float = 0.15  # distância à linha (fração da diagonal) que conta como "perto"
    min_obs_por_lado: int = 2
    min_score_cruzamento: float = 0.45
    min_duracao_s: float = 1.0
    max_gap_costura_s: float = 2.0  # costura de trilhas (mesmo animal)
    max_dist_costura: float = 1.5  # em diagonais da caixa, após extrapolar pela velocidade
    max_gap_fragmento_s: float = 4.0  # critério mais frouxo, só para o limite inferior
    max_dist_fragmento: float = 2.5
    limiar_conf_media: float = 0.5
    min_cobertura: float = 0.6
    max_meia_largura_rel: float = 0.25
    max_frac_quadros_ruins: float = 0.5
    max_oclusao: float = 0.7  # fração de detecções com ≥ 25% da caixa coberta por outra
    fator_oclusao_teto: float = 0.5  # teto += ⌈contagem × oclusão × fator⌉ (animais escondidos)
    # movimento de câmera (fração da largura do quadro / log da escala), acumulado no vídeo
    max_translacao_camera: float = 0.35
    max_zoom_camera: float = 0.08
    max_caminho_camera: float = 3.0


@dataclass
class Motivo:
    codigo: str
    msg: str
    abstem: bool = False

    def como_dict(self) -> dict:
        # mesmo formato de motivo das outras ferramentas de visão (codigo, severidade, msg)
        return {"codigo": self.codigo, "severidade": "indeterminado" if self.abstem else "info",
                "msg": self.msg, "abstem": self.abstem}


@dataclass
class ResultadoContagem:
    modo: Modo
    contagem: int
    intervalo: tuple[int, int]
    eventos: list[dict] = field(default_factory=list)  # cruzamentos ou cadeias contadas
    ids_contados: list[int] = field(default_factory=list)  # ids das cadeias contadas
    detalhes: dict = field(default_factory=dict)
    motivos: list[Motivo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cadeias (trilhas costuradas)
# ---------------------------------------------------------------------------


class Cadeia:
    """Uma ou mais trilhas consecutivas que, presumivelmente, são o mesmo animal."""

    def __init__(self, trilhas: list[Trilha]):
        self.trilhas = trilhas
        self.obs: list[Observacao] = [o for t in trilhas for o in t.obs]
        self._dono = [t.id for t in trilhas for _ in t.obs]

    @property
    def id(self) -> int:
        return self.trilhas[0].id

    @property
    def ids(self) -> list[int]:
        return [t.id for t in self.trilhas]

    @property
    def inicio(self) -> int:
        return self.obs[0].quadro

    @property
    def fim(self) -> int:
        return self.obs[-1].quadro

    @property
    def n_costuras(self) -> int:
        return len(self.trilhas) - 1

    @property
    def vel(self) -> np.ndarray:
        return self.trilhas[-1].vel

    @property
    def score_medio(self) -> float:
        return float(np.mean([o.score for o in self.obs]))

    @property
    def continuidade(self) -> float:
        return len(self.obs) / (self.fim - self.inicio + 1)

    def centro(self, i: int = -1) -> tuple[float, float]:
        x1, y1, x2, y2 = self.obs[i].caixa
        return (x1 + x2) / 2, (y1 + y2) / 2

    def dono(self, i: int) -> int:
        """Id da trilha a que pertence a i-ésima observação."""
        return self._dono[i]


def _dist_extrapolada(a, b) -> float:
    """Distância (em diagonais da caixa de A) entre o início de B e a posição de A extrapolada até lá."""
    gap = b.inicio - a.fim
    vx = (a.vel[0] + a.vel[2]) / 2
    vy = (a.vel[1] + a.vel[3]) / 2
    xa, ya = a.centro(-1)
    xb, yb = b.centro(0)
    x1, y1, x2, y2 = a.obs[-1].caixa
    diag = max(math.hypot(x2 - x1, y2 - y1), 1.0)
    return math.hypot(xb - (xa + vx * gap), yb - (ya + vy * gap)) / diag


def _area(o: Observacao) -> float:
    x1, y1, x2, y2 = o.caixa
    return max((x2 - x1) * (y2 - y1), 1.0)


def _pares_compativeis(itens: list, gap_max: int, dist_max: float) -> list[tuple[int, int]]:
    """Pareamento guloso A→B (B começa depois de A acabar, perto da posição extrapolada de A)."""
    cand: list[tuple[float, int, int]] = []
    for i, a in enumerate(itens):
        for j, b in enumerate(itens):
            if i == j:
                continue
            gap = b.inicio - a.fim
            if gap <= 0 or gap > gap_max:
                continue
            razao = _area(b.obs[0]) / _area(a.obs[-1])
            if not (1 / 3 <= razao <= 3):
                continue
            d = _dist_extrapolada(a, b)
            if d <= dist_max:
                cand.append((d + 0.05 * gap, i, j))
    usados_a, usados_b, out = set(), set(), []
    for _, i, j in sorted(cand):
        if i in usados_a or j in usados_b:
            continue
        usados_a.add(i)
        usados_b.add(j)
        out.append((i, j))
    return out


def costurar(trilhas: list[Trilha], gap_max: int, dist_max: float = 1.5) -> list[Cadeia]:
    """Junta trilhas fragmentadas do mesmo animal em cadeias."""
    trilhas = sorted(trilhas, key=lambda t: t.inicio)
    pares = _pares_compativeis(trilhas, gap_max, dist_max)
    prox = dict(pares)
    tem_pred = {j for _, j in pares}
    cadeias = []
    for i in range(len(trilhas)):
        if i in tem_pred:
            continue
        seq = [trilhas[i]]
        k = i
        while k in prox:
            k = prox[k]
            seq.append(trilhas[k])
        cadeias.append(Cadeia(seq))
    return sorted(cadeias, key=lambda c: c.id)


# ---------------------------------------------------------------------------
# Geometria da linha
# ---------------------------------------------------------------------------


def distancia_assinada(px: float, py: float, linha: tuple[float, float, float, float]) -> float:
    """Distância (px) do ponto à reta orientada p1→p2; positivo = lado B, negativo = lado A.

    Em coordenadas de imagem: linha de cima para baixo → B à direita; linha da direita para a
    esquerda → B embaixo. "a_para_b" é, portanto, esquerda→direita ou cima→baixo nesses casos.
    """
    x1, y1, x2, y2 = linha
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1.0
    return (dy * (px - x1) - dx * (py - y1)) / n


def linha_automatica(cadeias: list, largura: int, altura: int,
                     min_desloc_rel: float = 0.1) -> tuple[tuple[float, float, float, float], str, bool]:
    """Escolhe uma linha perpendicular ao movimento dominante, passando pelo centro do quadro.

    Devolve (linha em px, eixo do movimento "horizontal"/"vertical", houve_movimento).
    """
    dx_tot = dy_tot = 0.0
    houve = False
    for t in cadeias:
        (x0, y0), (x1, y1) = t.centro(0), t.centro(-1)
        if math.hypot((x1 - x0) / largura, (y1 - y0) / altura) >= min_desloc_rel:
            dx_tot += abs(x1 - x0) / largura
            dy_tot += abs(y1 - y0) / altura
            houve = True
    if dx_tot >= dy_tot:  # movimento horizontal → linha vertical no meio (B à direita)
        return (largura / 2, 0.0, largura / 2, float(altura)), "horizontal", houve
    return (float(largura), altura / 2, 0.0, altura / 2), "vertical", houve  # B embaixo


# ---------------------------------------------------------------------------
# Modo linha
# ---------------------------------------------------------------------------


def contar_linha(cadeias: list[Cadeia], linha: tuple[float, float, float, float], largura: int,
                 altura: int, ultimo_quadro: int, max_idade: int, p: ParametrosContagem) -> ResultadoContagem:
    diag = math.hypot(largura, altura)
    banda = p.banda_rel * diag
    zona = p.zona_interrupcao_rel * diag

    cruzamentos: list[dict] = []
    terminadas = nascidas = 0
    for c in cadeias:
        dists = [distancia_assinada((o.caixa[0] + o.caixa[2]) / 2, (o.caixa[1] + o.caixa[3]) / 2, linha)
                 for o in c.obs]
        definidos = [(i, 1 if d > 0 else -1) for i, d in enumerate(dists) if abs(d) >= banda]
        if definidos and definidos[0][1] != definidos[-1][1]:
            s_ini, s_fim = definidos[0][1], definidos[-1][1]
            k_ult_ini = max(k for k, (_, s) in enumerate(definidos) if s == s_ini)
            i_antes, i_depois = definidos[k_ult_ini][0], definidos[k_ult_ini + 1][0]
            n_ini = sum(1 for _, s in definidos if s == s_ini)
            n_fim = sum(1 for _, s in definidos if s == s_fim)
            na_costura = c.dono(i_antes) != c.dono(i_depois)
            fraco = (na_costura or min(n_ini, n_fim) < p.min_obs_por_lado
                     or c.score_medio < p.min_score_cruzamento)
            cruzamentos.append({"cadeia": c.id, "trilhas": c.ids, "quadro": c.obs[i_depois].quadro,
                                "sentido": "a_para_b" if s_fim > 0 else "b_para_a", "fraco": fraco,
                                "na_costura": na_costura, "score_medio": round(c.score_medio, 3)})
            continue
        if abs(dists[-1]) <= zona and c.fim < ultimo_quadro - max_idade:
            terminadas += 1  # sumiu perto da linha sem cruzar (oclusão?)
        if abs(dists[0]) <= zona and c.inicio > max_idade:
            nascidas += 1  # apareceu perto da linha já no meio do vídeo

    n_ab = sum(1 for c in cruzamentos if c["sentido"] == "a_para_b")
    n_ba = sum(1 for c in cruzamentos if c["sentido"] == "b_para_a")
    sentido = p.sentido
    if sentido == "auto":
        sentido = "a_para_b" if n_ab >= n_ba else "b_para_a"
    contra = "b_para_a" if sentido == "a_para_b" else "a_para_b"
    favor = [c for c in cruzamentos if c["sentido"] == sentido]
    contra_l = [c for c in cruzamentos if c["sentido"] == contra]
    contagem = max(0, len(favor) - len(contra_l))
    fracos_favor = sum(1 for c in favor if c["fraco"])
    fracos_contra = sum(1 for c in contra_l if c["fraco"])
    lo = max(0, contagem - fracos_favor)
    hi = contagem + fracos_contra + max(terminadas, nascidas)

    eventos = sorted(cruzamentos, key=lambda c: c["quadro"])
    acumulado = 0
    for c in eventos:
        acumulado += 1 if c["sentido"] == sentido else -1
        c["acumulado"] = acumulado
    return ResultadoContagem(
        modo="linha", contagem=contagem, intervalo=(lo, max(hi, contagem)), eventos=eventos,
        ids_contados=sorted(c["cadeia"] for c in favor),
        detalhes={"sentido": sentido, "cruzamentos_a_para_b": n_ab, "cruzamentos_b_para_a": n_ba,
                  "cruzamentos_fracos": fracos_favor + fracos_contra,
                  "cruzamentos_na_costura": sum(1 for c in cruzamentos if c["na_costura"]),
                  "interrompidas_perto_da_linha": terminadas + nascidas,
                  "n_cadeias": len(cadeias), "n_costuras": sum(c.n_costuras for c in cadeias),
                  "linha_px": [round(v, 1) for v in linha]})


# ---------------------------------------------------------------------------
# Modo IDs únicos
# ---------------------------------------------------------------------------


def contar_ids(cadeias: list[Cadeia], fps_proc: float, p: ParametrosContagem) -> ResultadoContagem:
    min_q = max(1, round(p.min_duracao_s * fps_proc))
    longas = [c for c in cadeias if (c.fim - c.inicio + 1) >= min_q]
    curtas = [c for c in cadeias if (c.fim - c.inicio + 1) < min_q and c.score_medio >= p.limiar_conf_media]
    frag = _pares_compativeis(longas, round(p.max_gap_fragmento_s * fps_proc), p.max_dist_fragmento)
    por_quadro: dict[int, int] = {}
    for c in longas:
        for o in c.obs:
            por_quadro[o.quadro] = por_quadro.get(o.quadro, 0) + 1
    max_sim = max(por_quadro.values(), default=0)
    contagem = len(longas)
    n_cost = sum(c.n_costuras for c in longas)
    lo = max(max_sim, contagem - len(frag))
    hi = contagem + n_cost + len(curtas)
    eventos = [{"cadeia": c.id, "trilhas": c.ids, "quadro": c.inicio, "fim": c.fim,
                "score_medio": round(c.score_medio, 3)} for c in longas]
    return ResultadoContagem(
        modo="ids_unicos", contagem=contagem, intervalo=(min(lo, contagem), hi), eventos=eventos,
        ids_contados=[c.id for c in longas],
        detalhes={"max_simultaneo": max_sim, "possiveis_fragmentos": len(frag), "n_costuras": n_cost,
                  "cadeias_curtas": len(curtas), "min_quadros": min_q, "n_cadeias": len(cadeias)})


# ---------------------------------------------------------------------------
# Confiabilidade e abstenção
# ---------------------------------------------------------------------------


def alargar_por_oclusao(res: ResultadoContagem, oclusao: float, p: ParametrosContagem) -> None:
    """Sobe o teto do intervalo pela taxa de oclusão: animal escondido atrás de outro some (nunca sobra).

    Fator 0,5 escolhido nos vídeos semissintéticos de corredor; recalibrar com vídeo real.
    """
    if res.contagem <= 0 or oclusao <= 0:
        return
    extra = math.ceil(res.contagem * oclusao * p.fator_oclusao_teto)
    res.intervalo = (res.intervalo[0], res.intervalo[1] + extra)
    res.detalhes["acrescimo_teto_oclusao"] = extra


def avaliar(res: ResultadoContagem, cadeias: list[Cadeia], p: ParametrosContagem, *,
            frac_quadros_ruins: float, oclusao: float, frac_outra_classe: float, truncado: bool,
            houve_movimento: bool | None, duracao_s: float,
            camera: dict | None = None) -> tuple[str, bool, float, float]:
    """Preenche `res.motivos` e devolve (status, abstencao, conf_media, cobertura)."""
    ids = set(res.ids_contados)
    contadas = [c for c in cadeias if c.id in ids]
    conf_media = float(np.mean([c.score_medio for c in contadas])) if contadas else 0.0
    cobertura = float(np.mean([c.continuidade for c in contadas])) if contadas else 0.0
    m = res.motivos

    if duracao_s < 1.0:
        m.append(Motivo("VIDEO_CURTO", f"vídeo processado com {duracao_s:.1f} s; mínimo 1 s", True))
    if truncado:
        m.append(Motivo("TRUNCADO", "vídeo maior que o limite de processamento; contagem parcial", True))
    if frac_quadros_ruins > p.max_frac_quadros_ruins:
        m.append(Motivo("VIDEO_RUIM", f"{frac_quadros_ruins:.0%} dos quadros escuros ou borrados", True))
    if camera and camera.get("confiavel", True):
        tr, zm, cam = camera["translacao_liquida"], camera["zoom_liquido"], camera["caminho"]
        if tr > p.max_translacao_camera or abs(zm) > p.max_zoom_camera or cam > p.max_caminho_camera:
            m.append(Motivo("CAMERA_EM_MOVIMENTO", f"câmera se moveu (translação {tr:.2f} quadro, zoom "
                            f"{zm:+.2f}, caminho {cam:.1f}); animais saem e voltam ao quadro", True))
    if res.contagem == 0 and not cadeias:
        m.append(Motivo("SEM_BOVINOS", "nenhum bovino detectado com confiança; filme mais perto e com luz",
                        True))
    elif res.contagem == 0 and res.modo == "linha":
        msg = "animais detectados, mas nenhum cruzou a linha"
        if houve_movimento is False:
            msg += "; lote parece parado: use o modo ids_unicos ou filme o lote passando no corredor"
        m.append(Motivo("SEM_CRUZAMENTO", msg, True))
    if contadas and conf_media < p.limiar_conf_media:
        m.append(Motivo("CONF_BAIXA", f"confiança média {conf_media:.2f} < {p.limiar_conf_media}", True))
    if contadas and cobertura < p.min_cobertura:
        m.append(Motivo("COBERTURA_BAIXA", f"cadeias observadas em {cobertura:.0%} dos quadros "
                        f"(mín. {p.min_cobertura:.0%}): oclusão ou detector instável", True))
    lo, hi = res.intervalo
    meia = (hi - lo) / 2
    if res.contagem > 0 and meia > max(1.0, p.max_meia_largura_rel * res.contagem):
        m.append(Motivo("INTERVALO_LARGO", f"intervalo [{lo}, {hi}] largo demais para {res.contagem} "
                        f"(meia-largura {meia:.1f} > {p.max_meia_largura_rel:.0%})", True))
    if oclusao > p.max_oclusao:
        m.append(Motivo("OCLUSAO_ALTA", f"{oclusao:.0%} das detecções com ≥ 25% da caixa coberta por outra", True))
    elif oclusao > p.max_oclusao / 2:
        m.append(Motivo("OCLUSAO", f"{oclusao:.0%} das detecções com ≥ 25% da caixa coberta por outra; risco de subcontagem (teto já alargado)"))
    if frac_outra_classe > 0.5:
        m.append(Motivo("CLASSE_CONFUSA", f"{frac_outra_classe:.0%} das detecções rotuladas como outra "
                        "classe pelo modelo COCO (ex.: ovelha); conferir quadros-chave"))
    abstencao = any(x.abstem for x in m)
    return ("indeterminado" if abstencao else "ok"), abstencao, conf_media, cobertura
