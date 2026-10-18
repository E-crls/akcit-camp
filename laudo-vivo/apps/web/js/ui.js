// Utilitários de interface: criação segura de elementos (sem innerHTML com dados), ícones, status, avisos,
// faixa e selo de demonstração e a gaveta "Detalhes técnicos".

export function h(tag, attrs = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v; // só com conteúdo estático (ícones)
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const f of filhos.flat(Infinity)) {
    if (f === null || f === undefined || f === false) continue;
    el.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return el;
}

// Ícones SVG inline, traço de 2 px numa grade de 24 (um só estilo em toda a interface).
const T = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
const P = {
  verificado: `<path d="M5 12.5l4.5 4.5L19 7.5" ${T} stroke-width="2.6"/>`,
  divergente: `<path d="M7 7l10 10M17 7L7 17" ${T} stroke-width="2.6"/>`,
  pendente: `<circle cx="12" cy="12" r="8.5" ${T}/><path d="M12 7.5V12l3 2" ${T}/>`,
  abstencao: `<circle cx="12" cy="12" r="8.5" ${T}/><path d="M6.2 17.8L17.8 6.2" ${T}/>`,
  cadeado: `<rect x="5" y="10.5" width="14" height="10" rx="2" ${T}/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" ${T}/>`,
  escudo: `<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6z" ${T}/><path d="M9 12.2l2.2 2.2L15.5 10" ${T}/>`,
  alerta: `<path d="M12 3.8L21 19.5H3z" ${T}/><path d="M12 10v4.2" ${T}/><circle cx="12" cy="17" r="1.1" fill="currentColor"/>`,
  info: `<circle cx="12" cy="12" r="8.5" ${T}/><path d="M12 11v5.5" ${T}/><circle cx="12" cy="7.8" r="1.1" fill="currentColor"/>`,
  mic: `<rect x="9" y="3" width="6" height="11" rx="3" ${T}/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" ${T}/>`,
  camera: `<path d="M4 8h3.5l1.5-2.5h6L16.5 8H20v11H4z" ${T}/><circle cx="12" cy="13" r="3.4" ${T}/>`,
  video: `<rect x="3" y="6.5" width="12.5" height="11" rx="2" ${T}/><path d="M15.5 10.5l5-3v9l-5-3z" ${T}/>`,
  doc: `<path d="M6 3h8l4 4v14H6z" ${T}/><path d="M14 3v4h4M9 12h6M9 15.5h6" ${T}/>`,
  nota: `<path d="M6 3h12v18l-2-1.5L14 21l-2-1.5L10 21l-2-1.5L6 21z" ${T}/><path d="M9 8h6M9 11.5h6M9 15h3" ${T}/>`,
  gta: `<path d="M3 16V8h11v8M14 11h4l3 3v2h-7" ${T}/><circle cx="7" cy="17.5" r="1.8" ${T}/><circle cx="17" cy="17.5" r="1.8" ${T}/>`,
  xml: `<path d="M6 3h8l4 4v14H6z" ${T}/><path d="M10 12l-2 2 2 2M14 12l2 2-2 2" ${T}/>`,
  pino: `<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z" ${T}/><circle cx="12" cy="10" r="2.2" fill="currentColor"/>`,
  som: `<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" ${T}/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" ${T}/>`,
  enviar: `<path d="M5 12h13M13 6l6 6-6 6" ${T}/>`,
  trace: `<path d="M4 6h10M4 12h16M4 18h7" ${T}/><circle cx="17" cy="6" r="2" fill="currentColor"/><circle cx="14" cy="18" r="2" fill="currentColor"/>`,
  assinar: `<path d="M4 18c3-1 4-6 6-6s1 4 3 4 2.5-3 4-3 2 1.5 3 1.5" ${T}/><path d="M4 21h16" ${T}/>`,
  play: '<path d="M8 5.5v13l10.5-6.5z" fill="currentColor"/>',
  pular: `<path d="M6 6l7 6-7 6zM17 6v12" ${T}/>`,
  reiniciar: `<path d="M5 12a7 7 0 1 0 2.1-5M5 4.5V9h4.5" ${T}/>`,
  clipe: `<path d="M20 11.5l-7.6 7.6a5 5 0 0 1-7.1-7.1l8-8a3.4 3.4 0 0 1 4.8 4.8l-8 8a1.7 1.7 0 0 1-2.4-2.4l7.3-7.3" ${T}/>`,
  ajustes: `<path d="M4 7h10M18 7h2M4 17h4M12 17h8" ${T}/><circle cx="16" cy="7" r="2" ${T}/><circle cx="10" cy="17" r="2" ${T}/>`,
  fechar: `<path d="M6 6l12 12M18 6L6 18" ${T}/>`,
  baixo: `<path d="M6 9l6 6 6-6" ${T}/>`,
  direita: `<path d="M9 6l6 6-6 6" ${T}/>`,
  voltar: `<path d="M19 12H6M11 6l-6 6 6 6" ${T}/>`,
  codigo: `<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14" ${T}/>`,
  copiar: `<rect x="8" y="8" width="12" height="12" rx="2" ${T}/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" ${T}/>`,
  baixar: `<path d="M12 4v11M7 10l5 5 5-5M5 20h14" ${T}/>`,
  imprimir: `<path d="M7 9V4h10v5M7 17H5a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-2" ${T}/><path d="M7 14h10v6H7z" ${T}/>`,
  hash: `<path d="M9 4L7 20M17 4l-2 16M4.5 9h15M3.5 15h15" ${T}/>`,
  agente: `<rect x="4" y="7" width="16" height="12" rx="4" ${T}/><path d="M12 3.5V7M9 12.5v1M15 12.5v1M9.5 16h5" ${T}/>`,
  pessoa: `<circle cx="12" cy="8" r="3.6" ${T}/><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" ${T}/>`,
  folha: `<path d="M5 19c0-8 5-13.5 14-14-0.5 9-6 14-14 14z" ${T}/><path d="M5 19l7-7" ${T}/>`,
  mapa: `<path d="M3.5 6.5l5.5-2 6 2 5.5-2v13l-5.5 2-6-2-5.5 2z" ${T}/><path d="M9 4.5v13M15 6.5v13" ${T}/>`,
  lupa: `<circle cx="11" cy="11" r="6.5" ${T}/><path d="M16 16l4 4" ${T}/>`,
  olho: `<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" ${T}/><circle cx="12" cy="12" r="3" ${T}/>`,
  galeria: `<rect x="3.5" y="4.5" width="17" height="15" rx="2" ${T}/><circle cx="9" cy="10" r="1.8" ${T}/><path d="M20.5 16l-5-5-8.5 8.5" ${T}/>`,
  lista: `<path d="M9 6h11M9 12h11M9 18h11" ${T}/><path d="M4.5 6l1 1 1.8-2M4.5 12l1 1 1.8-2M4.5 18l1 1 1.8-2" ${T}/>`,
  satelite: `<path d="M9.5 14.5l-4 4M7 9l3-3 8 8-3 3z" ${T}/><path d="M13 5l2-2 6 6-2 2M5 13l-2 2 6 6 2-2" ${T}/>`,
  selo: `<circle cx="12" cy="10" r="6" ${T}/><path d="M9.5 15.3L8 21l4-2 4 2-1.5-5.7" ${T}/><path d="M9.6 10l1.6 1.6 3.2-3.2" ${T}/>`,
  externo: `<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" ${T}/>`,
  mais: '<circle cx="5.5" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18.5" cy="12" r="1.8" fill="currentColor"/>',
  cima: `<path d="M12 19V6M6 11l6-6 6 6" ${T}/>`,
  descer: `<path d="M12 5v13M6 13l6 6 6-6" ${T}/>`,
  semrede: `<path d="M3 3l18 18M8.5 16.5a5 5 0 0 1 7 0M5 12.6a10 10 0 0 1 4.2-2.4M19 12.6a10 10 0 0 0-2.6-1.8M2 9a15 15 0 0 1 4.4-2.9M22 9a15 15 0 0 0-9.6-3.9" ${T}/><circle cx="12" cy="20" r="1.1" fill="currentColor"/>`,
};

export function icone(nome, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("focusable", "false");
  s.setAttribute("class", cls ? `ico ${cls}` : "ico");
  s.innerHTML = P[nome] || P.info;
  return s;
}

export const ROTULO_STATUS = { verificado: "Verificado", divergente: "Divergente", pendente: "Pendente", abstencao: "Abstenção",
  ok: "Concluída", indeterminado: "Inconclusiva", erro: "Erro" };
const ICONE_STATUS = { verificado: "verificado", ok: "verificado", divergente: "divergente", pendente: "pendente", erro: "pendente",
  abstencao: "abstencao", indeterminado: "abstencao" };
export const DICA_STATUS = {
  verificado: "Verificado: a evidência confere com o financiado.",
  divergente: "Divergente: a evidência não confere com o financiado.",
  pendente: "Pendente: falta evidência para concluir.",
  abstencao: "Abstenção: a evidência não permite concluir (o sistema não chuta).",
};

export function chipStatus(status, grande = false) {
  return h("span", { class: `st st-${status}${grande ? " st-grande" : ""}`, title: DICA_STATUS[status] || null },
    icone(ICONE_STATUS[status] || "info"), ROTULO_STATUS[status] || status);
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
  if (isNaN(d)) return iso;
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function hashAgrupado(hx) {
  const el = h("span", { class: "hash", translate: "no" });
  (hx || "").match(/.{1,4}/g)?.forEach((g) => el.append(h("span", { class: "g" }, g)));
  return el;
}

// Aviso flutuante. O de erro fica até ser fechado (botão ✕): no campo, com 4G ruim, ninguém lê um erro que some em
// 4 s. O mesmo texto não empilha: o aviso que já está na tela só pisca de novo.
export function avisar(texto, erro = false, ms = 4500) {
  const box = document.getElementById("avisos");
  const igual = [...box.children].find((a) => a.dataset.texto === String(texto));
  if (igual) {
    igual.classList.remove("repete");
    void igual.offsetWidth; // reinicia a animação
    igual.classList.add("repete");
    return igual;
  }
  const a = h("div", { class: `aviso${erro ? " erro" : ""}`, role: erro ? "alert" : "status", dataset: { texto: String(texto) } },
    icone(erro ? "alerta" : "info"), h("span", { class: "aviso-txt" }, texto));
  if (erro) {
    a.append(h("button", { class: "aviso-fechar", type: "button", "aria-label": "Fechar o aviso", title: "Fechar",
      onclick: () => a.remove() }, icone("fechar")));
  } else setTimeout(() => a.remove(), ms);
  box.append(a);
  return a;
}

// Tira da tela os avisos de erro (ex.: o "Assinatura recusada" depois que a assinatura deu certo).
export function limparErros() {
  document.querySelectorAll("#avisos .aviso.erro").forEach((a) => a.remove());
}

export function anunciar(texto, urgente = false) {
  const el = document.getElementById(urgente ? "anuncio-urgente" : "anuncio");
  el.textContent = "";
  setTimeout(() => { el.textContent = texto; }, 30);
}

export function abrirModal(titulo, conteudo) {
  const m = document.getElementById("modal");
  document.getElementById("modal-titulo").textContent = titulo;
  const corpo = document.getElementById("modal-corpo");
  corpo.replaceChildren(conteudo);
  corpo.scrollTop = 0;
  if (!m.open) m.showModal();
  return corpo;
}

export function iniciarModal() {
  const m = document.getElementById("modal");
  const fechar = m.querySelector("[data-fechar]");
  fechar.replaceChildren(icone("fechar"));
  fechar.addEventListener("click", () => m.close());
  m.addEventListener("click", (e) => { if (e.target === m) m.close(); });
}

export function limpar(el) { el.replaceChildren(); return el; }

// ---------------------------------------------------------------- demonstração (regra de honestidade)
// Operação sintética (demo ou golden set): faixa fina no topo e selo discreto fixo no canto. Nenhuma tela de
// demonstração pode sugerir irregularidade de um produtor real. A faixa também diz quando as respostas do modelo
// vêm de uma gravação (replay) ou quando há ferramentas simuladas.
const FAIXA = { demo: null, modo: [] };

export function definirDemo(bloco) {
  FAIXA.demo = bloco || null;
  renderFaixa();
}

export function definirAvisosModo(lista) {
  FAIXA.modo = lista || [];
  renderFaixa();
}

function renderFaixa() {
  const el = document.getElementById("faixa-demo");
  const selo = document.getElementById("selo-demo");
  if (!el) return;
  const d = FAIXA.demo;
  const partes = [];
  if (d) {
    partes.push(h("strong", {}, d.marca_dagua || "DEMONSTRAÇÃO — dados sintéticos"),
      h("span", { class: "faixa-sub" }, "Operação fictícia; não descreve nenhum produtor real."));
  }
  for (const m of FAIXA.modo) {
    if (partes.length) partes.push(h("span", { class: "faixa-sep", "aria-hidden": "true" }, "·"));
    partes.push(h("span", { class: "faixa-sub", title: m.dica || null }, m.curto));
  }
  el.hidden = !partes.length;
  if (partes.length) {
    // o texto vai num bloco só: no celular ele cabe numa linha (com reticências) e o "Saiba mais" abre o aviso inteiro
    el.replaceChildren(h("span", { class: "faixa-txt" }, icone("info", "faixa-ic"), ...partes),
      h("button", { class: "faixa-mais", type: "button", onclick: sobreDemonstracao }, "Saiba mais"));
  }
  if (selo) {
    selo.hidden = !d;
    selo.replaceChildren(icone("selo"), h("span", {}, "Demonstração"), h("small", {}, "dados sintéticos"));
  }
  window.dispatchEvent(new Event("lv:topo"));
}

function sobreDemonstracao() {
  const d = FAIXA.demo;
  abrirModal("Sobre esta demonstração", h("div", { class: "texto" },
    d ? h("p", {}, h("strong", {}, `${d.marca_dagua}. `), d.aviso || "") : null,
    FAIXA.modo.map((m) => h("p", {}, m.longo || m.curto)),
    h("p", { class: "nota" }, "Prioridade de verificação não é indício de irregularidade.")));
}

// Bloco de aviso (pacote de exibição, laudo): o texto da demonstração inteiro, sem marca d'água na tela.
export function faixaDemonstracao(bloco) {
  if (!bloco) return null;
  return h("div", { class: "demo-faixa", role: "note" }, icone("info"),
    h("div", {}, h("strong", {}, bloco.marca_dagua), " ", bloco.aviso || ""));
}

// ---------------------------------------------------------------- gaveta "Detalhes técnicos"
// Estado do modelo, ferramentas, etapas da máquina de estados, decisões da política e trace: tudo o que a banca quer
// ver e o fiscal não precisa ler. Cada tela registra as suas seções; a gaveta junta e mostra.
const TEC = new Map();

export function secaoTecnica(chave, construir) {
  if (construir) TEC.set(chave, construir);
  else TEC.delete(chave);
  const g = document.getElementById("tecnico");
  if (g && !g.hidden) renderTecnico();
}

function renderTecnico() {
  const corpo = document.getElementById("tecnico-corpo");
  if (!corpo) return;
  const ordem = ["sistema", "fis", "laudo"];
  const chaves = [...TEC.keys()].sort((a, b) => (ordem.indexOf(a) + 9) % 9 - (ordem.indexOf(b) + 9) % 9);
  const nos = [];
  for (const k of chaves) {
    try { nos.push(TEC.get(k)()); } catch (e) { nos.push(h("p", { class: "nota" }, `seção ${k}: ${e.message}`)); }
  }
  corpo.replaceChildren(...nos);
}

export function abrirTecnico(abrir) {
  const g = document.getElementById("tecnico");
  const b = document.getElementById("btn-tecnico");
  if (!g) return;
  const vai = abrir === undefined ? g.hidden : !!abrir;
  if (vai) renderTecnico();
  g.hidden = !vai;
  b?.setAttribute("aria-expanded", vai ? "true" : "false");
  if (vai) g.querySelector("[data-fechar-tec]")?.focus({ preventScroll: true });
  else if (document.activeElement && g.contains(document.activeElement)) b?.focus({ preventScroll: true });
}

export function tecnicoAberto() {
  const g = document.getElementById("tecnico");
  return !!g && !g.hidden;
}

// Uma seção da gaveta: título + conteúdo.
export function blocoTec(titulo, ...conteudo) {
  return h("section", { class: "tec-sec" }, h("h3", {}, titulo), ...conteudo);
}

// ---------------------------------------------------------------- textos
// Descrições do Sicor são longas ("Aquisição de 29 vacas … — Sicor: AQUISIÇÃO DE ANIMAIS — …"): na tela vai a
// primeira parte; o texto inteiro fica no atributo title.
export function curto(texto, max = 64) {
  const t = String(texto || "");
  let c = t.split(/ — Sicor:| — | \(projeto sintético;/)[0];
  if (c.length > max) c = `${c.slice(0, max - 1).trimEnd()}…`;
  return c;
}

// "Por que está na amostra": abertura da prioridade de verificação (motivos de laudo.geo.triagem com código, pontos
// e critério). `amostra` = estado.amostra ou operacao.amostra da carteira. Nunca acusa: o aviso vai junto.
export function aberturaAmostra(amostra, { aberto = false, titulo = "Por que está na amostra" } = {}) {
  if (!amostra) return null;
  const corpo = [];
  if (!amostra.tem_triagem) corpo.push(h("p", { class: "nota" }, amostra.resumo || "sem triagem registrada"));
  if (amostra.motivos?.length) {
    // o código do critério (LOTACAO_ALTA) fica no title: na tela vão o nome do critério e os pontos por extenso
    corpo.push(h("ul", { class: "motivos-amostra" }, amostra.motivos.map((m) => h("li", { title: m.codigo ? `critério ${m.codigo}` : null },
      m.titulo ? h("strong", {}, `${m.titulo}: `) : null, m.texto,
      m.pontos !== null && m.pontos !== undefined ? h("span", { class: "pontos-amostra" }, `${m.pontos} ${m.pontos === 1 ? "ponto" : "pontos"}`) : null,
      m.criterio ? h("div", { class: "nota" }, `Como se calcula: ${semCaminho(m.criterio)}`) : null))));
  }
  (amostra.observacoes || []).forEach((o) => corpo.push(h("p", { class: "nota" }, `Observação (não pontua): ${o}`)));
  if (amostra.regra_nivel) {
    corpo.push(h("p", { class: "nota", title: amostra.nota || null },
      `Faixas de prioridade: ${String(amostra.regra_nivel).replace(/(\d+) ponto\(s\)/g, (m, n) => `${n} ${n === "1" ? "ponto" : "pontos"}`)}. ${semCaminho(amostra.nota || "")}`));
  }
  corpo.push(h("p", { class: "nota aviso-nao-indicio" }, icone("info"),
    h("strong", {}, amostra.aviso || "Prioridade de verificação não é indício de irregularidade.")));
  const pontos = amostra.pontos !== null && amostra.pontos !== undefined ? ` · ${amostra.pontos} pt` : "";
  const nivel = amostra.nivel_rotulo ? `prioridade ${amostra.nivel_rotulo}${pontos}` : "sem triagem";
  return h("details", { class: "abertura-amostra", open: aberto || null, onclick: (e) => e.stopPropagation() },
    h("summary", { title: titulo }, icone("direita", "seta-det"), icone("info", "ic-amostra"), h("span", { class: "rot-amostra" }, titulo),
      h("span", { class: "nivel-amostra" }, nivel)),
    h("div", { class: "abertura-corpo" }, ...corpo));
}

// "(laudo.geo.triagem.LIMIARES)" e outros caminhos de configuração saem do texto da tela.
function semCaminho(t) {
  return String(t || "").replace(/\s*\((?:[a-z_]+\.)+[A-Za-z_]+\)/g, "").replace(/\s{2,}/g, " ").trim();
}

// Rótulos legíveis (L98): mesmos nomes de `src/laudo/tools/laudo.py` (ROTULO_FERRAMENTA, ROTULO_TIPO_EVIDENCIA). O
// id técnico fica no atributo title (passar o mouse), não no texto da tela.
export const ROT_FERRAMENTA = {
  contar_bovinos_video: "Contagem no vídeo", conciliar_nfe: "Conciliação da NF-e", conciliar_gta: "Conciliação da GTA",
  integridade_foto: "Integridade da foto", geofence: "Foto na gleba", classificar_foto: "Classificação da foto",
  serie_ndvi: "Série NDVI (satélite)", planejar_metodo: "Plano de método", avaliar_regras: "Regras do MCR",
  checar_lotacao: "Lotação", ler_documento_foto: "Leitura da foto do documento",
  completar_leitura_documento: "Campos lidos pela fiscal", conciliar_alegacoes: "Alegações × evidência",
  carregar_operacao: "Operação (Sicor)", explicar_regra: "Explicação da regra", declaracao_conclusao: "Declaração do fiscal",
  declaracao_independencia: "Declaração de independência", registrar_conclusao_obra: "Conclusão da obra (fiscal)",
  registrar_justificativa: "Justificativa do fiscal", emitir_rascunho: "Emissão do rascunho",
  solicitar_assinatura: "Envio para assinatura", registrar_ocorrencia: "Registro de ocorrência",
};
export const ROT_TIPO_EV = { video: "Vídeo", foto: "Foto", nfe_xml: "NF-e (XML)", gta: "e-GTA", documento: "Documento",
  declaracao: "Fala do fiscal", ocorrencia: "Ocorrência", audio: "Áudio", quadro_chave: "Quadro-chave", satelite: "Cena de satélite" };
export const ROT_OCORRENCIA = { pressao: "Pressão", injecao: "Instrução embutida", fora_de_escopo: "Fora do escopo",
  falha_ferramenta: "Falha de ferramenta", outro: "Outro" };

// Texto para a tela sem ids técnicos crus (L98): "(item:bov1:quantidade)", "checagem chk_2d88ee1829" e
// "item:bov1:gta_data: " saem do texto exibido; "integridade_foto: ok" vira "Integridade da foto: ok" e um
// trecho repetido entre "; " aparece uma vez. O texto original fica no title de quem chama. Espelho de
// `laudo.formatacao.texto_sem_ids` (o laudo HTML para imprimir usa aquele).
export function semIds(texto) {
  const s = String(texto || "")
    .replace(/\s*\((?:item|documento|operacao|laudo)(?::[\w-]+)+\)/g, "")
    .replace(/\b(?:item|documento|laudo):[\w:-]+:\s+/g, "")
    .replace(/\s*(?:—\s*)?checagem\s+chk_[0-9a-z]+/gi, "")
    .replace(/\b(?:chk|ev|oc|alg|al)_[0-9a-z_]+\b/g, "")
    .replace(/\bautofiscalizacao_assistida\b/g, "autofiscalização assistida")
    .replace(/\b([a-z]+(?:_[a-z]+)*)(?=:\s)/g, (m) => ROT_FERRAMENTA[m] || m);
  // um trecho repetido aparece uma vez, mesmo quando a repetição é a última frase (com o ponto final)
  const partes = [];
  const vistas = new Set();
  for (const p of s.split("; ").map((x) => x.trim())) {
    const chave = p.replace(/[.\s]+$/, "");
    if (p && !vistas.has(chave)) { vistas.add(chave); partes.push(p); }
  }
  if (/\.\s*$/.test(s) && partes.length && !/[.!?]$/.test(partes.at(-1))) partes[partes.length - 1] += ".";
  return partes.join("; ")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:)])/g, "$1")
    .replace(/^[\s:;,.—-]+/, "")
    .trim();
}

// Texto do verificador em linguagem de gente (só na tela; o original fica no title de quem chama):
// "contagem 12 [12, 17] vs financiado 29 (limite 27,55)" vira "contados 12 (até 17), financiado 29, mínimo aceito
// 27,55"; a chave ilegível "??????…????" e o "indeterminado" saem; datas ISO viram dd/mm/aaaa.
export function legivel(texto) {
  let s = semIds(texto);
  s = s.replace(/contagem (\d+) \[(\d+), (\d+)\] vs financiado ([\d.,]+) \(limite ([\d.,]+)\)(:\s*abaixo do limite mesmo no extremo superior)?/gi,
    (m, c, a, b, f, l, abaixo) => `contados ${c} (até ${b}), financiado ${f}, mínimo aceito ${l}${abaixo ? `: mesmo ${b} fica abaixo do mínimo` : ""}`);
  s = s.replace(/^checagem inconclusiva \(\d+\/\d+\):\s*indeterminado\s*\((.*)\)\s*$/i, "Não deu para conferir: $1");
  s = s.replace(/^checagem inconclusiva \(\d+\/\d+\):\s*/i, "Não deu para conferir: ");
  s = s.replace(/\b(?:NF-e|chave)\s+[?…]{3,}[?…]*:\s*/g, "");
  s = s.replace(/\?{3,}[?…]*/g, "ilegível");
  s = s.replace(/\bindeterminado\b/gi, "não deu para conferir");
  s = s.replace(/(^|:\s)divergente \((.*)\)$/i, "$1$2"); // "GTA: divergente (GTA … antes da NF-e)" → "GTA: GTA … antes da NF-e"
  s = s.replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, "$3/$2/$1");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Valor de um aspecto do laudo para a tela: { rot, txt } ou null. Contagem: "Contados: 12 (até 17) · financiado 29";
// aspecto pendente mostra a referência ("Referência: financiado 29 · mínimo aceito 27,55"), nunca "Apurado".
export function valorLegivel(l) {
  const v = l?.valor;
  if (v && typeof v === "object" && !Array.isArray(v)) {
    if (v.contagem !== undefined && v.contagem !== null) {
      const max = Array.isArray(v.intervalo) ? v.intervalo[1] : null;
      return { rot: "Contados", txt: `${fmtNum(v.contagem)}${max !== null && max !== v.contagem ? ` (até ${fmtNum(max)})` : ""}` +
        (v.financiado !== undefined ? ` · financiado ${fmtNum(v.financiado)}` : "") };
    }
    if (l.status === "pendente" && v.financiado !== undefined) {
      return { rot: "Referência", txt: `financiado ${fmtNum(v.financiado)}` +
        (v.limite_inferior !== undefined ? ` · mínimo aceito ${fmtNum(v.limite_inferior)}` : "") };
    }
  }
  const f = l?.valor_fmt && l.valor_fmt !== "—" ? String(l.valor_fmt).replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, "$3/$2/$1") : null;
  if (!f) return null;
  return { rot: l.status === "pendente" ? "Referência" : "Apurado", txt: f };
}

// Motivo de um aspecto em uma frase curta (o texto cru do verificador vai no title). Na contagem, o valor já está na
// linha: o motivo diz só o mínimo aceito e a conclusão.
export function motivoLegivel(l) {
  const v = l?.valor;
  const m = String(l?.motivo || "");
  if (v && typeof v === "object" && v.contagem !== undefined && v.limite_inferior !== undefined) {
    const max = Array.isArray(v.intervalo) ? v.intervalo[1] : v.contagem;
    const tol = v.tolerancia_pct !== undefined ? ` (tolerância de ${fmtNum(v.tolerancia_pct)}%)` : "";
    const fim = /abaixo do limite mesmo/i.test(m) ? ` Mesmo ${fmtNum(max)} fica abaixo.` : "";
    return `Mínimo aceito: ${fmtNum(v.limite_inferior)}${tol}.${fim}`;
  }
  const t = legivel(m);
  return l?.status === "pendente" ? t.replace(/^Evidência ausente:\s*/i, "Falta: ") : t;
}

export function rotuloFerramenta(nome) {
  return ROT_FERRAMENTA[nome] || String(nome || "").replaceAll("_", " ");
}

// Id de regra (MCR-2-7-item16-benfeitorias-conclusao) com quebra só nos hífens, nunca no meio da palavra.
export function regraQuebravel(id) {
  const el = h("span", { class: "regra-id", translate: "no" });
  String(id || "").split("-").forEach((parte, i) => {
    if (i) el.append("-", h("wbr"));
    el.append(parte);
  });
  return el;
}

// Regra curta para a tela: "MCR-2-7-item16-benfeitorias-conclusao" e "PROVISORIO/MCR-2-7" viram "MCR 2-7";
// "POL-01/OP-…" vira "POL-01"; "OP-bovinos-gta" vira "Regra operacional". O id inteiro vai na dica.
export function regraCurta(id) {
  const s = String(id || "");
  if (!s) return "";
  const mcr = s.match(/MCR[-\s]?(\d+)-(\d+)/i);
  if (mcr) return `MCR ${mcr[1]}-${mcr[2]}`;
  const pol = s.match(/POL-(\d+)/);
  if (pol) return `POL-${pol[1]}`;
  if (/^OP-/.test(s)) return "Regra operacional";
  return s.split(/[-/]/).slice(0, 2).join(" ");
}

const DICA_POL = { "POL-00": "Política: ação permitida na etapa", "POL-01": "Política: evidência mínima antes de emitir",
  "POL-02": "Política: divergência exige justificativa do fiscal", "POL-03": "Política: a assinatura é sempre humana",
  "POL-04": "Política: laudo selado não muda", "POL-06": "Política: instrução embutida em documento é dado, não comando",
  "POL-07": "Política: valor só muda com nova evidência" };

export function chipRegra(id) {
  if (!id) return null;
  const curtaR = regraCurta(id);
  const pol = curtaR.startsWith("POL-") ? DICA_POL[curtaR] : null;
  const prov = /PROVISORIO/i.test(id) ? " (provisória, até o método ser definido)" : "";
  return h("span", { class: "regra-chip", title: `${pol ? `${pol} · ` : ""}regra ${id}${prov}`, translate: "no" }, curtaR);
}

// Pede ao topo que recarregue /api/saude (estado do modelo e da gravação) — L34.
export function atualizarSaude() {
  window.dispatchEvent(new Event("lv:saude"));
}

const ROT_CHECK = { presente: "presente", parcial: "parcial", ausente: "ausente", nao_aplicavel: "não aplicável" };

export function chipChecklist(status) {
  return h("span", { class: `st st-chk-${status}` }, ROT_CHECK[status] || status);
}

// Copiar para a área de transferência, com aviso.
export async function copiar(texto, rotulo = "Copiado") {
  try { await navigator.clipboard.writeText(texto); avisar(`${rotulo}.`); } catch { avisar("Não consegui copiar; selecione o texto.", true); }
}
