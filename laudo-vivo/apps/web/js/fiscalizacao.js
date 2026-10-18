// Tela da fiscalização (fiscal de campo). A conversa com o agente fica no centro, com o compositor fixo embaixo
// (anexar Foto, Vídeo, NF-e, GTA, Nota impressa; microfone; texto). Ao lado, o painel "Laudo" com o progresso por
// item, o que falta para emitir e o botão principal; à esquerda (ou numa aba), as evidências enviadas. Clicar num
// item abre a prova numa gaveta. Avisos da política e das guardas entram na conversa como cartões de sistema. O
// técnico (etapas, ações, decisões da política, trace) vai para a gaveta "Detalhes técnicos".

import { api, postForm, postFormProgresso } from "./api.js";
import { miniMapa } from "./mapa.js";
import { aberturaAmostra, abrirModal, anunciar, atualizarSaude, avisar, blocoTec, chipRegra, chipStatus, curto, definirDemo,
  fmtData, fmtNum, h, icone, legivel, motivoLegivel, rotuloFerramenta, secaoTecnica, semIds, valorLegivel } from "./ui.js";
import { Gravador, lerGPS, tts } from "./voz.js";

const ROT_TIPO = { video: "Vídeo", foto: "Foto", nfe_xml: "NF-e (XML)", gta: "e-GTA", documento: "Nota impressa / documento",
  audio: "Áudio", quadro_chave: "Quadro-chave" };
const IC_TIPO = { video: "video", foto: "camera", nfe_xml: "xml", gta: "gta", documento: "nota", quadro_chave: "galeria" };
// A GTA eletrônica é o JSON; PDF ou foto da GTA vão como documento em papel (o servidor também converte, L38)
const ACEITA = { foto: "image/*", video: "video/*", nfe_xml: ".xml,text/xml,application/xml", gta: ".json,application/json",
  documento: ".pdf,image/*" };
const ANEXOS = [
  { k: "foto", rot: "Foto", ic: "camera", opcoes: [{ tipo: "foto", rot: "Tirar ou escolher uma foto", captura: true }] },
  { k: "video", rot: "Vídeo", ic: "video", opcoes: [{ tipo: "video", rot: "Gravar ou escolher um vídeo", captura: true }] },
  { k: "nfe", rot: "NF-e", ic: "xml", opcoes: [{ tipo: "nfe_xml", rot: "Escolher o XML da NF-e" }] },
  { k: "gta", rot: "GTA", ic: "gta", opcoes: [{ tipo: "gta", rot: "Escolher a e-GTA (JSON)" },
    { tipo: "documento", rot: "GTA em papel (foto ou PDF)", item: "gta" }] },
  { k: "papel", rot: "Nota impressa", ic: "nota", opcoes: [{ tipo: "documento", rot: "Fotografar a nota impressa (DANFE)" }] },
];
const TIPOS_ANEXO = { foto: ["foto"], video: ["video"], nfe: ["nfe_xml"], gta: ["gta"], papel: ["documento"] };
const STATUS_ENVIO = { video: "Contando os animais no vídeo…", documento: "Lendo o documento…", nfe_xml: "Conferindo a NF-e…",
  gta: "Conferindo a GTA…", foto: "Conferindo a foto e a localização…" };
const PRIORIDADE_EVENTO = { bloqueio: 0, abstencao: 1, pressao: 2, injecao: 2, assinatura: 2, selado: 3, negado: 3,
  divergencia: 4, emitido: 5, justificativa: 5, pendente: 6, verificado: 7, ocorrencia: 8 };
const IC_EVENTO = { bloqueio: "cadeado", abstencao: "abstencao", pressao: "escudo", injecao: "escudo", assinatura: "escudo",
  selado: "cadeado", negado: "cadeado", divergencia: "divergente", emitido: "doc", pendente: "pendente",
  verificado: "verificado", ocorrencia: "info", justificativa: "alerta", guarda: "escudo" };
// Texto curto, sem jargão, para cada aviso da política (o texto técnico fica na dica)
const EXPLICA = {
  pressao: "O valor só muda com nova evidência. O pedido ficou registrado.",
  injecao: "O documento trazia uma instrução escondida; ela foi tratada como dado, não como ordem.",
  assinatura: "Só o fiscal assina, com PIN, depois de conferir o hash.",
  selado: "O laudo está selado: correção só com uma nova fiscalização.",
  negado: "A política não permitiu esta ação.",
};
const NIVEL_FORTE = ["bloqueio", "abstencao", "divergente"];
// Guardas que funcionaram (pressão recusada, instrução ignorada, o agente não assina, laudo selado não muda): são uma
// garantia, não uma falha. Ficam em ardósia com escudo; o vermelho fica só para o bloqueio por falta de evidência.
const GUARDA = new Set(["pressao", "injecao", "assinatura", "selado", "negado"]);
// O que a fiscal envia em cada passo do roteiro que não tem fala (a barra mostra isto, não o nome do arquivo)
const ENVIO_TIPO = { nfe_xml: "a fiscal anexa o XML da NF-e da compra", gta: "a fiscal anexa a e-GTA da compra",
  video: "a fiscal envia o vídeo do lote", foto: "a fiscal envia a foto", documento: "a fiscal fotografa a nota impressa" };

let S = null; // estado da tela

export function sairFiscalizacao() {
  if (!S) return;
  clearTimeout(S.tReinicio);
  S.obsRoteiro?.disconnect();
  document.removeEventListener("keydown", S.teclaDown);
  document.removeEventListener("keyup", S.teclaUp);
  document.removeEventListener("pointerdown", S.foraMenu, true);
  window.removeEventListener("lv:layout", S.aoLayout);
  S.gravador?.liberar();
  S.miniMapa?.remove?.();
  S = null;
  secaoTecnica("fis", null);
}

export async function telaFiscalizacao(raiz, fisId, { irLaudo, saude, campo = null }) {
  sairFiscalizacao();
  raiz.replaceChildren(h("p", { class: "carregando" }, "Carregando a fiscalização…"));
  let estado;
  try { estado = await api.estado(fisId); } catch (e) {
    raiz.replaceChildren(h("div", { class: "vazio grande" }, h("p", {}, `Não encontrei a fiscalização ${fisId}.`), h("p", { class: "nota" }, e.message),
      h("a", { class: "btn btn-pri", href: "#/carteira" }, "Voltar à carteira")));
    return;
  }
  S = { id: fisId, estado, raiz, selecionado: null, painel: "laudo", movel: "conversa", ocupado: false, eventos: [],
    metaTurno: {}, gravador: null, saude, irLaudo, confirmacao: estado.confirmacao_pendente || null, evTurno: {},
    pendente: null, progresso: null, ultimoLat: "", falhou: null, expandido: {}, confirmarReinicio: false, alvosChat: null };
  carregarEventos(estado);
  montar();
  atualizar(estado, estado.ultimos_eventos || []);
  if (campo && (estado.matriz || []).some((l) => l.campo === campo)) selecionar(campo);
  atualizarSaude();
}

// Os cartões de sistema de cada turno ficam guardados nesta aba do navegador (sessionStorage): a API devolve só os
// eventos do último turno.
function chaveEv() { return `lv.ev.${S.id}`; }
function carregarEventos(estado) {
  try { S.evTurno = JSON.parse(sessionStorage.getItem(chaveEv()) || "{}") || {}; } catch { S.evTurno = {}; }
  const conv = estado.conversa || [];
  if (!conv.length) S.evTurno = {};
  const ult = conv.at(-1)?.turno;
  if (ult !== undefined && estado.ultimos_eventos?.length && !S.evTurno[ult]) S.evTurno[ult] = estado.ultimos_eventos;
}
function salvarEventos() {
  try { sessionStorage.setItem(chaveEv(), JSON.stringify(S.evTurno)); } catch { /* armazenamento indisponível */ }
}

// ---------------------------------------------------------------- montagem
function montar() {
  const el = {};
  S.el = el;
  el.opCab = h("div", { class: "op-cab", id: "op-cab" });

  // conversa
  el.chat = h("div", { class: "chat", role: "log", "aria-label": "Conversa com o agente", "aria-live": "off" });
  el.texto = h("textarea", { id: "fala", rows: "1", placeholder: "Escreva para o agente…", title: "Enter envia; Shift+Enter quebra a linha", "aria-label": "Mensagem para o agente" });
  el.texto.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarTexto(); }
  });
  el.texto.addEventListener("input", () => ajustarAltura(el.texto));
  el.enviar = h("button", { class: "btn btn-pri btn-enviar", type: "button", onclick: enviarTexto, "aria-label": "Enviar mensagem", title: "Enviar (Enter)" },
    icone("enviar"));
  const motivoMic = Gravador.motivoIndisponivel();
  const asrOk = S.saude?.asr?.disponivel !== false;
  el.falar = h("button", { class: "btn btn-mic", type: "button", "aria-pressed": "false", disabled: motivoMic || !asrOk ? true : null,
    "aria-label": "Segure para falar",
    title: motivoMic || (!asrOk ? "Voz desligada neste modo: digite a mensagem" : "Segure para falar (ou segure a barra de espaço)") },
  icone("mic"), h("span", { class: "so-leitor rot-mic" }, "Segure para falar"));
  el.nivel = h("div", { class: "gravando", hidden: true, role: "status" }, h("span", { class: "rec", "aria-hidden": "true" }),
    h("span", {}, "Gravando… solte para enviar"), h("div", { class: "nivel", "aria-hidden": "true" }, h("i")));
  ligarFalar(el.falar);
  el.anexos = h("div", { class: "anexos", role: "group", "aria-label": "Anexar evidência" },
    ANEXOS.map((d) => h("button", { class: "chip-anexo", type: "button", "aria-haspopup": "dialog", dataset: { k: d.k },
      title: `Anexar ${d.rot}`, onclick: (e) => abrirMenuAnexo(d, e.currentTarget) }, icone(d.ic), h("span", { class: "rot-chip" }, d.rot))));
  // no celular, um botão de clipe no lugar da fileira de chips: abre a folha com Foto, Vídeo, NF-e, GTA e Nota
  el.clipe = h("button", { class: "btn btn-clipe", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false",
    "aria-label": "Anexar evidência (foto, vídeo, NF-e, GTA ou nota)", title: "Anexar evidência", onclick: (e) => abrirMenuTodos(e.currentTarget) },
  icone("clipe"));
  el.menu = h("div", { class: "menu-anexo", hidden: true, role: "dialog", "aria-label": "Anexar evidência" });
  el.menuVoz = h("div", { class: "menu-voz", hidden: true, role: "dialog", "aria-label": "Preferências de voz" });
  el.btnVoz = h("button", { class: "btn btn-fantasma btn-peq", type: "button", "aria-expanded": "false",
    onclick: () => alternarMenuVoz() }, icone("ajustes"), h("span", { class: "rot" }, "Voz"));
  el.confNum = h("input", { type: "checkbox", id: "confnum", checked: true });
  el.ttsChk = h("input", { type: "checkbox", id: "tts", checked: tts.ligado() ? true : null, disabled: tts.disponivel() ? null : true });
  el.ttsChk.addEventListener("change", () => tts.ligar(el.ttsChk.checked));
  el.vozSel = h("select", { id: "voz-sel", "aria-label": "Voz do agente" });
  preencherVozes(el.vozSel);
  if ("speechSynthesis" in window) speechSynthesis.addEventListener?.("voiceschanged", () => preencherVozes(el.vozSel));
  el.vozSel.addEventListener("change", () => tts.escolher(el.vozSel.value));
  el.menuVoz.append(
    h("div", { class: "menu-cab" }, h("strong", {}, "Voz"),
      h("button", { class: "btn btn-icone btn-fantasma btn-peq fechar-menu", type: "button", "aria-label": "Fechar", onclick: () => alternarMenuVoz(false) },
        icone("fechar"))),
    h("label", { class: "opcao", for: "tts" }, el.ttsChk, h("span", {}, icone("som"), "Resposta falada")),
    h("div", { class: "campo" }, h("label", { for: "voz-sel" }, "Voz do agente"), el.vozSel),
    h("label", { class: "opcao", for: "confnum" }, el.confNum, h("span", {}, "Confirmar números falados antes de enviar")));

  const avisoLongo = "Sessão gravada: a fala é transcrita neste computador e entra na trilha. Avise quem estiver presente.";
  const colConversa = h("section", { class: "col col-conversa", "aria-labelledby": "t-conv", id: "col-conversa" },
    h("div", { class: "conv-cab" },
      h("div", { class: "conv-tt" }, h("span", { class: "avatar ag", "aria-hidden": "true" }, icone("agente")),
        h("div", {}, h("h2", { id: "t-conv" }, "Conversa com o agente"),
          h("p", { class: "nota" }, "O agente pede evidências e confere; o status vem do verificador, não do modelo."))),
      h("div", { class: "conv-acoes" }, el.btnVoz)),
    el.menuVoz,
    el.chat,
    h("div", { class: "compositor" },
      el.menu,
      el.nivel,
      h("div", { class: "linha-comp" },
        el.anexos,
        h("div", { class: "escrever" }, el.clipe, el.texto, el.falar, el.enviar)),
      h("p", { class: "aviso-gravacao", role: "note", title: avisoLongo }, icone("mic"),
        h("span", { class: "ag-longo" }, avisoLongo),
        h("span", { class: "ag-curto", "aria-hidden": "true" }, "Sessão gravada: a fala entra na trilha. Avise quem estiver presente."))));
  el.veu = h("div", { class: "veu-menu", hidden: true, "aria-hidden": "true", onclick: () => { fecharMenus(); alternarMenuVoz(false); } });

  // painel do laudo
  el.progTxt = h("span", { class: "prog-txt" });
  el.barra = h("div", { class: "barra-prog", role: "img" });
  el.contadores = h("div", { class: "contadores" });
  el.matriz = h("div", { class: "matriz-wrap" });
  el.emitir = h("div", { class: "emitir" });
  // no tablet e no modo apresentação o painel alterna entre Laudo e Evidências por este botão do cabeçalho
  el.paraEvid = h("button", { class: "btn btn-sec btn-peq troca-painel", type: "button", "aria-controls": "col-evid",
    onclick: () => trocarPainel("evid") }, icone("galeria"), h("span", { class: "rot-troca" }, "Evidências"));
  el.paraLaudo = h("button", { class: "btn btn-sec btn-peq troca-painel", type: "button", "aria-controls": "col-itens",
    onclick: () => trocarPainel("laudo") }, icone("voltar"), "Laudo");
  const colItens = h("section", { class: "col col-itens painel", "aria-labelledby": "t-itens", id: "col-itens" },
    h("div", { class: "painel-cab" }, h("div", { class: "painel-tt" }, h("h2", { id: "t-itens" }, "Laudo"), el.progTxt), el.paraEvid),
    h("div", { class: "painel-resumo" }, el.barra, el.contadores),
    el.matriz,
    el.emitir);

  // evidências
  el.evid = h("div", { class: "evid-corpo" });
  el.evidN = h("span", { class: "nota" });
  const colEvid = h("section", { class: "col col-evid painel", "aria-labelledby": "t-evid", id: "col-evid" },
    h("div", { class: "painel-cab" }, h("h2", { id: "t-evid" }, "Evidências"), el.evidN, el.paraLaudo), el.evid);

  // abas do celular
  el.abasMovel = h("div", { class: "abas-movel", role: "tablist", "aria-label": "Partes da tela" });

  // gaveta da prova do item
  el.prova = h("div", { class: "prova-corpo", id: "painel-dir" });
  el.fecharProva = h("button", { class: "btn btn-icone btn-fantasma fechar-prova", type: "button", "aria-label": "Fechar a prova (Esc)",
    title: "Fechar (Esc)", onclick: () => abrirGaveta(false) }, icone("fechar"));
  const colProva = h("section", { class: "gaveta-prova", "aria-labelledby": "t-prova", id: "col-prova" },
    h("div", { class: "gaveta-cab" }, h("div", {}, h("p", { class: "sobre" }, "Prova do item"), h("h2", { id: "t-prova" }, "—")), el.fecharProva),
    el.prova);
  el.tituloProva = colProva.querySelector("#t-prova");

  el.grade = h("div", { class: "fis", dataset: { painel: "laudo", movel: "conversa" } }, colEvid, colConversa, colItens, colProva);
  el.roteiro = h("div", { class: "roteiro", hidden: true, role: "region", "aria-label": "Controle da demonstração" });
  // a tela reserva embaixo a altura real da barra (--rot-h): ela nunca cobre as colunas
  if ("ResizeObserver" in window) {
    S.obsRoteiro = new ResizeObserver(() => document.documentElement.style.setProperty("--rot-h", `${el.roteiro.offsetHeight || 0}px`));
    S.obsRoteiro.observe(el.roteiro);
  }
  el.tela = h("div", { class: "tela-fis" }, el.opCab, el.abasMovel, el.grade, el.roteiro, el.veu);
  S.raiz.replaceChildren(el.tela);

  S.teclaDown = (e) => {
    const alvo = e.target;
    const editavel = alvo && (alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName));
    if (document.getElementById("modal").open) return;
    if (e.key === "Escape") {
      if (!S.el.menu.hidden) { fecharMenus(true); return; }
      if (!S.el.menuVoz.hidden) { alternarMenuVoz(false); return; }
      if (S.el.grade.classList.contains("prova-aberta")) { abrirGaveta(false); return; }
      const amostra = S.el.opCab.querySelector("details[open]");
      if (amostra) { amostra.open = false; amostra.querySelector("summary")?.focus(); return; }
    }
    if (!editavel && (e.key === "ArrowRight" || e.key === "PageDown") && S.estado.roteiro && !e.repeat) {
      e.preventDefault(); proximoPasso();
    } else if (!editavel && e.code === "Space" && !alvo.closest?.("button, a, tr, summary, label, [role=tab]") && !e.repeat && !el.falar.disabled) {
      e.preventDefault(); iniciarGravacao();
    }
  };
  S.teclaUp = (e) => {
    if (e.code === "Space" && S.gravando) { e.preventDefault(); pararGravacao(); }
  };
  S.foraMenu = (e) => {
    if (!S) return;
    const dono = (el) => el.contains(e.target);
    if (!S.el.menu.hidden && !dono(S.el.menu) && !dono(S.el.anexos) && !dono(S.el.clipe)) fecharMenus();
    if (!S.el.menuVoz.hidden && !dono(S.el.menuVoz) && !dono(S.el.btnVoz) && !dono(S.el.menu)) alternarMenuVoz(false);
    const amostra = S.el.opCab.querySelector("details[open]");
    if (amostra && !dono(amostra)) amostra.open = false;
  };
  S.aoLayout = () => { if (S) renderAbas(); };
  document.addEventListener("keydown", S.teclaDown);
  document.addEventListener("keyup", S.teclaUp);
  document.addEventListener("pointerdown", S.foraMenu, true);
  window.addEventListener("lv:layout", S.aoLayout);
}

function ajustarAltura(t) {
  t.style.height = "auto";
  t.style.height = `${Math.min(t.scrollHeight + 2, 160)}px`;
}

function preencherVozes(sel) {
  const vozes = tts.vozes();
  sel.replaceChildren(...(vozes.length ? vozes : [{ name: "voz padrão pt-BR", lang: "pt-BR" }]).map((v) =>
    h("option", { value: v.name, selected: tts.voz()?.name === v.name ? true : null }, `${v.name} (${v.lang})`)));
}

function alternarMenuVoz(abrir) {
  const m = S.el.menuVoz;
  const vai = abrir === undefined ? m.hidden : abrir;
  fecharMenus();
  m.hidden = !vai;
  S.el.btnVoz.setAttribute("aria-expanded", vai ? "true" : "false");
  S.el.veu.hidden = !vai;
  if (vai) m.querySelector("input, select")?.focus({ preventScroll: true });
}

// No celular os menus viram uma folha que sobe de baixo, com o fundo escurecido (o véu).
function ehMovel() { return window.matchMedia("(max-width: 767px)").matches; }

function fecharMenus(devolverFoco = false) {
  if (!S) return;
  const estavaAberto = !S.el.menu.hidden;
  S.el.menu.hidden = true;
  S.el.veu.hidden = S.el.menuVoz.hidden;
  S.el.anexos.querySelectorAll(".chip-anexo").forEach((b) => b.setAttribute("aria-expanded", "false"));
  S.el.clipe.setAttribute("aria-expanded", "false");
  if (estavaAberto && devolverFoco) (S.botaoMenu || S.el.texto).focus({ preventScroll: true });
}

// ---------------------------------------------------------------- abas (celular) e troca do painel
function renderAbas() {
  // a mesma conta em todo lugar: evidências que a fiscal enviou (os quadros-chave e o rascunho são do sistema)
  const n = evidenciasEnviadas().length;
  const falta = pendTotal();
  const tab = (k, t, atual, onclick, controla) => h("button", { type: "button", role: "tab", "aria-selected": atual === k ? "true" : "false",
    "aria-controls": controla, onclick: () => onclick(k) }, t);
  S.el.paraEvid.querySelector(".rot-troca").replaceChildren("Evidências", n ? h("span", { class: "contagem", title: `${n} enviada(s)` }, n) : "");
  S.el.abasMovel.replaceChildren(
    tab("conversa", "Conversa", S.movel, trocarMovel, "col-conversa"),
    tab("laudo", h("span", {}, "Laudo", falta && S.estado.etapa !== "BRIEFING"
      ? h("span", { class: "contagem alerta", title: `${falta} pendência(s) para emitir` }, `${falta} ${falta === 1 ? "falta" : "faltam"}`) : null),
    S.movel, trocarMovel, "col-itens"),
    tab("evid", h("span", {}, "Evidências", n ? h("span", { class: "contagem", title: `${n} enviada(s)` }, n) : null), S.movel, trocarMovel, "col-evid"));
}

function evidenciasEnviadas() {
  return (S.estado.evidencias || []).filter((e) => e.tipo !== "quadro_chave" && !e.laudo && !/^rascunho_/.test(e.nome || ""));
}

function pendTotal() { return faltas(S.estado).length; }

function trocarPainel(k) {
  const veioDoBotao = document.activeElement === S.el.paraEvid || document.activeElement === S.el.paraLaudo;
  S.painel = k;
  S.el.grade.dataset.painel = k;
  renderAbas();
  if (veioDoBotao) (k === "evid" ? S.el.paraLaudo : S.el.paraEvid).focus({ preventScroll: true });
}

function trocarMovel(k) {
  S.movel = k;
  S.el.grade.dataset.movel = k;
  renderAbas();
  if (k === "conversa") rolarChat();
  if (k === "laudo") ajustarMatriz();
}

// ---------------------------------------------------------------- atualização
function atualizar(estado, eventos, resp) {
  const anterior = S.estado;
  S.antes = Object.fromEntries((anterior?.matriz || []).map((l) => [l.campo, l.status]));
  S.estado = estado;
  if (eventos) S.eventos = eventos;
  if (resp && resp.turno !== undefined) {
    const chave = resp.turno || (resp.acoes?.[0]?.acao === "assinar" ? "assinatura" : "rascunho");
    S.metaTurno[chave] = resp;
  }
  const nav = document.getElementById("nav-fis");
  nav.hidden = false; nav.href = `#/fis/${estado.id}`;
  const navL = document.getElementById("nav-laudo");
  navL.hidden = !estado.laudo; navL.href = `#/fis/${estado.id}/laudo`;
  renderCabecalho();
  renderChat();
  renderPainel(anterior);
  renderEvidencias();
  renderAbas();
  if (S.el.grade.classList.contains("prova-aberta")) renderProva();
  renderRoteiro();
  secaoTecnica("fis", secaoFis);
}

const UN = { cabeca: "cabeças", UA_450kg: "UA", m: "m", ha: "ha", un: "un", m2: "m²" };
// "Aquisição de 29 vacas leiteiras (matrizes) — Sicor: …" vira "29 vacas leiteiras (matrizes)"
function nomeItem(desc, max = 60) {
  const c = curto(desc, 200).replace(/^(Aquisição|Construção|Compra|Implantação|Reforma) de /i, "");
  return c.length > max ? `${c.slice(0, max - 1).trimEnd()}…` : c;
}
const ROT_ITEM = { bovinos: "bovinos", cerca: "cerca" };

function renderCabecalho() {
  const e = S.estado; const op = e.operacao;
  definirDemo(e.demonstracao);
  const itens = op.itens.map((i) => `${fmtNum(i.quantidade)} ${UN[i.unidade] ?? i.unidade ?? ""}${ROT_ITEM[i.tipo] ? ` (${ROT_ITEM[i.tipo]})` : ""}`);
  const tri = e.triagem || {};
  const nivel = tri.prioridade_nivel || (e.amostra?.tem_triagem ? "media" : null);
  const rotNivel = { alta: "alta", media: "média", baixa: "baixa" }[nivel] || nivel;
  S.el.opCab.replaceChildren(
    h("div", { class: "op-id" },
      h("h1", { title: op.instituicao || null }, h("span", { class: "op-num" }, `Operação ${op.ref_bacen}`),
        e.demonstracao ? h("span", { class: "etiqueta fake" }, "fictícia") : null),
      h("div", { class: "op-meta" },
        h("span", { class: "op-mun" }, icone("pino"), h("span", {}, `${op.municipio_nome || "município ?"}/${op.uf}`)),
        h("span", { class: "op-valor" }, op.valor_fmt),
        h("span", { class: "op-itens", title: op.itens.map((i) => i.descricao).join("\n") }, `${op.itens.length} ${op.itens.length === 1 ? "item" : "itens"}: ${itens.join(" · ")}`),
        e.metodo ? h("span", { class: "op-metodo", title: "método de fiscalização definido pela regra" }, icone("lista"), e.metodo_rotulo || e.metodo) : null,
        h("span", { class: "op-inst" }, op.instituicao || ""))),
    h("div", { class: "op-lado" },
      nivel ? h("span", { class: `prio ${nivel}`, title: `Prioridade de verificação ${rotNivel} (não é indício de irregularidade)` },
        h("span", { class: `marcador mini ${nivel}`, "aria-hidden": "true" }, h("span", {}, { alta: "A", media: "M", baixa: "B" }[nivel] || "")),
        h("span", { class: "prio-rot" }, `Prioridade ${rotNivel}`),
        tri.prioridade_verificacao !== undefined ? h("span", { class: "prio-pt" }, `${tri.prioridade_verificacao} pt`) : null) : null,
      e.amostra?.tem_triagem ? aberturaAmostra(e.amostra, { titulo: "Por que está na amostra" })
        : tri.motivos?.length ? h("span", { class: "nota" }, tri.motivos.join("; ")) : null));
}

// ---------------------------------------------------------------- conversa
// Rolagem do chat depois de cada turno: se o turno inteiro cabe, vai até o fim; se não cabe, o começo do turno fica à
// vista (a fala do fiscal, a resposta do agente ou, quando há, o cartão que importa: bloqueio, divergência, "Complete
// a nota"). Nunca deixa o título do cartão mais importante cortado em cima.
function rolarChat(alvos) {
  if (alvos !== undefined) S.alvosChat = alvos;
  const aplicar = () => {
    if (!S) return;
    const chat = S.el.chat;
    const fim = Math.max(0, chat.scrollHeight - chat.clientHeight);
    const { ancora, agente, forte, forteFim } = S.alvosChat || {};
    if (!ancora || !ancora.isConnected || !chat.clientHeight) { chat.scrollTop = fim; return; }
    const base = chat.getBoundingClientRect().top - chat.scrollTop;
    const y = (el) => el.getBoundingClientRect().top - base - 8; // 8 px de folga em cima
    const alt = chat.clientHeight;
    if (chat.scrollHeight - y(ancora) <= alt) { chat.scrollTop = fim; return; }
    // até onde precisa caber: o cabeçalho do último cartão importante (com dois, como a instrução ignorada e a
    // divergência da GTA, os dois títulos ficam à vista), ou o começo da resposta do agente
    const fimImp = forteFim && forteFim.isConnected ? forteFim : forte;
    const limite = fimImp ? y(fimImp) + 8 + Math.min(fimImp.offsetHeight, fimImp === forte ? 110 : 56)
      : agente ? y(agente) + 8 + Math.min(agente.offsetHeight, 150) : chat.scrollHeight;
    const cands = [ancora, agente, forte].filter((c) => c && c.isConnected);
    const alvo = cands.find((c) => limite - y(c) <= alt) || cands.at(-1);
    chat.scrollTop = Math.max(0, Math.min(fim, y(alvo)));
  };
  aplicar();
  requestAnimationFrame(aplicar);
}

function hora(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function anexoChip(tipo, nome) {
  return h("div", { class: "anexo-msg" }, icone(IC_TIPO[tipo] || "doc"),
    h("span", {}, h("strong", {}, ROT_TIPO[tipo] || tipo), nome ? h("small", {}, nome) : null));
}

function bolhaFiscal(texto, { evidencia = null, nome = null, em = null, voz = false, pendente = false } = {}) {
  return h("div", { class: `msg fiscal${pendente ? " enviando" : ""}` },
    h("div", { class: "bolha" }, evidencia ? anexoChip(evidencia, nome) : null, texto ? h("div", { class: "txt" }, texto) : null),
    h("div", { class: "meta" }, voz ? h("span", { class: "etiqueta" }, "voz") : null, "Fiscal", em ? ` · ${hora(em)}` : "",
      pendente ? " · enviando…" : ""));
}

function ferramentasDoTurno(acoes) {
  const nomes = [];
  for (const a of acoes || []) {
    const [nome, st] = typeof a === "string" ? a.split(":") : [a.acao, a.permitido === false || a.ok === false ? "negado" : "ok"];
    if (!nome || st === "negado" || ["guarda", "evento", "assinar", "emitir_rascunho", "solicitar_assinatura"].includes(nome)) continue;
    const r = rotuloFerramenta(nome);
    if (!nomes.includes(r)) nomes.push(r);
  }
  return nomes;
}

// `recolher`: quando o turno traz um cartão forte (bloqueio, divergência), a resposta do agente fica em 2 linhas com
// "ver mais" — o cartão já mostra o que importa e a conversa não vira um muro de texto.
function bolhaAgente(c, { recolher = false } = {}) {
  const meta = S.metaTurno[c.turno] || null;
  const acoes = meta?.acoes || c.acoes || [];
  const ferr = ferramentasDoTurno(acoes);
  // a chave ilegível da foto ("??????…????????") vira "(ilegível)"; o texto original fica no title
  const limpo = semIds(c.agente).replace(/\?{3,}[?…]*/g, "(ilegível)");
  const podeRecolher = recolher && limpo.length > 150;
  const recolhido = podeRecolher && !S.expandido[c.turno];
  const txt = h("div", { class: `txt${recolhido ? " recolhido" : ""}`, title: c.agente !== limpo ? c.agente : null }, limpo);
  const alternar = podeRecolher ? h("button", { class: "link-btn ver-mais", type: "button", "aria-expanded": recolhido ? "false" : "true",
    onclick: () => {
      S.expandido[c.turno] = !S.expandido[c.turno];
      txt.classList.toggle("recolhido", !S.expandido[c.turno]);
      alternar.textContent = S.expandido[c.turno] ? "ver menos" : "ver mais";
      alternar.setAttribute("aria-expanded", S.expandido[c.turno] ? "true" : "false");
    } }, recolhido ? "ver mais" : "ver menos") : null;
  return h("div", { class: "msg agente" },
    h("span", { class: "avatar ag", "aria-hidden": "true" }, icone("agente")),
    h("div", { class: "corpo-msg" },
      h("div", { class: "bolha" }, txt, alternar,
        ferr.length ? h("div", { class: "conferido" }, icone("verificado"), `Conferido com: ${ferr.join(" · ")}`) : null),
      h("div", { class: "meta" }, "Agente", c.em ? ` · ${hora(c.em)}` : "")));
}

// Cartão de sistema: cabeçalho (ícone, título, regra) e corpo. `destaque` pinta a faixa do título (o momento que a
// banca precisa ver); o corpo fica sempre em fundo claro para ler.
function cartaoSis({ tipo, titulo: tt, regra = null, texto = null, dica = null, extra = [], destaque = false, forte = false,
  novo = false, compacto = false, icone: ic = "info", alerta = false }) {
  return h("div", { class: `sis sis-${tipo}${destaque ? " destaque" : ""}${forte ? " forte" : ""}${novo ? " novo" : ""}${compacto ? " compacto" : ""}`,
    role: alerta ? "alert" : null },
  h("div", { class: "sis-cab" }, h("span", { class: "sis-ic" }, icone(ic)), h("span", { class: "sis-tt" }, tt), regra ? chipRegra(regra) : null),
  texto || extra.length ? h("div", { class: "sis-corpo" }, texto ? h("div", { class: "sis-tx", title: dica || null }, texto) : null, extra) : null);
}

function cartaoSelado(c) {
  return cartaoSis({ tipo: "ok", icone: "selo", titulo: "Laudo assinado e selado",
    texto: semIds(c.agente) || "Assinatura humana com PIN e hash conferido.",
    extra: [h("a", { class: "btn btn-sec btn-peq", href: `#/fis/${encodeURIComponent(S.id)}/laudo` }, icone("doc"), "Ver laudo selado")] });
}

// Mensagem que não chegou ao servidor (4G ruim, servidor fora do ar): fica no chat com "Tentar de novo".
function bolhaFalhou(f) {
  const acoes = h("div", { class: "acoes-falha" },
    h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: tentarDeNovo }, icone("reiniciar"), "Tentar de novo"),
    h("button", { class: "btn btn-fantasma btn-peq", type: "button", onclick: descartarFalha }, "Descartar"));
  if (!f.texto && !f.evidencia) {
    return cartaoSis({ tipo: "falha", icone: "semrede", titulo: "O pedido não chegou ao servidor", texto: f.erro, extra: [acoes], alerta: true });
  }
  return h("div", { class: "msg fiscal falhou", role: "alert" },
    h("div", { class: "bolha" }, f.evidencia ? anexoChip(f.evidencia, f.nome) : null, f.texto ? h("div", { class: "txt" }, f.texto) : null),
    h("div", { class: "meta falha" }, icone("semrede"), h("span", {}, `Não enviada · ${f.erro}`)),
    acoes);
}

function tentarDeNovo() {
  const f = S?.falhou;
  if (!f || S.ocupado) return;
  S.falhou = null;
  if (f.restaurar && S.el.texto.value.trim() === f.restaurar) { S.el.texto.value = ""; ajustarAltura(S.el.texto); }
  f.repetir();
}

function descartarFalha() {
  S.falhou = null;
  renderChat();
}

function renderChat() {
  const conversa = S.estado.conversa || [];
  const ultimo = conversa.at(-1)?.turno;
  const nos = [];
  if (!conversa.length && !S.pendente) {
    nos.push(h("div", { class: "boas-vindas" },
      h("span", { class: "avatar ag grande", "aria-hidden": "true" }, icone("agente")),
      h("h3", {}, "Pronto para começar a fiscalização"),
      h("p", {}, "Cumprimente o agente e pergunte o que a regra pede. Ele explica por que a operação está na amostra, define o método e diz quais evidências faltam."),
      h("button", { class: "btn btn-sec", type: "button", onclick: () => { S.el.texto.value = "Bom dia. Por que esta operação caiu na amostra e qual método a regra pede?"; ajustarAltura(S.el.texto); S.el.texto.focus(); } },
        "Sugestão: “Por que esta operação caiu na amostra?”")));
  }
  // alvos da rolagem: começo do último turno, resposta do agente e o cartão que importa
  let ancora = null; let agente = null; let forte = null; let forteFim = null;
  for (const c of conversa) {
    const meta = S.metaTurno[c.turno] || null;
    const ehUltimo = c.turno === ultimo;
    if (c.turno === "assinatura") {
      const n = cartaoSelado(c);
      nos.push(n);
      if (ehUltimo) { ancora = n; agente = null; forte = null; }
      continue;
    }
    const evs = S.evTurno[c.turno];
    const cartoes = evs?.length ? cartoesSistema(evs, ehUltimo) : [];
    const imps = ehUltimo ? cartoes.filter((n) => n.classList.contains("forte") || n.classList.contains("destaque")) : [];
    const importante = imps[0] || null;
    if (c.fiscal || c.evidencia) {
      const b = bolhaFiscal(c.fiscal, { evidencia: c.evidencia, em: c.em, voz: meta?._origem === "asr" });
      nos.push(b);
      if (ehUltimo) ancora = b;
    }
    if (c.agente) {
      const a = bolhaAgente(c, { recolher: ehUltimo && cartoes.some((n) => n.classList.contains("forte")) });
      nos.push(a);
      if (ehUltimo) { agente = a; ancora = ancora || a; }
    }
    nos.push(...cartoes);
    if (ehUltimo) { forte = importante; forteFim = imps.at(-1) || null; ancora = ancora || cartoes[0] || null; }
  }
  if (S.falhou) { const b = bolhaFalhou(S.falhou); nos.push(b); ancora = b; agente = null; forte = null; forteFim = null; }
  if (S.pendente) {
    const b = bolhaFiscal(S.pendente.texto, { evidencia: S.pendente.evidencia, nome: S.pendente.nome, pendente: true });
    nos.push(b); ancora = b; agente = null; forte = null; forteFim = null;
  }
  if (S.confirmacao) { const n = cartaoConfirmacao(S.confirmacao); nos.push(n); forte = forte || n; forteFim = n; ancora = ancora || n; }
  else if (S.estado.residual && !S.ocupado) { const n = cartaoResidual(S.estado.residual); nos.push(n); forte = forte || n; forteFim = n; ancora = ancora || n; }
  if (S.ocupado) {
    nos.push(h("div", { class: "msg agente digitando", id: "pensando", role: "status" },
      h("span", { class: "avatar ag", "aria-hidden": "true" }, icone("agente")),
      h("div", { class: "corpo-msg" }, h("div", { class: "bolha" }, h("span", { class: "pontos", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
        h("span", {}, S.ocupadoTexto || "O agente está trabalhando…"),
        S.progresso !== null ? h("div", { class: "progresso" }, h("i", { style: `width:${Math.round(S.progresso * 100)}%` })) : null))));
  }
  S.el.chat.replaceChildren(h("div", { class: "chat-interno" }, nos));
  rolarChat({ ancora, agente, forte, forteFim });
}

// Uma faixa por campo (L98): de vários eventos do mesmo campo no turno, fica o mais importante.
function eventosUmPorCampo(eventos) {
  const ordenados = [...(eventos || [])].sort((a, b) => (PRIORIDADE_EVENTO[a.tipo] ?? 9) - (PRIORIDADE_EVENTO[b.tipo] ?? 9));
  const vistos = new Set();
  return ordenados.filter((ev) => {
    if (!ev.campo) return true;
    if (vistos.has(ev.campo)) return false;
    vistos.add(ev.campo);
    return true;
  });
}

function titulo(t) {
  const s = String(t || "").replace(/\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,}\b/g, (w) => w.toLowerCase());
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function aspectoDoTexto(texto) {
  const partes = String(texto || "").split(" — ");
  return legivel(partes.at(-1));
}

function rotuloCampoLaudo(campo) {
  const l = (S.estado.matriz || []).find((x) => x.campo === campo);
  return l ? l.aspecto : String(campo || "").split(":").pop().replaceAll("_", " ");
}

// Cartões de sistema de um turno: avisos da política e das guardas, divergências, itens verificados, rascunho.
function cartoesSistema(eventos, recente) {
  const evs = eventosUmPorCampo(eventos);
  const ocorr = evs.some((e) => e.tipo === "ocorrencia");
  const verif = evs.filter((e) => e.tipo === "verificado");
  const nos = [];
  let marcouOcorr = false;
  for (const ev of evs) {
    if (ev.tipo === "verificado" || ev.tipo === "ocorrencia") continue;
    const guarda = GUARDA.has(ev.tipo);
    // forte: bloqueio por falta de evidência, divergência ou abstenção no último turno (recolhe a resposta do agente);
    // destaque: a faixa do título pintada (bloqueio e guardas do último turno)
    const forte = recente && !guarda && (ev.tipo === "bloqueio" || NIVEL_FORTE.includes(ev.nivel));
    const destaque = recente && (guarda || ev.tipo === "bloqueio");
    let tx = EXPLICA[ev.tipo] || null;
    const extra = [];
    if (ev.tipo === "bloqueio") {
      const n = ev.pendencias?.length || 0;
      tx = `${n || ""} pendência(s) antes de emitir. A política só libera o rascunho com a evidência mínima e as divergências justificadas.`.trim();
      if (n) {
        extra.push(h("ul", { class: "sis-lista pendencias" }, ev.pendencias.slice(0, 6).map((p) => h("li", { title: legivel(p.falta || "") },
          h("span", { class: `pt-st ${p.status}`, "aria-hidden": "true" }),
          h("span", { class: "pend-txt" }, h("strong", {}, `${rotuloCampoLaudo(p.campo)}: `), curtoFalta(p.falta, p.status)),
          h("button", { class: "link-btn ver-item", type: "button", title: "Abrir a prova deste item", onclick: () => verItem(p.campo) },
            "ver item", icone("direita"))))));
      }
    } else if (ev.tipo === "divergencia" || ev.tipo === "pendente" || ev.tipo === "justificativa" || ev.tipo === "abstencao") {
      tx = aspectoDoTexto(ev.texto);
    } else if (ev.tipo === "emitido") {
      tx = "Confira o hash e assine com o PIN; o agente não assina.";
      if (["RASCUNHO", "ASSINATURA"].includes(S.estado.etapa)) {
        extra.push(h("a", { class: "btn btn-sec btn-peq", href: `#/fis/${encodeURIComponent(S.id)}/laudo` }, icone("assinar"), "Revisar e assinar"));
      }
    } else if (!tx) tx = semIds(ev.texto);
    if (ocorr && !marcouOcorr && ["pressao", "injecao", "negado", "assinatura"].includes(ev.tipo)) {
      extra.push(h("p", { class: "sis-nota" }, icone("hash"), "Ocorrência registrada na trilha auditável (cadeia de hash)."));
      marcouOcorr = true;
    }
    nos.push(cartaoSis({ tipo: guarda ? "guarda" : ev.nivel, icone: guarda ? (ev.tipo === "selado" ? "cadeado" : "escudo") : IC_EVENTO[ev.tipo] || "info",
      titulo: titulo(ev.titulo), regra: ev.rule_id || null, texto: tx, dica: ev.texto || null, extra, destaque, forte, novo: recente,
      alerta: forte || destaque }));
  }
  if (ocorr && !marcouOcorr) {
    nos.push(cartaoSis({ tipo: "info", icone: "hash", titulo: "Ocorrência registrada na trilha auditável", compacto: true }));
  }
  if (verif.length) {
    const nomes = [...new Set(verif.map((v) => aspectoDoTexto(v.texto)))];
    nos.push(cartaoSis({ tipo: "ok", icone: "verificado", compacto: true, novo: recente,
      titulo: verif.length === 1 ? "Item verificado" : `${verif.length} itens verificados`, texto: nomes.join(" · ") }));
  }
  return nos;
}

// Abre a prova de um item a partir da conversa (no celular, troca para a aba Laudo).
function verItem(campo) {
  if (ehMovel()) trocarMovel("laudo");
  else if (S.painel !== "laudo") trocarPainel("laudo");
  selecionar(campo);
}

// O que falta, em uma frase: "nova captura ou justificativa do fiscal (foto fora da gleba, a 649,9 m da borda)". A
// instrução longa depois dos dois-pontos e as faixas "(entre 100 e 1000 m)" ficam no title.
function curtoFalta(falta, status) {
  if (status === "divergente") return "justificar a divergência ou enviar nova evidência";
  let t = semIds(String(falta || "evidência").replace(/^evidência ausente:\s*/i, "")).replace(/\s*\((?:bov|cerca|item)\w*\)$/, "");
  const m = t.match(/^(.*?)\s*\((.*)\)\s*$/);
  if (m && m[1]) {
    const dentro = m[2].split(/:\s/)[0].replace(/\s*\(entre [^()]*\)?/g, "").replace(/[()]/g, "").trim();
    t = dentro ? `${m[1]} (${dentro})` : m[1];
  }
  return t;
}

function cartaoConfirmacao(c) {
  const campo = h("input", { type: "text", value: c.texto || "", "aria-label": "Texto reconhecido (pode corrigir)" });
  const nums = (c.numeros || []).filter((n) => n.critico);
  setTimeout(() => campo.focus(), 50);
  return h("div", { class: "msg agente" }, h("span", { class: "avatar ag", "aria-hidden": "true" }, icone("agente")),
    h("div", { class: "corpo-msg" }, h("div", { class: "cartao-acao", role: "group", "aria-label": "Confirmar números falados" },
      h("div", { class: "acao-tt" }, icone("alerta"), "Confirme os números antes de enviar"),
      h("p", {}, c.pergunta),
      nums.length ? h("div", { class: "numeros" }, nums.map((n) => h("span", { class: "num" }, n.rotulo))) : null,
      campo,
      h("div", { class: "grupo-btn" },
        h("button", { class: "btn btn-pri", type: "button", onclick: () => confirmar(true, campo.value) }, icone("verificado"), "Confirmar e enviar"),
        h("button", { class: "btn btn-sec", type: "button", onclick: () => confirmar(false) }, "Descartar")),
      h("p", { class: "nota" }, "Também dá para responder por voz: “sim” ou “não”."))));
}

// Pedido do residual: só os campos do DANFE/GTA que a foto não validou. A fiscal fala (segurar para falar) ou
// digita; o agente confere cada valor com as mesmas regras da leitura (DV da chave, somas, datas) antes de aceitar.
function cartaoResidual(p) {
  const doc = p.tipo_documento === "gta" ? "GTA" : "nota (DANFE)";
  const entradas = [];
  const linhas = (p.campos || []).map((c) => {
    const nomes = c.campos || [];
    const alvo = c.formato === "municipio" ? nomes.slice(0, 1) : nomes;
    const inputs = (c.confirmar ? alvo.flatMap((n) => [n, `${n}#2`]) : alvo).map((n) => {
      const numerico = ["digitos", "numero", "grade", "documento"].includes(c.formato);
      const inp = h("input", { type: "text", "data-campo": n, inputmode: numerico ? "numeric" : null,
        autocomplete: "off", placeholder: rotuloCampo(n), "aria-label": `${c.rotulo}: ${rotuloCampo(n)}` });
      entradas.push(inp);
      return inp;
    });
    return h("li", {}, h("div", {}, c.instrucao, c.modo === "digitacao" ? h("span", { class: "etiqueta" }, "digitar") : null),
      h("div", { class: "residual-campos" }, inputs));
  });
  const enviar = () => {
    const residual = Object.fromEntries(entradas.map((i) => [i.dataset.campo, i.value.trim()]).filter(([, v]) => v));
    if (!Object.keys(residual).length) { avisar("Preencha ao menos um campo, ou responda por voz.", true); return; }
    executar(() => api.turno(S.id, "", residual), { texto: "Conferindo os campos…", fala: `Completei ${Object.keys(residual).length} campo(s) da ${doc}.` },
      { origem: "texto" });
  };
  return h("div", { class: "msg agente" }, h("span", { class: "avatar ag", "aria-hidden": "true" }, icone("agente")),
    h("div", { class: "corpo-msg" }, h("div", { class: "cartao-acao residual", role: "group", "aria-label": `Completar a ${doc}` },
      h("div", { class: "acao-tt" }, icone("nota"), `Complete a ${doc}: leia no papel só estes campos`,
        p.tentativa > 1 ? h("span", { class: "etiqueta" }, `tentativa ${p.tentativa}`) : null),
      p.refazer_foto ? h("p", { class: "nota" }, "A foto ficou ruim em muitos campos: refazer a foto (de cima, sem sombra) pode ser mais rápido.") : null,
      h("ol", { class: "residual-lista" }, linhas),
      h("div", { class: "grupo-btn" },
        h("button", { class: "btn btn-pri", type: "button", onclick: enviar }, icone("verificado"), "Enviar para conferir")),
      h("p", { class: "nota" }, "Pode também falar os valores, na ordem. CPF/CNPJ só digitado. Nada é aceito sem passar pelo dígito verificador, pelas somas e pelas datas."))));
}

function rotuloCampo(n) {
  if (n.endsWith("#2")) return "repita (confere a digitação)";
  const r = { quantidade: "quantidade", valor_unitario: "valor unitário", valor_total: "valor total", chave: "dígitos da chave",
    total: "total", total_machos: "machos", total_femeas: "fêmeas", municipio: "município (ou código IBGE)", emitente_doc: "CNPJ/CPF do emitente" };
  const folha = n.split(".").pop();
  return r[folha] || folha.replaceAll("_", " ");
}

// ---------------------------------------------------------------- painel do laudo
const ROT_CONT = { verificado: "Verificado", divergente: "Divergente", pendente: "Pendente", abstencao: "Abstenção" };
const IC_CONT = { verificado: "verificado", divergente: "divergente", pendente: "pendente", abstencao: "abstencao" };
const IC_ITEM = { bovinos: "pessoa", cerca: "mapa" };

// O que falta para emitir: aspectos pendentes e divergências sem justificativa (o que as políticas POL-01 e POL-02
// conferem). O texto do pedido vem das pendências do servidor quando há; a política continua sendo quem decide.
function faltas(e) {
  const linhas = (e.matriz || []).filter((l) => !l.agregado);
  const doServidor = Object.fromEntries((Array.isArray(e.pendencias) ? e.pendencias : []).map((p) => [p.campo, p]));
  return linhas.filter((l) => l.status === "pendente" || (l.status === "divergente" && !l.justificativa)).map((l) => ({
    campo: l.campo, aspecto: l.aspecto, status: l.status,
    falta: l.status === "divergente" ? "justificar a divergência ou enviar nova evidência"
      : curtoFalta(doServidor[l.campo]?.falta || l.pedido || "evidência", "pendente"),
    regra: doServidor[l.campo]?.regra_id || null,
  }));
}

function grupos(e) {
  const linhas = e.matriz || [];
  const itens = e.operacao.itens || [];
  const ag = Object.fromEntries(linhas.filter((l) => l.agregado).map((l) => [l.campo, l]));
  const out = [];
  for (const it of itens) {
    const filhos = linhas.filter((l) => !l.agregado && l.item_id === it.id);
    if (filhos.length) out.push({ titulo: nomeItem(it.descricao), descricao: it.descricao, tipo: it.tipo, agregado: ag[`item:${it.id}`] || null, linhas: filhos });
  }
  const resto = linhas.filter((l) => !l.agregado && !itens.some((it) => it.id === l.item_id));
  if (resto.length) out.push({ titulo: "Requisitos do laudo", descricao: "Registros que o MCR exige em todo laudo", tipo: "laudo", agregado: null, linhas: resto });
  return out;
}

function renderPainel(anterior) {
  const e = S.estado;
  const linhas = (e.matriz || []).filter((l) => !l.agregado);
  const c = { verificado: 0, divergente: 0, pendente: 0, abstencao: 0 };
  linhas.forEach((l) => { c[l.status] = (c[l.status] || 0) + 1; });
  const total = linhas.length;
  const concl = total - c.pendente;
  // sem denominador: o total cresce quando o agente define o método ou chega evidência de outro item, e "2 de 9" →
  // "4 de 10" parecia retrocesso
  const semMetodo = !e.metodo || !total;
  S.el.progTxt.textContent = semMetodo ? "aguardando o método"
    : `${concl} ${concl === 1 ? "aspecto concluído" : "aspectos concluídos"} · ${c.pendente} em aberto`;
  S.el.progTxt.title = "Aspectos concluídos (verificados, divergentes ou com abstenção) e em aberto. Novos aspectos entram quando o agente define o método e quando chega evidência de outro item.";
  S.el.barra.classList.toggle("indet", semMetodo);
  S.el.barra.setAttribute("aria-label", semMetodo ? "aguardando o método"
    : `${c.verificado} verificados, ${c.divergente} divergentes, ${c.pendente} pendentes, ${c.abstencao} abstenções`);
  S.el.barra.replaceChildren(...(semMetodo ? [h("i", { class: "indet" })] : Object.keys(ROT_CONT).filter((k) => c[k]).map((k) =>
    h("i", { class: k, style: `flex-grow:${c[k]}`, title: `${ROT_CONT[k]}: ${c[k]}` }))));
  // placar com rótulo por extenso (no telão, ⊘ e ⏱ sozinhos não se leem)
  const rot = { verificado: ["verificado", "verificados"], divergente: ["divergente", "divergentes"], pendente: ["pendente", "pendentes"],
    abstencao: ["abstenção", "abstenções"] };
  S.el.contadores.replaceChildren(...Object.keys(ROT_CONT).map((k) =>
    h("span", { class: `contador ${k}${c[k] ? "" : " zero"}`, role: "img", "aria-label": `${c[k]} ${rot[k][c[k] === 1 ? 0 : 1]}`, title: DICA_CONT[k] },
      icone(IC_CONT[k]), h("b", {}, c[k]), h("span", { class: "rot-cont" }, rot[k][c[k] === 1 ? 0 : 1]))));
  renderMatriz(anterior);
  renderEmitir();
  ajustarMatriz(); // depois do "O que falta" (que muda a altura da tabela)
}

const DICA_CONT = { verificado: "Verificado: a evidência confere com o financiado", divergente: "Divergente: a evidência não confere com o financiado",
  pendente: "Pendente: falta evidência para concluir", abstencao: "Abstenção: a evidência não permite concluir (o sistema não chuta)" };

function renderMatriz(anterior) {
  const linhas = S.estado.matriz || [];
  const antes = Object.fromEntries((anterior?.matriz || []).map((l) => [l.campo, l.status]));
  if (!linhas.length) {
    S.el.matriz.replaceChildren(h("p", { class: "vazio" }, "Os itens aparecem quando o agente define o método."));
    return;
  }
  const corpo = h("tbody");
  // a linha fica marcada só enquanto a prova dela está aberta na gaveta (senão disputava com o realce de "mudou")
  const aberta = S.el.grade.classList.contains("prova-aberta");
  const linhaTr = (l, extraCls, conteudo) => {
    const mudou = anterior && antes[l.campo] !== undefined && antes[l.campo] !== l.status;
    const sel = aberta && S.selecionado === l.campo;
    return h("tr", { class: `linha${extraCls}${sel ? " selecionada" : ""}${mudou ? " mudou" : ""}`, tabindex: "0",
      "aria-selected": sel ? "true" : "false", dataset: { campo: l.campo },
      onclick: () => selecionar(l.campo), onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selecionar(l.campo); } } },
    conteudo);
  };
  for (const g of grupos(S.estado)) {
    const cab = [h("td", { class: "c-item" }, h("div", { class: "grupo-tt", title: g.descricao },
      icone(IC_ITEM[g.tipo] || "doc"), h("span", {}, g.titulo))),
    h("td", { class: "c-st" }, g.agregado ? chipStatus(g.agregado.status) : null)];
    if (g.agregado) corpo.append(linhaTr(g.agregado, " grupo", cab));
    else {
      const primeiro = g.linhas[0]?.campo;
      corpo.append(h("tr", { class: "secao", onclick: () => primeiro && selecionar(primeiro) }, cab));
    }
    for (const l of g.linhas) {
      const valor = valorLegivel(l);
      corpo.append(linhaTr(l, "", [
        h("td", { class: "c-item" },
          h("div", { class: "aspecto", title: l.aspecto }, l.aspecto),
          (valor || l.regra_id || l.justificativa) ? h("div", { class: "sub" },
            valor ? h("span", { class: `valor${valor.rot === "Referência" ? " ref" : ""}`, title: l.valor_fmt || null }, `${valor.rot}: ${valor.txt}`) : null,
            l.justificativa ? h("span", { class: "etiqueta etq-just", title: `Justificativa do fiscal: “${l.justificativa}”` }, "justificado") : null,
            chipRegra(l.regra_id)) : null,
          l.motivo && l.status !== "verificado" ? h("div", { class: "motivo", title: l.motivo }, motivoLegivel(l)) : null),
        h("td", { class: "c-st" }, chipStatus(l.status))]));
    }
  }
  const topo = S.el.matriz.scrollTop;
  S.el.matriz.replaceChildren(h("table", { class: "matriz" },
    h("caption", { class: "so-leitor" }, "Itens do laudo com o status de cada aspecto; Enter abre a prova"),
    h("colgroup", {}, h("col", {}), h("col", { class: "col-st" })),
    h("thead", { class: "so-leitor" }, h("tr", {}, h("th", { scope: "col" }, "Item e aspecto"), h("th", { scope: "col" }, "Status"))),
    corpo));
  S.el.matriz.scrollTop = topo;
}

// A tabela não abre com uma linha cortada em cima: encaixa no começo da primeira linha à vista e, se um status mudou
// neste turno, traz a linha que mudou (com o cabeçalho do grupo dela).
function ajustarMatriz() {
  const wrap = S.el.matriz;
  if (!wrap.clientHeight) return;
  const base = wrap.getBoundingClientRect().top - wrap.scrollTop;
  for (const tr of wrap.querySelectorAll("tbody tr")) {
    const topo = tr.getBoundingClientRect().top - base;
    if (topo + tr.offsetHeight > wrap.scrollTop + 1) {
      // a primeira linha de um grupo leva junto o cabeçalho do grupo (o item a que o aspecto pertence)
      const cab = tr.previousElementSibling?.matches(".grupo, .secao") ? tr.previousElementSibling : null;
      if (topo < wrap.scrollTop - 1 || (cab && topo <= wrap.scrollTop + 1)) wrap.scrollTop = cab ? cab.getBoundingClientRect().top - base : topo;
      break;
    }
  }
  rolarMatrizMudou();
}

// Depois de um turno, a linha que mudou de status fica à vista, com o cabeçalho do grupo dela quando cabe.
function rolarMatrizMudou() {
  const wrap = S.el.matriz;
  const tr = wrap.querySelector("tr.mudou:not(.grupo)") || wrap.querySelector("tr.mudou");
  if (!tr || !wrap.clientHeight) return;
  let cab = tr.matches(".grupo, .secao") ? tr : tr.previousElementSibling;
  while (cab && !cab.matches(".grupo, .secao")) cab = cab.previousElementSibling;
  const base = wrap.getBoundingClientRect().top - wrap.scrollTop;
  const topoTr = tr.getBoundingClientRect().top - base;
  const fimTr = topoTr + tr.offsetHeight;
  const topoCab = cab ? cab.getBoundingClientRect().top - base : topoTr;
  const ini = fimTr - topoCab <= wrap.clientHeight ? topoCab : topoTr;
  if (ini >= wrap.scrollTop && fimTr <= wrap.scrollTop + wrap.clientHeight) return; // já à vista
  wrap.scrollTop = ini < wrap.scrollTop ? ini : Math.min(ini, fimTr - wrap.clientHeight);
}

function renderEmitir() {
  const e = S.estado;
  const lista = faltas(e);
  const nos = [];
  const emitido = ["RASCUNHO", "ASSINATURA"].includes(e.etapa) && e.laudo;
  const reemitir = emitido && e.laudo?.valido_para_assinar === false;
  if (e.etapa === "SELADO") {
    nos.push(h("div", { class: "pronto ok" }, icone("selo"), h("span", {}, h("strong", {}, "Laudo selado."), " Nada mais muda nesta fiscalização.")),
      h("div", { class: "emitir-acoes" },
        h("a", { class: "btn btn-pri btn-bloco", href: `#/fis/${encodeURIComponent(e.id)}/laudo` }, icone("doc"), "Ver laudo selado"),
        h("a", { class: "btn btn-sec", href: `#/fis/${encodeURIComponent(e.id)}/laudo?pacote=1`, title: "ZIP com manifest sha256 para o BCB ou a Justiça" },
          icone("baixar"), "Pacote de exibição")));
  } else if (emitido && !reemitir) {
    nos.push(h("div", { class: "pronto" }, icone("doc"), h("span", {}, h("strong", {}, "Rascunho emitido."), " Confira o hash e assine com o PIN.")),
      h("a", { class: "btn btn-pri btn-bloco", href: `#/fis/${encodeURIComponent(e.id)}/laudo` }, icone("assinar"), "Revisar e assinar"));
  } else {
    let motivo = "";
    if (e.etapa === "BRIEFING") motivo = "Comece pela conversa: o agente define o método antes.";
    else if (S.ocupado) motivo = "Aguarde o agente terminar.";
    else if (lista.length) motivo = `Faltam ${lista.length} ${lista.length === 1 ? "pendência" : "pendências"}.`;
    if (lista.length && e.etapa !== "BRIEFING") {
      // no telão e em tela baixa (tablet deitado) a lista começa fechada: o cartão da conversa já a mostra e a tabela
      // precisa da altura
      const telao = document.body.classList.contains("apresentacao") || !window.matchMedia("(min-height: 821px)").matches;
      nos.push(h("details", { class: "falta", open: (lista.length <= 3 && !telao) || null },
        h("summary", {}, icone("direita", "seta-det"), h("h3", {}, "O que falta para emitir"), h("span", { class: "contagem alerta" }, lista.length)),
        h("ul", {}, lista.map((f) => h("li", {}, h("button", { class: "link-falta", type: "button", onclick: () => selecionar(f.campo), title: "Abrir a prova do item" },
          h("span", { class: `pt-st ${f.status}`, "aria-hidden": "true" }), h("span", {}, h("strong", {}, f.aspecto), h("small", {}, f.falta))))))));
    } else if (!lista.length && e.etapa !== "BRIEFING") {
      nos.push(h("div", { class: "pronto ok" }, icone("verificado"), h("span", {}, reemitir ? "Há evidência nova depois do rascunho: emita de novo." : "Tudo pronto para emitir o rascunho.")));
    }
    // na demonstração, quando o próximo passo do roteiro é a emissão, este é o botão em destaque (o "Executar passo"
    // da barra fica discreto): emitir por aqui também avança o roteiro
    const realce = !motivo && passoEmissao();
    nos.push(h("button", { class: `btn btn-pri btn-bloco${realce ? " realce" : ""}`, type: "button", id: "btn-rascunho", onclick: pedirRascunho,
      disabled: motivo ? true : null, "aria-describedby": motivo ? "motivo-emitir" : null }, icone("doc"), reemitir ? "Emitir rascunho de novo" : "Emitir rascunho"));
    if (motivo) nos.push(h("p", { class: "motivo-btn", id: "motivo-emitir" }, motivo, lista.length ? " A política confere tudo antes de liberar." : ""));
  }
  S.el.emitir.replaceChildren(...nos);
}

// O próximo passo do roteiro é pedir o rascunho, e o painel já pode emitir?
function passoEmissao() {
  const r = S.estado.roteiro;
  const p = r?.passos?.[r.proximo - 1];
  if (!p || S.ocupado || !/emiss|emitir/i.test(`${p.titulo} ${p.fala}`) || /bloquead/i.test(p.titulo)) return false;
  const e = S.estado;
  return !["BRIEFING", "SELADO"].includes(e.etapa) && !(["RASCUNHO", "ASSINATURA"].includes(e.etapa) && e.laudo) && !faltas(e).length;
}

// ---------------------------------------------------------------- evidências
function ehImagem(e) { return ["foto", "quadro_chave"].includes(e.tipo) || /\.(jpe?g|png|webp)$/i.test(e.nome || ""); }

function renderEvidencias() {
  const evs = [...S.estado.evidencias].reverse();
  const itens = Object.fromEntries((S.estado.operacao.itens || []).map((i) => [i.id, nomeItem(i.descricao, 40)]));
  const env = new Set(evidenciasEnviadas());
  const enviadas = evs.filter((e) => env.has(e));
  const geradas = evs.filter((e) => !env.has(e));
  S.el.evidN.textContent = enviadas.length ? `${enviadas.length} ${enviadas.length === 1 ? "enviada" : "enviadas"}` : "";
  if (!evs.length) {
    S.el.evid.replaceChildren(h("div", { class: "vazio" }, icone("clipe"), h("p", {}, "Nenhuma evidência ainda."),
      h("p", { class: "nota" }, "Use Foto, Vídeo, NF-e, GTA ou Nota impressa embaixo da conversa.")));
    return;
  }
  const cartao = (e, peq) => h("li", { class: `ev-card${peq ? " peq" : ""}` },
    h("a", { href: e.url || "#", target: "_blank", rel: "noopener", title: `${e.nome || ""}\nsha256 ${e.sha256 || ""}` },
      h("div", { class: "ev-mini" }, ehImagem(e) && e.url ? h("img", { src: e.url, alt: "", loading: "lazy" }) : icone(IC_TIPO[e.tipo] || "doc")),
      h("div", { class: "ev-txt" }, h("strong", {}, ROT_TIPO[e.tipo] || e.tipo),
        itens[e.item_id] ? h("small", {}, itens[e.item_id]) : null,
        h("small", {}, fmtData(e.recebida_em)),
        e.gps ? h("small", { class: "ev-gps" }, icone("pino"), "com GPS") : null)));
  const nos = [h("ul", { class: "galeria" }, enviadas.map((e) => cartao(e, false)))];
  if (geradas.length) {
    nos.push(h("p", { class: "rotulo-sec" }, "Gerados pelo sistema"), h("ul", { class: "galeria peq" }, geradas.map((e) => cartao(e, true))));
  }
  nos.push(h("p", { class: "nota ev-rodape" }, icone("hash"), "Cada arquivo entra na cadeia com o seu sha256 (passe o mouse para ver)."));
  S.el.evid.replaceChildren(...nos);
}

// ---------------------------------------------------------------- prova do item (gaveta)
function marcarSelecao(campo) {
  S.el.matriz.querySelectorAll("tr.linha").forEach((tr) => {
    const sel = !!campo && tr.dataset.campo === campo;
    tr.classList.toggle("selecionada", sel);
    tr.setAttribute("aria-selected", sel ? "true" : "false");
  });
}

function selecionar(campo) {
  S.selecionado = campo;
  marcarSelecao(campo);
  abrirGaveta(true);
}

function abrirGaveta(abrir) {
  if (!S) return;
  const estava = S.el.grade.classList.contains("prova-aberta");
  S.el.grade.classList.toggle("prova-aberta", !!abrir);
  if (abrir) {
    renderProva();
    S.el.fecharProva.focus({ preventScroll: true });
  } else {
    S.miniMapa?.remove?.(); S.miniMapa = null;
    // o foco volta para a linha; a marcação de selecionada sai junto com a gaveta
    if (estava) S.el.matriz.querySelector(`tr[data-campo="${CSS.escape(S.selecionado || "")}"]`)?.focus({ preventScroll: true });
    S.selecionado = null;
    marcarSelecao(null);
  }
}

function renderProva() {
  S.miniMapa?.remove?.(); S.miniMapa = null;
  const l = (S.estado.matriz || []).find((x) => x.campo === S.selecionado);
  S.el.tituloProva.textContent = l ? l.aspecto : "—";
  S.el.prova.replaceChildren(painelProva(l));
  S.el.prova.scrollTop = 0;
}

function painelProva(l) {
  if (!l) return h("p", { class: "vazio" }, "Escolha um item no painel do laudo para ver a prova.");
  const chks = S.estado.checagens.filter((c) => l.checagens.includes(c.id));
  const valor = valorLegivel(l);
  const motivo = l.motivo ? motivoLegivel(l) : "";
  const cab = h("div", { class: "cab-prova" },
    h("p", { class: "nota", title: l.item_descricao }, curto(l.item_descricao, 90)),
    h("div", { class: "prova-st" }, chipStatus(l.status, true),
      valor ? h("span", { class: `valor${valor.rot === "Referência" ? " ref" : ""}`, title: l.valor_fmt || null }, `${valor.rot}: ${valor.txt}`) : null),
    h("dl", { class: "kv" },
      h("dt", {}, "Motivo"), h("dd", { title: l.motivo || "" }, motivo || "—"),
      l.proveniencia?.length ? [h("dt", {}, "Origem do valor"), h("dd", {}, l.proveniencia.join("; "))] : null,
      l.justificativa ? [h("dt", {}, "Justificativa"), h("dd", {}, `“${l.justificativa}”`)] : null,
      l.ressalvas?.length ? [h("dt", {}, "Ressalvas"), h("dd", {}, l.ressalvas.map(legivel).join("; "))] : null,
      // a regra com o nome curto ("MCR 2-7", "Regra operacional"); o id completo fica na dica e em Detalhes técnicos
      l.regra_id ? [h("dt", {}, "Regra"), h("dd", { class: "regra", title: l.regra_id }, chipRegra(l.regra_id))] : null));
  const nos = [cab];
  if (!chks.length) {
    nos.push(h("div", { class: "vazio" }, h("p", {}, l.pedido ? `Falta: ${curtoFalta(l.pedido, l.status)}` : "Ainda sem checagem para este item."),
      h("button", { class: "btn btn-sec", type: "button", onclick: () => {
        abrirGaveta(false); trocarMovel("conversa");
        (ehMovel() ? S.el.clipe : S.el.anexos.querySelector(".chip-anexo"))?.focus();
      } }, icone("clipe"), "Enviar evidência")));
  }
  for (const c of chks) nos.push(blocoProva(c));
  return h("div", { class: "prova" }, nos);
}

function blocoProva(c) {
  const p = c.prova || {};
  const cab = h("div", { class: "bloco-cab" },
    h("strong", { title: c.ferramenta }, rotuloFerramenta(c.ferramenta)),
    h("span", { class: "bloco-st" }, chipStatus(c.status),
      p.fake ? h("span", { class: "etiqueta fake", title: "ferramenta simulada nesta execução" }, "simulada") : null,
      c.span_id ? h("button", { class: "link-btn", type: "button", onclick: () => abrirSpan(c.span_id), title: "Abrir o registro desta checagem no trace" },
        icone("trace"), "trace") : null));
  const corpo = [cab];
  if (p.tipo === "contagem") {
    corpo.push(h("div", { class: "contagem-grande" },
      h("span", { class: "numero-grande" }, fmtNum(p.contagem)),
      h("span", {}, Array.isArray(p.intervalo) && p.intervalo[1] !== p.contagem ? `animais contados (pode chegar a ${fmtNum(p.intervalo[1])})` : "animais contados"), p.lote ? h("span", { class: "nota" }, `lote ${p.lote}`) : null));
    if (p.quadros?.length) {
      corpo.push(h("div", { class: "quadros" }, p.quadros.map((q) => h("figure", {},
        h("img", { src: q.url, alt: `Quadro-chave em ${q.t_s} s com as caixas dos animais; contados até aqui: ${q.contagem_ate_aqui}`, loading: "lazy" }),
        h("figcaption", {}, `${q.t_s} s · ${q.contagem_ate_aqui} contados`)))));
    } else if (p.video_url) {
      corpo.push(h("video", { src: p.video_url, controls: true, preload: "metadata", muted: true }),
        h("p", { class: "nota" }, p.fake ? "Contagem simulada (sem quadros-chave nesta execução)." : "Sem quadros-chave."));
    }
    if (p.pedidos_recaptura?.length) corpo.push(h("ul", { class: "nota" }, p.pedidos_recaptura.map((x) => h("li", {}, x))));
  } else if (p.tipo === "foto_mapa") {
    if (p.foto_url) corpo.push(h("img", { class: "foto", src: p.foto_url, alt: "Foto enviada como evidência", loading: "lazy" }));
    corpo.push(h("dl", { class: "kv" },
      p.gps ? [h("dt", {}, "GPS"), h("dd", {}, `${p.gps.lat.toFixed(6)}, ${p.gps.lon.toFixed(6)} (±${p.gps.precisao_m ?? "?"} m, ${p.gps.fonte})`)] : [h("dt", {}, "GPS"), h("dd", {}, "sem GPS")],
      p.distancia_borda_m !== undefined && p.distancia_borda_m !== null ? [h("dt", {}, "Distância à borda"), h("dd", {}, `${fmtNum(p.distancia_borda_m)} m`)] : null,
      p.status_ferramenta ? [h("dt", {}, "Resultado"), h("dd", {}, p.status_ferramenta)] : null));
    if (p.glebas?.length || p.gps) {
      const mm = h("div", { class: "mini-mapa", role: "img", "aria-label": "Gleba da operação e ponto da foto" });
      corpo.push(mm);
      setTimeout(() => { if (!S || !mm.isConnected) return; S.miniMapa?.remove?.(); S.miniMapa = miniMapa(mm, p.glebas || [], p.gps); }, 30);
    }
  } else if (p.tipo === "documento") {
    if (p.criterios?.length) {
      corpo.push(h("table", { class: "crit" }, h("thead", {}, h("tr", {}, h("th", {}, "Critério"), h("th", {}, "Status"), h("th", {}, "Motivo"))),
        h("tbody", {}, p.criterios.map((k) => h("tr", {}, h("td", { title: k.regra_id || "" }, String(k.campo || "").split(":").pop().replaceAll("_", " ")),
          h("td", {}, chipStatus(k.status)), h("td", { title: k.motivo || null }, legivel(k.motivo)))))));
    }
    if (p.nao_verificado_offline?.length) {
      corpo.push(h("p", { class: "nota" }, "Não verificável offline (vira ressalva, não divergência): " +
        p.nao_verificado_offline.map((a) => a.regra_id).join(", ")));
    }
    if (p.trecho_url) {
      const alvo = h("div");
      corpo.push(h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: async () => {
        try { alvo.replaceChildren(renderTrecho(await api.trecho(p.trecho_url))); } catch (e) { alvo.textContent = e.message; }
      } }, icone("doc"), "Ver trecho do documento"), alvo);
    }
  } else if (p.tipo === "plano") {
    corpo.push(h("p", {}, h("strong", {}, `Método: ${p.metodo || "—"}. `), p.justificativa || ""));
  } else if (p.dados) {
    corpo.push(h("dl", { class: "kv" }, Object.entries(p.dados).map(([k, v]) => [h("dt", {}, k.replaceAll("_", " ")), h("dd", {}, fmtNum(v))])));
  }
  if (p.motivos?.length && p.tipo !== "documento") corpo.push(h("ul", { class: "nota" }, p.motivos.slice(0, 5).map((m) => h("li", { title: m }, legivel(m)))));
  if (p.erro) corpo.push(h("p", { class: "nota" }, `Erro da ferramenta: ${p.erro}`));
  corpo.push(h("div", { class: "fonte", title: `${c.id} · evidência ${c.evidencias.join(", ") || "—"}` }, `Fonte/versão: ${c.fonte_versao || "—"}`));
  return h("div", { class: "bloco" }, corpo);
}

function renderTrecho(t) {
  const nos = [h("dl", { class: "kv" }, (t.campos || []).map((c) => [h("dt", {}, c.rotulo), h("dd", {}, c.valor)]))];
  if (t.produtos?.length) {
    nos.push(h("table", { class: "crit" },
      h("thead", {}, h("tr", {}, ["Produto", "NCM", "CFOP", "Qtd", "Valor"].map((x) => h("th", {}, x)))),
      h("tbody", {}, t.produtos.map((p) => h("tr", {}, [p.descricao, p.ncm, p.cfop, `${p.quantidade || ""} ${p.unidade || ""}`, p.valor].map((x) => h("td", {}, x || "—")))))));
  }
  if (t.xml) nos.push(h("pre", { class: "xml" }, t.xml));
  return h("div", { class: "trecho" }, nos);
}

export async function abrirSpan(spanId) {
  if (!spanId || !S) return;
  try {
    const r = await api.spans(S.id, spanId);
    const corpo = h("div", {}, (r.spans || []).map((s) => h("div", { class: `span${s.span_id === spanId ? " alvo" : ""}` },
      h("h3", {}, s.name),
      h("div", { class: "nota mono" }, `${s.span_id} · ${s.status} · ${s.duration_ms ?? "?"} ms · ${fmtData(s.start)}`),
      h("dl", { class: "kv" }, Object.entries(s.attributes || {}).map(([k, v]) => [h("dt", { class: "mono" }, k), h("dd", { class: "mono" }, String(v))])))),
    h("a", { class: "btn btn-sec btn-peq", href: `/api/fiscalizacoes/${encodeURIComponent(S.id)}/trace`, target: "_blank", rel: "noopener" }, icone("trace"), "Trace completo (JSONL)"));
    abrirModal(`Trace — registro ${spanId}`, corpo);
  } catch (e) { avisar(`Trace indisponível: ${e.message}`, true); }
}

// ---------------------------------------------------------------- detalhes técnicos (gaveta)
function secaoFis() {
  const e = S.estado;
  const idx = e.etapas.findIndex((x) => x.id === e.etapa);
  const etapas = h("ol", { class: "tec-etapas", "aria-label": "Etapas da máquina de estados" }, e.etapas.map((x, i) =>
    h("li", { class: `${i < idx ? "feita" : ""}${i === idx ? " atual" : ""}`, "aria-current": i === idx ? "step" : null, title: x.rotulo }, x.id)));
  const turnos = (e.conversa || []).slice(-8).reverse().map((c) => {
    const meta = S.metaTurno[c.turno] || null;
    const acoes = meta?.acoes || c.acoes || [];
    return h("li", {}, h("div", { class: "tec-turno" }, h("strong", {}, `Turno ${c.turno}`), h("span", { class: "nota" }, c.etapa || ""),
      meta?.fala_origem ? h("span", { class: "etiqueta" }, `fala: ${meta.fala_origem}`) : null,
      meta?._lat >= 0 ? h("span", { class: "nota" }, `${(meta._lat / 1000).toFixed(1).replace(".", ",")} s`) : null),
    h("ul", { class: "tec-acoes" }, acoes.map(linhaAcao)));
  });
  const g = [...(e.governanca || [])].reverse();
  return h("div", {},
    blocoTec("Máquina de estados", etapas,
      h("dl", { class: "kv" }, h("dt", {}, "Etapa"), h("dd", { class: "mono" }, e.etapa),
        h("dt", {}, "Método"), h("dd", {}, e.metodo ? `${e.metodo_rotulo || ""} (${e.metodo})` : "—"),
        h("dt", {}, "Rulebook"), h("dd", { class: "mono" }, e.rulebook || "—"),
        h("dt", {}, "Fiscalização"), h("dd", { class: "mono" }, e.id),
        S.ultimoLat ? [h("dt", {}, "Último turno"), h("dd", {}, S.ultimoLat)] : null)),
    blocoTec(`Decisões da política (${g.length})`, g.length ? h("ol", { class: "tec-gov" }, g.map((d) => h("li", {},
      h("span", { class: `regra-chip ${String(d.resultado || "").split("+")[0]}`, translate: "no" }, d.rule_id),
      h("span", {}, h("strong", {}, `${rotuloFerramenta(d.acao)} · ${d.resultado}: `), d.motivo || ""),
      d.span_id ? h("button", { class: "link-btn", type: "button", onclick: () => abrirSpan(d.span_id) }, "trace") : null)))
      : h("p", { class: "nota" }, "Nenhuma decisão registrada ainda.")),
    blocoTec("Ações do agente (últimos turnos)", turnos.length ? h("ol", { class: "tec-turnos" }, turnos) : h("p", { class: "nota" }, "Sem turnos ainda.")),
    blocoTec("Trace", h("p", { class: "nota" }, `${e.n_spans} registros (spans) nesta fiscalização.`),
      h("div", { class: "grupo-btn" },
        h("a", { class: "btn btn-sec btn-peq", href: e.trace_url || `/api/fiscalizacoes/${encodeURIComponent(e.id)}/trace`, target: "_blank", rel: "noopener" }, icone("trace"), "Trace completo (JSONL)"),
        h("a", { class: "btn btn-sec btn-peq", href: `/api/fiscalizacoes/${encodeURIComponent(e.id)}`, target: "_blank", rel: "noopener" }, icone("codigo"), "Estado (JSON)"))));
}

function linhaAcao(a) {
  if (typeof a === "string") {
    const [nome, st] = a.split(":");
    return h("li", { class: st === "negado" ? "negado" : "" }, st === "negado" ? "✖ " : "✔ ", rotuloFerramenta(nome), st ? ` · ${st}` : "");
  }
  const neg = !a.permitido || a.ok === false;
  let txt = rotuloFerramenta(a.acao);
  if (a.rule_id) txt += ` [${a.rule_id}]`;
  if (neg) txt += ` — ${semIds(a.resultado).slice(0, 140)}`;
  else if (a.checagem_id) txt += ` — ${semIds(String(a.resultado || "").split(".")[0]).slice(0, 90)}`;
  return h("li", { class: neg ? "negado" : "", title: `${a.acao}${a.checagem_id ? ` · ${a.checagem_id}` : ""}${a.span_id ? ` · span ${a.span_id}` : ""}` },
    neg ? "✖ " : "✔ ", h("span", { class: "etiqueta" }, a.origem), " ", txt);
}

// ---------------------------------------------------------------- controle da demonstração (roteiro)
function renderRoteiro() {
  const r = S.estado.roteiro;
  const bar = S.el.roteiro;
  if (!r) { bar.hidden = true; S.el.tela.classList.remove("com-roteiro"); return; }
  bar.hidden = false;
  S.el.tela.classList.add("com-roteiro");
  const p = r.passos[r.proximo - 1];
  const tinhaFoco = bar.contains(document.activeElement) ? document.activeElement.dataset.k : null;
  // "Executar passo" fica discreto quando o painel mostra a mesma ação em destaque (emitir o rascunho)
  const mesmoPainel = !!p && passoEmissao();
  const confirma = S.confirmarReinicio;
  bar.replaceChildren(...[ // sem filtro, o null de um botão ausente virava o texto "null" na barra
    h("div", { class: "roteiro-id", title: "Controle da demonstração (não faz parte do produto)" },
      h("span", { class: "pos" }, `Passo ${Math.min(r.proximo, r.total)}/${r.total}`)),
    h("span", { class: "titulo", title: p?.fala || null }, h("span", { class: "tt" }, p ? p.titulo : "Roteiro concluído"),
      mesmoPainel ? h("small", {}, "ou clique em “Emitir rascunho” no painel do laudo")
        : p?.fala ? h("small", {}, `“${p.fala}”`) : p?.evidencia ? h("small", {}, rotuloEnvio(p, r))
          : p?.acao === "residual" ? h("small", {}, "a fiscal lê no papel só o que o agente pediu")
            : !p ? h("small", {}, "use “Recomeçar” para rodar de novo") : null),
    p ? h("button", { class: `btn btn-pri${mesmoPainel ? " discreto" : ""}`, type: "button", onclick: proximoPasso, disabled: S.ocupado ? true : null,
      dataset: { k: "executar" } },
    icone("play"), p.acao === "assinar" ? "Ir para assinatura" : "Executar passo", h("kbd", {}, "→")) : null,
    p && p.acao !== "assinar" ? h("button", { class: "btn btn-escuro", type: "button", onclick: pularPasso, disabled: S.ocupado ? true : null,
      dataset: { k: "pular" }, "aria-label": "Pular passo",
      title: "Avança o roteiro sem executar o passo (use quando o passo já foi feito pelo microfone ou por um botão)" },
    icone("pular"), h("span", { class: "rot" }, h("span", { class: "rot-curta" }, "Pular"), h("span", { class: "rot-longa" }, " passo"))) : null,
    // recomeçar pede confirmação no próprio botão (sem o confirm() do navegador no telão)
    h("button", { class: `btn btn-escuro${confirma ? " confirmar" : ""}`, type: "button", onclick: reiniciarDemo, dataset: { k: "reiniciar" },
      "aria-label": confirma ? "Clique de novo para recomeçar a demonstração" : "Recomeçar demo",
      title: confirma ? "Apaga a fiscalização de demonstração e recomeça do passo 1" : "Apaga esta fiscalização de demonstração e recomeça" },
    icone(confirma ? "alerta" : "reiniciar"),
    confirma ? h("span", { class: "rot rot-sempre" }, "Clique de novo para recomeçar")
      : h("span", { class: "rot" }, h("span", { class: "rot-curta" }, "Recomeçar"), h("span", { class: "rot-longa" }, " demo")))].filter(Boolean));
  if (tinhaFoco) bar.querySelector(`[data-k="${tinhaFoco}"]`)?.focus({ preventScroll: true });
}

// "evidência: gta_1.json" não diz nada para a banca: a barra diz o que a fiscal envia.
function rotuloEnvio(p, r) {
  const a = (r.arquivos || []).find((x) => x.nome === p.evidencia);
  const base = ENVIO_TIPO[a?.tipo] || "a fiscal envia o arquivo do caso";
  return a?.tipo === "gta" && /instru/i.test(p.titulo) ? `${base}; o campo de observação traz uma instrução escondida` : base;
}

async function proximoPasso() {
  if (S.ocupado) return;
  const r = S.estado.roteiro;
  const p = r?.passos[r.proximo - 1];
  if (!p) return;
  if (p.acao === "assinar") { S.irLaudo(S.id, true); return; }
  const arq = p.evidencia ? (r.arquivos || []).find((a) => a.nome === p.evidencia) : null;
  await executar(() => api.proximoPasso(S.id), {
    fala: p.fala || (p.acao === "residual" ? `${p.fala_prefixo || ""}…` : ""),
    evidencia: arq?.tipo || null, nome: p.evidencia || null,
    texto: arq ? STATUS_ENVIO[arq.tipo] : p.acao === "residual" ? "Conferindo os campos lidos…" : null,
  });
}

async function pularPasso() {
  if (S.ocupado) return;
  try {
    const r = await api.pularPasso(S.id);
    atualizar(r.estado, S.eventos);
    avisar(r.aviso || "Passo pulado.");
  } catch (e) { avisar(e.message, true); }
}

async function reiniciarDemo() {
  const r = S.estado.roteiro;
  if (!r) return;
  if (!S.confirmarReinicio) { // 1º clique: o botão pede confirmação por 5 s
    S.confirmarReinicio = true;
    renderRoteiro();
    clearTimeout(S.tReinicio);
    S.tReinicio = setTimeout(() => { if (S?.confirmarReinicio) { S.confirmarReinicio = false; renderRoteiro(); } }, 5000);
    return;
  }
  S.confirmarReinicio = false;
  clearTimeout(S.tReinicio);
  try {
    const e = await api.abrirCaso(r.caso_id, true);
    S.metaTurno = {}; S.eventos = []; S.selecionado = null; S.confirmacao = null; S.evTurno = {}; S.falhou = null; S.expandido = {};
    salvarEventos();
    abrirGaveta(false);
    atualizar(e, []);
    avisar("Demonstração recomeçada.");
  } catch (e) { avisar(e.message, true); renderRoteiro(); }
  atualizarSaude();
}

// ---------------------------------------------------------------- ações
function ocupar(opcoes) {
  S.ocupado = !!opcoes;
  S.ocupadoTexto = opcoes?.texto || "";
  S.pendente = opcoes && (opcoes.fala || opcoes.evidencia) ? { texto: opcoes.fala, evidencia: opcoes.evidencia, nome: opcoes.nome } : null;
  if (!opcoes) S.progresso = null;
  S.el.enviar.disabled = S.ocupado;
  S.el.texto.disabled = S.ocupado;
  S.el.falar.classList.toggle("ocupado", S.ocupado && !S.gravando);
  const travar = S.ocupado || S.estado.etapa === "SELADO";
  S.el.anexos.querySelectorAll("button").forEach((b) => { b.disabled = travar; });
  S.el.clipe.disabled = travar;
  renderChat();
  renderRoteiro();
  renderEmitir();
}

// `opcoes`: { texto: status no indicador, fala: mensagem do fiscal (mostrada já), evidencia: tipo anexado, nome,
// restaurar: texto digitado que volta para a caixa se o envio falhar }
async function executar(fn, opcoes = {}, extraMeta = {}) {
  if (!S) return null;
  S.falhou = null;
  ocupar({ texto: opcoes.texto || "O agente está trabalhando…", fala: opcoes.fala, evidencia: opcoes.evidencia, nome: opcoes.nome });
  const t0 = performance.now();
  let r = null;
  try {
    r = await fn();
  } catch (e) {
    if (!S) return null;
    // a mensagem não se perde: fica no chat como "não enviada" com "Tentar de novo", e o texto volta para a caixa
    S.falhou = { texto: opcoes.fala, evidencia: opcoes.evidencia, nome: opcoes.nome, erro: e.message, rede: !!e.rede,
      restaurar: opcoes.restaurar || null, repetir: () => executar(fn, opcoes, extraMeta) };
    if (opcoes.restaurar && !S.el.texto.value.trim()) { S.el.texto.value = opcoes.restaurar; ajustarAltura(S.el.texto); }
    ocupar(null);
    avisar(e.message, true);
    atualizarSaude();
    return null;
  }
  if (!S) return r;
  ocupar(null);
  atualizarSaude(); // estado do modelo em dia depois de cada turno (L34)
  tratarResposta(r, Math.round(performance.now() - t0), extraMeta);
  return r;
}

function tratarResposta(r, latTotal, extraMeta = {}) {
  if (r.confirmacao) {
    S.confirmacao = r.confirmacao;
    if (r.estado) S.estado = r.estado;
    renderChat();
    tts.falar(r.fala_voz || r.confirmacao.pergunta);
    anunciar(r.confirmacao.pergunta);
    return;
  }
  if (r.aviso && !r.resposta) {
    avisar(r.aviso);
    tts.falar(r.fala_voz || r.aviso);
    if (r.estado) atualizar(r.estado, S.eventos);
    return;
  }
  S.confirmacao = null;
  if (r.aviso) avisar(r.aviso);
  const resp = r.resposta;
  if (resp) {
    resp._lat = r.latencia_ms;
    resp._origem = r.transcricao ? "asr" : extraMeta.origem;
    resp._asr_ms = r.transcricao?.latencia_ms;
  }
  const ult = r.estado?.conversa?.at(-1)?.turno;
  if (ult !== undefined && r.eventos?.length) { S.evTurno[ult] = r.eventos; salvarEventos(); }
  S.ultimoLat = `turno ${((r.latencia_ms || 0) / 1000).toFixed(1)} s` +
    (r.transcricao ? ` · ASR ${(r.transcricao.latencia_ms / 1000).toFixed(1)} s` : "") + ` · total ${(latTotal / 1000).toFixed(1)} s`;
  atualizar(r.estado, r.eventos || [], resp);
  if (resp?.fala) {
    tts.falar(r.fala_voz || resp.fala);
    const urg = (r.eventos || []).some((e) => ["bloqueio", "abstencao"].includes(e.nivel));
    anunciar(resp.fala, urg);
  }
  const passo = r.passo;
  if (r.acao_humana === "assinar" || passo?.acao === "assinar") S.irLaudo(S.id, true);
}

async function enviarTexto() {
  const t = S.el.texto.value.trim();
  if (!t || S.ocupado) return;
  S.el.texto.value = "";
  ajustarAltura(S.el.texto);
  await executar(() => api.turno(S.id, t), { fala: t, restaurar: t }, { origem: "texto" });
  S?.el.texto.focus();
}

async function confirmar(aceitar, texto) {
  S.confirmacao = null;
  await executar(() => api.confirmar(S.id, aceitar, texto), aceitar ? { fala: texto } : { texto: "Descartando…" }, { origem: "asr" });
}

async function pedirRascunho() {
  await executar(() => api.rascunho(S.id), { texto: "Pedindo o rascunho do laudo à política…" });
}

async function enviarDoCaso(nome, tipo) {
  fecharMenus();
  const texto = S.el.texto.value.trim();
  S.el.texto.value = "";
  ajustarAltura(S.el.texto);
  await executar(() => api.evidenciaCaso(S.id, nome, texto), { fala: texto, evidencia: tipo, nome, texto: STATUS_ENVIO[tipo], restaurar: texto });
}

// Menu de anexo: arquivo do aparelho (câmera no celular), item financiado e, na demonstração, os arquivos do caso.
// No celular vira uma folha que sobe de baixo (o menu dentro da conversa ficava cortado), aberta sempre do topo.
function abrirMenuAnexo(def, botao, { daFolha = false } = {}) {
  const m = S.el.menu;
  const jaAberto = !m.hidden && m.dataset.k === def.k;
  fecharMenus();
  alternarMenuVoz(false);
  if (jaAberto && !daFolha) return;
  m.dataset.k = def.k;
  S.botaoMenu = botao;
  botao?.setAttribute("aria-expanded", "true");
  const itens = S.estado.operacao.itens;
  const selItem = h("select", { id: "ev-item" }, h("option", { value: "" }, "Automático (o agente escolhe)"),
    itens.map((i) => h("option", { value: i.id, title: i.descricao }, nomeItem(i.descricao, 48))));
  const opcoes = def.opcoes.map((o) => {
    const inp = h("input", { type: "file", accept: ACEITA[o.tipo], hidden: true, ...(o.captura ? { capture: "environment" } : {}) });
    inp.addEventListener("change", () => {
      const f = inp.files[0];
      inp.value = "";
      if (!f) return;
      fecharMenus();
      enviarArquivo(f, o.tipo, selItem.value || itemPadrao(o.tipo === "documento" ? "nfe_xml" : o.tipo));
    });
    return h("span", { class: "opcao-arq" }, inp, h("button", { class: "btn btn-pri btn-bloco btn-grande", type: "button", onclick: () => inp.click() },
      icone(IC_TIPO[o.tipo] || "doc"), o.rot));
  });
  const prontos = (S.estado.roteiro?.arquivos || []).filter((a) => TIPOS_ANEXO[def.k].includes(a.tipo));
  const nome = def.rot.toLowerCase() === "nf-e" ? "NF-e" : def.rot === "GTA" ? "GTA" : def.rot.toLowerCase();
  m.replaceChildren(...[
    h("div", { class: "menu-cab" },
      daFolha ? h("button", { class: "btn btn-icone btn-fantasma btn-peq", type: "button", "aria-label": "Voltar aos tipos de evidência",
        onclick: () => abrirMenuTodos(S.el.clipe) }, icone("voltar")) : null,
      h("strong", {}, `Anexar ${nome}`),
      h("button", { class: "btn btn-icone btn-fantasma btn-peq fechar-menu", type: "button", "aria-label": "Fechar", onclick: () => fecharMenus(true) }, icone("fechar"))),
    ...opcoes,
    h("div", { class: "campo" }, h("label", { for: "ev-item" }, "Para qual item?"), selItem),
    ["foto", "video"].includes(def.k) ? h("p", { class: "nota" }, icone("pino"), "O GPS do aparelho é lido no envio.") : null,
    h("p", { class: "nota" }, "O que estiver escrito na caixa de mensagem vai junto como comentário."),
    prontos.length ? h("div", { class: "prontos" }, h("p", { class: "rotulo-sec" }, "Arquivos do caso de demonstração"),
      prontos.map((a) => h("button", { class: "btn btn-sec btn-bloco", type: "button", title: a.nome, onclick: () => enviarDoCaso(a.nome, a.tipo) },
        icone(IC_TIPO[a.tipo] || "doc"), h("span", { class: "rot-arq" }, rotuloArquivo(a)),
        a.disponivel === false ? h("span", { class: "etiqueta fake" }, "simulado") : null))) : null,
  ].filter(Boolean)); // replaceChildren escreveria "null" para um nó ausente
  abrirFolha();
  m.querySelector("button.btn-pri")?.focus({ preventScroll: true });
}

// Celular: o clipe abre a folha com os tipos de evidência (e as preferências de voz, que no celular saem do topo).
function abrirMenuTodos(botao) {
  const m = S.el.menu;
  const jaAberto = !m.hidden && m.dataset.k === "todos";
  fecharMenus();
  alternarMenuVoz(false);
  if (jaAberto) return;
  m.dataset.k = "todos";
  S.botaoMenu = botao;
  botao?.setAttribute("aria-expanded", "true");
  m.replaceChildren(
    h("div", { class: "menu-cab" }, h("strong", {}, "Anexar evidência"),
      h("button", { class: "btn btn-icone btn-fantasma btn-peq fechar-menu", type: "button", "aria-label": "Fechar", onclick: () => fecharMenus(true) }, icone("fechar"))),
    h("div", { class: "tipos-anexo" }, ANEXOS.map((d) => h("button", { class: "btn btn-sec btn-bloco btn-grande tipo-anexo", type: "button",
      onclick: () => abrirMenuAnexo(d, botao, { daFolha: true }) }, icone(d.ic), h("span", { class: "rot-arq" }, d.rot), icone("direita")))),
    h("button", { class: "btn btn-fantasma btn-bloco btn-grande", type: "button", onclick: () => { fecharMenus(); alternarMenuVoz(true); } },
      icone("ajustes"), h("span", { class: "rot-arq" }, "Preferências de voz")));
  abrirFolha();
  m.querySelector(".tipo-anexo")?.focus({ preventScroll: true });
}

function abrirFolha() {
  const m = S.el.menu;
  m.hidden = false;
  m.scrollTop = 0;
  S.el.veu.hidden = false;
}

// Rótulo legível do arquivo do caso ("Foto da cerca nº 1 — item: 1200 m de cerca…"); o nome do arquivo vai no title.
function rotuloArquivo(a) {
  const item = (S.estado.operacao.itens || []).find((i) => i.id === a.item_id);
  const doItem = item ? ` — item: ${nomeItem(item.descricao, 34)}` : "";
  const n = (String(a.nome).match(/_(\d+)\./) || [])[1];
  const sujeito = (String(a.nome).match(/^foto_([a-z]+)_/) || [])[1];
  const DE = { cerca: "da cerca", lote: "do lote", curral: "do curral" };
  if (a.tipo === "foto") return `Foto ${DE[sujeito] || ""}${n ? ` nº ${n}` : ""}`.replace(/\s+/g, " ").trim() + doItem;
  if (a.tipo === "nfe_xml") return `XML da NF-e${n ? ` nº ${n}` : ""}${doItem}`;
  if (a.tipo === "gta") {
    const num = (String(a.rotulo || "").match(/\(([^)]+)\)/) || [])[1];
    return `e-GTA${num ? ` ${num}` : ""}${doItem}`;
  }
  if (a.tipo === "documento") return `Foto da nota impressa (DANFE)${doItem}`;
  if (a.tipo === "video") {
    const dur = (String(a.rotulo || "").match(/\(([\d.,]+)\s*s\)/) || [])[1];
    return `Vídeo do lote no curral${dur ? ` (${Math.round(Number(dur.replace(",", ".")))} s)` : ""}${doItem}`;
  }
  return String(a.rotulo || a.nome).replace(/\s*\([a-z]+\d+\)$/i, "");
}

function itemPadrao(tipo) {
  const itens = S.estado.operacao.itens;
  const bov = itens.find((i) => i.tipo === "bovinos");
  if (["video", "nfe_xml", "gta"].includes(tipo)) return bov?.id || itens[0]?.id;
  return (itens.find((i) => i.tipo !== "bovinos") || itens[0])?.id;
}

async function enviarArquivo(arquivo, tipo, itemId) {
  if (S.ocupado) return;
  const comentario = S.el.texto.value.trim();
  S.el.texto.value = "";
  ajustarAltura(S.el.texto);
  const form = new FormData();
  form.append("arquivo", arquivo, arquivo.name);
  form.append("tipo", tipo);
  if (itemId) form.append("item_id", itemId);
  if (comentario) form.append("texto", comentario);
  if (arquivo.lastModified) form.append("capturada_em", new Date(arquivo.lastModified).toISOString());
  const base = { fala: comentario, evidencia: tipo, nome: arquivo.name };
  if (tipo === "foto" || tipo === "video") {
    ocupar({ ...base, texto: "Lendo o GPS do aparelho…" });
    const g = await lerGPS();
    if (!S) return;
    if (g.erro) avisar(`GPS do navegador indisponível (${g.erro}); vale o GPS do EXIF, se houver.`);
    else {
      form.append("lat", g.lat); form.append("lon", g.lon); form.append("precisao_m", g.precisao_m);
      form.append("gps_capturado_em", g.capturado_em);
    }
    ocupar(null);
  }
  S.progresso = 0;
  await executar(() => postFormProgresso(`/api/fiscalizacoes/${encodeURIComponent(S.id)}/evidencias`, form,
    (f) => {
      if (!S) return;
      S.progresso = f;
      if (f >= 1) { S.ocupadoTexto = STATUS_ENVIO[tipo] || "Arquivo recebido; o agente está conferindo…"; S.progresso = null; }
      renderChat();
    }),
  { ...base, texto: `Enviando ${ROT_TIPO[tipo] || tipo} (${(arquivo.size / 1e6).toFixed(1)} MB)…` });
}

// ---------------------------------------------------------------- voz
function ligarFalar(btn) {
  btn.addEventListener("pointerdown", (e) => { if (e.button !== 0) return; e.preventDefault(); btn.setPointerCapture?.(e.pointerId); iniciarGravacao(); });
  const parar = (e) => { if (S?.gravando) { e.preventDefault(); pararGravacao(); } };
  btn.addEventListener("pointerup", parar);
  btn.addEventListener("pointercancel", parar);
  btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); iniciarGravacao(); } });
  btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pararGravacao(); } });
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
}

function mostrarGravando(sim) {
  S.el.falar.setAttribute("aria-pressed", sim ? "true" : "false");
  S.el.nivel.hidden = !sim;
}

async function iniciarGravacao() {
  if (!S || S.gravando || S.ocupado || S.el.falar.disabled) return;
  S.gravando = true;
  mostrarGravando(true);
  try {
    if (!S.gravador) S.gravador = new Gravador({ aoNivel: (v) => { const i = S?.el.nivel.querySelector("i"); if (i) i.style.width = `${Math.round(v * 100)}%`; } });
    await S.gravador.iniciar();
  } catch (e) {
    S.gravando = false;
    mostrarGravando(false);
    avisar(`Microfone indisponível: ${e.message}`, true);
  }
}

async function pararGravacao() {
  if (!S || !S.gravando) return;
  S.gravando = false;
  mostrarGravando(false);
  const r = await S.gravador.parar();
  if (!r || r.duracaoMs < 450) { avisar("Segure o botão enquanto fala."); return; }
  const form = new FormData();
  form.append("audio", r.blob, `fala.${r.ext}`);
  form.append("confirmar_numeros", S.el.confNum.checked ? "true" : "false");
  await executar(() => postForm(`/api/fiscalizacoes/${encodeURIComponent(S.id)}/turno-audio`, form), { texto: "Transcrevendo a fala…" }, { origem: "asr" });
}
