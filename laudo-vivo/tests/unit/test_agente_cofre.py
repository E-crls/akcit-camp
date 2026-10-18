"""Retenção e expurgo LGPD por crypto-shredding: apagar a chave torna os brutos ilegíveis e a cadeia de hash
continua íntegra."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from laudo.agent import estado as est
from laudo.audit import cofre as cf
from laudo.audit import hashchain
from laudo.contracts import AprovacaoHumana, Fiscalizacao, Operacao


def _fis(tmp_path):
    dados = tmp_path / "dados"
    (dados / "evidencias").mkdir(parents=True)
    fis = Fiscalizacao(id="fis_lgpd_01", operacao=Operacao(ref_bacen="SINT-1", fonte="sintetico"))
    arquivos = {}
    for nome, conteudo in {
        "foto.jpg": b"\xff\xd8 foto sintetica",
        "fala.webm": b"audio sintetico " * 300,
    }.items():
        p = dados / "evidencias" / nome
        p.write_bytes(conteudo)
        arquivos[nome] = p
    est.adicionar_evidencia(fis, "foto", caminho=str(arquivos["foto.jpg"]))
    est.adicionar_evidencia(fis, "audio", caminho=str(arquivos["fala.webm"]))
    est.adicionar_evidencia(
        fis, "declaracao", conteudo=b"cheguei na fazenda", meta={"texto": "cheguei na fazenda"}
    )
    return dados, fis, arquivos


def test_cofre_cifra_e_decifra_com_chave_por_fiscalizacao(tmp_path):
    c = cf.Cofre(tmp_path / "chaves")
    blob = c.cifrar("fis_a", b"dado pessoal sintetico")
    assert blob[:4] == cf.VERSAO and b"dado pessoal" not in blob
    assert c.decifrar("fis_a", blob) == b"dado pessoal sintetico"
    assert c.decifrar_texto("fis_a", c.cifrar_texto("fis_a", "fala sintética")) == "fala sintética"
    c.chave("fis_b", criar=True)
    with pytest.raises(cf.ErroIntegridade):  # chave de outra fiscalização não abre
        c.decifrar("fis_b", blob)
    adulterado = blob[:-40] + bytes([blob[-40] ^ 1]) + blob[-39:]
    with pytest.raises(cf.ErroIntegridade):
        c.decifrar("fis_a", adulterado)
    assert c.cifrar("fis_a", b"x") != c.cifrar("fis_a", b"x")  # nonce aleatório


def test_expurgo_torna_brutos_ilegiveis_sem_quebrar_cadeia(tmp_path):
    dados, fis, arquivos = _fis(tmp_path)
    c = cf.Cofre(dados / "chaves")
    raiz_antes = hashchain.verificar_cadeia(fis.evidencias)
    assert raiz_antes.integra
    cifrados = [c.cifrar_arquivo(fis.id, p) for p in arquivos.values()]
    assert all(not p.exists() for p in arquivos.values())
    assert c.decifrar_arquivo(fis.id, cifrados[0]) == b"\xff\xd8 foto sintetica"

    reg = c.expurgar(fis.id, "pedido do titular (teste)")
    assert reg["chave_existia"] and not c.tem_chave(fis.id) and c.expurgado(fis.id)
    for p in cifrados:
        with pytest.raises(cf.ChaveExpurgada):
            c.decifrar_arquivo(fis.id, p)
    with pytest.raises(cf.ChaveExpurgada):  # não recria chave de fiscalização expurgada
        c.cifrar(fis.id, b"novo")
    depois = hashchain.verificar_cadeia(fis.evidencias)
    assert depois.integra and depois.raiz == raiz_antes.raiz  # a prova (hashes) sobrevive ao expurgo
    assert c.expurgar(fis.id, "de novo")["chave_existia"] is False  # idempotente


def test_retencao_lista_seladas_vencidas(tmp_path):
    _, fis, _ = _fis(tmp_path)
    hoje = date(2026, 10, 8)
    fis.estado_fsm = "SELADO"
    fis.aprovacoes.append(
        AprovacaoHumana(
            papel="fiscal",
            nome_ref="fiscal-sintetico",
            em=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            hash_assinado="0" * 64,
        )
    )
    aberta = Fiscalizacao(id="fis_aberta", operacao=Operacao(ref_bacen="SINT-2", fonte="sintetico"))
    assert cf.vencidas([fis, aberta], hoje, dias=90) == ["fis_lgpd_01"]
    assert cf.vencidas([fis], hoje, dias=(hoje - date(2026, 6, 1)).days) == []
    assert cf.data_do_selo(aberta) is None


def test_script_expurgo_cifra_brutos_e_mantem_estado(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    dados, fis, arquivos = _fis(tmp_path)
    est.RepositorioFiscalizacoes(dados).salvar(fis)
    spec = importlib.util.spec_from_file_location(
        "expurgo_lgpd", Path(__file__).resolve().parents[2] / "scripts" / "expurgo_lgpd.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--dados", str(dados), "cifrar", fis.id]) == 0
    assert all(not p.exists() for p in arquivos.values())
    assert mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "teste"]) == 0
    assert mod.main(["--dados", str(dados), "situacao", fis.id]) == 0
    out = capsys.readouterr().out
    assert "íntegra" in out and "ilegível (chave expurgada)" in out
    recarregada = est.RepositorioFiscalizacoes(dados).carregar(fis.id)
    assert hashchain.verificar_cadeia(recarregada.evidencias).integra


def _modulo_expurgo():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "expurgo_lgpd", Path(__file__).resolve().parents[2] / "scripts" / "expurgo_lgpd.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _selada_ha_tempo(tmp_path, externos=()):
    """Fiscalização selada em 01/01/2026, com a foto em claro e nenhuma chave (ninguém rodou `cifrar`): o caso
    de `dados_locais/auditoria/L23/repro_expurgo_sem_cifrar.py`."""
    dados = tmp_path / "dados"
    (dados / "evidencias").mkdir(parents=True)
    foto = dados / "evidencias" / "cerca.jpg"
    foto.write_bytes(b"\xff\xd8 FOTO-EM-CLARO")
    fis = Fiscalizacao(id="fis_l23", operacao=Operacao(ref_bacen="SINT-1", fonte="sintetico"))
    est.adicionar_evidencia(fis, "foto", caminho=str(foto))
    for p in externos:
        est.adicionar_evidencia(fis, "foto", caminho=str(p))
    # upload da interface que não virou evidência
    upload = dados / "evidencias" / fis.id / "a1b2c3" / "gta.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"%PDF GTA-EM-CLARO")
    fis.estado_fsm = "SELADO"
    fis.aprovacoes.append(AprovacaoHumana(papel="fiscal", nome_ref="fiscal-sintetico",
                                          em=datetime(2026, 1, 1, tzinfo=UTC), hash_assinado="0" * 64))
    est.RepositorioFiscalizacoes(dados).salvar(fis)
    conversa = dados / "fiscalizacoes" / f"{fis.id}.conversa.jsonl"
    conversa.write_text('{"fiscal": "fala"}\n', encoding="utf-8")
    return dados, fis, [foto, upload, conversa]


def _sem_claro(arquivos) -> bool:
    return all(not p.exists() for p in arquivos)


def test_l23_vencidos_cifra_os_brutos_antes_de_apagar_a_chave(tmp_path, capsys):
    dados, fis, arquivos = _selada_ha_tempo(tmp_path)
    mod = _modulo_expurgo()
    assert mod.main(["--dados", str(dados), "vencidos", "--dias", "90"]) == 0
    # sem --executar: só lista
    assert "3 bruto(s) em claro" in capsys.readouterr().out and not _sem_claro(arquivos)
    assert mod.main(["--dados", str(dados), "vencidos", "--dias", "90", "--executar"]) == 0
    assert _sem_claro(arquivos)
    c = cf.Cofre(dados / "chaves")
    assert not c.tem_chave(fis.id) and c.expurgado(fis.id)
    for p in arquivos:
        blob = p.with_name(p.name + cf.SUFIXO)
        assert b"EM-CLARO" not in blob.read_bytes() and b"fala" not in blob.read_bytes()
        with pytest.raises(cf.ChaveExpurgada):
            c.decifrar_arquivo(fis.id, blob)
    assert hashchain.verificar_cadeia(est.RepositorioFiscalizacoes(dados).carregar(fis.id).evidencias).integra


def test_l23_expurgar_sem_cifrar_antes_tambem_protege_e_apaga_o_que_chega_depois(tmp_path, capsys):
    dados, fis, arquivos = _selada_ha_tempo(tmp_path)
    mod = _modulo_expurgo()
    assert mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "pedido do titular"]) == 0
    reg = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert reg["brutos_cifrados"] == 3 and reg["brutos_em_claro"] == 0 and _sem_claro(arquivos)
    # bruto em claro que aparece depois do expurgo (cópia esquecida): sem chave para cifrar, é apagado
    tardio = dados / "evidencias" / fis.id / "z9" / "foto2.jpg"
    tardio.parent.mkdir(parents=True)
    tardio.write_bytes(b"\xff\xd8 TARDIO")
    assert mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "de novo"]) == 0
    assert not tardio.exists() and json.loads(capsys.readouterr().out)["brutos_apagados"] == 1


def test_l23_falha_e_mantem_a_chave_se_sobrar_arquivo_em_claro(tmp_path, capsys, monkeypatch):
    dados, fis, arquivos = _selada_ha_tempo(tmp_path)
    c = cf.Cofre(dados / "chaves")
    c.chave(fis.id, criar=True)
    original = cf.Cofre.cifrar_arquivo

    def trava_a_foto(self, fis_id, caminho, apagar_original=True):
        if str(caminho).endswith("cerca.jpg"):
            raise PermissionError("arquivo aberto por outro processo")
        return original(self, fis_id, caminho, apagar_original)

    monkeypatch.setattr(cf.Cofre, "cifrar_arquivo", trava_a_foto)
    mod = _modulo_expurgo()
    rc = mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "teste"])
    assert rc == mod.RC_SOBROU_EM_CLARO
    err = capsys.readouterr().err
    assert "cerca.jpg" in err and "NÃO foi apagada" in err
    assert c.tem_chave(fis.id) and not c.expurgado(fis.id) and arquivos[0].exists()
    rc = mod.main(["--dados", str(dados), "vencidos", "--dias", "90", "--executar"])
    assert rc == mod.RC_SOBROU_EM_CLARO
    assert c.tem_chave(fis.id)
    monkeypatch.setattr(cf.Cofre, "cifrar_arquivo", original)  # liberou o arquivo: agora vai
    assert mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "teste"]) == 0
    assert _sem_claro(arquivos) and not c.tem_chave(fis.id)


def test_cifra_de_arquivo_em_blocos_e_compativel_com_decifrar(tmp_path):
    import os as _os

    c = cf.Cofre(tmp_path / "chaves")
    dado = _os.urandom(2 * cf._BLOCO_ARQUIVO + 12345)  # mais de 2 blocos, fim fora do múltiplo de 32
    p = tmp_path / "video.mp4"
    p.write_bytes(dado)
    blob = c.cifrar_arquivo("fis_blocos", p)
    assert not p.exists() and blob.stat().st_size == len(dado) + 4 + 16 + 32
    assert c.decifrar_arquivo("fis_blocos", blob) == dado
    vazio = tmp_path / "vazio.bin"
    vazio.write_bytes(b"")
    assert c.decifrar_arquivo("fis_blocos", c.cifrar_arquivo("fis_blocos", vazio)) == b""


def test_l23_evidencia_fora_do_diretorio_de_dados_gera_aviso(tmp_path, capsys):
    """Arquivo de evidência fora do diretório de dados e do repositório (a CLI aceita caminho qualquer): o
    expurgo não mexe no que não é do sistema, mas não fica calado sobre a foto que continua legível."""
    externo = tmp_path / "pendrive" / "foto_externa.jpg"
    externo.parent.mkdir()
    externo.write_bytes(b"\xff\xd8 EXTERNA")
    dados, fis, arquivos = _selada_ha_tempo(tmp_path, externos=[externo])
    mod = _modulo_expurgo()
    assert mod.main(["--dados", str(dados), "expurgar", fis.id, "--motivo", "pedido do titular"]) == 0
    saida = capsys.readouterr()
    reg = json.loads(saida.out.strip().splitlines()[-1])
    assert reg["fora_dos_dados"] == 1 and reg["brutos_em_claro"] == 0 and _sem_claro(arquivos)
    assert "AVISO" in saida.err and "foto_externa.jpg" in saida.err and externo.exists()
