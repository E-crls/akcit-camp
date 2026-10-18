"""Baixa e recorta para Goiás os microdados do Sicor (BCB) de 2026, em streaming.

Uso (da raiz do repositório):
    scripts/py.sh scripts/dados_sicor.py [--ano 2026] [--uf GO] [--complemento]

Saída em `dados_locais/sicor/` (ignorado pelo git):
    operacoes_go_2026.parquet   uma linha por (REF_BACEN, NU_ORDEM) de GO, todas as colunas públicas
    glebas_go_2026.parquet      polígonos (WKT, WGS84) das glebas dessas operações
    tabelas/*.parquet           tabelas de domínio (empreendimento, categoria, programa, fonte, IFs)
    municipio_operacao_go_2026.parquet  (só com --complemento) REF_BACEN, NU_ORDEM, CD_IBGE_MUNICIPIO
    fontes.json                 URL, Last-Modified, bytes transferidos e sha256 de cada arquivo

Nada é carregado inteiro na memória: o gzip é lido em blocos de 1 MB, linha a linha, e só as
linhas de GO ficam. O bruto não é gravado em disco.

Fontes (BCB, "Tabelas e Microdados do Crédito Rural e do Proagro",
https://www.bcb.gov.br/estabilidadefinanceira/tabelas-credito-rural-proagro):
    https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2026.gz  (~46 MB)
    https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_GLEBAS_WKT_2026.gz              (~117 MB)
    https://www.bcb.gov.br/htms/sicor/Empreendimento.csv (+ CategoriaEmitente, Programa,
        FonteRecursos, DadosBrutos/SICOR_LISTA_IFS.csv)
    Dicionário: https://www.bcb.gov.br/htms/sicor/manualDadosSicorCompleto.pdf

Dicionário dos campos usados (descrições do manual do BCB; `REF_BACEN` é mascarado na origem):
    sicor_operacao_basica_estado
        REF_BACEN            Número do refbacen mascarado (chave da operação)
        NU_ORDEM             Número de ordem (cada ordem é um empreendimento/item da cédula)
        CNPJ_IF              Concedente do crédito (raiz do CNPJ da IF; 00000000 = Banco do Brasil)
        DT_EMISSAO           Data de emissão da operação (dd/mm/aaaa)
        DT_VENCIMENTO        Data de vencimento da operação
        CD_CATEG_EMITENTE    Categoria do emitente (2222 pequeno, 3333 médio, 4444 grande produtor)
        CD_FONTE_RECURSO     Código da fonte de recursos
        CD_ESTADO            Unidade da federação (filtro do recorte)
        CD_EMPREENDIMENTO    Código do empreendimento (decodificado por Empreendimento.csv)
        CD_PROGRAMA          Código do programa/linha (Programa.csv)
        CD_FASE_CICLO_PRODUCAO  Fase do ciclo de produção (FaseCicloProducao.csv; 60 = engorda em
                             confinamento, 57 = recria e engorda, 51 = cria)
        VL_QUANTIDADE        Quantidade (para animais: cabeças ou UA de 450 kg, conforme a
                             UNIDADE_MEDIDA do empreendimento)
        VL_PARC_CREDITO      Valor da parcela de crédito (R$)
        VL_REC_PROPRIO       Valor do recurso próprio (R$)
        VL_AREA_INFORMADA    Área do empreendimento informada (ha)
        VL_AREA_FINANC       VL_AREA_INFORMADA * VL_PARC_CREDITO / (VL_PARC_CREDITO + VL_REC_PROPRIO)
        DT_INIC_PLANTIO ...  Datas de plantio e colheita (lavoura)
        CD_CNPJ_CADASTRANTE  IF cadastrante (identifica o sistema cooperativo: 02038232 Sicoob,
                             01181521 Sicredi, 01401771 Cresol)
        PC_BONUS_CAR         Percentual de bônus do CAR
        CNPJ_AGENTE_INVEST   Concedente da operação de investimento (instituição, não o tomador)
    sicor_glebas_wkt
        REF_BACEN, NU_ORDEM, NU_INDICE (identificador da gleba), GT_GEOMETRIA (polígono WKT)
    Empreendimento.csv
        CODIGO, FINALIDADE, ATIVIDADE, MODALIDADE, PRODUTO, VARIEDADE, UNIDADE_MEDIDA, ...

Não há CPF/CNPJ nem nome do tomador nesses arquivos. Ligação com o CAR: existe no arquivo
`SICOR_PROPRIEDADES.gz` (campos REF_BACEN, NU_ORDEM, CD_CNPJ_CPF, CD_SNCR, CD_NIRF, CD_CAR; 493 MB,
contém CPF/CNPJ do proprietário). Não é baixado aqui. O município da operação existe em
`SICOR_COMPLEMENTO_OPERACAO_BASICA.gz` (CD_IBGE_MUNICIPIO; 449 MB, também traz agência, número
da cédula e refbacen explícito); com `--complemento` o script lê esse arquivo em streaming e grava
só REF_BACEN, NU_ORDEM e CD_IBGE_MUNICIPIO. Sem a opção, o município é inferido pelo polígono
(ver bench/fiscal_go/build.py). Arquivos acima de 200 MB exigem combinar com o coordenador.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.geo.fontes import InfoDownload, baixar_bytes, blocos, gunzip, linhas

BCB = "https://www.bcb.gov.br/htms/sicor"
SAIDA = RAIZ / "dados_locais" / "sicor"

TABELAS = {
    "empreendimento": f"{BCB}/Empreendimento.csv",
    "categoria_emitente": f"{BCB}/CategoriaEmitente.csv",
    "programa": f"{BCB}/Programa.csv",
    "fonte_recursos": f"{BCB}/FonteRecursos.csv",
    "lista_ifs": f"{BCB}/DadosBrutos/SICOR_LISTA_IFS.csv",
    "fase_ciclo_producao": f"{BCB}/FaseCicloProducao.csv",
}

COLS_DATA = ["DT_EMISSAO", "DT_VENCIMENTO", "DT_FIM_COLHEITA", "DT_FIM_PLANTIO", "DT_INIC_COLHEITA",
             "DT_INIC_PLANTIO"]


def _cabecalho(linha: str) -> list[str]:
    return [c.strip().lstrip("#") for c in linha.split(";")]


def baixar_operacoes(ano: int, uf: str) -> tuple[pd.DataFrame, InfoDownload]:
    url = f"{BCB}/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_{ano}.gz"
    info = InfoDownload(url=url)
    it = linhas(gunzip(blocos(url, info)))
    cab = _cabecalho(next(it))
    i_uf = cab.index("CD_ESTADO")
    mantidas: list[str] = []
    for ln in it:
        info.linhas_lidas += 1
        partes = ln.split(";")
        if len(partes) > i_uf and partes[i_uf] == uf:
            mantidas.append(ln)
    info.linhas_mantidas = len(mantidas)
    df = pd.read_csv(io.StringIO("\n".join(mantidas)), sep=";", header=None, names=cab, dtype=str,
                     keep_default_na=False)
    df = df.replace({"": None})
    for c in cab:
        if c.startswith(("VL_", "PC_")):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in COLS_DATA:
        if c in df:
            df[c] = pd.to_datetime(df[c], format="%d/%m/%Y", errors="coerce")
    df["NU_ORDEM"] = df["NU_ORDEM"].astype(int)
    return df, info


def baixar_glebas(ano: int, refs: set[str]) -> tuple[pd.DataFrame, InfoDownload]:
    url = f"{BCB}/DadosBrutos/SICOR_GLEBAS_WKT_{ano}.gz"
    info = InfoDownload(url=url)
    it = linhas(gunzip(blocos(url, info)))
    cab = _cabecalho(next(it))
    assert cab[:4] == ["REF_BACEN", "NU_ORDEM", "NU_INDICE", "GT_GEOMETRIA"], cab
    reg = []
    for ln in it:
        info.linhas_lidas += 1
        p = ln.split(";", 3)
        if p[0] in refs:
            reg.append((p[0], int(p[1]), int(p[2]), p[3]))
    info.linhas_mantidas = len(reg)
    df = pd.DataFrame(reg, columns=["REF_BACEN", "NU_ORDEM", "NU_INDICE", "WKT"])
    return df, info


def baixar_complemento(refs: set[str]) -> tuple[pd.DataFrame, InfoDownload]:
    """Município IBGE por operação (arquivo de 449 MB; só com --complemento)."""
    url = f"{BCB}/DadosBrutos/SICOR_COMPLEMENTO_OPERACAO_BASICA.gz"
    info = InfoDownload(url=url)
    it = linhas(gunzip(blocos(url, info)))
    cab = _cabecalho(next(it))
    i_ref, i_ord, i_mun = cab.index("REF_BACEN"), cab.index("NU_ORDEM"), cab.index("CD_IBGE_MUNICIPIO")
    reg = []
    for ln in it:
        info.linhas_lidas += 1
        p = ln.split(";")
        if p[i_ref] in refs:
            # só as três colunas; agência, número da cédula e refbacen explícito são descartados
            reg.append((p[i_ref], int(p[i_ord]), p[i_mun]))
    info.linhas_mantidas = len(reg)
    return pd.DataFrame(reg, columns=["REF_BACEN", "NU_ORDEM", "CD_IBGE_MUNICIPIO"]), info


def baixar_tabela(nome: str, url: str) -> tuple[pd.DataFrame, InfoDownload]:
    info = InfoDownload(url=url)
    bruto = baixar_bytes(url, info)
    df = pd.read_csv(io.BytesIO(bruto), sep=";", dtype=str, encoding="latin-1", keep_default_na=False)
    df.columns = [c.strip().lstrip("#") for c in df.columns]
    df = df.replace({"": None})
    info.linhas_mantidas = len(df)
    return df, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ano", type=int, default=2026)
    ap.add_argument("--uf", default="GO")
    ap.add_argument("--complemento", action="store_true",
                    help="lê SICOR_COMPLEMENTO_OPERACAO_BASICA.gz (449 MB) para o município IBGE")
    args = ap.parse_args()
    uf = args.uf.upper()
    sufixo = f"{uf.lower()}_{args.ano}"
    (SAIDA / "tabelas").mkdir(parents=True, exist_ok=True)
    fontes: dict[str, dict] = {}

    for nome, url in TABELAS.items():
        t = time.perf_counter()
        df, info = baixar_tabela(nome, url)
        df.to_parquet(SAIDA / "tabelas" / f"{nome}.parquet", index=False)
        fontes[nome] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
        print(f"tabela {nome}: {len(df)} linhas")

    t = time.perf_counter()
    ops, info = baixar_operacoes(args.ano, uf)
    ops.to_parquet(SAIDA / f"operacoes_{sufixo}.parquet", index=False, compression="zstd")
    fontes["operacoes"] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
    print(f"operações {uf} {args.ano}: {len(ops)} linhas, {ops.REF_BACEN.nunique()} REF_BACEN "
          f"({info.bytes_transferidos / 1e6:.1f} MB em {time.perf_counter() - t:.0f} s)")

    refs = set(ops["REF_BACEN"])
    t = time.perf_counter()
    gl, info = baixar_glebas(args.ano, refs)
    gl.to_parquet(SAIDA / f"glebas_{sufixo}.parquet", index=False, compression="zstd")
    fontes["glebas"] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
    print(f"glebas: {len(gl)} de {gl.REF_BACEN.nunique()} operações "
          f"({info.bytes_transferidos / 1e6:.1f} MB em {time.perf_counter() - t:.0f} s)")

    if args.complemento:
        t = time.perf_counter()
        comp, info = baixar_complemento(refs)
        comp.to_parquet(SAIDA / f"municipio_operacao_{sufixo}.parquet", index=False)
        fontes["complemento"] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
        print(f"complemento: {len(comp)} linhas com município")

    fontes["_gerado_em"] = {"quando": datetime.now(UTC).astimezone().isoformat(timespec="seconds"), "ano": args.ano,
                            "uf": uf}
    (SAIDA / "fontes.json").write_text(json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
