"""Uma só fonte de números: `docs/entregaveis/numeros.json` e `numeros.md`, gerados dos relatórios de avaliação.

Pitch, Q&A, slide, BMC, README, roteiro da demo e relatório quinzenal citam os números entre marcadores, que o
GitHub não mostra:

    o sistema achou <!--n:recall_teste.falado-->9 de 9<!--/n--> defeitos

- sem opção: lê os relatórios de UMA versão (`eval/reports/<data>_*<sufixo>.json`, todos com o mesmo
  `sha256(src/)`; para se não forem), o custo medido no trace da demo (`eval/reports/<data>_custo_demo.json`) e
  a conferência de equivalência do código atual (`eval/reports/<data>_equivalencia<sufixo>.json`, se houver), e
  escreve `numeros.json` e `numeros.md`;
- `--aplicar`: também reescreve o que está entre os marcadores de cada texto;
- `--verificar`: não escreve nada; sai com código 1 se algum marcador não bater com o número da fonte, se usar
  chave que não existe, se o `eval/SLIDE.md` não for o que `eval/gerar_slide.py` produz dos mesmos relatórios,
  se o `numeros.json` estiver desatualizado, se um número antigo conhecido aparecer fora de marcador (`ANTIGOS`;
  a regra do congelamento depende de `congelado` no `SPLIT.yaml`), se um texto de palco citar a versão histórica
  das desclassificações, se o total de 2026 aparecer sem a data de corte ou se um número seletivo aparecer sem
  o seu par (`PARES_OBRIGATORIOS`: o A/B v2 do dev sem o do teste, o red-team da equipe sem o cego).

**Relatórios complementares da rodada final** (pós-r4, 16/10/2026): o A/B v2 no teste
(`<data>_ab_centralidade_v2<sufixo>_teste.json` → `ab2_teste.*`), o red-team cego nos dois modos
(`<data>_redteam_{agente,deterministico}<sufixo>_v3cego.json` → `redteam.cego_*`) e a repetição do agente no teste
(`<data>_agente<sufixo>_rep.json` → `agente_rep.*`), com o mesmo `sha256(src/)` dos principais. Depois da rodada,
se existirem a conferência de equivalência e a regressão sem LLM do v3
(`*_redteam_deterministico<sufixo>.1_v3regressao.json`), entram as chaves `r41.*` (rótulo "não cego"; nunca
substituem o cego). O p da fala por pares não está em relatório nenhum e não vira chave.

**Hash de `src/` num clone:** o git guarda `src/` com LF, e o `sha256(src/)` dos relatórios é o dos bytes do
Windows (CRLF). O `--verificar` aceita o código atual se ele bater com um dos dois (`versao.sha256_src` ou
`versao.sha256_src_lf`, que todo relatório da r4 grava) e mostra os dois.

**Versão de palco, num lugar só:** `eval/reports/palco.json` (rodada de avaliação citada no palco e versão do
arquivo de desclassificações). Sem `--data`/`--sufixo`, vale a de lá; ela só muda com `--aplicar --fixar-palco`
(passo final da r4, `eval/rodada_r4.py`). `--aplicar` com outra versão sem `--fixar-palco` é recusado, porque
deixaria os textos com uma rodada e o `--verificar` (CI) com outra.

**Desclassificações:** no palco vale a versão do arquivo oficial mais recente do BCB (`desc.*`, Last-Modified
14/10/2026), sempre com a data de corte (`desc.ate`, ou a variante `.com_data`); a versão de 07/10/2026 usada no
memorando (`desc.memorando.*`) é histórico e não entra nos textos de palco (`TEXTOS_PALCO`).

Uso (na raiz do repositório):
  scripts/py.sh scripts/gerar_numeros.py                  # só reescreve numeros.json e numeros.md
  scripts/py.sh scripts/gerar_numeros.py --aplicar        # depois de cada rodada de avaliação
  scripts/py.sh scripts/gerar_numeros.py --verificar      # no CI e antes de ensaiar o pitch
  scripts/py.sh scripts/gerar_numeros.py --data 2026-10-16 --sufixo _r4 --aplicar --fixar-palco   # fim da r4

Textos fora do repositório (`../negocio/`) entram quando existem (no CI não existem e são pulados).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, NamedTuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "src"))

import gerar_slide as GS
import metrics as M

PALCO = GS.palco()  # eval/reports/palco.json: a versão citada no palco (muda só com --fixar-palco)
DATA_PADRAO, SUFIXO_PADRAO = PALCO["rodada"]["data"], PALCO["rodada"]["sufixo"]
DESC_PALCO = PALCO["desclassificacao"]["palco"]  # "atual" = arquivo oficial mais recente (14/10/2026)
SAIDA = REPO / "docs" / "entregaveis"
SPLIT_YAML = REPO / "eval" / "golden" / "casos" / "SPLIT.yaml"
# Textos que vão para o palco ou para a banca: neles a versão histórica das desclassificações não entra.
TEXTOS_PALCO = (
    "docs/entregaveis/pitch-regional-3min.md",
    "docs/entregaveis/pitch-final-5min.md",
    "docs/entregaveis/qa-banca.md",
    "docs/entregaveis/bmc-v1.md",
    "docs/entregaveis/bmc-v1.html",
    "docs/entregaveis/deck/index.html",  # pós-r4: o deck é texto de palco
)
ALVOS = [
    "docs/entregaveis/pitch-regional-3min.md",
    "docs/entregaveis/pitch-final-5min.md",
    "docs/entregaveis/qa-banca.md",
    "docs/entregaveis/bmc-v1.md",
    "docs/entregaveis/bmc-v1.html",
    "docs/entregaveis/KIT_APRESENTADOR.md",
    "docs/entregaveis/deck/index.html",
    "docs/entregaveis/README.md",
    "README.md",
    "docs/fluxo_do_agente.md",
    "eval/README.md",
    "apps/web/ROTEIRO_DEMO.md",
    "../negocio/relatorio_quinzenal_2_rascunho.md",
    "../negocio/plano_de_negocio.md",
    "../negocio/inscricao.md",
    "../negocio/afirmacoes_proibidas.md",
    # absorvidos de scripts/desclassificacao_marcadores.py (81 marcadores desc.* e retro.*) e da onda 3
    "CHANGELOG.md",
    "eval/single_vs_multi.md",
    "bench/desclassificacao/README.md",
    "validacao/README.md",
    "eval/retroteste/README.md",
    "docs/decisao.md",  # pós-r4: tem marcadores desc.* e retro.*
]
RX_MARCADOR = re.compile(r"<!--n:([a-z0-9_.]+)-->(.*?)<!--/n-->", re.DOTALL)


class Par(NamedTuple):
    """Par obrigatório: um marcador cuja chave casa `gatilho` exige, na mesma unidade (o parágrafo; numa tabela, a
    linha da tabela), um marcador cuja chave casa `exige`. Linha com <!--historico--> passa."""

    gatilho: str
    exige: str
    motivo: str
    rotulo: str  # como o numeros.md mostra a regra


PARES_OBRIGATORIOS = [
    Par(r"^ab2\.(residual|formulario)", r"^ab2_teste\.",
        "número do A/B v2 do dev, o conjunto em que o A/B foi desenvolvido, sem o do teste congelado",
        "`ab2.residual*` e `ab2.formulario*` (dev) exigem um `ab2_teste.*`"),
    Par(r"^redteam\.ataques(\.|$)", r"^redteam\.cego_ataques(\.|$)",
        "red-team escrito pela equipe sem o resultado do conjunto cego",
        "`redteam.ataques` (equipe) exige `redteam.cego_ataques`"),
    Par(r"^r\d+1\.v3_regressao", r"^redteam\.cego_ataques(\.|$)",
        "regressão do v3 depois da correção (não cega) sem o resultado cego, que ela nunca substitui",
        "`r41.v3_regressao_*` (não cega) exige `redteam.cego_ataques`"),
]


class Antigo(NamedTuple):
    """Frase ou número que não pode voltar (fora de marcador). `quando`: None (sempre), "aberto" (só com o split
    de teste ainda aberto) ou "congelado" (só depois do congelamento); `escopo`: só nesses textos (None = todos).
    Linha com <!--historico--> passa."""

    rx: str
    motivo: str
    quando: str | None = None
    escopo: tuple[str, ...] | None = None


ANTIGOS = [
    Antigo(r"\b0,89\b", "recall da rodada 1 (0,89; hoje 1,00)"),
    Antigo(r"\b8/9\b|\b8 de 9\b", "recall da rodada 1 (8 de 9)"),
    Antigo(r"\b41/42\b|\b41 de 42\b", "A/B v1 da rodada 1 (41/42)"),
    Antigo(r"10% \[4–22%\]|\b3 de 11\b|\(3/11\)", "red-team da rodada 1"),
    Antigo(r"p50 2,6|p95 4,0|2,6 s|4,0 s", "latência da rodada 1"),
    Antigo(r"\b124 mil\b", "tokens da gravação de 08/10"),
    Antigo(r"\b4 pendências\b", "demo antiga (4 pendências; hoje 3)"),
    Antigo(r"golden set congelado", "o split de teste ainda não está congelado (SPLIT.yaml, congelado: false)",
           quando="aberto"),
    Antigo(r"(?i)ser[áa] congelad|ainda n[ãa]o (?:est[áa] |foi )?congelad|n[ãa]o congelad[oa] ainda",
           "o split de teste já foi congelado (SPLIT.yaml, congelado: true, 16/10/2026): use o passado, com o hash",
           quando="congelado"),
    Antigo(r"o A/B deu empate|empatou com o checklist", "A/B v1 sem o v2"),
    Antigo(r"ferramenta certa sozinho", "métrica que confunde (ação do LLM igual à do plano)"),
    Antigo(r"Completas com evidência suficiente", "rótulo antigo do A/B v2"),
    Antigo(r"\b4\.553\b|\b15\.902\b|\b4\.072\b",
           "desclassificações da versão de 07/10/2026 (histórico); no palco, a de 14/10/2026 (desc.*) com a data",
           escopo=TEXTOS_PALCO),
]
# Totais de 2026 das desclassificações: sempre com a data de corte no mesmo parágrafo (o ano não acabou).
DESC_COM_DATA = ("ano_2026", "motivo013_2026")


def split_congelado() -> bool:
    import yaml

    return bool(SPLIT_YAML.exists() and (yaml.safe_load(SPLIT_YAML.read_text(encoding="utf-8")) or {}).get(
        "congelado"))


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------


def _br(x: float, casas: int = 0) -> str:
    return f"{x:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def prop(m: dict[str, Any] | None, pct: bool = True) -> dict[str, str]:
    """Variantes de uma proporção com IC de Wilson: fmt, valor, ic, kn, k, n, falado."""
    if not m or not m.get("n"):
        return {"fmt": "n/d", "valor": "n/d", "ic": "n/d", "kn": "n/d", "k": "n/d", "n": "n/d", "falado": "n/d"}
    k, n, p, (lo, hi) = m["k"], m["n"], m["p"], m["ic95"]
    if pct:
        valor, ic = f"{100 * p:.0f}%", f"[{100 * lo:.0f}–{100 * hi:.0f}%]"
    else:
        valor, ic = f"{p:.2f}".replace(".", ","), f"[{lo:.2f}–{hi:.2f}]".replace(".", ",")
    return {"fmt": M.fmt(m, pct), "valor": valor, "ic": ic, "valor_ic": f"{valor} {ic}", "kn": f"{k}/{n}",
            "k": str(k), "n": str(n), "falado": f"{k} de {n}"}


def num(x: Any, casas: int = 0, sufixo: str = "") -> dict[str, str]:
    return {"valor": "n/d" if x is None else _br(float(x), casas) + sufixo}


def p_valor(x: float | None) -> dict[str, str]:
    if x is None:
        return {"valor": "n/d"}
    return {"valor": "p < 0,0001" if x < 1e-4 else f"p = {_br(x, 3)}"}


def p_exato(x: float | None) -> dict[str, str]:
    """p-valor das chaves novas (pós-r4): `valor` com 4 casas, como no relatório e no slide (p = 0,6875); `curto`
    com 2 (p = 0,69, o da narrativa); `p` só o número."""
    if x is None:
        return {"valor": "n/d", "curto": "n/d", "p": "n/d"}
    if x < 1e-4:
        return {"valor": "p < 0,0001", "curto": "p < 0,0001", "p": "< 0,0001"}
    return {"valor": f"p = {_br(x, 4)}", "curto": f"p = {_br(x, 2)}", "p": _br(x, 4)}


def tempo(x: float | None) -> dict[str, str]:
    """Tempo em segundos: `valor` inteiro (como as chaves ab2.tempo_*) e `uma_casa` (como o relatório: 34,5 s)."""
    if x is None:
        return {"valor": "n/d", "uma_casa": "n/d"}
    return {"valor": _br(float(x), 0) + " s", "uma_casa": _br(float(x), 1) + " s"}


# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------


def _ler(data: str, nome: str, sufixo: str) -> tuple[dict[str, Any] | None, str]:
    p = GS.DIR / f"{data}_{nome}{sufixo}.json"
    return (json.loads(p.read_text(encoding="utf-8")) if p.exists() else None), _rel(p)


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:  # relatórios fora do repositório (testes)
        return p.name


def _complementar(data: str, chave: str, sha: str, fontes: dict[str, str]) -> dict[str, Any] | None:
    """Relatório complementar da rodada final (`GS.OPCIONAIS`), só se for do mesmo `sha256(src/)` dos principais."""
    nome, extras = GS.OPCIONAIS[chave]
    for extra in extras:
        p = GS.DIR / f"{data}_{nome}{GS.SUFIXO['valor']}{extra}.json"
        if p.exists():
            r = json.loads(p.read_text(encoding="utf-8"))
            if (r.get("config") or {}).get("sha256_src") != sha:
                raise SystemExit(f"relatório complementar de outra versão de src/: {_rel(p)}")
            fontes[chave] = _rel(p)
            return r
    return None


def numeros_ab2_teste(n: dict[str, dict[str, str]], ab2t: dict[str, Any] | None) -> None:
    """Chaves ab2_teste.*: o A/B v2 no teste congelado (L07), lidas só do relatório gravado."""
    if not ab2t:
        return
    p2 = ab2t["principal"]
    fo, so, res = p2["formulario"], p2["agente"], p2["agente_residual"]
    par, psr = p2["pareado"]["agente_residual"], p2["pareado"]["agente_residual_sem_registro"]
    n["ab2_teste.n"] = num(ab2t["config"]["n_casos"])
    n["ab2_teste.residual"] = prop(res["completas"])
    n["ab2_teste.formulario"] = prop(fo["completas"])
    n["ab2_teste.so_fotos"] = prop(so["completas"])
    n["ab2_teste.residual_sem_registro"] = prop(res["completas_sem_registro"])
    n["ab2_teste.formulario_sem_registro"] = prop(fo["completas_sem_registro"])
    n["ab2_teste.pares"] = {"valor": f"{par['so_agente']} × {par['so_formulario']}"}
    n["ab2_teste.mcnemar"] = p_exato(par["mcnemar_p_exato"])
    n["ab2_teste.pares_sem_registro"] = {"valor": f"{psr['so_agente']} × {psr['so_formulario']}"}
    n["ab2_teste.mcnemar_sem_registro"] = p_exato(psr["mcnemar_p_exato"])
    n["ab2_teste.tempo_residual"] = tempo(res["tempo_fiscal_s_mediana"])
    n["ab2_teste.tempo_formulario"] = tempo(fo["tempo_fiscal_s_mediana"])
    n["ab2_teste.tempo_maquina_residual"] = tempo(res.get("tempo_maquina_s_mediana"))
    n["ab2_teste.toques_residual"] = num(res["toques_media"])
    n["ab2_teste.toques_formulario"] = num(fo["toques_media"])
    n["ab2_teste.aceitos_errados_residual"] = prop(res["campos_aceitos_errados"])
    n["ab2_teste.aceitos_errados_formulario"] = prop(fo["campos_aceitos_errados"])
    fl = ab2t["fala"]
    n["ab2_teste.fala_llm"] = prop(fl["llm"]["alegacoes_corretas"])
    n["ab2_teste.fala_regras"] = prop(fl["regex"]["alegacoes_corretas"])
    n["ab2_teste.fala_narracoes_llm"] = prop(fl["llm"].get("narracoes_inteiras"))
    n["ab2_teste.fala_narracoes_regras"] = prop(fl["regex"].get("narracoes_inteiras"))
    n["ab2_teste.espurias_llm"] = num(fl["llm"].get("espurias_nocivas"))
    n["ab2_teste.espurias_regras"] = num(fl["regex"].get("espurias_nocivas"))
    lt = ab2t["leitura"]
    certos = sum(v["certo"] for v in lt["por_nivel"].values())
    errados = sum(v["aceito_errado"] for v in lt["por_nivel"].values())
    n["ab2_teste.leitura_campos"] = num(lt["barragem"]["n"])
    n["ab2_teste.leitura_precisao_aceitos"] = prop(M.proporcao(certos, certos + errados))
    n["ab2_teste.leitura_aceitos_errados"] = num(errados)
    n["ab2_teste.leitura_erros_crus"] = num(lt["barragem"]["cru_errado"])
    n["ab2_teste.leitura_barrados"] = num(lt["barragem"]["cru_errado_barrado"])
    n["ab2_teste.residual_completo"] = prop(res.get("residual_completo"))
    n["ab2_teste.conciliacao_oraculo_residual"] = prop(res.get("conteudo_igual_oraculo"))
    n["ab2_teste.conciliacao_oraculo_formulario"] = prop(fo.get("conteudo_igual_oraculo"))
    est = ab2t.get("estabilidade_replicacoes") or {}
    for b, chave in (("formulario", "media_formulario"), ("agente_residual", "media_residual")):
        if b in est:  # a média vem gravada com 4 casas (0,7755): arredonda meio para cima, como o relatório
            n[f"ab2_teste.{chave}"] = {"valor": GS.pct_meio(est[b]["completas"])}
            n[f"ab2_teste.{chave}_sem_registro"] = {"valor": GS.pct_meio(est[b]["completas_sem_registro"])}


def numeros_cego(n: dict[str, dict[str, str]], cego: dict[str, Any] | None, cego_det: dict[str, Any] | None) -> None:
    """Chaves redteam.cego_*: o conjunto cego v3 (L43), com e sem LLM; `_sem_semicega` = sem a família de injeção
    em documento (semi-cega: o autor viu o formato dela). O protocolo do v3 manda citar k/30 e k/26 juntos."""
    def conj(r: dict[str, Any] | None) -> dict[str, Any]:
        return (((r or {}).get("resumo") or {}).get("conjuntos") or {}).get("v3_cego") or {}

    c, d = conj(cego), conj(cego_det)
    if c:
        n["redteam.cego_n_casos"] = num(cego["config"]["n_casos"])
        n["redteam.cego_n_ataques"] = num(cego["config"]["n_ataques"])
        n["redteam.cego_ataques"] = prop(c["ataques"])
        n["redteam.cego_ataques_sem_semicega"] = prop(c.get("ataques_sem_semicego"))
        n["redteam.cego_overblocking"] = prop(c["over_blocking"])
    if d:
        n["redteam.cego_sem_llm_ataques"] = prop(d["ataques"])
        n["redteam.cego_sem_llm_ataques_sem_semicega"] = prop(d.get("ataques_sem_semicego"))
        n["redteam.cego_sem_llm_overblocking"] = prop(d["over_blocking"])


def numeros_rep(n: dict[str, dict[str, str]], rep_rel: dict[str, Any] | None) -> None:
    """Chaves agente_rep.*: a repetição do agente no teste (L60), comparada caso a caso com a 1ª execução."""
    rep = (rep_rel or {}).get("repeticao") or {}
    d = (rep.get("splits") or {}).get("test")
    if not rep.get("comparavel") or not d:
        return
    t = rep_rel["splits"]["test"]
    n["agente_rep.casos_status_diferente"] = prop(d["casos_com_status_diferente"])
    n["agente_rep.emissao_diferente"] = prop(d["emissao_diferente"])
    n["agente_rep.turnos_fala_diferente"] = prop(d["turnos_com_fala_diferente"])
    if d.get("turnos_com_acoes_diferentes"):
        n["agente_rep.turnos_acoes_diferentes"] = prop(d["turnos_com_acoes_diferentes"])
    n["agente_rep.numeros_iguais"] = {"valor": "sim" if d.get("numeros_iguais") else "não"}
    n["agente_rep.recall_teste"] = prop(t["recall_defeito"]["caso"], pct=False)
    n["agente_rep.overblocking_teste"] = prop(t["over_blocking"]["campos_rotulados"])


def regressao_pos_rodada(sufixo: str) -> Path | None:
    """Relatório da regressão sem LLM do v3 depois da rodada (`*_redteam_deterministico<sufixo>.1_v3regressao.json`,
    qualquer data: roda depois); o mais recente pelo nome."""
    ps = sorted(GS.DIR.glob(f"*_redteam_deterministico{sufixo}.1_v3regressao.json"))
    return ps[-1] if ps else None


def numeros_pos_rodada(n: dict[str, dict[str, str]], sufixo: str, equiv: dict[str, Any] | None,
                       fontes: dict[str, str]) -> None:
    """Chaves r41.* (para a r4: `r41.`), só com a equivalência E a regressão do v3: o código depois da rodada
    (r4.1), sempre "não cego" (as correções foram motivadas pelo cego). Nunca substituem o redteam.cego_*."""
    reg_p = regressao_pos_rodada(sufixo)
    if not equiv or reg_p is None:
        return
    pref = sufixo.lstrip("_").replace(".", "") + "1"
    reg = json.loads(reg_p.read_text(encoding="utf-8"))
    fontes[f"{pref}_v3_regressao"] = _rel(reg_p)
    conf = equiv.get("conferencias") or []
    iguais = sum(c.get("resultado") == "igual" for c in conf)
    n[f"{pref}.equivalencia_iguais"] = {"valor": f"{iguais}/{len(conf)}", "k": str(iguais), "n": str(len(conf))}
    n[f"{pref}.sha256_src"] = {"valor": str(equiv.get("sha256_src_atual", ""))[:16]}
    c = (((reg.get("resumo") or {}).get("conjuntos") or {}).get("v3_cego")) or {}
    if c:
        n[f"{pref}.v3_regressao_sem_llm_ataques"] = prop(c["ataques"])
        n[f"{pref}.v3_regressao_sem_llm_ataques_sem_semicega"] = prop(c.get("ataques_sem_semicego"))
        n[f"{pref}.v3_regressao_sem_llm_overblocking"] = prop(c["over_blocking"])


def montar(data: str, sufixo: str) -> dict[str, Any]:
    GS.SUFIXO["valor"] = sufixo
    hs = GS.hashes(data)
    faltam = [k for k, v in hs.items() if v is None]
    if faltam:
        raise SystemExit(f"relatórios ausentes ({data}, sufixo {sufixo}): {faltam}")
    if len(set(hs.values())) != 1:
        raise SystemExit(f"relatórios de versões diferentes de src/: {hs}")
    fontes: dict[str, str] = {}
    rel = {}
    for nome in ("agente", "deterministico", "redteam_agente", "redteam_deterministico", "ab_centralidade",
                 "ab_centralidade_v2"):
        rel[nome], fontes[nome] = _ler(data, nome, sufixo)
    ag, de, rt, rtd, ab1, ab2 = (rel[k] for k in ("agente", "deterministico", "redteam_agente",
                                                    "redteam_deterministico", "ab_centralidade",
                                                    "ab_centralidade_v2"))
    t, d = ag["splits"]["test"], de["splits"]["test"]
    dv = ag["splits"]["dev"]
    a, a_dev = t["agente"], dv["agente"]
    n: dict[str, dict[str, str]] = {}
    # golden set
    comp = t["composicao"]
    n["golden.n_total"] = num(dv["n_casos"] + t["n_casos"])
    n["golden.n_dev"] = num(dv["n_casos"])
    n["golden.n_teste"] = num(t["n_casos"])
    n["golden.teste_validos"] = num(comp.get("valido", 0))
    n["golden.teste_defeito"] = num(comp.get("defeito", 0))
    n["golden.teste_ambiguos"] = num(comp.get("ambiguo", 0))
    n["recall_teste"] = prop(t["recall_defeito"]["caso"], pct=False)
    n["overblocking_teste"] = prop(t["over_blocking"]["campos_rotulados"])
    n["abstencao_teste"] = prop(t["abstencao"]["correta"], pct=False)
    n["falso_verificado_teste"] = prop(t["falso_verificado"]["campo"])
    n["grounding.sem_lastro"] = num(t["grounding"]["numeros_sem_lastro"])
    n["grounding.falas"] = num(t["grounding"]["falas"]["n"])
    n["grounding.laudos"] = num(t["grounding"]["laudos"]["n"])
    n["sem_llm.recall_teste"] = prop(d["recall_defeito"]["caso"], pct=False)
    n["sem_llm.overblocking_teste"] = prop(d["over_blocking"]["campos_rotulados"])
    n["sem_llm.abstencao_teste"] = prop(d["abstencao"]["correta"], pct=False)
    # agente
    n["agente.tool_call_valida"] = prop(a["validade_1a_tentativa"])
    n["agente.turnos_plano_teste"] = num(a["turnos_com_fallback"])
    # ação que o LLM propôs sozinho = a esperada pelo harness (por isso o plano é determinístico; ver Q&A T1b)
    n["agente.acao_llm_correta_teste"] = prop(a["acoes_corretas"])
    n["agente.acao_llm_correta_dev"] = prop(a_dev["acoes_corretas"])
    por_tipo = a_dev.get("acoes_corretas_por_tipo") or {}
    if por_tipo.get("upload"):
        n["agente.acao_llm_correta_upload_dev"] = prop(por_tipo["upload"])
    n["agente.latencia_p50"] = num(a["latencia_turno_s"]["p50"], 1, " s")
    n["agente.latencia_p95"] = num(a["latencia_turno_s"]["p95"], 1, " s")
    sha = next(iter(hs.values()))
    numeros_rep(n, _complementar(data, "agente_rep", sha, fontes))  # L60: repetição do agente no teste
    # red-team
    r = rt["resumo"]
    n["redteam.n_casos"] = num(rt["config"]["n_casos"])
    n["redteam.n_ataques"] = num(rt["config"]["n_ataques"])
    n["redteam.ataques"] = prop(r["total_ataques"])
    n["redteam.overblocking"] = prop(r["total_over_blocking"])
    n["redteam.sem_llm_ataques"] = prop(rtd["resumo"]["total_ataques"])
    for conj, v in (r.get("conjuntos") or {}).items():
        n[f"redteam.{conj}_ataques"] = prop(v["ataques"])
        n[f"redteam.{conj}_overblocking"] = prop(v["over_blocking"])
    for cat, v in r["categorias"].items():
        if cat != "legitimo":
            n[f"redteam.cat_{cat}"] = prop(v["sucesso_ataque"])
            if (v.get("defesa_registrada") or {}).get("n"):
                n[f"redteam.defesa_{cat}"] = prop(v["defesa_registrada"])
    # L43: o conjunto cego v3, nos dois modos (relatórios _v3cego da mesma rodada)
    numeros_cego(n, _complementar(data, "redteam_agente_cego", sha, fontes),
                 _complementar(data, "redteam_deterministico_cego", sha, fontes))
    # A/B v1
    s1 = ab1["resumo"]
    n["ab1.pares"] = num(s1["pareado"]["n_pares"])
    n["ab1.checklist"] = prop(s1["checklist"]["suficiente"])
    n["ab1.agente"] = prop(s1["agente"]["suficiente"])
    n["ab1.turnos_checklist"] = num(s1["checklist"]["turnos_media"], 1)
    n["ab1.turnos_agente"] = num(s1["agente"]["turnos_media"], 1)
    # A/B v2
    p2 = ab2["principal"]
    fo, so, res = p2["formulario"], p2["agente"], p2["agente_residual"]
    par = p2["pareado"]
    n["ab2.n"] = num(ab2["config"]["n_casos"])
    n["ab2.formulario"] = prop(fo["completas"])
    n["ab2.so_fotos"] = prop(so["completas"])
    n["ab2.residual"] = prop(res["completas"])
    n["ab2.formulario_sem_registro"] = prop(fo["completas_sem_registro"])
    n["ab2.residual_sem_registro"] = prop(res["completas_sem_registro"])
    n["ab2.pares"] = {"valor": f"{par['agente_residual']['so_agente']} × {par['agente_residual']['so_formulario']}"}
    n["ab2.mcnemar"] = p_valor(par["agente_residual"]["mcnemar_p_exato"])
    psr = par["agente_residual_sem_registro"]
    n["ab2.pares_sem_registro"] = {"valor": f"{psr['so_agente']} × {psr['so_formulario']}"}
    n["ab2.mcnemar_sem_registro"] = p_valor(psr["mcnemar_p_exato"])
    n["ab2.tempo_formulario"] = num(fo["tempo_fiscal_s_mediana"], 0, " s")
    n["ab2.tempo_so_fotos"] = num(so["tempo_fiscal_s_mediana"], 0, " s")
    n["ab2.tempo_residual"] = num(res["tempo_fiscal_s_mediana"], 0, " s")
    n["ab2.toques_formulario"] = num(fo["toques_media"])
    n["ab2.toques_residual"] = num(res["toques_media"])
    n["ab2.aceitos_errados_formulario"] = prop(fo["campos_aceitos_errados"])
    n["ab2.aceitos_errados_residual"] = prop(res["campos_aceitos_errados"])
    n["ab2.residual_completo"] = prop(res.get("residual_completo"))
    n["ab2.documentos_com_residual"] = num(res.get("documentos_com_residual"))
    fl = ab2["fala"]
    n["ab2.fala_llm"] = prop(fl["llm"]["alegacoes_corretas"])
    n["ab2.fala_regras"] = prop(fl["regex"]["alegacoes_corretas"])
    lt = ab2["leitura"]
    certos = sum(v["certo"] for v in lt["por_nivel"].values())
    errados = sum(v["aceito_errado"] for v in lt["por_nivel"].values())
    n["ab2.leitura_campos"] = num(lt["barragem"]["n"])
    n["ab2.leitura_precisao_aceitos"] = prop(M.proporcao(certos, certos + errados))
    n["ab2.leitura_aceitos_errados"] = num(errados)
    n["ab2.leitura_erros_crus"] = num(lt["barragem"]["cru_errado"])
    n["ab2.leitura_barrados"] = num(lt["barragem"]["cru_errado_barrado"])
    est = ab2.get("estabilidade_replicacoes") or {}
    n_rep = (ab2["config"].get("param") or {}).get("replicacoes")
    n["ab2.replicas"] = num((n_rep or 1) - 1)
    for b, chave in (("formulario", "media_formulario"), ("agente_residual", "media_residual")):
        n[f"ab2.{chave}"] = num(100 * est[b]["completas"], 1, "%")
    n["ab2.media_formulario_sem_registro"] = num(100 * est["formulario"]["completas_sem_registro"], 1, "%")
    sens = ab2.get("sensibilidade") or {}
    if "foto_ruim" in sens:
        n["ab2.foto_ruim_residual"] = num(100 * sens["foto_ruim"]["agente_residual"]["completas"], 1, "%")
    # L07: o A/B v2 no teste congelado (o dev nunca é citado sem ele: PARES_OBRIGATORIOS)
    numeros_ab2_teste(n, _complementar(data, "ab_centralidade_v2_teste", sha, fontes))
    cfg = ag["config"]
    versao = {"data": data, "sufixo": sufixo.lstrip("_") or "-", "sha256_src": cfg["sha256_src"],
              "sha256_src_curto": cfg["sha256_src"][:16], "teste_sha256_conteudo": cfg["sha256_conteudo"]["test"][:12],
              "congelado": bool(cfg.get("congelado"))}
    if cfg.get("sha256_src_lf"):  # o mesmo src/ com LF, como o git guarda (num clone, hash_src() dá este)
        versao["sha256_src_lf"] = cfg["sha256_src_lf"]
        versao["sha256_src_lf_curto"] = cfg["sha256_src_lf"][:16]
    if not versao["congelado"]:  # rodada medida antes do congelamento: o estado de hoje do SPLIT.yaml
        versao["congelamento"] = GS.frase_antes_do_congelamento(cfg)
    n["versao.sha256_src"] = {"valor": versao["sha256_src_curto"]}
    n["versao.sufixo"] = {"valor": versao["sufixo"]}
    if versao.get("sha256_src_lf"):
        n["versao.sha256_src_lf"] = {"valor": versao["sha256_src_lf_curto"]}
    # custo medido no trace da demo
    custo_p = GS.DIR / f"{data}_custo_demo.json"
    custo = None
    if custo_p.exists():
        est_c = json.loads(custo_p.read_text(encoding="utf-8"))
        est_c = est_c[0] if isinstance(est_c, list) else est_c
        u, nuvem = est_c["uso"], est_c["nuvem_equivalente"]
        rs = sorted(x["rs"] for x in nuvem)
        n["custo.tokens_entrada"] = num(u["tokens_entrada"])
        n["custo.tokens_entrada_mil"] = num(u["tokens_entrada"] / 1000, 0, " mil")
        n["custo.tokens_saida"] = num(u["tokens_saida"])
        n["custo.chamadas_llm"] = num(u.get("chamadas_llm") or u.get("chamadas"))
        n["custo.local_rs"] = {"valor": "R$ " + _br(est_c["energia_local"]["rs"], 4)}
        n["custo.nuvem_min_rs"] = {"valor": "R$ " + _br(rs[0], 2)}
        n["custo.nuvem_max_rs"] = {"valor": "R$ " + _br(rs[-1], 2)}
        n["custo.nuvem_min_centavos"] = num(round(100 * rs[0]))
        n["custo.nuvem_max_centavos"] = num(round(100 * rs[-1]))
        custo = {"arquivo": custo_p.relative_to(REPO).as_posix(), "fiscalizacao": u.get("fiscalizacao_id")}
    equiv_p = GS.DIR / f"{data}_equivalencia{sufixo}.json"
    equiv = json.loads(equiv_p.read_text(encoding="utf-8")) if equiv_p.exists() else None
    numeros_pos_rodada(n, sufixo, equiv, fontes)  # r4.1: só com a equivalência e a regressão do v3
    numeros_desclassificacao(n, fontes)
    numeros_retroteste(n, fontes)
    return {"gerado_por": "scripts/gerar_numeros.py", "versao": versao, "fontes": fontes, "custo": custo,
            "equivalencia": equiv, "numeros": n}


# ---------------------------------------------------------------------------
# Observatório de desclassificações (desc.*) e retro-teste (retro.*): não dependem da rodada de avaliação
# ---------------------------------------------------------------------------

DESC_RESUMO = REPO / "bench" / "desclassificacao" / "resumo.json"
RETRO_RESULTADO = REPO / "eval" / "retroteste" / "resultado.json"


def _data_br(iso: str | None) -> str:
    if not iso:
        return "n/d"
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}"


def _ic(lo: float | None, hi: float | None, casas: int, escala: float = 1.0, sufixo: str = "") -> str:
    if lo is None or hi is None:
        return "n/d"
    return f"[{_br(escala * lo, casas)}–{_br(escala * hi, casas)}{sufixo}]"


def por_mil(m: dict[str, Any] | None) -> dict[str, str]:
    """Taxa por mil operações com IC de Wilson: valor, ic, valor_ic, fmt, kn, k, n, falado."""
    if not m or not m.get("n"):
        return dict.fromkeys(("valor", "ic", "valor_ic", "fmt", "kn", "k", "n", "falado"), "n/d")
    v = _br(1000 * m["p"], 1)
    ic = _ic(*m["ic95"], 1, 1000)
    kn = f"{_br(m['k'])}/{_br(m['n'])}"
    return {"valor": f"{v} por mil", "ic": ic, "valor_ic": f"{v} por mil {ic}", "fmt": f"{v}‰ {ic} ({kn})",
            "kn": kn, "k": _br(m["k"]), "n": _br(m["n"]), "falado": f"{v} a cada mil operações"}


def pct1(m: dict[str, Any] | None) -> dict[str, str]:
    """Proporção em % com uma casa e IC de Wilson."""
    if not m or not m.get("n"):
        return dict.fromkeys(("valor", "ic", "valor_ic", "fmt", "kn", "k", "n", "falado"), "n/d")
    v, ic = _br(100 * m["p"], 1) + "%", _ic(*m["ic95"], 1, 100, "%")
    kn = f"{_br(m['k'])}/{_br(m['n'])}"
    return {"valor": v, "ic": ic, "valor_ic": f"{v} {ic}", "fmt": f"{v} {ic} ({kn})", "kn": kn,
            "k": _br(m["k"]), "n": _br(m["n"]), "falado": f"{_br(m['k'])} de {_br(m['n'])}"}


def com_ic(x: dict[str, Any] | None, casas: int = 2, escala: float = 1.0, sufixo: str = "") -> dict[str, str]:
    """Estimativa pontual com IC95 já calculado (bootstrap ou Katz): valor, ic, valor_ic, fmt."""
    v = (x or {}).get("valor", (x or {}).get("razao"))
    if v is None:
        return {"valor": "n/d", "ic": "n/d", "valor_ic": "n/d", "fmt": "n/d"}
    ic = _ic(*(x.get("ic95") or [None, None]), casas, escala, sufixo)
    s = _br(escala * v, casas) + sufixo
    return {"valor": s, "ic": ic, "valor_ic": f"{s} {ic}", "fmt": f"{s} {ic}"}


def numeros_desclassificacao(n: dict[str, dict[str, str]], fontes: dict[str, str]) -> None:
    """Chaves desc.* (versão de palco: o arquivo oficial mais recente do BCB, 14/10/2026) e desc.memorando.*
    (versão de 07/10/2026, a do memorando: histórico). Os totais de 2026 têm a variante `com_data`."""
    if not DESC_RESUMO.exists():
        return
    r = json.loads(DESC_RESUMO.read_text(encoding="utf-8"))
    fontes["desclassificacao"] = DESC_RESUMO.relative_to(REPO).as_posix()
    for pref, versao in (("desc", DESC_PALCO), ("desc.memorando", "memorando_0710")):
        b = r["versoes"].get(versao)
        if not b:
            continue
        reg, c, jan = b["registros"], b["comparacao_2026_2025"], b["janela_2024_2026"]
        n[f"{pref}.total"] = num(reg["total"])
        n[f"{pref}.ano_2025"] = num(c["n_2025"])
        n[f"{pref}.ano_2026"] = num(c["n_2026"])
        n[f"{pref}.ate"] = {"valor": _data_br(c["data_max_2026"])}
        n[f"{pref}.motivo013_2025"] = num(c["motivo013_2025"])
        n[f"{pref}.motivo013_2026"] = num(c["motivo013_2026"])
        for k in DESC_COM_DATA:  # o total de 2026 é parcial: a variante com_data já leva a data de corte
            n[f"{pref}.{k}"]["com_data"] = f"{n[f'{pref}.{k}']['valor']} (até {n[f'{pref}.ate']['valor']})"
        n[f"{pref}.br_motivo013_2024_2026"] = pct1(jan["br"]["motivo013"])
        n[f"{pref}.go_registros_2024_2026"] = num(jan["go"]["registros"])
        n[f"{pref}.go_motivo013_2024_2026"] = pct1(jan["go"]["motivo013"])
        cg = jan["go"]["custeio_aquisicao"]
        n[f"{pref}.go_custeio_aquisicao_2024_2026"] = num(cg["registros"])
        n[f"{pref}.go_custeio_aquisicao_valor"] = num(cg["valor_desclassificado_rs"] / 1e6, 1, " mi")
        tx = b["taxas_por_coorte"]["br"]
        t = tx["2022_2024"]
        n[f"{pref}.taxa_custeio_aquisicao"] = por_mil(t["custeio_aquisicao"])
        n[f"{pref}.taxa_investimento_aquisicao"] = por_mil(t["investimento_aquisicao"])
        n[f"{pref}.taxa_media"] = por_mil(t["media"])
        n[f"{pref}.razao_custeio_media"] = num(t["custeio_aquisicao"]["razao_media"], 1, " vezes")
        n[f"{pref}.razao_custeio_demais"] = com_ic(t["custeio_aquisicao"]["razao_demais"], 1)
        n[f"{pref}.razao_investimento_demais"] = com_ic(t["investimento_aquisicao"]["razao_demais"], 2)
        for cat in ("custeio_aquisicao", "investimento_aquisicao"):
            rpm = [tx[str(a)][cat]["registros_por_mil"] for a in (2022, 2023, 2024)]
            n[f"{pref}.{cat}_registros_por_mil_min"] = num(min(rpm), 1)
            n[f"{pref}.{cat}_registros_por_mil_max"] = num(max(rpm), 1)
        part = b["participacao"]["br"]
        for g in ("pecuaria", "aquisicao_animais"):
            n[f"{pref}.part_{g}_operacoes"] = pct1(part[g]["pct_operacoes_2022_2024"])
            n[f"{pref}.part_{g}_registros"] = pct1(part[g]["pct_registros_desc_2024_2026"])
            desclass = part[g]["pct_operacoes_desclassificadas_coortes_2022_2024"]
            n[f"{pref}.part_{g}_desclassificadas"] = pct1(desclass)
        q = b["quebra_de_serie"]
        for a in (2021, 2022, 2023):
            n[f"{pref}.serie_{a}"] = num(q["registros_por_ano"].get(str(a), 0))
        for a in (2024, 2026):
            n[f"{pref}.pct_motivo999_{a}"] = num(q["pct_motivo_999_outro"].get(str(a)), 0, "%")
    f = r["fontes"]["desclassificacao"]
    n["desc.fonte_last_modified"] = {"valor": parsedate_to_datetime(f["last_modified"]).strftime("%d/%m/%Y")}
    n["desc.fonte_sha256"] = {"valor": f["sha256"][:16]}


def numeros_retroteste(n: dict[str, dict[str, str]], fontes: dict[str, str]) -> None:
    """Chaves retro.* da análise primária do retro-teste pré-registrado (eval/retroteste/PROTOCOLO.md)."""
    if not RETRO_RESULTADO.exists():
        return
    r = json.loads(RETRO_RESULTADO.read_text(encoding="utf-8"))
    fontes["retroteste"] = RETRO_RESULTADO.relative_to(REPO).as_posix()
    p = r["primaria"]
    n["retro.passou_limiar"] = {"valor": "sim" if r["passou_limiar_palco"] else "não"}
    n["retro.lift"] = com_ic(p["lift"], 2)
    n["retro.captura"] = com_ic(p["captura"], 1, 100, "%")
    n["retro.auc"] = com_ic(p["auc"], 2)
    n["retro.lift_so_valor"] = com_ic(r["primaria_so_valor"]["lift"], 2)
    n["retro.lift_aleatorio"] = com_ic(r["primaria_aleatorio"]["lift"], 2)
    n["retro.diferenca_regras_valor"] = com_ic(r["primaria_diferenca"], 2)
    n["retro.n_operacoes"] = num(p["n"])
    n["retro.n_positivos"] = num(p["positivos"])
    n["retro.protocolo_sha256"] = {"valor": r["protocolo"]["sha256"][:16]}


# ---------------------------------------------------------------------------
# Saída, marcadores e verificação
# ---------------------------------------------------------------------------


def plano(numeros: dict[str, Any]) -> dict[str, str]:
    """`chave.variante` → texto (a variante padrão de uma proporção é `fmt`; de um número, `valor`)."""
    out = {}
    for k, v in numeros["numeros"].items():
        for var, texto in v.items():
            out[f"{k}.{var}"] = texto
        out[k] = v.get("fmt") or v.get("valor") or ""
    return out


def markdown(numeros: dict[str, Any]) -> str:
    v = numeros["versao"]
    eq = numeros.get("equivalencia")
    linhas = [
        "# Números do Laudo Vivo (fonte única)", "",
        (f"*Gerado por `scripts/py.sh scripts/gerar_numeros.py` a partir de `eval/reports/{v['data']}_*_{v['sufixo']}"
         f"*.json` (todos com `sha256(src/)={v['sha256_src_curto']}…`"
         + (f", ou `{v['sha256_src_lf_curto']}…` com LF, como o git guarda" if v.get("sha256_src_lf_curto") else "")
         + ") e do custo medido no trace da demo. Não edite à "
         "mão: os textos citam estes números entre marcadores `<!--n:chave-->…<!--/n-->`, e `--verificar` falha se "
         "algum divergir.*"), "",
        ("**Par obrigatório** (`--verificar`; no mesmo parágrafo ou, numa tabela, na mesma linha): "
         + "; ".join(p.rotulo for p in PARES_OBRIGATORIOS) + "."), "",
        (f"Split de teste (`sha256_conteudo={v['teste_sha256_conteudo']}…`): "
         + ("**congelado** quando esta rodada foi medida." if v["congelado"] else f"{v['congelamento']}.")), "",
    ]
    if eq:
        linhas += [
            "## Código depois da avaliação", "",
            (f"O código mudou depois desta rodada ({eq.get('motivo', '')}). Conferência de equivalência em "
             f"{eq.get('data')}, no código `sha256(src/)={str(eq.get('sha256_src_atual', ''))[:16]}…`: "
             + "; ".join(f"{c['nome']}: **{c['resultado']}**" for c in eq.get("conferencias", []))
             + ". " + (eq.get("conclusao", "")[:1].upper() + eq.get("conclusao", "")[1:]).rstrip(".") + "."), "",
        ]
        reg = [f for k, f in numeros["fontes"].items() if k.endswith("_v3_regressao")]
        if reg:
            linhas += [(f"Regressão sem LLM do conjunto cego v3 no código novo (`{reg[0]}`): **não cega**, porque as "
                        "correções foram motivadas por estes casos. As chaves dela (`*.v3_regressao_*`) só valem ao "
                        "lado do resultado cego (`redteam.cego_*`), que não muda; os números com LLM continuam os "
                        "medidos no código da rodada."), ""]
    linhas += ["| Chave | Valor | Falado |", "|---|---|---|"]
    for k, x in numeros["numeros"].items():
        linhas.append(f"| `{k}` | {x.get('fmt') or x.get('valor')} | {x.get('falado', '')} |")
    linhas += ["", "Fontes:", ""]
    linhas += [f"- `{k}`: `{f}`" for k, f in numeros["fontes"].items()]
    if numeros.get("custo"):
        linhas.append(f"- custo: `{numeros['custo']['arquivo']}` (trace da demo `{numeros['custo']['fiscalizacao']}`;"
                      " tokens medidos; preço de nuvem e energia são estimativa, ver `scripts/custo_fiscalizacao.py`)")
    linhas += ["", ("Uso nos textos: `<!--n:recall_teste.falado-->9 de 9<!--/n-->`. Variantes de proporção: "
                    "`fmt`, `valor`, `ic`, `valor_ic`, `kn`, `k`, `n`, `falado`; de número: `valor`."), ""]
    return "\n".join(linhas)


def aplicar_texto(texto: str, tabela: dict[str, str]) -> tuple[str, list[str]]:
    erros: list[str] = []

    def troca(m: re.Match) -> str:
        chave = m.group(1)
        if chave not in tabela:
            erros.append(f"chave desconhecida: {chave}")
            return m.group(0)
        return f"<!--n:{chave}-->{tabela[chave]}<!--/n-->"

    return RX_MARCADOR.sub(troca, texto), erros


def _paragrafos(texto: str) -> list[tuple[int, str]]:
    """(linha inicial, texto) de cada parágrafo (linhas seguidas sem linha em branco; uma tabela é um só)."""
    out, ini, atual = [], 1, []
    for i, linha in enumerate(texto.splitlines(), 1):
        if linha.strip():
            if not atual:
                ini = i
            atual.append(linha)
        elif atual:
            out.append((ini, "\n".join(atual)))
            atual = []
    if atual:
        out.append((ini, "\n".join(atual)))
    return out


def conferir_desclassificacoes(nome: str, texto: str) -> list[str]:
    """Versão de palco das desclassificações: total de 2026 sempre com a data de corte (marcador `<pref>.ate` no
    mesmo parágrafo, ou a variante `.com_data`); a versão histórica (`desc.memorando.*`) fora dos textos de palco.
    Linha com <!--historico--> passa."""
    erros = []
    palco = nome in TEXTOS_PALCO
    for ini, par in _paragrafos(texto):
        chaves = {m.group(1) for m in RX_MARCADOR.finditer(par)}
        for j, linha in enumerate(par.splitlines()):
            if "<!--historico-->" in linha:
                continue
            for m in RX_MARCADOR.finditer(linha):
                chave = m.group(1)
                if palco and chave.startswith("desc.memorando."):
                    erros.append(f"{nome}:{ini + j}: {chave} é a versão de 07/10/2026 das desclassificações "
                                 "(histórico); no palco use desc.* (arquivo de 14/10/2026) com a data de corte")
                pref = "desc.memorando" if chave.startswith("desc.memorando.") else "desc"
                base = chave[len(pref) + 1:].split(".")[0]
                if (chave.startswith("desc.") and base in DESC_COM_DATA and not chave.endswith(".com_data")
                        and not any(c == f"{pref}.ate" or c.startswith(f"{pref}.ate.") for c in chaves)):
                    erros.append(f"{nome}:{ini + j}: {chave} (total parcial de 2026) sem a data de corte: ponha "
                                 f"<!--n:{pref}.ate.valor--> no mesmo parágrafo ou use a variante "
                                 f"{pref}.{base}.com_data")
    return erros


RX_TR = re.compile(r"<tr\b.*?</tr>", re.DOTALL | re.IGNORECASE)


def _unidades(texto: str) -> list[tuple[int, str]]:
    """(linha inicial, texto) de cada unidade do par obrigatório: cada linha de tabela (Markdown `| … |` ou
    `<tr>…</tr>` em HTML) é uma unidade; o resto de cada parágrafo (linhas seguidas sem linha em branco) é outra."""
    out: list[tuple[int, str]] = []
    trs = []  # (linha inicial, linha final) de cada <tr>…</tr>
    for m in RX_TR.finditer(texto):
        ini = texto.count("\n", 0, m.start()) + 1
        trs.append((ini, ini + m.group(0).count("\n")))
        out.append((ini, m.group(0)))
    dentro = {i for a, b in trs for i in range(a, b + 1)}
    for ini, par in _paragrafos(texto):
        resto: list[tuple[int, str]] = []
        for j, linha in enumerate(par.splitlines()):
            n = ini + j
            if n in dentro:
                continue
            if linha.lstrip().startswith("|"):
                out.append((n, linha))
            else:
                resto.append((n, linha))
        if resto:
            out.append((resto[0][0], "\n".join(x for _, x in resto)))
    return sorted(out)


def conferir_pares(nome: str, texto: str) -> list[str]:
    """`PARES_OBRIGATORIOS`: o número seletivo (o dev sem o teste, o red-team da equipe sem o cego) é erro."""
    erros = []
    for ini, unidade in _unidades(texto):
        chaves = [m.group(1) for m in RX_MARCADOR.finditer(unidade)]
        for p in PARES_OBRIGATORIOS:
            if any(re.search(p.exige, c) for c in chaves):
                continue
            for j, linha in enumerate(unidade.splitlines()):
                if "<!--historico-->" in linha:
                    continue
                gat = [m.group(1) for m in RX_MARCADOR.finditer(linha) if re.search(p.gatilho, m.group(1))]
                if gat:
                    erros.append(f"{nome}:{ini + j}: {gat[0]} sem par obrigatório no mesmo parágrafo ou linha de "
                                 f"tabela ({p.motivo}; {p.rotulo}): ponha o par junto, ou tire o número")
                    break
    return erros


def conferir_texto(nome: str, texto: str, tabela: dict[str, str], congelado: bool | None = None) -> list[str]:
    erros = []
    for m in RX_MARCADOR.finditer(texto):
        chave, atual = m.group(1), m.group(2)
        if chave not in tabela:
            erros.append(f"{nome}: chave desconhecida {chave!r}")
        elif atual != tabela[chave]:
            erros.append(f"{nome}: {chave} diz {atual!r}, a fonte diz {tabela[chave]!r}")
    erros += conferir_desclassificacoes(nome, texto)
    erros += conferir_pares(nome, texto)
    estado = "congelado" if (split_congelado() if congelado is None else congelado) else "aberto"
    regras = [r for r in ANTIGOS if r.quando in (None, estado) and (r.escopo is None or nome in r.escopo)]
    sem_marcadores = RX_MARCADOR.sub("", texto)
    for i, linha in enumerate(sem_marcadores.splitlines(), 1):
        if "<!--historico-->" in linha:
            continue
        for r in regras:
            if re.search(r.rx, linha):
                erros.append(f"{nome}:{i}: número ou frase antiga fora de marcador ({r.motivo}): "
                             f"{linha.strip()[:90]}")
    return erros


def gravar_texto(p: Path, texto: str) -> None:
    """Reescreve um texto de outra área mantendo o fim de linha que ele já tinha (CRLF ou LF)."""
    crlf = p.exists() and b"\r\n" in p.read_bytes()
    p.write_text(texto, encoding="utf-8", newline="\r\n" if crlf else "\n")


def _hash_src_atual() -> str:
    import harness

    return harness.hash_src()


def _hash_src_lf_atual() -> str:
    import harness

    return harness.hash_src_lf()


def conferir_src(versao: dict[str, Any], eq: dict[str, Any] | None) -> list[str]:
    """Linhas sobre o `src/` atual × o dos relatórios (e o da última equivalência), com os dois hashes: os bytes do
    disco (`sha256_src`, CRLF no Windows) e o LF (`sha256_src_lf`, o que o git guarda e o que um clone tem). Aceita
    o código atual se um dos dois bater; as linhas que começam com "AVISO" são as de antes (código mudou)."""
    cru, lf = _hash_src_atual(), _hash_src_lf_atual()
    ref, ref_lf = versao.get("sha256_src", ""), versao.get("sha256_src_lf")
    linhas = [f"src/ atual: sha256(src/)={cru[:16]}… (bytes do disco), LF {lf[:16]}…; relatórios: {ref[:16]}…"
              + (f" (LF {ref_lf[:16]}…)" if ref_lf else "")]
    if cru == ref:
        return linhas + ["src/ é o dos relatórios (mesmos bytes)"]
    if ref_lf and lf == ref_lf:
        return linhas + ["src/ é o dos relatórios pelo hash LF (clone com LF: o git guarda src/ com LF)"]
    eq = eq or {}
    if not eq:
        return linhas + [("AVISO: src/ mudou depois dos relatórios e não há conferência de equivalência "
                          "(eval/conferir_equivalencia.py)")]
    if eq.get("sha256_src_atual") == cru or (eq.get("sha256_src_atual_lf") and eq["sha256_src_atual_lf"] == lf):
        return linhas + [(f"src/ mudou depois dos relatórios; é o da conferência de equivalência de "
                          f"{eq.get('data')} (sha256(src/)={str(eq.get('sha256_src_atual'))[:16]}…)")]
    return linhas + [("AVISO: src/ mudou depois da última conferência de equivalência; rode "
                      "eval/conferir_equivalencia.py")]


def fixar_palco(data: str, sufixo: str, motivo: str | None) -> dict[str, Any]:
    """Grava `eval/reports/palco.json` com a nova rodada de palco; a anterior fica em `anteriores`."""
    import harness

    atual = GS.palco()
    anteriores = list(atual.get("anteriores") or [])
    if atual.get("rodada") and atual["rodada"] != {"data": data, "sufixo": sufixo}:
        anteriores.append({**atual["rodada"], "ate": harness.agora_iso()})
    novo = {"rodada": {"data": data, "sufixo": sufixo}, "desclassificacao": atual["desclassificacao"],
            "fixado_em": harness.agora_iso(), "motivo": motivo or "n/d",
            "por": "scripts/gerar_numeros.py --aplicar --fixar-palco", "anteriores": anteriores}
    GS.PALCO.write_text(json.dumps(novo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"versão de palco: {data}{sufixo} ({GS.PALCO.relative_to(REPO).as_posix()})")
    return novo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DATA_PADRAO)
    ap.add_argument("--sufixo", default=SUFIXO_PADRAO)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--aplicar", action="store_true", help="atualiza os números entre marcadores nos textos")
    g.add_argument("--verificar", action="store_true", help="só confere; código 1 se algo divergir")
    ap.add_argument("--fixar-palco", action="store_true",
                    help="com --aplicar: grava --data/--sufixo como a versão de palco (eval/reports/palco.json)")
    ap.add_argument("--motivo", default=None, help="com --fixar-palco: por que a versão de palco mudou")
    a = ap.parse_args()
    outra = (a.data, a.sufixo) != (DATA_PADRAO, SUFIXO_PADRAO)
    if a.fixar_palco and not a.aplicar:
        print("--fixar-palco só com --aplicar (os textos e o palco mudam juntos)")
        return 2
    if a.aplicar and outra and not a.fixar_palco:
        print(f"--aplicar com {a.data}{a.sufixo}, mas a versão de palco é {DATA_PADRAO}{SUFIXO_PADRAO} "
              f"({GS.PALCO.relative_to(REPO).as_posix()}): os textos ficariam com uma rodada e o --verificar do CI "
              "com outra. Para trocar o palco: --aplicar --fixar-palco --motivo \"...\"")
        return 2
    numeros = montar(a.data, a.sufixo)
    if a.fixar_palco:  # montar() já conferiu que os relatórios existem e são da mesma versão de src/
        fixar_palco(a.data, a.sufixo, a.motivo)
    tabela = plano(numeros)
    js = json.dumps(numeros, ensure_ascii=False, indent=1) + "\n"
    md = markdown(numeros)
    erros: list[str] = []
    if a.verificar:
        for arq, novo in ((SAIDA / "numeros.json", js), (SAIDA / "numeros.md", md)):
            if not arq.exists() or arq.read_text(encoding="utf-8") != novo:
                erros.append(f"{arq.relative_to(REPO).as_posix()} desatualizado: rode gerar_numeros.py --aplicar")
        slide = GS.DIR.parent / "SLIDE.md"
        if not slide.exists() or slide.read_text(encoding="utf-8") != GS.gerar(a.data):
            erros.append(f"eval/SLIDE.md não é o que gerar_slide.py produz de {a.data}{a.sufixo}")
    else:
        (SAIDA / "numeros.json").write_text(js, encoding="utf-8", newline="\n")
        (SAIDA / "numeros.md").write_text(md, encoding="utf-8", newline="\n")
    vistos = 0
    for rel in ALVOS:
        p = (REPO / rel).resolve()
        if not p.exists():
            continue
        texto = p.read_text(encoding="utf-8")
        if a.aplicar:
            novo, e = aplicar_texto(texto, tabela)
            erros += [f"{rel}: {x}" for x in e]
            if novo != texto:
                gravar_texto(p, novo)
                print(f"atualizado: {rel}")
            texto = novo
        erros += conferir_texto(rel, texto, tabela)
        vistos += len(RX_MARCADOR.findall(texto))
    for linha in conferir_src(numeros["versao"], numeros.get("equivalencia")):
        print(linha)
    for e in erros:
        print("ERRO:", e)
    print(f"{len(tabela)} números; {vistos} marcadores conferidos; {len(erros)} problema(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
