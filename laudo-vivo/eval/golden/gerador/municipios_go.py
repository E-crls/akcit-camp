"""Municípios de Goiás usados nos casos sintéticos (pecuária de corte e leite).

Códigos IBGE conferidos em `dados/sicor/tabelas_aux/MunicipiosSicor.csv` (tabela auxiliar do Sicor/BCB,
08/10/2026). Coordenadas são aproximações da sede municipal (graus decimais, WGS84), suficientes para
posicionar glebas sintéticas a alguns quilômetros da sede; não use para nada além disso.
"""

from __future__ import annotations

from typing import NamedTuple


class Municipio(NamedTuple):
    ibge: str
    nome: str
    lat: float
    lon: float


MUNICIPIOS_GO: tuple[Municipio, ...] = (
    Municipio("5214838", "NOVA CRIXÁS", -14.098, -50.326),
    Municipio("5220207", "SÃO MIGUEL DO ARAGUAIA", -13.275, -50.163),
    Municipio("5218003", "PORANGATU", -13.441, -49.149),
    Municipio("5212204", "JUSSARA", -15.866, -50.866),
    Municipio("5214002", "MOZARLÂNDIA", -14.745, -50.571),
    Municipio("5208905", "GOIÁS", -15.934, -50.140),
    Municipio("5210208", "IPORÁ", -16.442, -51.118),
    Municipio("5204409", "CAIAPÔNIA", -16.957, -51.810),
    Municipio("5218805", "RIO VERDE", -17.792, -50.920),
    Municipio("5211909", "JATAÍ", -17.881, -51.714),
    Municipio("5213103", "MINEIROS", -17.565, -52.551),
    Municipio("5206404", "CRIXÁS", -14.549, -49.969),
    Municipio("5214606", "NIQUELÂNDIA", -14.474, -48.460),
    Municipio("5217203", "PIRANHAS", -16.425, -51.822),
    Municipio("5221601", "URUAÇU", -14.525, -49.141),
    Municipio("5207535", "FAINA", -15.447, -50.362),
    Municipio("5202502", "ARUANÃ", -14.917, -51.083),
    Municipio("5213707", "MONTES CLAROS DE GOIÁS", -16.106, -51.399),
    Municipio("5216403", "PARAÚNA", -16.947, -50.449),
    Municipio("5218508", "QUIRINÓPOLIS", -18.448, -50.452),
    Municipio("5208004", "FORMOSA", -15.540, -47.334),
    Municipio("5218300", "POSSE", -14.093, -46.369),
    Municipio("5213806", "MORRINHOS", -17.731, -49.101),
    Municipio("5210109", "IPAMERI", -17.722, -48.159),
)

# Origem interestadual ocasional (vendedor em MT), para exercitar CFOP 6.xxx e GTA de outra UF.
MUNICIPIOS_MT: tuple[Municipio, ...] = (
    Municipio("5103106", "COCALINHO", -14.390, -51.000),
    Municipio("5101803", "BARRA DO GARÇAS", -15.890, -52.257),
)
