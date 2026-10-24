// Agentes (arquitetura v2): o registro vem de GET /api/agentes, carregado uma vez. Três usos na tela:
// - na conversa, a linha discreta de chips com o especialista de cada ação ("Visão", "Documentos", "Território", "Triagem");
// - a gaveta "Agentes" (botão do cabeçalho): o Condutor no centro, os especialistas, o Auditor, os guarda-corpos e a fiscal;
// - "Revisão do Auditor (IA)" antes de assinar: o parecer do Agente Auditor, que não muda nenhum status.

import { api } from "./api.js";
import { avisar, h, icone } from "./ui.js";

let REG = null; // { agentes, guarda_corpos, ferramenta_agente, interop }
let carregando = null;
const ESPECIALISTAS = ["visao", "documentos", "territorio", "triagem"];
export const NOTA_AUDITOR = "O Auditor não muda nenhum status; quem decide é o verificador, citando o MCR. A assinatura é sua.";

export function carregarAgentes() {
  if (REG) return Promise.resolve(REG);
  if (!carregando) {
    carregando = api.agentes().then((r) => { REG = r; window.dispatchEvent(new Event("lv:agentes")); return r; })
      .catch(() => { carregando = null; return null; });
  }
  return carregando;
}

// Os especialistas das ações de um turno ("contar_bovinos_video:ok" → "Visão"), sem repetir, na ordem em que agiram.
// Pura (testável): recebe o mapa ferramenta → agente e a lista de agentes.
export function especialistasDasAcoes(acoes, mapa, agentes) {
  const vistos = [];
  for (const a of acoes || []) {
    const nome = String(typeof a === "string" ? a : a?.acao || "").split(":")[0];
    const id = mapa?.[nome];
    if (id && ESPECIALISTAS.includes(id) && !vistos.includes(id)) vistos.push(id);
  }
  return vistos.map((id) => (agentes || []).find((x) => x.id === id)).filter(Boolean);
}

export function chipsAgentes(acoes) {
  if (!REG) return null;
  const lista = especialistasDasAcoes(acoes, REG.ferramenta_agente, REG.agentes);
  if (!lista.length) return null;
  return h("div", { class: "ag-chips", "aria-label": "Agentes especialistas que agiram" },
    lista.map((a) => h("span", { class: "ag-chip", title: `${a.nome}: ${a.papel}` }, a.curto)));
}

// ---------------------------------------------------------------- gaveta "Agentes"
function cartaoAgente(a, cls = "") {
  return h("article", { class: `ag-cartao ${cls}`.trim() },
    h("h3", {}, a.nome, a.novo ? h("span", { class: "ag-novo" }, "novo") : null),
    h("p", { class: "ag-papel" }, a.papel),
    h("dl", { class: "ag-kv" },
      h("dt", {}, "Quando"), h("dd", {}, a.quando_age),
      h("dt", {}, "Modelo"), h("dd", {}, a.modelo),
      h("dt", {}, "Ferramentas"), h("dd", { class: "mono" }, a.ferramentas?.length ? a.ferramentas.join(" · ") : "lê o rascunho, as provas e o verificador"),
      h("dt", {}, "Guarda-corpo"), h("dd", {}, a.guarda_corpo)));
}

function corpoGaveta(reg) {
  if (!reg) return [h("p", { class: "t-sec" }, "Não consegui carregar os agentes. Tente de novo.")];
  const ag = Object.fromEntries(reg.agentes.map((a) => [a.id, a]));
  const esp = ["visao", "documentos", "territorio"].map((id) => ag[id]).filter(Boolean);
  return [
    h("p", { class: "ag-frase" }, "Quem conversa não confere."),
    h("p", { class: "t-sec" }, "Um Condutor supervisiona a visita e delega a especialistas, cada um com seu modelo, suas ferramentas e o direito de se abster: sem prova, vira pendência. "
      + "Um Auditor revisa o rascunho antes da assinatura. A política e o verificador, os dois sem IA, são os guarda-corpos. A fiscal assina."),
    h("div", { class: "ag-diagrama", role: "list", "aria-label": "Diagrama dos agentes" },
      ag.triagem ? h("div", { class: "ag-faixa", role: "listitem" }, h("span", { class: "ag-etapa" }, "Antes do campo"), cartaoAgente(ag.triagem)) : null,
      h("div", { class: "ag-faixa", role: "listitem" }, h("span", { class: "ag-etapa" }, "Durante a visita"),
        ag.condutor ? cartaoAgente(ag.condutor, "centro") : null,
        h("div", { class: "ag-seta", "aria-hidden": "true" }, "delega a"),
        h("div", { class: "ag-especialistas" }, esp.map((a) => cartaoAgente(a)))),
      ag.auditor ? h("div", { class: "ag-faixa", role: "listitem" }, h("span", { class: "ag-etapa" }, "Antes da assinatura"), cartaoAgente(ag.auditor)) : null,
      h("div", { class: "ag-faixa", role: "listitem" }, h("span", { class: "ag-etapa" }, "Guarda-corpos (sem IA)"),
        h("ul", { class: "ag-guardas" }, reg.guarda_corpos.map((g) => h("li", {}, icone("escudo"), h("span", {}, h("strong", {}, g.nome), ` · ${g.faz}`))))),
      h("div", { class: "ag-faixa ag-fiscal", role: "listitem" }, h("span", { class: "ag-etapa" }, "Quem decide"),
        h("p", {}, icone("assinar"), h("strong", {}, "A fiscal assina."), " O status de cada item vem do verificador, citando o MCR 2-7."))),
    h("section", { class: "tec-sec" }, h("h3", {}, "Fala a língua dos outros agentes"),
      h("p", { class: "t-sec" }, `MCP: ${reg.interop?.mcp?.ferramentas?.length || 0} ferramentas tipadas pelo servidor `, h("span", { class: "mono" }, "laudo.mcp_server"), "."),
      h("p", { class: "t-sec" }, "A2A: ", h("a", { href: reg.interop?.a2a || "/.well-known/agent.json", target: "_blank", rel: "noopener" }, "cartão de agente"),
        " publicado. O recebimento de tarefas A2A ainda é a construir.")),
    h("p", { class: "t-sec ag-medido" }, "Os números da avaliação são do Condutor com os especialistas e os guarda-corpos. O Auditor é novo e não foi avaliado no golden set."),
  ];
}

export async function abrirAgentes(abrir) {
  const g = document.getElementById("gaveta-agentes");
  const b = document.getElementById("btn-agentes");
  if (!g) return;
  const vai = abrir === undefined ? g.hidden : !!abrir;
  g.hidden = !vai;
  b?.setAttribute("aria-expanded", vai ? "true" : "false");
  document.getElementById("veu-global").hidden = !vai && !document.querySelector(".folha-m.aberta") && document.getElementById("tecnico")?.hidden !== false;
  if (!vai) return;
  const corpo = document.getElementById("agentes-corpo");
  if (!REG) corpo.replaceChildren(h("p", { class: "t-sec" }, "Carregando os agentes…"));
  corpo.replaceChildren(...corpoGaveta(await carregarAgentes()));
  g.querySelector("[data-fechar-agentes]")?.focus({ preventScroll: true });
}
export function agentesAberto() { const g = document.getElementById("gaveta-agentes"); return !!g && !g.hidden; }

// ---------------------------------------------------------------- Revisão do Auditor (IA)
const ROT_RISCO = { alto: "Risco alto", medio: "Risco médio", baixo: "Risco baixo" };

export function cartaoParecer(out, rotuloItem = (id) => id) {
  const p = out?.parecer || {};
  const revisar = p.recomendacao !== "pode_assinar";
  return h("section", { class: "cartao auditor-parecer", role: "region", "aria-label": "Parecer do Auditor" },
    h("p", { class: `aud-rec ${revisar ? "revisar" : "pode"}` }, icone(revisar ? "alerta" : "check"),
      h("strong", {}, revisar ? "Revisar antes de assinar" : "Pode assinar, se concordar")),
    p.resumo ? h("p", { class: "aud-resumo" }, p.resumo) : null,
    (p.itens || []).length ? h("ul", { class: "aud-itens" }, p.itens.map((it) => h("li", { class: `aud-item r-${it.risco}` },
      h("span", { class: "aud-risco" }, ROT_RISCO[it.risco] || it.risco), h("strong", {}, rotuloItem(it.item_id)),
      it.motivo ? h("p", {}, it.motivo) : null,
      it.pergunta_para_a_fiscal ? h("p", { class: "aud-pergunta" }, icone("balao"), it.pergunta_para_a_fiscal) : null,
      it.evidencias?.length ? h("p", { class: "t-sec aud-ev", title: it.evidencias.join(" · ") },
        it.evidencias.length === 1 ? "1 prova citada" : `${it.evidencias.length} provas citadas`) : null)))
      : h("p", { class: "t-sec" }, "Nenhum item em risco."),
    h("p", { class: "aud-nota" }, icone("escudo-cheio"), NOTA_AUDITOR),
    h("p", { class: "t-sec aud-origem" }, out?.origem === "llm" ? `Parecer do modelo ${out.modelo || ""}, conferido pelas regras.` : "Parecer pelas regras do verificador (sem modelo nesta execução)."));
}

// O item do laudo como a tela o chama ("Bovinos · Quantidade (contagem em vídeo)"), pelo campo da matriz.
export function rotuloItemLaudo(estado, id) {
  const ln = (estado?.matriz || []).find((x) => x.campo === id) || (estado?.matriz || []).find((x) => x.item_id === id);
  if (!ln) return id;
  const item = String(ln.item_descricao || id).split(" — ")[0]; // sem o texto do Sicor
  return ln.aspecto && ln.aspecto !== ln.item_descricao ? `${item} · ${ln.aspecto}` : item;
}

// O botão secundário e o lugar do parecer; `rotuloItem` traduz o id do item para a tela; `inicial` mostra o parecer
// já recebido (a tela se redesenha a cada turno) e `aoResultado` o guarda.
export function blocoAuditor(fisId, { rotuloItem, inicial = null, aoResultado = null } = {}) {
  const lugar = h("div", { class: "auditor-lugar", "aria-live": "polite" }, inicial ? cartaoParecer(inicial, rotuloItem) : null);
  const btn = h("button", { class: "btn btn-sec btn-cheio", type: "button", id: "btn-auditor" }, icone("escudo"), "Revisão do Auditor (IA)");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    lugar.replaceChildren(h("p", { class: "t-sec" }, "O Auditor está revisando o rascunho…"));
    try {
      const out = await api.auditoria(fisId);
      aoResultado?.(out);
      lugar.replaceChildren(cartaoParecer(out, rotuloItem));
    } catch (e) {
      lugar.replaceChildren();
      avisar(e.amigavel ? e.message : "Não consegui a revisão do Auditor agora.", true);
    }
    btn.disabled = false;
  });
  return h("div", { class: "auditor-bloco" }, btn, lugar);
}
