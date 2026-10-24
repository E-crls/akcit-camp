// Utilitários de interface: criação segura de elementos (sem innerHTML com dados), ícones do sprite, status, avisos,
// folhas e menus, topo (trilha no computador; voltar e título no celular), marca de demonstração e a gaveta
// "Detalhes técnicos".

export function h(tag, attrs = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") {
      // propriedades personalizadas ("--n") só entram por setProperty
      for (const [pk, pv] of Object.entries(v)) { if (pk.startsWith("--")) el.style.setProperty(pk, pv); else el.style[pk] = pv; }
    }
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const f of filhos.flat(Infinity)) {
    if (f === null || f === undefined || f === false) continue;
    el.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return el;
}

// Ícones: o sprite de index.html (Phosphor Bold e Fill, MIT; o satélite da Lucide, ISC; cerca, área e esquadro próprios),
// montado por scripts/montar_sprite_web.py. Nomes antigos continuam valendo.
const DE_PARA = { verificado: "check", divergente: "diverge", pendente: "falta", abstencao: "sem-conclusao", compartilhar: "telao",
  doc: "nota", clipe: "mais", fechar: "x", lupa: "busca", reiniciar: "recomecar", pessoa: "vaca", trace: "codigo",
  ajustes: "opcoes", som: "mic", semrede: "info", xml: "arquivo", cima: "baixo", descer: "baixo", ok: "check" };
const NS = "http://www.w3.org/2000/svg";

export function icone(nome, cls = "") {
  const id = DE_PARA[nome] || nome;
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("focusable", "false");
  s.setAttribute("class", `ic${cls ? ` ${cls}` : ""}${nome === "cima" ? " girar" : ""}`);
  const u = document.createElementNS(NS, "use");
  u.setAttribute("href", `#i-${id}`);
  s.append(u);
  return s;
}

// Símbolos da marca: "selo-g" (a marca: o esquadro graduado na placa ipê, de 32 px para cima), "marca-p" (lisa, abaixo de 20 px), "agente"
// (só o esquadro, na cor do texto: sem rosto, sem placa, sem círculo) e "pino-demo" (o piquete ipê com o esquadro).
export function simbolo(id, cls) {
  const vb = { "marca-p": "0 0 64 64", "selo-g": "0 0 64 64", agente: "8 6 50 52", "pino-demo": "0 0 30 30" }[id] || "0 0 24 24";
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("focusable", "false");
  s.setAttribute("viewBox", vb);
  s.setAttribute("class", cls || id);
  const u = document.createElementNS(NS, "use");
  u.setAttribute("href", `#${id}`);
  s.append(u);
  return s;
}
// quem fala: o esquadro de 20 px e o nome em rótulo (o agente aparece pelo trabalho que fez, sem rosto)
export const avatarAgente = () => h("span", { class: "avatar" }, simbolo("agente", "agente"), h("span", { class: "quem-ag" }, "Laudo Vivo"));

// ---------------------------------------------------------------- status: ícone + palavra + cor (nunca só cor)
// "divergente-j": a divergência justificada pela fiscal (pronta). Contorno ipê-roxo com o visto, para não se confundir
// com a divergência aberta (roxo cheio): as duas só se distinguiam na régua.
export const ROTULO_STATUS = { verificado: "Verificado", divergente: "Divergente", "divergente-j": "Divergente · justificada", pendente: "Falta",
  abstencao: "Sem conclusão", ok: "Verificado", indeterminado: "Sem conclusão", erro: "Erro" };
const CLS_STATUS = { verificado: "st-ok", ok: "st-ok", divergente: "st-div", "divergente-j": "st-divj", pendente: "st-falta", erro: "st-falta",
  abstencao: "st-sem", indeterminado: "st-sem" };
const IC_STATUS = { verificado: "check-cheio", ok: "check-cheio", divergente: "diverge", "divergente-j": "check", pendente: "falta", erro: "falta",
  abstencao: "sem-conclusao", indeterminado: "sem-conclusao" };

export function chipStatus(status, rotulo = null) {
  return h("span", { class: `st ${CLS_STATUS[status] || "st-neutro"}` }, icone(IC_STATUS[status] || "info"), rotulo || ROTULO_STATUS[status] || status);
}
export function chipNeutro(texto, ic = null, cls = "st-neutro") {
  return h("span", { class: `st ${cls}` }, ic ? icone(ic) : null, texto);
}

export function fmtNum(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  if (Array.isArray(v)) return v.length === 2 ? `${fmtNum(v[0])} a ${fmtNum(v[1])}` : v.map(fmtNum).join(", ");
  return String(v);
}

export function fmtData(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function hashAgrupado(hx) {
  const el = h("span", { class: "hash mono", translate: "no" });
  (hx || "").match(/.{1,4}/g)?.forEach((g) => el.append(h("span", { class: "g" }, g)));
  return el;
}

// ---------------------------------------------------------------- avisos e leitor de tela
// O aviso de erro fica até ser fechado (no campo, com 4G ruim, ninguém lê um erro que some em 4 s). O aviso comum
// aparece no topo, abaixo do cabeçalho, por 3 s, e nunca cobre o botão principal nem o campo de mensagem.
export function avisar(texto, erro = false, ms = 3000) {
  const box = document.getElementById("avisos");
  const igual = [...box.children].find((a) => a.dataset.texto === String(texto));
  if (igual) { igual.classList.remove("repete"); void igual.offsetWidth; igual.classList.add("repete"); return igual; }
  const a = h("div", { class: `aviso${erro ? " erro" : ""}`, role: erro ? "alert" : "status", dataset: { texto: String(texto) } },
    icone(erro ? "alerta" : "info"), h("span", { class: "aviso-txt" }, texto));
  if (erro) a.append(h("button", { class: "btn-icone aviso-fechar", type: "button", "aria-label": "Fechar o aviso", onclick: () => a.remove() }, icone("x")));
  else setTimeout(() => a.remove(), ms);
  box.append(a);
  return a;
}
export function limparErros() { document.querySelectorAll("#avisos .aviso.erro").forEach((a) => a.remove()); }

export function anunciar(texto, urgente = false) {
  const el = document.getElementById(urgente ? "anuncio-urgente" : "anuncio");
  el.textContent = "";
  setTimeout(() => { el.textContent = texto; }, 30);
}
// ao trocar de tela, o leitor de tela não repete o que foi anunciado na anterior
export function limparAnuncios() {
  for (const id of ["anuncio", "anuncio-urgente"]) { const el = document.getElementById(id); if (el) el.textContent = ""; }
}

// ---------------------------------------------------------------- modal
export function abrirModal(titulo, conteudo, { largo = false } = {}) {
  const m = document.getElementById("modal");
  document.getElementById("modal-titulo").textContent = titulo;
  m.classList.toggle("largo", !!largo);
  const corpo = document.getElementById("modal-corpo");
  corpo.replaceChildren(conteudo);
  corpo.scrollTop = 0;
  if (!m.open) m.showModal();
  return corpo;
}
export function fecharModal() { const m = document.getElementById("modal"); if (m.open) m.close(); }

export function iniciarModal() {
  const m = document.getElementById("modal");
  m.querySelector("[data-fechar]").addEventListener("click", () => m.close());
  m.addEventListener("click", (e) => { if (e.target === m) m.close(); });
}

export function limpar(el) { el.replaceChildren(); return el; }

// ---------------------------------------------------------------- menus (popover no computador, folha no celular)
const MENUS = new Set();
export function ehMovel() { return !window.matchMedia("(min-width: 1100px)").matches; }

// itens: [{ rot, ic, acao, perigo, sub }] ou um nó pronto. O menu se fecha no clique fora, no Esc e ao escolher.
export function abrirMenu(menu, botao, itens, { titulo = null } = {}) {
  fecharMenus();
  const lista = itens.filter(Boolean).map((it) => (it instanceof Node ? it : h("button", {
    class: `menu-item${it.perigo ? " perigo" : ""}`, type: "button", role: "menuitem",
    onclick: (ev) => { ev.stopPropagation(); if (!it.manter) fecharMenus(); it.acao?.(ev); } },
  it.ic ? icone(it.ic) : null, h("span", { class: "menu-rot" }, it.rot, it.sub ? h("small", {}, it.sub) : null))));
  menu.replaceChildren(...(titulo ? [h("div", { class: "menu-cab" }, h("strong", {}, titulo),
    h("button", { class: "btn-icone", type: "button", "aria-label": "Fechar", onclick: () => fecharMenus(true) }, icone("x")))] : []), ...lista);
  // no celular o menu é uma folha inferior: vai para o <body> enquanto está aberto, para ficar acima do véu (o topo e a
  // barra da demonstração criam o seu próprio empilhamento, e uma folha dentro deles ficaria por baixo do véu)
  if (ehMovel() && menu.parentElement !== document.body) {
    menu._casa = [menu.parentElement, menu.nextSibling];
    document.body.append(menu);
  }
  menu.hidden = false;
  menu._botao = botao;
  botao?.setAttribute("aria-expanded", "true");
  MENUS.add(menu);
  if (ehMovel()) document.getElementById("veu-global").hidden = false;
  menu.querySelector(".menu-item")?.focus({ preventScroll: true });
}
export function fecharMenus(devolver = false) {
  for (const m of MENUS) {
    m.hidden = true;
    m._botao?.setAttribute("aria-expanded", "false");
    if (m._casa) {
      const [pai, prox] = m._casa;
      m._casa = null;
      if (pai?.isConnected) pai.insertBefore(m, prox && prox.parentNode === pai ? prox : null); else m.remove();
    }
    if (devolver && m._botao?.isConnected) m._botao.focus({ preventScroll: true });
  }
  MENUS.clear();
  if (!document.querySelector(".folha-m.aberta")) document.getElementById("veu-global").hidden = true;
}
export function menuAberto() { return MENUS.size > 0; }
document.addEventListener("pointerdown", (e) => {
  for (const m of MENUS) if (!m.contains(e.target) && !m._botao?.contains(e.target)) { fecharMenus(); break; }
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && MENUS.size) { e.stopImmediatePropagation(); fecharMenus(true); } }, true);

// ---------------------------------------------------------------- topo
// { trilha: [{ rot, href }], titulo, sub, voltar: href | função, mais: [itens], casa: bool }
export function definirTopo({ trilha = [], titulo = "", sub = "", voltar = null, mais = null, casa = false } = {}) {
  const nav = document.getElementById("trilha");
  nav.replaceChildren(...trilha.flatMap((t, i) => [i ? icone("direita") : null,
    t.href ? h("a", { href: t.href }, t.rot) : h("span", { "aria-current": "page" }, t.rot)]).filter(Boolean));
  const v = document.getElementById("topo-voltar");
  v.hidden = !voltar;
  if (typeof voltar === "string") { v.href = voltar; v.onclick = null; } else if (voltar) { v.href = "#"; v.onclick = (e) => { e.preventDefault(); voltar(); }; }
  document.getElementById("topo-h1").textContent = titulo;
  document.getElementById("topo-sub").textContent = sub;
  document.getElementById("topo-sub").hidden = !sub;
  document.getElementById("topo-titulo").hidden = casa || !titulo;
  document.body.classList.toggle("topo-casa", !!casa);
  const b = document.getElementById("topo-mais");
  b.hidden = !mais;
  b.onclick = mais ? () => abrirMenu(document.getElementById("menu-mais"), b, typeof mais === "function" ? mais() : mais, { titulo: ehMovel() ? "Opções" : null }) : null;
  window.dispatchEvent(new Event("lv:topo"));
}

// ---------------------------------------------------------------- folha inferior (celular) e gaveta
export function alternarFolha(el, abrir, { foco = null } = {}) {
  const vai = abrir === undefined ? !el.classList.contains("aberta") : !!abrir;
  el.classList.toggle("aberta", vai);
  el.setAttribute("aria-hidden", vai ? "false" : "true");
  // o véu escuro só no celular (folha que sobe de baixo); no computador a gaveta e o menu ficam sobre a tela
  const veu = document.getElementById("veu-global");
  veu.hidden = !ehMovel() || (!document.querySelector(".folha-m.aberta") && !menuAberto());
  if (vai) (foco || el.querySelector("button, a, input"))?.focus({ preventScroll: true });
  return vai;
}

// ---------------------------------------------------------------- marca de demonstração (uma por tela)
let DEMO = null;
export function definirDemo(bloco) {
  DEMO = bloco || null;
  document.getElementById("faixa-demo").hidden = !DEMO;
  document.getElementById("demo-pilula").hidden = !DEMO;
  document.body.classList.toggle("com-demo", !!DEMO);
  window.dispatchEvent(new Event("lv:topo"));
}
export function demoAtual() { return DEMO; }

// ---------------------------------------------------------------- gaveta "Detalhes técnicos"
// Estado do sistema (replay/ao vivo, fora da gravação), decisões da política, checagens e ferramentas, etapas,
// evidências, trace e o aviso longo da demonstração. Cada tela registra as suas seções; a gaveta junta e mostra.
const TEC = new Map();
const ORDEM_TEC = ["sistema", "fis", "laudo", "carteira"];

export function secaoTecnica(chave, construir) {
  if (construir) TEC.set(chave, construir); else TEC.delete(chave);
  if (tecnicoAberto()) renderTecnico();
}
function renderTecnico() {
  const corpo = document.getElementById("tecnico-corpo");
  const chaves = [...TEC.keys()].sort((a, b) => ORDEM_TEC.indexOf(a) - ORDEM_TEC.indexOf(b));
  const nos = [];
  for (const k of chaves) {
    try { nos.push(TEC.get(k)()); } catch (e) { nos.push(h("p", { class: "t-sec" }, `seção ${k}: ${e.message}`)); }
  }
  if (DEMO) nos.push(blocoTec("Demonstração", h("p", {}, h("strong", {}, `${DEMO.marca_dagua}. `), DEMO.aviso || "")));
  corpo.replaceChildren(...nos);
}
export function abrirTecnico(abrir) {
  const g = document.getElementById("tecnico");
  const b = document.getElementById("btn-tecnico");
  const vai = abrir === undefined ? g.hidden : !!abrir;
  if (vai) renderTecnico();
  g.hidden = !vai;
  b?.setAttribute("aria-expanded", vai ? "true" : "false");
  document.getElementById("veu-global").hidden = !vai && !document.querySelector(".folha-m.aberta");
  if (vai) g.querySelector("[data-fechar-tec]")?.focus({ preventScroll: true });
}
export function tecnicoAberto() { const g = document.getElementById("tecnico"); return !!g && !g.hidden; }
export function blocoTec(titulo, ...conteudo) { return h("section", { class: "tec-sec" }, h("h3", {}, titulo), ...conteudo); }
export function kv(pares) {
  return h("dl", { class: "kv" }, pares.filter(Boolean).map(([k, v, cls]) => [h("dt", {}, k), h("dd", { class: cls || null }, v ?? "—")]));
}
export function atualizarSaude() { window.dispatchEvent(new Event("lv:saude")); }

// ---------------------------------------------------------------- textos
// Rótulos legíveis das ferramentas e dos tipos de evidência (o id técnico fica em Detalhes técnicos).
export const ROT_FERRAMENTA = {
  contar_bovinos_video: "Contagem no vídeo", conciliar_nfe: "Conferência da NF-e", conciliar_gta: "Conferência da GTA",
  integridade_foto: "Integridade da foto", geofence: "Foto na área financiada", classificar_foto: "O que a foto mostra",
  serie_ndvi: "Série do satélite", planejar_metodo: "Plano de método", avaliar_regras: "Regras do MCR",
  checar_lotacao: "Lotação", ler_documento_foto: "Leitura da foto do documento",
  completar_leitura_documento: "Campos lidos pela fiscal", conciliar_alegacoes: "Alegações × evidência",
  carregar_operacao: "Operação (Sicor)", explicar_regra: "Explicação da regra", declaracao_conclusao: "Declaração da fiscal",
  declaracao_independencia: "Declaração de independência", registrar_conclusao_obra: "Conclusão da obra (fiscal)",
  registrar_justificativa: "Justificativa da fiscal", emitir_rascunho: "Emissão do rascunho",
  solicitar_assinatura: "Envio para assinatura", registrar_ocorrencia: "Registro de ocorrência",
};
export const ROT_TIPO_EV = { video: "Vídeo", foto: "Foto", nfe_xml: "Arquivo da NF-e", gta: "GTA", documento: "Foto do documento",
  declaracao: "Fala da fiscal", ocorrencia: "Ocorrência", audio: "Áudio", quadro_chave: "Quadro do vídeo", satelite: "Cena de satélite" };
export function rotuloFerramenta(nome) { return ROT_FERRAMENTA[nome] || String(nome || "").replaceAll("_", " "); }

// Texto da API sem ids técnicos crus: "(item:bov1:quantidade)", "checagem chk_…", "item:bov1:gta_data: " saem; um
// trecho repetido entre "; " aparece uma vez. Espelho de `laudo.formatacao.texto_sem_ids`.
export function semIds(texto) {
  const s = String(texto || "")
    .replace(/\s*\((?:item|documento|operacao|laudo)(?::[\w-]+)+\)/g, "")
    .replace(/\s*\(item [\w-]+:[\w-]+\)/g, "")
    .replace(/\b(?:item|documento|laudo):[\w:-]+:\s+/g, "")
    .replace(/\s*(?:—\s*)?checagem\s+chk_[0-9a-z]+/gi, "")
    .replace(/\b(?:chk|ev|oc|alg|al)_[0-9a-z_]+\b/g, "")
    .replace(/\bautofiscalizacao_assistida\b/g, "autofiscalização assistida")
    .replace(/\?{3,}[?…]*/g, "(ilegível)")
    .replace(/\b([a-z]+(?:_[a-z]+)+)(?=:\s)/g, (m) => ROT_FERRAMENTA[m] || m);
  const partes = [];
  const vistas = new Set();
  for (const p of s.split("; ").map((x) => x.trim())) {
    const chave = p.replace(/[.\s]+$/, "");
    if (p && !vistas.has(chave)) { vistas.add(chave); partes.push(p); }
  }
  if (/\.\s*$/.test(s) && partes.length && !/[.!?]$/.test(partes.at(-1))) partes[partes.length - 1] += ".";
  return partes.join("; ").replace(/\s{2,}/g, " ").replace(/\s+([.,;:)])/g, "$1").replace(/^[\s:;,.—-]+/, "").trim();
}

// Texto do verificador em linguagem de gente (só na gaveta da prova e em Detalhes)
export function legivel(texto) {
  let s = semIds(texto);
  s = s.replace(/contagem (\d+) \[(\d+), (\d+)\] vs financiado ([\d.,]+) \(limite ([\d.,]+)\)(:\s*abaixo do limite mesmo no extremo superior)?/gi,
    (m, c, a, b, f, l, abaixo) => `contados ${c} (até ${b}), financiado ${f}, mínimo aceito ${l}${abaixo ? `: mesmo ${b} fica abaixo do mínimo` : ""}`);
  s = s.replace(/^checagem inconclusiva \(\d+\/\d+\):\s*/i, "Não deu para conferir: ");
  s = s.replace(/\bindeterminado\b/gi, "não deu para conferir");
  s = s.replace(/(^|:\s)divergente \((.*)\)$/i, "$1$2");
  s = s.replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, "$3/$2/$1");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Regra curta: "MCR-2-7-item16-…" → "MCR 2-7"; "POL-01/…" → "POL-01"; "OP-…" → "Regra operacional".
export function regraCurta(id) {
  const s = String(id || "");
  const mcr = s.match(/MCR[-\s]?(\d+)-(\d+)/i);
  if (mcr) return `MCR ${mcr[1]}-${mcr[2]}`;
  const pol = s.match(/POL-(\d+)/);
  if (pol) return `POL-${pol[1]}`;
  if (/^OP-/.test(s)) return "Regra operacional";
  return s.split(/[-/]/).slice(0, 2).join(" ");
}
export const TEXTO_POL = {
  "POL-00": "Cada ação só vale na etapa certa da fiscalização.",
  "POL-01": "O rascunho só sai com a prova mínima de cada item.",
  "POL-02": "Toda divergência precisa da justificativa da fiscal.",
  "POL-03": "A assinatura é sempre humana: o agente não assina.",
  "POL-04": "Laudo selado não muda: correção abre uma nova fiscalização.",
  "POL-06": "Instrução escondida num documento é dado, não ordem.",
  "POL-07": "Um número só muda com nova prova, nunca com um pedido.",
};

// Checklist do pacote: fora da regra de cor da conferência (verde só para "Verificado", ipê só para ação e falta).
// Presente = visto em carvão; Parcial = contorno; Ausente = contorno com o x; Não aplicável = traço, em grafite.
export const ROT_CHECK = { presente: "Presente", parcial: "Parcial", ausente: "Ausente", nao_aplicavel: "Não aplicável" };
const CLS_CHECK = { presente: "chk-ok", parcial: "chk-parcial", ausente: "chk-ausente", nao_aplicavel: "chk-na" };
const IC_CHECK = { presente: "check", parcial: "falta", ausente: "x", nao_aplicavel: null };
export function chipChecklist(status) {
  return h("span", { class: `chk ${CLS_CHECK[status] || "chk-na"}` }, IC_CHECK[status] ? icone(IC_CHECK[status]) : null, ROT_CHECK[status] || status);
}

// "3 presente(s)", "1 vídeo(s)", "1 parcial(is)", "12 cena(s) de satélite datada(s)" → a concordância certa, pelo
// número mais próximo antes da palavra (0 e 2+ no plural; 1 no singular).
export function concordar(texto) {
  const s = String(texto || "");
  return s.replace(/([\p{L}]+)\((s|is|es)\)/gu, (m, base, suf, pos) => {
    const antes = s.slice(0, pos);
    const nums = antes.match(/\d+(?:[.,]\d+)?/g);
    const n = nums ? Number(nums.at(-1).replace(/\./g, "").replace(",", ".")) : 2;
    if (n === 1) return base;
    if (suf === "is") return base.replace(/l$/, "") + "is";
    return base + suf;
  });
}

export async function copiar(texto, rotulo = "Copiado") {
  try { await navigator.clipboard.writeText(texto); avisar(`${rotulo}.`); } catch { avisar("Não consegui copiar; selecione o texto.", true); }
}

// "Por que está na amostra" completo (critérios, pontos, faixas): fica em Detalhes técnicos → Amostra.
export function blocoAmostra(amostra, motivos = []) {
  if (!amostra && !motivos.length) return null;
  const corpo = [];
  if (amostra?.motivos?.length) {
    corpo.push(h("ul", { class: "tec-lista" }, amostra.motivos.map((m) => h("li", {},
      m.titulo ? h("strong", {}, `${m.titulo}: `) : null, m.texto,
      m.pontos !== null && m.pontos !== undefined ? ` (${m.pontos} ${m.pontos === 1 ? "ponto" : "pontos"}; critério ${m.codigo || "—"})` : "",
      m.criterio ? h("div", { class: "t-sec" }, `Como se calcula: ${m.criterio}`) : null))));
  } else if (motivos.length) corpo.push(h("ul", { class: "tec-lista" }, motivos.map((m) => h("li", {}, m))));
  if (amostra?.regra_nivel) corpo.push(h("p", { class: "t-sec" }, `Faixas de prioridade: ${amostra.regra_nivel}. ${amostra.nota || ""}`));
  corpo.push(h("p", { class: "t-sec" }, amostra?.aviso || "Prioridade de verificação não é indício de irregularidade."));
  return blocoTec("Amostra", ...corpo);
}
