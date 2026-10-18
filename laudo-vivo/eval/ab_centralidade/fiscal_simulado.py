"""Fiscal roteirizado do A/B de centralidade (parecer técnico 4.3).

O fiscal simulado tem na "mochila" as evidências de um caso VÁLIDO do golden set e só entrega uma evidência
quando a mensagem do sistema a pede de forma específica (palavra-chave do tipo de evidência). Entrega uma por
turno: a primeira pedida na mensagem (ordem de aparição) que ele ainda tem. Comete erros típicos, conforme o
perfil:

- `foto_fora`: a 1ª foto da benfeitoria é tirada da sede, a ~650 m da gleba (GPS bom, EXIF íntegro);
- `video_ruim`: o 1º vídeo é filmado com a câmera andando e o lote encostado (o contador se abstém);
- `esquece_gta`: na 1ª vez que pedem a GTA ele diz que não está com ela; só entrega se pedirem de novo.

Além das evidências, a mochila tem as duas declarações que só o fiscal pode fazer (independência, MCR 2-7-15, e
conclusão da obra, MCR 2-7-16-a); ele as faz quando a mensagem pede.

Se a mensagem não pede nada que ele tenha, ele pergunta "o que mais falta?" (turno ocioso); com 2 turnos
ociosos seguidos, ou no limite de turnos, vai embora da fazenda. As mesmas regras valem para os dois braços;
o que muda é só o canal de orientação: o checklist fixo do rulebook (baseline) ou a fala do agente.
"""

from __future__ import annotations

import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import wkt as shp_wkt

RAIZ_EVAL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_EVAL / "golden" / "gerador"))

from fotos_sinteticas import gerar_jpeg

PEDIDOS = {  # tipo de evidência → palavras que contam como pedido específico
    "declaracao": re.compile(r"declar|independ|assist[eê]ncia t[eé]cnica", re.IGNORECASE),
    "nfe": re.compile(r"\bnf-?e?\b|nota fiscal|\bnotas?\b|\bxml\b", re.IGNORECASE),
    "gta": re.compile(r"\bgtas?\b|guia de tr[aâ]nsito", re.IGNORECASE),
    "video": re.compile(r"v[ií]deo|\bfilm|recontag|\bconte\b|contagem", re.IGNORECASE),
    "foto": re.compile(r"\bfotos?\b|fotograf", re.IGNORECASE),
    "conclusao": re.compile(r"conclu[ií]d|conclus[aã]o|obra pronta|obra terminad|estrutura inteira", re.IGNORECASE),
}
# Só conta como pedido a frase que tem um verbo/marca de pedido ("preciso", "envie", "falta", "refaça"...):
# "Foto OK" ou "a contagem deu 35" não fazem o fiscal mandar nada.
PEDIDO_FRASE = re.compile(r"precis|envi[ae]|mand[ae]|tir[ae]|tirar|film[ae]|refa[çz]|refilm|nov[ao]|falt|pend|"
                          r"solicit|pe[çc]o|pedir|\bpedi\b|aguard|pr[oó]ximo passo|traga|fotograf|grav[ae]|captur|repit|"
                          r"repet|inform[ae]|declar[ae]|requer|necess", re.IGNORECASE)
PERFIS = {"P1": {"foto_fora"}, "P2": {"foto_fora", "esquece_gta"}, "P3": {"foto_fora", "esquece_gta", "video_ruim"}}
DECLARACAO = "Declaro que não presto assistência técnica ao produtor nem a empresa dele."


def tipos_pedidos(mensagem: str) -> list[tuple[int, str]]:
    """Tipos de evidência pedidos na mensagem, com a posição. Uma frase conta como pedido se tem marca de pedido;
    se ela não nomeia o tipo ("Precisa refazer do interior."), vale o tipo citado na frase anterior (anáfora,
    como um fiscal de verdade entenderia)."""
    achados: list[tuple[int, str]] = []
    pos, anterior = 0, None
    for frase in re.split(r"(?<=[.!?;\n])\s+", mensagem or ""):
        tipos = [(m.start(), t) for t, rx in PEDIDOS.items() if (m := rx.search(frase))]
        if PEDIDO_FRASE.search(frase):
            if not tipos and anterior:
                tipos = [(0, anterior)]
            for p, t in tipos:
                if t not in {x for _, x in achados}:
                    achados.append((pos + p, t))
        if tipos:
            anterior = min(tipos)[1]
        pos += len(frase) + 1
    return achados


@dataclass
class Item:
    tipo: str
    texto: str
    evidencia: dict[str, Any] | None
    erro: str | None = None  # erro plantado nesta entrega


@dataclass
class Fiscal:
    caso: dict[str, Any]
    dcaso: Path
    dtrab: Path
    perfil: str
    semente: int = 0
    mochila: dict[str, list[Item]] = field(default_factory=dict)
    recusou_gta: bool = False
    ociosos: int = 0
    entregas: list[str] = field(default_factory=list)
    pedidos_vistos: dict[str, int] = field(default_factory=dict)
    relogio: datetime | None = None

    def __post_init__(self) -> None:
        self.rng = random.Random(f"{self.semente}:{self.caso['id']}:{self.perfil}")
        d = datetime.fromisoformat(self.caso["data_fiscalizacao"] + "T08:00:00-03:00")
        self.relogio = d
        erros = PERFIS[self.perfil]
        bov = next(i for i in self.caso["operacao"]["itens"] if i["tipo"] == "bovinos")
        benf = next(i for i in self.caso["operacao"]["itens"] if i["tipo"] != "bovinos")
        m: dict[str, list[Item]] = {"declaracao": [Item("declaracao", DECLARACAO, {
            "tipo": "declaracao", "conteudo_texto": DECLARACAO,
            "meta": {"assunto": "independencia_fiscal", "conflito": False}})]}
        m["nfe"] = [Item("nfe", "Segue o XML da nota fiscal.", {"tipo": "nfe_xml", "caminho": str(self.dcaso / n["arquivo"]),
                                                               "item_id": bov["id"]})
                    for n in self.caso["documentos"]["nfe"]]
        m["gta"] = [Item("gta", f"Segue a GTA {k}.", {"tipo": "gta", "caminho": str(self.dcaso / g["arquivo_json"]),
                                                      "item_id": bov["id"]})
                    for k, g in enumerate(self.caso["documentos"]["gta"], 1)]
        bom = self.dtrab / "curral.mp4"
        bom.write_bytes(b"video-bom\n")
        m["video"] = []
        if "video_ruim" in erros:
            ruim = self.dtrab / "curral_ruim.mp4"
            ruim.write_bytes(b"video-ruim\n")
            m["video"].append(Item("video", "Filmei o lote.", {"tipo": "video", "caminho": str(ruim),
                                                               "item_id": bov["id"]}, erro="video_ruim"))
        m["video"].append(Item("video", f"Filmei o lote passando no corredor; contei {int(bov['quantidade'])} "
                                        "cabeças no olho.", {"tipo": "video", "caminho": str(bom),
                                                             "item_id": bov["id"]}))
        fotos = [f for f in self.caso["fotos"] if f["item_id"] == benf["id"]]
        m["foto"] = []
        if "foto_fora" in erros:
            m["foto"].append(self._foto_fora(benf, fotos[0]))
        for f in fotos:
            g = f["gps_app"]
            m["foto"].append(Item("foto", f"Foto da {benf['tipo']} tirada de dentro da gleba.", {
                "tipo": "foto", "caminho": str(self.dcaso / f["arquivo"]), "item_id": benf["id"],
                "gps": {"lat": g["lat"], "lon": g["lon"], "precisao_m": g["precisao_m"], "fonte": "app"},
                "capturada_em": datetime.fromisoformat(f["exif"]["data_hora"])}))
        detalhe = {"cerca": "com os mourões e os fios instalados", "curral": "com brete, tronco e porteiras prontos"}
        obra = f"{'obra do ' if benf['tipo'] == 'curral' else ''}{benf['tipo']}"
        m["conclusao"] = [Item("conclusao", f"Confirmo que a {obra} está concluída, "
                                            f"{detalhe.get(benf['tipo'], 'pronta')}.", None)]
        self.mochila = m

    def saidas_video(self) -> dict[str, dict[str, Any]]:
        s = dict(self.caso["video"]["saida_simulada_contador"])
        ruim = {"estimativa": max(1, int(s["estimativa"] * 0.8)), "ic80": [max(0, int(s["estimativa"] * 0.6)),
                                                                          int(s["estimativa"] * 1.1) + 1],
                "confianca": 0.41, "oclusao_frac": 0.45}
        return {"curral.mp4": s, "curral_ruim.mp4": ruim}

    def _foto_fora(self, benf: dict[str, Any], ref: dict[str, Any]) -> Item:
        """Foto tirada da sede: 650 m a leste do vértice mais a leste da gleba, GPS bom, EXIF coerente."""
        poly = shp_wkt.loads(self.caso["operacao"]["glebas_wkt"][0])
        c = poly.centroid
        epsg = (32700 if c.y < 0 else 32600) + int((c.x + 180) // 6) % 60 + 1
        ida = Transformer.from_crs(4326, epsg, always_xy=True)
        volta = Transformer.from_crs(epsg, 4326, always_xy=True)
        xs = [ida.transform(x, y) for x, y in poly.exterior.coords]
        x, y = max(xs, key=lambda p: p[0])
        lon, lat = volta.transform(x + 650.0, y)
        quando = datetime.fromisoformat(ref["exif"]["data_hora"]) - timedelta(minutes=40)
        arq = self.dtrab / "foto_sede.jpg"
        arq.write_bytes(gerar_jpeg(self.rng, benf["tipo"], quando, (lat, lon)))
        return Item("foto", f"Foto da {benf['tipo']}.", {
            "tipo": "foto", "caminho": str(arq), "item_id": benf["id"],
            "gps": {"lat": lat, "lon": lon, "precisao_m": 6.0, "fonte": "app"}, "capturada_em": quando},
            erro="foto_fora")

    # -- decisão -------------------------------------------------------------
    def responder(self, mensagem: str) -> tuple[str, Item | None]:
        """Lê a mensagem do sistema e decide o que fazer: ("entrega", item), ("ocioso", None) ou ("fim", None)."""
        achados = tipos_pedidos(mensagem)
        for _, tipo in achados:
            self.pedidos_vistos[tipo] = self.pedidos_vistos.get(tipo, 0) + 1
        for _, tipo in sorted(achados):
            if not self.mochila.get(tipo):
                continue
            if tipo == "gta" and "esquece_gta" in PERFIS[self.perfil] and not self.recusou_gta:
                self.recusou_gta = True
                self.ociosos = 0
                return "recusa", Item("gta", "A GTA ficou no escritório, depois eu mando.", None, erro="esquece_gta")
            item = self.mochila[tipo].pop(0)
            self.ociosos = 0
            self.entregas.append(tipo + (f"({item.erro})" if item.erro else ""))
            return "entrega", item
        self.ociosos += 1
        if self.ociosos >= 2:
            return "fim", Item("fim", "Terminei aqui, vou embora da fazenda.", None)
        return "ocioso", Item("ocioso", "Pronto. O que mais falta?", None)

    def avancar_relogio(self, minutos: int = 4) -> datetime:
        self.relogio = (self.relogio or datetime.now().astimezone()) + timedelta(minutes=minutos)
        return self.relogio
