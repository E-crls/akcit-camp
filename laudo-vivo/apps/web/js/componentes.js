// Componentes compartilhados pelas telas: o indicador do laudo, o resumo por objeto e o código do laudo.

import { codigoBlocos, codigoCurto, etapasLaudo, textoIndicador, textoMarcaDiv } from "./regras.js";
import { abrirModal, chipStatus, copiar, h, icone } from "./ui.js";

// Régua: tinta = pronto; vermelho = divergente sem justificativa; âmbar = a vez (o item do AGORA); listrado claro = falta.
// A divergência justificada conta como pronta e guarda um filete vermelho. Nunca só cor: o texto vai ao lado.
export function barraProgresso(ind) {
  return h("div", { class: "prog", "aria-hidden": "true" }, ind.segs.map((s) => h("i", { class: s === "falta" ? "" : s })));
}

// "2 de 5 itens prontos" com o número em Condensed 800 (o texto inteiro continua no mesmo nó, para leitura e busca)
function textoComNumero(txt) {
  const m = String(txt).match(/^(\d+)(\s.*)$/);
  return m ? [h("span", { class: "n" }, m[1]), m[2]] : [txt];
}

export function linhaIndicador(ind, { grande = false, apoioAntes = true } = {}) {
  if (ind.antes) {
    return h("div", { class: "ind antes" }, h("strong", { class: grande ? "grande" : null }, "Itens do laudo"),
      apoioAntes ? h("span", { class: "t-sec" }, "A lista sai com a sua primeira prova.") : null);
  }
  return h("div", { class: "ind" },
    h("div", { class: "prog-txt" }, h("strong", { class: `ind-n${grande ? " grande" : ""}`, "aria-live": "polite" }, ...textoComNumero(textoIndicador(ind))),
      textoMarcaDiv(ind) ? h("span", { class: `div-txt${ind.D ? "" : " div-j"}` }, icone("diverge"), textoMarcaDiv(ind)) : null),
    barraProgresso(ind));
}

export function cartaoResumo(resumo, { link = null } = {}) {
  return h("div", { class: "cartao resumo" },
    h("div", { class: "total" }, h("span", { class: "si si-ok" }, icone("check-cheio")), h("strong", {}, resumo.total)),
    resumo.objetos.map((o) => h("div", { class: "obj" }, icone(o.ic),
      h("div", { class: "txt" }, h("div", { class: "l1" }, h("strong", {}, o.nome), chipStatus(o.status)),
        o.frase ? h("span", { class: "det" }, o.frase) : null))),
    link);
}

export function verCodigo(hx) {
  abrirModal("Código do laudo", h("div", { class: "codigo-todo" },
    h("p", {}, "Este código resume todo o conteúdo do laudo. Qualquer mudança, por menor que seja, gera outro código."),
    h("p", { class: "codigo mono", translate: "no" }, codigoBlocos(hx)),
    h("div", { class: "acoes-linha" }, h("button", { class: "btn btn-sec", type: "button", onclick: () => copiar(hx, "Código copiado") }, icone("copiar"), "Copiar"))));
}

export function cartaoCodigo(hx, { id = null, nota = true } = {}) {
  return h("section", { class: "cartao codigo-card", id, "aria-label": "Código do laudo" },
    h("div", { class: "codigo-l1" }, h("span", { class: "t-sec" }, "Código do laudo"),
      h("button", { class: "btn-ter link", type: "button", onclick: () => verCodigo(hx) }, "Ver todo")),
    h("p", { class: "codigo mono", translate: "no" }, codigoCurto(hx)),
    nota ? h("p", { class: "nota-cad" }, icone("cadeado"), "Ninguém pode alterar este laudo. Correção abre uma nova fiscalização.") : null);
}

// Trilha do laudo (Em campo → Rascunho → Assinado → Selado): cada etapa com quando e (com comQuem) quem fez.
export function trilhaEtapas(e, { comQuem = false, fiscal, segundos = false } = {}) {
  const et = etapasLaudo(e, { fiscal, segundos });
  return h("ol", { class: "etapas", "aria-label": "Etapas do laudo" }, et.map((x) => h("li", { class: x.estado || null, "aria-current": x.estado === "atual" ? "step" : null },
    h("span", { class: "et-n" }, x.rot),
    h("span", { class: "et-d" }, x.quando || (x.estado ? "" : "—")),
    comQuem && x.quem ? h("span", { class: "et-d" }, x.quem) : null)));
}

// Placar: números grandes lado a lado, com o filete de cor de cada bloco (tinta, verde, vermelho). A linha do número
// tem altura fixa e alinha pela linha de base: o "R$ … mi" não empurra o rótulo do bloco para baixo.
export function placar(blocos, { cls = "" } = {}) {
  return h("div", { class: `placar${cls ? ` ${cls}` : ""}`, style: { "--n": String(blocos.length) } }, blocos.map((b) => h("div", { class: b.cls || null },
    h("b", {}, b.pre ? h("small", { class: "pre" }, b.pre) : null, h("span", { class: "num" }, b.n), b.un ? h("small", {}, b.un) : null), h("span", { class: "rot-pl" }, b.rot))));
}

// a justificativa da fiscal no laudo e na prova: texto recuado, com o rótulo "Fiscal:" (sem barra de destaque)
export function justificativa(texto) {
  return h("blockquote", { class: "just" }, h("span", { class: "just-rot" }, "Fiscal:"), h("span", { class: "just-txt" }, `“${texto}”`));
}
