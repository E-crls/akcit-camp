"""Ferramentas falsas (fixtures) para testes, bake-off e demo sem as ferramentas reais.

Respeitam o contrato (entrada Pydantic, retorno `Envelope`), mas os resultados vêm de um *cenário*:
um dicionário `nome_do_arquivo -> resultado`. Tudo sai marcado com `fake=True` e
`fonte_versao="fake@0.1.0"`, e as regras
citadas são `FAKE/MCR-2-7` (não inventamos número de item da norma).

Nunca são registradas no `REGISTRO` global: `registro_com_falsas()` devolve um dicionário novo, com as reais
que existirem e as falsas só para os nomes que faltarem.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from laudo.agent.verificador import requisitos_provisorios
from laudo.contracts import CodigoErro, Envelope, Ferramenta, ItemFinanciado

FONTE = "fake@0.1.0"
REGRA = "FAKE/MCR-2-7"


class EntradaPlanejar(BaseModel):
    operacao: dict[str, Any] = Field(default_factory=dict, description="operação (preenchida pelo agente)")


class EntradaVideo(BaseModel):
    caminho: str = Field(description="arquivo de vídeo")
    item_id: str | None = None
    lote: str | None = None


class EntradaArquivo(BaseModel):
    caminho: str = Field(description="arquivo da evidência")
    item_id: str | None = None


class EntradaGeofence(BaseModel):
    lat: float
    lon: float
    precisao_m: float | None = None
    gleba_wkt: str
    item_id: str | None = None


class EntradaNdvi(BaseModel):
    gleba_wkt: str
    inicio: str | None = None
    fim: str | None = None


def _nome(caminho: str) -> str:
    return Path(caminho).name


def _pontos_wkt(wkt: str) -> list[tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", wkt)]
    return list(zip(nums[0::2], nums[1::2]))


def _dentro(lon: float, lat: float, poly: list[tuple[float, float]]) -> bool:
    dentro = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            dentro = not dentro
        j = i
    return dentro


def _dist_borda_m(lon: float, lat: float, poly: list[tuple[float, float]]) -> float:
    kx = 111320 * math.cos(math.radians(lat))
    ky = 110540
    melhor = float("inf")
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        ax, ay, bx, by = (x1 - lon) * kx, (y1 - lat) * ky, (x2 - lon) * kx, (y2 - lat) * ky
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1e-12)))
        melhor = min(melhor, math.hypot(ax + t * dx, ay + t * dy))
    return melhor


def criar_ferramentas_falsas(cenario: dict[str, dict[str, Any]] | None = None) -> dict[str, Ferramenta]:
    cen = cenario or {}

    def do_cenario(nome_ferr: str, caminho: str, padrao: dict[str, Any] | None) -> Envelope:
        t0 = time.perf_counter()
        r = cen.get(_nome(caminho), {}).get(nome_ferr, padrao)
        if r is None:
            return Envelope.falha(
                nome_ferr, CodigoErro.SEM_DADOS, f"cenário sem resultado para {_nome(caminho)}", t0=t0
            )
        if r.get("_erro"):
            return Envelope.falha(
                nome_ferr,
                CodigoErro(r["_erro"]),
                r.get("msg", "erro simulado"),
                retryable=bool(r.get("retryable")),
                t0=t0,
            )
        return Envelope.sucesso(nome_ferr, {**r, "fake": True}, fonte_versao=FONTE, t0=t0)

    def planejar_metodo(a: EntradaPlanejar) -> Envelope:
        t0 = time.perf_counter()
        itens = [ItemFinanciado.model_validate(i) for i in a.operacao.get("itens", [])]
        if not itens:
            return Envelope.falha(
                "planejar_metodo", CodigoErro.SEM_DADOS, "operação sem itens financiados", t0=t0
            )
        reqs = requisitos_provisorios(itens)
        for r in reqs:
            r["regra_id"] = REGRA
        tem_bov = any(i.tipo == "bovinos" for i in itens)
        return Envelope.sucesso(
            "planejar_metodo",
            {
                "status": "ok",
                "metodo": "presencial" if tem_bov else "documental",
                "justificativa": "FAKE: bovinos exigem contagem presencial por vídeo; benfeitoria com foto "
                "georreferenciada; documentos fiscais conciliados com o projeto.",
                "requisitos": reqs,
                "regra_id": REGRA,
                "fake": True,
            },
            fonte_versao=FONTE,
            t0=t0,
        )

    def contar_bovinos_video(a: EntradaVideo) -> Envelope:
        env = do_cenario("contar_bovinos_video", a.caminho, None)
        if env.ok and env.data is not None:
            env.data.setdefault("lote", a.lote)
            env.data.setdefault("item_id", a.item_id)
        return env

    def integridade_foto(a: EntradaArquivo) -> Envelope:
        return do_cenario(
            "integridade_foto",
            a.caminho,
            {"status": "ok", "exif": True, "gps_exif": True, "duplicata_de": [], "score_tela": 0.02},
        )

    def conciliar_nfe(a: EntradaArquivo) -> Envelope:
        return do_cenario("conciliar_nfe", a.caminho, None)

    def conciliar_gta(a: EntradaArquivo) -> Envelope:
        return do_cenario("conciliar_gta", a.caminho, None)

    def geofence(a: EntradaGeofence) -> Envelope:
        t0 = time.perf_counter()
        poly = _pontos_wkt(a.gleba_wkt)
        if len(poly) < 3:
            return Envelope.falha("geofence", CodigoErro.ENTRADA_INVALIDA, "polígono inválido", t0=t0)
        dist = _dist_borda_m(a.lon, a.lat, poly)
        dentro = _dentro(a.lon, a.lat, poly)
        prec = a.precisao_m or 0.0
        status = "indeterminado" if prec > 30 or dist < prec else ("dentro" if dentro else "fora")
        return Envelope.sucesso(
            "geofence",
            {
                "status": status,
                "distancia_borda_m": round(dist, 1),
                "precisao_m": a.precisao_m,
                "item_id": a.item_id,
                "fake": True,
            },
            fonte_versao=FONTE,
            t0=t0,
        )

    def serie_ndvi(a: EntradaNdvi) -> Envelope:
        t0 = time.perf_counter()
        return Envelope.sucesso(
            "serie_ndvi",
            {
                "status": "ok",
                "sensor": "Sentinel-2 MSI L2A (FAKE)",
                "datas": ["2026-09-21", "2026-09-26"],
                "resolucao_m": 10,
                "bandas": ["B04", "B08", "SCL"],
                "metodologia": "FAKE: NDVI mediano da gleba com máscara SCL",
                "fake": True,
            },
            fonte_versao=FONTE,
            t0=t0,
        )

    defs = [
        (
            "planejar_metodo",
            "Escolhe o método de fiscalização e lista os requisitos de evidência por item.",
            EntradaPlanejar,
            planejar_metodo,
        ),
        (
            "contar_bovinos_video",
            "Conta bovinos num vídeo do lote passando pelo corredor (com intervalo).",
            EntradaVideo,
            contar_bovinos_video,
        ),
        (
            "integridade_foto",
            "Confere EXIF, GPS, horário, duplicata e foto de tela de uma foto.",
            EntradaArquivo,
            integridade_foto,
        ),
        (
            "geofence",
            "Diz se o ponto da foto está dentro, fora ou indeterminado em relação à gleba.",
            EntradaGeofence,
            geofence,
        ),
        (
            "conciliar_nfe",
            "Lê a NF-e (XML) e confere emitente, NCM, quantidade, data e valor contra o item.",
            EntradaArquivo,
            conciliar_nfe,
        ),
        (
            "conciliar_gta",
            "Confere a GTA (espécie, quantidade, origem/destino, data) contra NF-e e item.",
            EntradaArquivo,
            conciliar_gta,
        ),
        ("serie_ndvi", "Série NDVI Sentinel-2 da gleba (com metadados do sensor).", EntradaNdvi, serie_ndvi),
    ]
    return {
        n: Ferramenta(nome=n, descricao=f"[FAKE] {d}", entrada=e, funcao=f, timeout_s=5.0)
        for n, d, e, f in defs
    }


GLEBA_EXEMPLO = (
    "POLYGON((-49.300 -16.800, -49.290 -16.800, -49.290 -16.790, -49.300 -16.790, -49.300 -16.800))"
)
GPS_DENTRO = {"lat": -16.7952, "lon": -49.2951, "precisao_m": 6.0, "fonte": "app"}
GPS_FORA = {"lat": -16.7700, "lon": -49.2600, "precisao_m": 5.0, "fonte": "app"}


def operacao_exemplo(ref: str = "SINT-2026-0001"):
    """Operação sintética de investimento pecuário (40 garrotes + 800 m de cerca) para testes e demo."""
    from datetime import date

    from laudo.contracts import Operacao

    return Operacao(
        ref_bacen=ref,
        tomador_ref="tomador-sintetico-01",
        uf="GO",
        municipio_ibge="5208707",
        municipio_nome="Goiânia",
        instituicao="Cooperativa de crédito (sintética)",
        finalidade="investimento",
        empreendimento="bovinocultura de corte",
        data_contratacao=date(2026, 7, 15),
        valor_rs=160000.0,
        area_financiada_ha=120.0,
        glebas_wkt=[GLEBA_EXEMPLO],
        fonte="sintetico",
        itens=[
            ItemFinanciado(
                id="bov1",
                tipo="bovinos",
                descricao="Garrotes nelore para recria",
                quantidade=40,
                unidade="cabeca",
                valor_rs=112000.0,
                categoria_animal="garrote",
            ),
            ItemFinanciado(
                id="cerca1",
                tipo="cerca",
                descricao="Cerca de arame liso, 5 fios",
                quantidade=800,
                unidade="m",
                valor_rs=48000.0,
            ),
        ],
    )


def registro_com_falsas(
    cenario: dict[str, dict[str, Any]] | None = None, base: dict[str, Ferramenta] | None = None
) -> tuple[dict[str, Ferramenta], list[str]]:
    """Registro com as ferramentas reais de `base` e as falsas só onde faltar.
    Devolve (registro, nomes_falsos)."""
    reg = dict(base or {})
    falsas = []
    for nome, f in criar_ferramentas_falsas(cenario).items():
        if nome not in reg:
            reg[nome] = f
            falsas.append(nome)
    return reg, falsas
