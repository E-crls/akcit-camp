"""Casos inspirados em casos públicos (split separado `casos_publicos`) e casos de dev do perfil custeio.

Uso (na raiz do repositório):
    scripts/py.sh eval/golden/gerador/casos_publicos.py --gerar     # regrava casos_publicos/ e dev_custeio/
    scripts/py.sh eval/golden/gerador/casos_publicos.py --rodar     # roda os 6 no modo determinístico
    scripts/py.sh eval/golden/gerador/casos_publicos.py --rodar --custeio   # os 4 de dev do perfil custeio

**Por que um split separado.** Os 6 cenários reproduzem o *mecanismo* de casos noticiados (GTA é necessária,
mas não suficiente), não a frequência: não entram no dev nem no test do golden principal (`casos/SPLIT.yaml`,
congelado em 16/10/2026) e não calibram limiar. Cada caso traz no `caso.yaml` o item normativo e a URL da
notícia/fonte. **Dados 100% sintéticos**: produtor, vendedor, fazendas e documentos são marcadores (`TESTE`,
CPF 000.000.xxx, CNPJ 99.999.999) e os municípios usados NÃO são os das notícias, para que nenhum caso aponte
para pessoa ou imóvel real.

**Modo determinístico** (o mesmo de `eval/run_eval.py --modo deterministico`): o condutor de verdade, sem LLM
(plano mínimo), com as ferramentas reais do `REGISTRO`, o verificador, `avaliar_regras` e a política.
Contornos: contagem simulada pelo resultado do caso (`harness.ferramenta_contador_simulado`, os vídeos não
existem). A consulta ao índice de documentos de laudos selados é a do produto (o executor preenche
`indice_documentos` = `<dir_dados>/indices/documentos.jsonl` e `operacao_ref` = ref. Bacen,
`laudo.agent.indice`); o runner só fixa o índice quando ele é compartilhado entre casos (`rodar(indice=...)`).
No PUB-0004, um laudo selado de OUTRA operação registra antes os mesmos documentos
(`indice.registrar_documentos`, o que a selagem faria). O estado global tocado (traces, ids determinísticos) é
restaurado no fim.

**NF-e e grupo ZF.** Cada NF-e cita no máximo UMA guia (NT 2024.003 v1.03 e v1.10: ZF01 0-1, ZF04 1-1): numa
compra em várias cargas, a nota cita a GTA da carga 1, como a NF-e real de GO (ZF05-10 ativa para NCM 0102;
regras de validação da NT em produção desde 01/03/2026).

**Casos de dev do perfil custeio** (rulebook mcr-2-7 0.4.0, `OP-perfil-custeio-animais`): 4 especificações em
`CUSTEIO_DEV`, versionadas em `eval/golden/casos_publicos/dev_custeio/` (split `dev_custeio`, com SPLIT.yaml
próprio); servem para desenvolver o perfil, nunca para o número do slide.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

_AQUI = Path(__file__).resolve().parent
_REPO = _AQUI.parents[2]
sys.path.insert(0, str(_AQUI))
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from municipios_go import MUNICIPIOS_GO, Municipio

from laudo.contracts import ItemFinanciado, Operacao
from laudo.docs_fiscais import gta as gta_mod
from laudo.docs_fiscais import sintetico as sint
from laudo.docs_fiscais.comum import hash_documento_publico, so_alnum

# 0.2.0: uma guia por NF-e; índice por operação; dev_custeio versionado
# 0.2.1 (16/10/2026, onda 3): PUB-0005 marcado como cenário construído (sem atribuir o mecanismo à notícia de
#       Pains); `split` e `papel` no SPLIT.yaml (dev_custeio = split de desenvolvimento)
VERSAO = "0.2.1"
SEMENTE_CHAVES = "casos-publicos-20261016"
DIR_PUBLICOS = _REPO / "eval" / "golden" / "casos_publicos"
DIR_CUSTEIO = DIR_PUBLICOS / "dev_custeio"
TZ = timezone(timedelta(hours=-3))
CABECAS_POR_CARGA = 40
NOTA_SPLIT = (
    "split separado (casos inspirados em casos públicos): não entra no dev nem no test do golden "
    "principal, não calibra limiar; mede o mecanismo, não a frequência"
)
NOTA_CUSTEIO = (
    "split dev_custeio: 4 casos de desenvolvimento do perfil custeio de animais (rulebook mcr-2-7 0.4.0); "
    "não são casos públicos nem entram no golden principal; nunca vão para o número do slide"
)
PAPEL_PUBLICOS = (
    "avaliacao_separada: mede o mecanismo (não a frequência); não calibra limiar; fora do dev e do test "
    "do golden principal"
)
PAPEL_CUSTEIO = (
    "dev: desenvolvimento do perfil custeio; pode ser regerado e usado para ajustar o perfil; sem split de "
    "teste próprio, por isso nunca vai para número de slide; fica fora de eval/golden/casos, cujo split está "
    "congelado (sha256_split) desde 16/10/2026"
)


def _mun(nome: str) -> Municipio:
    return next(m for m in MUNICIPIOS_GO if m.nome == nome)


# ---------------------------------------------------------------------------
# Especificação de um caso
# ---------------------------------------------------------------------------


@dataclass
class GTAEsp:
    quantidade: int
    numero: str
    serie: str = "A"
    uf: str = "GO"
    destino_codigo: str | None = None  # None = o estabelecimento da operação
    destino_estab: str | None = None
    origem_doc: str | None = None  # None = o vendedor da NF-e
    origem_nome: str | None = None
    origem_mun: str | None = None  # None = município do vendedor
    origem_codigo: str | None = None


@dataclass
class Caso:
    id: str
    n: int  # ordem do caso (marcadores TESTE NN, CPF/CNPJ sintéticos)
    titulo: str
    classe: str  # valido | defeito | ambiguo (mesmo vocabulário do golden principal)
    inspiracao: dict[str, Any] | None
    finalidade: str
    categoria: str  # novilha | vaca | garrote
    quantidade: int  # financiada
    preco: float
    municipio: str
    municipio_vendedor: str
    area_ha: float
    descricao_item: str
    nfe_quantidade: int | None  # None = sem NF-e
    gtas: list[GTAEsp]
    guia_zf: dict[str, str] | None = None  # grupo ZF da NF-e (NT 2024.003): uma guia por nota
    contador: dict[str, Any] | None = None  # saída simulada do contador; None = sem vídeo (documental)
    pre_indice: bool = False  # NF-e e GTA já em laudo selado de OUTRA operação (índice de reuso)
    contratacao: date = date(2026, 7, 1)
    data_nf: date = date(2026, 7, 20)
    data_fiscalizacao: date = date(2026, 9, 15)
    esperado_laudo: dict[str, str] = field(default_factory=dict)  # campo do laudo → status
    esperado_finos: dict[str, str] = field(default_factory=dict)  # campo da conciliação → status sugerido
    ausentes: list[str] = field(
        default_factory=list
    )  # campos do laudo que não devem existir (não aplicáveis)
    notas: str = ""

    @property
    def mun(self) -> Municipio:
        return _mun(self.municipio)

    @property
    def mun_vend(self) -> Municipio:
        return _mun(self.municipio_vendedor)

    @property
    def cod_estab(self) -> str:
        return f"TESTE-{self.mun.ibge}-{self.n:04d}"

    @property
    def tomador(self) -> sint.ParteSintetica:
        return sint.ParteSintetica(
            sint.cpf_sintetico(700 + self.n),
            f"PRODUTOR TESTE PUB {self.n:02d}",
            "GO",
            self.mun.ibge,
            self.mun.nome,
            f"10999{self.n:04d}",
        )

    @property
    def vendedor(self) -> sint.ParteSintetica:
        return sint.ParteSintetica(
            sint.cnpj_sintetico(700 + self.n),
            f"AGROPECUARIA VENDEDORA TESTE PUB {self.n:02d} LTDA",
            "GO",
            self.mun_vend.ibge,
            self.mun_vend.nome,
            f"10998{self.n:04d}",
        )


_CAT = {  # categoria: (sexo, faixa etária, NCM, xProd, finalidade da GTA)
    "novilha": ("F", "13-24", "01022990", "NOVILHA NELORE 13-24 MESES", "REPRODUCAO"),
    "vaca": ("F", ">36", "01022911", "VACA NELORE PRENHE", "REPRODUCAO"),
    "garrote": ("M", "13-24", "01022990", "GARROTE NELORE 13-24 MESES", "ENGORDA"),
    "boi": ("M", "25-36", "01022990", "BOI MAGRO NELORE 25-36 MESES", "ENGORDA"),
}


def _cargas(q: int) -> list[int]:
    n = max(1, -(-q // CABECAS_POR_CARGA))
    return [q // n + (1 if k < q % n else 0) for k in range(n)]


def _gtas_padrao(q: int, numero0: int, serie: str = "A") -> list[GTAEsp]:
    return [GTAEsp(quantidade=x, numero=f"{numero0 + k:06d}", serie=serie) for k, x in enumerate(_cargas(q))]


def _cont(est: int, lo: int, hi: int, conf: float = 0.92) -> dict[str, Any]:
    return {"estimativa": est, "ic80": [lo, hi], "confianca": conf, "oclusao_frac": 0.04}


def _zf(g: GTAEsp) -> dict[str, str]:
    """Grupo ZF que cita a GTA dada (tpGuia 1 = GTA; serieGuia, C 1-9, com a série da e-GTA)."""
    return {"tpGuia": "1", "UFGuia": g.uf, "serieGuia": g.serie, "nGuia": g.numero}


# ---------------------------------------------------------------------------
# Os 6 cenários inspirados em casos públicos
# ---------------------------------------------------------------------------

_URL_PAINS = (
    "https://comprerural.com/fraude-em-financiamentos-rurais-de-r-18-milhao-faz-politico-virar-reu-na-"
    "justica-federal/"
)
_URL_BOI_PAPEL = "https://comprerural.com/boi-de-papel-fraude-deixa-prejuizo-de-r-94-milhoes/"
_URL_ORIZONA = (
    "https://comprerural.com/gta-teria-sido-usada-para-legalizar-transporte-de-gado-furtado-em-goias-"
    "agrodefesa-investiga/"
)
_URL_ORIZONA_2 = (
    "https://www.maisgoias.com.br/cidades/agrodefesa-investiga-servidor-suspeito-de-fraudar-guias-para-"
    "transporte-de-gado-furtado-em-goias/"
)
_URL_ZF = "https://inventti.com.br/wp-content/uploads/2025/02/NT_2024.003-1.03.pdf"  # PDF da NT v1.03
_URL_GADO_FANTASMA_EUA = "https://www.wlj.net/ky-cattle-fraud-scheme-exposed/"
_URL_MANUAL_SDA = "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos"
ACESSO = "2026-10-16"
ACESSO_NAO_REGISTRADO_SDA = (
    "data de acesso não registrada: regra do destino (item 12) tirada de src/laudo/docs_fiscais/fontes.py "
    "(MAPA-SDA-BOV-item12), que registra a URL sem data; não relida em 16/10/2026"
)


def _publicos() -> list[Caso]:
    g_pains = _gtas_padrao(160, 520201)
    g_papel = _gtas_padrao(80, 530301)
    g_papel_citada = GTAEsp(40, "538801", serie="B")  # a guia que a NF-e cita (não apresentada)
    g_reuso = _gtas_padrao(40, 540401)
    g_destino = [
        GTAEsp(40, "550501", destino_codigo="TESTE-{ibge}-0099", destino_estab="FAZENDA OUTRA TESTE PUB 05")
    ]
    g_origem = [
        GTAEsp(
            40,
            "560601",
            origem_doc=sint.cpf_sintetico(790),
            origem_nome="PRODUTOR ORIGEM TESTE PUB 03",
            origem_mun="IPAMERI",
            origem_codigo="TESTE-5210109-9303",
        )
    ]
    g_mcclain = _gtas_padrao(120, 570701)
    return [
        Caso(
            id="PUB-0001",
            n=1,
            titulo="Documentos completos e rebanho ausente: 3% do financiado no curral",
            classe="defeito",
            inspiracao={
                "caso": "Pains (MG): 1.553 cabeças financiadas e 47 encontradas na vistoria do banco",
                "fonte": "CompreRural",
                "url": _URL_PAINS,
                "acesso": ACESSO,
                "data_noticia": "2026-01-09",
                "item_normativo": (
                    "MCR 2-7-2-a-I e 2-5-10 (aplicação comprovada); OP-bovinos-contagem-tolerancia"
                ),
                "o_que_prova": "NF-e e GTA coerentes não provam que o animal financiado está na fazenda",
                "o_que_nao_prova": "frequência do desvio; nada sobre Goiás",
                "adaptacao": "proporção mantida (cerca de 3%): 160 financiadas, 5 contadas; uma NF-e e 4 "
                "GTAs (uma por carga), com a GTA da carga 1 no grupo ZF da nota (uma guia por NF-e)",
            },
            finalidade="investimento",
            categoria="novilha",
            quantidade=160,
            preco=3400.0,
            municipio="JUSSARA",
            municipio_vendedor="FAINA",
            area_ha=180.0,
            descricao_item="Aquisição de 160 novilhas (bovinos carne - matrizes)",
            nfe_quantidade=160,
            gtas=g_pains,
            guia_zf=_zf(g_pains[0]),
            contador=_cont(5, 4, 6),
            esperado_laudo={
                "item:bov1:quantidade": "divergente",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "verificado",
                "item:bov1": "divergente",
            },
            esperado_finos={"documento:gta:nfe_guia": "verificado", "item:bov1:gta_quantidade": "verificado"},
        ),
        Caso(
            id="PUB-0002",
            n=2,
            titulo="GTA de papel: as GTAs apresentadas não são a citada no grupo ZF da NF-e",
            classe="ambiguo",
            inspiracao={
                "caso": "Operação Boi de Papel (PF/TO): GTAs falsas simulando compra de gado inexistente; "
                "R$ 94 mi é o crédito concedido, não o prejuízo",
                "fonte": "CompreRural",
                "url": _URL_BOI_PAPEL,
                "acesso": ACESSO,
                "data_noticia": "2024-03-08",
                "item_normativo": "NT 2024.003 v1.03 grupo ZF (guiaTransito: uma guia por NF-e; nGuia, "
                "série, UF); OP-bovinos-gta; MCR 2-5-10-b",
                "o_que_prova": "a GTA só vale cruzada com a nota: quando nenhuma GTA apresentada é a citada "
                "no grupo ZF, o laudo não fecha (pendência até a GTA citada aparecer)",
                "o_que_nao_prova": (
                    "falsidade da GTA (autenticidade só no SIDAGO/BDU, fora do escopo offline); nem que a "
                    "GTA é de outra venda: o fiscal pode só não ter enviado a GTA citada, por isso é "
                    "pendência e não acusação"
                ),
                "adaptacao": "fiscalização documental (sem vídeo); duas GTAs apresentadas (cargas 1 e 2) e a "
                "NF-e cita no grupo ZF uma terceira guia, de outra série",
            },
            finalidade="investimento",
            categoria="vaca",
            quantidade=80,
            preco=4100.0,
            municipio="IPORÁ",
            municipio_vendedor="PIRANHAS",
            area_ha=150.0,
            descricao_item="Aquisição de 80 vacas (bovinos carne - matrizes)",
            nfe_quantidade=80,
            gtas=g_papel,
            guia_zf=_zf(g_papel_citada),
            contador=None,
            esperado_laudo={
                "item:bov1:quantidade": "pendente",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "pendente",
                "item:bov1": "pendente",
            },
            esperado_finos={"documento:gta:nfe_guia": "pendente", "item:bov1:gta_quantidade": "verificado"},
        ),
        Caso(
            id="PUB-0003",
            n=3,
            titulo="GTA com origem em outro produtor e outro município que o vendedor da NF-e",
            classe="ambiguo",
            inspiracao={
                "caso": "GTA com origem falsa (Orizona/Vianópolis, GO): a guia teria indicado como origem "
                "uma fazenda diferente daquela de onde o gado saiu; caso em apuração na Agrodefesa",
                "fonte": "CompreRural (republicação de Mais Goiás)",
                "url": _URL_ORIZONA,
                "url_adicional": _URL_ORIZONA_2,
                "acesso": ACESSO,
                "data_noticia": "2026-09-17",
                "item_normativo": "Manual SDA de trânsito de bovinos, item 11 (procedência); OP-bovinos-gta",
                "o_que_prova": "origem da GTA incoerente com o vendedor da NF-e vira pendência para o "
                "humano, nunca acusação",
                "o_que_nao_prova": "que a origem é falsa; a investigação citada não tem conclusão",
                "adaptacao": "municípios trocados por outros de GO (nenhum dado aponta para os imóveis da "
                "notícia)",
            },
            finalidade="investimento",
            categoria="novilha",
            quantidade=40,
            preco=3300.0,
            municipio="MORRINHOS",
            municipio_vendedor="MORRINHOS",
            area_ha=60.0,
            descricao_item="Aquisição de 40 novilhas (bovinos carne - matrizes)",
            nfe_quantidade=40,
            gtas=g_origem,
            contador=_cont(40, 40, 40),
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "pendente",
                "item:bov1": "pendente",
            },
            esperado_finos={"item:bov1:gta_origem": "pendente"},
        ),
        Caso(
            id="PUB-0004",
            n=4,
            titulo="Mesma NF-e e mesma GTA já em laudo selado de outra operação (reuso de documento)",
            classe="defeito",
            inspiracao={
                "caso": "Regra 10ZF04-20 da NT 2024.003 (rejeição 838, 'Guia de Trânsito já utilizada', "
                "facultativa por UF): a SEFAZ recusa a guia já usada; do lado da IF, o análogo é o "
                "índice local dos documentos de laudos já selados",
                "fonte": "Nota Técnica 2024.003 v1.03 da NF-e (fev/2025), seção 4, regras 10ZF04-10 e "
                "10ZF04-20",
                "url": _URL_ZF,
                "acesso": ACESSO,
                "data_noticia": "2025-02",  # mês da v1.03 (o PDF não traz o dia)
                "item_normativo": "MCR 2-7-6-b e 2-7-7-d (duplicidade de crédito; pecuária pelo item 9); "
                "NT 2024.003 ZF04-20",
                "o_que_prova": "o mesmo documento não comprova duas operações: GTA e chave de NF-e "
                "conferidas por HMAC, nunca em claro; refiscalizar a mesma operação não é reuso",
                "o_que_nao_prova": "reuso fora desta instalação (hashes com sal não se comparam entre IFs)",
                "adaptacao": "um laudo selado sintético de outra operação registra os documentos antes do "
                "caso",
            },
            finalidade="investimento",
            categoria="novilha",
            quantidade=40,
            preco=3350.0,
            municipio="PARAÚNA",
            municipio_vendedor="PARAÚNA",
            area_ha=70.0,
            descricao_item="Aquisição de 40 novilhas (bovinos carne - matrizes)",
            nfe_quantidade=40,
            gtas=g_reuso,
            guia_zf=_zf(g_reuso[0]),
            contador=_cont(40, 39, 41),
            pre_indice=True,
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:comprovante_nfe": "divergente",
                "item:bov1:gta": "divergente",
                "item:bov1": "divergente",
            },
            esperado_finos={
                "documento:gta:reuso": "divergente",
                "documento:nfe:reuso": "divergente",
                "documento:gta:nfe_guia": "verificado",
            },
        ),
        Caso(
            id="PUB-0005",
            n=5,
            titulo="GTA com destino em outro imóvel do mesmo município",
            classe="defeito",
            inspiracao={
                "natureza": "cenario_construido",
                "caso": "cenário construído pela equipe, sem notícia de origem: a GTA leva o lote para outro "
                "estabelecimento do mesmo município, e não para o da operação; a regra é a do campo de "
                "destino da GTA",
                "fonte": "Manual SDA de trânsito de bovinos e bubalinos (regra do destino; não é notícia)",
                "url": _URL_MANUAL_SDA,
                # sem data de acesso registrada: a regra vem de docs_fiscais/fontes.py (MAPA-SDA-BOV-item12),
                # que guarda a URL sem data; em 16/10/2026 a página não foi relida (abre só o cabeçalho sem
                # script e a rede desta máquina recusa o download). Não se põe a data de hoje sem acesso.
                "acesso": None,
                "acesso_nota": ACESSO_NAO_REGISTRADO_SDA,
                "item_normativo": "Manual SDA de trânsito de bovinos, item 12 (destino); MCR 2-7-2-a-I; "
                "OP-bovinos-gta",
                "o_que_prova": "estabelecimento de destino da GTA diferente do da operação diverge, mesmo "
                "no mesmo município",
                "o_que_nao_prova": (
                    "que os animais não estão no imóvel (pode haver arrendamento: humano decide)"
                ),
                "adaptacao": "mesmo tomador e mesmo município; só o código do estabelecimento muda",
            },
            finalidade="investimento",
            categoria="novilha",
            quantidade=40,
            preco=3250.0,
            municipio="QUIRINÓPOLIS",
            municipio_vendedor="RIO VERDE",
            area_ha=55.0,
            descricao_item="Aquisição de 40 novilhas (bovinos carne - matrizes)",
            nfe_quantidade=40,
            gtas=g_destino,
            contador=_cont(40, 40, 41),
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "divergente",
                "item:bov1": "divergente",
            },
            esperado_finos={"item:bov1:gta_destino": "divergente"},
        ),
        Caso(
            id="PUB-0006",
            n=6,
            titulo="Custeio de engorda: contagem muito abaixo da GTA (25% do documentado)",
            classe="defeito",
            inspiracao={
                "caso": "Esquema de gado 'fantasma' em confinamento nos EUA (TX/KY): 89.522 cabeças "
                "declaradas como garantia em dez/2022 (37.992 em fev/2023) e 10.559 encontradas na auditoria "
                "do credor (cerca de 12% e 28%, respectivamente)",
                "fonte": "Western Livestock Journal",
                "url": _URL_GADO_FANTASMA_EUA,
                "acesso": ACESSO,
                "data_noticia": "2023-05-19",
                "item_normativo": "OP-perfil-custeio-animais (MCR 2-7-1-c); OP-bovinos-contagem-tolerancia",
                "o_que_prova": "GTA e NF-e somando o lote inteiro não substituem a contagem no curral",
                "o_que_nao_prova": "nada sobre o crédito rural brasileiro (caso estrangeiro, só mecanismo)",
                "adaptacao": "custeio de aquisição para engorda (perfil 0.4.0); 120 na NF-e e na GTA, "
                "100 financiadas, 30 contadas",
            },
            finalidade="custeio",
            categoria="garrote",
            quantidade=100,
            preco=2600.0,
            municipio="MONTES CLAROS DE GOIÁS",
            municipio_vendedor="ARUANÃ",
            area_ha=90.0,
            descricao_item="Custeio de aquisição de 100 garrotes para engorda",
            nfe_quantidade=120,
            gtas=g_mcclain,
            guia_zf=_zf(g_mcclain[0]),
            contador=_cont(30, 28, 32),
            esperado_laudo={
                "item:bov1:quantidade": "divergente",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "verificado",
                "item:bov1:lotacao": "verificado",
                "item:bov1:metodo_if": "verificado",
                "item:bov1": "divergente",
            },
            esperado_finos={"documento:gta:nfe_guia": "verificado"},
        ),
    ]


def _custeio() -> list[Caso]:
    g80 = _gtas_padrao(80, 610101)
    g80b = _gtas_padrao(80, 620201)
    g80c = [
        GTAEsp(40, "630301"),
        GTAEsp(
            40, "630302", destino_codigo="TESTE-{ibge}-0098", destino_estab="FAZENDA VIZINHA TESTE CUS 03"
        ),
    ]
    base = {
        "finalidade": "custeio",
        "categoria": "garrote",
        "preco": 2550.0,
        "municipio": "CRIXÁS",
        "municipio_vendedor": "NOVA CRIXÁS",
        "inspiracao": None,
    }
    return [
        Caso(
            id="CUS-0001",
            n=21,
            titulo="Custeio de aquisição de garrotes: tudo confere",
            classe="valido",
            quantidade=80,
            area_ha=50.0,
            descricao_item="Custeio de aquisição de 80 garrotes para recria",
            nfe_quantidade=80,
            gtas=g80,
            guia_zf=_zf(g80[0]),
            contador=_cont(80, 79, 81),
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "verificado",
                "item:bov1:lotacao": "verificado",
                "item:bov1:metodo_if": "verificado",
                "item:bov1": "verificado",
            },
            **base,
        ),
        Caso(
            id="CUS-0002",
            n=22,
            titulo="Custeio de aquisição: contagem abaixo da tolerância",
            classe="defeito",
            quantidade=80,
            area_ha=50.0,
            descricao_item="Custeio de aquisição de 80 garrotes para recria",
            nfe_quantidade=80,
            gtas=g80b,
            contador=_cont(52, 50, 54),
            esperado_laudo={
                "item:bov1:quantidade": "divergente",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "verificado",
                "item:bov1:lotacao": "verificado",
                "item:bov1": "divergente",
            },
            **base,
        ),
        Caso(
            id="CUS-0003",
            n=23,
            titulo="Custeio de aquisição: uma das GTAs vai para outro estabelecimento",
            classe="defeito",
            quantidade=80,
            area_ha=50.0,
            descricao_item="Custeio de aquisição de 80 garrotes para recria",
            nfe_quantidade=80,
            gtas=g80c,
            contador=_cont(80, 80, 81),
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:comprovante_nfe": "verificado",
                "item:bov1:gta": "divergente",
                "item:bov1": "divergente",
            },
            esperado_finos={"item:bov1:gta_destino": "divergente"},
            **base,
        ),
        Caso(
            id="CUS-0004",
            n=24,
            titulo="Custeio só de manutenção do lote, lotação acima do parâmetro",
            classe="valido",
            quantidade=150,
            area_ha=30.0,
            descricao_item="Custeio de manutenção de 150 bois em engorda (sal mineral, ração e vacinas)",
            nfe_quantidade=None,
            gtas=[],
            contador=_cont(150, 149, 152),
            esperado_laudo={
                "item:bov1:quantidade": "verificado",
                "item:bov1:lotacao": "pendente",
                "item:bov1:metodo_if": "verificado",
                "item:bov1": "verificado",
            },
            ausentes=["item:bov1:comprovante_nfe", "item:bov1:gta"],
            notas="NF-e e GTA de compra não se aplicam (item só de manutenção); lotação de 5 cab/ha é ponto "
            "de atenção não bloqueante",
            **{**base, "categoria": "boi"},
        ),
    ]


PUBLICOS = _publicos()
CUSTEIO_DEV = _custeio()


# ---------------------------------------------------------------------------
# Geração dos arquivos
# ---------------------------------------------------------------------------


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _nfe(c: Caso, pool: sint.PoolChaves) -> tuple[sint.NFeSintetica, bytes]:
    _, _, ncm, xprod, _ = _CAT[c.categoria]
    dh = datetime(c.data_nf.year, c.data_nf.month, c.data_nf.day, 9, 30 + c.n % 20, tzinfo=TZ)
    item = sint.ItemSintetico(
        f"BOV-{c.categoria[:3].upper()}", xprod, ncm, "5101", "CB", float(c.nfe_quantidade or 0), c.preco
    )
    spec = sint.NFeSintetica(
        emitente=c.vendedor,
        destinatario=c.tomador,
        itens=[item],
        dh_emi=dh,
        serie=1,
        n_nf=7000 + c.n,
        c_nf=f"{(c.n * 7919 + 1234567) % 100_000_000:08d}",
        guia_transito=c.guia_zf,
    )
    return spec, sint.gerar_nfe_xml(spec, pool)


def _gta(c: Caso, g: GTAEsp, k: int, n_cargas: int, chave_nfe: str | None) -> gta_mod.GTA:
    sexo, faixa, _, _, finalidade = _CAT[c.categoria]
    origem_mun = _mun(g.origem_mun) if g.origem_mun else c.mun_vend
    origem_doc = so_alnum(g.origem_doc or c.vendedor.documento)
    destino_cod = (g.destino_codigo or c.cod_estab).format(ibge=c.mun.ibge)
    d = c.data_nf
    return gta_mod.GTA(
        modelo="e-GTA",
        uf_emissao=g.uf,
        numero=g.numero,
        serie=g.serie,
        especie="bovina",
        quantidades=[gta_mod.QuantidadeGTA(sexo=sexo, faixa_etaria=faixa, quantidade=g.quantidade)],
        total=g.quantidade,
        total_por_extenso=f"{sint.por_extenso(g.quantidade)} BOVINOS",
        marca_rebanho=f"MARCA TESTE PUB {c.n:02d}",
        origem=gta_mod.LocalGTA(
            documento=origem_doc,
            nome=g.origem_nome or c.vendedor.nome,
            estabelecimento=f"FAZENDA ORIGEM TESTE PUB {c.n:02d}",
            codigo_estabelecimento=g.origem_codigo or f"TESTE-{origem_mun.ibge}-9{c.n:03d}",
            municipio_nome=origem_mun.nome,
            municipio_ibge=origem_mun.ibge,
            uf="GO",
        ),
        destino=gta_mod.LocalGTA(
            documento=so_alnum(c.tomador.documento),
            nome=c.tomador.nome,
            estabelecimento=g.destino_estab or f"FAZENDA TESTE PUB {c.n:02d}",
            codigo_estabelecimento=destino_cod,
            municipio_nome=c.mun.nome,
            municipio_ibge=c.mun.ibge,
            uf="GO",
        ),
        finalidade=finalidade,
        meio_transporte={"tipo": "RODOVIARIO", "placa": f"TST{c.n % 10}A{k:02d}"},
        observacao=f"CARGA {k} DE {n_cargas}" if n_cargas > 1 else None,
        emitente=gta_mod.EmitenteGTA(
            tipo="PRODUTOR",
            identificacao="EMISSAO ELETRONICA - EMITENTE TESTE",
            unidade_expedidora=f"UNIDADE LOCAL TESTE {origem_mun.nome}",
        ),
        emissao=gta_mod.EmissaoGTA(
            local_municipio=origem_mun.nome,
            data=d,
            hora=f"{10 + k % 8:02d}:15",
            validade=d + timedelta(days=2),
        ),
        nfe_chaves=[chave_nfe] if chave_nfe else [],
        codigo_barras=f"SINT{g.uf}{g.serie}{g.numero}",
        sintetico=True,
    )


def gerar_caso(c: Caso, pool: sint.PoolChaves, saida: Path) -> dict[str, Any]:
    """Escreve `<saida>/<id>/` (caso.yaml, nfe_1.xml, gta_N.json) e devolve o resumo com o sha256 do caso."""
    d = saida / c.id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    docs_nfe, chave = [], None
    if c.nfe_quantidade:
        spec, xml = _nfe(c, pool)
        (d / "nfe_1.xml").write_bytes(xml)
        chave = spec.chave
        docs_nfe.append(
            {
                "arquivo": "nfe_1.xml",
                "chave": chave,
                "sha256": _sha(xml),
                "grupo_zf": (
                    f"{c.guia_zf['UFGuia']}-{c.guia_zf.get('serieGuia', '?')}-{c.guia_zf['nGuia']}"
                    if c.guia_zf
                    else None
                ),
            }
        )
    docs_gta = []
    for k, g in enumerate(c.gtas, 1):
        gta = _gta(c, g, k, len(c.gtas), chave)
        js = json.dumps(gta.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8")
        (d / f"gta_{k}.json").write_bytes(js)
        docs_gta.append(
            {"arquivo_json": f"gta_{k}.json", "identificador": gta.identificador, "sha256": _sha(js)}
        )
    bov = ItemFinanciado(
        id="bov1",
        tipo="bovinos",
        descricao=c.descricao_item,
        quantidade=c.quantidade,
        unidade="cabeca",
        valor_rs=round(c.quantidade * c.preco, 2),
        categoria_animal=c.categoria,
    )
    op = Operacao(
        ref_bacen=f"SINT-PUB-2026-{c.n:06d}",
        tomador_ref=f"TOMADOR-TESTE-PUB-{c.n:02d}",
        uf="GO",
        municipio_ibge=c.mun.ibge,
        municipio_nome=c.mun.nome,
        instituicao=f"COOPERATIVA DE CREDITO TESTE PUB {c.n % 3 + 1:02d}",
        finalidade=c.finalidade,
        data_contratacao=c.contratacao,
        valor_rs=bov.valor_rs,
        area_financiada_ha=c.area_ha,
        area_informada_ha=c.area_ha,
        itens=[bov],
        fonte="sintetico",
    )
    tomador_hash = hash_documento_publico(c.tomador.documento)
    contexto = {
        "item": bov.model_dump(mode="json"),
        "uf_operacao": "GO",
        "municipio_ibge": c.mun.ibge,
        "municipio_nome": c.mun.nome,
        "data_contratacao": c.contratacao.isoformat(),
        "data_fiscalizacao": c.data_fiscalizacao.isoformat(),
        "tomador_doc_sha256": tomador_hash,
        "codigo_estabelecimento_destino": c.cod_estab,
    }
    entradas: dict[str, Any] = {}
    if docs_nfe:
        entradas["conciliar_nfe"] = {
            **contexto,
            "caminhos": ["nfe_1.xml"],
            "parametros": {"aceitar_homologacao": True},
        }
    if docs_gta:
        entradas["conciliar_gta"] = {
            **contexto,
            "caminhos": [x["arquivo_json"] for x in docs_gta],
            "nfe_caminhos": [x["arquivo"] for x in docs_nfe],
            "parametros": {},
        }
    caso = {
        "id": c.id,
        "versao_gerador": VERSAO,
        "split": "casos_publicos" if c.id.startswith("PUB") else "dev_custeio",
        "sintetico": True,
        "classe": c.classe,
        "titulo": c.titulo,
        "inspiracao": c.inspiracao,
        "data_fiscalizacao": c.data_fiscalizacao.isoformat(),
        "operacao": op.model_dump(mode="json"),
        "projeto": {
            "propriedade": {
                "nome": f"FAZENDA TESTE PUB {c.n:02d}",
                "codigo_estabelecimento": c.cod_estab,
                "municipio_ibge": c.mun.ibge,
                "municipio_nome": c.mun.nome,
            },
            "lotacao_implicita_cab_ha": round(c.quantidade / c.area_ha, 2),
        },
        "tomador": {
            "ref": op.tomador_ref,
            "nome": c.tomador.nome,
            "documento_sintetico": c.tomador.documento,
            "documento_sha256": tomador_hash,
        },
        "documentos": {"nfe": docs_nfe, "gta": docs_gta},
        "pre_indice": {
            "operacao": f"SINT-PUB-ANTERIOR-{c.n:06d}",
            "fiscalizacao": f"fis:anterior:{c.id}",
            "documentos": "nfe_1.xml e todas as GTAs do caso, em laudo selado de outra operação",
        }
        if c.pre_indice
        else None,
        "video": None
        if c.contador is None
        else {
            "id": "video_curral_1",
            "ref": f"sintetico://videos/{c.id}/curral.mp4",
            "arquivo_disponivel": False,
            "item_id": "bov1",
            "saida_simulada_contador": c.contador,
        },
        "entradas_ferramentas": entradas,
        "esperado": {
            "laudo": dict(c.esperado_laudo),
            "finos": dict(c.esperado_finos),
            "ausentes": list(c.ausentes),
        },
        "notas": c.notas or None,
    }
    texto = yaml.safe_dump(caso, sort_keys=False, allow_unicode=True, width=110).encode("utf-8")
    (d / "caso.yaml").write_bytes(texto)
    arquivos = {p.name: _sha(p.read_bytes()) for p in sorted(d.iterdir())}
    return {
        "id": c.id,
        "classe": c.classe,
        "titulo": c.titulo,
        "sha256_caso": _sha(texto),
        "arquivos": arquivos,
    }


def gerar(casos: list[Caso], saida: Path, bits: int = 1024, nota: str | None = None) -> dict[str, Any]:
    """Gera os casos e o manifesto `SPLIT.yaml` (hash de cada caso e do conjunto). Determinístico."""
    saida.mkdir(parents=True, exist_ok=True)
    pool = sint.PoolChaves(SEMENTE_CHAVES, n_emitentes=2, bits=bits)
    resumos = [gerar_caso(c, pool, saida) for c in casos]
    sha_conteudo = _sha("".join(f"{r['id']}:{r['sha256_caso']}\n" for r in resumos).encode())
    custeio = bool(casos) and all(c.id.startswith("CUS") for c in casos)
    if nota is None:
        nota = NOTA_CUSTEIO if custeio else NOTA_SPLIT
    meta = {
        "gerador": {"versao": VERSAO, "semente_chaves": SEMENTE_CHAVES, "bits": bits},
        "split": "dev_custeio" if custeio else "casos_publicos",
        # 0.2.1: o papel do split fica escrito no manifesto (dev_custeio é split de desenvolvimento)
        "papel": PAPEL_CUSTEIO if custeio else PAPEL_PUBLICOS,
        "nota": nota,
        "congelado": False,
        "sha256_conteudo": sha_conteudo,
        "casos": resumos,
    }
    (saida / "SPLIT.yaml").write_bytes(
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110).encode("utf-8")
    )
    return meta


# ---------------------------------------------------------------------------
# Execução determinística (condutor sem LLM)
# ---------------------------------------------------------------------------


def _harness():
    if str(_REPO / "eval") not in sys.path:
        sys.path.insert(0, str(_REPO / "eval"))
    import harness as H

    return H


@contextlib.contextmanager
def _estado_global(semente: str, traces: Path):
    """Ids determinísticos e traces num diretório próprio; restaura os dois no fim."""
    from laudo.agent import estado as est
    from laudo.audit import otel

    antes = dict(otel._estado)
    ids = dict(est._IDS)
    est.ids_deterministicos(semente)
    otel.configurar(traces)
    try:
        yield
    finally:
        otel._estado.clear()
        otel._estado.update(antes)
        est._IDS.clear()
        est._IDS.update(ids)


def registro_do_caso(caso: dict[str, Any], indice: Path | None, operacao_ref: str) -> dict:
    """Ferramentas reais + contador simulado; `conciliar_nfe`/`conciliar_gta` consultando o índice de
    documentos de laudos selados indicado (`indice_documentos` + `operacao_ref` = ref. Bacen: o mesmo que o
    executor preenche a partir do diretório de dados, aqui fixado para o índice poder ser compartilhado)."""
    from laudo.tools import carregar_todas

    H = _harness()
    reg = dict(carregar_todas())
    video = caso.get("video") or {}
    reg["contar_bovinos_video"] = H.ferramenta_contador_simulado(
        {"curral.mp4": video["saida_simulada_contador"]} if video else {}
    )
    if indice is not None:
        extras = {"indice_documentos": str(indice), "operacao_ref": operacao_ref}
        for nome in ("conciliar_nfe", "conciliar_gta"):
            reg[nome] = H.ferramenta_com_contexto(reg[nome], extras)
    return reg


def semear_indice(caso: dict[str, Any], dcaso: Path, indice: Path) -> int:
    """Laudo selado (sintético) de OUTRA operação com a NF-e e as GTAs do caso (cenário de reuso): concilia os
    documentos e registra no índice o que a selagem registraria. Devolve quantas linhas gravou."""
    from laudo.docs_fiscais import indice as I
    from laudo.tools import documentos as T

    pre = caso.get("pre_indice")
    if not pre:
        return 0
    ent = caso["entradas_ferramentas"]
    docs: list[tuple[str, str, str | None]] = []
    if "conciliar_nfe" in ent:
        e = dict(ent["conciliar_nfe"], caminhos=[str(dcaso / x) for x in ent["conciliar_nfe"]["caminhos"]])
        env = T.conciliar_nfe(T.EntradaConciliarNFe.model_validate(e))
        assert env.ok and env.data is not None
        docs += I.documentos_do_resultado("conciliar_nfe", env.data)
    if "conciliar_gta" in ent:
        e = dict(
            ent["conciliar_gta"],
            caminhos=[str(dcaso / x) for x in ent["conciliar_gta"]["caminhos"]],
            nfe_caminhos=[str(dcaso / x) for x in ent["conciliar_gta"]["nfe_caminhos"]],
        )
        env = T.conciliar_gta(T.EntradaConciliarGTA.model_validate(e))
        assert env.ok and env.data is not None
        docs += I.documentos_do_resultado("conciliar_gta", env.data)
    return I.IndiceDocumentos(indice).registrar_documentos(docs, pre["operacao"], pre["fiscalizacao"])


def roteiro(caso: dict[str, Any], dcaso: Path, dtrab: Path) -> list:
    """Abertura, declaração de independência, NF-e, GTAs, vídeo (se houver) e pedido de laudo."""
    from laudo.agent.condutor import NovaEvidencia  # noqa: F401 - garante o import do condutor

    H = _harness()
    d = date.fromisoformat(caso["data_fiscalizacao"])

    def em(h: int, m: int = 0) -> datetime:
        return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)

    turnos = [
        H.Turno(
            "abertura",
            f"Bom dia. Vou iniciar a fiscalização da operação {caso['operacao']['ref_bacen']}.",
            agora=em(7, 30),
        )
    ]
    txt = "Declaro que não presto assistência técnica ao produtor nem a empresa dele."
    turnos.append(
        H.Turno(
            "declaracao",
            txt,
            agora=em(7, 35),
            evidencia={
                "tipo": "declaracao",
                "conteudo_texto": txt,
                "recebida_em": em(7, 35),
                "meta": {"assunto": "independencia_fiscal", "conflito": False},
            },
        )
    )
    for k, nf in enumerate(caso["documentos"]["nfe"], 1):
        turnos.append(
            H.Turno(
                "upload",
                "Segue o XML da nota fiscal da compra dos animais.",
                agora=em(7, 40 + k),
                evidencia={
                    "tipo": "nfe_xml",
                    "caminho": str(dcaso / nf["arquivo"]),
                    "item_id": "bov1",
                    "recebida_em": em(7, 40 + k),
                },
            )
        )
    for k, g in enumerate(caso["documentos"]["gta"], 1):
        turnos.append(
            H.Turno(
                "upload",
                f"Segue a GTA {k} do transporte dos animais.",
                agora=em(8, k),
                evidencia={
                    "tipo": "gta",
                    "caminho": str(dcaso / g["arquivo_json"]),
                    "item_id": "bov1",
                    "recebida_em": em(8, k),
                },
            )
        )
    if caso.get("video"):
        arq = dtrab / "curral.mp4"
        arq.write_bytes(f"{caso['video']['ref']}\n".encode())
        turnos.append(
            H.Turno(
                "upload",
                "Estou no curral, vou filmar o lote passando pelo corredor.",
                agora=em(10, 5),
                evidencia={
                    "tipo": "video",
                    "caminho": str(arq),
                    "item_id": "bov1",
                    "capturada_em": em(10),
                    "recebida_em": em(10, 5),
                },
            )
        )
    turnos.append(H.Turno("emissao", "Terminei a coleta. Pode gerar o rascunho do laudo?", agora=em(11, 30)))
    return turnos


def campos_finos(fis) -> dict[str, str]:
    """Status sugerido por campo das conciliações que valem no fim (sem as checagens substituídas pela
    reconciliação cumulativa: a GTA 1 sozinha é carga parcial, as quatro juntas cobrem o lote)."""
    from laudo.docs_fiscais.comum import STATUS_CAMPO

    H = _harness()
    substituidas = {s for ch in fis.checagens for s in (ch.resultado.get("substitui") or [])}
    saida: dict[str, list[str]] = {}
    for chk in fis.checagens:
        if (
            chk.ferramenta not in ("conciliar_nfe", "conciliar_gta")
            or chk.status == "erro"
            or chk.id in substituidas
        ):
            continue
        for campo, c in (chk.resultado.get("campos") or {}).items():
            saida.setdefault(campo, []).append(
                c.get("status_campo_sugerido") or STATUS_CAMPO.get(c.get("status"), "pendente")
            )
    return {k: H.pior(v) for k, v in saida.items()}


def rodar(
    caso: dict[str, Any],
    dcaso: Path,
    trabalho: Path,
    indice: Path | None = None,
    selar: bool = False,
) -> dict[str, Any]:
    """Roda um caso no modo determinístico e devolve status por campo do laudo, campos finos e emissão.

    `indice`: índice de documentos compartilhado (padrão: um por caso, em `trabalho/<id>/indices/`). `selar`:
    no fim, registra no índice os documentos das conciliações finais, como a selagem do laudo faria
    (`indice.registrar_fiscalizacao`); serve para simular a refiscalização da mesma operação."""
    from laudo.agent import estado as est
    from laudo.agent.condutor import Condutor
    from laudo.docs_fiscais import indice as I

    H = _harness()
    dtrab = trabalho / caso["id"]
    if dtrab.exists():
        shutil.rmtree(dtrab)
    dtrab.mkdir(parents=True)
    indice = indice or dtrab / "indices" / "documentos.jsonl"
    with _estado_global(f"pub:{caso['id']}", dtrab / "traces"):
        semear_indice(caso, dcaso, indice)
        reg = registro_do_caso(caso, indice, caso["operacao"]["ref_bacen"])
        hoje = date.fromisoformat(caso["data_fiscalizacao"])
        cond = Condutor(
            None, repo=est.RepositorioFiscalizacoes(dtrab / "fiscalizacoes"), registro=reg, hoje=hoje
        )
        op = dict(caso["operacao"])
        op["codigo_estabelecimento"] = caso["projeto"]["propriedade"]["codigo_estabelecimento"]
        op["tomador_ref"] = f"sha256:{caso['tomador']['documento_sha256']}"
        fis = cond.abrir(Operacao.model_validate(op), data_referencia=hoje, data_fiscalizacao=hoje)
        turnos = [H.executar_turno(cond, fis.id, t) for t in roteiro(caso, dcaso, dtrab)]
        fim = H.estado_final(cond, fis.id)
        finos = campos_finos(fim["fis"])
        selados = I.registrar_fiscalizacao(indice, fim["fis"]) if selar else 0
    return {
        "selados_no_indice": selados,
        "id": caso["id"],
        "campos": {k: v["status"] for k, v in fim["campos"].items()},
        "motivos": {k: v["motivo"] for k, v in fim["campos"].items()},
        "finos": finos,
        "emissao_permitida": fim["emissao_permitida"],
        "pendencias": fim["pendencias"],
        "ocorrencias": fim["ocorrencias"],
        "etapa": fim["etapa"],
        "acoes": [a["acao"] for t in turnos for a in t["acoes"]],
    }


def conferir(caso: dict[str, Any], r: dict[str, Any]) -> list[str]:
    """Diferenças entre o esperado do caso e o resultado da execução (vazio = confere)."""
    esp = caso["esperado"]
    erros = [
        f"{campo}: esperado {st}, sistema {r['campos'].get(campo, 'ausente')}"
        for campo, st in esp["laudo"].items()
        if r["campos"].get(campo) != st
    ]
    erros += [
        f"{campo} (fino): esperado {st}, sistema {r['finos'].get(campo, 'ausente')}"
        for campo, st in esp.get("finos", {}).items()
        if r["finos"].get(campo) != st
    ]
    erros += [f"{campo}: deveria não existir" for campo in esp.get("ausentes", []) if campo in r["campos"]]
    return erros


def carregar(dir_casos: Path = DIR_PUBLICOS) -> list[tuple[dict[str, Any], Path]]:
    meta = yaml.safe_load((dir_casos / "SPLIT.yaml").read_text(encoding="utf-8"))
    return [
        (yaml.safe_load((dir_casos / x["id"] / "caso.yaml").read_text(encoding="utf-8")), dir_casos / x["id"])
        for x in meta["casos"]
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--gerar", action="store_true", help="regrava casos_publicos/ e casos_publicos/dev_custeio/"
    )
    ap.add_argument("--rodar", action="store_true", help="roda os casos no modo determinístico")
    ap.add_argument("--custeio", action="store_true", help="roda os 4 casos de dev do perfil custeio")
    ap.add_argument("--saida", type=Path, default=None, help="diretório dos casos (padrão: o versionado)")
    ap.add_argument("--trabalho", type=Path, default=_REPO / "dados_locais" / "eval" / "casos_publicos")
    a = ap.parse_args(argv)
    if a.gerar:
        for casos, destino in ((PUBLICOS, a.saida or DIR_PUBLICOS), (CUSTEIO_DEV, DIR_CUSTEIO)):
            if a.saida and casos is CUSTEIO_DEV:
                destino = a.saida / "dev_custeio"
            meta = gerar(casos, destino)
            print(f"{len(casos)} casos em {destino} (sha256_conteudo {meta['sha256_conteudo'][:12]})")
    saida = a.saida or DIR_PUBLICOS
    if a.custeio:
        saida = saida / "dev_custeio"
    falhas = 0
    if a.rodar:
        for caso, dcaso in carregar(saida):
            r = rodar(caso, dcaso, a.trabalho)
            erros = conferir(caso, r)
            falhas += bool(erros)
            print(
                f"{caso['id']}: {'confere' if not erros else 'DIFERE'} | "
                + ", ".join(
                    f"{k.split(':', 2)[-1]}={v}"
                    for k, v in sorted(r["campos"].items())
                    if k.startswith("item:")
                )
                + (f" | {'; '.join(erros)}" if erros else "")
            )
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
