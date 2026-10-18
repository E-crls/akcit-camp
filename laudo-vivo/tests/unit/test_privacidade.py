"""LGPD: sal por instalação, hash com sal de CPF/CNPJ e da chave de acesso, chave só mascarada no estado, no
trace e no laudo, e a chave inteira cifrada no cofre (consulta futura; some com o expurgo)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pytest

from laudo import privacidade as P
from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.pii import mascarar
from laudo.audit import cofre as cf
from laudo.audit import otel
from laudo.contracts import Envelope, Fiscalizacao, Operacao
from laudo.docs_fiscais.comum import hash_documento, hash_documento_publico
from laudo.docs_fiscais.sintetico import cpf_sintetico
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

RAIZ = Path(__file__).resolve().parents[2]
CASO = RAIZ / "eval" / "golden" / "demo" / "DEMO-0001"


def _chave() -> str:
    """Chave de 44 posições com DV válido e CPF sintético do emitente (montada em tempo de execução)."""
    from laudo.docs_fiscais.comum import montar_chave

    return montar_chave("52", "2604", cpf_sintetico(3), "55", 1, 8664, 1, "55942943")


@pytest.fixture()
def config_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_CONFIG_DIR", str(tmp_path / "cfg"))
    P.limpar_cache()
    yield tmp_path / "cfg"
    P.limpar_cache()


def test_sal_criado_na_primeira_execucao_fora_do_repositorio(config_isolada):
    assert not (config_isolada / P.ARQUIVO).exists()
    s1 = P.sal()
    cfg = json.loads((config_isolada / P.ARQUIVO).read_text(encoding="utf-8"))
    assert len(s1) == 32 and cfg["sal"] == s1.hex() and cfg["versao"] == 1
    P.limpar_cache()
    assert P.sal() == s1  # estável entre execuções
    assert RAIZ not in config_isolada.parents  # nunca dentro do repositório
    assert re.fullmatch(r"[0-9a-f]{12}", P.id_instalacao())


def test_hash_de_documento_depende_do_sal_da_instalacao(config_isolada, monkeypatch, tmp_path):
    cpf = cpf_sintetico(5)
    publico = hash_documento_publico(cpf)
    # o formato público é o v1 de sempre (o golden set guarda esse; nada muda nos casos)
    assert publico == hashlib.sha256(f"laudo-vivo/doc/v1::{cpf}".encode()).hexdigest()
    h1 = hash_documento(cpf)
    assert h1 != publico and h1 == hash_documento(f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}")
    assert P.hash_referencia(f"sha256:{publico}") == h1 == P.hash_referencia(publico)
    assert P.hash_referencia(f"hmac:{h1}") == h1 and P.hash_referencia("anon") is None
    monkeypatch.setenv("LAUDO_CONFIG_DIR", str(tmp_path / "outra"))
    P.limpar_cache()
    assert hash_documento(cpf) != h1  # outra instalação, outro hash: não se compara entre instalações


def test_mascara_da_chave_nao_mostra_o_documento_do_emitente():
    ch = _chave()
    doc = ch[6:20]
    m = P.mascarar_chave(ch)
    assert m == f"{ch[:6]}…{ch[-8:]}" and doc[3:] not in m
    agrupada = " ".join(ch[i:i + 4] for i in range(0, 44, 4))
    lida_errada = ch[:10] + ch[12:]  # 42 posições: o VLM pulou dois dígitos
    for texto in (agrupada, f"(lido: {lida_errada})", f"#NFe{ch}"):
        assert doc[3:] not in P.mascarar_texto(texto), texto
        assert doc[3:] not in mascarar(texto), texto  # POL-08: trace, log e LLM externo
    # números comuns não são tocados
    t = "contagem 12 (12 a 17); protocolo 152260000012345; 2026-10-08T10:12:05; NF-e 522604…59429439"
    assert P.mascarar_texto(t) == t


def test_proteger_e_restaurar_resultado_com_o_cofre(tmp_path):
    ch = _chave()
    cofre = cf.Cofre(tmp_path / "chaves")
    data = {"tipo_documento": "danfe", "documento": {"chave": ch, "numero": 8664},
            "campos": {"chave": {"valor": ch, "status": "ok", "motivo": "DV módulo 11 válido"}},
            "leituras_brutas": [{"chave": " ".join(ch[i:i + 4] for i in range(0, 44, 4))}],
            "pedido_residual": {"campos": [{"base_chave": ch[:32] + "?" * 12}]},
            "concordancia": {"chave": "2/3"}, "notas": [{"chave": ch, "doc_sha256": "ab" * 32}],
            "gtas": [{"nfe_chaves": [ch]}], "motivo": f"Não validei: chave (lido: {ch[:40]})"}
    prot = P.proteger_resultado(data, "fis_teste_priv", cofre)
    texto = json.dumps(prot, ensure_ascii=False)
    assert ch[6:20] not in texto and not re.search(r"\d{20,}", texto)
    assert prot["documento"]["chave"] == P.mascarar_chave(ch)
    assert prot["documento"]["chave_hash"] == P.hash_chave(ch) and prot["gtas"][0]["nfe_chaves_hash"] == [
        P.hash_chave(ch)]
    assert prot["concordancia"]["chave"] == "2/3" and prot["notas"][0]["doc_sha256"] == "ab" * 32
    assert prot["_cofre"]["token"].startswith("lvc1:")
    # de volta em memória para a próxima ferramenta: igual ao original (mais os hashes)
    volta = P.restaurar_resultado(prot, "fis_teste_priv", cofre)
    assert "_cofre" not in volta and volta["documento"]["chave"] == ch
    assert volta["pedido_residual"] == data["pedido_residual"]
    assert volta["leituras_brutas"][0]["chave"] == data["leituras_brutas"][0]["chave"]
    assert volta["motivo"] == data["motivo"] and volta["gtas"][0]["nfe_chaves"] == [ch]
    assert P.chaves_para_consulta([prot], "fis_teste_priv", cofre) == [ch]
    # expurgo: a chave da fiscalização some e o que estava cifrado não volta mais (crypto-shredding)
    cofre.expurgar("fis_teste_priv", "teste")
    assert P.restaurar_resultado(prot, "fis_teste_priv", cofre)["documento"]["chave"] == P.mascarar_chave(ch)
    assert P.chaves_para_consulta([prot], "fis_teste_priv", cofre) == []


def test_registrar_checagem_grava_so_a_mascara(tmp_path):
    ch = _chave()
    fis = Fiscalizacao(operacao=Operacao(ref_bacen="TESTE-PRIV-1"))
    env = Envelope.sucesso("conciliar_nfe", {"status": "ok", "notas": [{"chave": ch}]})
    chk = est.registrar_checagem(fis, "conciliar_nfe", "h", env, cofre=cf.Cofre(tmp_path / "chaves"))
    assert chk.resultado["notas"][0]["chave"] == P.mascarar_chave(ch) and "_cofre" in chk.resultado
    sem_cofre = est.registrar_checagem(fis, "conciliar_nfe", "h2", env)
    assert sem_cofre.resultado["notas"][0]["chave"] == P.mascarar_chave(ch) and "_cofre" not in sem_cofre.resultado


@pytest.mark.skipif(not (CASO / "caso.yaml").exists(), reason="DEMO-0001 não montado")
def test_estado_trace_e_laudo_da_fiscalizacao_sem_chave_nem_hash_publico(tmp_path):
    """Fiscalização de verdade (condutor, ferramentas reais, sem LLM): NF-e XML e GTA do DEMO-0001. A chave de
    acesso não aparece inteira em nenhum arquivo da fiscalização, nem o hash público do CPF do tomador."""
    import yaml

    from laudo.agent import roteiro_demo as demo

    caso = demo.carregar_caso_real()
    dados = yaml.safe_load((CASO / "caso.yaml").read_text(encoding="utf-8"))
    ch = dados["documentos"]["nfe"][0]["chave"]
    publico = dados["operacao"]["tomador_ref"].removeprefix("sha256:")
    otel.configurar(tmp_path / "traces")
    try:
        cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path), registro=dict(carregar_todas()),
                        hoje=caso.data_referencia)
        fis = cond.abrir(caso.operacao, data_referencia=caso.data_referencia, data_fiscalizacao=date(2026, 10, 8))
        assert fis.operacao.tomador_ref == f"hmac:{P.hash_referencia(publico)}"
        for nome in ("nfe_1.xml", "gta_1.json"):
            cond.turno(fis.id, Evento(texto="", evidencia=caso.evidencias[nome].model_copy(deep=True)))
        final = cond.repo.carregar(fis.id)
        nfe = next(c for c in final.checagens if c.ferramenta == "conciliar_nfe")
        assert nfe.status == "ok"  # a parte "comprador = tomador" fecha pelo hash com sal
        assert nfe.resultado["notas"][0]["chave_hash"] == P.hash_chave(ch)
        # o laudo (JSON e HTML) como a emissão monta: aqui sem passar pela política (o caso tem pendências)
        laudo = ferr_laudo.montar_laudo(final, cond.verificador.recalcular(final), politica=cond.politica)
        (tmp_path / "laudo.json").write_text(json.dumps(laudo, ensure_ascii=False, default=str), encoding="utf-8")
        (tmp_path / "laudo.html").write_text(ferr_laudo.renderizar_html(laudo), encoding="utf-8")
        arquivos = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl", ".html")]
        assert any("traces" in p.parts for p in arquivos) and any("fiscalizacoes" in p.parts for p in arquivos)
        for p in arquivos:
            t = p.read_text(encoding="utf-8")
            assert ch not in t and ch[6:20] not in t, p
            assert publico not in t, p
    finally:
        ferr_laudo.configurar(None, None)


def test_nova_evidencia_do_tipo_documento_existe():
    # o tipo usado pela foto do DANFE continua aceito pelo condutor (sanidade do contrato usado acima)
    assert NovaEvidencia(tipo="documento", caminho="x.jpg").tipo == "documento"
