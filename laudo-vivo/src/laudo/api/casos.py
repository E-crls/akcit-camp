"""Casos de demonstração que a interface sabe abrir (roteiro da demo ou caso do golden set).

Dois formatos:

1. **`roteiro`** — o roteiro da demo do agente (`laudo.agent.roteiro_demo`): mesma operação, mesmos arquivos,
   mesmos turnos e a mesma semente de ids que `scripts/demo_cli.py`. Por isso o replay gravado com o modelo
   real (`tests/unit/dados_agente/replay_demo_qwen35_4b.jsonl`) casa requisição por requisição.
2. **pasta com `caso.yaml`** no formato do golden set (`eval/golden/casos/DEMO-0001/`, ou
   `eval/golden/demo/<ID>/`, ou uma subpasta de `LAUDO_CASOS_DIR`: casos de demonstração fora do repositório,
   listados na carteira com qualquer nome; ver `laudo.demonstracao`). Os arquivos (NF-e XML, e-GTA JSON, fotos) são
   usados no lugar; o vídeo, se não existir, vira um marcador e o contador falso devolve a
   `saida_simulada_contador` do caso. O roteiro de passos vem de `roteiro:` no `caso.yaml` ou de
   `roteiro.yaml` na mesma pasta; sem eles, é derivado das falas e evidências do caso.

Formato de um passo de roteiro (YAML):
```yaml
roteiro:
  - titulo: Vídeo do curral
    fala: Estou no curral, vou filmar o lote passando pelo corredor.
    evidencia: video_curral_1      # id ou nome de arquivo de uma evidência do caso
  - {titulo: Pedido de rascunho, acao: rascunho}   # botão "emitir rascunho" (ação humana direta)
  - {titulo: Assinatura humana, acao: assinar}     # abre o diálogo de PIN na interface
  - {titulo: Residual lido do papel, acao: residual, fala_prefixo: "Lendo no papel: "}
                         # a fiscal lê no papel só o que a foto do DANFE não validou (o impresso vem de
                         # documentos.danfe_foto.verdade); sem residual pendente, o passo não faz nada
```

Horários: as evidências do caso levam o `recebida_em` (e o `capturada_em`) do próprio caso, como a CLI
(`roteiro_demo.carregar_caso_real`): fotos e vídeo com os do `caso.yaml`; NF-e, GTA e foto do DANFE com o
horário do documento no dia da fiscalização (09:50, -03:00). Sem isso, a demo rodada dias depois receberia os
arquivos "agora" e a integridade acusaria captura muito anterior ao recebimento.

Split de teste congelado: um caso `GLD-*` do split de teste (`eval/golden/casos/SPLIT.yaml`,
`congelado: true`) não abre pela web nem pela CLI (`CasoDoTesteCongelado`): seria uso do teste fora do
registro (`eval/golden/casos/registro_teste.jsonl`, só pelo avaliador com `--final`).
`LAUDO_USO_TESTE_CONGELADO=1` abre assim mesmo, com aviso no log e no resumo do caso (para depurar, nunca para
medir).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from laudo import demonstracao
from laudo.agent.condutor import NovaEvidencia
from laudo.contracts import GPS, Operacao

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[3]
DIRS_CASOS = [REPO / "eval" / "golden" / "demo", REPO / "eval" / "golden" / "casos"]
SPLIT_YAML = REPO / "eval" / "golden" / "casos" / "SPLIT.yaml"
REGISTRO_TESTE = REPO / "eval" / "golden" / "casos" / "registro_teste.jsonl"
ENV_USO_TESTE = "LAUDO_USO_TESTE_CONGELADO"
_FUSO_DEMO = timezone(timedelta(hours=-3))
_FAKE_CONTADOR = "detector + rastreador + linha de contagem (FAKE: saída simulada do caso)"


class ArquivoCaso(BaseModel):
    """Evidência pronta do caso (o operador escolhe na interface em vez de procurar arquivo)."""

    nome: str  # chave única no caso (nome do arquivo)
    rotulo: str
    tipo: str
    item_id: str | None = None
    disponivel: bool = True  # False = marcador (arquivo real ainda não existe)
    nova: NovaEvidencia  # exatamente o que vai para o condutor


class PassoRoteiro(BaseModel):
    n: int
    titulo: str
    fala: str = ""
    evidencia: str | None = None  # `ArquivoCaso.nome`
    acao: Literal["turno", "rascunho", "assinar", "residual"] = "turno"
    fala_prefixo: str = ""  # acao=residual: começo da fala ("Lendo no papel: ")
    passos_llm: list[Any] = Field(default_factory=list, exclude=True)  # roteiro do LLM falso

    model_config = {"arbitrary_types_allowed": True}


class CasoDemo(BaseModel):
    id: str
    titulo: str
    descricao: str = ""
    fis_id: str
    semente_ids: str
    operacao: Operacao
    arquivos: list[ArquivoCaso] = Field(default_factory=list)
    roteiro: list[PassoRoteiro] = Field(default_factory=list)
    cenario: dict[str, dict[str, Any]] = Field(default_factory=dict)  # ferramentas falsas, por arquivo
    triagem: dict[str, Any] = Field(default_factory=dict)
    replay_padrao: str | None = None
    data_fiscalizacao: date | None = None
    data_referencia: date | None = None
    sintetico: bool = True
    papel_danfe: dict[str, Any] = Field(default_factory=dict, exclude=True)  # o que está impresso no DANFE
    aviso_uso: str | None = None  # caso do split de teste aberto com LAUDO_USO_TESTE_CONGELADO=1

    def arquivo(self, nome: str) -> ArquivoCaso | None:
        return next((a for a in self.arquivos if a.nome == nome), None)

    def resumo(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "fis_id": self.fis_id,
            "ref_bacen": self.operacao.ref_bacen,
            "municipio": self.operacao.municipio_nome,
            "n_passos": len(self.roteiro),
            "sintetico": self.sintetico,
            "demonstracao": demonstracao.bloco_laudo(self.operacao),
            "instituicao": self.operacao.instituicao,
            "arquivos": [a.model_dump(exclude={"nova"}) for a in self.arquivos],
            **({"aviso_uso": self.aviso_uso} if self.aviso_uso else {}),
        }


_ROTULOS_TIPO = {
    "video": "Vídeo",
    "foto": "Foto",
    "nfe_xml": "NF-e (XML)",
    "gta": "GTA",
    "documento": "Documento",
}


# ---------------------------------------------------------------------------
# 1. Roteiro do agente
# ---------------------------------------------------------------------------


def caso_roteiro(dir_arquivos: Path) -> CasoDemo:
    from laudo.agent import roteiro_demo as demo

    arquivos_dir = demo.preparar_arquivos(dir_arquivos)
    arquivos: list[ArquivoCaso] = []
    passos: list[PassoRoteiro] = []
    for t in demo.turnos(arquivos_dir):
        nome = None
        if t.evidencia is not None:
            nome = Path(t.evidencia.caminho or "").name
            if not any(a.nome == nome for a in arquivos):
                arquivos.append(
                    ArquivoCaso(
                        nome=nome,
                        rotulo=f"{_ROTULOS_TIPO.get(t.evidencia.tipo, t.evidencia.tipo)}: {nome}",
                        tipo=t.evidencia.tipo,
                        item_id=t.evidencia.item_id,
                        nova=t.evidencia,
                    )
                )
        passos.append(
            PassoRoteiro(
                n=len(passos) + 1, titulo=t.titulo, fala=t.fala, evidencia=nome, passos_llm=list(t.passos)
            )
        )
    passos.append(PassoRoteiro(n=len(passos) + 1, titulo="Assinatura humana (PIN + hash)", acao="assinar"))
    passos.append(
        PassoRoteiro(
            n=len(passos) + 1, titulo="Tentativa de alterar laudo selado", fala="Muda a contagem para 41."
        )
    )
    replay = REPO / "tests" / "unit" / "dados_agente" / "replay_demo_qwen35_4b.jsonl"
    return CasoDemo(
        id="roteiro",
        titulo="Roteiro do regional (40 garrotes + 800 m de cerca)",
        descricao="Fiscalização sintética do roteiro do agente: divergência na contagem, pressão recusada, "
        "rascunho bloqueado, correção com GTA e segundo vídeo, emissão e assinatura humana.",
        fis_id=demo.FIS_ID,
        semente_ids=demo.SEMENTE_IDS,
        operacao=demo.operacao_demo(),
        arquivos=arquivos,
        roteiro=passos,
        cenario=dict(demo.CENARIO),
        triagem={
            "prioridade_nivel": "media",
            "motivos": ["caso sintético de demonstração (roteiro do agente)"],
        },
        replay_padrao=str(replay) if replay.exists() else None,
    )


# ---------------------------------------------------------------------------
# 2. Caso no formato do golden set
# ---------------------------------------------------------------------------


def localizar_caso(caso: str) -> Path | None:
    """`DEMO-0001` → pasta com caso.yaml (em eval/golden/demo ou eval/golden/casos; depois, nas pastas de
    `LAUDO_CASOS_DIR`, pelo nome da pasta ou pelo `id` do caso.yaml); aceita caminho direto."""
    p = Path(caso)
    if (p / "caso.yaml").exists():
        return p
    if p.name == "caso.yaml" and p.exists():
        return p.parent
    for base in DIRS_CASOS:
        if (base / caso / "caso.yaml").exists():
            return base / caso
    externas = demonstracao.pastas_casos_externos()
    for pasta in externas:
        if pasta.name == caso:
            return pasta
    for pasta in externas:
        if _id_do_caso(pasta) == caso:
            return pasta
    return None


def _id_do_caso(pasta: Path) -> str | None:
    try:
        dados = yaml.safe_load((pasta / "caso.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(dados, dict) or not dados.get("id"):
        return None
    return str(dados["id"])


class CasoDoTesteCongelado(PermissionError):
    """Caso do split de teste congelado aberto fora do avaliador (uso fora do registro)."""


def casos_do_teste_congelado(split_yaml: Path | None = None) -> set[str]:
    """Ids do split de teste quando `SPLIT.yaml` diz `congelado: true` (vazio se não congelado ou sem o
    arquivo)."""
    p = split_yaml or SPLIT_YAML
    if not p.is_file():
        return set()
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    return {str(x) for x in d.get("test") or []} if d.get("congelado") else set()


def checar_uso_do_teste(pasta: Path, cid: str | None = None) -> str | None:
    """Recusa (`CasoDoTesteCongelado`) abrir pela web ou pela CLI um caso do split de teste congelado. Com
    `LAUDO_USO_TESTE_CONGELADO=1`, deixa abrir e devolve o aviso (que vai ao log e ao resumo do caso)."""
    ids = casos_do_teste_congelado()
    alvo = {str(cid or ""), Path(pasta).name} & ids
    if not alvo:
        return None
    gid = min(alvo)
    msg = (
        f"{gid} é do split de teste congelado ({SPLIT_YAML.relative_to(REPO).as_posix()}): abrir pela web ou "
        f"pela CLI é uso do teste fora do registro ({REGISTRO_TESTE.relative_to(REPO).as_posix()}). Rode o "
        "avaliador com --final (eval/README.md) ou use um caso do dev"
    )
    if os.environ.get(ENV_USO_TESTE) == "1":
        aviso = f"AVISO: {msg} ({ENV_USO_TESTE}=1: aberto assim mesmo; não use para medir)"
        log.warning(aviso)
        return aviso
    raise CasoDoTesteCongelado(msg + f" ({ENV_USO_TESTE}=1 abre assim mesmo, só para depurar).")


def listar_casos_disponiveis() -> list[str]:
    """Casos da carteira: as pastas `DEMO*` do repositório e, depois, todas as pastas de caso de
    `LAUDO_CASOS_DIR` (casos de demonstração montados fora do repositório, com qualquer nome)."""
    vistos: list[str] = []
    for base in DIRS_CASOS:
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if (d / "caso.yaml").exists() and d.name.upper().startswith("DEMO") and d.name not in vistos:
                    vistos.append(d.name)
    for d in demonstracao.pastas_casos_externos():
        if d.name not in vistos:
            vistos.append(d.name)
    return vistos


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _gps(d: dict[str, Any] | None, fonte: str = "app") -> GPS | None:
    if not d or d.get("lat") is None or d.get("lon") is None:
        return None
    return GPS(lat=float(d["lat"]), lon=float(d["lon"]), precisao_m=d.get("precisao_m"), fonte=fonte)  # type: ignore[arg-type]


def _status_esperado(esperado: dict[str, Any], prefixo: str) -> tuple[str, str]:
    """Status agregado dos campos esperados com o prefixo (cenário das ferramentas falsas)."""
    campos = {k: v for k, v in (esperado.get("campos") or {}).items() if prefixo in k}
    divs = [(k, v) for k, v in campos.items() if v.get("status_esperado") == "divergente"]
    if divs:
        return "divergente", "; ".join(
            f"{k.split(':')[-1]}: {v.get('motivo') or 'divergente'}" for k, v in divs
        )
    pend = [(k, v) for k, v in campos.items() if v.get("status_esperado") in ("pendente", "abstencao")]
    if pend:
        return "indeterminado", "; ".join(v.get("motivo") or k for k, v in pend)
    return "ok", "critérios conferem (saída simulada a partir do caso)"


def caso_yaml(pasta: Path, dir_trabalho: Path) -> CasoDemo:
    dados = yaml.safe_load((pasta / "caso.yaml").read_text(encoding="utf-8"))
    cid = str(dados.get("id") or pasta.name)
    op = Operacao.model_validate(dados["operacao"])
    esperado = dados.get("esperado") or {}
    arquivos: list[ArquivoCaso] = []
    cenario: dict[str, dict[str, Any]] = {}
    item_bov = next((i.id for i in op.itens if i.tipo == "bovinos"), None)
    docs = dados.get("documentos") or {}
    df = dados.get("data_fiscalizacao")
    dia = date.fromisoformat(str(df)) if df else None
    # documento recebido no dia da fiscalização (o mesmo horário da CLI: roteiro_demo.carregar_caso_real)
    hora_doc = datetime(dia.year, dia.month, dia.day, 9, 50, tzinfo=_FUSO_DEMO) if dia else None

    for k, n in enumerate(docs.get("nfe") or [], 1):
        nome = n["arquivo"]
        arquivos.append(
            ArquivoCaso(
                nome=nome,
                rotulo=f"NF-e {k} (XML)",
                tipo="nfe_xml",
                item_id=item_bov,
                nova=NovaEvidencia(
                    tipo="nfe_xml",
                    caminho=str(pasta / nome),
                    item_id=item_bov,
                    recebida_em=_dt(n.get("recebida_em")) or hora_doc,
                ),
            )
        )
        st, motivo = _status_esperado(esperado, "nfe")
        cenario[nome] = {"conciliar_nfe": {"status": st, "motivo": motivo}}
    for k, g in enumerate(docs.get("gta") or [], 1):
        nome = g.get("arquivo_json") or g.get("arquivo_pdf")
        arquivos.append(
            ArquivoCaso(
                nome=nome,
                rotulo=f"GTA {k} ({g.get('identificador', '')})".strip(),
                tipo="gta",
                item_id=item_bov,
                nova=NovaEvidencia(
                    tipo="gta",
                    caminho=str(pasta / nome),
                    item_id=item_bov,
                    recebida_em=_dt(g.get("recebida_em")) or hora_doc,
                ),
            )
        )
        st, motivo = _status_esperado(esperado, "gta")
        cenario[nome] = {"conciliar_gta": {"status": st, "motivo": motivo}}
    danfe = docs.get("danfe_foto") or {}
    papel_danfe: dict[str, Any] = {}
    if danfe.get("arquivo") and (pasta / danfe["arquivo"]).is_file():
        if danfe.get("verdade") and (pasta / danfe["verdade"]).is_file():
            import json

            papel_danfe = (
                json.loads((pasta / danfe["verdade"]).read_text(encoding="utf-8")).get("campos") or {}
            )
        arquivos.append(
            ArquivoCaso(
                nome=Path(danfe["arquivo"]).name,
                rotulo="Foto da nota impressa (DANFE): leitura por VLM + residual",
                tipo="documento",
                item_id=item_bov,
                nova=NovaEvidencia(
                    tipo="documento",
                    caminho=str(pasta / danfe["arquivo"]),
                    item_id=item_bov,
                    meta={"tipo_documento": "danfe"},
                    recebida_em=_dt(danfe.get("recebida_em")) or hora_doc,
                ),
            )
        )
    for f in dados.get("fotos") or []:
        nome = Path(f["arquivo"]).name
        exif = f.get("exif") or {}
        arquivos.append(
            ArquivoCaso(
                nome=nome,
                rotulo=f"Foto {f.get('id', nome)} ({f.get('item_id')})",
                tipo="foto",
                item_id=f.get("item_id"),
                nova=NovaEvidencia(
                    tipo="foto",
                    caminho=str(pasta / f["arquivo"]),
                    item_id=f.get("item_id"),
                    gps=_gps(f.get("gps_app")),
                    capturada_em=_dt(f.get("capturada_em") or exif.get("data_hora")),
                    # recebimento do caso (como em roteiro_demo.carregar_caso_real), não o relógio da máquina:
                    # sem isso a foto do caso vira "captura N h antes do recebimento" (> 72 h) quando a demo
                    # roda dias depois, e o rascunho fica bloqueado (contingência e demo ao vivo do caso)
                    recebida_em=_dt(f.get("recebida_em")),
                ),
            )
        )
        cenario[nome] = {
            "integridade_foto": {
                "status": "ok",
                "exif": bool(exif.get("presente")),
                "gps_exif": bool(exif.get("gps")),
                "duplicata_de": [],
            }
        }
    v = dados.get("video")
    if v:
        nome_v = Path(str(v.get("arquivo") or "curral.mp4")).name
        real = pasta / str(v.get("arquivo") or "")
        disponivel = bool(v.get("arquivo")) and real.is_file()
        if disponivel:
            caminho = real
        else:
            caminho = dir_trabalho / cid / nome_v
            caminho.parent.mkdir(parents=True, exist_ok=True)
            if not caminho.exists():
                caminho.write_bytes(f"marcador sintético: vídeo {v.get('id')} do caso {cid}\n".encode())
        sim = v.get("saida_simulada_contador") or {}
        cenario[nome_v] = {
            "contar_bovinos_video": {
                "status": "ok" if sim.get("estimativa") is not None else "indeterminado",
                "contagem": sim.get("estimativa"),
                "intervalo": sim.get("ic80"),
                "confianca": sim.get("confianca"),
                "oclusao": sim.get("oclusao_frac"),
                "metodo": _FAKE_CONTADOR,
            }
        }
        arquivos.append(
            ArquivoCaso(
                nome=nome_v,
                rotulo=f"Vídeo do curral ({v.get('duracao_s', '?')} s)"
                + ("" if disponivel else " — marcador, contagem simulada"),
                tipo="video",
                item_id=v.get("item_id") or item_bov,
                disponivel=disponivel,
                nova=NovaEvidencia(
                    tipo="video",
                    caminho=str(caminho),
                    item_id=v.get("item_id") or item_bov,
                    lote=v.get("lote") or "curral",
                    capturada_em=_dt(v.get("capturada_em")),
                    recebida_em=_dt(v.get("recebida_em")),
                ),
            )
        )

    roteiro_bruto = dados.get("roteiro")
    if roteiro_bruto is None and (pasta / "roteiro.yaml").exists():
        r = yaml.safe_load((pasta / "roteiro.yaml").read_text(encoding="utf-8"))
        roteiro_bruto = r.get("roteiro") if isinstance(r, dict) else r
    if roteiro_bruto is None:
        roteiro_bruto = _roteiro_derivado(dados, arquivos)
    # o roteiro pode citar a evidência pelo id do caso (foto_cerca_1, video_curral_1) ou pelo nome do arquivo
    por_id = {str(f.get("id")): Path(f["arquivo"]).name for f in dados.get("fotos") or []}
    if v:
        por_id[str(v.get("id"))] = Path(str(v.get("arquivo") or "curral.mp4")).name
    if danfe.get("arquivo"):
        por_id["danfe_1"] = Path(danfe["arquivo"]).name
    passos = []
    for p in roteiro_bruto:
        ev = p.get("evidencia")
        ev = por_id.get(str(ev), ev) if ev else None
        passos.append(
            PassoRoteiro(
                n=len(passos) + 1,
                titulo=p.get("titulo") or f"Passo {len(passos) + 1}",
                fala=p.get("fala") or "",
                evidencia=ev,
                acao=p.get("acao") or "turno",
                fala_prefixo=p.get("fala_prefixo") or "",
                passos_llm=_llm_do_passo(p),
            )
        )
    triagem = dados.get("triagem") or {
        "prioridade_nivel": "media",
        "motivos": [f"caso sintético do golden set ({(dados.get('defeito') or {}).get('titulo', cid)})"],
    }
    replay = next(iter(sorted(pasta.glob("replay*.jsonl"))), None)
    return CasoDemo(
        id=cid,
        titulo=f"{cid}: {(dados.get('defeito') or {}).get('titulo') or 'caso de demonstração'}",
        descricao=(dados.get("defeito") or {}).get("descricao", ""),
        fis_id="fis_" + "".join(c for c in cid.lower().replace("-", "_") if c.isalnum() or c == "_"),
        semente_ids=f"caso-{cid}",
        operacao=op,
        arquivos=arquivos,
        roteiro=passos,
        cenario=cenario,
        triagem=triagem,
        replay_padrao=str(replay) if replay else None,
        data_fiscalizacao=date.fromisoformat(str(df)) if df else None,
        data_referencia=date.fromisoformat(str(dados["data_referencia"]))
        if dados.get("data_referencia")
        else None,
        sintetico=bool(dados.get("sintetico", True)),
        papel_danfe=papel_danfe,
    )


def _sem_acento(t: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode("ascii").lower()


_ASPECTO_POR_PALAVRA = [
    (r"contagem|quantidade|cabeca|vaca|boi|garrote|novilh|lote|animais", ("quantidade",)),
    (r"\bgta\b", ("gta", "gta_data")),
    (r"nota|nf-?e", ("nfe",)),
    (r"foto|cerca|gleba|curral|benfeitoria", ("existencia", "localizacao")),
]


def _justificar(fala: str):
    """LLM roteirizado: registra a fala como justificativa do campo divergente que ela cita (para testes sem
    GPU; com Ollama quem escolhe o campo é o modelo, e a política confere o trecho literal)."""
    import json
    import re

    from laudo.llm.provider import ChamadaFerramenta, RespostaLLM

    def f(mensagens):
        ctx: dict[str, Any] = {}
        for m in reversed(mensagens):
            achou = re.search(r"<contexto>(.*?)</contexto>", str(m.get("content") or ""), re.DOTALL)
            if m.get("role") == "user" and achou:
                try:
                    ctx = json.loads(achou.group(1))
                except json.JSONDecodeError:
                    ctx = {}
                break
        divs = [
            c["campo"]
            for c in ctx.get("campos", [])
            if c.get("status") == "divergente" and not c.get("justificativa")
        ]
        t = _sem_acento(fala)
        alvo = None
        for rx, sufixos in _ASPECTO_POR_PALAVRA:
            if re.search(rx, t):
                alvo = next((c for c in divs if c.split(":")[-1] in sufixos), None)
                if alvo:
                    break
        alvo = alvo or (divs[0] if divs else None)
        if not alvo:
            return RespostaLLM(conteudo="")
        return RespostaLLM(
            chamadas=[
                ChamadaFerramenta(nome="registrar_justificativa", argumentos={"campo": alvo, "trecho": fala})
            ]
        )

    return f


def _llm_do_passo(p: dict[str, Any]) -> list[Any]:
    """Respostas do LLM roteirizado para um passo de caso YAML (só no modo `--llm roteiro`).

    Explícito: `llm: [{acao: explicar_regra}, {falar: "..."}]`. Sem isso, heurística pela fala: "confirmo a
    divergência…" → `registrar_justificativa`. Emitir o rascunho e mandar para assinatura são comandos humanos
    reconhecidos sem LLM (`intencao.comando_humano`): o LLM nem é consultado nesses turnos. Uploads ficam com
    o plano mínimo determinístico do condutor."""
    import re

    from laudo.agent.roteiro_demo import chamar, falar

    if p.get("llm"):
        out = []
        for x in p["llm"]:
            if "falar" in x:
                out.append(falar(str(x["falar"])))
            elif x.get("acao") == "registrar_justificativa" and not x.get("argumentos"):
                out.append(_justificar(p.get("fala") or ""))
            else:
                out.append(
                    chamar(x["acao"], com_evidencia=bool(x.get("com_evidencia")), args=x.get("argumentos"))
                )
        return out
    if p.get("evidencia") or p.get("acao") in ("assinar", "rascunho", "residual"):
        return []
    t = _sem_acento(p.get("fala") or "")
    if re.search(r"^confirmo a divergencia|justific", t):
        return [_justificar(p.get("fala") or "")]
    return []


def _roteiro_derivado(dados: dict[str, Any], arquivos: list[ArquivoCaso]) -> list[dict[str, Any]]:
    """Roteiro padrão a partir do caso: plano → vídeo → NF-e → GTA → foto → pressão → rascunho."""
    falas = [f.get("texto", "") for f in dados.get("falas") or []]
    fiscal = [f.get("texto", "") for f in dados.get("falas") or [] if f.get("de") == "fiscal"]
    pressao = next(
        (t for t in falas if "marcar" in t.lower() or "pode" in t.lower() and any(c.isdigit() for c in t)),
        None,
    )
    por_tipo: dict[str, list[ArquivoCaso]] = {}
    for a in arquivos:
        por_tipo.setdefault(a.tipo, []).append(a)
    passos: list[dict[str, Any]] = [
        {"titulo": "Plano de método", "fala": "Bom dia. Vamos começar a fiscalização desta operação."}
    ]
    if por_tipo.get("video"):
        passos.append(
            {
                "titulo": "Coleta: vídeo do curral",
                "fala": fiscal[0] if fiscal else "",
                "evidencia": por_tipo["video"][0].nome,
            }
        )
    for a in por_tipo.get("nfe_xml", []):
        passos.append({"titulo": "Coleta: NF-e", "evidencia": a.nome})
    for a in por_tipo.get("gta", []):
        passos.append({"titulo": "Coleta: GTA", "evidencia": a.nome})
    fotos_cerca = [a for a in por_tipo.get("foto", []) if a.item_id and a.item_id != "bov1"]
    if fotos_cerca:
        passos.append(
            {
                "titulo": "Coleta: foto da benfeitoria",
                "fala": fiscal[1] if len(fiscal) > 1 else "",
                "evidencia": fotos_cerca[0].nome,
            }
        )
    if pressao:
        passos.append({"titulo": "Pressão", "fala": pressao})
    passos.append({"titulo": "Pedido de rascunho", "acao": "rascunho"})
    return passos


def carregar_caso(caso: str, dir_trabalho: Path) -> CasoDemo:
    """`roteiro`, um id (`DEMO-0001`) ou o caminho de uma pasta com caso.yaml."""
    if caso == "roteiro":
        return caso_roteiro(dir_trabalho / "roteiro")
    pasta = localizar_caso(caso)
    if pasta is None:
        bases = [*DIRS_CASOS, *demonstracao.dirs_casos_externos()]
        raise FileNotFoundError(f"caso {caso!r} não encontrado (procurei em {', '.join(map(str, bases))})")
    aviso = checar_uso_do_teste(pasta, caso)  # split de teste congelado: recusa (ou avisa, com a variável)
    c = caso_yaml(pasta, dir_trabalho)
    if aviso:
        c.aviso_uso = aviso
    return c


def caso_padrao() -> str:
    """Caso aberto por padrão: `LAUDO_CASO_DEMO` ou o roteiro do agente."""
    return os.environ.get("LAUDO_CASO_DEMO") or "roteiro"
