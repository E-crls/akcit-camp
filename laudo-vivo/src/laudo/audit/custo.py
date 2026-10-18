"""Custo por fiscalização medido no trace.

O que é **medido** (do trace OpenTelemetry JSONL de cada fiscalização, `audit/otel.py`):
- por chamada ao LLM (`gen_ai.*`): tokens de prompt e de geração devolvidos pelo Ollama (`prompt_eval_count`,
  `eval_count`), latência, tempo de carga e tempos de GPU (`prompt_eval_duration`, `eval_duration`).
  No replay, os mesmos números vêm da gravação original (`llm.uso_origem = "gravacao"`);
- por ferramenta (`tool <nome>`): número de chamadas e tempo de parede (ex.: a contagem do vídeo em CPU).

O que é **estimado**, com os parâmetros à vista no relatório:
- equivalente em nuvem = tokens medidos × preço público por milhão de tokens (tabela `PRECOS`, com fonte
  e data da consulta) × câmbio (PTAX);
- energia local = (tempo de LLM × potência da GPU + tempo de ferramentas × potência da CPU) × tarifa. As
  potências são o teto nominal das peças da máquina da demo, não medição de tomada.

Não entra aqui: revisão humana, armazenamento e deslocamento (ver `negocio/plano_de_negocio.md`).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONSULTA = "2026-10-08"


@dataclass(frozen=True)
class Preco:
    provedor: str
    modelo: str
    entrada_usd_mtok: float  # US$ por 1 milhão de tokens de entrada (sem cache)
    saida_usd_mtok: float  # US$ por 1 milhão de tokens de saída
    fonte: str


_OPENAI = "https://developers.openai.com/api/docs/pricing (tier padrão; consultado em " + CONSULTA + ")"
_GOOGLE = (
    "https://ai.google.dev/gemini-api/docs/pricing (tier pago; página de 2026-10-07; consultado em "
    + CONSULTA
    + ")"
)

# Modelos pequenos de nuvem comparáveis ao papel do qwen3.5:4b (conduzir a conversa e escolher ferramentas).
PRECOS: tuple[Preco, ...] = (
    Preco("OpenAI", "gpt-5-nano", 0.05, 0.40, _OPENAI),
    Preco("OpenAI", "gpt-5-mini", 0.25, 2.00, _OPENAI),
    Preco("OpenAI", "gpt-4.1-mini", 0.40, 1.60, _OPENAI),
    Preco("Google", "gemini-2.5-flash-lite", 0.10, 0.40, _GOOGLE),
    Preco("Google", "gemini-2.5-flash", 0.30, 2.50, _GOOGLE),
    Preco("Google", "gemini-3.5-flash-lite", 0.30, 2.50, _GOOGLE),
)

CAMBIO_PADRAO = 4.9935  # PTAX venda de 07/10/2026 (BCB, API Olinda CotacaoDolarDia)
FONTE_CAMBIO = "PTAX venda 07/10/2026, Banco Central (olinda.bcb.gov.br, CotacaoDolarDia)"
POTENCIA_GPU_W = 300.0  # TDP nominal da RTX 5070 Ti (teto; a GPU é dividida com outros processos)
POTENCIA_CPU_W = 120.0  # TDP nominal do Ryzen 9 9950X3D (teto)
TARIFA_KWH_RS = 1.00  # ordem de grandeza da tarifa residencial com impostos; ajuste para a distribuidora


@dataclass
class UsoFiscalizacao:
    fiscalizacao_id: str
    turnos: int = 0
    chamadas_llm: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    llm_ms: int = 0  # latência de parede das chamadas (inclui carga)
    gpu_ms: int = 0  # prompt_eval + eval do Ollama (0 em gravações antigas)
    carga_ms: int = 0
    modelos: set[str] = field(default_factory=set)
    origem_uso: set[str] = field(default_factory=set)  # medido | gravacao
    ferramentas: dict[str, list[int]] = field(default_factory=dict)  # nome → [chamadas, ms]

    @property
    def ferramentas_ms(self) -> int:
        return sum(ms for _, ms in self.ferramentas.values())

    def como_dict(self) -> dict[str, Any]:
        return {
            "fiscalizacao_id": self.fiscalizacao_id,
            "turnos": self.turnos,
            "chamadas_llm": self.chamadas_llm,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "llm_ms": self.llm_ms,
            "gpu_ms": self.gpu_ms,
            "carga_ms": self.carga_ms,
            "modelos": sorted(self.modelos),
            "origem_uso": sorted(self.origem_uso),
            "ferramentas": {k: {"chamadas": v[0], "ms": v[1]} for k, v in sorted(self.ferramentas.items())},
            "ferramentas_ms": self.ferramentas_ms,
        }


def ler_spans(caminhos: Iterable[Path]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for c in caminhos:
        with open(c, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if linha:
                    try:
                        spans.append(json.loads(linha))
                    except json.JSONDecodeError:
                        continue
    return spans


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def somar(spans: Iterable[dict[str, Any]]) -> dict[str, UsoFiscalizacao]:
    """Soma o uso por fiscalização (`laudo.fiscalizacao_id` de cada span)."""
    por_fis: dict[str, UsoFiscalizacao] = {}
    for s in spans:
        a = s.get("attributes") or {}
        fis = str(a.get("laudo.fiscalizacao_id") or "geral")
        u = por_fis.setdefault(fis, UsoFiscalizacao(fis))
        nome = str(s.get("name") or "")
        if nome == "agente.turno":
            u.turnos += 1
        elif nome.startswith("gen_ai.") or "gen_ai.operation.name" in a:
            u.chamadas_llm += 1
            u.tokens_entrada += _int(a.get("gen_ai.usage.input_tokens"))
            u.tokens_saida += _int(a.get("gen_ai.usage.output_tokens"))
            u.llm_ms += _int(a.get("llm.latency_ms")) or _int(s.get("duration_ms"))
            u.gpu_ms += _int(a.get("llm.prompt_eval_ms")) + _int(a.get("llm.eval_ms"))
            u.carga_ms += _int(a.get("llm.load_ms"))
            modelo = a.get("gen_ai.response.model") or a.get("gen_ai.request.model")
            if modelo:
                u.modelos.add(str(modelo))
            if a.get("llm.uso_origem"):
                u.origem_uso.add(str(a["llm.uso_origem"]))
            elif a.get("llm.replay"):
                u.origem_uso.add("gravacao")
        elif nome.startswith("tool ") or "tool.name" in a:
            ferr = str(a.get("tool.name") or nome.removeprefix("tool "))
            par = u.ferramentas.setdefault(ferr, [0, 0])
            par[0] += 1
            par[1] += _int(s.get("duration_ms"))
    return por_fis


def estimar(
    u: UsoFiscalizacao,
    cambio: float = CAMBIO_PADRAO,
    potencia_gpu_w: float = POTENCIA_GPU_W,
    potencia_cpu_w: float = POTENCIA_CPU_W,
    tarifa_kwh_rs: float = TARIFA_KWH_RS,
    precos: Iterable[Preco] = PRECOS,
) -> dict[str, Any]:
    """Equivalente em nuvem (tokens medidos × preço público) e energia local, em R$ por fiscalização."""
    nuvem = []
    for p in precos:
        usd = u.tokens_entrada / 1e6 * p.entrada_usd_mtok + u.tokens_saida / 1e6 * p.saida_usd_mtok
        nuvem.append(
            {
                "provedor": p.provedor,
                "modelo": p.modelo,
                "usd": round(usd, 5),
                "rs": round(usd * cambio, 4),
                "entrada_usd_mtok": p.entrada_usd_mtok,
                "saida_usd_mtok": p.saida_usd_mtok,
                "fonte": p.fonte,
            }
        )
    tempo_gpu_s = (u.gpu_ms or u.llm_ms) / 1000
    kwh = (tempo_gpu_s * potencia_gpu_w + u.ferramentas_ms / 1000 * potencia_cpu_w) / 3600 / 1000
    return {
        "uso": u.como_dict(),
        "nuvem_equivalente": nuvem,
        "energia_local": {
            "kwh": round(kwh, 6),
            "rs": round(kwh * tarifa_kwh_rs, 5),
            "tempo_gpu_s": round(tempo_gpu_s, 1),
            "tempo_gpu_fonte": "prompt_eval+eval do Ollama"
            if u.gpu_ms
            else "latência de parede do LLM (teto)",
            "tempo_ferramentas_s": round(u.ferramentas_ms / 1000, 1),
        },
        "parametros": {
            "cambio_usd_brl": cambio,
            "fonte_cambio": FONTE_CAMBIO if cambio == CAMBIO_PADRAO else "informado",
            "potencia_gpu_w": potencia_gpu_w,
            "potencia_cpu_w": potencia_cpu_w,
            "tarifa_kwh_rs": tarifa_kwh_rs,
        },
    }


def _br(v: float, casas: int = 2) -> str:
    """Número no formato brasileiro (1.234,56)."""
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def relatorio_md(est: dict[str, Any]) -> str:
    u, e, p = est["uso"], est["energia_local"], est["parametros"]
    ferr = (
        ", ".join(f"{k} {v['chamadas']}× {_br(v['ms'] / 1000, 1)} s" for k, v in u["ferramentas"].items())
        or "—"
    )
    linhas = [
        f"## Custo da fiscalização `{u['fiscalizacao_id']}`",
        "",
        (
            f"- Turnos: {u['turnos']}; chamadas ao LLM: {u['chamadas_llm']} "
            f"({', '.join(u['modelos']) or '—'}; "
            f"uso {', '.join(u['origem_uso']) or 'sem tokens no trace'})"
        ),
        (
            f"- Tokens medidos: **{_br(u['tokens_entrada'], 0)} de entrada** e "
            f"**{_br(u['tokens_saida'], 0)} de saída**"
        ),
        (
            f"- Tempo de LLM: {_br(u['llm_ms'] / 1000, 1)} s de parede; "
            f"GPU (prompt + geração): {_br(u['gpu_ms'] / 1000, 1)} s"
        ),
        f"- Ferramentas: {ferr}",
        "",
        "| Equivalente em nuvem (mesmos tokens) | US$ entrada/saída por 1M | Custo (R$) |",
        "|---|---|---|",
    ]
    for n in est["nuvem_equivalente"]:
        linhas.append(
            f"| {n['provedor']} {n['modelo']} | {_br(n['entrada_usd_mtok'])} / {_br(n['saida_usd_mtok'])} | "
            f"{_br(n['rs'], 4)} |"
        )
    linhas += [
        "",
        (
            f"Energia local estimada: {_br(e['kwh'] * 1000)} Wh ≈ R$ {_br(e['rs'], 4)} "
            f"(GPU {_br(e['tempo_gpu_s'], 1)} s × {p['potencia_gpu_w']:.0f} W, {e['tempo_gpu_fonte']}; "
            f"ferramentas {_br(e['tempo_ferramentas_s'], 1)} s × {p['potencia_cpu_w']:.0f} W; "
            f"tarifa R$ {_br(p['tarifa_kwh_rs'])}/kWh)."
        ),
        f"Câmbio: R$ {_br(p['cambio_usd_brl'], 4)} por US$ ({p['fonte_cambio']}). Preços: "
        + "; ".join(sorted({n["fonte"] for n in est["nuvem_equivalente"]}))
        + ".",
        (
            "Tokens e tempos são medidos no trace; preço de nuvem, energia e câmbio são estimativas com os "
            "parâmetros acima. Revisão humana, armazenamento e deslocamento não entram nesta conta."
        ),
    ]
    return "\n".join(linhas)
