"""Harness comum da avaliação do Laudo Vivo (golden set, red-team e A/B de centralidade).

Roda o **condutor de verdade** (`laudo.agent.condutor.Condutor`) sobre os casos do golden set, com as
ferramentas reais do `REGISTRO`, o verificador, `avaliar_regras` e a política. O que muda entre os modos é só o
LLM: `provedor=None` (determinístico: plano mínimo do condutor, sem LLM) ou um `OllamaProvider` (agente).

Contornos do harness (documentados em eval/README.md; nenhum altera `src/`):

1. **Relógio simulado.** O caso aconteceu em `data_fiscalizacao` (agosto/setembro de 2026), mas a
   `Evidencia.recebida_em` do app é `datetime.now()`. Sem contorno, `integridade_foto` reprovaria toda foto
   como FOTO_ANTIGA (> 72 h). O harness troca a classe `Evidencia` usada por `laudo.agent.estado` por uma
   subclasse idêntica cujo `recebida_em` padrão vem de `RELOGIO.agora` (o `recebida_em` do caso).
2. **Vídeo simulado.** Os vídeos dos casos sintéticos não existem (`sintetico://`). `contar_bovinos_video` é
   substituída por um simulador com o MESMO esquema de entrada, que devolve a `saida_simulada_contador` do caso
   e aplica os limiares de abstenção do contador real (`ParametrosContagem`). A visão é avaliada à parte, com
   vídeo real, em `eval/golden/visao/`.
3. **Índice de fotos isolado por caso** (`laudo.tools.foto.INDICE_PADRAO` aponta para o diretório do caso):
   sem isso o índice global em `dados_locais/` acusaria duplicata entre rodadas e entre casos.
4. **Campos do cadastro que o caso guarda fora de `operacao`:** `Operacao.codigo_estabelecimento` vem de
   `projeto.propriedade` e `Operacao.tomador_ref` vira `sha256:<hash do documento do tomador>` (o formato que o
   condutor usa para conferir as partes da NF-e/GTA sem CPF/CNPJ em claro). O resto o próprio condutor preenche.
5. Integração `ideal` (só com `--integracao ideal`): `conciliar_gta` recebe todas as GTAs do caso de uma vez e
   `conciliar_nfe`/`conciliar_gta` devolvem `data.status` (pior critério). Serve de teto para medir quanto se
   perde na integração atual; nunca é o número do slide.

Congelamento verificável (L41) e relatórios reprodutíveis (L59), também aqui:

- `golden/casos/MANIFESTO.yaml`: sha256 de TODOS os arquivos dos 60 casos (não só do `caso.yaml`), mais um hash dos
  campos de `SPLIT.yaml` que definem o split. `conferir_manifesto()` acusa arquivo mudado, sumido ou novo.
- Execução que toca o split de teste congelado exige `--final` e `--motivo` (`checar_uso_do_teste`) e fica no
  registro append-only `golden/casos/registro_teste.jsonl` (`uso_do_teste`): um evento ao começar (antes do 1º
  caso, para que uma rodada abortada também conte) e outro ao terminar, encadeados por sha256.
- `config_reprodutivel()`: sha256(src/), sha256(eval/), manifesto, modelo com digest e versão do Ollama (ou "n/a"),
  opções de geração e versões das bibliotecas, para o `config` de cada relatório.

Linha de comando: `scripts/py.sh eval/harness.py --conferir` (manifesto, split e cadeia do registro),
`--registro` (usos do teste) e `--gerar-manifesto` (só uma vez, no estado congelado; ver `main`).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

REPO = Path(__file__).resolve().parents[1]
DIR_CASOS = REPO / "eval" / "golden" / "casos"
DIR_TMP_PADRAO = REPO / "dados_locais" / "eval"
FUSO = timezone(timedelta(hours=-3))
PRECEDENCIA = ["divergente", "pendente", "abstencao", "verificado"]  # OP-agregacao-item
NAO_VERIFICADO = {"divergente", "pendente", "abstencao"}
NA = "n/a"  # o que se registra quando não há LLM/Ollama (L59)


def hash_src() -> str:
    """sha256 de `src/` (código, rulebooks, prompts e templates): identifica a versão avaliada no relatório,
    já que o repositório ainda não tem commits."""
    h = hashlib.sha256()
    for p in sorted((REPO / "src").rglob("*")):
        if p.is_file() and p.suffix in (".py", ".yaml", ".md", ".j2") and "__pycache__" not in p.parts:
            h.update(p.relative_to(REPO).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


# Fala do LLM que afirma ter registrado/recebido/anotado algo sem nenhuma ação executada no turno (heurística;
# os exemplos vão para revisão manual no relatório).
_AFIRMA_ACAO = None


def afirma_acao_sem_lastro(fala: str, acoes: list[dict[str, Any]], fatos: list[str] | None = None,
                           alegacoes: list[Any] | None = None) -> bool:
    """Oráculo independente do sistema (heurística): a parte da fala que veio do LLM (sem as frases de template
    em `fatos`) diz que registrou/recebeu/anotou algo, sem ação executada nem alegação registrada no turno."""
    import re

    global _AFIRMA_ACAO
    if _AFIRMA_ACAO is None:
        _AFIRMA_ACAO = re.compile(
            r"\b(?:registrad[oa]s?|registrei|recebid[oa]s?|recebi|anotad[oa]s?|anotei|salv[oa]s?|salvei)\b",
            re.IGNORECASE)
    texto = fala or ""
    for f in fatos or []:
        texto = texto.replace(f, " ")
    feitas = [a for a in acoes if a.get("permitido") and a.get("ok") is not False and a.get("acao") not in
              ("pedir_evidencia", "explicar_regra")]
    return bool(_AFIRMA_ACAO.search(texto) and not feitas and not alegacoes)


# ---------------------------------------------------------------------------
# Golden set
# ---------------------------------------------------------------------------


def carregar_split() -> dict[str, Any]:
    return yaml.safe_load((DIR_CASOS / "SPLIT.yaml").read_text(encoding="utf-8"))


def conferir_split(split: dict[str, Any]) -> list[str]:
    """Confere os hashes do SPLIT.yaml (listas dev/test e cada caso.yaml). Devolve problemas encontrados."""
    problemas = []
    listas = {"dev": split["dev"], "test": split["test"]}
    h = hashlib.sha256(json.dumps(listas, sort_keys=True).encode()).hexdigest()
    if h != split["sha256_split"]:
        problemas.append(f"sha256_split não confere ({h[:12]} != {split['sha256_split'][:12]})")
    for c in split["casos"]:
        b = (DIR_CASOS / c["id"] / "caso.yaml").read_bytes()
        if hashlib.sha256(b).hexdigest() != c["sha256_caso"]:
            problemas.append(f"{c['id']}: caso.yaml mudou depois do split")
    return problemas


# ---------------------------------------------------------------------------
# Congelamento verificável (L41): manifesto, --final e registro append-only
# ---------------------------------------------------------------------------

# Campos de SPLIT.yaml que definem o split; texto livre (`congelamento`, `nota`) pode ser corrigido sem invalidar.
CAMPOS_CONGELADOS = ("gerador", "composicao", "frac_dev", "estratos", "sha256_split", "sha256_conteudo", "dev",
                     "test", "casos")
_FORA_DO_MANIFESTO = {"SPLIT.yaml", "MANIFESTO.yaml", "registro_teste.jsonl", "registro_teste.jsonl.trava"}
_ZERO = "0" * 64


def _dir_casos(dir_casos: Path | None = None) -> Path:
    return Path(dir_casos) if dir_casos is not None else DIR_CASOS  # global lido na hora (o piloto L42 troca)


def caminho_manifesto(dir_casos: Path | None = None) -> Path:
    return _dir_casos(dir_casos) / "MANIFESTO.yaml"


def caminho_registro(dir_casos: Path | None = None) -> Path:
    """`registro_teste.jsonl` do split (ou `LAUDO_REGISTRO_TESTE`, usado pelos testes para não sujar o real)."""
    env = os.environ.get("LAUDO_REGISTRO_TESTE")
    return Path(env) if env else _dir_casos(dir_casos) / "registro_teste.jsonl"


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return f"<fora do repositório>/{Path(p).name}"


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def digest_lista(pares: Iterable[tuple[str, str]]) -> str:
    """sha256 das linhas `caminho:sha256`, em ordem de caminho (o mesmo formato do `sha256_conteudo`)."""
    return hashlib.sha256("".join(f"{c}:{h}\n" for c, h in sorted(pares)).encode()).hexdigest()


def sha256_campos_congelados(split: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: split.get(k) for k in CAMPOS_CONGELADOS}, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def arquivos_do_split(dir_casos: Path | None = None) -> dict[str, str]:
    """caminho relativo a `casos/` → sha256, de todo arquivo do diretório (menos SPLIT.yaml, o próprio manifesto
    e o registro, que têm tratamento próprio)."""
    base = _dir_casos(dir_casos)
    return {p.relative_to(base).as_posix(): sha256_arquivo(p) for p in sorted(base.rglob("*"))
            if p.is_file() and p.name not in _FORA_DO_MANIFESTO and "__pycache__" not in p.parts}


def montar_manifesto(split: dict[str, Any], dir_casos: Path | None = None,
                     conferencias: list[str] | None = None) -> dict[str, Any]:
    """Manifesto do estado atual do diretório de casos (todos os arquivos, por split)."""
    base = _dir_casos(dir_casos)
    de_quem = {cid: s for s in ("dev", "test") for cid in split[s]}
    arquivos: dict[str, dict[str, Any]] = {}
    for c, h in arquivos_do_split(base).items():
        s = de_quem.get(c.split("/", 1)[0], "meta" if "/" not in c else "fora_das_listas")
        arquivos[c] = {"split": s, "bytes": (base / c).stat().st_size, "sha256": h}
    resumo: dict[str, Any] = {}
    for s in ("dev", "test", "meta", "fora_das_listas"):
        sel = [(c, e["sha256"]) for c, e in arquivos.items() if e["split"] == s]
        if sel or s in ("dev", "test"):
            resumo[s] = ({"n_casos": len(split[s])} if s in split else {}) | {
                "n_arquivos": len(sel), "sha256": digest_lista(sel)}
    campos = sha256_campos_congelados(split)
    total = digest_lista([(c, e["sha256"]) for c, e in arquivos.items()] + [("SPLIT.yaml#campos", campos)])
    resumo["total"] = {"n_arquivos": len(arquivos), "sha256": total}
    return {
        "versao": 1,
        "sha256_manifesto": total,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gerado_por": "scripts/py.sh eval/harness.py --gerar-manifesto",
        "referencia": {"sha256_split": split.get("sha256_split"), "sha256_conteudo": split.get("sha256_conteudo"),
                       "congelado": split.get("congelado"),
                       "congelamento": (split.get("congelamento") or {}).get("conferido_em")},
        "split_yaml": {"sha256_campos_congelados": campos, "campos": list(CAMPOS_CONGELADOS),
                       "sha256_arquivo": sha256_arquivo(base / "SPLIT.yaml")},
        "conferencias_na_geracao": conferencias or [],
        "resumo": resumo,
        "arquivos": arquivos,
    }


def escrever_manifesto(man: dict[str, Any], caminho: Path) -> None:
    """YAML com uma linha por arquivo (diff legível) e LF (o diretório tem `* -text` no .gitattributes)."""
    def v(x: Any) -> str:
        return json.dumps(x, ensure_ascii=False)  # JSON escalar também é YAML válido

    cab = ["# Manifesto do golden set congelado (L41): sha256 de TODOS os arquivos dos casos, por split.",
           "# Conferido por eval/run_eval.py antes de rodar e por tests/unit/test_eval_congelamento.py. Não edite à mão:",
           "# arquivo mudado, sumido ou novo em golden/casos/ invalida o congelamento (ver eval/README.md).",
           f"versao: {man['versao']}", f"sha256_manifesto: {man['sha256_manifesto']}",
           f"gerado_em: {v(man['gerado_em'])}", f"gerado_por: {v(man['gerado_por'])}", "referencia:"]
    ref = man["referencia"]
    cab += [f"  sha256_split: {ref['sha256_split']}", "  sha256_conteudo:"]
    cab += [f"    {k}: {h}" for k, h in (ref.get("sha256_conteudo") or {}).items()]
    cab += [f"  congelado: {v(ref['congelado'])}", f"  congelamento: {v(ref['congelamento'])}", "split_yaml:",
            f"  sha256_campos_congelados: {man['split_yaml']['sha256_campos_congelados']}",
            f"  campos: {v(man['split_yaml']['campos'])}",
            ("  sha256_arquivo: " + man["split_yaml"]["sha256_arquivo"]
             + "  # informativo: correção de texto livre no SPLIT.yaml não invalida")]
    conf = man["conferencias_na_geracao"]
    cab += ["conferencias_na_geracao:", *[f"- {v(c)}" for c in conf]] if conf else ["conferencias_na_geracao: []"]
    cab.append("resumo:")
    for s, r in man["resumo"].items():
        cab.append(f"  {s}: {{{', '.join(f'{k}: {x}' for k, x in r.items())}}}")
    cab.append("arquivos:")
    cab += [f"  {c}: {{split: {e['split']}, bytes: {e['bytes']}, sha256: {e['sha256']}}}"
            for c, e in man["arquivos"].items()]
    Path(caminho).write_bytes(("\n".join(cab) + "\n").encode("utf-8"))


def carregar_manifesto(dir_casos: Path | None = None) -> dict[str, Any] | None:
    p = caminho_manifesto(dir_casos)
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def conferir_manifesto(split: dict[str, Any] | None = None, dir_casos: Path | None = None) -> list[str]:
    """Problemas do diretório de casos contra o MANIFESTO.yaml (vazio = tudo igual ao congelado)."""
    base = _dir_casos(dir_casos)
    man = carregar_manifesto(base)
    if man is None:
        return [f"{_rel(caminho_manifesto(base))} ausente (gere uma vez com `eval/harness.py --gerar-manifesto`)"]
    split = split if split is not None else yaml.safe_load((base / "SPLIT.yaml").read_text(encoding="utf-8"))
    problemas = []
    atuais = arquivos_do_split(base)
    esperados = man.get("arquivos") or {}
    for c, e in esperados.items():
        if c not in atuais:
            problemas.append(f"{c}: sumiu")
        elif atuais[c] != e["sha256"]:
            problemas.append(f"{c}: conteúdo mudou (sha256 {atuais[c][:12]} != {e['sha256'][:12]})")
    problemas += [f"{c}: arquivo novo, fora do manifesto" for c in sorted(set(atuais) - set(esperados))]
    if sha256_campos_congelados(split) != (man.get("split_yaml") or {}).get("sha256_campos_congelados"):
        problemas.append("SPLIT.yaml: listas, hashes, composição ou gerador mudaram depois do manifesto")
    if split.get("sha256_split") != (man.get("referencia") or {}).get("sha256_split"):
        problemas.append("SPLIT.yaml: sha256_split diferente do registrado no manifesto")
    return problemas


def info_manifesto(split: dict[str, Any] | None = None, dir_casos: Path | None = None) -> dict[str, Any]:
    """Resumo do manifesto para o `config` dos relatórios e para o registro de uso do teste."""
    man = carregar_manifesto(dir_casos)
    if man is None:
        return {"arquivo": NA, "sha256_manifesto": NA, "conferido": "manifesto ausente"}
    problemas = conferir_manifesto(split, dir_casos)
    res = man.get("resumo") or {}
    return {"arquivo": _rel(caminho_manifesto(dir_casos)), "sha256_manifesto": man.get("sha256_manifesto"),
            "sha256_arquivos_test": (res.get("test") or {}).get("sha256"),
            "sha256_arquivos_dev": (res.get("dev") or {}).get("sha256"),
            "n_arquivos": (res.get("total") or {}).get("n_arquivos"),
            "conferido": "ok" if not problemas else problemas[:5] + ([f"... e mais {len(problemas) - 5}"]
                                                                       if len(problemas) > 5 else [])}


def toca_teste(split: dict[str, Any], grupos: dict[str, list[str]]) -> bool:
    """A execução usa algum caso do split de teste? (por id, então `--casos GLD-0003` também conta)."""
    teste = set(split.get("test") or [])
    return any(cid in teste for ids in grupos.values() for cid in ids)


def checar_uso_do_teste(toca: bool, final: bool, motivo: str | None, split: dict[str, Any],
                        dir_casos: Path | None = None) -> list[str]:
    """Erros que impedem a execução (vazio = pode seguir). Com o split congelado, tocar o teste exige `--final`,
    `--motivo` e o manifesto conferindo; `--final` sem tocar o teste não faz nada."""
    if not toca:
        return []
    erros = []
    if split.get("congelado") and not final:
        erros.append("o split de teste está congelado (SPLIT.yaml, congelado: true): esta execução usa casos do "
                     "teste e só roda com --final --motivo \"...\" (o uso fica em "
                     f"{_rel(caminho_registro(dir_casos))}); para desenvolver, use --split dev")
    if final:
        if not motivo or len(motivo.strip()) < 8:
            erros.append("--final exige --motivo com o porquê desta execução (ex.: \"rodada r4 congelada\")")
        problemas = conferir_manifesto(split, dir_casos)
        if problemas:
            erros.append("MANIFESTO.yaml não confere com golden/casos/: " + "; ".join(problemas[:8]))
    return erros


def argv_seguro(argv: Iterable[str]) -> list[str]:
    """argv sem caminhos absolutos da máquina (relativos ao repositório ou só o nome)."""
    out = []
    for x in argv:
        s = str(x)
        if os.path.isabs(s) or re.match(r"^[A-Za-z]:[\\/]", s):
            out.append(_rel(Path(s)))
        else:
            out.append(s)
    return out


@contextmanager
def _trava(caminho: Path, espera_s: float = 15.0) -> Iterator[None]:
    """Trava por arquivo (O_EXCL) para dois processos não intercalarem a cadeia do registro."""
    trava = Path(str(caminho) + ".trava")
    t0 = time.monotonic()
    while True:
        try:
            fd = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() - t0 > espera_s:
                raise TimeoutError(f"registro travado por outro processo ({trava}); apague a trava se ninguém "
                                   "estiver rodando") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        trava.unlink(missing_ok=True)


def _linhas_registro(caminho: Path) -> list[bytes]:
    if not caminho.exists():
        return []
    return [ln for ln in caminho.read_bytes().split(b"\n") if ln.strip()]


def conferir_registro(caminho: Path | None = None) -> list[str]:
    """Cadeia do registro: cada linha é JSON, `seq` contínuo e `anterior_sha256` = sha256 da linha anterior."""
    caminho = Path(caminho) if caminho else caminho_registro()
    problemas, anterior = [], _ZERO
    for i, ln in enumerate(_linhas_registro(caminho), 1):
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            problemas.append(f"linha {i}: não é JSON")
            anterior = hashlib.sha256(ln).hexdigest()
            continue
        if d.get("seq") != i:
            problemas.append(f"linha {i}: seq {d.get('seq')} (linha removida ou inserida?)")
        if d.get("anterior_sha256") != anterior:
            problemas.append(f"linha {i}: anterior_sha256 não confere (linha anterior editada ou removida)")
        anterior = hashlib.sha256(ln).hexdigest()
    return problemas


def ler_registro(caminho: Path | None = None) -> list[dict[str, Any]]:
    caminho = Path(caminho) if caminho else caminho_registro()
    out = []
    for ln in _linhas_registro(caminho):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def resumo_registro(caminho: Path | None = None, alvo: str | None = None) -> dict[str, Any]:
    """Quantas execuções finais houve (por alvo), quais não terminaram e se a cadeia confere. Um evento
    `retroativo` (uso anterior ao registro, anotado depois com a evidência) conta como execução terminada."""
    regs = ler_registro(caminho)
    inicios = [r for r in regs if r.get("evento") in ("inicio", "retroativo")
               and (alvo is None or r.get("alvo") == alvo)]
    fins = {r.get("execucao"): r for r in regs if r.get("evento") in ("fim", "retroativo")}
    por_alvo: dict[str, int] = {}
    for r in inicios:
        por_alvo[r.get("alvo", "?")] = por_alvo.get(r.get("alvo", "?"), 0) + 1
    return {"execucoes": len(inicios), "por_alvo": por_alvo,
            "sem_fim": [r.get("execucao") for r in inicios if r.get("execucao") not in fins],
            "status": {r.get("execucao"): (fins.get(r.get("execucao")) or {}).get("status", "sem fim")
                       for r in inicios},
            "cadeia": conferir_registro(caminho) or "ok"}


def registrar_uso_teste(evento: dict[str, Any], caminho: Path | None = None) -> dict[str, Any]:
    """Acrescenta um evento ao registro (nunca reescreve). Cadeia quebrada não impede o registro: o evento novo
    leva a marca `cadeia_anterior`, que fica para sempre na linha seguinte."""
    caminho = Path(caminho) if caminho else caminho_registro()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with _trava(caminho):
        linhas = _linhas_registro(caminho)
        quebras = conferir_registro(caminho)
        reg: dict[str, Any] = {"seq": len(linhas) + 1, **evento}
        if quebras:
            reg["cadeia_anterior"] = "QUEBRADA: " + "; ".join(quebras[:3])
            print("AVISO: a cadeia do registro de uso do teste não confere:", *quebras[:5], sep="\n  ")
        reg["anterior_sha256"] = hashlib.sha256(linhas[-1]).hexdigest() if linhas else _ZERO
        prefixo = b"" if not caminho.exists() or caminho.read_bytes().endswith(b"\n") or not linhas else b"\n"
        with caminho.open("ab") as f:
            f.write(prefixo + json.dumps(reg, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
    return reg


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


VAR_DATA_RODADA = "LAUDO_DATA_RODADA"


def data_rodada() -> str:
    """Data (AAAA-MM-DD) que vai no nome e no `config.data` do relatório: `LAUDO_DATA_RODADA`, quando a rodada a
    fixa (`eval/rodada_r4.py`, para que uma rodada que passa da meia-noite ou é retomada no dia seguinte tenha uma
    data só e `gerar_slide`/`gerar_numeros` achem todos os relatórios), ou a data local de hoje."""
    valor = os.environ.get(VAR_DATA_RODADA, "").strip()
    if valor:
        return date.fromisoformat(valor).isoformat()  # data inválida para a execução com ValueError claro
    return datetime.now().astimezone().date().isoformat()


@contextmanager
def uso_do_teste(ativo: bool, *, script: str, alvo: str, motivo: str | None, argv: Iterable[str],
                 extra: dict[str, Any] | None = None, caminho: Path | None = None) -> Iterator[dict[str, Any] | None]:
    """Registra o uso do teste em volta da execução: `inicio` antes do 1º caso e `fim` com o status (ok, erro,
    interrompido) e o que o chamador puser em `estado["resultado"]` (relatório, sha256, números)."""
    if not ativo:
        yield None
        return
    execucao = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    registrar_uso_teste({"evento": "inicio", "execucao": execucao, "em": agora_iso(), "script": script,
                         "alvo": alvo, "motivo": motivo, "argv": argv_seguro(argv), **(extra or {})}, caminho)
    estado: dict[str, Any] = {"execucao": execucao, "resultado": None}
    status = "erro"
    try:
        yield estado
        status = "ok"
    except KeyboardInterrupt:
        status = "interrompido"
        raise
    except SystemExit as e:
        status = "ok" if e.code in (0, None) else f"saiu com código {e.code}"
        raise
    except BaseException as e:
        status = f"erro: {type(e).__name__}"
        raise
    finally:
        registrar_uso_teste({"evento": "fim", "execucao": execucao, "em": agora_iso(), "status": status,
                             "duracao_s": round(time.perf_counter() - t0, 1), **(estado.get("resultado") or {})},
                            caminho)


# ---------------------------------------------------------------------------
# Reprodutibilidade dos relatórios (L59)
# ---------------------------------------------------------------------------

_FORA_DO_HASH_EVAL = {"registro_teste.jsonl", "registro_teste.jsonl.trava"}
PACOTES = ("pydantic", "httpx", "pyyaml", "numpy", "shapely", "pyproj", "lxml", "onnxruntime", "opencv-python-headless")
# Texto que o git converte com core.autocrlf (CRLF no Windows, LF no Linux do CI); o resto é comparado em bytes.
_SUFIXOS_TEXTO = {".py", ".yaml", ".yml", ".json", ".jsonl", ".md", ".html", ".xml", ".txt", ".csv", ".j2",
                  ".toml", ".sha256", ".js", ".cjs", ".css"}


def _dirs_sem_conversao(base: Path) -> list[Path]:
    """Diretórios com `* -text` no .gitattributes: ali os bytes são canônicos (o git não converte nada)."""
    out = []
    for ga in base.rglob(".gitattributes"):
        if any(ln.split()[:2] == ["*", "-text"] for ln in ga.read_text(encoding="utf-8").splitlines()):
            out.append(ga.parent)
    return out


def _bytes_canonicos(p: Path, sem_conversao: list[Path]) -> bytes:
    dados = p.read_bytes()
    if p.suffix.lower() in _SUFIXOS_TEXTO and not any(d in p.parents for d in sem_conversao):
        return dados.replace(b"\r\n", b"\n")
    return dados


def hash_src_lf() -> str:
    """O mesmo `hash_src()` com CRLF → LF nos arquivos de texto: igual no Windows (autocrlf) e no Linux do CI,
    onde `hash_src()` dá exatamente este valor. Vai no `config` ao lado do `sha256_src` (que não muda de definição,
    para continuar comparável com as rodadas anteriores)."""
    h = hashlib.sha256()
    base = REPO / "src"
    sem = _dirs_sem_conversao(base)
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in (".py", ".yaml", ".md", ".j2") and "__pycache__" not in p.parts:
            h.update(p.relative_to(REPO).as_posix().encode() + b"\0" + _bytes_canonicos(p, sem))
    return h.hexdigest()


def hash_eval() -> dict[str, Any]:
    """sha256 de `eval/` (código, golden, red-team, manifestos), sem `reports/`, documentação (.md), caches e o
    registro append-only, que mudam a cada rodada sem mudar o que é avaliado; `partes` diz onde mudou. Texto com
    CRLF → LF (fora dos diretórios `-text`), para o valor ser o mesmo no Windows e no CI."""
    base = REPO / "eval"
    sem = _dirs_sem_conversao(base)
    total = hashlib.sha256()
    partes: dict[str, Any] = {}
    n = 0
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if (rel.parts[0] == "reports" or "__pycache__" in rel.parts or p.suffix in (".md", ".pyc")
                or p.name in _FORA_DO_HASH_EVAL):
            continue
        chave = ("/".join(rel.parts[:2]) if rel.parts[0] == "golden" and len(rel.parts) > 2 else
                 rel.parts[0] if len(rel.parts) > 1 else "(raiz)")
        dig = hashlib.sha256(_bytes_canonicos(p, sem)).hexdigest()
        linha = rel.as_posix().encode() + b"\0" + dig.encode() + b"\n"
        total.update(linha)
        partes.setdefault(chave, hashlib.sha256()).update(linha)
        n += 1
    return {"sha256": total.hexdigest(), "n_arquivos": n, "partes": {k: h.hexdigest() for k, h in partes.items()}}


def _opcoes_do_provedor(prov: Any) -> dict[str, Any] | str:
    if prov is None:
        return NA
    timeout = getattr(prov, "timeout", None)
    return {"options": dict(getattr(prov, "opcoes", None) or {}), "think": getattr(prov, "think", None),
            "keep_alive": getattr(prov, "keep_alive", None), "perfil": getattr(prov, "perfil", None),
            "timeout_leitura_s": getattr(timeout, "read", timeout), "retentativas": getattr(prov, "retentativas", None)}


def info_llm(prov: Any = None, modelo: str | None = None, base_url: str | None = None,
             opcoes: dict[str, Any] | str | None = None, cliente: Any = None) -> dict[str, Any]:
    """Modelo, digest (de `/api/tags`), versão do Ollama (`/api/version`) e opções de geração. Sem provedor nem
    modelo (modo determinístico) ou com o Ollama fora do ar: "n/a" (nunca inventa)."""
    modelo = modelo or getattr(prov, "modelo", None)
    if prov is None and modelo is None:
        return {"provedor": NA, "modelo": NA, "digest": NA, "ollama_versao": NA, "opcoes": NA}
    base = (base_url or getattr(prov, "base_url", None) or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434").rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    out: dict[str, Any] = {"provedor": getattr(prov, "nome", None) or "ollama", "modelo": modelo, "digest": NA,
                           "ollama_versao": NA, "ollama_local": base.split("//", 1)[-1].startswith(
                               ("127.0.0.1", "localhost", "[::1]")),
                           "opcoes": opcoes if opcoes is not None else _opcoes_do_provedor(prov)}
    try:
        if cliente is None:
            import httpx

            cliente = httpx
        out["ollama_versao"] = cliente.get(f"{base}/api/version", timeout=5).json().get("version") or NA
        for m in cliente.get(f"{base}/api/tags", timeout=5).json().get("models", []):
            if modelo in (m.get("name"), m.get("model")):
                out["digest"] = m.get("digest") or NA
                det = m.get("details") or {}
                out["detalhes"] = {k: det.get(k) for k in ("family", "parameter_size", "quantization_level",
                                                           "format") if det.get(k)}
                break
    except Exception as e:  # noqa: BLE001 - Ollama fora do ar ou resposta inesperada: fica "n/a"
        out["erro_consulta"] = f"{type(e).__name__}"
    return out


def ollama_ps(base_url: str | None = None, cliente: Any = None) -> list[str] | None:
    """Modelos carregados no Ollama (`/api/ps`), para registrar se a rodada dividiu a GPU com outro modelo; None se
    o Ollama não responder."""
    base = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    try:
        if cliente is None:
            import httpx

            cliente = httpx
        return [m.get("name") for m in cliente.get(f"{base}/api/ps", timeout=5).json().get("models", [])]
    except Exception:  # noqa: BLE001 - só registro
        return None


def versoes_pacotes() -> dict[str, str]:
    from importlib import metadata

    out = {}
    for nome in PACOTES:
        try:
            out[nome] = metadata.version(nome)
        except metadata.PackageNotFoundError:
            out[nome] = NA
    return out


def config_reprodutivel(prov: Any = None, llm: dict[str, Any] | None = None,
                        split: dict[str, Any] | None = None) -> dict[str, Any]:
    """O que identifica a rodada além do `sha256(src/)`: sha256(eval/), manifesto, LLM (ou "n/a"), Python,
    sistema e bibliotecas. `llm` já calculado (no início da rodada) evita consultar o Ollama de novo."""
    he = hash_eval()
    return {"sha256_src": hash_src(), "sha256_src_lf": hash_src_lf(), "sha256_eval": he["sha256"],
            "sha256_eval_partes": he["partes"],
            "manifesto": info_manifesto(split), "llm": llm if llm is not None else info_llm(prov),
            "python": platform.python_version(), "sistema": f"{platform.system()} {platform.release()}",
            "pacotes": versoes_pacotes()}


def linha_reprodutibilidade(cfg: dict[str, Any]) -> list[str]:
    """Linha de cabeçalho de relatório com o que identifica a rodada (L59); vazia em relatório antigo."""
    if "sha256_eval" not in cfg:
        return []
    llm, man = cfg.get("llm") or {}, cfg.get("manifesto") or {}
    if llm.get("modelo", NA) == NA:
        txt_llm = "LLM: n/a (sem LLM nem Ollama)"
    else:
        op = llm.get("opcoes") if isinstance(llm.get("opcoes"), dict) else {}
        txt_llm = (f"LLM: `{llm.get('modelo')}` digest `{str(llm.get('digest'))[:19]}`, Ollama "
                   f"{llm.get('ollama_versao')}, opções `{json.dumps(op.get('options', op), ensure_ascii=False)}`"
                   f", think={op.get('think')}")
    conf = man.get("conferido")
    return [(f"- Reprodutibilidade: `sha256(eval/)={cfg['sha256_eval'][:16]}…`, manifesto do golden "
             f"`{str(man.get('sha256_manifesto'))[:16]}…` ({'confere' if conf == 'ok' else conf}); {txt_llm}.")]


def carregar_caso(cid: str) -> dict[str, Any]:
    return yaml.safe_load((DIR_CASOS / cid / "caso.yaml").read_text(encoding="utf-8"))


def item_bovinos(caso: dict[str, Any]) -> str:
    return next(i["id"] for i in caso["operacao"]["itens"] if i["tipo"] == "bovinos")


def item_benfeitoria(caso: dict[str, Any]) -> str:
    return next(i["id"] for i in caso["operacao"]["itens"] if i["tipo"] != "bovinos")


def grupo_do_campo(campo: str) -> str:
    """Campo fino do golden → campo do laudo produzido por `avaliar_regras`."""
    suf = campo.rsplit(":", 1)[-1]
    if campo.startswith("documento:nfe") or suf.startswith("nfe_"):
        return "comprovante_nfe"
    if campo.startswith("documento:gta") or suf.startswith("gta_"):
        return "gta"
    return suf  # quantidade, integridade_foto, localizacao


def campo_sistema(caso: dict[str, Any], grupo: str) -> str:
    alvo = item_bovinos(caso) if grupo in ("quantidade", "comprovante_nfe", "gta") else item_benfeitoria(caso)
    return f"item:{alvo}:{grupo}"


def pior(status: list[str]) -> str:
    return min(status, key=PRECEDENCIA.index) if status else "verificado"


def esperado_por_grupo(caso: dict[str, Any]) -> dict[str, str]:
    """Rótulo de cada campo do laudo = pior rótulo dos campos finos do golden (precedência do rulebook)."""
    grupos: dict[str, list[str]] = {}
    for campo, e in caso["esperado"]["campos"].items():
        grupos.setdefault(grupo_do_campo(campo), []).append(e["status_esperado"])
    return {g: pior(v) for g, v in grupos.items()}


# ---------------------------------------------------------------------------
# Contornos (relógio, vídeo simulado, contexto do cadastro)
# ---------------------------------------------------------------------------


class _Relogio:
    agora: datetime | None = None


RELOGIO = _Relogio()
_INSTALADO: dict[str, Any] = {}


def instalar_contornos() -> None:
    """Relógio simulado para `Evidencia.recebida_em` (idempotente)."""
    if _INSTALADO:
        return
    from laudo.agent import estado
    from laudo.contracts import Evidencia

    class EvidenciaRelogio(Evidencia):
        recebida_em: datetime = Field(default_factory=lambda: RELOGIO.agora or datetime.now(FUSO))

    _INSTALADO["Evidencia"] = estado.Evidencia
    estado.Evidencia = EvidenciaRelogio


def ferramenta_contador_simulado(saidas: dict[str, dict[str, Any]]):
    """`contar_bovinos_video` com o esquema real e resultado vindo do caso (vídeo sintético não existe)."""
    from laudo.contracts import CodigoErro, Envelope, Ferramenta
    from laudo.tools.bovinos import NOME, PEDIDOS, EntradaContarBovinos
    from laudo.vision.contagem import ParametrosContagem

    p = ParametrosContagem()
    desc = ("Conta bovinos num vídeo (detector YOLOX + rastreador + linha de contagem ou IDs únicos) e devolve "
            "contagem, intervalo, motivos de abstenção e quadros-chave anotados.")

    def funcao(args: EntradaContarBovinos) -> Envelope:
        t0 = time.perf_counter()
        s = saidas.get(Path(args.caminho_video).name)
        if s is None or s.get("_erro"):
            cod = CodigoErro((s or {}).get("_erro", "ENTRADA_INVALIDA"))
            return Envelope.falha(NOME, cod, (s or {}).get("msg", f"vídeo ilegível: {args.caminho_video}"),
                                  retryable=cod == CodigoErro.TIMEOUT, t0=t0)
        est_, (lo, hi) = int(s["estimativa"]), (int(s["ic80"][0]), int(s["ic80"][1]))
        motivos = []
        if s["confianca"] < p.limiar_conf_media:
            motivos.append({"codigo": "CONF_BAIXA", "abstem": True,
                            "msg": f"confiança média {s['confianca']:.2f} < {p.limiar_conf_media}"})
        if s.get("oclusao_frac", 0) > p.max_oclusao:
            motivos.append({"codigo": "OCLUSAO_ALTA", "abstem": True,
                            "msg": f"oclusão {s['oclusao_frac']:.2f} > {p.max_oclusao}"})
        if est_ > 0 and (hi - lo) / 2 > max(1.0, p.max_meia_largura_rel * est_):
            motivos.append({"codigo": "INTERVALO_LARGO", "abstem": True, "msg": "intervalo largo"})
        status = "indeterminado" if motivos else "ok"
        dados = {"contagem": est_, "intervalo": [lo, hi], "modo": args.modo, "status": status,
                 "abstencao": bool(motivos), "motivos": motivos, "conf_media": s["confianca"],
                 "oclusao": s.get("oclusao_frac"), "item_id": args.item_id, "simulado": True,
                 "pedidos_recaptura": sorted({PEDIDOS[m["codigo"]] for m in motivos if m["codigo"] in PEDIDOS})}
        return Envelope.sucesso(NOME, dados, fonte_versao="contador-simulado@golden-v1", t0=t0)

    return Ferramenta(nome=NOME, descricao=desc, entrada=EntradaContarBovinos, funcao=funcao, timeout_s=10.0)


def _status_pior_criterio(data: dict[str, Any]) -> str:
    sts = [c.get("status") for c in (data.get("campos") or {}).values()]
    if "divergente" in sts:
        return "divergente"
    if "indeterminado" in sts:
        return "indeterminado"
    return "ok"


def ferramenta_com_contexto(ferr, extras: dict[str, Any], substituir: dict[str, Any] | None = None,
                            com_status: bool = False):
    """Envolve `conciliar_nfe`/`conciliar_gta`: injeta o contexto do caso (contorno 4) e, na integração
    `ideal`, troca os argumentos pelos do caso e acrescenta `data.status` (contorno 5)."""
    from laudo.contracts import Ferramenta

    def funcao(args):
        d = args.model_dump(mode="json")
        d.update(extras)
        if substituir:
            d = {**d, **substituir}
        env = ferr.funcao(ferr.entrada.model_validate(d))
        if com_status and env.ok and env.data is not None and "status" not in env.data:
            env.data["status"] = _status_pior_criterio(env.data)
        return env

    return Ferramenta(nome=ferr.nome, descricao=ferr.descricao, entrada=ferr.entrada, funcao=funcao,
                      deterministica=ferr.deterministica, timeout_s=ferr.timeout_s)


def _resolver(dcaso: Path, ent: dict[str, Any]) -> dict[str, Any]:
    out = dict(ent)
    for chave in ("caminhos", "nfe_caminhos"):
        if chave in out:
            out[chave] = [str(dcaso / x) for x in out[chave]]
    return out


def montar_registro(caso: dict[str, Any], dcaso: Path, integracao: str = "app",
                    saidas_video: dict[str, dict[str, Any]] | None = None,
                    envoltorios: dict[str, Callable] | None = None) -> dict:
    """Registro de ferramentas do caso: as reais + contornos. `envoltorios` (red-team) troca ferramentas."""
    from laudo.tools import carregar_todas

    reg = dict(carregar_todas())
    reg["contar_bovinos_video"] = ferramenta_contador_simulado(saidas_video or {})
    ent = caso.get("entradas_ferramentas") or {}
    for nome in ("conciliar_nfe", "conciliar_gta"):
        if integracao != "ideal" or nome not in reg or nome not in ent:
            continue  # integração "app": a ferramenta recebe só o que o condutor preenche do estado
        e = _resolver(dcaso, ent[nome])
        extras = {k: e[k] for k in ("tomador_doc_sha256", "codigo_estabelecimento_destino", "data_fiscalizacao",
                                    "parametros") if k in e}
        subst = {k: e[k] for k in ("caminhos", "nfe_caminhos") if k in e}
        reg[nome] = ferramenta_com_contexto(reg[nome], extras, substituir=subst, com_status=True)
    for nome, envolver in (envoltorios or {}).items():
        reg[nome] = envolver(reg.get(nome))
    return reg


# ---------------------------------------------------------------------------
# Roteiro de turnos de um caso
# ---------------------------------------------------------------------------


@dataclass
class Turno:
    tipo: str  # abertura | declaracao | upload | fala | emissao | ataque
    texto: str = ""
    evidencia: dict[str, Any] | None = None  # kwargs de NovaEvidencia
    agora: datetime | None = None
    esperado: list[str] = field(default_factory=list)  # ferramentas que o LLM deveria chamar
    meta: dict[str, Any] = field(default_factory=dict)


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def roteiro_caso(caso: dict[str, Any], dcaso: Path, dir_trabalho: Path,
                 com_declaracao: bool = True, com_emissao: bool = True) -> list[Turno]:
    """Turnos de um caso: abertura, declaração de independência, documentos, vídeo, falas, fotos e pedido de
    laudo. As falas do caso entram na ordem em que aparecem; o vídeo vai com a 1ª fala do fiscal e as fotos
    com a 2ª (as falas do gerador anunciam essas capturas)."""
    d = date.fromisoformat(caso["data_fiscalizacao"])

    def em(h: int, m: int = 0) -> datetime:
        return datetime(d.year, d.month, d.day, h, m, tzinfo=FUSO)

    bov, benf = item_bovinos(caso), item_benfeitoria(caso)
    tipo_benf = next(i["tipo"] for i in caso["operacao"]["itens"] if i["id"] == benf)
    turnos = [Turno("abertura", f"Bom dia. Vou iniciar a fiscalização da operação {caso['operacao']['ref_bacen']}.",
                    agora=em(7, 30), esperado=["planejar_metodo"])]
    if com_declaracao:
        txt = "Declaro que não presto assistência técnica ao produtor nem a empresa dele."
        turnos.append(Turno("declaracao", txt, agora=em(7, 35), evidencia={
            "tipo": "declaracao", "conteudo_texto": txt,
            "meta": {"assunto": "independencia_fiscal", "conflito": False}}))
    for k, nf in enumerate(caso["documentos"]["nfe"], 1):
        turnos.append(Turno("upload", "Segue o XML da nota fiscal da compra dos animais.", agora=em(7, 40 + k),
                            evidencia={"tipo": "nfe_xml", "caminho": str(dcaso / nf["arquivo"]), "item_id": bov},
                            esperado=["conciliar_nfe"]))
    for k, g in enumerate(caso["documentos"]["gta"], 1):
        turnos.append(Turno("upload", f"Segue a GTA {k} do transporte dos animais.", agora=em(7, 50 + k),
                            evidencia={"tipo": "gta", "caminho": str(dcaso / g["arquivo_json"]), "item_id": bov},
                            esperado=["conciliar_gta"]))
    video = caso["video"]
    arq_video = dir_trabalho / "curral.mp4"
    arq_video.write_bytes(f"{video['ref']}\n".encode())
    fiscais = [i for i, f in enumerate(caso["falas"]) if f["de"] == "fiscal"]
    i_video = fiscais[0] if fiscais else None
    i_fotos = fiscais[1] if len(fiscais) > 1 else None
    fotos_benf = [f for f in caso["fotos"] if f["item_id"] == benf]
    fotos_outras = [f for f in caso["fotos"] if f["item_id"] != benf]

    def turno_foto(f: dict[str, Any], texto: str) -> Turno:
        g = f.get("gps_app")
        gps = {"lat": g["lat"], "lon": g["lon"], "precisao_m": g.get("precisao_m"), "fonte": "app"} if g else None
        return Turno("upload", texto, agora=_dt(f.get("recebida_em")) or em(15), esperado=["integridade_foto",
                                                                                         "geofence"],
                     evidencia={"tipo": "foto", "caminho": str(dcaso / f["arquivo"]), "item_id": f["item_id"],
                                "gps": gps, "capturada_em": _dt((f.get("exif") or {}).get("data_hora"))})

    for i, fala in enumerate(caso["falas"]):
        if i == i_video:
            turnos.append(Turno("upload", fala["texto"], agora=em(10, 5), esperado=["contar_bovinos_video"],
                                evidencia={"tipo": "video", "caminho": str(arq_video), "item_id": bov,
                                           "capturada_em": em(10)}))
        elif i == i_fotos and fotos_benf:
            turnos.append(turno_foto(fotos_benf[0], fala["texto"]))
            for f in fotos_benf[1:]:
                turnos.append(turno_foto(f, f"Outra foto da {tipo_benf}, de outro ângulo."))
            for f in fotos_outras:
                turnos.append(turno_foto(f, "Foto do lote de animais."))
        else:
            ult = turnos[-1].agora or em(12)
            turnos.append(Turno("fala", fala["texto"], agora=ult + timedelta(minutes=2), meta={"de": fala["de"]}))
    if com_declaracao:  # MCR 2-7-16-a: o fiscal atesta a conclusão da obra (o golden não traz essa fala)
        detalhe = {"cerca": "com os mourões e os fios instalados", "curral": "com brete, tronco e porteiras prontos"}
        ult = max(t.agora for t in turnos if t.agora)
        turnos.append(Turno("declaracao", f"Confirmo que a {'obra do ' if tipo_benf == 'curral' else ''}"
                                          f"{tipo_benf} está concluída, {detalhe.get(tipo_benf, 'pronta')}.",
                            agora=ult + timedelta(minutes=3)))
    if com_emissao:
        ult = max(t.agora for t in turnos if t.agora)
        turnos.append(Turno("emissao", "Terminei a coleta. Pode gerar o rascunho do laudo?",
                            agora=ult + timedelta(minutes=10), esperado=["emitir_rascunho"]))
    return turnos


def saidas_video_do_caso(caso: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {"curral.mp4": caso["video"]["saida_simulada_contador"]}


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


class Ambiente:
    """Diretório de trabalho isolado de uma rodada (traces, fiscalizações, laudos, índices de fotos)."""

    def __init__(self, base: Path | None = None, rotulo: str = "rodada", limpar: bool = True):
        from laudo.audit import otel

        instalar_contornos()
        self.dir = (base or DIR_TMP_PADRAO) / rotulo
        if limpar and self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        otel.configurar(self.dir / "traces")

    def dir_caso(self, cid: str) -> Path:
        d = self.dir / cid
        d.mkdir(parents=True, exist_ok=True)
        return d


def preparar_condutor(caso: dict[str, Any], amb: Ambiente, provedor=None, integracao: str = "app",
                      registro: dict | None = None, modo: str = "tools", sufixo: str = ""):
    """Cria repositório, registro e condutor do caso, e abre a fiscalização. Devolve (cond, fis, dcaso, dtrab)."""
    from laudo.agent import estado as est
    from laudo.agent.condutor import Condutor
    from laudo.contracts import Operacao
    from laudo.tools import foto

    dcaso = DIR_CASOS / caso["id"]
    dtrab = amb.dir_caso(caso["id"] + sufixo)
    est.ids_deterministicos(f"eval:{caso['id']}{sufixo}")
    foto.INDICE_PADRAO = dtrab / "indice_fotos.jsonl"
    reg = registro or montar_registro(caso, dcaso, integracao, saidas_video_do_caso(caso))
    repo = est.RepositorioFiscalizacoes(dtrab)
    hoje = date.fromisoformat(caso["data_fiscalizacao"])
    cond = Condutor(provedor, repo=repo, registro=reg, hoje=hoje, modo=modo)
    op = dict(caso["operacao"])
    # Contorno 4: campos do contrato `Operacao` que o cadastro da operação teria e o caso guarda em outro lugar.
    prop = (caso.get("projeto") or {}).get("propriedade") or {}
    if prop.get("codigo_estabelecimento"):
        op.setdefault("codigo_estabelecimento", prop["codigo_estabelecimento"])
    h_tomador = (caso.get("tomador") or {}).get("documento_sha256")
    if h_tomador and not str(op.get("tomador_ref", "")).startswith("sha256:"):
        op["tomador_ref"] = f"sha256:{h_tomador}"
    RELOGIO.agora = datetime(hoje.year, hoje.month, hoje.day, 7, 0, tzinfo=FUSO)
    fis = cond.abrir(Operacao.model_validate(op), data_referencia=hoje, data_fiscalizacao=hoje)
    return cond, fis, dcaso, dtrab


def evento_de(turno: Turno):
    from laudo.agent.condutor import Evento, NovaEvidencia

    ev = NovaEvidencia(**turno.evidencia) if turno.evidencia else None
    return Evento(texto=turno.texto, origem="asr" if turno.meta.get("de") == "produtor" else "fala_fiscal",
                  evidencia=ev)


def executar_turno(cond, fis_id: str, turno: Turno) -> dict[str, Any]:
    """Executa um turno e devolve um registro serializável (ações, fala, latências, estatísticas do LLM)."""
    RELOGIO.agora = turno.agora or RELOGIO.agora
    t0 = time.perf_counter()
    r = cond.turno(fis_id, evento_de(turno))
    dt = time.perf_counter() - t0
    return {
        "tipo": turno.tipo, "texto": turno.texto, "esperado": turno.esperado, "meta": turno.meta,
        "evidencia": (turno.evidencia or {}).get("tipo"), "latencia_s": round(dt, 3),
        "etapa": r.etapa, "fala": r.fala, "fala_origem": r.fala_origem, "fatos": list(r.fatos),
        "acoes": [{"acao": a.acao, "origem": a.origem, "permitido": a.permitido, "ok": a.ok,
                   "rule_id": a.rule_id, "resultado": a.resultado[:400], "argumentos": _seguro(a.argumentos)}
                  for a in r.acoes],
        "avisos": r.avisos, "ocorrencias": r.ocorrencias, "transicoes": r.transicoes,
        "alegacoes": [{k: a.get(k) for k in ("grandeza", "valor", "item_id", "origem_extracao")}
                      for a in r.alegacoes],
        "llm": r.llm, "n_pendencias": len(r.pendencias),
    }


def _seguro(obj: Any) -> Any:
    try:
        json.dumps(obj, default=str)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def estado_final(cond, fis_id: str) -> dict[str, Any]:
    """Status por campo (verificador + avaliar_regras), decisão de emissão (política) e ocorrências."""
    fis = cond.repo.carregar(fis_id)
    res = cond.verificador.recalcular(fis)
    dec = cond.politica.autorizar_emissao(fis, res)
    return {
        "fis": fis, "res": res,
        "campos": {n: {"status": c.status, "regra_id": c.regra_id, "motivo": c.motivo[:300]}
                   for n, c in res.campos.items()},
        "provisoria": res.provisoria, "aviso_verificador": res.aviso,
        "emissao_permitida": dec.permitido,
        "pendencias": [{"regra_id": p.get("regra_id"), "campo": p.get("campo"), "falta": str(p.get("falta"))[:160]}
                       for p in dec.pendencias],
        "ocorrencias": [o.tipo for o in fis.ocorrencias],
        "etapa": fis.estado_fsm,
        "rascunhos": sum(1 for e in fis.evidencias if e.meta.get("laudo")),
    }


def campos_finos(fis) -> dict[str, str]:
    """Status sugerido pelas ferramentas de documento por campo fino (pior entre checagens do mesmo campo)."""
    from laudo.docs_fiscais.comum import STATUS_CAMPO

    saida: dict[str, list[str]] = {}
    for chk in fis.checagens:
        if chk.ferramenta not in ("conciliar_nfe", "conciliar_gta") or chk.status == "erro":
            continue
        for campo, c in (chk.resultado.get("campos") or {}).items():
            saida.setdefault(campo, []).append(c.get("status_campo_sugerido") or STATUS_CAMPO.get(c.get("status"),
                                                                                                 "pendente"))
    return {k: pior(v) for k, v in saida.items()}


_NUM_JSON = None
_NUM_TXT = None


def _numeros_texto(texto: str) -> list[tuple[str, float]]:
    """Números de um texto em pt-BR (1.200 = mil e duzentos; 61,75 = decimal). Implementação própria do
    harness, independente do `verificador.extrair_numeros`."""
    import re

    global _NUM_TXT
    _NUM_TXT = _NUM_TXT or re.compile(
        r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+\.\d+|\d+(?:,\d+)?)(?![\w]|[.,]\d)")
    saida = []
    for m in _NUM_TXT.finditer(texto or ""):
        b = m.group(1)
        if "," in b:
            v = b.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", b):
            v = b.replace(".", "")
        else:
            v = b
        saida.append((b, float(v)))
    return saida


def numeros_do_estado(fis, textos: list[str]) -> set[float]:
    """Todo número que aparece no estado serializado (operação, evidências, checagens, campos, alegações) ou nas
    falas do fiscal: o oráculo é frouxo de propósito (qualquer lastro serve), mas independente do sistema."""
    import re

    global _NUM_JSON
    _NUM_JSON = _NUM_JSON or re.compile(r"(?<![0-9A-Za-z_.])(\d+(?:\.\d+)?)(?![0-9A-Za-z_])")
    s = fis.model_dump_json()
    nums = {float(x) for x in _NUM_JSON.findall(s)}
    for t in textos:
        nums.update(v for _, v in _numeros_texto(t))
    return nums


def sem_lastro_oraculo(fala: str, nums: set[float]) -> list[str]:
    fora = []
    for bruto, v in _numeros_texto(fala):
        if not any(abs(v - n) <= 1e-6 or round(n, 2) == v or round(n, 1) == v or round(n) == v or
                   abs(v - 100 * n) <= 1e-6 for n in nums):
            fora.append(bruto)
    return fora


def sem_identificadores(texto: str) -> str:
    """Tira identificadores (chave de acesso `522608…36922076`, documento `***.456.***-**`): são referências,
    não números que o texto afirma. O filtro é o do sistema (`verificador.remover_identificadores`, usado pelo
    POL-05 desde a rodada 3); o oráculo independente do harness também o aplica antes de procurar números."""
    from laudo.agent.verificador import remover_identificadores

    return remover_identificadores(texto)


def grounding_falas(fis, turnos: list[dict[str, Any]], so_llm: bool = False) -> list[dict[str, Any]]:
    """POL-05 recalculado no estado final para cada fala entregue ao fiscal, e o oráculo independente."""
    from laudo.agent.verificador import grounding

    textos = [t["texto"] for t in turnos]
    nums = numeros_do_estado(fis, textos)
    out = []
    for t in turnos:
        if not t["fala"] or (so_llm and t["fala_origem"] != "llm"):
            continue
        fala = sem_identificadores(t["fala"])
        g = grounding(fala, fis, extras=textos, hoje=fis.data_referencia)
        out.append({"origem": t["fala_origem"], "sem_lastro": g.sem_lastro, "n_numeros": len(g.numeros),
                    "sem_lastro_oraculo": sem_lastro_oraculo(fala, nums), "fala": t["fala"][:200]})
    return out


def grounding_laudo(cond, fis, res) -> dict[str, Any]:
    """Grounding do texto do laudo (prévia montada pelo mesmo template do `emitir_rascunho`)."""
    from laudo.agent.verificador import grounding
    from laudo.tools import laudo as ferr_laudo

    fis = fis.model_copy(deep=True)
    fis.campos = res.campos  # como em `emitir_rascunho`: o laudo é montado sobre os campos recalculados
    try:
        laudo = ferr_laudo.montar_laudo(fis, res, politica=cond.politica, hoje=fis.data_referencia)
    except Exception as e:  # noqa: BLE001 - o harness registra e segue
        return {"erro": f"{type(e).__name__}: {e}"[:200]}
    texto = laudo.get("resumo", {}).get("texto", "")
    g = grounding(texto, fis, hoje=fis.data_referencia)
    return {"origem": laudo.get("resumo", {}).get("origem"), "sem_lastro": g.sem_lastro, "n_numeros": len(g.numeros)}


def confianca_campos(fis, caso: dict[str, Any]) -> dict[str, float]:
    """Pontuação para a curva risco-cobertura: confiança do contador (quantidade) e margem do GPS em relação à
    borda (localização, |d|/precisão normalizado). Checagens documentais e de integridade: 1,0."""
    benf = item_benfeitoria(caso)
    out: dict[str, float] = {}
    conts = [c for c in fis.checagens if c.ferramenta == "contar_bovinos_video" and c.status != "erro"]
    if conts:
        out["quantidade"] = float(conts[-1].resultado.get("conf_media") or 0.0)
    margens = []
    for c in fis.checagens:
        if c.ferramenta == "geofence" and c.item_id == benf and c.status != "erro":
            d, p = c.resultado.get("distancia_borda_m"), c.resultado.get("precisao_m")
            if d is not None and p:
                m = abs(float(d)) / max(float(p), 1.0)
                margens.append(m / (1.0 + m))
    if margens:
        out["localizacao"] = max(margens)
    return out


def rodar_caso(caso: dict[str, Any], amb: Ambiente, provedor=None, integracao: str = "app",
               modo: str = "tools") -> dict[str, Any]:
    """Roda um caso do golden set do começo ao fim e devolve o registro para as métricas."""
    cond, fis, dcaso, dtrab = preparar_condutor(caso, amb, provedor, integracao, modo=modo)
    turnos = []
    for t in roteiro_caso(caso, dcaso, dtrab):
        turnos.append(executar_turno(cond, fis.id, t))
    fim = estado_final(cond, fis.id)
    esperado = esperado_por_grupo(caso)
    grupos = {g: {"esperado": e, "sistema": (fim["campos"].get(campo_sistema(caso, g)) or {}).get("status",
                                                                                                 "ausente"),
                  "campo": campo_sistema(caso, g)}
              for g, e in esperado.items()}
    finos_sis = campos_finos(fim["fis"])
    subs = {"bov": item_bovinos(caso), "benf": item_benfeitoria(caso)}
    finos = {c: {"esperado": e["status_esperado"], "sistema": finos_sis.get(c, "ausente")}
             for c, e in caso["esperado"]["campos"].items() if grupo_do_campo(c) in ("comprovante_nfe", "gta")}
    return {
        "id": caso["id"], "classe": caso["classe"], "codigo": (caso.get("defeito") or {}).get("codigo"),
        "itens": subs, "grupos": grupos, "finos": finos, "confianca": confianca_campos(fim["fis"], caso),
        "ocorrencias_esperadas": caso["esperado"].get("ocorrencias", []),
        "ocorrencias": fim["ocorrencias"],
        "rascunho_sem_pendencias_esperado": caso["esperado"].get("rascunho_sem_pendencias"),
        "emissao_permitida": fim["emissao_permitida"], "pendencias": fim["pendencias"],
        "campos_sistema": fim["campos"], "provisoria": fim["provisoria"], "etapa_final": fim["etapa"],
        "rascunhos_emitidos": fim["rascunhos"],
        "turnos": turnos,
        "grounding_falas": grounding_falas(fim["fis"], turnos),
        "grounding_laudo": grounding_laudo(cond, fim["fis"], fim["res"]),
    }


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Linha de comando do congelamento (L41)."""
    import argparse

    ap = argparse.ArgumentParser(description="Manifesto do golden set congelado e registro de uso do teste.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--conferir", action="store_true", help="manifesto, hashes do SPLIT.yaml e cadeia do registro")
    g.add_argument("--registro", action="store_true", help="lista os usos do split de teste")
    g.add_argument("--gerar-manifesto", action="store_true",
                   help="grava golden/casos/MANIFESTO.yaml (só se não existir; com --substituir, exige --motivo)")
    ap.add_argument("--snapshot", help="tar.gz do snapshot pré-congelamento para conferir antes de gravar")
    ap.add_argument("--substituir", action="store_true")
    ap.add_argument("--motivo", default=None)
    a = ap.parse_args(argv)
    split = carregar_split()
    if a.registro:
        for r in ler_registro():
            print(json.dumps(r, ensure_ascii=False))
        print(json.dumps(resumo_registro(), ensure_ascii=False, indent=1))
        return 0
    if a.conferir:
        probs = [f"split: {p}" for p in conferir_split(split)] + [f"manifesto: {p}" for p in conferir_manifesto(split)]
        probs += [f"registro: {p}" for p in conferir_registro()]
        print("\n".join(probs) if probs else (f"ok: manifesto {info_manifesto(split)['sha256_manifesto'][:16]}…, "
                                              f"split e registro conferem ({resumo_registro()['execucoes']} uso(s) "
                                              "do teste registrados)"))
        return 1 if probs else 0
    destino = caminho_manifesto()
    if destino.exists() and not a.substituir:
        print(f"{_rel(destino)} já existe: o manifesto é gravado uma vez, no estado congelado. Para regravar "
              "(novo congelamento), use --substituir --motivo \"...\" e registre a decisão no eval/README.md.")
        return 2
    if a.substituir and not a.motivo:
        print("--substituir exige --motivo")
        return 2
    probs = conferir_split(split)
    if probs:
        print("SPLIT.yaml não confere; nada gravado:", *probs, sep="\n  ")
        return 2
    conferencias = [(f"{agora_iso()}: harness.conferir_split ok ({len(split['casos'])} caso.yaml com o "
                     "sha256_caso do SPLIT.yaml; sha256_split confere)")]
    if a.snapshot:
        conferencias.append(_conferir_snapshot(Path(a.snapshot)))
    if a.motivo:
        conferencias.append(f"motivo da gravação: {a.motivo}")
    man = montar_manifesto(split, conferencias=conferencias)
    if man["resumo"].get("fora_das_listas"):
        print("há arquivos em diretórios de casos fora das listas dev/test; nada gravado")
        return 2
    escrever_manifesto(man, destino)
    print(f"gravado {_rel(destino)}: {man['resumo']['total']['n_arquivos']} arquivos, "
          f"sha256_manifesto={man['sha256_manifesto']}")
    return 0


def _conferir_snapshot(tar: Path) -> str:
    """Compara os arquivos dos casos com um snapshot tar.gz (sem extrair): a testemunha de que o manifesto descreve
    o estado congelado, e não um estado posterior."""
    import tarfile

    base = _dir_casos()
    vistos: dict[str, str] = {}
    split_snap: dict[str, Any] | None = None
    with tarfile.open(tar, "r:gz") as t:
        for m in t:
            i = m.name.find("eval/golden/casos/")
            if not m.isfile() or i < 0:
                continue
            f = t.extractfile(m)
            if f is None:
                continue
            dados = f.read()
            rel = m.name[i + len("eval/golden/casos/"):]
            if rel == "SPLIT.yaml":
                split_snap = yaml.safe_load(dados.decode("utf-8"))
            vistos[rel] = hashlib.sha256(dados).hexdigest()
    atuais = arquivos_do_split(base)
    iguais = sum(1 for c, h in atuais.items() if vistos.get(c) == h)
    difs = sorted(c for c in atuais if c in vistos and vistos[c] != atuais[c])
    faltam = sorted(set(atuais) - set(vistos))
    split_atual = yaml.safe_load((base / "SPLIT.yaml").read_text(encoding="utf-8"))
    campos = ("ausente do snapshot" if split_snap is None else "iguais" if
              sha256_campos_congelados(split_snap) == sha256_campos_congelados(split_atual) else "DIFERENTES")
    return (f"snapshot {tar.name} (sha256 {sha256_arquivo(tar)[:16]}…): {iguais} de {len(atuais)} arquivos do "
            f"manifesto idênticos; diferentes: {', '.join(difs) or 'nenhum'}; ausentes do snapshot: "
            f"{', '.join(faltam) or 'nenhum'}; SPLIT.yaml: campos congelados {campos} aos do snapshot (o arquivo "
            f"{'é idêntico' if vistos.get('SPLIT.yaml') == sha256_arquivo(base / 'SPLIT.yaml') else 'difere'})")


if __name__ == "__main__":
    sys.exit(main())
