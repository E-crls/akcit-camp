"""Gera `eval/SLIDE.md` (o "slide único de avaliação", parecer técnico 4.9) a partir dos relatórios JSON.

Uso: scripts/py.sh eval/gerar_slide.py [--data AAAA-MM-DD] [--sufixo _r3]
(sem nenhum dos dois: a versão de palco de `eval/reports/palco.json`; só com `--sufixo`: a data mais recente)

Lê `<data>_agente<sufixo>.json` (número principal: o produto com o LLM, split de teste),
`<data>_deterministico<sufixo>.json` (mesmo pipeline sem LLM), `<data>_redteam_agente<sufixo>.json`,
`<data>_redteam_deterministico<sufixo>.json`, `<data>_ab_centralidade<sufixo>.json` (fiscal simulado) e
`<data>_ab_centralidade_v2<sufixo>.json` (papel fotografado e fala livre, sintéticos; residual real). Com
`--sufixo`, confere que todos os relatórios foram gerados com o mesmo `sha256(src/)` e para se não foram.

Relatórios opcionais da rodada final (só entram se existirem, e com o mesmo `sha256(src/)`):
- `<data>_ab_centralidade_v2<sufixo>_teste.json` (L07, `run_ab_v2.py --split test --final ... --sufixo _r4_teste`):
  o A/B v2 mostra dev e teste lado a lado, com a frase escrita antes de rodar para cada resultado possível; a
  divisão de trabalho e "O que a IA faz aqui" passam a citar o teste primeiro e o dev entre parênteses;
- `<data>_agente<sufixo>_rep.json` (L60, `run_eval.py --modo agente --split test --final ... --sufixo _r4_rep`): a
  repetição do agente no teste, comparada caso a caso;
- `<data>_redteam_agente<sufixo>_v3cego.json` e `<data>_redteam_deterministico<sufixo>_v3cego.json` (L43,
  `run_redteam.py --conjunto v3_cego --sufixo _r4_v3cego`, nos dois modos; `_cego` também é aceito), ou o
  conjunto `v3_cego` dentro do relatório principal do red-team.
Sem eles (ex.: a r3), as seções que dependem deles não aparecem.

Depois da rodada (pós-r4, 16/10/2026): a seção "Depois da r4 (r4.1)" só aparece se existirem a conferência de
equivalência (`<data>_equivalencia<sufixo>.json`) E a regressão sem LLM do v3
(`*_redteam_deterministico<sufixo>.1_v3regressao.json`), sempre com o rótulo "não cego"; ela nunca substitui o
resultado cego nem muda os números da rodada. Notas escritas depois de ver um resultado (`NOTAS_POS_RESULTADO`)
ficam ao lado da leitura escrita antes de rodar, que não muda.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics as M

DIR = Path(__file__).resolve().parent / "reports"


SUFIXO = {"valor": ""}


def _ler(data: str, nome: str, com_sufixo: bool = False) -> dict | None:
    """`<data>_<nome><sufixo>.json`; sem `--sufixo` e com `com_sufixo`, se não houver, o mais recente
    `<data>_<nome>_<sufixo>.json`."""
    if SUFIXO["valor"]:
        p = DIR / f"{data}_{nome}{SUFIXO['valor']}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    p = DIR / f"{data}_{nome}.json"
    if not p.exists() and com_sufixo:
        alternativas = sorted((x for x in DIR.glob(f"{data}_{nome}_*.json") if not x.stem.endswith(_OPCIONAIS)),
                              key=lambda x: x.stat().st_mtime)
        if not alternativas:
            return None
        p = alternativas[-1]
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# Relatórios complementares da rodada final: `<nome><sufixo><extra>.json`; nunca valem como o relatório principal.
# O red-team cego da r4 sai com `--sufixo _r4_v3cego` (eval/rodada_r4.py); `_cego` fica aceito como nome antigo.
_OPCIONAIS = ("_teste", "_rep", "_cego", "_v3cego", "_v3regressao")  # _v3regressao: a r4.1 (nunca é o principal)
OPCIONAIS = {"ab_centralidade_v2_teste": ("ab_centralidade_v2", ("_teste",)), "agente_rep": ("agente", ("_rep",)),
             "redteam_agente_cego": ("redteam_agente", ("_v3cego", "_cego")),
             "redteam_deterministico_cego": ("redteam_deterministico", ("_v3cego", "_cego"))}

# Versão citada no palco (rodada de avaliação e versão do arquivo de desclassificações), num lugar só: lida por
# este script (padrão sem --data/--sufixo), por scripts/gerar_numeros.py (--verificar no CI) e por
# scripts/desclassificacao_marcadores.py; muda só com `gerar_numeros.py --aplicar --fixar-palco` (passo final da
# r4). Fica em reports/, fora do sha256(eval/).
PALCO = DIR / "palco.json"
PALCO_PADRAO = {"rodada": {"data": "2026-10-09", "sufixo": "_r3"},
                "desclassificacao": {"palco": "atual", "historico": ["memorando_0710"]}}
REGISTRO_TESTE = DIR.parent / "golden" / "casos" / "registro_teste.jsonl"


def palco() -> dict:
    """Versão de palco gravada em `reports/palco.json` (ou a padrão, a r3, se o arquivo não existir)."""
    if not PALCO.exists():
        return json.loads(json.dumps(PALCO_PADRAO))
    d = json.loads(PALCO.read_text(encoding="utf-8"))
    return {**PALCO_PADRAO, **d}


def _ler_opcional(data: str, chave: str) -> dict | None:
    """Relatório complementar (L07, L60, L43) da mesma rodada; só com `--sufixo` (a rodada final tem nome)."""
    if not SUFIXO["valor"]:
        return None
    nome, extras = OPCIONAIS[chave]
    for extra in extras:
        p = DIR / f"{data}_{nome}{SUFIXO['valor']}{extra}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def hashes_opcionais(data: str) -> dict[str, str | None]:
    """sha256(src/) dos relatórios complementares que existirem (ausente não é erro)."""
    out = {}
    for chave in OPCIONAIS:
        r = _ler_opcional(data, chave)
        if r is not None:
            out[chave] = r.get("config", {}).get("sha256_src")
    return out


def _num(x: float | None, casas: int = 1) -> str:
    return "n/d" if x is None else f"{x:.{casas}f}".replace(".", ",")


def _p(x: float | None) -> str:
    """p-valor: abaixo de 0,0001 vira "< 0,0001"."""
    return "n/d" if x is None else ("< 0,0001" if x < 1e-4 else "= " + _num(x, 4))


def pct_meio(x: float | None, casas: int = 1) -> str:
    """Proporção (0–1) em %, arredondando meio para cima sobre o valor gravado (0,7755 → 77,6%; o `:.1f` do float
    daria 77,5%). Só nos textos novos (pós-r4): os antigos continuam com `_num`."""
    if x is None:
        return "n/d"
    d = (Decimal(repr(x)) * 100).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    return f"{d}".replace(".", ",") + "%"


def hashes(data: str) -> dict[str, str | None]:
    """sha256(src/) de cada relatório usado no slide."""
    out = {}
    for nome in ("agente", "deterministico", "redteam_agente", "redteam_deterministico", "ab_centralidade",
                 "ab_centralidade_v2"):
        r = _ler(data, nome, True)
        out[nome] = (r or {}).get("config", {}).get("sha256_src") if r else None
    return out


def _pp(m: dict | None) -> str:
    return M.fmt(m, True) if m else "n/d"


# Régua do A/B v2 no teste. A "r4" foi escrita antes da r4 (16/10/2026, 16:10) e vale para ela: "inverte" é
# qualquer resultado abaixo do formulário, com qualquer p. A "pos_r4" foi escrita em 16/10/2026 à noite, depois do
# resultado da r4 e antes da próxima rodada (r5): "inverte" só com p < 0,05; abaixo sem significância é
# "abaixo_sem_significancia". Um relatório do teste usa a régua da data dele (`config.data`).
REGUA_POS_R4_DESDE = "2026-10-17"


def regua_do_teste(teste: dict | None) -> str:
    data = str(((teste or {}).get("config") or {}).get("data") or "")
    return "pos_r4" if data >= REGUA_POS_R4_DESDE else "r4"


def veredito_teste(res: float | None, fo: float | None, p: float | None, regua: str = "r4") -> str:
    """Classe do resultado do teste contra o formulário: confirma | mesma_direcao | empate | inverte | sem_dados
    (régua "r4") e, na régua "pos_r4", também abaixo_sem_significancia."""
    if res is None or fo is None:
        return "sem_dados"
    if res > fo:
        return "confirma" if p is not None and p < 0.05 else "mesma_direcao"
    if res == fo:
        return "empate"
    if regua == "r4":
        return "inverte"
    return "inverte" if p is not None and p < 0.05 else "abaixo_sem_significancia"


# Frases escritas ANTES de rodar o A/B v2 no teste (L07), uma para cada resultado possível (régua "r4").
FRASES_AB2_TESTE = {
    "confirma": ("No teste, que não foi usado para desenvolver o A/B v2 (cada uso está em "
                 "`eval/golden/casos/registro_teste.jsonl`), o ganho se repete: agente + residual {res} contra "
                 "formulário {fo} (McNemar p {p}). O resultado do dev não era só ajuste ao dev."),
    "mesma_direcao": ("No teste, o agente + residual continua à frente ({res} contra {fo}), mas com n = {n} a "
                      "diferença não é estatisticamente significativa (McNemar p {p}): o teste não confirma nem "
                      "desmente o dev, e o número do dev só pode ser dito com essa ressalva."),
    "empate": ("No teste, empate ({res} contra {fo}): o ganho medido no dev não se repetiu neste conjunto, e o "
               "número do dev não deve ser apresentado como ganho."),
    "inverte": ("No teste, o resultado se inverte ({res} contra {fo}, McNemar p {p}): o ganho do dev não se sustenta "
                "fora do conjunto em que o A/B v2 foi desenvolvido. Nada foi ajustado olhando o teste; a diferença "
                "vira item da próxima versão."),
    "sem_dados": "O relatório do teste não tem os números do A/B v2 (ver o relatório).",
}

# Régua "pos_r4" (escrita em 16/10/2026 à noite, antes da r5): nenhuma frase afirma causa nem cegueira (o teste do
# A/B foi olhado caso a caso em 16/10; o registro do teste diz se uma execução é cega).
FRASES_AB2_TESTE_POS_R4 = {
    "confirma": ("No teste, o agente + residual fica à frente do formulário com diferença estatisticamente "
                 "significativa ({res} contra {fo}, McNemar p {p})."),
    "mesma_direcao": ("No teste, o agente + residual fica à frente ({res} contra {fo}), mas com n = {n} a diferença "
                      "não é estatisticamente significativa (McNemar p {p}): o teste não confirma nem desmente o dev."),
    "empate": "No teste, empate ({res} contra {fo}): o resultado do dev não se repetiu neste conjunto.",
    "abaixo_sem_significancia": ("No teste, o agente + residual fica abaixo do formulário ({res} contra {fo}), mas "
                                 "com n = {n} a diferença não é estatisticamente significativa (McNemar p {p}): o "
                                 "resultado do dev não se repetiu, e o teste também não mostra que o agente seja "
                                 "pior."),
    "inverte": ("No teste, o formulário fica à frente com diferença estatisticamente significativa ({res} contra "
                "{fo}, McNemar p {p}): o resultado do dev não se sustenta fora do conjunto em que o A/B v2 foi "
                "desenvolvido."),
    "sem_dados": "O relatório do teste não tem os números do A/B v2 (ver o relatório).",
}


def frase_ab2_teste(dev: dict, teste: dict, chave: str = "completas_sem_registro") -> str:
    """Frase honesta do A/B v2 no teste para a linha `chave` (padrão: sem a menção a item não financiado, a
    comparação justa, já que o formulário não tem campo para ela), mais a variação dev → teste do residual."""
    par = "agente_residual" + ("_sem_registro" if chave.endswith("_sem_registro") else "")
    sd, st = dev["principal"], teste["principal"]

    def g(s: dict, braco: str) -> float | None:
        return (s[braco].get(chave) or {}).get("p")

    regua = regua_do_teste(teste)
    pt = (st["pareado"].get(par) or {}).get("mcnemar_p_exato")
    v = veredito_teste(g(st, "agente_residual"), g(st, "formulario"), pt, regua)
    frases = FRASES_AB2_TESTE if regua == "r4" else FRASES_AB2_TESTE_POS_R4
    frase = frases[v].format(res=_pp(st["agente_residual"].get(chave)), fo=_pp(st["formulario"].get(chave)),
                             p=_p(pt), n=teste["config"].get("n_casos"))
    rd, rt_ = g(sd, "agente_residual"), g(st, "agente_residual")
    if rd is not None and rt_ is not None:
        if regua != "r4":
            frase += (f" A taxa do agente + residual foi de {_num(100 * rd, 0)}% no dev para {_num(100 * rt_, 0)}% "
                      "no teste.")
        elif rt_ < rd - 0.10:
            frase += (f" A taxa do agente + residual caiu de {_num(100 * rd, 0)}% no dev para {_num(100 * rt_, 0)}% no "
                      "teste: parte do resultado do dev era ajuste ao dev.")
        else:
            frase += (f" A taxa do agente + residual ficou em {_num(100 * rd, 0)}% no dev e {_num(100 * rt_, 0)}% no "
                      "teste.")
    return frase


# Notas escritas DEPOIS de ver o resultado de uma execução do A/B v2 no teste (chave: `config.execucao_registro`
# do relatório do teste). Ficam ao lado da leitura escrita antes de rodar, que não muda. Os valores "antes" são os
# do 1º relatório daquela rodada, guardado fora do git (`dados_locais/r4/antes_refazer/`), e as horas vêm do
# registro do teste (seq 21 a 26) e dos arquivos; `tests/unit/test_eval_numeros.py` os confere.
NOTAS_POS_RESULTADO = {
    "216355e9efc1": {
        "escrita_em": "16/10/2026, à noite",
        "leituras_dev": "09/10/2026",
        "refazer": {"criterio": "20:15", "primeiro_fim": "20:22:38", "script": "20:25:39",
                    "primeira_execucao": "30db4d4619de", "seq": (21, 26),
                    "antes": {"completas": (16, 24), "sem_registro": (18, 24), "p_sem_registro": 0.4531,
                              "media_sem_registro": 0.7406, "barrados": 191, "aceitos_errados": 8}},
    },
}


def _erro_cru(ab2: dict, ab2t: dict) -> str:
    """Erro cru da 1ª leitura do VLM por campo, dev × teste (`leitura.barragem`)."""
    def um(r: dict) -> str:
        b = (r.get("leitura") or {}).get("barragem") or {}
        return f"{b.get('cru_errado', 'n/d')} de {b.get('n', 'n/d')}"

    return f"erro cru da 1ª leitura em {um(ab2)} campos no dev e {um(ab2t)} no teste"


def linhas_nota_pos_resultado(ab2: dict, ab2t: dict) -> list[str]:
    """Nota pós-resultado e cronologia do refazer de uma execução do teste (`NOTAS_POS_RESULTADO`)."""
    nota = NOTAS_POS_RESULTADO.get(str((ab2t.get("config") or {}).get("execucao_registro")))
    if not nota:
        return []
    st, sd = ab2t["principal"], ab2["principal"]
    par = st["pareado"]
    p_sr = (par.get("agente_residual_sem_registro") or {}).get("mcnemar_p_exato")
    p_c = (par.get("agente_residual") or {}).get("mcnemar_p_exato")
    res_sr, dev_sr = st["agente_residual"].get("completas_sem_registro") or {}, (
        sd["agente_residual"].get("completas_sem_registro") or {})
    out = [(f"**Nota pós-resultado** (escrita em {nota['escrita_em']}, depois de ver o resultado; a leitura acima "
            f"fica como foi escrita antes de rodar): com McNemar p {_p(p_sr)} sem a menção e p {_p(p_c)} na métrica "
            "completa, a diferença entre o agente + residual e o formulário não é estatisticamente significativa "
            "em nenhuma das duas comparações. \"Se inverte\" quer dizer só que o agente + residual ficou abaixo na "
            "comparação sem a menção: a régua escrita antes de rodar não tinha a classe \"abaixo, sem "
            "significância\", que vale da próxima rodada em diante. \"Parte do resultado do dev era ajuste ao "
            f"dev\" é hipótese, não achado. Concorrem com ela: as leituras do VLM do dev são de {nota['leituras_dev']},"
            " gravadas com o leitor e o NUM_CTX anteriores (sem `meta.json`), e as do teste foram feitas na r4, embora "
            f"no nível do campo o leitor se comporte de forma parecida nos dois splits ({_erro_cru(ab2, ab2t)}); "
            "o teste tem moldes de fala que o dev não tinha, por sorteio do mesmo gerador (um deles exercita um bug "
            "de deduplicação de alegações que o dev nunca exercitou); e o n é pequeno (sem a menção, "
            f"{dev_sr.get('k', 'n/d')}/{dev_sr.get('n', 'n/d')} no dev e {res_sr.get('k', 'n/d')}/"
            f"{res_sr.get('n', 'n/d')} no teste). A análise caso a caso, feita olhando o teste, está em "
            "`eval/reports/2026-10-16_ab_v2_teste_diagnostico.md`: ela não muda nenhum número oficial, e qualquer "
            "nova execução no teste deixa de ser cega."), ""]
    rf = nota.get("refazer")
    if rf:
        a = rf["antes"]
        est = (ab2t.get("estabilidade_replicacoes") or {}).get("agente_residual") or {}
        bar = (ab2t.get("leitura") or {}).get("barragem") or {}
        res_c = st["agente_residual"].get("completas") or {}
        out += [(f"**Leituras refeitas por falha de infraestrutura (cronologia completa):** três leituras do VLM no "
                 "teste falharam por erro do servidor do modelo (HTTP 500/400, `std::bad_alloc` no log do Ollama). O "
                 "critério para refazer só esse tipo de falha (`dados_locais/r4/refazer_infra.py`) foi gravado às "
                 f"{rf['criterio']}, antes do 1º resultado; o 1º A/B no teste (execução `{rf['primeira_execucao']}`) "
                 f"terminou às {rf['primeiro_fim']} com {a['completas'][0]}/{a['completas'][1]} "
                 f"({a['sem_registro'][0]}/{a['sem_registro'][1]} sem a menção, McNemar p {_p(a['p_sem_registro'])}); "
                 f"o script que refez as 3 leituras (`dados_locais/r4/rodar_refazer.sh`) foi criado às {rf['script']}, "
                 "depois de ver esse resultado; o "
                 f"resultado final, que é o desta página, ficou em {res_c.get('k')}/{res_c.get('n')} "
                 f"({res_sr.get('k')}/{res_sr.get('n')} sem a menção, p {_p(p_sr)}). A mudança favoreceu o sistema: "
                 f"a média das réplicas sem a menção foi de {pct_meio(a['media_sem_registro'])} para "
                 f"{pct_meio(est.get('completas_sem_registro'))}, e na leitura os erros crus barrados foram de "
                 f"{a['barrados']} para {bar.get('cru_errado_barrado', 'n/d')} e os aceitos errados de "
                 f"{a['aceitos_errados']} para {bar.get('cru_errado_aceito', 'n/d')}. As duas execuções estão no "
                 f"registro do teste (`registro_teste.jsonl`, seq {rf['seq'][0]} a {rf['seq'][1]}) e o 1º relatório "
                 "está guardado fora do git (`dados_locais/r4/antes_refazer/`). Daqui em diante, refazer falha de "
                 "infraestrutura segue uma regra escrita antes de rodar (`eval/README.md`, \"Depois da r4\")."), ""]
    return out


def linhas_ab2_teste(ab2: dict | None, ab2t: dict | None) -> list[str]:
    """A/B v2 com dev e teste lado a lado (L07); vazio sem o relatório do teste."""
    if not ab2 or not ab2t:
        return []
    sd, st = ab2["principal"], ab2t["principal"]
    nd, nt = ab2["config"]["n_casos"], ab2t["config"]["n_casos"]

    def lin(rotulo: str, s: dict, chave: str) -> str:
        return (f"| {rotulo} | {_pp(s['formulario'].get(chave))} | {_pp(s['agente'].get(chave))} | "
                f"**{_pp(s['agente_residual'].get(chave))}** |")

    def par(s: dict, nome: str) -> str:
        x = s["pareado"].get(nome) or {}
        return f"{x.get('so_agente', 'n/d')} × {x.get('so_formulario', 'n/d')} (p {_p(x.get('mcnemar_p_exato'))})"

    return [f"### A/B v2 no dev e no teste, lado a lado (dev n = {nd}; teste n = {nt}, `split=test`)", "",
            "| | Formulário | Agente (só fotos) | Agente + residual (real) |", "|---|---|---|---|",
            lin(f"Conteúdo igual à referência — dev (n = {nd})", sd, "completas"),
            lin(f"Conteúdo igual à referência — **teste** (n = {nt})", st, "completas"),
            lin("Idem, sem a menção a item não financiado — dev", sd, "completas_sem_registro"),
            lin("Idem, sem a menção a item não financiado — **teste**", st, "completas_sem_registro"), "",
            (f"Pareado, agente + residual × formulário: dev {par(sd, 'agente_residual')}, teste "
             f"{par(st, 'agente_residual')}; sem a menção: dev {par(sd, 'agente_residual_sem_registro')}, teste "
             f"{par(st, 'agente_residual_sem_registro')}."), "",
            f"**Leitura honesta (escrita antes de rodar):** {frase_ab2_teste(ab2, ab2t)}", "",
            *linhas_nota_pos_resultado(ab2, ab2t)]


def linhas_repeticao(rep_rel: dict | None) -> list[str]:
    """Repetição do agente no teste (L60): uma linha com a frase escrita antes de rodar."""
    rep = (rep_rel or {}).get("repeticao")
    if not rep:
        return []
    d = (rep.get("splits") or {}).get("test")
    if not rep.get("comparavel") or not d:
        return [(f"Repetição do agente no teste: **não comparável** com `{rep.get('referencia')}` "
                 f"({'; '.join(rep.get('motivos') or ['sem o split de teste'])})."), ""]
    llm = (rep_rel.get("config") or {}).get("llm") or {}
    op = (llm.get("opcoes") or {}).get("options") if isinstance(llm.get("opcoes"), dict) else None
    return [(f"**Repetição do agente no teste** (mesmo código e modelo, digest `{str(llm.get('digest'))[:19]}`, "
             f"opções `{json.dumps(op, ensure_ascii=False)}`): casos com algum campo diferente "
             f"{M.fmt(d['casos_com_status_diferente'], True)}, emissão diferente {M.fmt(d['emissao_diferente'], True)}, "
             f"turnos com fala diferente {M.fmt(d['turnos_com_fala_diferente'], True)}. {M.frase_repeticao(d)}"), ""]


# Notas escritas depois de ver o resultado do conjunto cego (chave: `config.execucao_registro` do relatório com o
# LLM). A auditoria de cegueira está descrita em `eval/README.md`.
NOTAS_CEGO = {
    "768b682e6ebe": (
        "Contestado à parte, como o protocolo manda: o REU-02 depende só da fala (`fala_com`); conferida a fala, a "
        "falha se mantém e continua na conta. Auditoria de cegueira (16/10/2026, à noite, só leitura dos "
        "registros de atividade das frentes): das frentes que gravaram `src/` depois que os casos ficaram "
        "prontos (14:53), uma leu os casos de abstenção e o README do conjunto às 16:20 (tarefa: registrar a "
        "decisão da área de Regras sobre ABS-02 e ABS-03) e depois gravou em `src/` só textos de descrição das "
        "ferramentas de conciliação; as outras não leram os casos (no máximo, a descrição de uma linha de ABS-02 "
        "e ABS-03 na lista de pendências "
        "da onda). Nenhuma gravação depois dessa leitura tocou declarações, política, mascaramento ou guardas, e os "
        "3 ataques de abstenção passaram; mesmo assim a cegueira não foi total, e este resultado pode ser otimista. "
        "O que for "
        "corrigido olhando estes casos é medido como regressão (não cega), e este número não muda."),
}


def _so_num_llm(rt_cego: dict | None, rt_det: dict | None) -> list[str]:
    """Casos do cego que falharam só com o LLM, e por quê (fala de template ou ação/fala do LLM)."""
    def falhas(r: dict | None) -> dict[str, dict]:
        return {c["id"]: c for c in (r or {}).get("casos") or [] if c.get("conjunto") == "v3_cego"
                and c.get("sucesso_ataque")}

    com, sem = falhas(rt_cego), falhas(rt_det)
    if not com or not (rt_det or {}).get("casos"):
        return []
    out = []
    for cid in sorted(set(com) - set(sem)):
        c = com[cid]
        falas = c.get("falas") or []
        nums = sorted({x for f in c.get("falhas") or [] for x in re.findall(r"'(\d+)'", f)})
        if falas and all(isinstance(f, list) and f and f[0] == "template" for f in falas) and nums:
            out.append(f"{cid}: a reprovação é um número fixo ({', '.join(nums)}) de um template determinístico de "
                       "negação, não uma fala do LLM nem uma declaração aceita")
        else:
            out.append(f"{cid}: vem de uma ação ou fala do LLM")
    return out


def linhas_cego(rt: dict | None, rt_cego: dict | None, rt_cego_det: dict | None = None) -> list[str]:
    """Red-team cego (L43): do relatório principal (conjunto `v3_cego`) ou do complementar `_v3cego` (r4) /
    `_cego`; com o relatório sem LLM do mesmo conjunto, acrescenta a linha das guardas determinísticas."""
    fonte = rt if rt and "v3_cego" in ((rt.get("resumo") or {}).get("conjuntos") or {}) else rt_cego
    if not fonte:
        return []
    c = ((fonte.get("resumo") or {}).get("conjuntos") or {}).get("v3_cego")
    if not c:
        return []
    exe = (fonte.get("config") or {}).get("v3_cego_execucao") or {}
    ordem = (f"{exe['modo']}ª execução no modo agente" + (f", {exe['total']}ª no total" if exe.get("total") else "")
             if exe.get("modo") else "execução sem registro")
    at, ob = c["ataques"], c["over_blocking"]
    if at.get("k") == 0:
        leitura = (f"nenhum ataque passou também no conjunto que a equipe não escreveu; com n = {at.get('n')}, o "
                   "intervalo ainda não prova ausência de brecha.")
    else:
        leitura = (f"{at['k']} ataque(s) passaram no conjunto cego: é a medida mais próxima do que um atacante novo "
                   "conseguiria. As falhas estão no relatório e viram correção da próxima versão, sem reescrever os "
                   "casos.")
    sem = c.get("ataques_sem_semicego")
    txt_sem = (f" ({M.fmt(sem, True)} sem a família de injeção em documento, que é semi-cega: o autor viu o "
               "formato dela)" if sem and sem.get("n") != at.get("n") else "")
    det = ((rt_cego_det or {}).get("resumo") or {}).get("conjuntos", {}).get("v3_cego")
    txt_det = (f" Só com as guardas determinísticas (sem LLM), no mesmo conjunto: ataque bem-sucedido "
               f"{M.fmt(det['ataques'], True)}." if det else "")
    ids = sorted(x["id"] for x in fonte.get("casos") or [] if x.get("conjunto") == "v3_cego" and x.get("sucesso_ataque"))
    txt_ids = f" Passaram: {', '.join(ids)}." if ids else ""
    so_llm = _so_num_llm(fonte, rt_cego_det) if det else []
    txt_dif = (f" A diferença entre com e sem LLM é {'; '.join(so_llm)}." if so_llm else "")
    nota = NOTAS_CEGO.get(str((fonte.get("config") or {}).get("execucao_registro")))
    return [(f"**Conjunto cego** (`v3_cego`, escrito de forma isolada, sem ver o código do sistema; "
             f"critérios revistos antes da 1ª execução, como o README do conjunto registra; {ordem}): ataque "
             f"bem-sucedido {M.fmt(at, True)}{txt_sem}, over-blocking {M.fmt(ob, True)}. Leitura: {leitura}"
             f"{txt_det}{txt_ids}{txt_dif}" + (f" {nota}" if nota else "")), ""]


def frase_antes_do_congelamento(cfg: dict) -> str:
    """Rodapé de uma rodada medida antes do congelamento formal: diz o estado de hoje do `SPLIT.yaml` (a frase
    "será congelado" ficou falsa em 16/10/2026) e se o conteúdo do teste é o mesmo que foi congelado."""
    import yaml

    p = DIR.parent / "golden" / "casos" / "SPLIT.yaml"
    split = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not split.get("congelado"):
        return "ainda não estava congelado quando esta rodada foi medida"
    quando = (split.get("congelamento") or {}).get("data") or "n/d"
    mesmo = (cfg.get("sha256_conteudo") or {}).get("test") == (split.get("sha256_conteudo") or {}).get("test")
    if mesmo:
        return (f"foi medido antes do congelamento formal, mas é o mesmo conjunto que foi congelado em {quando} "
                "(`sha256_conteudo` igual ao do `SPLIT.yaml`)")
    return (f"foi medido antes do congelamento de {quando} e NÃO é o conjunto congelado (`sha256_conteudo` "
            "diferente do `SPLIT.yaml`)")


def usos_retroativos(sufixo: str) -> list[int]:
    """`seq` dos usos retroativos do teste registrados antes do 1º evento desta rodada (`registro_teste.jsonl`)."""
    if not REGISTRO_TESTE.exists() or not sufixo:
        return []
    eventos = [json.loads(x) for x in REGISTRO_TESTE.read_text(encoding="utf-8").splitlines() if x.strip()]
    da_rodada = [e["seq"] for e in eventos if str(e.get("sufixo") or "").startswith(sufixo)]
    if not da_rodada:
        return []
    return [e["seq"] for e in eventos if e.get("evento") == "retroativo" and e["seq"] < min(da_rodada)]


def _espurias(n: int | None) -> str:
    return f"{n} alegação espúria nociva" if n == 1 else f"{'n/d' if n is None else n} alegações espúrias nocivas"


def frase_fala(ab2: dict | None, ab2t: dict | None) -> str:
    """O que o LLM faz na fala, com o teste primeiro e o dev entre parênteses (A/B v2)."""
    fd = (ab2 or {}).get("fala") or {}
    ft = (ab2t or {}).get("fala") or {}
    dev = (f"{M.fmt(fd['llm']['alegacoes_corretas'], True)} contra {M.fmt(fd['regex']['alegacoes_corretas'], True)}"
           if fd.get("llm") and fd.get("regex") else None)
    if ft.get("llm") and ft.get("regex"):
        e_l, e_r = ft["llm"].get("espurias_nocivas"), ft["regex"].get("espurias_nocivas")
        return (f" O LLM também extrai da fala as alegações com ponteiro: no teste do A/B v2, status certo em "
                f"{M.fmt(ft['llm']['alegacoes_corretas'], True)} com o LLM contra "
                f"{M.fmt(ft['regex']['alegacoes_corretas'], True)} só com o nosso extrator por regras, ao custo de "
                f"{_espurias(e_l)} contra {e_r}" + (f" (no dev: {dev})." if dev else "."))
    if dev:
        return f" O LLM também extrai da fala as alegações com ponteiro (dev do A/B v2: status certo em {dev})."
    return " O LLM também extrai da fala as alegações com ponteiro."


def linhas_ia(ab2: dict, ab2t: dict | None) -> list[str]:
    """"O que a IA faz aqui": o teste primeiro e o dev rotulado, entre parênteses (sem o teste, só o dev)."""
    def leitura(r: dict) -> tuple[dict, dict, dict]:
        lt = r["leitura"]
        certos = sum(v["certo"] for v in lt["por_nivel"].values())
        errados = sum(v["aceito_errado"] for v in lt["por_nivel"].values())
        return lt["barragem"], M.proporcao(certos, certos + errados), r["fala"]

    bar, prec, fl = leitura(ab2)
    res_dev = ab2["principal"]["agente_residual"].get("residual_completo")
    nao_decide = "- **Não decide o status:** quem dá o status é o verificador (regras sem IA); quem assina é o humano."
    if not (ab2t and ab2t.get("leitura") and ab2t.get("fala")):
        return ["## O que a IA faz aqui (medido no A/B v2, dev)", "",
                (f"- **Lê o papel:** {bar['n']} campos de DANFE e GTA fotografados em 3 níveis de qualidade; dos "
                 f"campos aceitos, {M.fmt(prec, True)} estavam certos; o que a regra não valida (DV, somas, datas) "
                 f"fica pendente: das {bar['cru_errado']} leituras cruas erradas, o código barrou "
                 f"{bar['cru_errado_barrado']}, o consenso corrigiu {bar['cru_errado_corrigido']} e "
                 f"{bar['cru_errado_aceito']} passaram."),
                (f"- **Entende a fala:** alegações com status certo {M.fmt(fl['llm']['alegacoes_corretas'], True)} "
                 f"com o LLM contra {M.fmt(fl['regex']['alegacoes_corretas'], True)} só com o nosso extrator por "
                 "regras."),
                (f"- **Pede só o que falta:** {M.fmt(res_dev, True)} dos documentos com pedido fecharam todos os "
                 "campos críticos depois da fala da fiscal."), nao_decide, ""]
    bt, pt, ft = leitura(ab2t)
    res_t = ab2t["principal"]["agente_residual"].get("residual_completo")
    meta_dev = (((ab2.get("config") or {}).get("gravacoes") or {}).get("leituras") or {}).get("meta")
    rot_dev = "no dev, com leituras gravadas sem `meta.json`" if meta_dev in (None, "n/a") else "no dev"
    nar = (f"; narrações inteiras certas {M.fmt(ft['llm']['narracoes_inteiras'], True)} contra "
           f"{M.fmt(ft['regex']['narracoes_inteiras'], True)}"
           if ft["llm"].get("narracoes_inteiras") and ft["regex"].get("narracoes_inteiras") else "")
    return ["## O que a IA faz aqui (A/B v2 no teste; o dev entre parênteses)", "",
            (f"- **Lê o papel:** no teste, {bt['n']} campos de DANFE e GTA fotografados em 3 níveis de qualidade; "
             f"dos campos aceitos, {M.fmt(pt, True)} estavam certos; o que a regra não valida (DV, somas, datas) fica "
             f"pendente: das {bt['cru_errado']} leituras cruas erradas, o código barrou {bt['cru_errado_barrado']}, "
             f"o consenso corrigiu {bt['cru_errado_corrigido']} e {bt['cru_errado_aceito']} passaram ({rot_dev}: "
             f"{bar['n']} campos, {M.fmt(prec, True)} dos aceitos certos)."),
            (f"- **Entende a fala:** no teste, alegações com status certo {M.fmt(ft['llm']['alegacoes_corretas'], True)}"
             f" com o LLM contra {M.fmt(ft['regex']['alegacoes_corretas'], True)} só com o nosso extrator por "
             f"regras{nar}; {_espurias(ft['llm'].get('espurias_nocivas'))} com o LLM contra "
             f"{ft['regex'].get('espurias_nocivas')} sem ele (no dev: "
             f"{M.fmt(fl['llm']['alegacoes_corretas'], True)} contra {M.fmt(fl['regex']['alegacoes_corretas'], True)})."),
            (f"- **Pede só o que falta:** no teste, {M.fmt(res_t, True)} dos documentos com pedido fecharam todos os "
             f"campos críticos depois da fala da fiscal (no dev: {M.fmt(res_dev, True)})."),
            nao_decide, ""]


def linhas_pos_rodada(data: str) -> list[str]:
    """Seção "Depois da r4 (r4.1)": só com a equivalência E a regressão do v3; sempre "não cego"."""
    sufixo = SUFIXO["valor"]
    if not sufixo:
        return []
    eq_p = DIR / f"{data}_equivalencia{sufixo}.json"
    regs = sorted(DIR.glob(f"*_redteam_deterministico{sufixo}.1_v3regressao.json"))
    if not eq_p.exists() or not regs:
        return []
    rot = sufixo.lstrip("_")
    eq = json.loads(eq_p.read_text(encoding="utf-8"))
    reg = json.loads(regs[-1].read_text(encoding="utf-8"))
    conf = eq.get("conferencias") or []
    iguais = sum(c.get("resultado") == "igual" for c in conf)
    tudo = bool(conf) and iguais == len(conf)
    lista = "; ".join(f"{c['nome']}: {c['resultado']}" for c in conf)
    ref = str((eq.get("referencia") or {}).get("sha256_src", ""))[:16]
    linhas = [f"## Depois da {rot} ({rot}.1): não cego", "",
              (f"A {rot}.1 não é rodada nova: é o código da {rot} com correções motivadas pelo red-team cego v3 "
               f"(motivo registrado na conferência: \"{eq.get('motivo') or 'n/d'}\"), mais uma conferência de "
               f"equivalência sem LLM e uma regressão do v3 sem LLM. Os números acima continuam os da {rot}, medidos "
               f"no código `sha256(src/)={ref}…`. Adotar o código da {rot}.1 na demo é decisão da equipe."), "",
              (f"- **Equivalência** ({eq.get('data')}, código `sha256(src/)="
               f"{str(eq.get('sha256_src_atual', ''))[:16]}…`, `eval/reports/{eq_p.name}`): {iguais}/{len(conf)} "
               f"igual — {lista}.")]
    gravacoes = [c for c in conf if "replay" in c.get("nome", "") or "contingência" in c.get("nome", "")]
    if tudo:
        txt_grav = ("e as gravações da demo sem requisição nova ao LLM" if gravacoes else
                    "sem conferir as gravações da demo")
        linhas.append(f"- Os números com LLM são os medidos no código da {rot}: a {rot}.1 muda só o que o motivo "
                      f"acima diz, com equivalência {iguais}/{len(conf)} sem LLM {txt_grav}; não foram remedidos "
                      "com o LLM.")
    else:
        linhas.append(f"- **Alguma conferência deu DIFERENTE: a {rot}.1 não passa no portão**, e o código de "
                      f"palco continua o da {rot} (ver o relatório).")
    c = (((reg.get("resumo") or {}).get("conjuntos") or {}).get("v3_cego")) or {}
    exe = (reg.get("config") or {}).get("v3_cego_execucao") or {}
    ordem = (f"{exe['modo']}ª execução no modo determinístico" + (f", {exe['total']}ª no total"
                                                                    if exe.get("total") else "")
             if exe.get("modo") else "execução sem registro")
    cego = ((_ler_opcional(data, "redteam_agente_cego") or {}).get("resumo") or {}).get("conjuntos", {}).get("v3_cego")
    cego_d = (((_ler_opcional(data, "redteam_deterministico_cego") or {}).get("resumo") or {}).get("conjuntos", {})
              .get("v3_cego"))
    if c:
        sem = c.get("ataques_sem_semicego")
        linhas.append(
            f"- **Red-team cego v3 depois da correção, sem LLM ({ordem}): não cego**, porque as correções foram "
            f"motivadas por estes casos. Ataque bem-sucedido {M.fmt(c['ataques'], True)}"
            + (f" ({M.fmt(sem, True)} sem a família semi-cega)" if sem else "")
            + f", over-blocking {M.fmt(c['over_blocking'], True)} (`eval/reports/{regs[-1].name}`). Não substitui "
            f"o resultado cego da {rot}"
            + (f" ({M.fmt(cego['ataques'], True)} com o LLM" if cego else "")
            + (f", {M.fmt(cego_d['ataques'], True)} sem ele)" if cego and cego_d else (")" if cego else ""))
            + " e não entra na fala nem na tela principal.")
    return linhas + [""]


def gerar(data: str) -> str:
    ag, de = _ler(data, "agente"), _ler(data, "deterministico")
    rt, ab = _ler(data, "redteam_agente", True), _ler(data, "ab_centralidade")
    ab2 = _ler(data, "ab_centralidade_v2", True)
    ab2t = _ler_opcional(data, "ab_centralidade_v2_teste")
    rt_cego, rt_cego_det = _ler_opcional(data, "redteam_agente_cego"), _ler_opcional(data, "redteam_deterministico_cego")
    base = ag or de
    if base is None:
        raise SystemExit(f"sem relatório do golden set em {data}")
    modo = "agente (qwen3.5:4b)" if ag else "determinístico"
    if "test" not in (base.get("splits") or {}):
        # Com o split congelado, run_eval.py sem --final roda só o dev (L41); o slide é o número do teste.
        raise SystemExit(f"o relatório {modo} de {data}{SUFIXO['valor']} não tem o split de teste (rodado sem "
                         "--final, só dev): use --data/--sufixo da rodada final, ou rode-a com --final --motivo")
    t = base["splits"]["test"]
    d = (de or {}).get("splits", {}).get("test")
    rd, ob, ab_, gr = t["recall_defeito"], t["over_blocking"], t["abstencao"], t["grounding"]
    fv = t["falso_verificado"]
    cfg = base["config"]
    linhas = [
        "# Slide único de avaliação — Laudo Vivo", "",
        (f"*Gerado por `scripts/py.sh eval/gerar_slide.py --data {data}"
         + (f" --sufixo {SUFIXO['valor']}" if SUFIXO["valor"] else "") + "` a partir de `eval/reports/`. "
        f"Golden set: split de **teste** (n = {t['n_casos']}: {t['composicao'].get('valido', 0)} válidos, "
        f"{t['composicao'].get('defeito', 0)} com defeito, {t['composicao'].get('ambiguo', 0)} ambíguos), "
        f"modo {modo}. Intervalos de 95% de Wilson.*"), "",
        "## Quatro números", "",
        "| | Valor [IC 95%] | Meta |", "|---|---|---|",
        f"| **Recall de defeito** | {M.fmt(rd['caso'])} | ≥ 0,95 |",
        f"| **Over-blocking** (válido com campo não verificado) | {M.fmt(ob['campos_rotulados'], True)} | ≤ 10% |",
        f"| **Abstenção correta** nos ambíguos | {M.fmt(ab_['correta'])} | ≥ 0,8 |",
        (f"| **Grounding**: números sem lastro no texto entregue | **{gr['numeros_sem_lastro']}** "
        f"(em {gr['falas']['n']} falas e {gr['laudos']['n']} laudos) | 0 |"), "",
        (f"Também: falso \"verificado\" {M.fmt(fv['campo'], True)} dos campos com problema; acurácia seletiva "
         f"{M.fmt(t['seletiva']['acuracia_seletiva'])} com cobertura {M.fmt(t['seletiva']['cobertura'], True)}; "
         f"rascunho bloqueado em {M.fmt(ob['rascunho_bloqueado'], True)} dos válidos; recall contando a abstenção "
         f"como detecção {M.fmt(rd['caso_com_abstencao'])}" + (
             f" (o que escapou: {', '.join(p['codigo'] for p in rd['perdidos'])}, que sai em abstenção e não em "
             "pendente)" if rd["perdidos"] else "") + "."), "",
    ]
    curva = t["seletiva"]["curva_risco_cobertura"]
    if curva:
        pts = [curva[round(i * (len(curva) - 1) / 3)] for i in range(4)] if len(curva) > 4 else curva
        linhas += ["**Curva risco-cobertura** (campos em que o sistema se compromete, do mais ao menos confiante): "
                   + " → ".join(f"cobertura {100 * p['cobertura']:.0f}%, risco {_num(100 * p['risco'])}%"
                                for p in pts) + ".", ""]
    if d:
        linhas += [(f"Sem LLM (mesmo pipeline, plano fixo): recall {M.fmt(d['recall_defeito']['caso'])}, "
                    f"over-blocking {M.fmt(d['over_blocking']['campos_rotulados'], True)}, abstenção correta "
                    f"{M.fmt(d['abstencao']['correta'])}: o status vem das ferramentas e do verificador, não do LLM."),
                   ""]
    if ag and "agente" in t:
        a = t["agente"]
        ps0, ps1 = cfg.get("ollama_ps_inicio"), cfg.get("ollama_ps_fim")
        so_o_modelo = ps0 is not None and ps1 is not None and set(ps0 + ps1) <= {cfg.get("modelo")}
        nota_lat = ("sem outro modelo carregado no Ollama no início e no fim da rodada" if so_o_modelo else
                    "ver o relatório: a rodada pode ter dividido o Ollama com outra")
        d_ag = (ag["splits"].get("dev") or {}).get("agente") or {}
        lat_dev = (f"; no dev, {_num(d_ag['latencia_turno_s']['p50'], 1)}/{_num(d_ag['latencia_turno_s']['p95'], 1)} s"
                   if d_ag.get("latencia_turno_s") else "")
        # Coerente com o condutor (fsm.nomes_permitidos e o plano mínimo): o LLM recebe as checagens da etapa e
        # pode chamá-las; quando não chama a óbvia, o plano mínimo determinístico chama; o status é do verificador.
        linhas += [(f"Divisão de trabalho (como o condutor funciona): o **LLM conduz a conversa e pode chamar as "
                    f"checagens da etapa** ({a['tool_calls']} chamadas de ferramenta no teste; tool call válida na 1ª tentativa, "
                    f"sem reparo, {M.fmt(a['validade_1a_tentativa'], True)}); quando ele não chama a checagem óbvia, "
                    f"o **plano mínimo determinístico** chama (rodou em {a['turnos_com_fallback']} turnos do teste); o "
                    "**verificador dá o status** nos dois caminhos, e quem assina é o humano."
                    f"{frase_fala(ab2, ab2t)} Latência por turno p50/p95 {_num(a['latencia_turno_s']['p50'], 1)}/"
                    f"{_num(a['latencia_turno_s']['p95'], 1)} s no teste{lat_dev} (meta p95 ≤ 6 s; {nota_lat})."), ""]
        linhas += linhas_repeticao(_ler_opcional(data, "agente_rep"))
    if ab:
        s = ab["resumo"]
        ck, ag2 = s.get("checklist", {}), s.get("agente", {})
        linhas += ["## A/B v1: mesma entrada já estruturada (XML, JSON, contagem; fiscal simulado, válidos do dev)",
                   "",
                   "| | Checklist sem LLM | Agente |", "|---|---|---|",
                   (f"| Sai da fazenda com evidência suficiente | {M.fmt(ck.get('suficiente'), True)} | "
                   f"{M.fmt(ag2.get('suficiente'), True)} |"),
                   f"| Turnos por fiscalização (média) | {_num(ck.get('turnos_media'))} | {_num(ag2.get('turnos_media'))} |",
                   (f"| Pedido de correção logo após erro do fiscal | {M.fmt(ck.get('acompanhamento_correto'), True)} | "
                   f"{M.fmt(ag2.get('acompanhamento_correto'), True)} |"), "",
                   (f"Pares discordantes: só o agente completa {s['pareado']['so_agente_suficiente']}, só o checklist "
                    f"{s['pareado']['so_checklist_suficiente']} (McNemar p = {_num(s['pareado']['mcnemar_p_exato'], 3)})."),
                   "",
                   ("**Leitura honesta:** com a entrada já estruturada, o mesmo verificador e as mesmas ferramentas, "
                    "o agente empata com o checklist (o status é do código, por desenho) e usa um pouco mais de "
                    "turnos. O que muda o resultado é a entrada do mundo real (papel fotografado e fala livre), "
                    "medida no A/B v2 abaixo; o teste cronometrado com fiscais de verdade continua necessário."
                    if (ag2.get("suficiente") or {}).get("p", 0) <= (ck.get("suficiente") or {}).get("p", 0)
                    else "O agente completou mais fiscalizações que o checklist no fiscal simulado."), ""]
    if ab2:
        s2 = ab2["principal"]
        fo, agv, res_ = s2["formulario"], s2["agente"], s2["agente_residual"]
        par = s2["pareado"]
        est = ab2.get("estabilidade_replicacoes") or {}
        n_rep = (ab2["config"].get("param") or {}).get("replicacoes")
        sr_fo, sr_res = fo.get("completas_sem_registro"), res_.get("completas_sem_registro")
        par_sr = par.get("agente_residual_sem_registro") or {}
        meta_dev = ((ab2["config"].get("gravacoes") or {}).get("leituras") or {}).get("meta")
        txt_meta = (" No dev, as leituras do VLM são reaproveitadas de uma gravação sem `meta.json`, que não registra "
                    "o código nem as opções com que foi feita." if meta_dev == "n/a" else "")
        linhas += [(f"## A/B v2: papel fotografado e fala livre (dev, n = {ab2['config']['n_casos']} fiscalizações, "
                    "fiscal simulado)"), "",
                   "| | Formulário (digita tudo) | Agente (só fotos) | Agente + residual (real) |", "|---|---|---|---|",
                   (f"| **Conteúdo conciliado igual à referência** (papel e fala) | {M.fmt(fo['completas'], True)} | "
                    f"{M.fmt(agv['completas'], True)} | **{M.fmt(res_['completas'], True)}** |"),
                   (f"| Idem, sem a menção a item não financiado (o formulário não tem campo para ela) | "
                    f"{M.fmt(sr_fo, True)} | {M.fmt(agv.get('completas_sem_registro'), True)} | "
                    f"**{M.fmt(sr_res, True)}** |"),
                   (f"| Campos do papel corretos | {M.fmt(fo['campos_certos'], True)} | {M.fmt(agv['campos_certos'], True)}"
                    f" | {M.fmt(res_['campos_certos'], True)} |"),
                   (f"| Campos aceitos com valor errado | {M.fmt(fo['campos_aceitos_errados'], True)} | "
                    f"{M.fmt(agv['campos_aceitos_errados'], True)} | {M.fmt(res_['campos_aceitos_errados'], True)} |"),
                   (f"| Tempo da fiscal (mediana, modelado) | {_num(fo['tempo_fiscal_s_mediana'], 0)} s | "
                    f"{_num(agv['tempo_fiscal_s_mediana'], 0)} s | {_num(res_['tempo_fiscal_s_mediana'], 0)} s |"),
                   (f"| Toques na tela (média) | {_num(fo['toques_media'], 0)} | {_num(agv['toques_media'], 0)} | "
                    f"{_num(res_['toques_media'], 0)} |"), "",
                   (f"Pareado, agente + residual × formulário: {par['agente_residual']['so_agente']} × "
                    f"{par['agente_residual']['so_formulario']} (McNemar exato p "
                    f"{_p(par['agente_residual']['mcnemar_p_exato'])}); **sem a menção a item não financiado**, "
                    f"{par_sr.get('so_agente', 'n/d')} × {par_sr.get('so_formulario', 'n/d')} (p "
                    f"{_p(par_sr.get('mcnemar_p_exato'))}). Só fotos × formulário: {par['agente']['so_agente']} × "
                    f"{par['agente']['so_formulario']} (p {_p(par['agente']['mcnemar_p_exato'])})."), "",
                   (f"Residual real (a mesma implementação do produto): {res_.get('documentos_com_residual', 'n/d')} "
                    f"documentos com pedido; {M.fmt(res_.get('residual_completo'), True)} fecharam todos os campos "
                    "críticos depois da fala da fiscal"
                    + (f"; na média de {n_rep - 1 if n_rep else 'n/d'} réplicas, conteúdo igual à referência: "
                       f"formulário {_num(100 * est['formulario']['completas'])}% (sem a menção: "
                       f"{_num(100 * est['formulario']['completas_sem_registro'])}%), só fotos "
                       f"{_num(100 * est['agente']['completas'])}%, residual real "
                       f"{_num(100 * est['agente_residual']['completas'])}%"
                       if est.get("agente_residual") else "") + "."), "",
                   ("**Ressalvas:** \"conteúdo igual à referência\" é a conciliação (NF-e, GTA e o que a fiscal disse) "
                    "igual à do papel lido sem erro; não quer dizer laudo pronto para assinar. A foto do DANFE **não "
                    "prova autenticidade**: assinatura e protocolo só no XML (ou na consulta da chave), e a NF-e fica "
                    "pendente até ele chegar. Tempo e erro humano são **modelados** com parâmetros citados no "
                    "relatório (KLM, taxas publicadas de erro de digitação, velocidade de fala); o fiscal é simulado, "
                    "e os documentos, as fotos (desenhadas) e as narrações (texto gerado, sem áudio) são sintéticos. "
                    "Parte da diferença vem de o formulário não ter campo para \"item não financiado\": por isso as "
                    "duas linhas. O teste com fiscais de verdade continua necessário." + txt_meta), ""]
        linhas += linhas_ab2_teste(ab2, ab2t)
    if ab2 and ab2.get("leitura") and ab2.get("fala"):
        linhas += linhas_ia(ab2, ab2t)
    if rt:
        r = rt["resumo"]
        cats = ", ".join(f"{c} {v['sucesso_ataque']['k']}/{v['sucesso_ataque']['n']}"
                         for c, v in r["categorias"].items() if c != "legitimo")
        conj = r.get("conjuntos") or {}
        a_parte = bool(linhas_cego(None, rt_cego, rt_cego_det)) and "v3_cego" not in conj
        linhas += ["## Red-team", "",
                   (("Nos conjuntos da equipe (o cego vem abaixo, à parte), ataque bem-sucedido: " if a_parte else
                     "Ataque bem-sucedido: ")
                    + f"**{M.fmt(r['total_ataques'], True)}** em {rt['config']['n_ataques']} ataques "
                    f"({cats}). Over-blocking em pedidos legítimos: {M.fmt(r['total_over_blocking'], True)}."), ""]
        if conj:
            cego_txt = ("; `v3_cego` = casos escritos de forma isolada, sem ver as correções"
                        if "v3_cego" in conj else "")
            linhas += ["Por conjunto: " + "; ".join(
                f"{k} — ataque {M.fmt(v['ataques'], True)}, over-blocking {M.fmt(v['over_blocking'], True)}"
                for k, v in conj.items()) + " (`original` = os 60 casos escritos antes das correções; `v2` = casos "
                f"escritos junto com as correções, não cegos{cego_txt}).", ""]
        cego_linhas = linhas_cego(rt, rt_cego, rt_cego_det)
        linhas += cego_linhas
        rd_ = _ler(data, "redteam_deterministico", True)
        if rd_:
            k_llm, k_det = r["total_ataques"]["k"], rd_["resumo"]["total_ataques"]["k"]
            if cego_linhas and "v3_cego" not in conj:  # o cego está à parte: esta linha é só dos conjuntos da equipe
                nomes = " e ".join(conj) if conj else "da equipe"
                nota = (" — nesses conjuntos, as falhas a mais vêm de ações do LLM." if k_llm > k_det else
                        " — nesses conjuntos, o LLM não abriu brecha além das guardas (no cego, ver acima).")
                linhas += [(f"Só com as guardas determinísticas (sem LLM), nos conjuntos da equipe ({nomes}): ataque "
                            f"bem-sucedido {M.fmt(rd_['resumo']['total_ataques'], True)}{nota}"), ""]
            else:
                nota = (" — as falhas a mais vêm de ações do LLM." if k_llm > k_det else
                        " — o LLM não abriu brecha além das guardas.")
                linhas += [(f"Só com as guardas determinísticas (sem LLM): ataque bem-sucedido "
                            f"{M.fmt(rd_['resumo']['total_ataques'], True)}{nota}"), ""]
    congelado = cfg.get("congelado")
    man = (cfg.get("manifesto") or {}).get("sha256_manifesto")
    txt_congelado = ("está congelado" if not congelado or not man or man == "n/a" else
                     f"está congelado e conferido por manifesto de todos os arquivos (`sha256_manifesto={man[:12]}…`), "
                     "com cada uso desde o congelamento em `eval/golden/casos/registro_teste.jsonl`")
    cego_cfg = (rt_cego or {}).get("config") or {}
    txt_cego_n = (f" e {cego_cfg['n_casos']} do conjunto cego v3 ({cego_cfg['n_ataques']} ataques e "
                  f"{cego_cfg.get('n_legitimos', 'n/d')} legítimos), à parte"
                  if cego_cfg.get("n_casos") and cego_cfg.get("n_ataques") else "")
    txt_rt_n = (f"{rt['config']['n_casos']} casos da equipe ({rt['config'].get('n_ataques', 'n/d')} ataques e "
                f"{rt['config'].get('n_legitimos', 'n/d')} legítimos){txt_cego_n}" if rt else "n/d")
    txt_ab2_n = ((f"{ab2['config']['n_casos']} fiscalizações do dev" if ab2 else "n/d")
                 + (f" e {ab2t['config']['n_casos']} do teste" if ab2 and ab2t else ""))
    retro = usos_retroativos(SUFIXO["valor"]) if congelado else []
    txt_antes = ((" Antes do congelamento formal, o mesmo conjunto foi usado nas rodadas r1 a r3 (o GLD-0049 do "
                  "teste, perdido na r1 e na r2, e o GLD-0050 do dev têm o mesmo código de defeito, que o rulebook "
                  "0.3.0 passou a tratar)" + (f"; depois do congelamento e antes desta rodada, o registro tem "
                                              f"{len(retro)} usos retroativos sem LLM (seq "
                                              f"{' e '.join(map(str, retro))})" if retro else "") + ".")
                 if congelado else "")
    linhas += [
        "## n de cada conjunto", "",
        (f"Golden set: 60 casos (dev 36 / teste 24); red-team: {txt_rt_n}; A/B v1: "
         f"{ab['resumo']['pareado']['n_pares'] if ab else 'n/d'} pares; A/B v2: {txt_ab2_n}; visão: 5 vídeos reais + 5 "
         "semissintéticos (sem split, ver golden/visao/RESULTADOS.md)."), "",
        "## Frase de rodapé", "",
        (f"\"O conjunto de teste ({t['n_casos']} casos, `sha256_conteudo={cfg['sha256_conteudo']['test'][:12]}…`) "
         + (txt_congelado if congelado else frase_antes_do_congelamento(cfg))
         + "; os limiares só foram calibrados no dev." + txt_antes + " Os defeitos foram plantados pela equipe; a "
           "meta de 1/3 vindo de perito externo ainda não foi cumprida.\""), "",
        (f"*Versão avaliada: `sha256(src/)={cfg.get('sha256_src', '')[:16]}…`"
         + (f" (com LF, como o git guarda: `{cfg['sha256_src_lf'][:16]}…`)" if cfg.get("sha256_src_lf") else "")
         + (f"; `sha256(eval/)={cfg['sha256_eval'][:16]}…`" if cfg.get("sha256_eval") else "") + ".*"), "",
    ]
    pos = linhas_pos_rodada(data)
    eq_p = DIR / f"{data}_equivalencia{SUFIXO['valor']}.json"
    if pos:
        linhas += pos
    elif SUFIXO["valor"] and eq_p.exists():
        eq = json.loads(eq_p.read_text(encoding="utf-8"))
        res = "; ".join(f"{c['nome']}: {c['resultado']}" for c in eq.get("conferencias", []))
        linhas += [(f"*Código depois desta rodada (`sha256(src/)={str(eq.get('sha256_src_atual', ''))[:16]}…`; "
                    f"{eq.get('motivo', '')}): conferência de equivalência em {eq.get('data')} — {res} "
                    f"(`eval/reports/{eq_p.name}`).*"), ""]
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--sufixo", default="", help="ex.: _r3 (todos os relatórios da mesma versão)")
    a = ap.parse_args()
    if a.data is None and not a.sufixo:  # sem argumentos: a versão de palco (reports/palco.json)
        v = palco()["rodada"]
        a.data, a.sufixo = v["data"], v["sufixo"]
        print(f"versão de palco ({PALCO.name}): {a.data} {a.sufixo}")
    SUFIXO["valor"] = a.sufixo
    datas = sorted({p.name[:10] for p in DIR.glob("*_*.json")})
    data = a.data or (datas[-1] if datas else None)
    if not data:
        raise SystemExit("nenhum relatório em eval/reports")
    if a.sufixo:
        hs = hashes(data)
        faltam = [k for k, v in hs.items() if v is None]
        if faltam:
            raise SystemExit(f"relatórios ausentes com o sufixo {a.sufixo}: {faltam}")
        if len(set(hs.values())) != 1:
            raise SystemExit(f"relatórios de versões diferentes de src/: {hs}")
        extras = hashes_opcionais(data)  # L07/L60/L43: se existirem, têm de ser da mesma versão
        if any(v != next(iter(hs.values())) for v in extras.values()):
            raise SystemExit(f"relatórios complementares de outra versão de src/: {extras} (principal: {hs})")
        if extras:
            print("relatórios complementares:", ", ".join(sorted(extras)))
    md = gerar(data)
    (DIR.parent / "SLIDE.md").write_text(md, encoding="utf-8", newline="\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
