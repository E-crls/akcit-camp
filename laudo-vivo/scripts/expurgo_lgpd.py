"""Retenção e expurgo LGPD por crypto-shredding (chave por fiscalização; ver `src/laudo/audit/cofre.py`).

Subcomandos (a partir da raiz do repositório):
  scripts/py.sh scripts/expurgo_lgpd.py cifrar <fis_id>       # cifra os brutos com dado pessoal
  scripts/py.sh scripts/expurgo_lgpd.py situacao <fis_id>     # chave, brutos em claro e cifrados, cadeia
  scripts/py.sh scripts/expurgo_lgpd.py expurgar <fis_id> --motivo "pedido do titular"
  scripts/py.sh scripts/expurgo_lgpd.py vencidos [--dias 90] [--executar]   # seladas há mais de N dias

`cifrar` só toca arquivos dentro do diretório de dados (`LAUDO_DADOS_DIR` ou `dados_locais/`); arquivos do
repositório (casos sintéticos em `eval/`) nunca são cifrados nem apagados. O estado da fiscalização (JSON
append-only com a cadeia de hash) não muda: a cadeia continua íntegra depois do expurgo.

`expurgar` e `vencidos --executar`: **antes** de apagar a chave, cifram com ela todo bruto ainda em
claro (evidências com arquivo no diretório de dados, uploads em `evidencias/<fis_id>/`, áudio e a conversa);
bruto que não dá para cifrar (chave já expurgada) é apagado. Depois conferem de novo: se sobrar arquivo em
claro, o comando falha (código 3), lista os arquivos e **não** apaga a chave. Evidência cujo arquivo está
fora do diretório de dados e do repositório (a CLI aceita caminho qualquer) não é do sistema: não é cifrada
nem apagada, mas sai um AVISO com a lista e a contagem `fora_dos_dados` no registro.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from laudo.agent import estado as est
from laudo.audit import cofre as cf
from laudo.audit import hashchain

REPO = Path(__file__).resolve().parents[1]
TIPOS_PESSOAIS = {"audio", "video", "foto", "quadro_chave", "nfe_xml", "gta", "documento"}
RC_SOBROU_EM_CLARO = 3


def _dentro(p: Path, base: Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _cifrado(p: Path) -> bool:
    return p.name.endswith(cf.SUFIXO) or p.name.endswith(cf.SUFIXO + ".tmp")


def arquivos_pessoais(fis, dados: Path, fis_id: str | None = None) -> list[tuple[str, Path]]:
    """(evidência ou rótulo, caminho) dos brutos em claro da fiscalização que estão no diretório de dados:
    arquivos das evidências, tudo o que a interface gravou em `evidencias/<fis_id>/` e `audio/<fis_id>/`
    (inclusive upload que não virou evidência) e a conversa. `fis` pode ser None (estado apagado): valem as
    pastas da fiscalização."""
    fis_id = fis_id or fis.id
    saida: list[tuple[str, Path]] = []
    for ev in fis.evidencias if fis is not None else []:
        if ev.tipo in TIPOS_PESSOAIS and ev.caminho and not ev.meta.get("laudo"):
            p = Path(ev.caminho)
            if p.is_file() and _dentro(p, dados):
                saida.append((ev.id, p))
    for rotulo in ("evidencias", "audio"):
        pasta = dados / rotulo / fis_id
        if pasta.is_dir():
            saida += [(rotulo, p) for p in sorted(pasta.rglob("*")) if p.is_file()]
    conversa = dados / "fiscalizacoes" / f"{fis_id}.conversa.jsonl"
    if conversa.is_file():
        saida.append(("conversa", conversa))
    vistos, unicos = set(), []
    for rot, p in saida:
        if p.resolve() not in vistos and not _cifrado(p):
            vistos.add(p.resolve())
            unicos.append((rot, p))
    return unicos


def fora_dos_dados(fis, dados: Path) -> list[str]:
    """Arquivos de evidência com dado pessoal que existem fora do diretório de dados e fora do repositório (a
    CLI aceita caminho qualquer): o expurgo não cifra nem apaga arquivo que o sistema não criou, mas avisa
    que eles continuam legíveis. Arquivos do repositório são casos sintéticos e não entram."""
    saida = []
    for ev in fis.evidencias if fis is not None else []:
        if ev.tipo in TIPOS_PESSOAIS and ev.caminho and not ev.meta.get("laudo"):
            p = Path(ev.caminho)
            if p.is_file() and not _dentro(p, dados) and not _dentro(p, REPO):
                saida.append(str(p))
    return sorted(set(saida))


def _avisar_fora(fis_id: str, fora: list[str]) -> None:
    if fora:
        print(f"AVISO: {fis_id}: {len(fora)} arquivo(s) de evidência fora do diretório de dados continuam "
              "legíveis (não são do sistema; apague-os ou cifre-os à parte):", file=sys.stderr)
        for p in fora:
            print(f"  {p}", file=sys.stderr)


def _carregar(fis_id: str, dados: Path):
    repo = est.RepositorioFiscalizacoes(dados)
    return repo.carregar(fis_id) if repo.existe(fis_id) else None


def proteger_brutos(fis_id: str, dados: Path, cofre: cf.Cofre, apagar_sem_chave: bool = True) -> dict:
    """Cifra com a chave da fiscalização todo bruto em claro; sem chave (já expurgada), apaga o arquivo (se
    `apagar_sem_chave`). Devolve o que foi cifrado, apagado e o que **sobrou em claro** (conferido de
    novo)."""
    fis = _carregar(fis_id, dados)
    manifesto = dados / "fiscalizacoes" / f"{fis_id}.cofre.jsonl"
    manifesto.parent.mkdir(parents=True, exist_ok=True)
    cifrados, apagados, falhas = [], [], []
    with open(manifesto, "a", encoding="utf-8") as f:
        for rot, p in arquivos_pessoais(fis, dados, fis_id):
            try:
                destino = cofre.cifrar_arquivo(fis_id, p)
                cifrados.append(str(p))
                linha = {"ref": rot, "original": str(p), "cifrado": str(destino)}
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
            except cf.ChaveExpurgada:
                if not apagar_sem_chave:
                    falhas.append(f"{p}: chave expurgada, não dá para cifrar")
                    continue
                try:
                    p.unlink()
                    apagados.append(str(p))
                    f.write(json.dumps({"ref": rot, "original": str(p), "apagado": True}, ensure_ascii=False)
                            + "\n")
                except OSError as e:
                    falhas.append(f"{p}: {type(e).__name__}: {e}")
            except OSError as e:  # arquivo aberto por outro processo, sem permissão...
                falhas.append(f"{p}: {type(e).__name__}: {e}")
    restantes = [str(p) for _, p in arquivos_pessoais(_carregar(fis_id, dados), dados, fis_id)]
    return {"cifrados": cifrados, "apagados": apagados, "falhas": falhas, "em_claro": restantes,
            "fora_dos_dados": fora_dos_dados(fis, dados)}


def _falhou(fis_id: str, prot: dict) -> int:
    print(f"ERRO: {fis_id}: {len(prot['em_claro'])} arquivo(s) com dado pessoal ainda em claro; a chave NÃO "
          "foi apagada (o expurgo não vale enquanto houver bruto legível):", file=sys.stderr)
    for p in prot["em_claro"]:
        print(f"  {p}", file=sys.stderr)
    for x in prot["falhas"]:
        print(f"  falha: {x}", file=sys.stderr)
    return RC_SOBROU_EM_CLARO


def cmd_cifrar(fis_id: str, dados: Path, cofre: cf.Cofre) -> int:
    prot = proteger_brutos(fis_id, dados, cofre, apagar_sem_chave=False)
    manifesto = dados / "fiscalizacoes" / f"{fis_id}.cofre.jsonl"
    print(f"{len(prot['cifrados'])} arquivo(s) cifrado(s) com a chave de {fis_id}; manifesto em {manifesto}")
    if prot["em_claro"]:
        return _falhou(fis_id, prot)
    return 0


def cmd_situacao(fis_id: str, dados: Path, cofre: cf.Cofre) -> int:
    fis = est.RepositorioFiscalizacoes(dados).carregar(fis_id)
    cadeia = hashchain.verificar_cadeia(fis.evidencias)
    cifrados = sorted(dados.rglob(f"*{cf.SUFIXO}"))
    meus = []
    for p in cifrados:
        try:
            cofre.decifrar_arquivo(fis_id, p)
            meus.append((p, "legível com a chave"))
        except cf.ChaveExpurgada:
            meus.append((p, "ilegível (chave expurgada)"))
        except cf.ErroIntegridade:
            continue  # de outra fiscalização
    em_claro = arquivos_pessoais(fis, dados)
    print(f"fiscalização {fis_id}: etapa {fis.estado_fsm}; selo em {cf.data_do_selo(fis) or '—'}")
    print(
        f"chave: {'presente' if cofre.tem_chave(fis_id) else 'AUSENTE'}; expurgada: {cofre.expurgado(fis_id)}"
    )
    print(
        f"cadeia de hash: {'íntegra' if cadeia.integra else 'QUEBRADA'} "
        f"({cadeia.n} evidências, raiz {cadeia.raiz[:16]}…)"
    )
    print(f"brutos em claro: {len(em_claro)}")
    for _, p in em_claro:
        print(f"  {p}: EM CLARO")
    for p, st in meus:
        print(f"  {p}: {st}")
    return 0


def cmd_expurgar(fis_id: str, motivo: str, dados: Path, cofre: cf.Cofre) -> int:
    prot = proteger_brutos(fis_id, dados, cofre)
    if prot["em_claro"]:
        return _falhou(fis_id, prot)
    reg = cofre.expurgar(fis_id, motivo)
    reg.update(brutos_cifrados=len(prot["cifrados"]), brutos_apagados=len(prot["apagados"]),
               brutos_em_claro=0, fora_dos_dados=len(prot["fora_dos_dados"]))
    _avisar_fora(fis_id, prot["fora_dos_dados"])
    print(json.dumps(reg, ensure_ascii=False))
    return 0


def cmd_vencidos(dias: int, executar: bool, dados: Path, cofre: cf.Cofre) -> int:
    repo = est.RepositorioFiscalizacoes(dados)
    fis = {i: repo.carregar(i) for i in repo.listar()}
    hoje = datetime.now().astimezone().date()
    # vencida com chave (dado cifrado legível) ou com bruto em claro (nunca cifrado): as duas precisam do
    # expurgo
    alvo = [i for i in cf.vencidas(list(fis.values()), hoje, dias)
            if cofre.tem_chave(i) or arquivos_pessoais(fis[i], dados)]
    rc = 0
    for i in alvo:
        if not executar:
            n = len(arquivos_pessoais(fis[i], dados))
            print(f"vencida (use --executar para expurgar): {i}" + (f" ({n} bruto(s) em claro)" if n else ""))
            continue
        prot = proteger_brutos(i, dados, cofre)
        if prot["em_claro"]:
            rc = _falhou(i, prot)
            continue
        cofre.expurgar(i, f"retenção vencida ({dias} dias após o selo)")
        _avisar_fora(i, prot["fora_dos_dados"])
        print(f"expurgada: {i} ({len(prot['cifrados'])} bruto(s) cifrado(s), "
              f"{len(prot['apagados'])} apagado(s))")
    if not alvo:
        print("nenhuma fiscalização com retenção vencida e chave presente ou bruto em claro")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retenção e expurgo LGPD (crypto-shredding por fiscalização).")
    ap.add_argument("--dados", type=Path, default=None, help="diretório de dados (padrão: LAUDO_DADOS_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nome in ("cifrar", "situacao"):
        sub.add_parser(nome).add_argument("fis_id")
    e = sub.add_parser("expurgar")
    e.add_argument("fis_id")
    e.add_argument("--motivo", required=True)
    v = sub.add_parser("vencidos")
    v.add_argument("--dias", type=int, default=cf.RETENCAO_BRUTOS_DIAS)
    v.add_argument("--executar", action="store_true")
    a = ap.parse_args(argv)
    dados = a.dados or est.diretorio_dados()
    cofre = cf.Cofre(dados / "chaves")
    if a.cmd == "cifrar":
        return cmd_cifrar(a.fis_id, dados, cofre)
    if a.cmd == "situacao":
        return cmd_situacao(a.fis_id, dados, cofre)
    if a.cmd == "expurgar":
        return cmd_expurgar(a.fis_id, a.motivo, dados, cofre)
    return cmd_vencidos(a.dias, a.executar, dados, cofre)


if __name__ == "__main__":
    raise SystemExit(main())
