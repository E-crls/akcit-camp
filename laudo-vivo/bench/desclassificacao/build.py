"""Monta o Observatório de desclassificações a partir dos microdados públicos do Sicor (BCB), em streaming.

Uso (da raiz do repositório; ~1 GB transferido, ~8 min, < 1 GB de RAM):
    scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta temporária> \
        [--snapshot-anterior <desc.csv de 07/10/2026>] [--sem-glebas] [--anos 2013-2026]

Lê, sem gravar o bruto:
    DadosBrutos/sicor_desclassificacao.gz            (~0,2 MB)  todas as desclassificações publicadas
    DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_<ano>.gz (13 a 68 MB cada, 2013 a 2026) atributos e denominadores
    DadosBrutos/SICOR_GLEBAS_WKT_<ano>.gz (2022 a 2024; ~250 MB cada; só fica GO) glebas do retro-teste
    Empreendimento.csv, MotivoDesclassificacao.csv e as tabelas de domínio do retro-teste

Grava em `bench/desclassificacao/`:
    desclassificacoes.parquet  um registro de desclassificação por linha, com os atributos da operação
                               (UF, empreendimento do 1º item, IF, ano do arquivo, valor) e a versão
                               (`na_versao_atual`; `no_snapshot_memorando`, a marca da versão de
                               07/10/2026, se houver snapshot)
    base_operacoes.parquet     denominadores: operações, itens e valor por ano, UF e empreendimento
    empreendimento.parquet     tabela de domínio usada (para recalcular sem rede)
    resumo.json                números do observatório, controles de honestidade e fontes (URL,
                               Last-Modified, bytes, sha256)
Grava em `--trabalho` (fora do repositório; apague ao fim): as linhas das operações da população do
retro-teste com as colunas de originação (`observatorio.CAMPOS_ORIGINACAO`), as glebas de GO e as tabelas.

`--snapshot-anterior` (ou `--snapshot-memorando`): uma cópia local da versão de 07/10/2026 do arquivo de
desclassificações, sem cabeçalho. O BCB republicou o arquivo em 14/10/2026; com o snapshot, cada registro
ganha a marca `no_snapshot_memorando` e o resumo traz também os números daquela versão
(`versoes.memorando_0710`). Sem a opção, as marcas de um `desclassificacoes.parquet` anterior são
preservadas.

Sem PII: o Sicor público não traz CPF/CNPJ nem nome do tomador; `REF_BACEN` já vem mascarado; `if_cnpj_base`
é a raiz do CNPJ da instituição financeira. Não usa `SICOR_PROPRIEDADES` (tem CPF/CNPJ).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(AQUI))

import numeros as N
import observatorio as O

from laudo.geo.fontes import InfoDownload, baixar_bytes, blocos, gunzip, linhas


def _info(info: InfoDownload, t0: float) -> dict:
    d = {
        k: info.como_dict()[k]
        for k in (
            "url",
            "last_modified",
            "bytes_transferidos",
            "sha256",
            "content_length",
            "via",
            "linhas_lidas",
            "linhas_mantidas",
        )
    }
    return d | {"segundos": round(time.perf_counter() - t0, 1)}


def _texto(url: str, fontes: dict, nome: str) -> list[str]:
    t0 = time.perf_counter()
    info = InfoDownload(url=url)
    bruto = baixar_bytes(url, info)
    txt = bruto.decode("latin-1").splitlines()
    info.linhas_lidas = len(txt)
    fontes[nome] = _info(info, t0)
    return txt


def baixar_desclassificacoes(fontes: dict) -> list[O.Desclassificacao]:
    t0 = time.perf_counter()
    info = InfoDownload(url=O.URL_DESC)
    regs = list(O.ler_desclassificacoes(linhas(gunzip(blocos(O.URL_DESC, info)))))
    info.linhas_lidas = info.linhas_mantidas = len(regs)
    fontes["desclassificacao"] = _info(info, t0)
    return regs


def snapshot_anterior(caminho: Path | None) -> set[tuple] | None:
    if caminho is not None:
        with open(caminho, encoding="latin-1") as f:
            return {d.chave for d in O.ler_desclassificacoes(f)}
    p = AQUI / "desclassificacoes.parquet"
    if not p.exists():
        return None
    ant = pd.read_parquet(p)
    if "no_snapshot_memorando" not in ant or ant["no_snapshot_memorando"].isna().all():
        return None
    ant = ant[ant["no_snapshot_memorando"].fillna(False).astype(bool)]
    return {
        (
            r.ref_bacen,
            int(r.nu_ordem),
            pd.Timestamp(r.dt_desc).date().isoformat(),
            r.cd_motivo,
            round(float(r.vl_desc) * 100),
            r.tipo_desc,
        )
        for r in ant.itertuples()
    }


def reconstruir(chaves: set[tuple]) -> list[O.Desclassificacao]:
    from datetime import date

    return [
        O.Desclassificacao(
            ref_bacen=k[0],
            nu_ordem=k[1],
            dt_desc=date.fromisoformat(k[2]),
            cd_motivo=k[3],
            vl_desc=k[4] / 100,
            tipo_desc=k[5],
        )
        for k in chaves
    ]


def gravar_gz(caminho: Path, cabecalho: str, conteudo: list[str]) -> None:
    with gzip.open(caminho, "wt", encoding="utf-8", compresslevel=5) as f:
        f.write(cabecalho + "\n")
        for ln in conteudo:
            f.write(ln + "\n")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # com -I o PYTHONUTF8 do py.sh é ignorado
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--trabalho",
        type=Path,
        required=True,
        help="pasta fora do repositório para o recorte do retro-teste (apague ao fim)",
    )
    ap.add_argument("--snapshot-anterior", "--snapshot-memorando", dest="snapshot_anterior", type=Path,
                    default=None, help="cópia local da versão de 07/10/2026 do arquivo de desclassificações")
    ap.add_argument(
        "--sem-glebas", action="store_true", help="não baixa as glebas de GO (retro-teste sem geo)"
    )
    ap.add_argument("--sem-retro", action="store_true", help="não extrai a população do retro-teste")
    ap.add_argument("--anos", default=f"{O.ANOS_OPERACOES[0]}-{O.ANOS_OPERACOES[-1]}")
    a = ap.parse_args()
    ini, _, fim = a.anos.partition("-")
    anos = list(range(int(ini), int(fim or ini) + 1))
    trab = a.trabalho.resolve()
    if trab.is_relative_to(RAIZ):
        raise SystemExit("--trabalho tem de ficar fora do repositório (o recorte é dado bruto)")
    (trab / "tabelas").mkdir(parents=True, exist_ok=True)
    t_ini = time.perf_counter()
    fontes: dict[str, dict] = {}

    # tabelas de domínio
    emp_txt = _texto(O.URL_EMPREENDIMENTO, fontes, "empreendimento")
    emp = O.ler_empreendimentos(emp_txt)
    motivos = O.ler_motivos(_texto(O.URL_MOTIVOS, fontes, "motivos"))
    pd.read_csv(io.StringIO("\n".join(emp_txt)), sep=";", dtype=str, keep_default_na=False).rename(
        columns=lambda c: c.strip().lstrip("#")
    ).replace({"": None}).to_parquet(AQUI / "empreendimento.parquet", index=False)
    if not a.sem_retro:
        for nome, url in O.TABELAS_RETRO.items():
            txt = emp_txt if nome == "empreendimento" else _texto(url, fontes, nome)
            df = pd.read_csv(io.StringIO("\n".join(txt)), sep=";", dtype=str, keep_default_na=False)
            df.columns = [c.strip().lstrip("#") for c in df.columns]
            df.replace({"": None}).to_parquet(trab / "tabelas" / f"{nome}.parquet", index=False)
    print(f"tabelas: {len(emp)} empreendimentos, {len(motivos)} motivos")

    # desclassificações (versão atual) e snapshot da versão de 07/10/2026
    atuais = baixar_desclassificacoes(fontes)
    snap = snapshot_anterior(a.snapshot_anterior)
    chaves_atuais = {d.chave for d in atuais}
    removidos = reconstruir(snap - chaves_atuais) if snap is not None else []
    todos = atuais + removidos
    refs = {d.ref_bacen for d in todos}
    print(
        f"desclassificações: {len(atuais)} registros ({len(refs)} operações); "
        f"snapshot: {'não' if snap is None else len(snap)}; removidos desde o snapshot: {len(removidos)}"
    )

    # operações, ano a ano
    juncao: dict[str, dict] = {}
    ano_de: dict[str, int] = {}
    repetidas = 0
    base_rows, area_rows, ops_por_ano = [], [], {}
    for ano in anos:
        t0 = time.perf_counter()
        info = InfoDownload(url=O.url_operacoes(ano))
        retro = (not a.sem_retro) and ano in O.ANOS_RETRO
        lt = O.LeitorOperacoes(ano=ano, refs=refs, empreendimentos=emp, extrair_retro=retro)
        lt.consumir(linhas(gunzip(blocos(info.url, info))))
        info.linhas_lidas = lt.linhas
        info.linhas_mantidas = len(lt.juncao)
        fontes[f"operacoes_{ano}"] = _info(info, t0) | {
            "operacoes": lt.operacoes,
            "fora_de_ordem": lt.fora_de_ordem,
        }
        ops_por_ano[ano] = lt.operacoes
        for ref, j in lt.juncao.items():
            if ref in juncao:
                repetidas += 1
                continue
            juncao[ref] = j
            ano_de[ref] = ano
        for (uf, cd), (n_ops, n_it, val) in lt.base.items():
            base_rows.append((ano, uf, cd, int(n_ops), int(n_it), round(val, 2)))
        for (escopo, faixa), n in lt.area.items():
            area_rows.append(
                {
                    "ano_operacao": ano,
                    "escopo": escopo,
                    "faixa_area": faixa,
                    "itens": int(n),
                    "valor_rs": round(lt.area_valor[(escopo, faixa)], 2),
                }
            )
        if retro:
            cab = ";".join(O.CAMPOS_ORIGINACAO)
            gravar_gz(trab / f"ops_compra_br_{ano}.csv.gz", cab, lt.retro_compra)
            gravar_gz(trab / f"ops_go_{ano}.csv.gz", cab, lt.retro_go)
            refs_go = {ln.split(";", 1)[0] for ln in lt.retro_go}
            print(
                f"  retro {ano}: {len(lt.retro_compra)} itens de operações com compra de gado (BR), "
                f"{len(lt.retro_go)} itens de GO ({len(refs_go)} operações)"
            )
            del lt
            if not a.sem_glebas:
                t1 = time.perf_counter()
                ig = InfoDownload(url=O.url_glebas(ano))
                gl, lidas = O.filtrar_glebas(linhas(gunzip(blocos(ig.url, ig))), refs_go)
                ig.linhas_lidas, ig.linhas_mantidas = lidas, len(gl)
                gravar_gz(trab / f"glebas_go_{ano}.csv.gz", "REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA", gl)
                fontes[f"glebas_{ano}"] = _info(ig, t1)
                print(f"  glebas {ano}: {len(gl)} de GO em {lidas} lidas ({time.perf_counter() - t1:.0f} s)")
                del gl
        print(
            f"operações {ano}: {fontes[f'operacoes_{ano}']['operacoes']} operações, "
            f"{fontes[f'operacoes_{ano}']['linhas_mantidas']} com desclassificação "
            f"({info.bytes_transferidos / 1e6:.1f} MB em {time.perf_counter() - t0:.0f} s)"
        )

    # tabelas derivadas
    linhas_desc = []
    for d in todos:
        r = O.enriquecer(d, juncao.get(d.ref_bacen), ano_de.get(d.ref_bacen), emp)
        r["na_versao_atual"] = d.chave in chaves_atuais
        r["no_snapshot_memorando"] = (d.chave in snap) if snap is not None else None
        linhas_desc.append(r)
    desc = pd.DataFrame(linhas_desc).sort_values(["dt_desc", "ref_bacen", "nu_ordem"]).reset_index(drop=True)
    desc["dt_desc"] = pd.to_datetime(desc["dt_desc"])
    base = pd.DataFrame(
        base_rows,
        columns=["ano_operacao", "uf", "cd_empreendimento", "n_operacoes", "n_itens", "valor_itens_rs"],
    )
    N.checar_pii(desc, "desclassificacoes")
    N.checar_pii(base, "base_operacoes")
    desc.to_parquet(AQUI / "desclassificacoes.parquet", index=False, compression="zstd")
    base.to_parquet(AQUI / "base_operacoes.parquet", index=False, compression="zstd")

    resumo = N.calcular(desc, base, pd.read_parquet(AQUI / "empreendimento.parquet"), motivos)
    resumo["area_animais"] = area_rows
    resumo["juncao"] = {
        "operacoes_desclassificadas": len(refs),
        "achadas": len(juncao),
        "sem_operacao": len(refs - set(juncao)),
        "repetidas_em_mais_de_um_ano": repetidas,
        "anos_lidos": anos,
        "operacoes_por_ano": ops_por_ano,
    }
    resumo["fontes"] = fontes
    resumo["gerado_em"] = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    (AQUI / "resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (trab / "fontes.json").write_text(json.dumps(fontes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resumo["versoes"]["atual"]["registros"], ensure_ascii=False))
    print(f"total {time.perf_counter() - t_ini:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
