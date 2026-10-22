"""Execução de ferramentas do REGISTRO com contrato, timeout, retentativa e trace.

- Valida a entrada com o modelo Pydantic da ferramenta (`ENTRADA_INVALIDA` se não casar). Id de evidência
  (`ev_...`) que sobrou num campo de caminho (evidência inexistente ou sem arquivo) também é `ENTRADA_INVALIDA`:
  a ferramenta nunca abre um "arquivo" chamado `ev_...`.
- Timeout por ferramenta (`Ferramenta.timeout_s`; `serie_ndvi` = 240 s) → `TIMEOUT`. A contagem de bovinos
  tem timeout proporcional à duração do vídeo (`timeout_efetivo`).
- Erro retryable: 2 novas tentativas com backoff; depois o envelope de erro volta e o campo fica "pendente".
  TIMEOUT só é repetido em ferramenta curta (≤ 30 s): repetir 4 min de satélite não ajuda o fiscal.
- Exceção solta vira `ERRO_INTERNO` (a ferramenta nunca derruba o agente; o valor nunca é inventado).
- Ferramenta inexistente vira `FORA_DO_ESCOPO` (caminho "nenhuma ferramenta serve").
- `data["status"]` sai sempre no vocabulário `StatusChecagem` (ok/divergente/indeterminado/erro): se a
  ferramenta devolver outro termo, o executor converte com `para_status_checagem` e guarda o original em
  `status_ferramenta`.
- Cada chamada gera um span `tool <nome>` com o hash dos argumentos (nunca os argumentos crus).

`preencher_argumentos` resolve referências que o LLM não deve copiar à mão (caminho do arquivo a partir do
`evidencia_id`, polígono da gleba, item financiado, GPS da evidência, contexto das regras, data de
referência, índice de documentos de laudos selados com a ref. Bacen da operação), olhando os nomes dos campos
do esquema de entrada de cada ferramenta. Assim o agente programa
contra o contrato, não contra a implementação.
"""

from __future__ import annotations

import concurrent.futures as cf
import re
import time
import typing
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from laudo import privacidade
from laudo.agent.estado import evidencia_por_id
from laudo.agent.indice import argumentos_de_consulta
from laudo.agent.pii import mascarar
from laudo.audit import otel
from laudo.audit.cofre import Cofre
from laudo.contracts import (
    GPS,
    CodigoErro,
    Envelope,
    Ferramenta,
    Fiscalizacao,
    hash_entrada,
    para_status_checagem,
)

_POOL = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="ferramenta")
STATUS_COMUNS = ("ok", "divergente", "indeterminado", "erro")
TIMEOUT_REPETIVEL_S = 30.0

_CAMPOS_CAMINHO = {
    "caminho",
    "arquivo",
    "caminho_arquivo",
    "caminho_video",
    "caminho_foto",
    "caminho_xml",
    "caminho_documento",
    "video",
    "foto",
    "xml",
    "path",
    "video_path",
    "foto_path",
    "xml_path",
}
_CAMPOS_LISTA_CAMINHO = {"caminhos", "nfe_caminhos"}
_CAMPOS_WKT = {"gleba_wkt", "poligono_wkt", "wkt", "poligono"}
_RX_ID_EV = re.compile(r"^ev_[0-9a-zA-Z_]+$")
# Campos de entrada que só fazem sentido a partir de uma evidência da fiscalização (arquivo, GPS, EXIF, hash).
CAMPOS_DE_EVIDENCIA = frozenset({
    "caminho", "arquivo", "caminho_arquivo", "caminho_video", "caminho_foto", "caminho_xml", "video", "foto",
    "xml", "path", "caminhos", "lat", "lon", "ponto", "gps", "exif", "sha256",
})
# Checagens que só valem ligadas a uma evidência da fiscalização ("sem fonte, sem afirmação"): sem
# evidência, a ferramenta não roda pelo condutor (ENTRADA_INVALIDA) e uma checagem dessas sem evidência não
# define campo.
FERRAMENTAS_SOBRE_EVIDENCIA = frozenset({
    "contar_bovinos_video", "conciliar_nfe", "conciliar_gta", "integridade_foto", "geofence",
    "classificar_foto", "ler_documento_foto", "completar_leitura_documento",
})


def sobre_evidencia(nome: str, registro: dict[str, Ferramenta] | None = None) -> bool:
    """A ferramenta trabalha sobre uma evidência (lista fixa ou entrada com campo de evidência)?"""
    if nome in FERRAMENTAS_SOBRE_EVIDENCIA:
        return True
    ferr = (registro or {}).get(nome)
    return ferr is not None and bool(set(ferr.entrada.model_fields) & CAMPOS_DE_EVIDENCIA)


def ids_nao_resolvidos(argumentos: dict[str, Any]) -> list[str]:
    """Ids `ev_...` que sobraram em campo de caminho: a evidência não existe (ou não tem arquivo)."""
    soltos: list[str] = []
    for k, v in argumentos.items():
        if k in _CAMPOS_LISTA_CAMINHO and isinstance(v, list):
            valores = v
        else:
            valores = [v] if k in _CAMPOS_CAMINHO else []
        soltos += [x for x in valores if isinstance(x, str) and _RX_ID_EV.match(x)]
    return soltos
# Segundos de CPU por segundo de vídeo a 8 quadros/s (medidos; docs/modelos.md), com folga.
_S_POR_S_VIDEO = {"yolox_tiny": 0.2, "yolox_s": 0.4, "yolox_m": 0.8}
_NIVEL_TRIAGEM = {"alta": "alta", "media": "media", "baixa": "baixa", "sem_sinal": "baixa"}


def normalizar_status(env: Envelope) -> Envelope:
    """Garante `data["status"]` no vocabulário `StatusChecagem` (o original fica em `status_ferramenta`)."""
    if not env.data or "status" not in env.data:
        return env
    bruto = env.data.get("status")
    if bruto in STATUS_COMUNS:
        return env
    data = dict(env.data)
    data["status_ferramenta"] = bruto
    data["status"] = para_status_checagem(str(bruto) if bruto is not None else None)
    return env.model_copy(update={"data": data})


def timeout_efetivo(ferr: Ferramenta, entrada: BaseModel) -> float:
    """Timeout da chamada. Para `contar_bovinos_video` é proporcional à duração do vídeo (até o limite
    `max_duracao_s` da própria entrada); nas demais é o `timeout_s` registrado."""
    if ferr.nome != "contar_bovinos_video":
        return ferr.timeout_s
    caminho = getattr(entrada, "caminho_video", None)
    try:
        from laudo.vision.video import info_video

        duracao = info_video(str(caminho)).duracao_s if caminho and Path(caminho).is_file() else None
    except Exception:  # noqa: BLE001 - vídeo ilegível: a própria ferramenta devolve o erro
        duracao = None
    if not duracao:
        return ferr.timeout_s
    duracao = min(duracao, float(getattr(entrada, "max_duracao_s", duracao) or duracao))
    fator = _S_POR_S_VIDEO.get(str(getattr(entrada, "modelo", "yolox_m")), 0.8)
    fator *= float(getattr(entrada, "fps_amostragem", 8.0) or 8.0) / 8.0
    return round(30.0 + 2.0 * fator * duracao, 1)


class ExecutorFerramentas:
    def __init__(
        self,
        registro: dict[str, Ferramenta],
        retentativas: int = 2,
        backoff_s: float = 0.5,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self.registro = registro
        self.retentativas = retentativas
        self.backoff_s = backoff_s
        self._dormir = dormir

    def executar(self, nome: str, argumentos: dict[str, Any]) -> tuple[Envelope, str, str]:
        """Executa a ferramenta. Devolve (envelope, span_id, entrada_hash)."""
        h = hash_entrada(argumentos)
        with otel.span_ferramenta(nome, argumentos) as s:
            env = normalizar_status(self._executar(nome, argumentos, s))
            otel.definir(
                s,
                **{
                    "tool.ok": env.ok,
                    "tool.latency_ms": env.latency_ms,
                    "tool.fonte_versao": env.fonte_versao,
                    "tool.envelope_trace_id": env.trace_id,
                    "tool.error_code": str(env.error.code) if env.error else None,
                    "tool.status": str((env.data or {}).get("status", "")),
                    "tool.resumo": resumo_envelope(env),
                },
            )
            if not env.ok:
                otel.marcar_erro(s, env.error.msg if env.error else "erro")
            return env, otel.id_span(s), h

    def _executar(self, nome: str, argumentos: dict[str, Any], s) -> Envelope:
        ferr = self.registro.get(nome)
        if ferr is None:
            return Envelope.falha(
                nome, CodigoErro.FORA_DO_ESCOPO, f"nenhuma ferramenta registrada com o nome {nome!r}"
            )
        if soltos := ids_nao_resolvidos(argumentos):
            return Envelope.falha(
                nome, CodigoErro.ENTRADA_INVALIDA,
                f"evidência {', '.join(soltos[:3])} não existe nesta fiscalização (ou não tem arquivo)",
            )
        try:
            entrada = ferr.entrada.model_validate(argumentos)
        except ValidationError as e:
            erros = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:5])
            return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, mascarar(erros))
        timeout = timeout_efetivo(ferr, entrada)
        otel.definir(s, **{"tool.timeout_s": timeout})
        env: Envelope | None = None
        for tentativa in range(self.retentativas + 1):
            if tentativa:
                self._dormir(self.backoff_s * (2 ** (tentativa - 1)))
            env = self._uma_vez(ferr, entrada, timeout)
            otel.definir(s, **{"tool.tentativas": tentativa + 1})
            if env.ok or not (env.error and env.error.retryable):
                break
            if env.error.code == CodigoErro.TIMEOUT and timeout > TIMEOUT_REPETIVEL_S:
                break
        assert env is not None
        return env

    def _uma_vez(self, ferr: Ferramenta, entrada, timeout: float) -> Envelope:
        t0 = time.perf_counter()
        futuro = _POOL.submit(ferr.funcao, entrada)
        try:
            env = futuro.result(timeout=timeout)
        except cf.TimeoutError:
            return Envelope.falha(
                ferr.nome,
                CodigoErro.TIMEOUT,
                f"sem resposta em {timeout:.0f} s",
                retryable=True,
                t0=t0,
            )
        except Exception as e:  # noqa: BLE001 - ferramenta nunca derruba o agente
            return Envelope.falha(
                ferr.nome, CodigoErro.ERRO_INTERNO, mascarar(f"{type(e).__name__}: {e}")[:300], t0=t0
            )
        if not isinstance(env, Envelope):
            return Envelope.falha(
                ferr.nome, CodigoErro.ERRO_INTERNO, "ferramenta não devolveu Envelope", t0=t0
            )
        return env


def resumo_envelope(env: Envelope, limite: int = 300) -> str:
    if not env.ok:
        return f"ERRO {env.error.code if env.error else ''}: {env.error.msg if env.error else ''}"[:limite]
    d = env.data or {}
    chaves = [
        k
        for k in (
            "status",
            "posicao",
            "contagem",
            "intervalo",
            "quantidade",
            "valor",
            "motivo",
            "metodo",
            "hash_raiz",
        )
        if k in d
    ]
    partes = [f"{k}={d[k]}" for k in chaves] or [f"{k}=…" for k in list(d)[:6]]
    return mascarar(", ".join(partes))[:limite]


# ---------------------------------------------------------------------------
# Preenchimento de argumentos a partir do estado
# ---------------------------------------------------------------------------


def prioridade_da_triagem(fis: Fiscalizacao) -> str | None:
    """Nível de prioridade de verificação da operação, lido da checagem de triagem mais recente
    (`carregar_operacao` ou `triar_carteira`). `sem_sinal` conta como baixa."""
    for chk in reversed(fis.checagens):
        if chk.status == "erro":
            continue
        r = chk.resultado
        nivel = None
        if chk.ferramenta == "carregar_operacao":
            nivel = (r.get("triagem") or {}).get("prioridade_nivel")
        elif chk.ferramenta == "triar_carteira":
            nivel = next(
                (
                    o.get("prioridade_nivel")
                    for o in r.get("operacoes") or []
                    if o.get("ref_bacen") == fis.operacao.ref_bacen
                ),
                None,
            )
        if nivel in _NIVEL_TRIAGEM:
            return _NIVEL_TRIAGEM[nivel]
    return None


def _tipo_do_campo(ferr: Ferramenta, nome: str) -> Any:
    info = ferr.entrada.model_fields.get(nome)
    return info.annotation if info is not None else None


def _modelo_do_campo(ferr: Ferramenta, nome: str) -> type[BaseModel] | None:
    tipo = _tipo_do_campo(ferr, nome)
    candidatos = [tipo, *typing.get_args(tipo)]
    return next((t for t in candidatos if isinstance(t, type) and issubclass(t, BaseModel)), None)


def _resolver_ids(fis: Fiscalizacao, args: dict[str, Any]) -> None:
    """Campos de caminho com id de evidência (`ev_...`) passam a apontar para o arquivo da evidência."""

    def caminho(v: Any) -> Any:
        if isinstance(v, str) and _RX_ID_EV.match(v):
            ev = evidencia_por_id(fis, v)
            return ev.caminho if ev is not None and ev.caminho else v
        return v

    for k in list(args):
        if k in _CAMPOS_CAMINHO:
            args[k] = caminho(args[k])
        elif k in _CAMPOS_LISTA_CAMINHO and isinstance(args[k], list):
            args[k] = [caminho(v) for v in args[k]]


DOCUMENTOS_CUMULATIVOS = {"conciliar_nfe": "nfe_xml", "conciliar_gta": "gta"}
_TIPO_LEITURA = {"conciliar_nfe": "danfe", "conciliar_gta": "gta"}


def leituras_foto_do_item(fis: Fiscalizacao, ferramenta: str, item_id: str | None,
                          cofre: Any | None = None) -> list[dict[str, Any]]:
    """`documento` validado de cada foto/PDF lido por `ler_documento_foto` ou completado pela fiscal
    (`completar_leitura_documento`): o mais recente de cada evidência, do tipo que a conciliação usa
    (DANFE → `conciliar_nfe`; GTA → `conciliar_gta`)."""
    por_ev: dict[str, dict[str, Any]] = {}
    for c in fis.checagens:
        if c.ferramenta not in ("ler_documento_foto", "completar_leitura_documento") or c.status == "erro":
            continue
        if c.resultado.get("tipo_documento") != _TIPO_LEITURA.get(ferramenta) or not c.resultado.get("documento"):
            continue
        ev = evidencia_por_id(fis, c.evidencias[0]) if c.evidencias else None
        if ev is None:  # leitura sem a foto/PDF do documento na fiscalização não entra na conciliação
            continue
        if ev.meta.get("item_id") not in (None, item_id):
            continue
        por_ev[ev.id] = c.resultado
    # no estado a chave de acesso está mascarada (LGPD); a conciliação precisa dela inteira (DANFE × XML pela
    # chave, DV): volta do cofre da fiscalização, só em memória
    return [privacidade.restaurar_resultado(r, fis.id, cofre)["documento"] for r in por_ev.values()]


def documentos_do_item(fis: Fiscalizacao, tipo: str, item_id: str | None) -> list[str]:
    """Caminhos dos documentos do tipo já recebidos para o item (na ordem de chegada, sem repetir arquivo)."""
    caminhos = [e.caminho for e in fis.evidencias
                if e.tipo == tipo and e.caminho and e.meta.get("item_id") in (None, item_id)]
    return list(dict.fromkeys(caminhos))


_CAMPOS_PONTO = frozenset({"lat", "lon", "precisao_m", "ponto", "gps"})


def gps_exif_da_foto(fis: Fiscalizacao, ev: Any) -> GPS | None:
    """GPS do EXIF de uma foto sem GPS do app (`fonte="exif"`): o que a integridade da mesma foto leu (ela roda
    antes do geofence) ou, sem ela, o lido do arquivo. A precisão vem do EXIF (GPSHPositioningError); sem ela, o
    geofence dá indeterminado (precisão ausente), nunca uma precisão inventada."""
    if ev is None or ev.tipo != "foto":
        return None
    g: Any = None
    integ = [c for c in fis.checagens if c.ferramenta == "integridade_foto" and ev.id in c.evidencias
             and c.status != "erro"]
    if integ:
        g = integ[-1].resultado.get("gps_exif")
    elif ev.caminho and Path(ev.caminho).is_file():
        try:
            from PIL import Image

            from laudo.vision.integridade import ler_exif

            with Image.open(ev.caminho) as img:
                _, g = ler_exif(img)
        except Exception:  # noqa: BLE001 - foto ilegível: sem ponto (a integridade acusa)
            g = None
    if not isinstance(g, dict) or g.get("lat") is None or g.get("lon") is None:
        return None
    try:
        prec = g.get("precisao_m")
        return GPS(lat=float(g["lat"]), lon=float(g["lon"]), fonte="exif",
                   precisao_m=float(prec) if prec is not None and float(prec) >= 0 else None)
    except (TypeError, ValueError):
        return None


def documento_tomador_hash(tomador_ref: str | None) -> str | None:
    """`tomador_ref` → `hmac:<hash do documento do tomador com o sal desta instalação>` (o de
    `comum.hash_documento`, com o prefixo que diz à ferramenta que já está convertido): serve para conferir as
    partes da NF-e/GTA sem o CPF/CNPJ em claro. Aceita `hmac:<hex>` (convertido na abertura) e o hash público
    (`sha256:<hex>` ou `<hex>`). Referência opaca ("anon", "TOMADOR-...") não serve."""
    h = privacidade.hash_referencia(tomador_ref)
    return f"hmac:{h}" if h else None


def preencher_argumentos(
    ferr: Ferramenta,
    fis: Fiscalizacao,
    base: dict[str, Any] | None = None,
    hoje: date | None = None,
    dir_dados: Path | None = None,
) -> dict[str, Any]:
    """Completa os argumentos com dados do estado, conforme os nomes dos campos da entrada da ferramenta.

    `hoje` padrão: `Fiscalizacao.data_referencia` (replay determinístico) ou a data do sistema.
    `dir_dados`: diretório de dados da fiscalização (índice de fotos, índice de documentos de laudos selados,
    quadros-chave).
    """
    hoje = hoje or fis.data_referencia or datetime.now().astimezone().date()
    args = dict(base or {})
    _resolver_ids(fis, args)
    campos = set(ferr.entrada.model_fields)
    op = fis.operacao
    ev = evidencia_por_id(fis, args.get("evidencia_id"))
    item_id = args.get("item_id") or (ev.meta.get("item_id") if ev else None)
    item = next((i for i in op.itens if i.id == item_id), None)
    data_fisc = fis.data_fiscalizacao or hoje

    def por(nome: str, valor: Any) -> None:
        if nome in campos and args.get(nome) in (None, "", []) and valor not in (None, "", []):
            args[nome] = valor

    por("fiscalizacao_id", fis.id)
    por("fiscalizacao", fis.model_dump(mode="json") if "fiscalizacao" in campos else None)
    por("operacao", op.model_dump(mode="json") if "operacao" in campos else None)
    por("ref_bacen", op.ref_bacen)
    por("municipio_ibge", op.municipio_ibge)
    por("uf", op.uf)
    por("area_ha", op.area_financiada_ha)
    por("area_financiada_ha", op.area_financiada_ha)
    por("data_contratacao", op.data_contratacao.isoformat() if op.data_contratacao else None)
    por("valor_rs", op.valor_rs)
    por("glebas_wkt", list(op.glebas_wkt))
    por("uf_operacao", op.uf)
    por("municipio_nome", op.municipio_nome)
    por("data_fiscalizacao", data_fisc.isoformat())
    por("data_referencia", hoje.isoformat())
    por("fim", hoje.isoformat())
    por("inicio", (op.data_contratacao or hoje - timedelta(days=90)).isoformat())
    por("tomador_doc_sha256", documento_tomador_hash(op.tomador_ref))
    por("codigo_estabelecimento_destino", op.codigo_estabelecimento)
    bov = [i.quantidade for i in op.itens if i.tipo == "bovinos" and i.quantidade]
    por("cabecas", sum(bov) if bov else None)
    por("compra", op.finalidade if op.finalidade in ("investimento", "custeio") else None)
    por("itens", [i.model_dump(mode="json") for i in op.itens] if "itens" in campos else None)
    por("metodo", fis.metodo)
    for nome in _CAMPOS_WKT:
        por(nome, op.glebas_wkt[0] if op.glebas_wkt else None)
    if "contexto" in campos and args.get("contexto") in (None, "", {}):
        if _modelo_do_campo(ferr, "contexto") is not None:
            # Ferramentas de regras: o que as regras precisam e não está na Operacao (o resto vem dos
            # contratos, ver tools/regras.py::completar_contexto).
            ctx: dict[str, Any] = {"data_fiscalizacao": data_fisc.isoformat()}
            if prio := prioridade_da_triagem(fis):
                ctx["prioridade_verificacao"] = prio
            args["contexto"] = ctx
        else:
            args["contexto"] = fis.id  # ex.: integridade_foto (duplicata em outra fiscalização)
    modelo_par = _modelo_do_campo(ferr, "parametros")
    if (
        modelo_par is not None
        and "aceitar_homologacao" in modelo_par.model_fields
        and "sintetico" in (op.fonte or "")
    ):
        # Documento sintético do golden set/demo: NF-e de homologação (tpAmb=2) aceita, com ressalva no laudo.
        par = dict(args.get("parametros") or {})
        par.setdefault("aceitar_homologacao", True)
        args["parametros"] = par
    por("item_id", item_id)
    if item is not None:
        por("item", item.model_dump(mode="json"))
        por("item_financiado", item.model_dump(mode="json"))
        por("quantidade_esperada", item.quantidade)
        por("quantidade_financiada", item.quantidade)
        por("categoria_animal", item.categoria_animal)
        if item.tipo in ("cerca", "curral", "galpao"):
            por("classe_esperada", item.tipo)  # classificar_foto: a foto mostra a estrutura do item?
    if dir_dados is not None:
        por("indice", str(Path(dir_dados) / "indices" / "fotos.jsonl"))
    # Índice de documentos de laudos selados (conciliar_nfe/conciliar_gta, só consulta): caminho no diretório
    # de dados e a operação (ref. Bacen), que separa a refiscalização legítima do reuso (agent/indice.py).
    for nome, valor in argumentos_de_consulta(fis, dir_dados).items():
        por(nome, valor)
    if ev is not None:
        for nome in _CAMPOS_CAMINHO:
            por(nome, ev.caminho)
        if ferr.nome in DOCUMENTOS_CUMULATIVOS and ev.tipo in (DOCUMENTOS_CUMULATIVOS[ferr.nome], "documento"):
            # NF-e e GTA se somam (duas notas, uma GTA por carga): concilia todos os documentos do mesmo tipo e
            # item já recebidos, não só o último; a checagem nova substitui as anteriores (ver condutor).
            por("caminhos", documentos_do_item(fis, DOCUMENTOS_CUMULATIVOS[ferr.nome], item_id) or None)
        if not (ev.tipo == "documento" and ferr.nome in DOCUMENTOS_CUMULATIVOS):  # foto não é XML/JSON
            por("caminhos", [ev.caminho] if ev.caminho else None)
        por("tipo_documento", ev.meta.get("tipo_documento"))  # app: botão "foto da nota" / "foto da GTA"
        por("recebida_em", ev.recebida_em.isoformat())
        por("gps_app", ev.gps.model_dump(mode="json") if ev.gps else None)
        nfes = [
            e.caminho
            for e in fis.evidencias
            if e.tipo == "nfe_xml" and e.caminho and e.meta.get("item_id") in (None, item_id)
        ]
        por("nfe_caminhos", nfes)
        por("sha256", ev.sha256)
        por("evidencia_ids", [ev.id])
        por("lote", ev.meta.get("lote") or ev.id)
        por("meta", ev.meta)
        por("exif", ev.meta.get("exif"))
        if dir_dados is not None:
            por("dir_evidencias", str(Path(dir_dados) / "evidencias" / "visao" / ev.sha256[:12]))
        # ponto da localização (geofence): o GPS do app; sem ele, o do EXIF da foto (P2-11). O `gps_app` acima
        # continua só o do app: a integridade compara o EXIF com ele, nunca com o próprio EXIF.
        gps = ev.gps
        if gps is None and campos & _CAMPOS_PONTO:
            gps = gps_exif_da_foto(fis, ev)
        if gps is not None:
            por("lat", gps.lat)
            por("lon", gps.lon)
            por("precisao_m", gps.precisao_m)
            por("ponto", gps.model_dump(mode="json"))
            por("gps", gps.model_dump(mode="json"))
        por("capturada_em", ev.capturada_em.isoformat() if ev.capturada_em else None)
    if ferr.nome in DOCUMENTOS_CUMULATIVOS:  # DANFE/GTA lidos de foto entram na mesma conciliação cumulativa
        cofre = Cofre(Path(dir_dados) / "chaves") if dir_dados is not None else None
        por("leituras_foto", leituras_foto_do_item(fis, ferr.nome, item_id, cofre))
        por("nfe_leituras_foto", leituras_foto_do_item(fis, "conciliar_nfe", item_id, cofre))
    if "evidencia_id" not in campos and "evidencia_id" in args and ev is not None:
        args.pop("evidencia_id")  # a ferramenta não conhece ids do estado; já recebeu caminho/meta
    return args
