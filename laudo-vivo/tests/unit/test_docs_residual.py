"""Residual da leitura por foto (rodada 3): o agente pede só os campos que não validaram, com instrução específica,
e só aceita o que a fiscal leu depois de passar pelas mesmas regras determinísticas (DV, coerência, somas)."""

from datetime import date
from pathlib import Path

import pytest
import yaml

from laudo.docs_fiscais import leitura as L
from laudo.docs_fiscais import residual as R
from laudo.docs_fiscais.comum import hash_documento
from laudo.tools import leitura_documentos as LD

REPO = Path(__file__).resolve().parents[2]
HOJE = date(2026, 10, 8)


def _rotulos(cid: str, tipo: str) -> dict:
    man = yaml.safe_load((REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml").read_text(encoding="utf-8"))
    return dict(next(c for c in man["casos"] if c["id"] == cid)["rotulos"][tipo][0])


def _leitura(tipo: str, valores: dict, brutos: list | None = None) -> dict:
    """Saída de `ler_documento_foto` para uma leitura em que só os campos com valor foram lidos."""
    validar = L.validar_danfe if tipo == "danfe" else L.validar_gta
    return LD.saida_leitura(validar(R.bruto_de_campos(tipo, valores), HOJE), brutos or [], {}, tipo)


@pytest.fixture()
def danfe():
    return _rotulos("GLD-0002", "danfe")


@pytest.fixture()
def gta():
    return _rotulos("GLD-0002", "gta")


def test_leitura_completa_nao_tem_residual(danfe):
    assert _leitura("danfe", danfe)["pedido_residual"] is None


def test_pede_so_os_campos_que_nao_validaram_com_instrucao_especifica(danfe):
    lido = {**danfe, "item1.quantidade": None, "item1.valor_unitario": None, "item1.valor_total": None}
    p = R.PedidoResidual.model_validate(_leitura("danfe", lido)["pedido_residual"])
    assert p.nomes == ["item1.quantidade", "item1.valor_unitario", "item1.valor_total"]
    assert "quantidade, o valor unitário e o valor total da linha 1" in p.texto


def test_chave_pede_os_ultimos_digitos_e_monta_o_resto_dos_campos_validados(danfe):
    """MOC 4.00: cUF, AAMM, CNPJ, modelo, série e número compõem a chave; com duas leituras concordando no CNPJ,
    só os 3 últimos grupos (tpEmis, cNF e DV) são pedidos."""
    ch = danfe["chave"]
    lido = {**danfe, "chave": None}
    brutos = [{"chave": ch[:34] + "0000000000"}, {"chave": ch[:34] + "1111111111"}]  # VLM discorda no fim
    leitura = _leitura("danfe", lido, brutos)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    [pc] = p.campos
    assert pc.blocos_chave == [9, 10, 11] and pc.instrucao == "leia os 12 últimos dígitos da chave de acesso"
    fala = " ".join(ch[32:44])  # "leia os 12 últimos": a fiscal fala dígito a dígito
    respostas = R.interpretar_resposta(p, f"os 12 últimos são {fala}")
    r = R.completar(leitura, respostas, HOJE, p)
    assert r.status == "ok" and r.campos["chave"]["valor"] == ch and r.campos["chave"]["origem"] == "fiscal"
    assert r.documento["proveniencia"] == R.PROVENIENCIA


def test_chave_lida_errada_nao_e_aceita_e_a_segunda_tentativa_pede_a_chave_inteira(danfe):
    ch = danfe["chave"]
    leitura = _leitura("danfe", {**danfe, "chave": None}, [{"chave": ch[:34] + "0" * 10}, {"chave": ch[:34] + "1" * 10}])
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    errado = ch[32:43] + str((int(ch[43]) + 1) % 10)  # um dígito trocado: o DV módulo 11 pega
    r = R.completar(leitura, R.interpretar_resposta(p, errado), HOJE, p)
    assert r.status == "indeterminado" and r.campos["chave"]["status"] == "indeterminado"
    assert r.pedido is not None and r.pedido.tentativa == 2
    assert r.pedido.campos[0].n_digitos == 44 and "chave de acesso inteira" in r.pedido.texto


def test_conta_que_nao_fecha_e_recusada(danfe):
    lido = {**danfe, "item1.quantidade": None, "item1.valor_unitario": None, "item1.valor_total": None}
    leitura = _leitura("danfe", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    r = R.completar(leitura, R.interpretar_resposta(p, "4 cabeças, 14.550,00 cada, total 60.000,00"), HOJE, p)
    assert r.status == "indeterminado" and not r.aceitos_da_fiscal
    assert any("valor unitário" in x["motivo"] for x in r.recusados)
    certo = R.completar(leitura, R.interpretar_resposta(p, "quatro cabeças, 14.550,00 cada, total 58.200,00"),
                        HOJE, p)
    assert certo.status == "ok" and certo.campos["item1.quantidade"]["valor"] == 4
    assert certo.campos["item1.quantidade"]["origem"] == "fiscal"


def test_documento_pessoal_so_por_digitacao_e_sai_mascarado(danfe):
    lido = {**danfe, "destinatario_doc": None}
    leitura = _leitura("danfe", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    assert p.campos[0].modo == "digitacao" and p.campos[0].instrucao.startswith("digite")
    assert R.interpretar_resposta(p, f"o CPF é {danfe['destinatario_doc']}") == {}  # a fala não vale
    r = R.completar(leitura, R.interpretar_resposta(p, digitado={"destinatario_doc": danfe["destinatario_doc"]}),
                    HOJE, p)
    assert r.status == "ok"
    assert danfe["destinatario_doc"] not in str(r.model_dump())  # CPF em claro não sai
    assert r.documento["destinatario"]["doc_sha256"] == hash_documento(danfe["destinatario_doc"])
    # o CNPJ do emitente, aceito na leitura, volta pelo hash (a trilha só guarda máscara + hash)
    assert r.documento["emitente"]["doc_sha256"] == hash_documento(danfe["emitente_doc"])


def test_gta_linha_total_rotulada_e_municipio(gta):
    lido = {**gta, "total": None, "total_machos": None, "total_femeas": None, "total_por_extenso": None,
            "quantidades_por_faixa": None, "destino.municipio": None, "destino.ibge": None}
    leitura = _leitura("gta", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    assert {"total", "destino.municipio"} <= set(p.nomes)
    m, f, t = gta["total_machos"], gta["total_femeas"], gta["total"]
    fala = f"{t} no total, {m} machos e {f} fêmeas; o destino é {gta['destino.municipio'].title()}"
    r = R.completar(leitura, R.interpretar_resposta(p, fala), HOJE, p)
    assert r.status == "ok", r.recusados
    assert r.campos["total"]["valor"] == t and r.campos["destino.ibge"]["valor"] == gta["destino.ibge"]


def test_gta_machos_mais_femeas_diferente_do_total_e_recusado(gta):
    lido = {**gta, "total": None, "total_machos": None, "total_femeas": None, "total_por_extenso": None,
            "quantidades_por_faixa": None}
    leitura = _leitura("gta", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    r = R.completar(leitura, {"total": "9", "total_machos": "4", "total_femeas": "4"}, HOJE, p)
    assert r.status == "indeterminado" and "total" not in r.aceitos_da_fiscal


def test_terceira_tentativa_errada_encerra_com_pedido_do_xml(danfe):
    lido = {**danfe, "item1.quantidade": None, "item1.valor_unitario": None, "item1.valor_total": None}
    leitura = _leitura("danfe", lido)
    for tentativa in range(1, R.MAX_TENTATIVAS + 1):
        p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
        assert p.tentativa == tentativa
        r = R.completar(leitura, {"item1.quantidade": "4", "item1.valor_unitario": "1,00",
                                  "item1.valor_total": "9,00"}, HOJE, p)
        leitura = {**leitura, "campos": r.campos, "documento": r.documento,
                   "pedido_residual": r.pedido.model_dump() if r.pedido else None}
    assert r.pedido is None and "XML" in r.motivo


def test_ferramenta_completar_leitura_documento(danfe):
    lido = {**danfe, "item1.quantidade": None, "item1.valor_unitario": None, "item1.valor_total": None}
    leitura = _leitura("danfe", lido)
    env = LD.completar_leitura_documento(LD.EntradaCompletarLeitura(
        leitura=leitura, texto="4, 14.550,00 e 58.200,00", data_referencia=HOJE))
    assert env.ok and env.data["status"] == "ok" and env.data["proveniencia"] == R.PROVENIENCIA
    assert env.data["aceitos_rotulos"] == ["quantidade e valores da linha 1"]
    vazio = LD.completar_leitura_documento(LD.EntradaCompletarLeitura(leitura=leitura, texto="não sei"))
    assert not vazio.ok and vazio.error.code == "SEM_DADOS"


def test_codigo_do_estabelecimento_sem_dv_exige_dupla_digitacao(gta):
    lido = {**gta, "destino.codigo_estabelecimento": None}
    leitura = _leitura("gta", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    [pc] = p.campos
    assert pc.confirmar and "duas vezes" in pc.instrucao
    cod = gta["destino.codigo_estabelecimento"]
    errado = R.completar(leitura, {"destino.codigo_estabelecimento": cod,
                                   "destino.codigo_estabelecimento#2": cod[:-1] + "X"}, HOJE, p)
    assert errado.status == "indeterminado" and errado.recusados[0]["motivo"] == "as duas digitações não conferem"
    _, dig = R.resposta_do_papel(p, gta)
    certo = R.completar(leitura, R.interpretar_resposta(p, digitado=dig), HOJE, p)
    assert certo.status == "ok" and certo.campos["destino.codigo_estabelecimento"]["origem"] == "fiscal"


def test_recusa_que_nao_e_de_leitura_nao_vira_novo_pedido(danfe):
    """D14 (vendedor = tomador): o papel diz isso mesmo; pedir de novo à fiscal não resolve, só o XML."""
    lido = {**danfe, "destinatario_doc": None}
    leitura = _leitura("danfe", lido)
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    r = R.completar(leitura, {"destinatario_doc": danfe["emitente_doc"]}, HOJE, p)
    assert r.status == "indeterminado" and r.pedido is None and "XML" in r.motivo


_POR_EXTENSO = dict(zip("0123456789", ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito",
                                        "nove"], strict=True))


def test_um_ditado_entre_digitos_vira_1():
    """P2-13: "um" isolado é artigo para o normalizador, e a chave ditada perdia o dígito (11 em vez de 12)."""
    fala = "seis quatro um cinco cinco nove quatro dois nove quatro três nove"
    assert R._digitos_seguidos(R._Texto(fala), 12) == "641559429439"
    assert R._numeros_do_texto("6, 4, um, 5") == "6, 4, 1, 5"  # o ASR costuma pôr vírgulas entre algarismos
    assert R._numeros_do_texto("seis um um cinco") == "6 1 1 5"
    assert R._numeros_do_texto("são um quatro cinco") == "são 1 4 5"  # começo da sequência ditada
    assert R._numeros_do_texto("quatro três um, e o CNPJ") == "4 3 1, e o CNPJ"  # fim da sequência ditada
    # artigo continua artigo
    assert R._numeros_do_texto("uma cerca de oitocentos metros") == "uma cerca de 800 metros"
    assert R._numeros_do_texto("tenho um 40 e um 5") == "tenho um 40 e um 5"
    assert R._numeros_do_texto("nota 1 2 3 um pouco borrada") == "nota 1 2 3 um pouco borrada"


def test_chave_ditada_por_extenso_com_um_e_aceita(danfe):
    ch = danfe["chave"]
    leitura = _leitura("danfe", {**danfe, "chave": None}, [{"chave": ch[:34] + "0" * 10}, {"chave": ch[:34] + "1" * 10}])
    p = R.PedidoResidual.model_validate(leitura["pedido_residual"])
    fala = " ".join(_POR_EXTENSO[c] for c in ch[32:44])
    assert "1" in ch[32:44] and " um " in f" {fala} "  # o caso exercita o "um" ditado
    r = R.completar(leitura, R.interpretar_resposta(p, f"os 12 últimos são {fala}"), HOJE, p)
    assert r.status == "ok" and r.campos["chave"]["valor"] == ch
