"""Contrato das ferramentas do REGISTRO (parecer técnico 4.8; AGENTS.md "Regras de código").

Para cada ferramenta registrada:
1. entrada Pydantic válida → `Envelope` (nunca exceção); se `ok`, `data` é dict e, para toda ferramenta cujo
   resultado vira `Checagem` no condutor, `data.status` está no vocabulário comum (`contracts._MAPA_STATUS`);
2. entrada que não valida no esquema → `Envelope` com `ENTRADA_INVALIDA` (pelo executor, que valida);
3. arquivo inexistente ou corrompido → `Envelope` de falha com código padronizado, nunca valor inventado.

Além disso: o envelope sem `data.status` nunca pode virar checagem "ok" (falso verificado silencioso).

Contratos ainda não cumpridos ficam como `xfail(strict=True)`: quando alguém corrigir, o teste passa a
falhar por XPASS e o marcador deve sair.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from laudo.agent import estado as est
from laudo.agent.executor import ExecutorFerramentas
from laudo.contracts import _MAPA_STATUS, CodigoErro, Envelope, Fiscalizacao, Operacao
from laudo.tools import carregar_todas

REPO = Path(__file__).resolve().parents[2]
CASO_DIR = REPO / "eval" / "golden" / "casos" / "GLD-0002"
VIDEO_CURTO = REPO / "dados_locais" / "videos" / "sinteticos" / "s01_fila_espacada.mp4"
REGISTRO = carregar_todas()

# Ferramentas cujo resultado o condutor NÃO grava como checagem (condutor._NAO_CHECAGEM).
NAO_CHECAGEM = {"emitir_rascunho", "registrar_ocorrencia", "triar_carteira"}
VOCABULARIO = set(_MAPA_STATUS)  # sinônimos aceitos pelo mapa do contrato
ESTRITO = {"ok", "divergente", "indeterminado", "erro"}  # StatusChecagem
CODIGOS_FALHA_ENTRADA = {CodigoErro.ENTRADA_INVALIDA, CodigoErro.SEM_DADOS, CodigoErro.FORA_DO_ESCOPO}

# Contratos conhecidos como não cumpridos (relatório da Avaliação). Remover quando corrigir.
SEM_STATUS_CONHECIDO: dict[str, str] = {}


def _caso() -> dict[str, Any]:
    return yaml.safe_load((CASO_DIR / "caso.yaml").read_text(encoding="utf-8"))


def _resolver(ent: dict[str, Any]) -> dict[str, Any]:
    out = dict(ent)
    for k in ("caminhos", "nfe_caminhos"):
        if k in out:
            out[k] = [str(CASO_DIR / x) for x in out[k]]
    return out


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    """Diretórios temporários para repositório, índice de fotos e laudos."""
    from laudo.agent.politica import Politica
    from laudo.audit import otel
    from laudo.tools import laudo as ferr_laudo

    otel.configurar(tmp_path / "traces")
    repo = est.RepositorioFiscalizacoes(tmp_path)
    ferr_laudo.configurar(repo, Politica())
    yield tmp_path, repo
    ferr_laudo.configurar(None, None)


def _ref_bacen_do_bench() -> str | None:
    try:
        from laudo.geo import bench

        return str(bench.operacoes()["ref_bacen"].iloc[0])
    except Exception:  # noqa: BLE001 - sem bench: o teste correspondente é pulado
        return None


def _ndvi_falso(geom, inicio, fim, **kw):
    """Saída com o formato de `laudo.geo.ndvi.serie_ndvi` (sem rede)."""
    return {"area_ha": 10.0, "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, "n_cenas_stac": 3,
            "n_datas_disponiveis": 3, "n_datas_lidas": 3, "n_obs_limpas": 3, "serie": [], "erros": [],
            "resumo": {"ndvi_p50_mediana": 0.6}, "custo": {},
            "metadados_laudo": {"satelite": ["sentinel-2a"], "sensor": "MSI", "datas": ["2026-08-01"],
                                "metodologia": "teste"}}


def entrada_valida(nome: str, tmp: Path, repo, monkeypatch) -> dict[str, Any] | None:
    """Entrada válida e realista para cada ferramenta (None = pular nesta máquina)."""
    caso = _caso()
    op = caso["operacao"]
    gleba = op["glebas_wkt"]
    foto = next(f for f in caso["fotos"] if f["gps_app"])
    hoje = caso["data_fiscalizacao"]
    if nome == "triar_carteira":
        return {"limite": 3}
    if nome == "carregar_operacao":
        ref = _ref_bacen_do_bench()
        return {"ref_bacen": ref} if ref else None
    if nome == "checar_lotacao":
        return {"cabecas": 40, "area_ha": 50, "municipio_ibge": "5213103"}
    if nome == "serie_ndvi":
        from laudo.geo import ndvi

        monkeypatch.setattr(ndvi, "serie_ndvi", _ndvi_falso)
        return {"poligono_wkt": gleba[0], "inicio": "2026-07-01", "fim": hoje}
    if nome == "planejar_metodo":
        return {"operacao": op, "data_referencia": hoje}
    if nome == "avaliar_regras":
        fis = Fiscalizacao(operacao=Operacao.model_validate(op))
        return {"fiscalizacao": fis.model_dump(mode="json"), "data_referencia": hoje}
    if nome == "explicar_regra":
        return {"regra_id": "MCR-2-7-item9-pecuaria-pastagem-instalacoes"}
    if nome == "integridade_foto":
        return {"caminho_foto": str(CASO_DIR / foto["arquivo"]), "recebida_em": foto["recebida_em"],
                "gps_app": {**foto["gps_app"], "fonte": "app"}, "indice": str(tmp / "indice.jsonl")}
    if nome == "classificar_foto":
        from laudo.vision import vlm

        def falso(caminho, classes, k=3, modelo="", descarregar=True, **kw):
            return {"classe": "curral", "classe_majoritaria": "curral", "votos": {"curral": 3}, "concordancia": 1.0,
                    "k": k, "abstencao": False, "status": "ok", "motivo": "", "justificativas": [],
                    "modelo": modelo, "modelos_carregados_antes": [], "descarregado": descarregar}

        monkeypatch.setattr(vlm, "classificar", falso)
        return {"caminho_foto": str(CASO_DIR / foto["arquivo"]), "k": 3}
    if nome == "ler_documento_foto":
        from laudo.tools import leitura_documentos as ld

        # VLM falso que devolve lixo: a leitura tem de sair indeterminada, nunca com valor inventado (o
        # monkeypatch devolve o leitor original no fim do teste).
        monkeypatch.setattr(ld, "_LEITOR", lambda img, prompt, esquema, temperatura, semente: {})
        return {"caminho": str(CASO_DIR / foto["arquivo"]), "tipo_documento": "danfe", "data_referencia": hoje}
    if nome == "geofence":
        g = foto["gps_app"]
        return {"lat": g["lat"], "lon": g["lon"], "precisao_m": g["precisao_m"], "glebas_wkt": gleba}
    if nome == "contar_bovinos_video":
        if not VIDEO_CURTO.is_file():
            return None
        return {"caminho_video": str(VIDEO_CURTO), "modo": "linha", "fps_amostragem": 4.0, "modelo": "yolox_tiny",
                "dir_evidencias": str(tmp / "quadros")}
    if nome in ("conciliar_nfe", "conciliar_gta"):
        return _resolver(caso["entradas_ferramentas"][nome])
    if nome == "conciliar_alegacoes":
        bov = next(i for i in op["itens"] if i["tipo"] == "bovinos")
        return {"itens": op["itens"],
                "alegacoes": [{"grandeza": "quantidade", "valor": 29, "item_id": bov["id"],
                               "trecho": "contei 29 cabeças"}],
                "checagens": [{"ferramenta": "contar_bovinos_video", "status": "ok", "item_id": bov["id"],
                               "resultado": {"contagem": 12, "intervalo": [12, 17]}}]}
    if nome == "completar_leitura_documento":
        from laudo.docs_fiscais import leitura as L
        from laudo.docs_fiscais import residual
        from laudo.tools import leitura_documentos as ld

        man = yaml.safe_load((REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml").read_text(encoding="utf-8"))
        rot = dict(next(c for c in man["casos"] if c["id"] == "GLD-0002")["rotulos"]["danfe"][0])
        verdade = {k: rot[k] for k in ("item1.quantidade", "item1.valor_unitario", "item1.valor_total")}
        rot.update(dict.fromkeys(verdade))  # a foto não leu a linha de produtos: residual pedido à fiscal
        res = L.validar_danfe(residual.bruto_de_campos("danfe", rot), date.fromisoformat(hoje))
        leitura = ld.saida_leitura(res, [], {}, "danfe")
        return {"leitura": leitura, "respostas": {k: residual.impresso(k, v) for k, v in verdade.items()},
                "data_referencia": hoje}
    if nome in ("emitir_rascunho", "registrar_ocorrencia"):
        fis = repo.criar(Operacao.model_validate(op))
        base = {"fiscalizacao_id": fis.id}
        return base if nome == "emitir_rascunho" else {**base, "tipo": "outro", "descricao": "teste de contrato"}
    raise AssertionError(f"ferramenta sem entrada de teste: {nome} (acrescente aqui)")


NOMES = sorted(REGISTRO)


def test_registro_tem_as_ferramentas_do_regional():
    esperadas = {"planejar_metodo", "avaliar_regras", "contar_bovinos_video", "integridade_foto", "geofence",
                 "conciliar_nfe", "conciliar_gta", "emitir_rascunho", "registrar_ocorrencia"}
    assert esperadas <= set(REGISTRO), esperadas - set(REGISTRO)


@pytest.mark.parametrize("nome", NOMES)
def test_entrada_valida_devolve_envelope_com_status(nome, amb, monkeypatch):
    tmp, repo = amb
    if nome in SEM_STATUS_CONHECIDO:
        pytest.xfail(SEM_STATUS_CONHECIDO[nome])
    ent = entrada_valida(nome, tmp, repo, monkeypatch)
    if ent is None:
        pytest.skip(f"{nome}: dado local ausente nesta máquina")
    ferr = REGISTRO[nome]
    entrada = ferr.entrada.model_validate(ent)
    env = ferr.funcao(entrada)
    assert isinstance(env, Envelope), f"{nome} não devolveu Envelope"
    assert env.ferramenta == nome
    if not env.ok:
        assert env.error is not None and env.error.code in set(CodigoErro)
        assert nome in ("emitir_rascunho",), f"{nome} falhou com entrada válida: {env.error}"
        return
    assert isinstance(env.data, dict)
    if nome in NAO_CHECAGEM:
        return
    status = env.data.get("status")
    assert status is not None, f"{nome}: Envelope ok sem data.status (o condutor grava a checagem como 'ok')"
    assert str(status).lower() in ESTRITO, f"{nome}: status {status!r} fora de StatusChecagem"
    if nome == "ler_documento_foto":  # leitor devolveu lixo: nada pode sair "ok"
        assert status != "ok", env.data


def _valor_invalido(anotacao_modelo: type[BaseModel], campo: str) -> Any:
    for candidato in ({"invalido": True}, ["x", {"y": 1}], "texto-invalido", -12345):
        try:
            anotacao_modelo.model_validate({campo: candidato})
        except ValidationError as e:
            if any(err["loc"] and err["loc"][0] == campo for err in e.errors()):
                return candidato
    return None


@pytest.mark.parametrize("nome", NOMES)
def test_entrada_invalida_vira_entrada_invalida_nunca_excecao(nome, amb):
    ferr = REGISTRO[nome]
    exec_ = ExecutorFerramentas(REGISTRO, retentativas=0)
    campos = list(ferr.entrada.model_fields)
    obrig = [c for c, f in ferr.entrada.model_fields.items() if f.is_required()]
    testados = 0
    for campo in obrig[:1] + [c for c in campos if c not in obrig][:2]:
        v = _valor_invalido(ferr.entrada, campo)
        if v is None:
            continue
        env, _, _ = exec_.executar(nome, {campo: v})
        assert isinstance(env, Envelope)
        assert not env.ok and env.error.code == CodigoErro.ENTRADA_INVALIDA, (nome, campo, env.error)
        testados += 1
    if obrig:
        env, _, _ = exec_.executar(nome, {})
        assert not env.ok and env.error.code == CodigoErro.ENTRADA_INVALIDA, (nome, env.error)
        testados += 1
    assert testados, f"{nome}: nenhum caso inválido construído"


def test_ferramenta_inexistente_e_fora_do_escopo():
    env, _, _ = ExecutorFerramentas(REGISTRO).executar("assinar_laudo", {})
    assert not env.ok and env.error.code == CodigoErro.FORA_DO_ESCOPO


ARQUIVOS = {
    "integridade_foto": ("caminho_foto", "foto.jpg"),
    "classificar_foto": ("caminho_foto", "foto.jpg"),
    "contar_bovinos_video": ("caminho_video", "video.mp4"),
    "conciliar_nfe": ("caminhos", "nfe.xml"),
    "conciliar_gta": ("caminhos", "gta.json"),
    "ler_documento_foto": ("caminho", "foto.jpg"),
}


def _corromper(dest: Path) -> None:
    if dest.suffix == ".jpg":
        dest.write_bytes((CASO_DIR / "fotos" / "foto_curral_1.jpg").read_bytes()[:300])
    elif dest.suffix == ".xml":
        dest.write_text((CASO_DIR / "nfe_1.xml").read_text(encoding="utf-8")[:900], encoding="utf-8")
    elif dest.suffix == ".json":
        dest.write_text('{"numero": "GO-1", "especie": ', encoding="utf-8")
    else:
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)


@pytest.mark.parametrize("nome", sorted(ARQUIVOS))
@pytest.mark.parametrize("defeito", ["inexistente", "corrompido"])
def test_arquivo_ruim_vira_falha_padronizada(nome, defeito, amb, monkeypatch):
    if nome not in REGISTRO:
        pytest.skip(f"{nome} não registrada")
    tmp, repo = amb
    ent = entrada_valida(nome, tmp, repo, monkeypatch) or {}
    if nome == "contar_bovinos_video" and not ent:
        ent = {"caminho_video": "x.mp4", "modelo": "yolox_tiny"}
    campo, arq = ARQUIVOS[nome]
    dest = tmp / arq
    if defeito == "corrompido":
        _corromper(dest)
    ent[campo] = [str(dest)] if campo == "caminhos" else str(dest)
    ferr = REGISTRO[nome]
    env = ferr.funcao(ferr.entrada.model_validate(ent))
    assert isinstance(env, Envelope)
    if nome == "classificar_foto" and defeito == "corrompido" and env.ok:
        pytest.skip("classificar_foto com VLM falso não lê a imagem")
    assert not env.ok, f"{nome} aceitou arquivo {defeito}: {env.data}"
    assert env.error.code in CODIGOS_FALHA_ENTRADA, (nome, env.error)


def test_envelope_ok_sem_status_nao_vira_checagem_ok():
    """Sem `data.status`, o condutor não pode presumir "ok" (seria falso verificado silencioso)."""
    env = Envelope.sucesso("ferramenta_x", {"contagem": 40})
    assert est.status_de_envelope(env) != "ok"


def test_mapas_de_status_concordam():
    """`estado.status_de_envelope` e `contracts.para_status_checagem` traduzem o vocabulário do mesmo jeito."""
    from laudo.contracts import para_status_checagem

    for s in VOCABULARIO:
        env = Envelope.sucesso("x", {"status": s})
        assert est.status_de_envelope(env) == para_status_checagem(s), s


def test_timeout_vira_timeout_retryable_e_nunca_valor():
    import time as _t

    from laudo.contracts import Ferramenta

    class E(BaseModel):
        x: int = 1

    def lenta(a: E) -> Envelope:
        _t.sleep(0.5)
        return Envelope.sucesso("lenta", {"status": "ok", "contagem": 99})

    reg = {"lenta": Ferramenta(nome="lenta", descricao="", entrada=E, funcao=lenta, timeout_s=0.05)}
    env, _, _ = ExecutorFerramentas(reg, retentativas=1, dormir=lambda s: None).executar("lenta", {})
    assert not env.ok and env.error.code == CodigoErro.TIMEOUT and env.error.retryable
    assert not env.data


def test_excecao_solta_vira_erro_interno():
    from laudo.contracts import Ferramenta

    class E(BaseModel):
        x: int = 1

    def quebra(a: E) -> Envelope:
        raise RuntimeError("CPF 000.000.001-91 vazou no erro")

    reg = {"quebra": Ferramenta(nome="quebra", descricao="", entrada=E, funcao=quebra)}
    env, _, _ = ExecutorFerramentas(reg, retentativas=0).executar("quebra", {})
    assert not env.ok and env.error.code == CodigoErro.ERRO_INTERNO
    assert "000.000.001-91" not in env.error.msg  # POL-08 também na mensagem de erro


def test_registro_global_nao_foi_modificado_pelos_testes():
    assert set(REGISTRO) == set(carregar_todas())
