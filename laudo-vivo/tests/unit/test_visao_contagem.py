"""Rastreador e contagem com detecções sintéticas (sem vídeo nem modelo)."""

from __future__ import annotations

import numpy as np

from laudo.vision.contagem import (
    ParametrosContagem,
    avaliar,
    contar_ids,
    contar_linha,
    costurar,
    linha_automatica,
)
from laudo.vision.rastreador import Rastreador

L, A = 640, 360  # quadro sintético


def _caixa(cx: float, cy: float, w: float = 60, h: float = 40, s: float = 0.9) -> list[float]:
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, s, 19]


def _rodar(quadros: list[list[list[float]]], gap_costura: int = 16, **kw) -> tuple[Rastreador, list]:
    """Roda o rastreador e devolve as cadeias (trilhas costuradas, gap de até 2 s a 8 fps)."""
    r = Rastreador(**kw)
    for dets in quadros:
        r.passo(np.array(dets, dtype=np.float64).reshape(-1, 6))
    return r, costurar(r.finalizar(), gap_costura)


def _fila(n: int, passo_px: float = 25, espaco: int = 8, n_quadros: int | None = None, y: float = 180,
          falhas: set[tuple[int, int]] | None = None, s: float = 0.9) -> list[list[list[float]]]:
    """n animais entrando pela esquerda, um a cada `espaco` quadros, andando `passo_px` por quadro."""
    n_quadros = n_quadros or (n * espaco + int(L / passo_px) + 10)
    out = []
    for q in range(n_quadros):
        dets = []
        for k in range(n):
            x = -30 + (q - k * espaco) * passo_px
            if 0 < x < L and (q, k) not in (falhas or set()):
                dets.append(_caixa(x, y + (k % 2) * 30, s=s))
        out.append(dets)
    return out


def test_ids_estaveis_em_fila():
    r, cadeias = _rodar(_fila(4))
    assert len(cadeias) == 4 and all(c.n_costuras == 0 for c in cadeias)
    assert len(r.encerradas) == 4
    assert all(c.continuidade == 1.0 for c in cadeias)


def test_contagem_por_linha_em_fila():
    quadros = _fila(5)
    r, trilhas = _rodar(quadros)
    linha, eixo, mov = linha_automatica(trilhas, L, A)
    assert eixo == "horizontal" and mov
    res = contar_linha(trilhas, linha, L, A, len(quadros) - 1, r.max_idade, ParametrosContagem())
    assert res.contagem == 5 and res.intervalo == (5, 5)
    assert res.detalhes["sentido"] == "a_para_b"
    assert [c["acumulado"] for c in res.eventos] == [1, 2, 3, 4, 5]


def test_animal_que_volta_nao_conta_duas_vezes():
    # vai até depois da linha, volta e cruza de novo para a direita: conta 1 (líquido por trilha)
    xs = list(range(100, 500, 30)) + list(range(500, 200, -30)) + list(range(200, 600, 30))
    quadros = [[_caixa(x, 180)] for x in xs]
    r, trilhas = _rodar(quadros)
    res = contar_linha(trilhas, (L / 2, 0, L / 2, A), L, A, len(quadros) - 1, r.max_idade,
                       ParametrosContagem())
    assert res.contagem == 1


def test_sentido_contrario_desconta():
    ida = _fila(3)
    volta = [[[L - d[2], d[1], L - d[0], d[3], d[4], d[5]] for d in dets] for dets in _fila(1)]
    quadros = ida + volta
    r, trilhas = _rodar(quadros)
    res = contar_linha(trilhas, (L / 2, 0, L / 2, A), L, A, len(quadros) - 1, r.max_idade,
                       ParametrosContagem(sentido="a_para_b"))
    assert res.detalhes["cruzamentos_a_para_b"] == 3 and res.detalhes["cruzamentos_b_para_a"] == 1
    assert res.contagem == 2


def test_oclusao_na_linha_vira_costura_e_alarga_intervalo():
    # o animal 0 some por 12 quadros bem em cima da linha (> max_idade): duas trilhas, uma cadeia
    falhas = {(q, 0) for q in range(8, 20)}
    quadros = _fila(2, passo_px=25, espaco=30, falhas=falhas)
    r, cadeias = _rodar(quadros, max_idade=4)
    assert len(r.encerradas) == 3 and len(cadeias) == 2
    res = contar_linha(cadeias, (L / 2, 0, L / 2, A), L, A, len(quadros) - 1, r.max_idade,
                       ParametrosContagem())
    assert res.contagem == 2
    assert res.detalhes["cruzamentos_na_costura"] == 1
    assert res.intervalo == (1, 2)  # o cruzamento que caiu na costura é fraco


def test_sem_costura_a_oclusao_perderia_o_animal():
    falhas = {(q, 0) for q in range(8, 20)}
    quadros = _fila(2, passo_px=25, espaco=30, falhas=falhas)
    r, cadeias = _rodar(quadros, gap_costura=1, max_idade=4)
    res = contar_linha(cadeias, (L / 2, 0, L / 2, A), L, A, len(quadros) - 1, r.max_idade,
                       ParametrosContagem(zona_interrupcao_rel=0.4))
    assert res.contagem == 1 and res.intervalo[1] >= 2  # o teto ainda cobre o animal perdido


def test_ids_unicos_lote_parado():
    # 6 animais parados, detector falha às vezes; 40 quadros a 8 fps (5 s)
    rng = np.random.default_rng(0)
    pos = [(80 + 90 * k, 120 + 60 * (k % 3)) for k in range(6)]
    quadros = [[_caixa(x + rng.normal(0, 2), y + rng.normal(0, 2)) for (x, y) in pos if rng.random() > 0.1]
               for _ in range(40)]
    _, trilhas = _rodar(quadros)
    res = contar_ids(trilhas, 8.0, ParametrosContagem(modo="ids_unicos"))
    assert res.contagem == 6
    assert res.detalhes["max_simultaneo"] == 6
    assert res.intervalo[0] == 6


def test_fragmento_costurado_e_intervalo():
    # mesmo animal some 20 quadros (> max_idade) e reaparece no mesmo lugar → 2 trilhas, 1 fragmento
    quadros = [[_caixa(300, 180)] for _ in range(20)] + [[] for _ in range(14)] + \
              [[_caixa(305, 182)] for _ in range(20)]
    _, cadeias = _rodar(quadros, max_idade=8)
    res = contar_ids(cadeias, 8.0, ParametrosContagem(modo="ids_unicos"))
    assert res.contagem == 1 and res.intervalo == (1, 2)  # costurado; se a costura errou, eram 2
    _, sem = _rodar(quadros, gap_costura=1, max_idade=8)
    res2 = contar_ids(sem, 8.0, ParametrosContagem(modo="ids_unicos"))
    assert res2.contagem == 2 and res2.intervalo == (1, 2)  # fragmento provável baixa o piso


def test_abstencao_por_confianca_baixa_e_sem_cruzamento():
    quadros = _fila(3, s=0.42)
    r, trilhas = _rodar(quadros, limiar_alto=0.4)
    res = contar_linha(trilhas, (L / 2, 0, L / 2, A), L, A, len(quadros) - 1, r.max_idade,
                       ParametrosContagem())
    status, abst, _conf, _cob = avaliar(res, trilhas, ParametrosContagem(), frac_quadros_ruins=0, oclusao=0,
                                      frac_outra_classe=0, truncado=False, houve_movimento=True,
                                      duracao_s=10)
    assert abst and status == "indeterminado"
    assert any(m.codigo == "CONF_BAIXA" for m in res.motivos)

    parados = [[_caixa(100, 100), _caixa(400, 200)] for _ in range(30)]
    r2, tr2 = _rodar(parados)
    linha, _, mov = linha_automatica(tr2, L, A)
    res2 = contar_linha(tr2, linha, L, A, 29, r2.max_idade, ParametrosContagem())
    _, abst2, _, _ = avaliar(res2, tr2, ParametrosContagem(), frac_quadros_ruins=0, oclusao=0,
                             frac_outra_classe=0, truncado=False, houve_movimento=mov, duracao_s=4)
    assert abst2 and any(m.codigo == "SEM_CRUZAMENTO" and "ids_unicos" in m.msg for m in res2.motivos)


def test_sem_deteccao_abstem():
    _, trilhas = _rodar([[] for _ in range(10)])
    res = contar_ids(trilhas, 8.0, ParametrosContagem(modo="ids_unicos"))
    _, abst, _, _ = avaliar(res, trilhas, ParametrosContagem(), frac_quadros_ruins=0, oclusao=0,
                                 frac_outra_classe=0, truncado=False, houve_movimento=None, duracao_s=2)
    assert res.contagem == 0 and abst and res.motivos[0].codigo == "SEM_BOVINOS"


def test_ruido_de_um_quadro_nao_vira_trilha():
    quadros = [[_caixa(100 + 7 * q, 100)] for q in range(20)]
    quadros[5].append(_caixa(500, 300))  # falso positivo isolado
    _, trilhas = _rodar(quadros)
    assert len(trilhas) == 1


def test_extensao_offline_recupera_trecho_de_score_baixo():
    # animal com score 0,3 (abaixo do limiar alto) até passar da linha, depois 0,9: sem extensão a
    # trilha nasceria do outro lado e o cruzamento se perderia
    quadros = [[_caixa(40 + 25 * q, 180, s=0.3 if q < 14 else 0.9)] for q in range(30)]
    r = Rastreador()
    for d in quadros:
        r.passo(np.array(d, dtype=np.float64).reshape(-1, 6))
    sem = costurar(Rastreador.finalizar(r, estender=False), 16)
    assert sem[0].inicio == 14
    r2 = Rastreador()
    for d in quadros:
        r2.passo(np.array(d, dtype=np.float64).reshape(-1, 6))
    com = costurar(r2.finalizar(), 16)
    assert com[0].inicio == 0 and com[0].trilhas[0].estendidas == 14
    res = contar_linha(com, (L / 2, 0, L / 2, A), L, A, 29, r2.max_idade, ParametrosContagem())
    assert res.contagem == 1


def test_oclusao_sobe_so_o_teto():
    from laudo.vision.contagem import ResultadoContagem, alargar_por_oclusao

    res = ResultadoContagem(modo="linha", contagem=12, intervalo=(11, 13))
    alargar_por_oclusao(res, 0.5, ParametrosContagem())
    assert res.intervalo == (11, 16) and res.detalhes["acrescimo_teto_oclusao"] == 3
    zero = ResultadoContagem(modo="linha", contagem=0, intervalo=(0, 1))
    alargar_por_oclusao(zero, 0.9, ParametrosContagem())
    assert zero.intervalo == (0, 1)
