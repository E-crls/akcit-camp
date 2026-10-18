"""Ferramentas do agente. Cada módulo registra suas ferramentas em `laudo.contracts.REGISTRO` ao ser importado."""

from __future__ import annotations

import importlib
import logging

from laudo.contracts import REGISTRO

_MODULOS = [
    "laudo.tools.carteira",
    "laudo.tools.ndvi",
    "laudo.tools.regras",
    "laudo.tools.foto",
    "laudo.tools.geofence",
    "laudo.tools.bovinos",
    "laudo.tools.documentos",
    "laudo.tools.leitura_documentos",  # leitura de DANFE/GTA por foto (VLM + validação)
    "laudo.tools.alegacoes",  # fala livre → alegações conferidas contra evidência
    "laudo.tools.laudo",
    "laudo.tools.pacote",  # pacote de exibição BCB/Justiça (só depois de SELADO)
]

log = logging.getLogger(__name__)


def carregar_todas() -> dict:
    """Importa todos os módulos de ferramentas disponíveis e devolve o registro."""
    for nome in _MODULOS:
        try:
            importlib.import_module(nome)
        except ModuleNotFoundError as e:  # módulo opcional ausente
            if e.name != nome:
                raise
            log.info("ferramenta ausente: %s", nome)
    return REGISTRO
