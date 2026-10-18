"""Fábricas de documentos sintéticos para os testes `test_docs_*` (não é módulo de teste)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from laudo.contracts import ItemFinanciado
from laudo.docs_fiscais import sintetico as s
from laudo.docs_fiscais.comum import hash_documento
from laudo.docs_fiscais.gta import GTA, EmissaoGTA, EmitenteGTA, LocalGTA, QuantidadeGTA
from laudo.docs_fiscais.nfe import ContextoOperacao, ParametrosNFe

TZ = timezone(timedelta(hours=-3))
NOVA_CRIXAS = ("5214838", "NOVA CRIXAS")
MOZARLANDIA = ("5214002", "MOZARLANDIA")
CONTRATACAO = date(2026, 7, 1)
FISCALIZACAO = date(2026, 9, 20)
DATA_NF = datetime(2026, 8, 12, 9, 31, tzinfo=TZ)


@lru_cache(maxsize=1)
def pool() -> s.PoolChaves:
    return s.PoolChaves("testes-docs", n_emitentes=2, bits=1024)


VENDEDOR = s.ParteSintetica(s.cnpj_sintetico(7), "AGROPECUARIA VENDEDORA TESTE 07 LTDA", "GO", *MOZARLANDIA, "109999901")
TOMADOR = s.ParteSintetica(s.cpf_sintetico(1), "PRODUTOR TESTE 01", "GO", *NOVA_CRIXAS, "109999902")
TOMADOR_HASH = hash_documento(TOMADOR.documento)  # hash da instalação (o que sai em doc_sha256)
TOMADOR_REF = f"hmac:{TOMADOR_HASH}"  # como o condutor repassa às ferramentas (já convertido)
COD_ESTAB = "TESTE-5214838-0001"


def item(quantidade: int = 40, valor: float = 126_000.0, categoria: str = "novilha") -> ItemFinanciado:
    return ItemFinanciado(id="bov1", tipo="bovinos", descricao=f"Aquisição de {quantidade} {categoria}s",
                          quantidade=quantidade, unidade="cabeca", valor_rs=valor, categoria_animal=categoria)


def spec_nfe(quantidade: float = 40, preco: float = 3150.0, ncm: str = "01022990", cfop: str = "5101",
             unidade: str = "CB", **kw: Any) -> s.NFeSintetica:
    itens = [s.ItemSintetico("NOV", "NOVILHA NELORE 13-24 MESES", ncm, cfop, unidade, quantidade, preco)]
    base: dict[str, Any] = {"emitente": VENDEDOR, "destinatario": TOMADOR, "itens": itens, "dh_emi": DATA_NF,
                            "serie": 1, "n_nf": 1234, "c_nf": "12345678"}
    base.update(kw)
    return s.NFeSintetica(**base)


def nfe_xml(adulterar: Any = None, **kw: Any) -> bytes:
    sp = spec_nfe(**kw)
    return s.gerar_nfe_xml(sp, pool() if sp.assinar else None, adulterar)


def contexto(**kw: Any) -> ContextoOperacao:
    base: dict[str, Any] = {"uf": "GO", "municipio_ibge": NOVA_CRIXAS[0], "municipio_nome": NOVA_CRIXAS[1],
                            "data_contratacao": CONTRATACAO, "data_fiscalizacao": FISCALIZACAO,
                            "tomador_doc_sha256": TOMADOR_HASH, "codigo_estabelecimento_destino": COD_ESTAB}
    base.update(kw)
    return ContextoOperacao(**base)


def params(**kw: Any) -> ParametrosNFe:
    return ParametrosNFe(**{"aceitar_homologacao": True, **kw})


def gta(quantidade: int = 40, data: date | None = None, **kw: Any) -> GTA:
    d = data or DATA_NF.date()
    base: dict[str, Any] = {
        "uf_emissao": "GO", "numero": "123456", "serie": "A", "especie": "bovina",
        "quantidades": [QuantidadeGTA(sexo="F", faixa_etaria="13-24", quantidade=quantidade)], "total": quantidade,
        "origem": LocalGTA(documento=VENDEDOR.documento, nome=VENDEDOR.nome, estabelecimento="FAZENDA ORIGEM TESTE",
                           codigo_estabelecimento="TESTE-5214002-9000", municipio_nome=MOZARLANDIA[1],
                           municipio_ibge=MOZARLANDIA[0], uf="GO"),
        "destino": LocalGTA(documento=TOMADOR.documento, nome=TOMADOR.nome, estabelecimento="FAZENDA TESTE 01",
                            codigo_estabelecimento=COD_ESTAB, municipio_nome=NOVA_CRIXAS[1],
                            municipio_ibge=NOVA_CRIXAS[0], uf="GO"),
        "finalidade": "REPRODUCAO",
        "emitente": EmitenteGTA(tipo="PRODUTOR", identificacao="EMITENTE TESTE"),
        "emissao": EmissaoGTA(local_municipio=MOZARLANDIA[1], data=d, hora="10:00", validade=d + timedelta(days=2)),
        "sintetico": True,
    }
    base.update(kw)
    return GTA(**base)


def status(resultado: dict[str, Any], campo_sufixo: str) -> str:
    """Status sugerido do campo cujo nome termina em `campo_sufixo`."""
    campos = [v for k, v in resultado["campos"].items() if k.endswith(campo_sufixo)]
    assert len(campos) == 1, (campo_sufixo, list(resultado["campos"]))
    return campos[0]["status_campo_sugerido"]
