"""avaliar_regras: critérios de status por item (bovinos, cerca/curral, máquina) e requisitos do laudo.

Tabelas de casos; cada caso cita o item da norma ou o parâmetro operacional. Dados 100% sintéticos
(marcadores TESTE-SINTETICO, anon-teste).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from laudo.contracts import REGISTRO, CampoLaudo, Checagem, Evidencia, Fiscalizacao, ItemFinanciado, Operacao
from laudo.tools import regras as R

REF = date(2026, 10, 8)
LIB = date(2026, 8, 1)
TZ = ZoneInfo("America/Sao_Paulo")
DIA = datetime(2026, 9, 20, 10, 0, tzinfo=TZ)


def _item(iid: str, tipo: str, qtd: float | None = 1) -> ItemFinanciado:
    return ItemFinanciado(id=iid, tipo=tipo, descricao=f"{tipo} (sintético)", quantidade=qtd)


BOV = _item("bov1", "bovinos", 100)
CUR = _item("cur1", "curral")
MAQ = _item("maq1", "maquina")


def _op(*itens: ItemFinanciado, area_fin: float = 120.0, contratacao: date = date(2026, 7, 1)) -> Operacao:
    return Operacao(ref_bacen="TESTE-SINTETICO-0001", tomador_ref="anon-teste", finalidade="investimento",
                    data_contratacao=contratacao, area_financiada_ha=area_fin, itens=list(itens), fonte="sintetico")


def _ev(tipo: str = "foto", quando: datetime | None = DIA, **meta) -> Evidencia:
    return Evidencia(tipo=tipo, sha256="0" * 64, capturada_em=quando, meta=meta)


def _chk(ferramenta: str, st: str, item_id: str | None = None, ev: Evidencia | None = None, **resultado):
    return Checagem(ferramenta=ferramenta, entrada_hash="teste", status=st, item_id=item_id,
                    resultado=resultado, evidencias=[ev.id] if ev else [])


def _decl(conflito: bool = False) -> Evidencia:
    return _ev("declaracao", None, assunto="independencia_fiscal", conflito=conflito)


def _fis(op: Operacao, checagens=(), evidencias=(), metodo="presencial", campos=None) -> Fiscalizacao:
    return Fiscalizacao(operacao=op, metodo=metodo, checagens=list(checagens), evidencias=list(evidencias),
                        campos=campos or {})


def _avaliar(fis: Fiscalizacao, ref: date = REF, **ctx) -> R.ResultadoAvaliacao:
    ctx.setdefault("data_liberacao", LIB)
    return R.avaliar(fis, R.ContextoRegras(**ctx), ref)


def _bloqueados(res: R.ResultadoAvaliacao) -> set[str]:
    return {b.campo for b in res.bloqueios}


# ============================================================ bovinos: contagem
# Q = 100 cabeças, tolerância 5% (PAR-contagem-tolerancia-pct) → limite L = 95.
CASOS_CONTAGEM = [
    # descrição (regra), status da ferramenta, resultado, status esperado
    ("OP-bovinos-contagem: inferior = L conta como dentro", "ok", {"contagem": 97, "intervalo": [95, 99]},
     "verificado"),
    ("OP-bovinos-contagem: intervalo cruza L → pendente", "ok", {"contagem": 96, "intervalo": [94, 98]}, "pendente"),
    ("OP-bovinos-contagem: superior = L ainda cruza (não diverge)", "ok", {"contagem": 94, "intervalo": [93, 95]},
     "pendente"),
    ("OP-bovinos-contagem: superior < L → divergente", "ok", {"contagem": 92, "intervalo": [90, 94.9]},
     "divergente"),
    ("OP-bovinos-contagem: mais animais que o financiado não diverge", "ok",
     {"contagem": 130, "intervalo": [125, 135]}, "verificado"),
    ("OP-bovinos-contagem: contagem pontual no limite (95)", "ok", {"contagem": 95}, "verificado"),
    ("OP-bovinos-contagem: contagem pontual abaixo (94)", "ok", {"contagem": 94}, "divergente"),
    ("OP-bovinos-contagem: a regra recalcula, o status da ferramenta não decide", "divergente",
     {"contagem": 97, "intervalo": [96, 99]}, "verificado"),
    ("OP-bovinos-contagem: contagem com abstenção → pendente, nunca divergente", "indeterminado",
     {"motivo": "oclusão no corredor", "contagem": 40}, "pendente"),
    ("OP-status-mapeamento: falha da ferramenta → pendente", "erro", {"motivo": "timeout"}, "pendente"),
    ("OP-bovinos-contagem: resultado da visão 'indeterminado' prevalece sobre checagem ok", "ok",
     {"status": "indeterminado", "contagem": 60, "intervalo": [40, 90],
      "motivos": [{"codigo": "OCLUSAO", "msg": "oclusão alta no corredor", "abstem": True}]}, "pendente"),
]


@pytest.mark.parametrize("norma,status_chk,resultado,esperado", CASOS_CONTAGEM, ids=[c[0] for c in CASOS_CONTAGEM])
def test_contagem_bovinos(norma, status_chk, resultado, esperado):
    v = _ev("video")
    res = _avaliar(_fis(_op(BOV), [_chk("contar_bovinos_video", status_chk, "bov1", v, **resultado)], [v]))
    campo = res.campos["item:bov1:quantidade"]
    assert campo.status == esperado, campo.motivo
    assert campo.regra_id == "OP-bovinos-contagem-tolerancia"
    assert campo.valor["limite_inferior"] == 95.0
    if esperado == "pendente":
        assert "item:bov1:quantidade" in _bloqueados(res)
    if esperado != "pendente" and status_chk not in ("erro", "indeterminado"):
        assert campo.evidencias == [v.id] and len(campo.checagens) == 1


def test_contagem_limite_exato_sem_erro_de_ponto_flutuante():
    """Q = 40, tolerância 5% → L = 38 exatamente (Decimal); [38, 40] está dentro."""
    item = _item("bov1", "bovinos", 40)
    res = _avaliar(_fis(_op(item), [_chk("contar_bovinos_video", "ok", "bov1", contagem=39, intervalo=[38, 40])]))
    assert res.campos["item:bov1:quantidade"].status == "verificado"


def test_contagem_sem_video_fica_pendente_com_pedido():
    res = _avaliar(_fis(_op(BOV)))
    campo = res.campos["item:bov1:quantidade"]
    assert campo.status == "pendente" and "corredor" in campo.motivo
    b = next(b for b in res.bloqueios if b.campo == "item:bov1:quantidade")
    assert b.regra_id == "OP-bovinos-contagem-tolerancia"


def test_contagem_quantidade_financiada_desconhecida():
    res = _avaliar(_fis(_op(_item("bov1", "bovinos", None)),
                        [_chk("contar_bovinos_video", "ok", "bov1", contagem=50)]))
    assert res.campos["item:bov1:quantidade"].status == "pendente"


CASOS_TENTATIVAS = [
    # descrição, sequência de (status, resultado), esperado
    ("PAR-tentativas-inconclusivas-max: 1 abstenção → pendente", [("indeterminado", {})], "pendente"),
    ("PAR-tentativas-inconclusivas-max: 2 abstenções → abstenção", [("indeterminado", {}), ("indeterminado", {})],
     "abstencao"),
    ("PAR-tentativas: intervalo cruzando + abstenção = 2 inconclusivas",
     [("ok", {"contagem": 96, "intervalo": [94, 98]}), ("indeterminado", {})], "abstencao"),
    ("OP-status-mapeamento: abstenção seguida de contagem conclusiva → verificado",
     [("indeterminado", {}), ("ok", {"contagem": 98, "intervalo": [96, 99]})], "verificado"),
    ("OP-status-mapeamento: conclusivas conflitantes → pendente (recontar até passar não resolve)",
     [("ok", {"contagem": 80, "intervalo": [78, 82]}), ("ok", {"contagem": 98, "intervalo": [96, 99]})], "pendente"),
    ("OP-status-mapeamento: erros não contam como tentativa", [("erro", {}), ("erro", {})], "pendente"),
]


@pytest.mark.parametrize("norma,seq,esperado", CASOS_TENTATIVAS, ids=[c[0] for c in CASOS_TENTATIVAS])
def test_tentativas_e_conflitos_da_contagem(norma, seq, esperado):
    chks = [_chk("contar_bovinos_video", s, "bov1", **r) for s, r in seq]
    res = _avaliar(_fis(_op(BOV), chks))
    assert res.campos["item:bov1:quantidade"].status == esperado


def test_abstencao_bloqueia_ate_haver_justificativa_humana():
    chks = [_chk("contar_bovinos_video", "indeterminado", "bov1") for _ in range(2)]
    res = _avaliar(_fis(_op(BOV), chks))
    b = next(b for b in res.bloqueios if b.campo == "item:bov1:quantidade")
    assert b.status == "abstencao" and "justificativa humana" in b.falta
    anterior = CampoLaudo(campo="item:bov1:quantidade", status="abstencao", regra_id="OP-bovinos-contagem-tolerancia",
                          justificativa_humana="lote em pasto de 40 ha; contagem manual do fiscal anexada")
    res2 = _avaliar(_fis(_op(BOV), chks, campos={"item:bov1:quantidade": anterior}))
    assert "item:bov1:quantidade" not in _bloqueados(res2)
    assert res2.campos["item:bov1:quantidade"].justificativa_humana.startswith("lote em pasto")


# ============================================================ bovinos: NF-e e GTA
CASOS_DOC_BOVINOS = [
    # regra, campo, ferramenta, status, resultado, esperado
    ("MCR 2-5-10-b: NF-e conciliada", "comprovante_nfe", "conciliar_nfe", "ok", {}, "verificado"),
    ("MCR 2-5-10-b: NF-e não confere", "comprovante_nfe", "conciliar_nfe", "divergente",
     {"motivo": "NF-e com 60 cabeças; projeto com 100"}, "divergente"),
    ("MCR 2-5-10-b: XML ilegível → pendente", "comprovante_nfe", "conciliar_nfe", "indeterminado", {}, "pendente"),
    ("MCR 2-5-10-b: requisito ausente → pendente", "comprovante_nfe", "conciliar_nfe", "ok",
     {"requisitos_ausentes": ["quantidade"]}, "pendente"),
    ("OP-bovinos-gta: GTA confere", "gta", "conciliar_gta", "ok", {}, "verificado"),
    ("OP-bovinos-gta: GTA com destino diferente", "gta", "conciliar_gta", "divergente", {}, "divergente"),
]


@pytest.mark.parametrize("norma,campo,ferr,status,resultado,esperado", CASOS_DOC_BOVINOS,
                         ids=[c[0] for c in CASOS_DOC_BOVINOS])
def test_documentos_bovinos(norma, campo, ferr, status, resultado, esperado):
    res = _avaliar(_fis(_op(BOV), [_chk(ferr, status, "bov1", **resultado)]))
    assert res.campos[f"item:bov1:{campo}"].status == esperado


@pytest.mark.parametrize("campo", ["comprovante_nfe", "gta"],
                         ids=["MCR 2-5-10-b: sem NF-e → pendente", "OP-bovinos-gta: sem GTA → pendente"])
def test_documento_ausente_e_pendente_e_bloqueia(campo):
    res = _avaliar(_fis(_op(BOV)))
    assert res.campos[f"item:bov1:{campo}"].status == "pendente"
    assert f"item:bov1:{campo}" in _bloqueados(res)


def test_alerta_prazo_do_mutuario_vencido_sem_comprovante():
    """MCR 2-5-10-b: liberação 01/08 → comprovantes até 31/08; em 08/10 sem NF-e gera alerta."""
    res = _avaliar(_fis(_op(BOV)))
    assert any("2026-08-31" in a and "2-5-10-b" in a for a in res.alertas)


def _bovinos_completo(contagem=(98, [96, 99]), nfe="ok", gta="ok") -> Fiscalizacao:
    v = _ev("video")
    n, iv = contagem
    return _fis(_op(BOV), [
        _chk("contar_bovinos_video", "ok", "bov1", v, contagem=n, intervalo=iv),
        _chk("conciliar_nfe", nfe, "bov1"),
        _chk("conciliar_gta", gta, "bov1"),
    ], [v, _decl()])


def test_item_bovinos_verificado_quando_tudo_confere():
    res = _avaliar(_bovinos_completo())
    assert res.campos["item:bov1"].status == "verificado"
    assert res.campos["item:bov1"].regra_id == "OP-agregacao-item"
    assert res.pode_emitir, res.bloqueios


@pytest.mark.parametrize(
    "kwargs,esperado",
    [({"contagem": (40, [38, 42])}, "divergente"), ({"gta": "divergente"}, "divergente"),
     ({"nfe": "indeterminado"}, "pendente")],
    ids=["OP-agregacao-item: contagem divergente domina", "OP-agregacao-item: GTA divergente",
         "OP-agregacao-item: NF-e pendente"],
)
def test_agregacao_do_item(kwargs, esperado):
    res = _avaliar(_bovinos_completo(**kwargs))
    assert res.campos["item:bov1"].status == esperado


def test_divergencia_nao_bloqueia_mas_aparece_no_campo():
    """Divergente é achado (vai ao laudo); a exigência de justificativa é da política (POL-02)."""
    res = _avaliar(_bovinos_completo(contagem=(40, [38, 42])))
    assert res.campos["item:bov1:quantidade"].status == "divergente"
    assert "item:bov1:quantidade" not in _bloqueados(res)
    assert res.resumo["divergente"] == 1


# ============================================================ cerca/curral
CASOS_GEOFENCE = [
    # regra, resultado do geofence, esperado
    ("OP-benfeitoria-geofence: dentro da gleba", {"status": "dentro"}, "verificado"),
    ("OP-benfeitoria-geofence: fora a 40 m", {"status": "fora", "distancia_borda_m": 40}, "verificado"),
    ("OP-benfeitoria-geofence: fora a 100 m (limite inclusivo)", {"status": "fora", "distancia_borda_m": 100},
     "verificado"),
    ("OP-benfeitoria-geofence: fora a 100,1 m → refazer ou justificar", {"status": "fora", "distancia_borda_m": 100.1},
     "pendente"),
    ("OP-benfeitoria-geofence: fora a 1000 m → ainda pendente", {"status": "fora", "distancia_borda_m": 1000},
     "pendente"),
    ("OP-benfeitoria-geofence: fora a 1000,1 m → divergente", {"status": "fora", "distancia_borda_m": 1000.1},
     "divergente"),
    ("OP-benfeitoria-geofence: GPS impreciso → pendente", {"status": "indeterminado"}, "pendente"),
    # saída da geofence@0.1.1: status comum + posicao
    ("OP-benfeitoria-geofence: posicao dentro (status ok)", {"status": "ok", "posicao": "dentro"}, "verificado"),
    ("OP-benfeitoria-geofence: posicao fora a 650 m (status divergente) → pendente",
     {"status": "divergente", "posicao": "fora", "distancia_borda_m": 650}, "pendente"),
    ("OP-benfeitoria-geofence: posicao fora a 40 m (status divergente) → verificado",
     {"status": "divergente", "posicao": "fora", "distancia_borda_m": 40}, "verificado"),
]


@pytest.mark.parametrize("norma,resultado,esperado", CASOS_GEOFENCE, ids=[c[0] for c in CASOS_GEOFENCE])
def test_geofence_benfeitoria(norma, resultado, esperado):
    f = _ev("foto")
    st = resultado["status"]
    status_chk = st if st in ("ok", "divergente", "indeterminado") else "ok"
    res = _avaliar(_fis(_op(CUR), [_chk("geofence", status_chk, "cur1", f, **resultado)], [f]))
    assert res.campos["item:cur1:localizacao"].status == esperado


def test_geofence_uma_foto_muito_longe_basta_para_divergir():
    """OP-benfeitoria-geofence (agregação qualquer_divergente)."""
    f1, f2 = _ev("foto"), _ev("foto")
    res = _avaliar(_fis(_op(CUR), [
        _chk("geofence", "ok", "cur1", f1, status="dentro"),
        _chk("geofence", "divergente", "cur1", f2, status="fora", distancia_borda_m=5000),
    ], [f1, f2]))
    campo = res.campos["item:cur1:localizacao"]
    assert campo.status == "divergente" and campo.evidencias == [f2.id]


CASOS_INTEGRIDADE = [
    ("OP-evidencia-integridade-foto: foto íntegra", ["ok"], "verificado"),
    ("OP-evidencia-integridade-foto: duplicata/tela → divergente", ["divergente"], "divergente"),
    ("OP-evidencia-integridade-foto: sem EXIF → pendente (capturar no app)", ["indeterminado"], "pendente"),
    ("OP-evidencia-integridade-foto: uma adulterada entre íntegras → divergente", ["ok", "divergente"], "divergente"),
]


@pytest.mark.parametrize("norma,status,esperado", CASOS_INTEGRIDADE, ids=[c[0] for c in CASOS_INTEGRIDADE])
def test_integridade_foto(norma, status, esperado):
    chks = [_chk("integridade_foto", s, "cur1") for s in status]
    res = _avaliar(_fis(_op(CUR), chks))
    assert res.campos["item:cur1:integridade_foto"].status == esperado


@pytest.mark.parametrize(
    "ferramenta,status,esperado",
    [("classificar_foto", "ok", "verificado"), ("declaracao_conclusao", "ok", "verificado"),
     ("classificar_foto", "divergente", "divergente"), ("classificar_foto", "indeterminado", "pendente")],
    ids=["2-7-16-a: obra concluída (foto)", "2-7-16-a: conclusão declarada pelo fiscal",
         "2-7-16-a: obra inacabada", "2-7-16-a: foto não permite concluir"],
)
def test_conclusao_da_obra(ferramenta, status, esperado):
    res = _avaliar(_fis(_op(CUR), [_chk(ferramenta, status, "cur1")]))
    assert res.campos["item:cur1:conclusao"].status == esperado


CASOS_CRONOGRAMA = [
    # regra, término do cronograma, data da foto, esperado
    ("2-7-16-a: fiscalização no último dia do cronograma", date(2026, 9, 20), DIA, "verificado"),
    ("2-7-16-a: fiscalização depois do cronograma", date(2026, 9, 19), DIA, "divergente"),
    ("2-7-16-a: cronograma desconhecido", None, DIA, "pendente"),
    ("2-7-16-a: sem foto do item", date(2026, 12, 31), None, "pendente"),
]


@pytest.mark.parametrize("norma,fim,quando,esperado", CASOS_CRONOGRAMA, ids=[c[0] for c in CASOS_CRONOGRAMA])
def test_prazo_cronograma_benfeitoria(norma, fim, quando, esperado):
    chks, evs = [], []
    if quando is not None:
        f = _ev("foto", quando)
        evs, chks = [f], [_chk("geofence", "ok", "cur1", f, status="dentro")]
    cron = {"cur1": fim} if fim else {}
    res = _avaliar(_fis(_op(CUR), chks, evs), cronograma_fim=cron)
    assert res.campos["item:cur1:prazo_cronograma"].status == esperado


def test_curral_completo_verificado():
    f = _ev("foto")
    res = _avaliar(_fis(_op(CUR), [
        _chk("integridade_foto", "ok", "cur1", f), _chk("geofence", "ok", "cur1", f, status="dentro"),
        _chk("classificar_foto", "ok", "cur1", f, classe="curral"),
    ], [f, _decl()]), cronograma_fim={"cur1": date(2026, 12, 31)})
    assert res.campos["item:cur1"].status == "verificado"
    assert res.pode_emitir, res.bloqueios


# ============================================================ máquina
CASOS_MAQUINA_PRAZO = [
    # regra, data da foto da plaqueta, data informada, esperado
    ("2-7-16-b-II: fiscalização no dia 60 (30/09) está no prazo", datetime(2026, 9, 30, 15, tzinfo=TZ), None,
     "verificado"),
    ("2-7-16-b-II: fiscalização no dia 61 (01/10) é divergente", datetime(2026, 10, 1, 9, tzinfo=TZ), None,
     "divergente"),
    ("2-7-16-b-II: 01/10 02h UTC ainda é 30/09 em Goiás (dia 60)", datetime(2026, 10, 1, 2, tzinfo=UTC), None,
     "verificado"),
    ("2-7-16-b-II: data informada no contexto prevalece", datetime(2026, 10, 5, 9, tzinfo=TZ), date(2026, 9, 30),
     "verificado"),
    ("2-7-16-b-II: prazo vencido sem fiscalização registrada → pendente", None, None, "pendente"),
]


@pytest.mark.parametrize("norma,quando,informada,esperado", CASOS_MAQUINA_PRAZO,
                         ids=[c[0] for c in CASOS_MAQUINA_PRAZO])
def test_prazo_maquina_60_dias(norma, quando, informada, esperado):
    chks, evs = [], []
    if quando is not None:
        f = _ev("foto", quando)
        evs, chks = [f], [_chk("conferir_numero_serie", "ok", "maq1", f)]
    res = _avaliar(_fis(_op(MAQ), chks, evs), data_fiscalizacao=informada)
    campo = res.campos["item:maq1:prazo_60d"]
    assert campo.status == esperado, campo.motivo
    assert campo.regra_id == "MCR-2-7-item16-maquinas-60d"
    if esperado == "pendente":
        assert "vencido" in campo.motivo


def test_prazo_maquina_sem_data_de_liberacao():
    res = _avaliar(_fis(_op(MAQ)), data_liberacao=None)
    assert res.campos["item:maq1:prazo_60d"].status == "pendente"
    assert "liberação" in res.campos["item:maq1:prazo_60d"].motivo


CASOS_NFE_MAQUINA = [
    ("2-7-16-b-II: NF-e com bem, comprador e IF", "ok", {}, "verificado"),
    ("2-7-16-b-II: NF-e sem identificação da IF → pendente", "ok", {"requisitos_ausentes": ["identificacao_if"]},
     "pendente"),
    ("2-7-16-b-II: ausência fora da norma não pesa", "ok", {"requisitos_ausentes": ["placa_transportador"]},
     "verificado"),
    ("2-7-16-b-II: NF-e de outro bem → divergente", "divergente", {}, "divergente"),
]


@pytest.mark.parametrize("norma,status,resultado,esperado", CASOS_NFE_MAQUINA, ids=[c[0] for c in CASOS_NFE_MAQUINA])
def test_nfe_maquina(norma, status, resultado, esperado):
    res = _avaliar(_fis(_op(MAQ), [_chk("conciliar_nfe", status, "maq1", **resultado)]))
    campo = res.campos["item:maq1:nfe"]
    assert campo.status == esperado
    if resultado.get("requisitos_ausentes") == ["identificacao_if"]:
        assert "identificacao_if" in campo.motivo


@pytest.mark.parametrize(
    "status,esperado",
    [("ok", "verificado"), ("divergente", "divergente"), ("indeterminado", "pendente")],
    ids=["2-7-16-b-I: número confere com a NF-e", "2-7-16-b-I: número difere", "2-7-16-b-I: plaqueta ilegível"],
)
def test_numero_de_serie(status, esperado):
    res = _avaliar(_fis(_op(MAQ), [_chk("conferir_numero_serie", status, "maq1")]))
    assert res.campos["item:maq1:numero_serie"].status == esperado


def test_numero_de_serie_quando_nao_couber():
    res = _avaliar(_fis(_op(MAQ)), itens_sem_numero_serie=["maq1"])
    assert "item:maq1:numero_serie" not in res.campos
    assert any(n["campo"] == "item:maq1:numero_serie" for n in res.nao_aplicaveis)


def test_checagem_de_outro_item_nao_conta():
    res = _avaliar(_fis(_op(MAQ, BOV), [_chk("conciliar_nfe", "ok", "bov1")]))
    assert res.campos["item:maq1:nfe"].status == "pendente"
    assert res.campos["item:bov1:comprovante_nfe"].status == "verificado"


# ============================================================ requisitos do laudo
def test_metodo_nao_registrado_bloqueia():
    """MCR 2-7-1-d: necessário registro das verificações (método)."""
    res = _avaliar(_fis(_op(BOV), metodo=None))
    assert res.campos["laudo:metodo"].status == "pendente" and "laudo:metodo" in _bloqueados(res)
    res = _avaliar(_fis(_op(BOV), metodo="autofiscalizacao_assistida"))
    assert res.campos["laudo:metodo"].valor["enquadramento_normativo"] == "documental"


@pytest.mark.parametrize(
    "evidencias,esperado",
    [([], "pendente"), ([_decl(False)], "verificado"), ([_decl(True)], "divergente")],
    ids=["2-7-15: sem declaração", "2-7-15: fiscal independente", "2-7-15: fiscal contratado pelo mutuário"],
)
def test_independencia_do_fiscal(evidencias, esperado):
    res = _avaliar(_fis(_op(BOV), evidencias=evidencias))
    assert res.campos["laudo:independencia_fiscal"].status == esperado


# Formato de `metadados_laudo` do serie_ndvi (src/laudo/geo/ndvi.py) + os dois campos que ele ainda não traz.
METADADOS_NDVI_ATUAL = {"satelite": ["sentinel-2b"], "sensor": "MSI (MultiSpectral Instrument)",
                        "bandas": {"B04": "vermelho", "B08": "infravermelho próximo"}, "resolucao_m": 10,
                        "datas": ["2026-09-10", "2026-09-25"],
                        "metodologia": "NDVI=(B08-B04)/(B08+B04) sobre L2A; máscara SCL"}
METADADOS_OK = {**METADADOS_NDVI_ATUAL, "resolucao_radiometrica_bits": 12,
                "uso_na_fiscalizacao": "presença e vigor de pastagem na gleba (MCR 2-7-9)"}
SEM_BANDAS = {k: v for k, v in METADADOS_OK.items() if k != "bandas"}

CASOS_SR = [
    # regra, checagens de sensoriamento, status sensoriamento, status metadados
    ("2-7-5: obrigatório e sem checagem → pendente", [], "pendente", None),
    ("2-7-5 + 2-7-4-b: checagem com todos os metadados", [("ok", {"metadados_laudo": METADADOS_OK})], "verificado",
     "verificado"),
    ("2-7-4-b-I: falta 'bandas' → pendente", [("ok", {"metadados_laudo": SEM_BANDAS})], "verificado", "pendente"),
    ("2-7-4-b-I e III: saída atual do serie_ndvi sem resolução radiométrica nem uso → pendente",
     [("ok", {"metadados_laudo": METADADOS_NDVI_ATUAL})], "verificado", "pendente"),
    ("2-7-4-b: metadados no nível de cima do resultado também valem", [("ok", METADADOS_OK)], "verificado",
     "verificado"),
    ("2-7-10: sensoriamento inconclusivo → complementar com outro método",
     [("indeterminado", {"motivo": "nuvem", "metadados_laudo": METADADOS_OK})], "pendente", "verificado"),
    ("2-7-9: sem pastagem detectada → divergente", [("divergente", {"metadados_laudo": METADADOS_OK})],
     "divergente", "verificado"),
]


@pytest.mark.parametrize("norma,chks,st_sr,st_md", CASOS_SR, ids=[c[0] for c in CASOS_SR])
def test_sensoriamento_obrigatorio_e_metadados(norma, chks, st_sr, st_md):
    checagens = [_chk("serie_ndvi", s, None, **r) for s, r in chks]
    res = _avaliar(_fis(_op(BOV, area_fin=850.0), checagens))
    assert res.campos["laudo:sensoriamento_remoto"].status == st_sr
    if st_md is None:
        assert "laudo:metadados_sensoriamento" not in res.campos
    else:
        assert res.campos["laudo:metadados_sensoriamento"].status == st_md
    if norma.startswith("2-7-10"):
        assert "2-7-10" in res.campos["laudo:sensoriamento_remoto"].motivo
    if norma.startswith("2-7-4-b-I:"):
        assert "bandas" in res.campos["laudo:metadados_sensoriamento"].motivo
    if norma.startswith("2-7-4-b-I e III"):
        motivo = res.campos["laudo:metadados_sensoriamento"].motivo
        assert "resolucao_radiometrica" in motivo and "uso_na_fiscalizacao" in motivo and "sensor" not in motivo


def test_sensoriamento_nao_obrigatorio_nao_gera_campo():
    """2-7-5-b: 300 ha exatos não obriga."""
    res = _avaliar(_fis(_op(BOV, area_fin=300.0)), area_total_ha=300.0)
    assert "laudo:sensoriamento_remoto" not in res.campos
    assert any(n["campo"] == "laudo:sensoriamento_remoto" for n in res.nao_aplicaveis)


def test_metadados_valem_mesmo_quando_o_sensoriamento_e_voluntario():
    """2-7-4-b: se o laudo usa sensoriamento remoto, registra os metadados (mesmo abaixo de 300 ha)."""
    res = _avaliar(_fis(_op(BOV), [_chk("serie_ndvi", "ok", None, satelite="Sentinel-2A")]))
    assert res.campos["laudo:metadados_sensoriamento"].status == "pendente"


def test_item_fora_do_escopo_bloqueia():
    res = _avaliar(_fis(_op(_item("lav1", "lavoura", 50))))
    assert res.campos["item:lav1"].status == "pendente"
    assert next(b for b in res.bloqueios if b.campo == "item:lav1").regra_id == "OP-escopo-itens-regional"


# ============================================================ fluxo completo e ferramenta
def test_fluxo_regional_completo_libera_rascunho():
    v, f = _ev("video"), _ev("foto")
    fis = _fis(_op(BOV, CUR), [
        _chk("contar_bovinos_video", "ok", "bov1", v, contagem=99, intervalo=[97, 101]),
        _chk("conciliar_nfe", "ok", "bov1"), _chk("conciliar_gta", "ok", "bov1"),
        _chk("integridade_foto", "ok", "cur1", f), _chk("geofence", "ok", "cur1", f, status="dentro"),
        _chk("classificar_foto", "ok", "cur1", f),
    ], [v, f, _decl()])
    res = _avaliar(fis, cronograma_fim={"cur1": date(2026, 12, 31)})
    assert res.bloqueios == [] and res.pode_emitir
    assert res.resumo["verificado"] == len([n for n in res.campos if n.count(":") != 1 or n.startswith("laudo")])
    assert res.fonte_versao.startswith("rulebook-mcr-2-7@")
    assert res.data_fiscalizacao == DIA.date()


def test_ferramenta_avaliar_regras_e_pura_e_devolve_envelope():
    fis = _bovinos_completo(contagem=(40, [38, 42]))
    antes = fis.model_dump()
    env = REGISTRO["avaliar_regras"].funcao(
        R.AvaliarRegrasEntrada(fiscalizacao=fis, contexto=R.ContextoRegras(data_liberacao=LIB), data_referencia=REF))
    assert env.ok, env.error
    assert env.data["campos"]["item:bov1:quantidade"]["status"] == "divergente"
    assert env.data["campos"]["item:bov1:quantidade"]["regra_id"] == "OP-bovinos-contagem-tolerancia"
    assert env.data["pode_emitir_rascunho"] is True
    assert fis.model_dump() == antes  # não altera o estado


def test_ferramenta_avaliar_regras_entrada_invalida():
    env = REGISTRO["avaliar_regras"].funcao({"fiscalizacao": {"operacao": {}}})
    assert not env.ok and env.error.code.value == "ENTRADA_INVALIDA"


# ================================================== 0.2.0: capturas superadas e reconciliação de documentos
CASOS_ORDEM = [
    # regra, sequência de checagens (ferramenta, status, resultado), esperado
    ("OP-evidencia-integridade-foto 0.2.0: foto íntegra seguida da cópia dela → pendente",
     "integridade_foto", "item:cur1:integridade_foto", [("ok", {}), ("indeterminado", {})], "pendente"),
    ("OP-evidencia-integridade-foto 0.2.0: foto sem EXIF refeita depois → verificado",
     "integridade_foto", "item:cur1:integridade_foto", [("indeterminado", {}), ("ok", {})], "verificado"),
    ("OP-benfeitoria-geofence 0.2.0: foto a 650 m e depois de dentro da gleba → verificado",
     "geofence", "item:cur1:localizacao",
     [("divergente", {"posicao": "fora", "distancia_borda_m": 650}), ("ok", {"posicao": "dentro"})], "verificado"),
    ("OP-benfeitoria-geofence 0.2.0: foto de dentro e depois uma a 650 m → pendente",
     "geofence", "item:cur1:localizacao",
     [("ok", {"posicao": "dentro"}), ("divergente", {"posicao": "fora", "distancia_borda_m": 650})], "pendente"),
]


@pytest.mark.parametrize("norma,ferr,campo,seq,esperado", CASOS_ORDEM, ids=[c[0] for c in CASOS_ORDEM])
def test_captura_inconclusiva_so_e_superada_por_posterior(norma, ferr, campo, seq, esperado):
    evs = [_ev("foto") for _ in seq]
    chks = [_chk(ferr, st, "cur1", ev, **res) for (st, res), ev in zip(seq, evs, strict=True)]
    assert _avaliar(_fis(_op(CUR), chks, evs)).campos[campo].status == esperado


def test_conciliacao_refeita_com_todos_os_documentos_substitui_a_parcial():
    """MCR-2-5-item10: 1ª NF-e sozinha (quantidade a menos) é substituída pela conciliação das duas notas."""
    parcial = _chk("conciliar_nfe", "divergente", "bov1", motivo="nfe_quantidade: divergente")
    completa = _chk("conciliar_nfe", "ok", "bov1", substitui=[parcial.id])
    res = _avaliar(_fis(_op(BOV), [parcial, completa]))
    assert res.campos["item:bov1:comprovante_nfe"].status == "verificado"
    assert res.campos["item:bov1:comprovante_nfe"].checagens == [completa.id]
    sem_substituir = _avaliar(_fis(_op(BOV), [parcial, _chk("conciliar_nfe", "ok", "bov1")]))
    assert sem_substituir.campos["item:bov1:comprovante_nfe"].status == "pendente"  # conflitantes


# ================================================== 0.3.0: faixa intermediária do geofence é pendência, não abstenção
CASOS_GEOFENCE_030 = [
    # regra, sequência de checagens do geofence (status, resultado), justificativa?, esperado, bloqueia?
    ("OP-benfeitoria-geofence 0.3.0: duas fotos fora a 405 e 574 m (D06) → pendente, não abstenção",
     [("divergente", {"posicao": "fora", "distancia_borda_m": 404.8}),
      ("divergente", {"posicao": "fora", "distancia_borda_m": 574.2})], None, "pendente", True),
    ("OP-benfeitoria-geofence 0.3.0: três fotos fora a 722, 634 e 650 m → continua pendente",
     [("divergente", {"posicao": "fora", "distancia_borda_m": d}) for d in (722.3, 633.5, 650.0)], None,
     "pendente", True),
    ("OP-benfeitoria-geofence 0.3.0 + PAR-tentativas-inconclusivas-max: GPS impreciso duas vezes → abstenção",
     [("indeterminado", {"posicao": "indeterminado"}), ("indeterminado", {"posicao": "indeterminado"})], None,
     "abstencao", True),
    ("OP-benfeitoria-geofence 0.3.0: GPS impreciso e depois foto medida a 650 m → pendente (faixa medida)",
     [("indeterminado", {"posicao": "indeterminado"}),
      ("divergente", {"posicao": "fora", "distancia_borda_m": 650.0})], None, "pendente", True),
    ("OP-benfeitoria-geofence 0.3.0: foto a 650 m com justificativa do fiscal → pendente que não bloqueia",
     [("divergente", {"posicao": "fora", "distancia_borda_m": 650.0})],
     "Justifico a localização: o curral fica na sede, fora da gleba financiada.", "pendente", False),
    ("OP-benfeitoria-geofence 0.3.0: duas fotos a 650 m e depois uma de dentro → verificado",
     [("divergente", {"posicao": "fora", "distancia_borda_m": 650.0}),
      ("divergente", {"posicao": "fora", "distancia_borda_m": 640.0}), ("ok", {"posicao": "dentro"})], None,
     "verificado", False),
    ("OP-benfeitoria-geofence 0.3.0: foto a 1.500 m → divergente (acima de PAR-geofence-longe-m)",
     [("divergente", {"posicao": "fora", "distancia_borda_m": 1500.0})], None, "divergente", False),
]


@pytest.mark.parametrize("norma,seq,justificativa,esperado,bloqueia", CASOS_GEOFENCE_030,
                         ids=[c[0] for c in CASOS_GEOFENCE_030])
def test_geofence_faixa_intermediaria_030(norma, seq, justificativa, esperado, bloqueia):
    evs = [_ev("foto") for _ in seq]
    chks = [_chk("geofence", st, "cur1", ev, **res) for (st, res), ev in zip(seq, evs, strict=True)]
    campos = None
    if justificativa:
        previo = _avaliar(_fis(_op(CUR), chks, evs)).campos["item:cur1:localizacao"]
        campos = {"item:cur1:localizacao": previo.model_copy(update={"justificativa_humana": justificativa})}
    res = _avaliar(_fis(_op(CUR), chks, evs, campos=campos))
    campo = res.campos["item:cur1:localizacao"]
    assert campo.status == esperado, campo.motivo
    assert ("item:cur1:localizacao" in _bloqueados(res)) == bloqueia
    if esperado == "pendente" and seq[-1][1].get("posicao") == "fora":
        assert campo.valor and campo.valor["aceita_justificativa"] and "justificativa" in campo.motivo
        assert "," in campo.motivo or campo.motivo.count(".") <= 1  # números em pt-BR ("404,8 m")


CASOS_CONCLUSAO_VLM = [
    ("MCR-2-7-item16-benfeitorias-conclusao 0.3.0: VLM vê curral no item curral → verificado",
     {"classe": "curral", "concordancia": 1.0}, "ok", "verificado"),
    ("MCR-2-7-item16-benfeitorias-conclusao 0.3.0: VLM vê bovinos no item curral → pendente (não prova a obra)",
     {"classe": "bovinos", "concordancia": 1.0}, "ok", "pendente"),
    ("MCR-2-7-item16-benfeitorias-conclusao 0.3.0: VLM se abstém → pendente",
     {"classe": None, "classe_majoritaria": "curral", "abstencao": True, "concordancia": 0.33}, "indeterminado",
     "pendente"),
]


@pytest.mark.parametrize("norma,resultado,st,esperado", CASOS_CONCLUSAO_VLM, ids=[c[0] for c in CASOS_CONCLUSAO_VLM])
def test_conclusao_pela_classe_da_foto(norma, resultado, st, esperado):
    f = _ev("foto")
    res = _avaliar(_fis(_op(CUR), [_chk("classificar_foto", st, "cur1", f, **resultado)], [f]))
    assert res.campos["item:cur1:conclusao"].status == esperado
