"""Rastreador multiobjeto simples, no espírito do SORT/ByteTrack, sem dependências pesadas.

- Previsão por velocidade constante suavizada (caixa xyxy + velocidade por quadro processado).
- Associação em 3 estágios com o algoritmo húngaro (`scipy.optimize.linear_sum_assignment`):
  1. trilhas ativas × detecções de score alto, por IoU "com buffer" (caixas infladas), que tolera
     o deslocamento grande entre quadros amostrados;
  2. trilhas ainda sem par × detecções de score baixo (ideia do ByteTrack: recupera oclusões);
  3. trilhas tentativas × detecções altas restantes.
- Trilha nasce tentativa; vira confirmada após `min_acertos` associações; morre após
  `max_idade` quadros processados sem associação.
- Como a contagem é offline (depois do vídeo inteiro), `finalizar(estender=True)` estende cada
  trilha para trás e para frente com detecções que sobraram (score baixo, ou de tentativas que
  morreram) ao longo do caminho extrapolado. Isso recupera o trecho em que o animal ainda estava
  longe/de costas com score baixo, que pode ser justamente o lado de antes da linha.

Toda a história (quadro, caixa, score, se foi observada ou só prevista) fica na trilha para a
contagem e para anotar os quadros-chave depois.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from laudo.vision.detector import iou_matriz


def inflar(caixas: np.ndarray, fator: float) -> np.ndarray:
    """Infla caixas xyxy em `fator` da largura/altura de cada lado (IoU com buffer, C-BIoU)."""
    if fator <= 0 or len(caixas) == 0:
        return caixas
    w = (caixas[:, 2] - caixas[:, 0])[:, None] * fator
    h = (caixas[:, 3] - caixas[:, 1])[:, None] * fator
    return caixas + np.hstack([-w, -h, w, h])


@dataclass
class Observacao:
    quadro: int  # índice do quadro processado (0, 1, 2, ...)
    caixa: tuple[float, float, float, float]
    score: float
    classe: int


@dataclass
class Trilha:
    id: int
    caixa: np.ndarray  # xyxy atual (prevista ou observada)
    vel: np.ndarray = field(default_factory=lambda: np.zeros(4, dtype=np.float64))
    acertos: int = 1
    sem_associar: int = 0
    confirmada: bool = False
    obs: list[Observacao] = field(default_factory=list)
    estendidas: int = 0  # observações recuperadas por extensão offline

    @property
    def inicio(self) -> int:
        return self.obs[0].quadro

    @property
    def fim(self) -> int:
        return self.obs[-1].quadro

    @property
    def score_medio(self) -> float:
        return float(np.mean([o.score for o in self.obs])) if self.obs else 0.0

    @property
    def continuidade(self) -> float:
        """Fração dos quadros entre o primeiro e o último em que a trilha foi de fato observada."""
        if not self.obs:
            return 0.0
        return len(self.obs) / (self.fim - self.inicio + 1)

    def centro(self, i: int = -1) -> tuple[float, float]:
        x1, y1, x2, y2 = self.obs[i].caixa
        return (x1 + x2) / 2, (y1 + y2) / 2

    def prever(self) -> None:
        self.caixa = self.caixa + self.vel
        self.sem_associar += 1

    def atualizar(self, caixa: np.ndarray, score: float, classe: int, quadro: int, min_acertos: int) -> None:
        passos = max(1, quadro - self.fim)
        anterior = np.asarray(self.obs[-1].caixa, dtype=np.float64)
        v_nova = (caixa - anterior) / passos
        self.vel = 0.6 * self.vel + 0.4 * v_nova if self.acertos > 1 else v_nova
        self.caixa = caixa.astype(np.float64)
        self.acertos += 1
        self.sem_associar = 0
        self.obs.append(Observacao(quadro, tuple(float(v) for v in caixa), float(score), int(classe)))
        if self.acertos >= min_acertos:
            self.confirmada = True


class Rastreador:
    def __init__(self, limiar_alto: float = 0.5, limiar_baixo: float = 0.2, iou_alto: float = 0.2,
                 iou_baixo: float = 0.4, buffer: float = 0.3, max_idade: int = 8, min_acertos: int = 3,
                 limiar_novo: float | None = None):
        self.limiar_alto = limiar_alto
        self.limiar_baixo = limiar_baixo
        self.iou_alto = iou_alto
        self.iou_baixo = iou_baixo
        self.buffer = buffer
        self.max_idade = max_idade
        self.min_acertos = min_acertos
        self.limiar_novo = limiar_alto if limiar_novo is None else limiar_novo
        self.ativas: list[Trilha] = []
        self.encerradas: list[Trilha] = []
        self._prox_id = 1
        self.quadro = -1
        self.sobras: dict[int, list[np.ndarray]] = {}  # quadro → detecções não usadas (x1..score, classe)

    # ------------------------------------------------------------------
    def _associar(self, trilhas: list[Trilha], dets: np.ndarray, limiar_iou: float, buffer: float):
        if not trilhas or len(dets) == 0:
            return [], list(range(len(trilhas))), list(range(len(dets)))
        prev = np.stack([t.caixa for t in trilhas])
        iou = iou_matriz(inflar(prev, buffer), inflar(dets[:, :4], buffer))
        lin, col = linear_sum_assignment(-iou)
        pares = [(i, j) for i, j in zip(lin, col) if iou[i, j] >= limiar_iou]
        usados_t = {i for i, _ in pares}
        usados_d = {j for _, j in pares}
        return (pares, [i for i in range(len(trilhas)) if i not in usados_t],
                [j for j in range(len(dets)) if j not in usados_d])

    def passo(self, dets: np.ndarray) -> list[Trilha]:
        """Processa as detecções (K, ≥5: x1, y1, x2, y2, score[, classe]) do próximo quadro.

        Devolve as trilhas confirmadas observadas neste quadro.
        """
        self.quadro += 1
        q = self.quadro
        dets = np.asarray(dets, dtype=np.float64)
        if dets.size == 0:
            dets = np.zeros((0, 6))
        elif dets.ndim == 1:
            dets = dets[None]
        if dets.shape[1] < 6:
            dets = np.hstack([dets[:, :5], np.full((len(dets), 1), 19.0)])
        for t in self.ativas:
            t.prever()

        altas = dets[dets[:, 4] >= self.limiar_alto]
        baixas = dets[(dets[:, 4] >= self.limiar_baixo) & (dets[:, 4] < self.limiar_alto)]
        confirmadas = [t for t in self.ativas if t.confirmada]
        tentativas = [t for t in self.ativas if not t.confirmada]

        # 1) confirmadas × altas
        pares, resto_t, resto_d = self._associar(confirmadas, altas, self.iou_alto, self.buffer)
        for i, j in pares:
            confirmadas[i].atualizar(altas[j, :4], altas[j, 4], int(altas[j, 5]), q, self.min_acertos)
        # 2) confirmadas restantes × baixas
        rest_conf = [confirmadas[i] for i in resto_t]
        pares2, _, resto_b = self._associar(rest_conf, baixas, self.iou_baixo, 0.0)
        for i, j in pares2:
            rest_conf[i].atualizar(baixas[j, :4], baixas[j, 4], int(baixas[j, 5]), q, self.min_acertos)
        for j in resto_b:
            self.sobras.setdefault(q, []).append(baixas[j, :6].copy())
        # 3) tentativas × altas restantes
        altas_rest = altas[resto_d]
        pares3, _, resto_d3 = self._associar(tentativas, altas_rest, self.iou_alto, self.buffer)
        for i, j in pares3:
            tentativas[i].atualizar(altas_rest[j, :4], altas_rest[j, 4], int(altas_rest[j, 5]), q,
                                    self.min_acertos)
        # novas trilhas
        for j in resto_d3:
            d = altas_rest[j]
            if d[4] < self.limiar_novo:
                continue
            t = Trilha(id=self._prox_id, caixa=d[:4].copy(), sem_associar=0,
                       obs=[Observacao(q, tuple(float(v) for v in d[:4]), float(d[4]), int(d[5]))])
            t.confirmada = self.min_acertos <= 1
            self._prox_id += 1
            self.ativas.append(t)

        # manutenção: tentativa sem par morre; confirmada morre após max_idade
        vivas = []
        for t in self.ativas:
            if t.sem_associar == 0:
                vivas.append(t)
            elif not t.confirmada:  # descartada; as detecções voltam para as sobras
                for o in t.obs:
                    self.sobras.setdefault(o.quadro, []).append(np.array([*o.caixa, o.score, o.classe]))
                continue
            elif t.sem_associar > self.max_idade:
                self.encerradas.append(t)
            else:
                vivas.append(t)
        self.ativas = vivas
        return [t for t in self.ativas if t.confirmada and t.sem_associar == 0]

    def finalizar(self, estender: bool = True) -> list[Trilha]:
        """Encerra tudo e devolve as trilhas confirmadas, em ordem de id."""
        for t in self.ativas:
            if t.confirmada:
                self.encerradas.append(t)
            else:
                for o in t.obs:
                    self.sobras.setdefault(o.quadro, []).append(np.array([*o.caixa, o.score, o.classe]))
        self.ativas = []
        trilhas = sorted((t for t in self.encerradas if t.confirmada), key=lambda t: t.id)
        if estender:
            for t in sorted(trilhas, key=lambda t: -t.score_medio):
                self._estender(t, -1)
                self._estender(t, +1)
        return trilhas

    def _estender(self, t: Trilha, sentido: int, iou_min: float = 0.3) -> None:
        """Prolonga a trilha no tempo (sentido −1 = para trás) com as sobras, pelo caminho extrapolado."""
        k = min(4, len(t.obs) - 1)
        if k < 1:
            return
        ref = t.obs[0] if sentido < 0 else t.obs[-1]
        par = t.obs[k] if sentido < 0 else t.obs[-1 - k]
        dq = abs(ref.quadro - par.quadro) or 1
        v = (np.asarray(ref.caixa) - np.asarray(par.caixa)) / dq  # deslocamento por quadro, no sentido
        caixa = np.asarray(ref.caixa, dtype=np.float64)
        q, falhas, novas = ref.quadro, 0, []
        while falhas <= self.max_idade:
            q += sentido
            if q < 0 or q > self.quadro:
                break
            caixa = caixa + v
            cands = self.sobras.get(q)
            if not cands:
                falhas += 1
                continue
            arr = np.stack(cands)
            iou = iou_matriz(inflar(caixa[None], self.buffer), inflar(arr[:, :4], self.buffer))[0]
            j = int(np.argmax(iou))
            if iou[j] < iou_min:
                falhas += 1
                continue
            d = cands.pop(j)
            novas.append(Observacao(q, tuple(float(x) for x in d[:4]), float(d[4]), int(d[5])))
            caixa = d[:4].astype(np.float64)
            falhas = 0
        if novas:
            t.obs = sorted(t.obs + novas, key=lambda o: o.quadro)
            t.estendidas += len(novas)
