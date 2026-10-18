"""Configuração comum dos testes.

O sal da instalação (`laudo.privacidade`) mora fora do repositório, em `~/.laudo-vivo/`. Nos testes ele vai
para uma pasta temporária, criada antes da coleta (módulos de apoio calculam hashes na importação), para a
suíte não tocar a configuração da máquina e rodar com um sal novo a cada execução: nenhum teste pode depender
do valor do sal (as gravações de replay, em especial, não podem mudar com ele).
"""

from __future__ import annotations

import os
import shutil
import tempfile

_DIR_CONFIG: list[str] = []


def pytest_configure(config):
    d = tempfile.mkdtemp(prefix="laudo-config-teste-")
    _DIR_CONFIG.append(d)
    os.environ["LAUDO_CONFIG_DIR"] = d
    from laudo import privacidade

    privacidade.limpar_cache()


def pytest_unconfigure(config):
    for d in _DIR_CONFIG:
        shutil.rmtree(d, ignore_errors=True)
