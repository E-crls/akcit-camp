// Suas fiscalizações (a fiscal, no celular): em andamento (com o indicador e o "Agora"), para começar e seladas.
// Um botão cheio só: o "Continuar" da primeira fiscalização em andamento.

import { api } from "./api.js";
import { linhaIndicador } from "./componentes.js";
import { agora, dataBR, indicador, localOperacao, minuscula, nomeOperacao } from "./regras.js";
import { definirTela } from "./sessao.js";
import { avisar, definirDemo, definirTopo, h, icone } from "./ui.js";

function tituloCaso(c) {
  if (c.itens?.length) return nomeOperacao({ itens: c.itens });
  const m = String(c.titulo || "").match(/\(([^)]*\d[^)]*)\)/);
  return m ? m[1].replace(/\s\+\s/g, " e ") : (c.municipio || "Operação");
}

// Casos que funcionam nesta execução: o "roteiro" é o caso de teste do agente (arquivos falsos; só com o modelo de
// roteiro); na gravação (replay), só o caso gravado responde, então os outros não aparecem.
function casoUtil(c, saude) {
  const tipo = saude?.llm?.tipo;
  if (c.erro) return false;
  if (c.id === "roteiro" && tipo !== "roteiro") return false;
  if (tipo === "replay" && !c.padrao) return false;
  return true;
}

export async function telaFiscalizacoes(raiz, { saude = null } = {}) {
  definirTela("fiscalizacoes");
  definirTopo({ casa: true, trilha: [{ rot: "Suas fiscalizações" }] });
  const corpo = h("div", { class: "lista-fis", "aria-busy": "true" }, h("div", { class: "cartao esqueleto alto" }), h("div", { class: "cartao esqueleto" }));
  raiz.replaceChildren(h("div", { class: "pagina estreita fiscalizacoes" }, h("h1", { class: "t-display" }, "Suas fiscalizações"), corpo));
  let dados;
  try { dados = await api.listar(); } catch (e) {
    corpo.removeAttribute("aria-busy");
    corpo.replaceChildren(h("div", { class: "vazio", role: "alert" }, h("p", {}, "Não consegui carregar as fiscalizações."),
      h("button", { class: "btn btn-sec", type: "button", onclick: () => telaFiscalizacoes(raiz) }, icone("recomecar"), "Tentar de novo")));
    return;
  }
  // fiscalização de um caso que este servidor não carregou (pasta de casos externa) fica de fora
  const casosOk = new Set((dados.casos || []).filter((c) => casoUtil(c, saude)).map((c) => c.id));
  const replay = saude?.llm?.tipo === "replay";
  // fiscalização aberta pela carteira (sem caso): na gravação ela não responde; só a selada continua à vista
  const fis = (dados.fiscalizacoes || []).filter((f) => (f.origem !== "caso" || !f.caso_id ? !replay || f.etapa === "SELADO" : casosOk.has(f.caso_id)));
  const estados = (await Promise.all(fis.map((f) => api.estado(f.id).catch(() => null)))).filter(Boolean);
  const andamento = estados.filter((e) => e.etapa !== "SELADO");
  const seladas = estados.filter((e) => e.etapa === "SELADO");
  const comecar = (dados.casos || []).filter((c) => casosOk.has(c.id) && !fis.some((f) => f.caso_id === c.id || f.id === c.fis_id));
  const demo = estados.find((e) => e.demonstracao)?.demonstracao || (dados.casos || []).find((c) => c.demonstracao)?.demonstracao || null;
  definirDemo(demo);
  corpo.removeAttribute("aria-busy");
  if (!andamento.length && !comecar.length && !seladas.length) {
    corpo.replaceChildren(h("div", { class: "vazio" }, h("p", {}, "Nenhuma fiscalização para você hoje."),
      h("button", { class: "btn btn-sec", type: "button", onclick: () => telaFiscalizacoes(raiz) }, "Atualizar")));
    return;
  }
  const nos = [];
  if (andamento.length) {
    nos.push(h("h2", { class: "rotulo-secao" }, "Em andamento"));
    andamento.forEach((e, i) => {
      const ind = indicador(e);
      const a = agora(e, { papel: "fiscal" });
      nos.push(h("article", { class: "cartao fis-card" },
        h("h3", { class: "t-titulo" }, nomeOperacao(e.operacao)),
        h("p", { class: "local" }, icone("pino"), localOperacao(e.operacao)),
        linhaIndicador(ind),
        h("p", { class: "agora-mini" }, icone(a.acoes?.[0]?.ic || "nota"), h("span", {}, `Agora: ${minuscula(a.titulo)}`)),
        h("a", { class: `btn ${i === 0 ? "btn-pri" : "btn-sec"} btn-cheio`, href: `#/fis/${encodeURIComponent(e.id)}` }, "Continuar", icone("direita"))));
    });
  }
  if (comecar.length) {
    nos.push(h("h2", { class: "rotulo-secao" }, "Para começar"));
    comecar.forEach((c) => nos.push(h("article", { class: "cartao fis-card peq" },
      h("h3", { class: "t-sub" }, tituloCaso(c)),
      h("p", { class: "local" }, icone("pino"), localOperacao({ municipio_nome: c.municipio, uf: "GO" })),
      h("button", { class: "btn btn-sec btn-cheio", type: "button", onclick: async () => {
        try { const est = await api.abrirCaso(c.id, false); location.hash = `#/fis/${encodeURIComponent(est.id)}`; } catch (e) { avisar(e.message, true); }
      } }, "Começar"))));
  }
  if (seladas.length) {
    nos.push(h("h2", { class: "rotulo-secao" }, "Seladas"));
    seladas.forEach((e) => nos.push(h("article", { class: "cartao fis-card peq" },
      h("h3", { class: "t-sub" }, nomeOperacao(e.operacao)),
      h("p", { class: "local" }, icone("cadeado"), `Laudo selado em ${dataBR((e.laudo?.selado_em || e.assinaturas?.[0]?.em || "").slice(0, 10)).slice(0, 5)}`),
      h("div", { class: "acoes-linha" },
        h("a", { class: "btn btn-ter", href: `#/fis/${encodeURIComponent(e.id)}/laudo` }, "Ver laudo"),
        h("a", { class: "btn btn-ter", href: `#/fis/${encodeURIComponent(e.id)}` }, "Ver a conversa")))));
  }
  // o caminho do laudo, em três passos, no pé da tela (a tela não fica com 60% em branco quando há uma fiscalização só)
  nos.push(h("section", { class: "como-sai", "aria-labelledby": "como-sai-t" }, h("h2", { class: "rotulo-secao", id: "como-sai-t" }, "Como o laudo sai"),
    h("ol", { class: "passos-laudo" },
      h("li", {}, h("span", { class: "n" }, "1"), icone("camera"), h("span", {}, "Você envia as provas do campo")),
      h("li", {}, h("span", { class: "n" }, "2"), icone("lista"), h("span", {}, "O agente confere cada item e mostra a prova")),
      h("li", {}, h("span", { class: "n" }, "3"), icone("assinar"), h("span", {}, "Você revisa e assina com o PIN"))),
    h("p", { class: "nota-cad" }, icone("cadeado-cheio"), "Depois do selo, nada muda: correção abre uma nova fiscalização.")));
  corpo.replaceChildren(...nos);
}
