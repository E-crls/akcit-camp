"""Perfil "custeio de aquisição e manutenção de animais" (mcr-2-7 0.4.0; revisão 0.5.0): seleção, campos,
plano, pendência não bloqueante, prazo de contestação e casos de dev.

Tabelas de casos; cada linha cita a regra. Dados sintéticos (TESTE-SINTETICO, anon-teste).
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from laudo.contracts import Checagem, Evidencia, Fiscalizacao, ItemFinanciado, Operacao
from laudo.rulebooks import carregar
from laudo.tools import regras as R

REPO = Path(__file__).resolve().parents[2]
REF = date(2026, 10, 8)
DIA = datetime(2026, 9, 20, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
PERFIL = "OP-perfil-custeio-animais"


def _item(
    descricao: str = "Custeio de aquisição de 80 garrotes para recria", qtd: float = 80, tipo: str = "bovinos"
) -> ItemFinanciado:
    return ItemFinanciado(
        id="bov1", tipo=tipo, descricao=descricao, quantidade=qtd, categoria_animal="garrote"
    )


def _op(
    *itens: ItemFinanciado,
    finalidade: str | None = "custeio",
    area_inf: float | None = 50.0,
    area_fin: float | None = 40.0,
) -> Operacao:
    return Operacao(
        ref_bacen="TESTE-SINTETICO-0101",
        tomador_ref="anon-teste",
        finalidade=finalidade,
        data_contratacao=date(2026, 7, 1),
        area_financiada_ha=area_fin,
        area_informada_ha=area_inf,
        itens=list(itens) or [_item()],
        fonte="sintetico",
    )


def _chk(ferramenta: str, st: str, item_id: str | None = "bov1", ev: Evidencia | None = None, **resultado):
    return Checagem(
        ferramenta=ferramenta,
        entrada_hash="teste",
        status=st,
        item_id=item_id,
        resultado=resultado,
        evidencias=[ev.id] if ev else [],
    )


def _verificadas() -> tuple[list[Checagem], list[Evidencia]]:
    v = Evidencia(tipo="video", sha256="0" * 64, capturada_em=DIA)
    return [
        _chk("contar_bovinos_video", "ok", ev=v, contagem=80, intervalo=[79, 81]),
        _chk("conciliar_nfe", "ok"),
        _chk("conciliar_gta", "ok"),
    ], [v]


def _avaliar(
    op: Operacao, checagens=(), evidencias=(), metodo: str | None = "presencial"
) -> R.ResultadoAvaliacao:
    fis = Fiscalizacao(operacao=op, metodo=metodo, checagens=list(checagens), evidencias=list(evidencias))
    return R.avaliar(fis, R.ContextoRegras(), REF)


# ============================================================ seleção do perfil
CASOS_PERFIL = [
    # (regra, finalidade, tipo do item, fluxo esperado, perfil esperado)
    (
        "OP-perfil-custeio-animais: custeio + bovinos → custeio_animais",
        "custeio",
        "bovinos",
        "custeio_animais",
        PERFIL,
    ),
    (
        "OP-perfil-custeio-animais: investimento + bovinos → fluxo bovinos de antes",
        "investimento",
        "bovinos",
        "bovinos",
        None,
    ),
    (
        "OP-perfil-custeio-animais: finalidade desconhecida não escolhe o perfil (indeterminado)",
        None,
        "bovinos",
        "bovinos",
        None,
    ),
    (
        "OP-perfil-custeio-animais: comercialização + bovinos → fluxo bovinos",
        "comercializacao",
        "bovinos",
        "bovinos",
        None,
    ),
    (
        "OP-perfil-custeio-animais: custeio + cerca → benfeitoria (perfil só para bovinos)",
        "custeio",
        "cerca",
        "benfeitoria",
        None,
    ),
]


@pytest.mark.parametrize("regra,finalidade,tipo,fluxo,perfil", CASOS_PERFIL, ids=[c[0] for c in CASOS_PERFIL])
def test_selecao_do_perfil(regra, finalidade, tipo, fluxo, perfil):
    rb = carregar("mcr-2-7")
    it = _item(tipo=tipo)
    nome, _, r = R.fluxo_do_item(rb, it, _op(it, finalidade=finalidade))
    assert nome == fluxo and (r.id if r else None) == perfil


def test_fluxo_reservado_nunca_e_escolhido_pelo_tipo_sozinho():
    rb = carregar("mcr-2-7")
    assert rb.fluxo_do_tipo("bovinos")[0] == "bovinos"  # o método do esquema continua devolvendo o padrão
    assert "custeio_animais" in rb.fluxos and rb.regra(PERFIL).efeito["fluxo"] == "custeio_animais"


@pytest.mark.parametrize(
    "descricao,esperado",
    [
        ("Custeio de aquisição de 80 garrotes para recria", True),
        ("Compra de 30 bezerros para engorda", True),
        ("Custeio de manutenção de 150 bois em engorda (sal mineral, ração e vacinas)", False),
        ("Bovinos de corte - recria", None),  # não dá para dizer: o campo de NF-e/GTA é mantido
    ],
)
def test_item_de_aquisicao_ou_so_manutencao(descricao, esperado):
    assert R.eh_aquisicao(_item(descricao)) is esperado


# ============================================================ campos do perfil (avaliar_regras)
def test_mesmas_checagens_do_investimento_mais_lotacao_e_metodo():
    chs, evs = _verificadas()
    res = _avaliar(_op(), chs, evs)
    campos = {k for k in res.campos if k.startswith("item:bov1:")}
    assert campos == {
        f"item:bov1:{c}" for c in ("quantidade", "comprovante_nfe", "gta", "lotacao", "metodo_if")
    }
    assert {res.campos[c].status for c in campos} == {"verificado"}
    assert res.campos["item:bov1"].status == "verificado"
    assert not [b for b in res.bloqueios if (b.campo or "").startswith("item:")]
    # mesmas regras do investimento para contagem, NF-e e GTA
    assert res.campos["item:bov1:quantidade"].regra_id == "OP-bovinos-contagem-tolerancia"
    assert res.campos["item:bov1:comprovante_nfe"].regra_id == "MCR-2-5-item10-comprovante-aquisicao"
    assert res.campos["item:bov1:gta"].regra_id == "OP-bovinos-gta"


def test_investimento_nao_muda():
    """Operação de investimento: os mesmos 3 campos de antes da 0.4.0, sem lotação nem método do perfil."""
    chs, evs = _verificadas()
    it = ItemFinanciado(id="bov1", tipo="bovinos", descricao="Aquisição de 80 novilhas", quantidade=80)
    res = _avaliar(_op(it, finalidade="investimento"), chs, evs)
    assert {k for k in res.campos if k.startswith("item:bov1:")} == {
        "item:bov1:quantidade",
        "item:bov1:comprovante_nfe",
        "item:bov1:gta",
    }


METODO = "MCR-2-7-item1-metodo-documentado-if"
CASOS_CUSTEIO = [
    # (regra, item, área informada, área financiada, checagens extras, campo → status esperado)
    (
        "OP-custeio-lotacao: 80 cab em 50 ha (1,6) → verificado",
        _item(),
        50.0,
        40.0,
        [],
        {"lotacao": "verificado", "item": "verificado"},
    ),
    (
        "OP-custeio-lotacao: 80 cab em 20 ha (4) → pendente que não bloqueia nem muda o item",
        _item(),
        20.0,
        40.0,
        [],
        {"lotacao": "pendente", "item": "verificado"},
    ),
    (
        "OP-custeio-lotacao: no limite (81 cab em 27 ha = 3,0) ainda verifica",
        _item(qtd=81),
        27.0,
        None,
        [],
        {"lotacao": "verificado"},
    ),
    (
        "OP-custeio-lotacao: sem área informada usa a financiada (com aviso)",
        _item(),
        None,
        10.0,
        [],
        {"lotacao": "pendente"},
    ),
    (
        "OP-custeio-lotacao: sem área nenhuma → pendente (indeterminado), não bloqueia",
        _item(),
        None,
        None,
        [],
        {"lotacao": "pendente", "item": "verificado"},
    ),
    (
        "OP-custeio-lotacao: checar_lotacao ok prevalece sobre a conta da operação",
        _item(),
        5.0,
        None,
        [
            _chk(
                "checar_lotacao", "ok", item_id=None, lotacao_cab_ha=1.2, cabecas=80, area_ha=66.7, classe="x"
            )
        ],
        {"lotacao": "verificado"},
    ),
    (
        "OP-custeio-lotacao: confinamento → lotação por área não se aplica (verificado)",
        _item(),
        5.0,
        None,
        [
            _chk(
                "checar_lotacao", "ok", item_id=None, lotacao_cab_ha=16.0, classe="nao_aplicavel_confinamento"
            )
        ],
        {"lotacao": "verificado"},
    ),
    (
        "OP-perfil-custeio-animais: item só de manutenção dispensa NF-e e GTA de compra",
        _item("Custeio de manutenção de 80 garrotes (sal mineral e vacinas)"),
        50.0,
        None,
        [],
        {"lotacao": "verificado", "comprovante_nfe": None, "gta": None, "item": "verificado"},
    ),
    (
        "MCR-2-5-item10 + OP-bovinos-gta: aquisição sem NF-e e GTA → pendentes e bloqueantes",
        _item(),
        50.0,
        None,
        "sem_documentos",
        {"comprovante_nfe": "pendente", "gta": "pendente", "item": "pendente"},
    ),
    (
        "OP-bovinos-contagem-tolerancia: contagem abaixo → divergente; lotação não esconde o achado",
        _item(),
        20.0,
        None,
        "contagem_baixa",
        {"quantidade": "divergente", "lotacao": "pendente", "item": "divergente"},
    ),
]


@pytest.mark.parametrize(
    "regra,item,area_inf,area_fin,extras,esperado", CASOS_CUSTEIO, ids=[c[0] for c in CASOS_CUSTEIO]
)
def test_campos_do_perfil_custeio(regra, item, area_inf, area_fin, extras, esperado):
    chs, evs = _verificadas()
    if extras == "sem_documentos":
        chs = chs[:1]
    elif extras == "contagem_baixa":
        chs = [_chk("contar_bovinos_video", "ok", ev=evs[0], contagem=50, intervalo=[48, 52])] + chs[1:]
    else:
        chs = chs + list(extras)
    res = _avaliar(_op(item, area_inf=area_inf, area_fin=area_fin), chs, evs)
    for campo, st in esperado.items():
        nome = "item:bov1" if campo == "item" else f"item:bov1:{campo}"
        if st is None:
            assert nome not in res.campos and any(n["campo"] == nome for n in res.nao_aplicaveis)
            continue
        assert res.campos[nome].status == st, (nome, res.campos[nome].motivo)
    bloqueados = {b.campo for b in res.bloqueios}
    assert "item:bov1:lotacao" not in bloqueados and "item:bov1:metodo_if" not in bloqueados
    if esperado.get("lotacao") == "pendente":
        assert (
            "não divergência" in res.campos["item:bov1:lotacao"].motivo
            or "indeterminada" in res.campos["item:bov1:lotacao"].motivo
        )
        # o item não se diz "todo verificado" com o sinal pendente (mesmo sem bloquear)
        motivo_item = res.campos["item:bov1"].motivo
        assert "todas as exigências verificadas" not in motivo_item
        assert "ponto de atenção não bloqueante: lotacao (pendente)" in motivo_item


def test_item_so_de_manutencao_registra_so_os_componentes_que_se_aplicam():
    """MCR-2-7-item1-metodo-documentado-if: item sem aquisição não lista NF-e e GTA no método do laudo."""
    _, evs = _verificadas()
    chs = [_chk("contar_bovinos_video", "ok", ev=evs[0], contagem=150, intervalo=[149, 152])]
    it = _item("Custeio de manutenção de 150 bois em engorda (sal mineral, ração e vacinas)", qtd=150)
    res = _avaliar(_op(it, area_inf=30.0), chs, evs)
    c = res.campos["item:bov1:metodo_if"]
    assert c.status == "verificado" and set(c.valor["componentes"]) == {"contagem", "lotacao"}
    assert c.valor["nao_aplicaveis"] == ["nfe", "gta"]
    assert "com contagem, lotacao (nfe, gta não se aplicam ao item" in c.motivo
    item = res.campos["item:bov1"]
    assert item.status == "verificado"
    assert item.motivo == (
        "exigências bloqueantes verificadas; ponto de atenção não bloqueante: lotacao (pendente)"
    )


def test_item_de_investimento_mantem_o_motivo_de_antes():
    """Fluxo sem regra não bloqueante (investimento): o motivo do item é o de antes da 0.4.0."""
    chs, evs = _verificadas()
    it = ItemFinanciado(id="bov1", tipo="bovinos", descricao="Aquisição de 80 novilhas", quantidade=80)
    res = _avaliar(_op(it, finalidade="investimento"), chs, evs)
    assert res.campos["item:bov1"].motivo == "todas as exigências verificadas"


def test_lotacao_com_area_financiada_avisa():
    chs, evs = _verificadas()
    res = _avaliar(_op(area_inf=None, area_fin=10.0), chs, evs)
    c = res.campos["item:bov1:lotacao"]
    assert c.valor["fonte"] == "operacao.area_financiada_ha" and "não é o pasto" in c.motivo
    assert c.valor["lotacao_cab_ha"] == 8.0 and c.valor["limite_cab_ha"] == 3.0


def test_metodo_documentado_pela_if_com_citacao_literal():
    chs, evs = _verificadas()
    res = _avaliar(_op(), chs, evs)
    c = res.campos["item:bov1:metodo_if"]
    rb = carregar("mcr-2-7")
    assert c.status == "verificado" and c.regra_id == METODO
    assert c.valor["perfil"] == PERFIL and c.valor["rulebook"] == rb.fonte_versao == "rulebook-mcr-2-7@0.5.0"
    assert c.valor["rulebook_sha256"] == rb.sha256 and set(c.valor["componentes"]) == {
        "contagem",
        "nfe",
        "gta",
        "lotacao",
    }
    assert c.valor["citacao"].startswith("a aplicação de critérios e métodos consistentes, verificáveis")
    assert rb.regra(METODO).item == "MCR 2-7-1-c" and rb.regra(METODO).origem == "norma"
    sem_metodo = _avaliar(_op(), chs, evs, metodo=None).campos["item:bov1:metodo_if"]
    assert sem_metodo.status == "pendente"


def test_planejar_perfil_custeio():
    d = R.planejar(_op(), R.ContextoRegras(prioridade_verificacao="media"), REF)
    m = d["metodos_por_item"][0]
    assert m["fluxo"] == "custeio_animais" and m["metodo"] == "autofiscalizacao_assistida"
    assert m["perfil"]["regra_id"] == PERFIL and set(m["perfil"]["metodo_if"]) >= {
        "contagem",
        "nfe",
        "gta",
        "lotacao",
    }
    req = {r["id"]: r for r in d["requisitos"]}
    assert {
        "item:bov1:quantidade",
        "item:bov1:comprovante_nfe",
        "item:bov1:gta",
        "item:bov1:lotacao",
        "item:bov1:metodo_if",
    } <= set(req)
    assert (
        req["item:bov1:lotacao"]["obrigatorio"] is False
        and req["item:bov1:metodo_if"]["obrigatorio"] is False
    )
    assert "item:bov1:MCR-3-3-item10-marcacao-animais" not in req  # marcação é do crédito de investimento


def test_planejar_investimento_inalterado():
    it = ItemFinanciado(id="bov1", tipo="bovinos", descricao="Aquisição de 80 novilhas", quantidade=80)
    d = R.planejar(_op(it, finalidade="investimento"), R.ContextoRegras(), REF)
    assert "perfil" not in d["metodos_por_item"][0]
    assert {r["id"] for r in d["requisitos"] if r["item_id"] == "bov1"} == {
        "item:bov1:quantidade",
        "item:bov1:comprovante_nfe",
        "item:bov1:gta",
        "item:bov1:MCR-3-3-item10-marcacao-animais",
    }



# ============================================================ revisão 0.5.0 (onda 3)
MANUTENCAO = "Custeio de manutenção de 150 bois em engorda (sal mineral, ração e vacinas)"
CASOS_PLANO = [
    # (regra, descrição do item, componentes no plano, não aplicáveis, nota de manutenção no plano?)
    ("MCR-2-7-item1-metodo-documentado-if: item de aquisição lista NF-e e GTA, sem a nota de manutenção",
     "Custeio de aquisição de 80 garrotes para recria", ["contagem", "nfe", "gta", "lotacao"], [], False),
    ("MCR-2-7-item1-metodo-documentado-if: item só de manutenção não lista NF-e nem GTA de compra",
     MANUTENCAO, ["contagem", "lotacao"], ["nfe", "gta"], True),
    ("MCR-2-7-item1-metodo-documentado-if: item que não dá para classificar mantém NF-e e GTA (nunca dispensa)",
     "Bovinos de corte - recria", ["contagem", "nfe", "gta", "lotacao"], [], False),
]


@pytest.mark.parametrize("regra,descricao,componentes,fora,nota", CASOS_PLANO, ids=[c[0] for c in CASOS_PLANO])
def test_plano_lista_so_os_componentes_que_se_aplicam(regra, descricao, componentes, fora, nota):
    d = R.planejar(_op(_item(descricao, qtd=150)), R.ContextoRegras(prioridade_verificacao="media"), REF)
    p = d["metodos_por_item"][0]["perfil"]
    assert p["componentes"] == componentes and p["nao_aplicaveis"] == fora, regra
    assert set(p["metodo_if"]) == set(componentes) | ({"manutencao"} if nota else set()), regra
    # o plano e o campo metodo_if do laudo usam a mesma regra
    chs, evs = _verificadas()
    if fora:
        chs = chs[:1]
    c = _avaliar(_op(_item(descricao, qtd=150), area_inf=100.0), chs, evs).campos["item:bov1:metodo_if"]
    assert set(c.valor["componentes"]) == set(componentes) and c.valor.get("nao_aplicaveis", []) == fora


def test_pendente_nao_bloqueante_aparece_diferente_do_que_bloqueia():
    """Decisão 0.5.0: o pendente de regra não bloqueante (lotação acima do parâmetro) continua `pendente`, mas
    traz a ressalva, o motivo diz que não bloqueia e ele vai para `nao_bloqueantes`, não para `bloqueios`. O
    pendente que bloqueia (sem GTA) não leva nada disso."""
    chs, evs = _verificadas()
    res = _avaliar(_op(area_inf=10.0), chs[:2], evs)  # 80 cab em 10 ha = 8 cab/ha; sem GTA
    lot, gta = res.campos["item:bov1:lotacao"], res.campos["item:bov1:gta"]
    assert lot.status == gta.status == "pendente"
    assert R.RESSALVA_NAO_BLOQUEANTE in lot.ressalvas and lot.motivo.endswith("(não bloqueia o laudo)")
    assert R.RESSALVA_NAO_BLOQUEANTE not in gta.ressalvas and "não bloqueia" not in gta.motivo
    assert res.nao_bloqueantes == ["item:bov1:lotacao"]
    bloqueados = {b.campo for b in res.bloqueios}
    assert "item:bov1:gta" in bloqueados and "item:bov1:lotacao" not in bloqueados
    assert res.campos["item:bov1"].status == "pendente" and "gta" in res.campos["item:bov1"].motivo
    sem_metodo = _avaliar(_op(), *_verificadas(), metodo=None)
    assert sem_metodo.nao_bloqueantes == ["item:bov1:metodo_if"] and sem_metodo.pode_emitir is False
    assert sem_metodo.campos["item:bov1:metodo_if"].motivo.endswith("(não bloqueia o laudo)")
    verificado = _avaliar(_op(), *_verificadas())
    assert verificado.nao_bloqueantes == [] and not verificado.campos["item:bov1:lotacao"].ressalvas
    assert verificado.campos["item:bov1"].motivo == "todas as exigências verificadas"


def test_agregacao_do_item_fala_em_exigencias_bloqueantes():
    r = carregar("mcr-2-7").regra("OP-agregacao-item")
    assert "bloqueantes" in r.criterios["verificado"] and "bloqueantes" in r.justificativa


def test_prazo_de_contestacao_do_pacote_registrado_como_parametro_operacional():
    """PAR-pacote-prazo-contestacao-dias: 15 dias, escolha da IF (o MCR não fixa prazo de contestação), base no
    MCR 2-8-3 (60 dias da IF) e 2-7-18, com pendência de compliance; é o mesmo valor do pacote."""
    from laudo.tools import pacote

    rb = carregar("mcr-2-7")
    p = next(x for x in rb.parametros if x.id == "PAR-pacote-prazo-contestacao-dias")
    assert p.valor == 15 and p.unidade == "dias corridos" and p.origem == "parametro_operacional"
    assert p.base_normativa == ["MCR 2-8-3", "MCR 2-7-18"] and "não direito do mutuário" in p.justificativa
    assert any("PAR-pacote-prazo-contestacao-dias" in x for x in rb.revisao.pendencias)
    assert pacote.PAR_PRAZO == p.id and pacote.PRAZO_CONTESTACAO_DIAS == p.valor
    normas = (REPO / "docs" / "normas" / "mcr_2_7.md").read_text(encoding="utf-8")
    assert "3 - A desclassificação da operação consiste" in normas and "18 - O mutuário poderá" in normas

# ============================================================ 4 casos de dev (modo determinístico)
@pytest.fixture(scope="module")
def casos_dev(tmp_path_factory):
    """Os 4 casos versionados em eval/golden/casos_publicos/dev_custeio/ (split `dev_custeio`)."""
    sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))
    import casos_publicos as CP

    d = tmp_path_factory.mktemp("custeio_dev")
    return CP, CP.carregar(CP.DIR_CUSTEIO), d / "trabalho"


def test_dev_custeio_versionado_e_o_do_gerador(casos_dev, tmp_path):
    import yaml

    CP, _, _ = casos_dev
    meta = CP.gerar(CP.CUSTEIO_DEV, tmp_path)
    versionado = yaml.safe_load((CP.DIR_CUSTEIO / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert meta["sha256_conteudo"] == versionado["sha256_conteudo"]
    for c in versionado["casos"]:
        for nome in c["arquivos"]:
            assert (CP.DIR_CUSTEIO / c["id"] / nome).read_bytes() == (tmp_path / c["id"] / nome).read_bytes()
    assert "dev_custeio" in versionado["nota"]


def test_quatro_casos_de_dev_do_perfil(casos_dev):
    CP, casos, trabalho = casos_dev
    assert [c["id"] for c, _ in casos] == ["CUS-0001", "CUS-0002", "CUS-0003", "CUS-0004"]
    assert {c["classe"] for c, _ in casos} == {"valido", "defeito"}
    for caso, d in casos:
        assert caso["operacao"]["finalidade"] == "custeio" and caso["split"] == "dev_custeio"
        r = CP.rodar(caso, d, trabalho)
        assert CP.conferir(caso, r) == [], (caso["id"], r["campos"])
        if caso["classe"] == "valido":  # zero over-blocking: válido do perfil pode emitir o rascunho
            assert r["emissao_permitida"] and not r["pendencias"], (caso["id"], r["pendencias"])
