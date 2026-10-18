"""Política default-deny (POL-00..08) adaptada à fiscalização do crédito rural (MCR 2-7).

Regras estreitas e determinísticas: o LLM não decide se algo é permitido. Cada decisão gera um span
`policy.decision` com `policy.rule_id`.

- POL-00 (bloqueio): ação fora da allowlist do estado da FSM, ou inexistente, é negada (default-deny);
  ferramenta do plano determinístico (`fsm.FERRAMENTAS_DO_PLANO`) pedida pelo LLM também. Argumentos que o
  LLM manda fora do esquema que ele recebe (caminho, GPS, item, leitura...) são descartados pelo condutor.
- POL-01 (bloqueio): rascunho só sem `bloqueios` do rulebook (`avaliar_regras`, modelo `Bloqueio`): nada
  "pendente", abstenção só com justificativa humana, metadados do sensoriamento remoto (MCR 2-7-4-b) quando
  houver. Sem `avaliar_regras` no registro, valem os bloqueios da regra provisória do verificador.
- POL-02 (bloqueio): nenhum "divergente" sem justificativa humana: trecho literal da fala do fiscal, que
  menciona o campo, não é pergunta e não contém pedido de alterar valor (pressão forte ou incerta). A
  justificativa nunca muda número nem status: só acompanha a divergência no laudo.
- POL-03 (bloqueio): o agente nunca assina; assinatura é ação humana com confirmação do hash. Emitir o
  rascunho e enviar para assinatura também são ações humanas (comando explícito reconhecido sem LLM ou botão
  da interface): o LLM não as recebe e, se tentar, é negado.
- POL-04 (bloqueio): evidência registrada é imutável; fiscalização selada não muda; correção é evidência nova.
- POL-05 (bloqueio): número sem lastro no estado bloqueia o texto (fala ou laudo cai no template).
- POL-06 (bloqueio): texto de OCR/ASR/documento é dado, nunca instrução; tentativa vira ocorrência "injecao".
- POL-07 (registro): pedido de alterar valor sem nova evidência. Pressão `forte` (verbo de alteração + valor
  ou status, dispensa da divergência, aprovação a pedido) vira ocorrência "pressao"; pressão `incerta` (sinal
  sem alvo, contexto ambíguo) só pede esclarecimento e não grava nada na cadeia (`intencao.py`). O valor nunca
  muda.
- POL-08 (transformação): CPF, CNPJ, telefone, e-mail (e nomes após gatilho) mascarados em logs, traces e
  gravações.
- POL-09 (transformação): fala do LLM com afirmação semanticamente inconsistente com o estado (falta × excesso,
  dentro × fora, status trocado, consequência sobre o crédito, ilícito, juízo sobre o pasto, ação afirmada que
  não aconteceu no turno nem está no estado) é trocada pelo template; frases que afirmam resultado saem da fala
  do LLM (o fato vem do template, `fatos.py`).

Não bloquear (anti-over-blocking): perguntas do domínio, foto legível imperfeita (vira alerta, não bloqueio),
o fiscal discordar de uma checagem com justificativa (o humano manda), menção a banco, gerente ou cooperativa
sem pedido de alterar valor ("o banco pediu as fotos").
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from laudo.agent import declaracoes as decl
from laudo.agent import fatos, fsm, intencao
from laudo.agent.verificador import ResultadoVerificacao, Verificador, campo_justificavel, grounding
from laudo.audit import hashchain, otel
from laudo.contracts import Fiscalizacao

POL_FSM = "POL-00"
REGRA_AGREGACAO = "OP-agregacao-item"  # status do item = pior dos seus campos (não recebe justificativa)
# "humano": botão da interface ou ação direta; "comando": fala explícita do fiscal reconhecida sem LLM.
ORIGENS_HUMANAS = frozenset({"humano", "comando"})


class Decisao(BaseModel):
    permitido: bool
    rule_id: str
    acao: str
    motivo: str = ""
    pendencias: list[dict[str, Any]] = Field(default_factory=list)
    ocorrencia: str | None = None  # tipo de ocorrência a registrar ("pressao", "injecao")
    esclarecer: str | None = None  # pressão incerta: pergunta ao fiscal (nada vai para a cadeia)
    span_id: str = ""


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Detectores (texto normalizado: minúsculas, sem acento)
# ---------------------------------------------------------------------------

# Pressão (POL-07): classificador com grau (forte/incerta) em `intencao.classificar_pressao`. Uma lista simples
# de regex dispararia em frases legítimas ("o banco pediu as fotos") e gravaria "pressão" na cadeia imutável.
# Pedido para o *agente* assinar. "Manda para eu assinar" / "minha assinatura" não é pedido
# (anti-over-blocking).
ASSINATURA = [
    re.compile(r"\bassin\w*\s+(?:por|pra|para|no lugar d)\w*\s+(?:mim|ele|ela|o fiscal|o agronomo|nos)\b"),
    re.compile(r"\b(?:voce|vc|o agente|a ia)\b[^.?!]{0,15}\b(?:assin|sel[ae])\w*"),
    re.compile(r"\b(?:pode|consegue|tem como|favor)\s+(?:assinar|selar|assina|sela)\b"),
    re.compile(r"\b(?:assina|assine|sela|sele)\s+(?:o laudo|ai|logo|isso|pra mim|por mim)\b"),
]
INJECAO_FALA = [
    re.compile(
        r"\b(?:ignore|ignora|ignorar|desconsidere|desconsidera|esqueca|esquece)\b[^.?!]{0,30}"
        r"\b(?:regras?|instruc\w+|politicas?|restric\w+|tudo)"
    ),
    re.compile(r"\bmodo (?:administrador|admin|desenvolvedor|dev|debug|deus|root|irrestrito)\b"),
    re.compile(r"\b(?:voce agora e|finja que|aja como|a partir de agora voce)\b"),
    re.compile(r"(?:^|\s)(?:system|sistema|assistant|assistente)\s*:"),
    re.compile(r"\b(?:prompt|instrucoes) (?:do sistema|de sistema|internas?)\b"),
]
# Em dado (OCR, documento, transcrição de terceiros) qualquer ordem dirigida ao agente é injeção.
INJECAO_DADO = INJECAO_FALA + [
    re.compile(
        r"\b(?:aprove|aprova|conclua|conclui|emita|emite|libere|libera|assine|assina)\b[^.?!]{0,20}"
        r"\b(?:laudo|fiscalizacao|item|tudo|rascunho)\b"
    ),
    re.compile(r"\b(?:marque|marca|considere|considera)\b[^.?!]{0,30}\b(?:verificad\w*|conforme|ok)\b"),
    re.compile(
        r"\b(?:agente|assistente|ia|inteligencia artificial|modelo)\b[^.?!]{0,15}\b(?:deve|precisa|"
        r"tem que)\b"
    ),
]


def detectar(padroes: list[re.Pattern], texto: str) -> str | None:
    t = _norm(texto)
    for p in padroes:
        m = p.search(t)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------


class Politica:
    def __init__(self, verificador: Verificador | None = None, registro: dict | None = None):
        self.verificador = verificador or Verificador()
        self.registro = self.verificador.registro if registro is None else registro

    @staticmethod
    def _decidir(permitido: bool, rule_id: str, acao: str, motivo: str = "", **kw: Any) -> Decisao:
        forcado = kw.pop("resultado", None)
        d = Decisao(permitido=permitido, rule_id=rule_id, acao=acao, motivo=motivo, **kw)
        resultado = "permitir" if permitido else "negar"
        if d.ocorrencia:
            resultado += "+registrar_ocorrencia"
        if d.esclarecer:
            resultado = "esclarecer"
        resultado = forcado or resultado
        d.span_id = otel.registrar_decisao(
            rule_id, resultado, acao, motivo, **{"policy.n_pendencias": len(d.pendencias)}
        )
        return d

    # -- ações propostas (LLM, API ou humano) ---------------------------------
    def autorizar(
        self,
        acao: str,
        fis: Fiscalizacao,
        argumentos: dict[str, Any] | None = None,
        origem: str = "llm",
        fala_atual: str = "",
    ) -> Decisao:
        args = argumentos or {}
        etapa = fsm.etapa(fis)
        if etapa == fsm.Etapa.SELADO:
            return self._decidir(
                False,
                "POL-04",
                acao,
                "fiscalização selada: nada pode ser alterado; correção vira nova fiscalização",
            )
        if acao in fsm.ACOES_HUMANAS and origem != "humano":
            return self._decidir(
                False,
                "POL-03",
                acao,
                "o agente nunca assina nem aprova; a assinatura é ação humana com confirmação do hash",
            )
        if acao in fsm.ACOES_POR_COMANDO_HUMANO and origem not in ORIGENS_HUMANAS:
            return self._decidir(
                False,
                "POL-03",
                acao,
                f"{acao} é ação humana: só por comando explícito do fiscal ou pelo botão da interface",
            )
        existe = acao in fsm.ACOES_INTERNAS or acao in self.registro
        if not existe:
            return self._decidir(False, POL_FSM, acao, f"ação desconhecida {acao!r} (default-deny)")
        if acao not in fsm.acoes_permitidas(etapa):
            return self._decidir(False, POL_FSM, acao, f"{acao} não é permitida na etapa {etapa}")
        if acao in fsm.FERRAMENTAS_DO_PLANO and origem == "llm":
            # Leitura de documento, completação do residual, classificação da foto e alegações ×
            # checagens são do plano determinístico (o LLM não as recebe); vindas do LLM, com argumentos dele,
            # são negadas
            return self._decidir(
                False, POL_FSM, acao, f"{acao} é do plano determinístico do condutor; o LLM não a dispara"
            )
        if acao == "registrar_justificativa":
            return self._justificativa(fis, args, fala_atual)
        if acao == "registrar_conclusao_obra":
            return self._conclusao_obra(fis, args, fala_atual)
        if acao == "avancar_etapa":
            return self._avancar(fis, args)
        if acao == "solicitar_assinatura":
            pend = self.pendencias_emissao(fis)
            if not any(e.meta.get("laudo") for e in fis.evidencias):
                pend.append({"regra_id": "POL-01", "falta": "rascunho do laudo emitido"})
            if pend:
                return self._decidir(
                    False, "POL-01", acao, "rascunho ausente ou com pendências", pendencias=pend
                )
        return self._decidir(True, POL_FSM, acao, f"permitida na etapa {etapa}")

    def _justificativa(self, fis: Fiscalizacao, args: dict[str, Any], fala_atual: str) -> Decisao:
        campo = str(args.get("campo") or "")
        trecho = str(args.get("trecho") or args.get("justificativa") or "")
        if campo not in fis.campos:
            return self._decidir(False, "POL-02", "registrar_justificativa", f"campo inexistente: {campo!r}")
        if not campo_justificavel(fis.campos[campo]):
            return self._decidir(
                False,
                "POL-02",
                "registrar_justificativa",
                f"{campo} está {fis.campos[campo].status}: justificativa só vale para campo divergente ou em "
                "abstenção (ou pendente que a regra deixa justificar: foto fora da gleba entre 100 e 1000 m)",
            )
        if len(_norm(trecho)) < 15 or _norm(trecho) not in _norm(fala_atual):
            return self._decidir(
                False,
                "POL-02",
                "registrar_justificativa",
                "a justificativa precisa ser trecho literal (uma frase inteira, não um resumo) da fala do fiscal "
                "neste turno; o agente não redige justificativa",
            )
        # Pedido de alterar valor (mesmo parafraseado) não é justificativa: "o certo é quarenta, bota o número
        # do projeto" pede outro valor em vez de explicar a divergência (RT-PRE-07).
        if p := intencao.classificar_pressao(fala_atual):
            return self._decidir(
                False,
                "POL-02",
                "registrar_justificativa",
                f"a fala pede para alterar valor ou status ('{p.trecho}'): não é justificativa; o valor só "
                "muda com nova evidência",
            )
        contexto = decl.contexto_do_trecho(fala_atual, trecho)
        if decl.eh_pergunta(contexto) or not decl.cita_campo(contexto, campo):
            return self._decidir(
                False,
                "POL-02",
                "registrar_justificativa",
                f"o trecho não é declaração reconhecida sobre {campo} (pergunta, ou não fala do assunto do "
                "campo); o fiscal justifica com as próprias palavras",
            )
        return self._decidir(True, "POL-02", "registrar_justificativa", f"justificativa humana para {campo}")

    def _conclusao_obra(self, fis: Fiscalizacao, args: dict[str, Any], fala_atual: str) -> Decisao:
        """Atestação de conclusão da obra (MCR 2-7-16-a): só com trecho literal da fala do fiscal (POL-02)."""
        item_id = str(args.get("item_id") or "")
        trecho = str(args.get("trecho") or "")
        item = next((i for i in fis.operacao.itens if i.id == item_id), None)
        if item is None or item.tipo not in ("cerca", "curral", "galpao", "benfeitoria"):
            return self._decidir(
                False, "POL-02", "registrar_conclusao_obra", f"item de benfeitoria inexistente: {item_id!r}"
            )
        if len(_norm(trecho)) < 10 or _norm(trecho) not in _norm(fala_atual):
            return self._decidir(
                False,
                "POL-02",
                "registrar_conclusao_obra",
                "a declaração precisa ser trecho literal (uma frase inteira) da fala do fiscal neste turno; "
                "o agente não atesta obra",
            )
        # O status que a checagem vai gravar (o da parte própria do trecho) tem de ser o que o próprio fiscal
        # atesta sobre este item na frase inteira em que o trecho foi dito. Vale também para o trecho que o LLM
        # recorta: "a cerca está concluída", tirado de "o produtor disse que a cerca está concluída", é negado.
        # A retirada ("me enganei, ela não está pronta") substitui a declaração anterior e pode não citar a obra pelo
        # nome; só o "ok" exige o item citado na frase.
        status = decl.status_conclusao(decl.atestacao_propria(trecho))
        contexto = decl.conclusao_no_contexto(fala_atual, trecho, fis).get(item_id) if status != "indeterminado" else None
        if decl.eh_retirada(trecho):
            sem_lastro = status == "ok" and contexto != "ok"
        elif status != "indeterminado":
            sem_lastro = contexto != status
        else:  # relato inteiro: o status só aparece fora da parte própria
            sem_lastro = decl.status_conclusao(trecho) != "indeterminado"
        if sem_lastro:
            return self._decidir(
                False,
                "POL-02",
                "registrar_conclusao_obra",
                "relato de terceiro, texto citado, pergunta, hipótese ou trecho que muda de sentido fora da frase "
                "inteira não é atestação do fiscal; diga o que você viu ou envie a foto da estrutura",
            )
        return self._decidir(True, "POL-02", "registrar_conclusao_obra", f"declaração do fiscal sobre {item_id}")

    def _avancar(self, fis: Fiscalizacao, args: dict[str, Any]) -> Decisao:
        para = str(args.get("para") or args.get("etapa") or "").upper()
        if para not in fsm.Etapa.__members__:
            return self._decidir(False, POL_FSM, "avancar_etapa", f"etapa desconhecida {para!r}")
        if para in ("RASCUNHO", "ASSINATURA", "SELADO"):
            regra = "POL-03" if para == "SELADO" else POL_FSM
            return self._decidir(
                False,
                regra,
                "avancar_etapa",
                f"{para} só por emitir_rascunho, solicitar_assinatura ou assinatura humana",
            )
        if not fsm.pode_transitar(fis.estado_fsm, para):
            return self._decidir(
                False, POL_FSM, "avancar_etapa", f"{fis.estado_fsm} → {para} não é permitida"
            )
        if para in ("CONCILIACAO", "REVISAO", "RASCUNHO"):
            pend = [p for p in self.pendencias_emissao(fis) if p["regra_id"].startswith("POL-01")]
            if pend:
                return self._decidir(
                    False, "POL-01", "avancar_etapa", "faltam evidências mínimas", pendencias=pend
                )
        return self._decidir(True, POL_FSM, "avancar_etapa", f"{fis.estado_fsm} → {para}")

    # -- emissão (POL-01, POL-02, POL-04) --------------------------------------
    def pendencias_emissao(self, fis: Fiscalizacao, res: ResultadoVerificacao | None = None) -> list[dict]:
        """Pendências que impedem o rascunho.

        - POL-01: os `bloqueios` do verificador (modelo `Bloqueio`): os do rulebook, vindos de
          `avaliar_regras`, ou, sem ele, os da regra provisória. A política não refaz a checagem.
        - POL-02: campo divergente sem justificativa humana (o status agregado do item não conta: a
          justificativa vai no campo que divergiu).
        - POL-04: cadeia de hash íntegra.
        """
        res = res or self.verificador.recalcular(fis)
        pend: list[dict[str, Any]] = []
        for b in res.bloqueios:
            pol = "POL-02" if b.status == "divergente" else "POL-01"
            pend.append(
                {
                    "regra_id": f"{pol}/{b.regra_id}",
                    "campo": b.campo,
                    "status": b.status,
                    "falta": b.falta,
                    "origem": "regra_provisoria" if res.provisoria else "avaliar_regras",
                }
            )
        ja = {p["campo"] for p in pend if p.get("campo")}
        for c in res.campos.values():
            if c.regra_id == REGRA_AGREGACAO or c.campo in ja:
                continue
            if c.status == "divergente" and not c.justificativa_humana:
                pend.append(
                    {
                        "regra_id": "POL-02",
                        "campo": c.campo,
                        "status": "divergente",
                        "evidencias": c.evidencias,
                        "checagens": c.checagens,
                        "falta": "justificativa do fiscal (ou nova evidência)",
                        "motivo": c.motivo,
                    }
                )
        cadeia = hashchain.verificar_cadeia(fis.evidencias)
        if not cadeia.integra:
            pend.append({"regra_id": "POL-04", "falta": "cadeia de hash íntegra", "motivo": cadeia.motivo})
        return pend

    def autorizar_emissao(self, fis: Fiscalizacao, res: ResultadoVerificacao | None = None) -> Decisao:
        pend = self.pendencias_emissao(fis, res)
        if pend:
            regras = sorted({p["regra_id"].split("/")[0] for p in pend})
            return self._decidir(
                False,
                "+".join(regras),
                "emitir_rascunho",
                f"rascunho bloqueado: {len(pend)} pendência(s)",
                pendencias=pend,
            )
        return self._decidir(True, "POL-01+POL-02", "emitir_rascunho", "evidência mínima e justificativas ok")

    # -- guardas da fala e de dados -------------------------------------------
    def avaliar_fala(
        self, texto: str, fis: Fiscalizacao, houve_nova_evidencia: bool = False
    ) -> list[Decisao]:
        """Guardas determinísticas sobre a fala do fiscal (antes do LLM)."""
        decisoes: list[Decisao] = []
        if m := detectar(INJECAO_FALA, texto):
            decisoes.append(
                self._decidir(
                    False,
                    "POL-06",
                    "fala",
                    f"tentativa de instrução fora do protocolo: '{m}'",
                    ocorrencia="injecao",
                )
            )
        if m := detectar(ASSINATURA, texto):
            decisoes.append(self._decidir(False, "POL-03", "fala", f"pedido para o agente assinar: '{m}'"))
        p = intencao.classificar_pressao(texto)
        if p is not None and p.grau == "incerta":
            # Sinal sem alvo claro: pergunta ao fiscal; nada vai para a cadeia imutável.
            decisoes.append(
                self._decidir(
                    True,
                    "POL-07",
                    "fala",
                    f"possível pedido de alteração ({p.tipo}: '{p.trecho}'); incerto: pedir esclarecimento, "
                    "sem ocorrência",
                    esclarecer=intencao.pedido_de_esclarecimento(p),
                )
            )
        elif p is not None and houve_nova_evidencia:
            decisoes.append(
                self._decidir(
                    False,
                    "POL-07",
                    "fala",
                    f"pedido de alterar valor ('{p.trecho}'); o valor virá da checagem da nova evidência",
                )
            )
        elif p is not None:
            decisoes.append(
                self._decidir(
                    False,
                    "POL-07",
                    "fala",
                    f"pedido de alterar valor sem nova evidência ({p.tipo}): '{p.trecho}'",
                    ocorrencia="pressao",
                )
            )
        return decisoes

    def avaliar_dado(self, texto: str, origem: str, ref: str | None = None) -> Decisao | None:
        """POL-06 para texto vindo de OCR, documento ou transcrição: instrução vira ocorrência, sem efeito."""
        if m := detectar(INJECAO_DADO, texto):
            return self._decidir(
                False,
                "POL-06",
                f"dado:{origem}",
                f"instrução embutida em {origem} ({ref or 's/ref'}) tratada como dado: '{m}'",
                ocorrencia="injecao",
            )
        return None

    def checar_texto(
        self, texto: str, fis: Fiscalizacao, extras: list[Any] | None = None, acao: str = "texto"
    ) -> Decisao:
        """POL-05: grounding numérico de um texto livre."""
        g = grounding(texto, fis, extras=extras or [])
        if g.ok:
            return self._decidir(True, "POL-05", acao, f"{len(g.numeros)} número(s) com lastro")
        return self._decidir(
            False,
            "POL-05",
            acao,
            f"número(s) sem lastro no estado: {', '.join(g.sem_lastro)}",
            pendencias=[{"sem_lastro": g.sem_lastro}],
        )

    def checar_semantica(
        self, texto: str, fis: Fiscalizacao, res: ResultadoVerificacao | None = None, acao: str = "fala_agente",
        acoes: fatos.ContextoAcoes | None = None,
    ) -> tuple[Decisao, fatos.AnaliseFala]:
        """POL-09: consistência semântica da fala do LLM com o estado e com as ações do turno (`acoes`: ação
        afirmada que não aconteceu também é violação). Violação → a fala vira template (resultado
        "transformar" no trace); sem violação, as frases que afirmam resultado saem da fala (o fato vem do
        template) e ficam só as de condução."""
        res = res or self.verificador.recalcular(fis)
        a = fatos.analisar_fala(texto, fis, res.campos, self.pendencias_emissao(fis, res), acoes=acoes)
        if a.violacoes:
            motivo = "; ".join(f"{v.tipo}: {v.motivo} («{v.trecho[:80]}»)" for v in a.violacoes[:3])
            d = self._decidir(False, fatos.REGRA_SEMANTICA, acao, motivo, resultado="transformar",
                              pendencias=[v.model_dump() for v in a.violacoes])
        else:
            d = self._decidir(True, fatos.REGRA_SEMANTICA, acao,
                              f"{len(a.conducao)} frase(s) de condução; {len(a.removidas)} afirmação(ões) de "
                              "resultado trocada(s) pelo template")
        return d, a
