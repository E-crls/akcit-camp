"""Verificador independente: status por item (regra provisória e avaliar_regras) e grounding numérico."""

from datetime import date

import pytest
from pydantic import BaseModel

from laudo.agent import estado as est
from laudo.agent.ferramentas_falsas import operacao_exemplo
from laudo.agent.verificador import (
    REGRA_PROVISORIA,
    Verificador,
    extrair_numeros,
    grounding,
    requisitos_provisorios,
)
from laudo.audit import otel
from laudo.contracts import CodigoErro, Envelope, Ferramenta, Fiscalizacao


@pytest.fixture(autouse=True)
def _traces(tmp_path):
    otel.configurar(tmp_path / "traces")


def _fis() -> Fiscalizacao:
    return Fiscalizacao(operacao=operacao_exemplo(), estado_fsm="COLETA")


def _chk(fis, ferramenta, item, data, ok=True, ev_tipo="foto", ev_id=None):
    if ev_id is None:
        ev_id = est.adicionar_evidencia(
            fis, ev_tipo, conteudo=f"{ferramenta}{len(fis.evidencias)}".encode(), meta={"item_id": item}
        ).id
    env = Envelope.sucesso(ferramenta, data) if ok else Envelope.falha(ferramenta, CodigoErro.TIMEOUT, "t")
    return est.registrar_checagem(
        fis, ferramenta, f"h{len(fis.checagens)}", env, item_id=item, evidencias=[ev_id]
    )


def test_requisitos_provisorios_por_tipo_de_item():
    reqs = requisitos_provisorios(operacao_exemplo().itens)
    assert [r["campo"] for r in reqs] == [
        "item:bov1:quantidade",
        "item:bov1:nfe",
        "item:bov1:gta",
        "item:cerca1:existencia",
    ]
    assert all(r["regra_id"] == REGRA_PROVISORIA for r in reqs)


def test_sem_checagem_fica_pendente():
    res = Verificador({}).recalcular(_fis())
    assert res.provisoria and all(c.status == "pendente" for c in res.campos.values())


@pytest.mark.parametrize(
    "dados,status",
    [
        ({"status": "ok", "contagem": 40, "intervalo": [39, 41]}, "verificado"),
        ({"status": "ok", "contagem": 32, "intervalo": [31, 33]}, "divergente"),
        ({"status": "indeterminado", "motivo": "oclusão"}, "abstencao"),
    ],
)
def test_quantidade_pela_contagem(dados, status):
    fis = _fis()
    _chk(fis, "contar_bovinos_video", "bov1", dados, ev_tipo="video")
    c = Verificador({}).recalcular(fis).campos["item:bov1:quantidade"]
    assert c.status == status and c.checagens


def test_quantidade_soma_lotes_distintos_e_ultima_por_lote():
    fis = _fis()
    _chk(
        fis,
        "contar_bovinos_video",
        "bov1",
        {"status": "ok", "contagem": 32, "intervalo": [31, 33], "lote": "curral"},
        ev_tipo="video",
    )
    _chk(
        fis, "contar_bovinos_video", "bov1", {"status": "ok", "contagem": 8, "lote": "retiro"}, ev_tipo="video"
    )
    c = Verificador({}).recalcular(fis).campos["item:bov1:quantidade"]
    assert c.status == "verificado" and c.valor == 40 and len(c.evidencias) == 2
    _chk(
        fis, "contar_bovinos_video", "bov1", {"status": "ok", "contagem": 5, "lote": "retiro"}, ev_tipo="video"
    )  # refilmagem
    c = Verificador({}).recalcular(fis).campos["item:bov1:quantidade"]
    assert c.status == "divergente" and c.valor == 37


def test_erro_de_ferramenta_vira_pendente_nunca_valor():
    fis = _fis()
    _chk(fis, "conciliar_nfe", "bov1", {}, ok=False, ev_tipo="nfe_xml")
    c = Verificador({}).recalcular(fis).campos["item:bov1:nfe"]
    assert c.status == "pendente" and c.valor is None


def test_existencia_foto_e_geofence():
    fis = _fis()
    ev = est.adicionar_evidencia(fis, "foto", conteudo=b"f1", meta={"item_id": "cerca1"}).id
    _chk(fis, "integridade_foto", "cerca1", {"status": "ok"}, ev_id=ev)
    v = Verificador({})
    assert v.recalcular(fis).campos["item:cerca1:existencia"].status == "pendente"  # falta geofence
    _chk(fis, "geofence", "cerca1", {"status": "fora"}, ev_id=ev)
    assert v.recalcular(fis).campos["item:cerca1:existencia"].status == "divergente"
    ev2 = est.adicionar_evidencia(fis, "foto", conteudo=b"f2", meta={"item_id": "cerca1"}).id
    _chk(fis, "integridade_foto", "cerca1", {"status": "ok"}, ev_id=ev2)
    _chk(fis, "geofence", "cerca1", {"status": "indeterminado"}, ev_id=ev2)
    assert v.recalcular(fis).campos["item:cerca1:existencia"].status == "divergente"
    ev3 = est.adicionar_evidencia(fis, "foto", conteudo=b"f3", meta={"item_id": "cerca1"}).id
    _chk(fis, "integridade_foto", "cerca1", {"status": "ok"}, ev_id=ev3)
    _chk(fis, "geofence", "cerca1", {"status": "dentro"}, ev_id=ev3)
    assert v.recalcular(fis).campos["item:cerca1:existencia"].status == "verificado"
    ev4 = est.adicionar_evidencia(fis, "foto", conteudo=b"f4", meta={"item_id": "cerca1"}).id
    _chk(fis, "integridade_foto", "cerca1", {"status": "suspeita"}, ev_id=ev4)  # foto de tela: domina
    assert v.recalcular(fis).campos["item:cerca1:existencia"].status == "divergente"


def test_justificativa_humana_sobrevive_ao_recalculo():
    fis = _fis()
    _chk(fis, "contar_bovinos_video", "bov1", {"contagem": 32}, ev_tipo="video")
    v = Verificador({})
    v.aplicar(fis, v.recalcular(fis))
    fis.campos["item:bov1:quantidade"].justificativa_humana = "oito vendidos antes da visita"
    v.aplicar(fis, v.recalcular(fis))
    assert fis.campos["item:bov1:quantidade"].justificativa_humana == "oito vendidos antes da visita"


class _EntradaRegras(BaseModel):
    fiscalizacao: dict


def _reg_regras(funcao) -> dict:
    return {
        "avaliar_regras": Ferramenta(
            nome="avaliar_regras", descricao="x", entrada=_EntradaRegras, funcao=funcao
        )
    }


def test_usa_avaliar_regras_quando_existe():
    def regras(a: _EntradaRegras) -> Envelope:
        assert a.fiscalizacao["operacao"]["ref_bacen"]
        return Envelope.sucesso(
            "avaliar_regras",
            {
                "campos": [
                    {"campo": "item:bov1:quantidade", "status": "verificado", "regra_id": "MCR-2-7-teste"}
                ],
                "bloqueios": [{"regra_id": "MCR-2-7-x", "falta": "algo"}],
            },
            fonte_versao="rulebook@9",
        )

    res = Verificador(_reg_regras(regras)).recalcular(_fis())
    assert not res.provisoria and res.fonte == "rulebook@9"
    assert res.campos["item:bov1:quantidade"].regra_id == "MCR-2-7-teste" and res.bloqueios


def test_avaliar_regras_fora_do_contrato_cai_na_regra_provisoria():
    res = Verificador(
        _reg_regras(lambda a: Envelope.sucesso("avaliar_regras", {"campos": [{"x": 1}]}))
    ).recalcular(_fis())
    assert res.provisoria and "fora do contrato" in res.aviso


# Grounding ---------------------------------------------------------------------
def test_extrair_numeros_pt_br_e_ignora_ids_e_normas():
    nums, datas, horas = extrair_numeros(
        "Contei 1.234,5 kg, 12,5% e R$ 160.000,00 em 08/10/2026 às 10:12; ver chk_ab12cd34ef, POL-02, "
        "MCR-2-7-item16, Res. CMN 5.267/2025, Sentinel-2, qwen3.5:4b e hash 0123456789abcdef0123."
    )
    assert [n.valor for n in nums] == [1234.5, 12.5, 160000.0]
    assert nums[1].percentual and datas == [date(2026, 10, 8)] and horas == ["10:12"]


def test_grounding_com_e_sem_lastro():
    fis = _fis()
    _chk(fis, "contar_bovinos_video", "bov1", {"contagem": 32.4, "intervalo": [31, 33]}, ev_tipo="video")
    assert grounding("A contagem deu 32 de 40 financiadas (31 a 33).", fis).ok
    g = grounding("Contei 55 animais em 03/02/2026.", fis)
    assert not g.ok and "55" in g.sem_lastro and "2026-02-03" in g.sem_lastro
    assert not grounding("faltam 3 animais", fis).ok  # número pequeno precisa bater exato
    assert grounding("o contrato é de R$ 160.000,00, de 15/07/2026", fis).ok
    assert grounding("faltam 3 animais", fis, extras=["3"]).ok


# POL-05 × identificadores (rodada 3: o filtro saiu do harness da avaliação e foi para o código) ---------------
@pytest.mark.parametrize(
    "texto",
    [
        "NF-e 522607…27121456: DigestValue não confere.",  # chave mascarada (nfe.chave_mascarada)
        "Emitente 12.345.678/****-** e destinatário ***.456.789-** conferem.",  # documentos mascarados
        "CPF [CPF] e CNPJ [CNPJ] mascarados pelo POL-08.",
        "Chave 5226 0812 3456 7800 0199 5500 1000 0040 5110 0000 1234 lida do DANFE.",  # 11 blocos de 4
        "Chave 52260812345678000199550010000040511000001234 validada.",  # 44 dígitos seguidos
        "DANFE nº 000.004.051, série 1.",  # número impresso com zeros à esquerda
    ],
    ids=["chave_mascarada", "doc_mascarado", "marcador_pol08", "chave_em_blocos", "chave_44", "numero_nfe"],
)
def test_pol05_identificador_nao_e_numero_a_aterrar(texto):
    """Identificador de documento é referência, não número que a fala afirma: não pode derrubar a fala."""
    from laudo.agent.verificador import remover_identificadores

    fis = _fis()
    nums, _, _ = extrair_numeros(remover_identificadores(texto))
    assert all(n.valor <= 1 for n in nums), nums  # sobra no máximo a "série 1"
    g = grounding(texto, fis, extras=["1"])
    assert g.ok, g.sem_lastro


def test_pol05_quantidade_ao_lado_de_identificador_continua_conferida():
    fis = _fis()
    _chk(fis, "contar_bovinos_video", "bov1", {"contagem": 32, "intervalo": [31, 33]}, ev_tipo="video")
    assert grounding("NF-e 522607…27121456: contagem 32.", fis).ok
    g = grounding("NF-e 522607…27121456: contagem 57.", fis)
    assert not g.ok and g.sem_lastro == ["57"]
    # valores em reais e milhar continuam números (não são identificadores)
    nums, _, _ = extrair_numeros("R$ 1.234.567,89 e 1.200 cabeças")
    assert [n.valor for n in nums] == [1234567.89, 1200.0]
