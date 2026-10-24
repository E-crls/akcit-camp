// Fiscalização: a conversa com o agente no centro, limpa como um app de mensagens. Cada resposta com prova visual
// começa por um cartão de resultado (um número, um status); a fala do agente fica a um toque. Quando o agente recusa
// um pedido, a bolha ganha o rodapé de guarda. O último elemento da conversa é sempre o cartão "Agora": a próxima ação
// em um verbo e um botão. Ao lado (computador) ou numa folha (celular), o laudo: o indicador, o que falta e o que está
// pronto. "Ver prova" abre a prova do item numa gaveta. O técnico (regras, ferramentas, etapas, trace) fica em
// Detalhes técnicos. O analista acompanha a mesma tela, sem compositor e sem botões de ação.

import { api, postForm, postFormProgresso } from "./api.js";
import { justificativa, linhaIndicador, trilhaEtapas } from "./componentes.js";
import { falaFiscal, falaSimples } from "./fala.js";
import { miniMapa, svgMiniMapa } from "./mapa.js";
import * as R from "./regras.js";
import { PERFIS, definirTela, papel, primeiroNome } from "./sessao.js";
import { TEXTO_POL, abrirMenu, abrirModal, abrirTecnico, alternarFolha, anunciar, atualizarSaude, avatarAgente, avisar, blocoAmostra,
  blocoTec, chipNeutro, chipStatus, definirDemo, definirTopo, ehMovel, fecharMenus, fecharModal, fmtData, fmtNum, h, icone, kv,
  legivel, regraCurta, rotuloFerramenta, secaoTecnica, semIds } from "./ui.js";
import { Gravador, confirmarNumeros, lerGPS, preferenciasVoz, tts } from "./voz.js";

const STATUS_ENVIO = { video: "Contando os animais do vídeo… isso leva uns 15 s", documento: "Lendo a foto do documento…",
  nfe_xml: "Conferindo a nota fiscal…", gta: "Conferindo a GTA…", foto: "Conferindo a foto e o local…" };
const ACEITA = { foto: "image/*", video: "video/*", nfe_xml: ".xml,text/xml,application/xml", gta: ".json,application/json,.pdf",
  documento: "image/*,.pdf" };
const ORDEM_CARTAO = ["contar_bovinos_video", "geofence", "conciliar_gta", "conciliar_nfe", "ler_documento_foto"];
const ENVIO_TIPO = { nfe_xml: "a fiscal envia o arquivo da NF-e", gta: "a fiscal envia a GTA", video: "a fiscal envia o vídeo do lote",
  foto: "a fiscal envia a foto", documento: "a fiscal fotografa a nota impressa" };

let S = null;
// o foco só volta para o botão da barra depois de um novo desenho se a pessoa usava o teclado (senão a barra
// recolhida do telão abriria sozinha, como se o operador tivesse focado pelo teclado)
let usaTeclado = false;
document.addEventListener("keydown", (e) => { if (e.key === "Tab" || e.key.startsWith("Arrow") || e.key === "Enter" || e.key === " ") usaTeclado = true; }, true);
document.addEventListener("pointerdown", () => { usaTeclado = false; }, true);

export function sairFiscalizacao() {
  if (!S) return;
  clearTimeout(S.tReinicio);
  S.timers?.forEach(clearTimeout);
  document.removeEventListener("keydown", S.teclaDown);
  document.removeEventListener("keyup", S.teclaUp);
  document.removeEventListener("pointerdown", S.foraClique, true);
  clearInterval(S.tRec);
  window.removeEventListener("lv:layout", S.aoLayout);
  window.removeEventListener("lv:veu", S.aoVeu);
  S.gravador?.liberar();
  S.miniMapa?.remove?.();
  if (S.el?.grade?.classList.contains("prova-aberta") && document.getElementById("tecnico")?.hidden !== false) document.getElementById("veu-global").hidden = true;
  // fora da fiscalização não há barra da demonstração: a marca volta para a faixa do topo
  document.body.classList.remove("com-roteiro");
  window.dispatchEvent(new Event("lv:topo"));
  S = null;
  secaoTecnica("fis", null);
}

export async function telaFiscalizacao(raiz, fisId, { irLaudo, saude, campo = null }) {
  sairFiscalizacao();
  raiz.replaceChildren(h("div", { class: "fis carregando", "aria-busy": "true" }, h("p", { class: "so-leitor" }, "Carregando a fiscalização…"),
    h("div", { class: "esq-chat" }, h("div", { class: "cartao esqueleto" }), h("div", { class: "cartao esqueleto alto" }))));
  let estado;
  try { estado = await api.estado(fisId); } catch (e) {
    definirTela("fis");
    definirTopo({ trilha: [{ rot: "Carteira", href: "#/carteira" }, { rot: "Fiscalização" }], titulo: "Fiscalização", voltar: "#/" });
    raiz.replaceChildren(h("div", { class: "pagina estreita" }, h("div", { class: "vazio" }, h("h1", { class: "t-titulo" }, "Não encontrei esta fiscalização."),
      h("p", { class: "t-sec" }, e.message), h("a", { class: "btn btn-pri", href: "#/" }, "Voltar ao início"))));
    return;
  }
  definirTela("fis", { demo: !!estado.demonstracao });
  S = { id: fisId, estado, raiz, ocupado: false, pendente: null, falhou: null, progresso: null, expandido: {}, resposta: {},
    confirmacao: estado.confirmacao_pendente || null, saude, irLaudo, gravador: null, gruposAbertos: null, ultimoPronto: null,
    realce: null, eventosVivos: {}, timers: [], confirmarReinicio: false, ultimoLat: "", provaCampo: null, eco: lerEco(fisId),
    retomar: precisaRetomar(estado) };
  montar();
  atualizar(estado);
  if (campo && (estado.matriz || []).some((l) => l.campo === campo)) abrirProva(campo);
  atualizarSaude();
}

// ---------------------------------------------------------------- montagem
function montar() {
  const el = {};
  S.el = el;
  el.progresso = h("button", { class: "progresso-m", type: "button", "aria-controls": "col-itens", "aria-expanded": "false",
    onclick: () => abrirItens(true) });
  el.cab = h("div", { class: "conv-cab" });
  el.chat = h("div", { class: "chat", role: "log", "aria-label": "Conversa com o agente", "aria-live": "off" });
  // celular: quem rola a conversa para cima ganha espaço (a régua recolhe numa linha); um turno novo abre a régua de novo
  el.chat.addEventListener("scroll", () => {
    if (!S || !ehMovel() || performance.now() < (S.rolagemProgramada || 0)) return;
    const longe = el.chat.scrollHeight - el.chat.clientHeight - el.chat.scrollTop > 48;
    if (longe) S.el.grade.classList.add("rolou");
  }, { passive: true });
  // compositor: "+" (anexar), campo, microfone (vira "Enviar" com texto digitado)
  el.texto = h("textarea", { id: "fala", rows: "1", placeholder: "Mensagem para o agente", "aria-label": "Mensagem para o agente" });
  el.texto.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviarTexto(); } });
  el.texto.addEventListener("input", () => { ajustarAltura(el.texto); renderCompositor(); });
  el.anexar = h("button", { class: "anexar", type: "button", "aria-label": "Anexar foto, vídeo ou documento", "aria-haspopup": "dialog",
    "aria-expanded": "false", onclick: () => abrirAnexar() }, icone("mais"));
  el.falar = h("button", { class: "falar", type: "button", "aria-label": "Segure para falar", title: "Segure para falar" }, icone("mic"));
  ligarFalar(el.falar);
  el.enviar = h("button", { class: "enviar btn-pri", type: "button", "aria-label": "Enviar", hidden: true, onclick: enviarTexto }, icone("enviar"));
  el.gravando = h("div", { class: "gravando", hidden: true, role: "status" }, h("span", { class: "rec", "aria-hidden": "true" }),
    h("span", { class: "rec-txt" }, "Gravando… solte para enviar"), h("span", { class: "rec-t" }, "0:00"));
  el.avisoVoz = h("p", { class: "aviso-voz", hidden: true, role: "note" }, icone("info"),
    h("span", {}, "A fala é transcrita neste aparelho e entra na trilha. Avise quem estiver presente."),
    h("button", { class: "btn-icone", type: "button", "aria-label": "Fechar o aviso", onclick: () => { el.avisoVoz.hidden = true; } }, icone("x")));
  el.compositor = h("div", { class: "compositor" }, el.anexar, h("div", { class: "campo-txt" }, el.texto, el.gravando), el.falar, el.enviar);
  el.notaAnalista = h("p", { class: "nota-analista", hidden: true }, icone("info"), "Só a fiscal envia provas e conversa com o agente nesta fiscalização.");
  el.notaSelado = h("p", { class: "nota-selado", hidden: true }, icone("cadeado"), "Laudo selado: o agente responde, mas nada muda.");
  el.menuAnexar = h("div", { class: "folha-m menu-anexar", id: "menu-anexar", role: "dialog", "aria-label": "Anexar", "aria-hidden": "true" });
  el.baseConv = h("div", { class: "base-conv" }, el.avisoVoz, el.notaSelado, el.compositor, el.notaAnalista, el.menuAnexar);
  const colConversa = h("section", { class: "col-conv", id: "col-conversa", "aria-label": "Conversa com o agente" }, el.cab, el.chat, el.baseConv);
  el.roteiro = h("div", { class: "roteiro", hidden: true, role: "region", "aria-label": "Controle da demonstração" });
  el.basePalco = h("div", { class: "base-palco" }, el.roteiro);
  // painel do laudo (no celular, uma folha aberta pelo indicador)
  el.painelCab = h("div", { class: "painel-cab" });
  el.painelCorpo = h("div", { class: "painel-corpo" });
  el.painelPe = h("div", { class: "painel-pe" });
  el.itens = h("aside", { class: "painel folha-m", id: "col-itens", "aria-label": "Laudo", "aria-hidden": "false" },
    h("div", { class: "alca", "aria-hidden": "true" }), el.painelCab, el.painelCorpo, el.painelPe);
  // gaveta da prova
  el.tituloProva = h("h2", { id: "t-prova" }, "Prova");
  el.subProva = h("p", { class: "t-sec" }, "Prova do item");
  el.prova = h("div", { class: "prova-corpo" });
  el.colProva = h("section", { class: "gaveta-prova folha-m", id: "col-prova", "aria-labelledby": "t-prova", "aria-hidden": "true" },
    h("div", { class: "alca", "aria-hidden": "true" }),
    h("div", { class: "gaveta-cab" }, h("div", {}, el.subProva, el.tituloProva),
      h("button", { class: "btn-icone fechar-prova", type: "button", "aria-label": "Fechar a prova (Esc)", onclick: () => fecharProva() }, icone("x"))),
    el.prova);
  el.grade = h("div", { class: "fis", dataset: { papel: papel() } }, el.progresso,
    h("div", { class: "col-principal" }, colConversa, el.basePalco, el.colProva), el.itens);
  S.raiz.replaceChildren(el.grade);

  S.teclaDown = (e) => {
    if (!S || document.getElementById("modal").open) return;
    const alvo = e.target;
    const editavel = alvo && (alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName));
    if (e.key === "Escape") {
      if (S.el.menuAnexar.classList.contains("aberta")) { fecharAnexar(true); return; }
      if (S.el.grade.classList.contains("prova-aberta")) { fecharProva(); return; }
      if (S.el.itens.classList.contains("aberta")) { abrirItens(false); return; }
      if (S.el.roteiro.classList.contains("aberta")) { S.el.roteiro.classList.remove("aberta"); return; }
    }
    if (!editavel && (e.key === "ArrowRight" || e.key === "PageDown") && S.estado.roteiro && !e.repeat && papel() === "fiscal") {
      e.preventDefault(); proximoPasso();
    } else if (!editavel && e.code === "Space" && !alvo.closest?.("button, a, summary, label, [role=button]") && !e.repeat && vozDisponivel() && papel() === "fiscal") {
      e.preventDefault(); iniciarGravacao();
    }
  };
  S.teclaUp = (e) => { if (e.code === "Space" && S?.gravando) { e.preventDefault(); pararGravacao(); } };
  S.aoLayout = () => { if (S) { renderTudo(); } };
  S.aoVeu = () => { if (!S) return; fecharAnexar(); abrirItens(false); fecharProva(); S.el.roteiro.classList.remove("aberta"); };
  // no computador, clicar fora fecha o menu "Anexar" (popover) e a gaveta da prova
  S.foraClique = (e) => {
    if (!S || ehMovel()) return;
    const t = e.target;
    if (S.el.menuAnexar.classList.contains("aberta") && !S.el.menuAnexar.contains(t) && !S.el.anexar.contains(t)) fecharAnexar();
    if (S.el.grade.classList.contains("prova-aberta") && !S.el.colProva.contains(t) && !t.closest?.(".ver-prova, .res-prova, #modal, .leaflet-container")
      && S.el.grade.contains(t) && !S.el.itens.contains(t)) fecharProva();
  };
  document.addEventListener("pointerdown", S.foraClique, true);
  document.addEventListener("keydown", S.teclaDown);
  document.addEventListener("keyup", S.teclaUp);
  window.addEventListener("lv:layout", S.aoLayout);
  window.addEventListener("lv:veu", S.aoVeu);
}

// ---------------------------------------------------------------- modo gravação (replay) e demonstração
// No replay, cada resposta do agente vem de uma gravação casada pelo histórico da conversa: um pedido fora do roteiro
// desalinha tudo o que vem depois. Então, no replay, só passa o que corresponde ao próximo passo do roteiro; o resto
// ganha um aviso ("use Executar passo").
function emReplay() { return S?.saude?.llm?.tipo === "replay" && !!S?.estado?.roteiro; }
// Demonstração pública (QR code): o passo do roteiro sai da gravação e o resto (texto, voz, arquivo do aparelho) vai
// ao agente; o servidor reconhece a fala e o arquivo do próximo passo. Do aparelho, só foto, vídeo curto e XML.
function publica() { return !!S?.saude?.config?.demo_publica; }
const TIPOS_PUBLICOS = ["foto", "video", "nfe_xml"];
function passoAtual() { const r = S?.estado?.roteiro; return r?.passos?.[r.proximo - 1] || null; }
function arquivoDoPasso(p) { return p?.evidencia ? (S.estado.roteiro?.arquivos || []).find((a) => a.nome === p.evidencia) || null : null; }
const norm = (t) => String(t || "").toLowerCase().normalize("NFD").replace(/\p{M}/gu, "").replace(/[^a-z0-9]+/g, " ").trim();
function avisoRoteiro() {
  avisar("Esta demonstração roda uma gravação: siga o roteiro com “Executar passo” (ou a tecla →).");
}

// eco do que a fiscal leu no papel (a API guarda os campos, não a frase): fica na sessão do navegador
function lerEco(id) { try { return JSON.parse(sessionStorage.getItem(`lv.eco.${id}`) || "{}"); } catch { return {}; } }
function guardarEco() { try { sessionStorage.setItem(`lv.eco.${S.id}`, JSON.stringify(S.eco)); } catch { /* */ } }

// demonstração aberta no meio, num navegador que ainda não a viu: "Continuar do passo 11 · Recomeçar"
function precisaRetomar(e) {
  const r = e?.roteiro;
  if (!r || r.proximo <= 1 || r.proximo > r.total) return false;
  try { return sessionStorage.getItem(`lv.demoVista.${e.id}`) !== "1"; } catch { return false; }
}
function marcarVista() {
  if (!S) return;
  S.retomar = false;
  try { sessionStorage.setItem(`lv.demoVista.${S.id}`, "1"); } catch { /* */ }
}

function ctxFala() {
  const itens = S.estado.operacao.itens || [];
  const animal = itens.find((i) => i.categoria_animal)?.categoria_animal?.split(" ")[0];
  return { itens: itens.map((it) => ({ id: it.id, nome: R.nomeItem(it, true) })), animal: animal ? `${animal}s`.replace(/ss$/, "s") : "animais" };
}
function falaDoAgente(t) { return semProximoPasso(falaSimples(t, ctxFala())); }
// Um único "agora": a próxima ação está só no cartão AGORA. O "Próximo passo: …" que o agente escreve sai da fala na
// conversa (o texto original continua em Detalhes técnicos → Conversa), para a tela nunca mostrar duas ordens.
function semProximoPasso(t) {
  const s = String(t || "");
  const r = s.replace(/(^|[.!?]\s+|\n)\s*(?:O\s+)?[Pp]r[óo]ximo passo(?:\s+é|\s*:)[^\n]*?(?:[.!?](?=\s|$)|$)/g, "$1").replace(/[ \t]{2,}/g, " ").trim();
  return r.length >= 12 ? r : s;
}
// título do passo na barra da demonstração, nas palavras da tela
function tituloPasso(t) { return String(t || "").replace(/\bglebas?\b/gi, "área").replace(/\s*\(DANFE\)/g, "").replace(/\s*\(PIN \+ hash\)/g, " (PIN)"); }

function ajustarAltura(t) { t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight + 2, 160)}px`; }
function vozDisponivel() { return S?.saude?.asr?.disponivel !== false && !Gravador.motivoIndisponivel(); }
function ehDemo() { return !!S?.estado?.demonstracao; }
function ehFiscal() { return papel() === "fiscal"; }

// ---------------------------------------------------------------- atualização
function atualizar(estado, eventos = null, resp = null) {
  const anterior = S.estado;
  S.estado = estado;
  S.chkTurno = R.checagensPorTurno(estado);
  S.evPorTurno = R.evidenciaPorTurno(estado);
  S.guardas = R.guardasReconstruidas(estado);
  if (resp && eventos) {
    const ult = estado.conversa?.at(-1)?.turno;
    if (ult !== undefined) S.eventosVivos[ult] = eventos;
  }
  // o grupo de prontos que abre é o do último item que ficou pronto
  if (anterior && anterior !== estado) {
    const antes = Object.fromEntries((anterior.matriz || []).map((l) => [l.campo, R.pronta(l)]));
    const novo = R.linhas(estado).filter((l) => R.pronta(l) && !antes[l.campo]).at(-1);
    if (novo) { S.ultimoPronto = novo.campo; S.gruposAbertos = null; }
  }
  definirDemo(estado.demonstracao);
  renderTudo(anterior);
  secaoTecnica("fis", secaoFis);
}

function renderTudo(anterior = null) {
  if (!S) return;
  S.el.grade.dataset.papel = papel();
  renderTopo();
  renderCab();
  renderChat();
  renderPainel(anterior);
  renderProgressoMovel();
  if (S.el.grade.classList.contains("prova-aberta")) renderProva();
  renderRoteiro();
  renderCompositor();
}

function renderTopo() {
  const e = S.estado; const op = e.operacao;
  definirTopo({
    trilha: [{ rot: "Carteira", href: "#/carteira" }, { rot: `Op. ${op.ref_bacen}` }],
    titulo: R.nomeOperacao(op, true), sub: R.localOperacao(op),
    voltar: ehFiscal() ? "#/fiscalizacoes" : "#/carteira",
    mais: () => [
      { rot: "Por que está na amostra", ic: "info", acao: porQueAmostra },
      { rot: "Voz", sub: "Resposta falada e microfone", ic: "mic", acao: () => preferenciasVoz() },
      { rot: "Detalhes técnicos", ic: "codigo", acao: () => abrirTecnico(true) },
      { rot: document.body.classList.contains("apresentacao") ? "Sair do modo apresentação" : "Modo apresentação", ic: "compartilhar",
        acao: () => window.dispatchEvent(new CustomEvent("lv:apresentacao", { detail: !document.body.classList.contains("apresentacao") })) },
    ],
  });
}

function renderCab() {
  const op = S.estado.operacao;
  const inst = R.instituicaoLimpa(op.instituicao);
  S.el.cab.replaceChildren(h("h1", { class: "t-titulo" }, R.nomeOperacao(op)),
    h("p", { class: "t-sec" }, [R.localOperacao(op), op.valor_fmt, inst].filter(Boolean).join(" · ")));
}

function porQueAmostra() {
  const e = S.estado;
  const animal = (e.operacao.itens || []).find((i) => i.categoria_animal)?.categoria_animal?.split(" ")[0];
  const motivos = (e.triagem?.motivos || []).map((m) => R.motivoSimples(m, animal ? `${animal}s` : "animais"));
  abrirModal("Por que está na amostra", h("div", { class: "texto" },
    motivos.length ? h("ul", {}, motivos.map((m) => h("li", {}, m.endsWith(".") ? m : `${m}.`))) : h("p", {}, "Sem motivo de triagem registrado."),
    h("p", { class: "aviso-linha" }, icone("info"), "Prioridade não é indício de irregularidade: só orienta onde a visita rende mais.")));
}

// ---------------------------------------------------------------- conversa
function hora(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function renderChat() {
  const e = S.estado;
  const conversa = e.conversa || [];
  const nos = [];
  let tAnterior = null;
  let ancora = null; let agenteNo = null;
  // o rótulo "Laudo Vivo" aparece uma vez por sequência (no começo e depois de cada separador de hora); nas outras
  // mensagens do agente ele fica só para o leitor de tela (a posição à esquerda já diz quem fala)
  let rotuloVisto = false;
  if (!conversa.length && !S.pendente) { nos.push(boasVindas()); rotuloVisto = true; }
  for (const c of conversa) {
    const t = new Date(c.em).getTime();
    if (c.em && (tAnterior === null || t - tAnterior >= 5 * 60 * 1000)) { nos.push(h("div", { class: "sep-hora ok-pequeno" }, hora(c.em))); rotuloVisto = false; }
    if (c.em) tAnterior = t;
    const ult = c === conversa.at(-1);
    const fala = falaFiscal(c.fiscal) || S.eco[c.turno] || "";
    if (fala || c.evidencia) {
      const b = bolhaFiscal(fala, { turno: c.turno, tipo: c.evidencia, ev: S.evPorTurno[c.turno], em: c.em });
      nos.push(b);
      if (ult) ancora = b;
    }
    if (c.agente) {
      const a = bolhaAgente(c, !rotuloVisto);
      rotuloVisto = true;
      nos.push(a);
      if (ult) { agenteNo = a; ancora = ancora || a; }
    }
  }
  if (S.falhou) { const b = bolhaFalhou(S.falhou); nos.push(b); ancora = b; agenteNo = null; }
  if (S.pendente) {
    const b = bolhaFiscal(S.pendente.texto, { tipo: S.pendente.evidencia, nome: S.pendente.nome, enviando: true });
    nos.push(b); ancora = b; agenteNo = null;
  }
  if (S.ocupado) {
    nos.push(h("div", { class: "msg agente digitando", id: "pensando", role: "status" }, avatarAgente(),
      h("div", { class: "bolha" }, h("span", { class: "pontos", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
        h("span", { class: "pensando-txt" }, S.ocupadoTexto || "Conferindo…"),
        S.progresso !== null ? h("div", { class: "barra-envio" }, h("i", { style: { width: `${Math.round(S.progresso * 100)}%` } }))
          : /vídeo|foto|nota|GTA/i.test(S.ocupadoTexto || "") ? h("div", { class: "barra-envio indet" }, h("i")) : null)));
  } else nos.push(cartaoAgora());
  S.el.chat.replaceChildren(h("div", { class: "chat-int" }, nos));
  S.el.grade.classList.remove("rolou");
  requestAnimationFrame(() => { marcarVerMais(); rolarChat(ancora, agenteNo); });
}

function boasVindas() {
  const op = S.estado.operacao;
  if (!ehFiscal()) return h("p", { class: "sis-linha" }, "A fiscal ainda não começou esta fiscalização.");
  return h("div", { class: "msg agente boas-vindas" }, avatarAgente(),
    h("div", { class: "bolha" },
      h("p", {}, `Olá, ${primeiroNome()}! Vamos fiscalizar `, h("strong", {}, R.nomeOperacao(op)), ". Eu peço as provas, confiro cada item e preparo o laudo."),
      h("ol", { class: "passos-ini" }, h("li", {}, "Você envia as provas"), h("li", {}, "Eu confiro cada item"), h("li", {}, "Você assina o laudo")),
      // na gravação, a pergunta livre desalinharia as respostas gravadas: a sugestão só aparece ao vivo
      emReplay() ? h("p", { class: "t-sec" }, "Comece pelo cartão abaixo.")
        : h("button", { class: "btn btn-sec sugestao", type: "button", onclick: () => { marcarVista(); enviarFala("O que preciso enviar?"); } }, "O que preciso enviar?")));
}

// Rolagem depois de cada turno: o cartão AGORA (o último da conversa) fica sempre inteiro, logo acima do campo de
// mensagem. O que vem antes sobe por baixo do topo fixo (fundo sólido com filete); se do item de cima só sobrar uma
// lasca (um pedaço de cartão ou meia linha), um calço no fim da conversa empurra a lasca para fora, e o primeiro item
// visível entra inteiro.
function rolarChat() {
  if (!S) return;
  const chat = S.el.chat;
  const int = chat.firstElementChild;
  S.rolagemProgramada = performance.now() + 400;
  const fim = () => { chat.scrollTop = Math.max(0, chat.scrollHeight - chat.clientHeight); };
  fim();
  if (!int || !chat.clientHeight || chat.scrollHeight <= chat.clientHeight + 1) return;
  const t0 = chat.getBoundingClientRect().top;
  const folga = parseFloat(getComputedStyle(int).rowGap) || 12;
  let calco = 0;
  // até 6 ajustes: esconder uma linha cortada pode deixar outra (na coluna ao lado) cortada na nova borda
  for (let i = 0; i < 6; i++) {
    const cortado = [...int.children].find((el) => { const r = el.getBoundingClientRect(); return r.height > 0 && r.top < t0 - 1 && r.bottom > t0 + 1; });
    if (!cortado) break;
    const r = cortado.getBoundingClientRect();
    const visivel = r.bottom - t0;
    let mais = 0;
    if (visivel <= Math.min(chat.clientHeight * 0.24, Math.max(64, r.height * 0.45))) {
      // só uma lasca do item de cima: ela sai inteira
      mais = Math.ceil(visivel + folga - Math.min(6, folga));
    } else {
      // o item aparece quase todo: o corte não pode cair no meio de uma linha de texto (meia linha lê como defeito)
      const linha = linhaCortada(cortado, t0);
      // até o pé exato da linha: a linha seguinte começa abaixo dela (com a entrelinha) e não fica cortada
      if (linha) mais = Math.round(linha.bottom - t0 + 0.5);
    }
    if (mais <= 0 || calco + mais > chat.clientHeight * 0.3) break;
    calco += mais;
    int.style.paddingBottom = `${calco}px`;
    fim();
  }
}

// a linha de texto (do item cortado) que a borda de cima da conversa corta ao meio, se houver; o texto recolhido
// ("ver mais", "Resposta do agente" fechada) e o que é só para o leitor de tela não contam. Uma lasca de imagem conta.
function linhaCortada(el, t0) {
  // primeiro, uma faixa fina de foto, vídeo ou mapa no alto: sai a imagem inteira, com os rótulos sobre ela (uma imagem
  // bem cortada continua, como num álbum)
  let faixa = null;
  for (const m of el.querySelectorAll(".res-quadro, .res-mapa, .anexo-msg img, .anexo-msg .play, .anexo-msg .anexo-ic")) {
    const q = m.getBoundingClientRect();
    if (q.height < 2 || q.top >= t0 - 0.5 || q.bottom <= t0 + 0.5) continue;
    if (q.bottom - t0 <= Math.max(48, q.height * 0.4) && (!faixa || q.bottom > faixa.bottom)) faixa = q;
  }
  if (faixa) return faixa;
  const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const rg = document.createRange();
  let achou = null;
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    const pai = n.parentElement;
    if (!n.textContent.trim() || !pai || pai.closest(".so-leitor, .resposta-txt:not(.aberta)")) continue;
    const clip = pai.closest(".fala, .res-quadro")?.getBoundingClientRect();
    // número grande (Condensed 800): o desenho da letra passa da caixa da linha; se a caixa começa abaixo da borda, a
    // linha está inteira
    if (pai.getBoundingClientRect().top >= t0 - 0.5) continue;
    rg.selectNodeContents(n);
    for (const q of rg.getClientRects()) {
      if (q.height < 2 || (clip && (q.top >= clip.bottom - 1 || q.bottom <= clip.top + 1))) continue;
      if (q.top < t0 - 0.5 && q.bottom > t0 + 0.5 && (!achou || q.bottom > achou.bottom)) achou = q;
    }
  }
  return achou;
}

// "ver mais" só quando o texto passa de 3 linhas de verdade
function marcarVerMais() {
  S?.el.chat.querySelectorAll(".bolha .fala.clamp").forEach((f) => {
    const b = f.parentElement.querySelector(".ver-mais");
    if (b && f.scrollHeight <= f.clientHeight + 2 && !f.classList.contains("aberta")) b.hidden = true;
  });
}

function rotuloAnexo(tipo, ev, nome) {
  if (tipo === "video") {
    const arq = (S.estado.roteiro?.arquivos || []).find((a) => a.nome === (ev?.nome || nome));
    const dur = Number((String(arq?.rotulo || "").match(/\(([\d.,]+)\s*s\)/) || [])[1]?.replace(",", "."));
    return dur ? `Vídeo do lote · ${Math.floor(dur / 60)}:${String(Math.round(dur % 60)).padStart(2, "0")}` : "Vídeo do lote";
  }
  if (tipo === "foto") return ev?.gps?.precisao_m ? `Foto · GPS ±${R.fmtDec(ev.gps.precisao_m)} m` : "Foto";
  if (tipo === "documento") return "Foto da nota";
  if (tipo === "nfe_xml") return "Arquivo da NF-e";
  if (tipo === "gta") return /\.pdf$/i.test(ev?.nome || nome || "") ? "Foto da guia" : "Arquivo da GTA";
  return "Arquivo";
}

function miniaturaAnexo(tipo, ev) {
  if ((tipo === "foto" || tipo === "documento") && ev?.url && !/\.pdf$/i.test(ev.nome || "")) return h("img", { src: ev.url, alt: "", loading: "lazy" });
  if (tipo === "video") {
    const q = (S.estado.checagens || []).find((c) => c.ferramenta === "contar_bovinos_video" && c.evidencias?.includes(ev?.id))?.prova?.quadros?.[1];
    return h("span", { class: "play" }, q ? h("img", { src: q.url, alt: "", loading: "lazy" }) : null, icone("play"));
  }
  return h("span", { class: "anexo-ic" }, icone(tipo === "gta" ? "gta" : tipo === "nfe_xml" ? "arquivo" : "nota"));
}

function bolhaFiscal(texto, { tipo = null, ev = null, nome = null, em = null, enviando = false } = {}) {
  return h("div", { class: `msg fiscal${enviando ? " enviando" : ""}`, title: em ? fmtData(em) : null },
    h("div", { class: "bolha" },
      tipo ? h("div", { class: "anexo-msg" }, miniaturaAnexo(tipo, ev), h("span", {}, rotuloAnexo(tipo, ev, nome))) : null,
      texto ? h("div", { class: "fala" }, texto) : null,
      enviando ? h("span", { class: "enviando-txt ok-pequeno" }, "enviando…") : null));
}

function guardaDoTurno(turno) {
  const vivos = S.eventosVivos[turno];
  const g = vivos ? R.guardaDoTurno(vivos) : null;
  if (g) return g;
  const rec = (S.guardas[turno] || []).find((x) => x.tipo !== "bloqueio" && x.tipo !== "negado");
  return rec ? { tipo: rec.tipo, ev: rec } : null;
}

function bolhaAgente(c, comRotulo = true) {
  const texto = falaDoAgente(c.agente);
  const card = cartaoResultado(c);
  const g = guardaDoTurno(c.turno);
  const aberta = !!S.expandido[c.turno];
  const nos = [];
  const bolha = h("div", { class: `bolha${card ? " com-cartao" : ""}` });
  if (card) {
    const fala = h("div", { class: `fala resposta-txt${S.resposta[c.turno] ? " aberta" : ""}`, id: `resp-${c.turno}` }, texto);
    const tog = h("button", { class: "resposta", type: "button", "aria-expanded": S.resposta[c.turno] ? "true" : "false", "aria-controls": `resp-${c.turno}`,
      onclick: () => { S.resposta[c.turno] = !S.resposta[c.turno]; fala.classList.toggle("aberta", !!S.resposta[c.turno]);
        tog.setAttribute("aria-expanded", S.resposta[c.turno] ? "true" : "false"); } },
    icone("balao"), h("span", {}, "Resposta do agente"), icone("baixo", "seta"));
    // "Resposta do agente" vai na mesma linha de "Ver prova" (no computador, lado a lado): o cartão fica baixo o
    // bastante para caber inteiro com o AGORA no telão
    const acoes = card.querySelector(".res-acoes");
    if (acoes) { acoes.insertBefore(tog, acoes.querySelector(".res-item")); nos.push(card, fala); } else nos.push(card, tog, fala);
  } else {
    const fala = h("div", { class: `fala clamp${aberta ? " aberta" : ""}` }, texto);
    const ver = h("button", { class: "ver-mais", type: "button", "aria-expanded": aberta ? "true" : "false" },
      h("span", {}, aberta ? "ver menos" : "ver mais"), icone("baixo", "seta"));
    const alternar = () => {
      S.expandido[c.turno] = !S.expandido[c.turno];
      fala.classList.toggle("aberta", !!S.expandido[c.turno]);
      ver.setAttribute("aria-expanded", S.expandido[c.turno] ? "true" : "false");
      ver.firstChild.textContent = S.expandido[c.turno] ? "ver menos" : "ver mais";
    };
    ver.addEventListener("click", (ev) => { ev.stopPropagation(); alternar(); });
    bolha.addEventListener("click", (ev) => { if (!ev.target.closest("button, a") && !ver.hidden) alternar(); });
    nos.push(fala, ver);
  }
  if (g) nos.push(rodapeGuarda(c.turno, g));
  bolha.append(...nos);
  const rot = avatarAgente();
  if (!comRotulo) rot.classList.add("so-leitor");
  return h("div", { class: `msg agente${comRotulo ? "" : " seguida"}`, dataset: { turno: String(c.turno) }, title: c.em ? fmtData(c.em) : null }, rot, bolha);
}

function rodapeGuarda(turno, g) {
  const def = R.GUARDAS[g.tipo] || R.GUARDAS.negado;
  const realce = S.realce === turno && document.body.classList.contains("apresentacao");
  const b = h("button", { class: `guarda-rod${realce ? " realce" : ""}`, type: "button", onclick: () => porQueGuarda(g) },
    icone(def.ic), h("span", { class: "g-txt" }, def.texto), h("span", { class: "g-porque" }, "Por quê?"), icone("direita"));
  if (realce) {
    S.timers.push(setTimeout(() => { b.classList.remove("realce"); if (S) S.realce = null; }, 3000));
  }
  return b;
}

function porQueGuarda(g) {
  const e = S.estado;
  const rid = String(g.ev?.rule_id || "");
  const pol = (rid.match(/POL-\d+/) || [])[0];
  const corpo = [];
  if (g.tipo === "pressao") {
    corpo.push(h("p", { class: "destaque" }, "O número só muda com nova prova."),
      h("p", {}, "O agente não muda um resultado por pedido. Se algo mudou em campo, envie um vídeo, uma foto ou um documento novo."));
    const o = (e.ocorrencias || []).find((x) => x.tipo === "pressao");
    if (o) corpo.push(h("p", {}, h("strong", {}, "Registrado no laudo: "), R.textoOcorrencia(e, o)));
  } else if (g.tipo === "injecao") {
    const o = (e.ocorrencias || []).find((x) => x.tipo === "injecao");
    const pads = (String(o?.descricao || "").match(/padrões:\s*([^)]*)/) || [])[1];
    const pede = pads ? pads.split(/,\s*/).map((p) => ({ ignorar_regras: "ignorar as regras", aprovar_laudo: "aprovar o laudo" }[p] || p.replaceAll("_", " "))).join(" e ") : null;
    const campo = /observa/i.test(o?.descricao || "") ? "no campo de observação do documento" : "no documento";
    corpo.push(h("p", { class: "destaque" }, "Instrução escondida no documento: ignorada."),
      h("p", {}, `O documento trazia um texto ${campo}${pede ? ` pedindo para ${pede}` : ""}. O agente tratou esse texto como dado, não como ordem, e registrou a ocorrência.`));
  } else if (g.tipo === "assinatura") {
    corpo.push(h("p", { class: "destaque" }, "O agente não assina. A assinatura é sua."),
      h("p", {}, "Só a fiscal assina, com o PIN, depois de revisar o laudo. O agente prepara e confere; quem responde pelo laudo é quem assina."));
  } else if (g.tipo === "selado") {
    corpo.push(h("p", { class: "destaque" }, "Laudo selado: nada muda."), h("p", {}, "Depois do selo, nenhum item muda. Correção abre uma nova fiscalização."));
  } else corpo.push(h("p", {}, semIds(g.ev?.texto || "A política não permitiu este pedido.")));
  if (pol) {
    corpo.push(h("div", { class: "regra-bloco" }, h("p", {}, TEXTO_POL[pol] || semIds(g.ev?.texto || ""))),
      h("details", { class: "regra-det" }, h("summary", {}, "Regra e detalhes"), kv([["Regra", pol, "mono"], g.ev?.texto ? ["Registro", semIds(g.ev.texto)] : null])));
  }
  abrirModal("Por quê?", h("div", { class: "texto" }, corpo));
}

// ---------------------------------------------------------------- cartão de resultado (um número, um status)
function linhaDaChecagem(chk, sufixos) {
  const ls = R.linhas(S.estado);
  return ls.find((l) => (l.checagens || []).includes(chk.id) && (!sufixos || sufixos.some((s) => l.campo.endsWith(s))))
    || ls.find((l) => l.item_id === chk.item_id && sufixos?.some((s) => l.campo.endsWith(s))) || null;
}

function cartaoResultado(c) {
  const chks = S.chkTurno[c.turno] || [];
  const chk = ORDEM_CARTAO.map((f) => chks.find((x) => x.ferramenta === f)).find(Boolean);
  if (!chk) return null;
  const p = chk.prova || {};
  const e = S.estado;
  let midia = null; let numero = null; let pill = null; let legenda = null; let campo = null; let falta = null; let contador = null;
  // O cartão não dá ordem: a próxima ação é só o cartão AGORA. Ele diz o que ficou faltando enquanto o item falta (o
  // cartão é de um turno passado; o estado é o de agora) e, depois, que a divergência foi justificada.
  const faltaLinha = (l, texto) => (l && R.ehFalta(l) ? { texto, feito: false } : l && R.justificada(l) ? { texto: "Divergência justificada.", feito: true } : null);
  if (chk.ferramenta === "contar_bovinos_video") {
    const l = linhaDaChecagem(chk, [":quantidade"]);
    campo = l?.campo;
    const it = (e.operacao.itens || []).find((i) => i.id === (l?.item_id || chk.item_id));
    const fin = it?.quantidade;
    if (p.abstencao || chk.status === "indeterminado" || chk.status === "erro" || p.contagem === undefined || p.contagem === null) {
      // a causa de verdade: arquivo que não abriu não é "câmera tremida"
      const causa = [chk.resumo, ...(p.motivos || [])].join(" ");
      const arquivoRuim = /ileg[ií]vel|corromp|inv[aá]lid|n[aã]o (?:abriu|foi poss[ií]vel abrir|consegui abrir)|formato/i.test(causa);
      numero = h("span", { class: "num-g" }, arquivoRuim ? "Arquivo não abriu" : "Sem contagem");
      pill = chipStatus("abstencao");
      legenda = arquivoRuim ? "O vídeo não abriu. Envie de novo." : (p.pedidos_recaptura || [])[0] || "O vídeo não permitiu contar. Apoie o celular e deixe a câmera parada.";
    } else {
      numero = h("span", { class: "num-g" }, R.fmtInt(p.contagem), h("small", {}, ` de ${R.fmtInt(fin)}`));
      pill = chipStatus(l?.status || "verificado");
      const min = Array.isArray(p.intervalo) ? p.intervalo[0] : p.contagem;
      const max = Array.isArray(p.intervalo) ? p.intervalo[1] : p.contagem;
      const faixa = Number(min) === Number(max) ? `${R.fmtInt(max)} animais` : `de ${R.fmtInt(min)} a ${R.fmtInt(max)} animais`;
      legenda = Number(max) >= Number(fin) ? `Contamos ${faixa} no vídeo; o financiado é ${R.fmtInt(fin)}: confere.`
        : `Contamos ${faixa} no vídeo; o financiado é ${R.fmtInt(fin)}.`;
      falta = faltaLinha(l, "Falta a justificativa ou um vídeo novo.");
      contador = contadorMarcas(p.contagem, max, fin);
    }
    // o quadro limpo do próprio vídeo (as caixas com id e confiança do detector ficam em "Ver prova" e em Detalhes técnicos)
    const qs = p.quadros || [];
    const melhor = qs.reduce((a, q) => (!a || q.contagem_ate_aqui > a.contagem_ate_aqui ? q : a), null);
    if (melhor && p.video_url) midia = quadroLimpo(chk, p.video_url, melhor);
  } else if (chk.ferramenta === "geofence") {
    const l = linhaDaChecagem(chk, [":localizacao", ":existencia"]);
    campo = l?.campo;
    const d = p.distancia_borda_m;
    const dentro = chk.status === "ok";
    numero = h("span", { class: "num-g" }, dentro ? "Dentro da área" : `a ${R.fmtInt(R.arred10(d))} m`);
    pill = dentro ? chipStatus("verificado") : chipStatus("pendente");
    legenda = dentro ? "A foto foi tirada dentro da área financiada." : "da borda da área financiada. A foto precisa ser de dentro.";
    if (!dentro) falta = faltaLinha(l, "Falta uma foto de dentro da área ou a justificativa.");
    midia = h("div", { class: "res-mapa" }, svgMiniMapa(p.glebas || e.operacao.glebas, p.gps, dentro ? null : d,
      { w: 260, h: 128, rotulo: dentro ? null : `${R.fmtInt(R.arred10(d))} m` }));
  } else if (chk.ferramenta === "conciliar_gta") {
    const l = linhaDaChecagem(chk, [":gta"]);
    campo = l?.campo;
    numero = h("span", { class: "num-m" }, l && l.status === "divergente" ? R.motivoGta(l) : "GTA da compra");
    pill = chipStatus(l?.status || (chk.status === "ok" ? "verificado" : chk.status));
    legenda = l?.status === "verificado" ? "Confere com a compra." : l?.status === "divergente" ? "A guia não pode sair antes da compra." : null;
    if (l?.status === "divergente") falta = faltaLinha(l, "Falta a justificativa ou a GTA certa.");
  } else if (chk.ferramenta === "conciliar_nfe") {
    if (!["ok", "divergente"].includes(chk.status)) return null;
    const l = linhaDaChecagem(chk, [":comprovante_nfe", ":nfe"]);
    campo = l?.campo;
    numero = h("span", { class: "num-m" }, "Nota fiscal da compra");
    pill = chipStatus(l?.status || (chk.status === "ok" ? "verificado" : "divergente"));
    legenda = chk.status === "ok" ? "Confere com a compra." : legivel((p.motivos || [])[0] || chk.resumo || "");
    if (l?.status === "divergente") falta = faltaLinha(l, "Falta a justificativa ou a nota certa.");
  } else if (chk.ferramenta === "ler_documento_foto") {
    const l = linhaDaChecagem(chk, [":comprovante_nfe", ":nfe"]);
    campo = l?.campo;
    const ev = (e.evidencias || []).find((x) => x.id === chk.evidencias?.[0]);
    if (ev?.url) midia = h("div", { class: "res-quadro doc" }, h("img", { src: ev.url, alt: "Foto da nota impressa", loading: "lazy" }));
    numero = h("span", { class: "num-m" }, "Nota lida pela foto");
    const resid = e.residual && e.residual.checagem_id === chk.id;
    pill = resid || l?.status === "pendente" ? chipStatus("pendente") : chipStatus(l?.status || "verificado");
    const n = (e.residual?.campos || []).length;
    legenda = resid ? `${n === 1 ? "Falta 1 campo" : `Faltam ${n} campos`} do papel.` : l?.status === "pendente" ? "Falta o arquivo da NF-e para fechar a nota." : "Confere com a compra.";
  }
  const verProva = campo ? h("button", { class: "res-prova", type: "button", onclick: () => abrirProva(campo) }, h("span", {}, "Ver prova"), icone("direita")) : null;
  // a etiqueta do item, como numa ficha de campo: "Item 02", na ordem do laudo (os itens que pedem prova da fiscal)
  const us = R.unidades(e).filter((u) => !u.agente);
  const iu = campo ? us.findIndex((u) => u.campos.includes(campo)) : -1;
  // no celular a etiqueta abre o cartão; no computador ela fecha a linha de ações (o cartão fica baixo para o telão)
  const etq = (onde) => (iu >= 0 ? h("span", { class: `res-item ${onde}`, role: "note", "aria-label": `Item ${iu + 1} de ${us.length}` }, h("span", { "aria-hidden": "true" }, "Item "),
    h("b", { "aria-hidden": "true" }, String(iu + 1).padStart(2, "0")), h("span", { class: "de", "aria-hidden": "true" }, `/${String(us.length).padStart(2, "0")}`)) : null);
  return h("div", { class: `res${midia ? " com-midia" : ""}${midia?.classList.contains("res-mapa") ? " com-mapa" : ""}` },
    midia,
    h("div", { class: "res-txt" }, etq("so-movel"), h("div", { class: "res-linha" }, numero, pill), legenda ? h("p", { class: "res-leg" }, legenda) : null, contador,
      falta ? h("p", { class: `res-falta${falta.feito ? " feito" : ""}` }, icone(falta.feito ? "diverge" : "falta"), h("span", {}, falta.texto)) : null,
      h("div", { class: "res-acoes" }, verProva, etq("so-computador"))));
}

const mmss = (s) => `${Math.floor(Number(s) / 60)}:${String(Math.floor(Number(s) % 60)).padStart(2, "0")}`;

// Quadro do vídeo no instante da última contagem, tirado do próprio vídeo (sem as caixas de depuração do detector), com
// a etiqueta "12 contados até 0:12 de 0:17". O elemento é guardado por checagem: o vídeo não recarrega a cada turno.
function quadroLimpo(chk, url, q) {
  S.quadros ||= {};
  const chave = `${chk.id}:${q.t_s}`;
  if (S.quadros[chave]) return S.quadros[chave];
  const t = Number(q.t_s) || 0;
  const ev = (S.estado.evidencias || []).find((x) => x.id === chk.evidencias?.[0]);
  const arq = (S.estado.roteiro?.arquivos || []).find((a) => a.nome === ev?.nome);
  const dur0 = Number((String(arq?.rotulo || "").match(/\(([\d.,]+)\s*s\)/) || [])[1]?.replace(",", "."));
  const rotulo = (dur) => `até ${mmss(t)}${dur ? ` de ${mmss(dur)}` : ""}`;
  const resto = document.createTextNode(rotulo(dur0));
  const v = h("video", { muted: true, playsinline: true, preload: "auto", src: `${url}#t=${t}`, tabindex: "-1", "aria-hidden": "true", disablepictureinpicture: true });
  v.muted = true;
  v.addEventListener("loadedmetadata", () => { if (!dur0 && Number.isFinite(v.duration)) resto.textContent = rotulo(v.duration); });
  v.addEventListener("error", () => v.remove(), { once: true });
  const el = h("div", { class: "res-quadro video", role: "img", "aria-label": `Quadro do vídeo em ${mmss(t)}: ${q.contagem_ate_aqui} animais contados até aqui` },
    v, h("span", { class: "res-etq", "aria-hidden": "true" }, h("span", { class: "l1" }, h("b", {}, R.fmtInt(q.contagem_ate_aqui)), " contados"), h("span", { class: "l2" }, resto)));
  S.quadros[chave] = el;
  return el;
}

// Contador: uma marca por animal financiado (cheia = contado; listrada = até o teto da incerteza; vazia = falta)
function contadorMarcas(c, max, fin) {
  const n = Number(fin); const k = Number(c); const m = Math.min(n, Math.max(k, Number(max) || k));
  if (!Number.isFinite(n) || !Number.isFinite(k) || n < 2 || n > 80) return null;
  const marcas = Array.from({ length: n }, (_, i) => h("i", { class: i < k ? "c" : i < m ? "t" : null }));
  return h("div", { class: "contador", role: "img", "aria-label": `${k} contados, até ${m} com a incerteza, de ${n} financiados` },
    h("div", { class: "marcas", style: { "--n": String(n) } }, marcas),
    h("p", { class: "leg", "aria-hidden": "true" }, h("span", {}, h("b", {}, R.fmtInt(k)), " contados"), m > k ? h("span", {}, "até ", h("b", {}, R.fmtInt(m))) : null,
      h("span", {}, h("b", {}, R.fmtInt(n)), " financiados")));
}

function bolhaFalhou(f) {
  // demonstração pública: a recusa do app (limites da demonstração, voz ocupada, arquivo grande) vem escrita para a tela;
  // o erro interno (5xx) continua com a frase de sempre
  const doServidor = publica() && f.amigavel && !f.rede && f.status < 500;
  // arquivo grande demais ou de tipo errado: mandar o mesmo de novo não adianta
  const repetir = !(doServidor && [413, 415].includes(f.status));
  return h("div", { class: "msg sistema", role: "alert" },
    h("div", { class: "bolha" }, h("p", {}, f.rede ? "Sem conexão. Nada foi enviado." : doServidor ? f.erro : "Não consegui falar com o servidor. Tente de novo."),
      f.texto ? h("p", { class: "t-sec" }, `Sua mensagem: “${f.texto}”`) : null,
      h("div", { class: "acoes-linha" }, repetir ? h("button", { class: "btn btn-sec", type: "button", onclick: tentarDeNovo }, icone("recomecar"), "Tentar de novo") : null,
        h("button", { class: "btn btn-ter", type: "button", onclick: () => { S.falhou = null; renderChat(); } }, repetir ? "Descartar" : "Fechar"))));
}
function tentarDeNovo() {
  const f = S?.falhou;
  if (!f || S.ocupado) return;
  S.falhou = null;
  if (f.restaurar && S.el.texto.value.trim() === f.restaurar) { S.el.texto.value = ""; ajustarAltura(S.el.texto); }
  f.repetir();
}

// ---------------------------------------------------------------- cartão "Agora" (sempre o último da conversa)
function passoEmissao() {
  const r = S.estado.roteiro;
  const p = r?.passos?.[r.proximo - 1];
  return !!p && !S.ocupado && /emiss|emitir/i.test(`${p.titulo} ${p.fala}`) && !/bloquead/i.test(p.titulo);
}

function cartaoAgora() {
  const a = R.agora(S.estado, { papel: papel(), confirmacao: S.confirmacao });
  const cls = `agora${a.acomp ? " acomp" : ""}${a.selado ? " selado" : ""}${a.bloqueio ? " bloqueio" : ""}`;
  const extra = [];
  if (a.bloqueio) {
    extra.push(h("p", { class: "t-sec so-computador" }, a.apoio),
      h("ul", { class: "faltas-curtas so-movel" }, a.faltasCurtas.map((f) => h("li", {}, h("span", { class: `si si-${f.tipo === "div" ? "div" : "falta"}` }, icone(f.ic)), f.titulo))),
      h("p", { class: "t-sec so-movel" }, a.apoioMovel));
  } else if (a.apoio) extra.push(h("p", { class: "t-sec agora-apoio" }, a.apoio));
  if (a.residual) extra.push(camposResidual(a.residual));
  if (a.confirmacao) {
    S.el.confTexto = h("input", { type: "text", class: "entrada", value: a.confirmacao.texto || "", "aria-label": "O que entendi (pode corrigir)" });
    extra.push(h("label", { class: "campo-agora" }, h("span", { class: "t-sec" }, "O que entendi (pode corrigir)"), S.el.confTexto));
  }
  // demonstração pública: a câmera só é a ação principal quando o passo do roteiro pede aquele arquivo
  const lista = publica() && ehFiscal() && S.estado.roteiro ? R.acoesAgoraPublica(a.acoes, passoAtual(), { doPasso: acaoDoPasso, ehArquivo: (x) => !!ACAO_ARQ[x] })
    : a.acoes;
  const acoes = lista.map((ac, i) => {
    const pri = i === 0;
    const realce = ac.acao === "emitir" && passoEmissao();
    const b = h("button", { class: `btn ${pri ? "btn-pri" : "btn-sec"}${realce ? " realce" : ""}`, type: "button", id: ac.acao === "emitir" ? "btn-rascunho" : null,
      dataset: { acao: ac.acao }, disabled: S.ocupado ? true : null, onclick: () => executarAcao(ac.acao, b) }, ac.ic ? icone(ac.ic) : null, ac.rot);
    if (ac.acao === "falar") ligarFalar(b, true);
    return b;
  });
  return h("section", { class: cls, id: "agora", role: "region", "aria-label": a.acomp ? "Acompanhamento" : "Próxima ação" },
    h("div", { class: "agora-txt" }, h("span", { class: "rot" }, a.rot), h("h3", {}, a.titulo), ...extra),
    acoes.length ? h("div", { class: `acoes${lista !== a.acoes ? " com-passo" : ""}` }, acoes) : null);
}

function camposResidual(p) {
  S.el.residual = [];
  const linhas = (p.campos || []).map((c) => {
    const alvo = c.formato === "municipio" ? (c.campos || []).slice(0, 1) : (c.campos || []);
    const nomes = c.confirmar ? alvo.flatMap((n) => [n, `${n}#2`]) : alvo;
    return h("li", {}, h("span", { class: "t-sec" }, R.maiuscula(c.instrucao || c.rotulo)), nomes.map((n) => {
      const numerico = ["digitos", "numero", "grade", "documento"].includes(c.formato);
      const inp = h("input", { type: "text", class: "entrada", "data-campo": n, inputmode: numerico ? "numeric" : null, autocomplete: "off",
        "aria-label": `${c.rotulo}${n.endsWith("#2") ? " (repita)" : ""}`, placeholder: n.endsWith("#2") ? "repita para conferir" : c.n_digitos ? `${c.n_digitos} dígitos` : "" });
      S.el.residual.push(inp);
      inp.addEventListener("input", () => { const m = inp.parentElement?.querySelector(`.erro-campo[data-de="${CSS.escape(n)}"]`); if (m) m.hidden = true; });
      return [inp, h("p", { class: "erro-campo", "data-de": n, role: "alert", hidden: true })];
    }));
  });
  return h("ol", { class: "residual" }, linhas);
}

// ---------------------------------------------------------------- ações do "Agora" e da lista de faltas
function itemPara(tipo) {
  const itens = S.estado.operacao.itens || [];
  const bov = itens.find((i) => R.ehBovino(i));
  if (["video", "nfe_xml", "gta", "documento"].includes(tipo)) return bov?.id || itens[0]?.id;
  return (itens.find((i) => !R.ehBovino(i)) || itens[0])?.id;
}

const ACAO_ARQ = {
  filmar: { tipo: "video", accept: "video/*", capture: true }, "galeria-video": { tipo: "video", accept: "video/*" },
  "fotografar-nota": { tipo: "documento", accept: "image/*", capture: true }, "arquivo-nfe": { tipo: "nfe_xml", accept: ACEITA.nfe_xml },
  "fotografar-gta": { tipo: "documento", accept: "image/*", capture: true, item: "gta" }, "arquivo-gta": { tipo: "gta", accept: ACEITA.gta },
  "fotografar-cerca": { tipo: "foto", accept: "image/*", capture: true }, "refazer-foto": { tipo: "foto", accept: "image/*", capture: true },
  "galeria-foto": { tipo: "foto", accept: "image/*" },
};
const COMPATIVEL = { video: ["video"], documento: ["documento"], nfe_xml: ["nfe_xml"], gta: ["gta", "documento"], foto: ["foto"] };
// a ação abre o arquivo pronto do próximo passo do roteiro (o modal "Arquivo da demonstração", não a câmera)
function acaoDoPasso(acao) {
  const d = ACAO_ARQ[acao];
  const arq = arquivoDoPasso(passoAtual());
  return !!(d && arq && (COMPATIVEL[d.tipo] || []).includes(arq.tipo));
}

function executarAcao(acao, botao = null) {
  if (!S || S.ocupado) return;
  const p = passoAtual();
  const replay = emReplay();
  if (acao === "executar-passo") { proximoPasso(); return; }
  if (ACAO_ARQ[acao]) { capturar(ACAO_ARQ[acao]); return; }
  if (acao.startsWith("justificar:")) {
    const campo = acao.slice(11);
    const suf = campo.split(":").pop();
    // na gravação, a justificativa é a do roteiro (o agente responde à frase gravada): ela vem pronta no campo; na
    // demonstração pública também, quando é o próximo passo (sai da gravação, sem custo); senão, o modelo da frase
    if (replay || publica()) {
      const doPasso = p && p.acao === "turno" && !p.evidencia && /^confirmo a diverg|justific/i.test(norm(p.fala))
        && (suf !== "quantidade" || /contagem/i.test(p.fala)) && (suf !== "gta" || /gta/i.test(p.fala));
      if (doPasso) { marcarVista(); escrever(p.fala); return; }
      if (replay) { avisoRoteiro(); return; }
    }
    const modelo = suf === "quantidade" ? "Confirmo a divergência na contagem: " : suf === "gta" ? "Confirmo a divergência da GTA: "
      : suf === "localizacao" ? "Justifico a foto fora da área: " : "Confirmo a divergência: ";
    escrever(modelo);
    return;
  }
  if (acao.startsWith("escrever:")) { if (replay) { avisoRoteiro(); return; } escrever(acao.slice(9)); return; }
  if (acao.startsWith("perguntar:")) { if (replay) { avisoRoteiro(); return; } enviarFala(acao.slice(10)); return; }
  if (acao === "declarar") {
    if (replay) { if (p && /declaro/i.test(p.fala || "")) proximoPasso(); else avisoRoteiro(); return; }
    enviarFala("Declaro que não presto assistência técnica ao produtor nem tenho vínculo com empresa dele.");
    return;
  }
  if (acao === "confirmar") { confirmar(true, S.el.confTexto?.value || S.confirmacao?.texto || ""); return; }
  if (acao === "corrigir") { const t = S.el.confTexto?.value || ""; confirmar(false).then(() => escrever(t)); return; }
  if (acao === "completar-nota") {
    if (replay) { if (p?.acao === "residual") proximoPasso(); else avisoRoteiro(); return; }
    enviarResidual();
    return;
  }
  if (acao === "emitir") {
    // na gravação, "Emitir" é o passo da emissão do roteiro (o pedido de emissão gravado)
    if (replay) { if (p && !p.evidencia && p.acao !== "assinar" && /emiti/i.test(p.fala || "") && !R.faltas(S.estado).length) proximoPasso(); else avisoRoteiro(); return; }
    pedirRascunho();
    return;
  }
  if (acao === "revisar-assinar") { S.irLaudo(S.id, true); return; }
  if (acao === "ver-laudo") { location.hash = `#/fis/${encodeURIComponent(S.id)}/laudo`; return; }
  if (acao === "baixar-pacote") { location.hash = `#/fis/${encodeURIComponent(S.id)}/laudo?pacote=1`; return; }
  if (acao === "anexar") { abrirAnexar(); return; }
  if (acao === "falar") return;
  if (botao) avisar("Ação indisponível.");
}

// Fotografar, filmar, nota, GTA. Na demonstração, quando o caso tem o arquivo pronto do próximo passo, o botão pede
// confirmação e mostra a mensagem que vai junto (nada sai sozinho); fora dela, abre a câmera ou o seletor do aparelho.
const ICONE_TIPO = { video: "video", foto: "camera", documento: "nota", nfe_xml: "arquivo", gta: "gta" };
function capturar(d) {
  const p = passoAtual();
  const doPasso = arquivoDoPasso(p);
  const arq = doPasso && (COMPATIVEL[d.tipo] || []).includes(doPasso.tipo) ? doPasso : null;
  if (!S.estado.roteiro) { doAparelho(d); return; }
  if (emReplay() && !arq) { avisoRoteiro(); return; }
  if (publica() && !arq && !TIPOS_PUBLICOS.includes(d.tipo)) {
    avisar("Na demonstração pública, a foto da nota e a GTA vêm dos arquivos prontos do caso (+ › Arquivo da demonstração).");
    return;
  }
  if (!arq) { doAparelho(d); return; }
  marcarVista();
  const corpo = h("div", { class: "texto demo-arquivo" },
    h("p", {}, "Nesta demonstração, o arquivo vem pronto do caso:"),
    h("p", { class: "arq-demo" }, h("span", { class: "ic-quadro" }, icone(ICONE_TIPO[arq.tipo] || "arquivo")), h("strong", {}, rotuloArquivoDemo(arq))),
    p.fala ? h("p", { class: "t-sec" }, "Vai junto a mensagem: ", h("q", {}, p.fala)) : null,
    h("div", { class: "acoes-linha" },
      h("button", { class: "btn btn-pri", type: "button", onclick: () => { fecharModal(); proximoPasso(); } }, icone("enviar"), "Enviar este arquivo"),
      emReplay() || (publica() && !TIPOS_PUBLICOS.includes(d.tipo)) ? null : h("button", { class: "btn btn-sec", type: "button",
        onclick: () => { fecharModal(); doAparelho(d); } }, icone(d.tipo === "video" ? "video" : "camera"), "Usar um meu")),
    emReplay() ? h("p", { class: "t-sec" }, "Esta demonstração roda uma gravação: só o arquivo do roteiro.") : null);
  abrirModal("Arquivo da demonstração", corpo);
}
function doAparelho(d) {
  escolherArquivo(d, (f) => { const tipo = d.tipo === "gta" && /\.pdf$/i.test(f.name) ? "documento" : d.tipo; enviarArquivo(f, tipo, itemPara(tipo)); });
}

function escrever(texto) {
  abrirItens(false);
  S.el.texto.value = texto;
  ajustarAltura(S.el.texto);
  renderCompositor();
  S.el.texto.focus();
  S.el.texto.setSelectionRange(texto.length, texto.length);
}

function escolherArquivo(d, aoEscolher) {
  const inp = h("input", { type: "file", accept: d.accept, hidden: true, ...(d.capture ? { capture: "environment" } : {}) });
  inp.addEventListener("change", () => { const f = inp.files[0]; inp.remove(); if (f) aoEscolher(f); });
  document.body.append(inp);
  inp.click();
}

// ---------------------------------------------------------------- compositor
function renderCompositor() {
  if (!S) return;
  const fiscal = ehFiscal();
  const selado = S.estado.etapa === "SELADO";
  S.el.compositor.hidden = !fiscal;
  S.el.notaAnalista.hidden = fiscal;
  S.el.notaSelado.hidden = !fiscal || !selado;
  const tem = !!S.el.texto.value.trim();
  S.el.enviar.hidden = !tem;
  S.el.falar.hidden = tem;
  S.el.falar.setAttribute("aria-disabled", vozDisponivel() ? "false" : "true");
  S.el.falar.title = vozDisponivel() ? "Segure para falar" : "Voz desligada nesta execução: digite a mensagem";
  S.el.texto.disabled = S.ocupado;
  S.el.enviar.disabled = S.ocupado;
  S.el.anexar.disabled = S.ocupado || selado;
  if (!fiscal) fecharAnexar();
}

// Folha "Anexar": para o que o agente não pediu (o que ele pediu está no "Agora").
function abrirAnexar(sub = null) {
  const m = S.el.menuAnexar;
  if (!sub && m.classList.contains("aberta") && !m.dataset.sub) { fecharAnexar(); return; }
  m.dataset.sub = sub || "";
  const linha = (rot, apoio, ic, onclick, cls = "") => h("button", { class: `linha-anexo ${cls}`, type: "button", onclick },
    h("span", { class: "ic-quadro" }, icone(ic)), h("span", { class: "txt" }, h("strong", {}, rot), apoio ? h("span", {}, apoio) : null), icone("direita"));
  const arq = (acao) => () => { fecharAnexar(); executarArquivo(acao); };
  let corpo;
  const pub = publica();
  if (sub === "nota") corpo = [pub ? null : linha("Fotografar a nota", "A nota impressa (DANFE)", "camera", arq("fotografar-nota")), linha("Arquivo da NF-e (.xml)", "O arquivo que o vendedor enviou", "arquivo", arq("arquivo-nfe"))].filter(Boolean);
  else if (sub === "gta") corpo = [linha("Fotografar a guia", "A GTA impressa", "camera", arq("fotografar-gta")), linha("Arquivo da GTA", "O arquivo da guia eletrônica", "arquivo", arq("arquivo-gta"))];
  else if (sub === "demo") {
    corpo = (S.estado.roteiro?.arquivos || []).map((a) => linha(rotuloArquivoDemo(a), a.disponivel === false ? "simulado nesta execução" : null,
      { video: "video", foto: "camera", documento: "nota", nfe_xml: "arquivo", gta: "gta" }[a.tipo] || "arquivo", () => { fecharAnexar(); enviarDoCaso(a.nome, a.tipo); }));
  } else {
    corpo = [linha("Fotografar", "Cerca, obra ou animais", "camera", arq("fotografar-cerca")),
      linha("Filmar", pub ? `O lote no corredor, ${R.regraVideoPublico(S.saude?.demo_publica?.limites)} (a contagem leva até ~1 min)` : "O lote passando no corredor", "video", arq("filmar")),
      linha("Nota fiscal", pub ? "Arquivo da NF-e (.xml)" : "Foto da nota ou arquivo da NF-e", "nota", () => abrirAnexar("nota")),
      pub ? null : linha("GTA", "Foto da guia ou arquivo", "gta", () => abrirAnexar("gta")),
      S.estado.roteiro?.arquivos?.length ? linha("Arquivo da demonstração", "Usar um arquivo pronto do caso", "info", () => abrirAnexar("demo"), "demo") : null].filter(Boolean);
  }
  const titulo = { nota: "Nota fiscal", gta: "GTA", demo: "Arquivo da demonstração" }[sub] || "Anexar";
  m.replaceChildren(...[h("div", { class: "alca", "aria-hidden": "true" }),
    h("div", { class: "folha-cab" }, sub ? h("button", { class: "btn-icone", type: "button", "aria-label": "Voltar", onclick: () => abrirAnexar() }, icone("voltar")) : null,
      h("h2", { class: "t-sub" }, titulo), h("button", { class: "btn-icone", type: "button", "aria-label": "Fechar", onclick: () => fecharAnexar(true) }, icone("x"))),
    h("div", { class: "lista-anexo" }, corpo),
    sub === "demo" ? null : pub ? h("p", { class: "gps-linha" }, icone("gps"), h("span", {}, "Na demonstração pública, a localização do aparelho não é enviada."))
      : h("p", { class: "gps-linha", id: "gps-linha" }, icone("gps"), h("span", {}, "A localização vai junto com a foto."))].filter(Boolean));
  alternarFolha(m, true, { foco: m.querySelector(".linha-anexo") });
  S.el.anexar.setAttribute("aria-expanded", "true");
  estadoGps();
}
function fecharAnexar(devolver = false) {
  if (!S) return;
  const m = S.el.menuAnexar;
  if (!m.classList.contains("aberta")) return;
  alternarFolha(m, false);
  S.el.anexar.setAttribute("aria-expanded", "false");
  if (devolver) S.el.anexar.focus({ preventScroll: true });
}
function executarArquivo(acao) { capturar(ACAO_ARQ[acao]); }
async function estadoGps() {
  const el = document.getElementById("gps-linha");
  if (!el || !navigator.permissions?.query) return;
  try {
    const st = await navigator.permissions.query({ name: "geolocation" });
    const span = el.querySelector("span");
    if (st.state === "granted") span.textContent = "Localização ligada: vai junto com a foto.";
    else if (st.state === "denied") span.textContent = "Localização desligada: a foto vai sem local. Ligue nas configurações para conferir a área.";
    else span.textContent = "A localização é pedida ao enviar a foto.";
  } catch { /* sem a API de permissões */ }
}
function rotuloArquivoDemo(a) {
  const n = (String(a.nome).match(/_(\d+)\./) || [])[1];
  if (a.tipo === "video") {
    const dur = Number((String(a.rotulo || "").match(/\(([\d.,]+)\s*s\)/) || [])[1]?.replace(",", "."));
    // dois vídeos no caso: o nome do arquivo diferencia ("curral", "retiro")
    const videos = (S.estado.roteiro?.arquivos || []).filter((x) => x.tipo === "video");
    if (videos.length > 1) {
      const dica = String(a.nome).replace(/\.[^.]+$/, "").split(/[_-]+/).filter((w) => w && !/^(lote|video|vídeo|s\d+|\d+)$/i.test(w)).join(" ");
      return `Vídeo do lote · ${dica || `nº ${videos.indexOf(a) + 1}`}${dur ? ` (${Math.round(dur)} s)` : ""}`;
    }
    return `Vídeo do curral${dur ? ` (${Math.round(dur)} s)` : ""}`;
  }
  if (a.tipo === "documento") return "Nota impressa (foto)";
  if (a.tipo === "nfe_xml") return "Arquivo da NF-e";
  if (a.tipo === "gta") return "GTA";
  if (a.tipo === "foto") {
    const s = (String(a.nome).match(/^foto_([a-z]+)_/) || [])[1];
    return `Foto ${{ cerca: "da cerca", lote: "do lote", curral: "do curral" }[s] || ""}${n ? ` ${n}` : ""}`.replace(/\s+/g, " ").trim();
  }
  return String(a.rotulo || a.nome);
}

// ---------------------------------------------------------------- painel do laudo
function renderProgressoMovel() {
  const ind = R.indicador(S.estado);
  S.el.progresso.setAttribute("aria-label", R.ariaIndicador(ind));
  S.el.progresso.replaceChildren(h("span", { class: "txt" }, linhaIndicador(ind)), icone("baixo", "seta"));
}

function abrirItens(abrir) {
  if (!S || !ehMovel()) return;
  const vai = alternarFolha(S.el.itens, abrir);
  S.el.progresso.setAttribute("aria-expanded", vai ? "true" : "false");
  if (!vai && abrir === false && document.activeElement && S.el.itens.contains(document.activeElement)) S.el.progresso.focus({ preventScroll: true });
}

function renderPainel(anterior) {
  const e = S.estado;
  const ind = R.indicador(e);
  const est = R.estadoLaudo(e);
  const movel = ehMovel();
  const faltam = ind.F;
  S.el.painelCab.replaceChildren(
    h("div", { class: "rot" }, movel ? h("h2", { class: "t-sub" }, ind.antes ? "Itens do laudo" : R.textoIndicador(ind)) : h("h2", { class: "rotulo" }, "Laudo"),
      movel ? h("button", { class: "btn-icone", type: "button", "aria-label": "Fechar a lista", onclick: () => abrirItens(false) }, icone("x"))
        : chipNeutro(est.rot, est.ic, est.cls === "st-neutro" ? "st-neutro" : est.cls)),
    movel ? (ind.antes ? h("p", { class: "t-sec" }, "A lista sai com a sua primeira prova.") : h("div", {}, linhaIndicador(ind).querySelector(".prog") || "",
      R.textoMarcaDiv(ind) ? h("p", { class: `div-txt${ind.D ? "" : " div-j"}` }, icone("diverge"), R.textoMarcaDiv(ind)) : null,
      faltam ? h("p", { class: "t-sec" }, faltam === 1 ? "Falta 1 para emitir o laudo." : `Faltam ${faltam} para emitir o laudo.`) : null)) : h("div", { class: "painel-ind" }, linhaIndicador(ind, { grande: true }), trilhaEtapas(e, { fiscal: PERFIS.fiscal.nome })));
  const nos = [];
  const oc = e.ocorrencias || [];
  if (oc.length) {
    const mudou = anterior && (anterior.ocorrencias || []).length !== oc.length && document.body.classList.contains("apresentacao");
    const b = h("button", { class: `recusas${mudou ? " realce" : ""}`, type: "button", onclick: listaRecusas },
      h("span", { class: "si si-guarda" }, icone("escudo-cheio")), h("span", { class: "rec-txt" }, R.textoRecusas(oc.length)), icone("direita"));
    if (mudou) S.timers.push(setTimeout(() => b.classList.remove("realce"), 3000));
    nos.push(b);
  }
  if (ind.antes) {
    // antes do plano: o que o laudo já sabe que vai pedir (a lista completa, com a conta, sai com a primeira mensagem)
    const aFazer = R.unidades(e).filter((u) => !u.agente);
    if (aFazer.length) {
      nos.push(h("h3", { class: "rotulo-secao" }, "O laudo vai pedir"),
        h("ol", { class: "a-fazer" }, aFazer.map((u) => h("li", {}, h("span", { class: "q", "aria-hidden": "true" }), h("span", { class: "txt" }, R.rotuloUnidade(e, u).titulo)))),
        h("p", { class: "t-sec painel-vazio" }, "O agente fecha a lista e a conta com a primeira mensagem. Comece pelo cartão Agora."));
    } else nos.push(h("p", { class: "t-sec painel-vazio" }, "O agente monta a lista do laudo com a primeira mensagem. Comece pelo cartão Agora."));
  }
  const grupos = R.faltasAgrupadas(e);
  if (grupos.length && !ind.antes) {
    const pisca = R.ultimoTurnoBloqueado(e) && S.eventosVivos[e.conversa?.at(-1)?.turno];
    nos.push(h("h3", { class: `rotulo-secao${pisca ? " pisca" : ""}` }, movel ? `Falta (${grupos.length})` : `Falta para emitir (${grupos.length})`));
    grupos.forEach((g, i) => nos.push(linhaFalta(g, i === 0)));
  }
  const us = R.unidades(e).filter((u) => u.pronta);
  const daFiscal = us.filter((u) => !u.agente);
  const doAgente = us.filter((u) => u.agente);
  if (daFiscal.length && !ind.antes) {
    nos.push(h("h3", { class: "rotulo-secao" }, `Prontos (${daFiscal.length})`));
    nos.push(...gruposProntos(daFiscal));
  }
  if (doAgente.length && !ind.antes) {
    nos.push(h("h3", { class: "rotulo-secao" }, `O agente verificou (${doAgente.length})`),
      h("p", { class: "t-sec nota-agente" }, "Com os dados da operação, sem prova sua."),
      h("div", { class: "sub-itens agente" }, doAgente.map((u) => linhaPronta(u))));
  }
  const topo = S.el.painelCorpo.scrollTop;
  S.el.painelCorpo.replaceChildren(...nos);
  S.el.painelCorpo.scrollTop = topo;
  renderRodapePainel(ind);
}

// Pé do painel: o botão de emitir fica sempre à vista, desligado com o motivo até não faltar nada (o principal,
// verde, continua no cartão Agora). Depois do rascunho, "Revisar e assinar"; depois do selo, "Ver laudo".
function renderRodapePainel(ind) {
  const e = S.estado;
  const n = ind.F;
  let corpo;
  // depois do rascunho, no computador, o cartão Agora (ao lado) já leva a "Revisar e assinar" / "Ver laudo"
  if (!ehMovel() && (e.etapa === "SELADO" || (["RASCUNHO", "ASSINATURA"].includes(e.etapa) && e.laudo && e.laudo.valido_para_assinar !== false))) {
    S.el.painelPe.replaceChildren();
    return;
  }
  if (e.etapa === "SELADO") {
    corpo = [h("a", { class: "btn btn-sec btn-cheio", href: `#/fis/${encodeURIComponent(S.id)}/laudo` }, icone("nota"), "Ver laudo selado")];
  } else if (["RASCUNHO", "ASSINATURA"].includes(e.etapa) && e.laudo && e.laudo.valido_para_assinar !== false) {
    corpo = ehFiscal() ? [h("button", { class: "btn btn-sec btn-cheio", type: "button", onclick: () => executarAcao("revisar-assinar") }, icone("caneta"), "Revisar e assinar")]
      : [h("p", { class: "t-sec" }, "Rascunho emitido: aguardando a assinatura da fiscal.")];
  } else if (ind.antes) {
    corpo = [h("button", { class: "btn btn-sec btn-cheio", type: "button", disabled: true, "aria-describedby": "motivo-emitir" }, icone("nota"), "Emitir laudo"),
      h("p", { class: "t-sec motivo", id: "motivo-emitir" }, "Sai quando todos os itens estiverem prontos.")];
  } else {
    const pode = n === 0 && ehFiscal() && !S.ocupado;
    corpo = [h("button", { class: "btn btn-sec btn-cheio", type: "button", disabled: pode ? null : true, "aria-describedby": "motivo-emitir",
      dataset: { acao: "emitir" }, onclick: () => executarAcao("emitir") }, icone("nota"), "Emitir laudo"),
    h("p", { class: "t-sec motivo", id: "motivo-emitir" }, n ? (n === 1 ? "Falta 1 item para emitir." : `Faltam ${n} itens para emitir.`)
      : ehFiscal() ? "Tudo pronto: o agente confere de novo antes de emitir." : "Só a fiscal emite o laudo.")];
  }
  S.el.painelPe.replaceChildren(...corpo);
}

function temProva(l) { return (l.checagens || []).length > 0 || (l.evidencias || []).length > 0; }
function unidadeTemProva(u) { return u.linhas.some(temProva); }

function linhaFalta(g, primeira) {
  const e = S.estado;
  const u = g.unidade;
  const pl = R.planoFalta(e, g.alvo);
  const cls = g.tipo === "div" ? "si-div" : g.tipo === "sem" ? "si-sem" : "si-falta";
  const acoes = ehFiscal() ? pl.acoes.slice(0, 2).map((ac, i) => h("button", { class: `btn ${primeira && i === 0 ? "btn-pri" : "btn-sec"}`, type: "button",
    dataset: { acao: ac.acao }, onclick: () => executarAcao(ac.acao) }, i === 0 && ac.ic ? icone(ac.ic) : null, ac.rot)) : [];
  const linha = h("div", { class: `item falta-item ${g.tipo}${primeira && g.tipo !== "div" ? " vez" : ""}`, dataset: { campo: g.principal.campo, campos: g.campos.join(" ") } },
    h("div", { class: "l1" }, h("span", { class: `si ${cls}` }, icone(g.ic)),
      h("div", { class: "txt" }, h("strong", { class: "item-titulo" }, g.titulo), h("span", { class: "item-estado t-sec" }, g.apoio)),
      unidadeTemProva(u) ? botaoProva(g.principal.campo) : null),
    acoes.length ? h("div", { class: "item-acoes" }, acoes) : null);
  return unidadeTemProva(u) ? linhaAbreProva(linha, g.principal.campo) : linha;
}

// "Ver prova" da lista: a seta no fim da linha (o nome continua para o leitor de tela); a linha inteira também abre
function botaoProva(campo) {
  return h("button", { class: "ver-prova", type: "button", "aria-label": "Ver prova", title: "Ver prova", onclick: (ev) => { ev.stopPropagation(); abrirProva(campo); } },
    h("span", { class: "vp-txt" }, "Ver prova"), icone("direita"));
}
function linhaAbreProva(el, campo) {
  el.classList.add("com-prova");
  el.addEventListener("click", (ev) => { if (!ev.target.closest("button, a, input")) abrirProva(campo); });
  return el;
}

// Linha de um item pronto: ✓ verde (verificado) ou △ vermelho (divergência justificada: pronto, mas a marca fica).
function linhaPronta(u) {
  const r = R.rotuloUnidade(S.estado, u);
  const div = r.tipo === "divj";
  const prova = unidadeTemProva(u);
  const linha = h("div", { class: `item pronto${div ? " divj" : ""}`, dataset: { campo: u.principal.campo }, title: div ? null : r.prontoApoio },
    h("span", { class: `si ${div ? "si-div" : "si-ok"}` }, icone(div ? "diverge" : "check-cheio")),
    h("span", { class: "txt" }, h("span", { class: "item-titulo" }, r.pronto), div ? h("span", { class: "item-estado" }, r.prontoApoio) : null),
    prova ? botaoProva(u.principal.campo) : null);
  return prova ? linhaAbreProva(linha, u.principal.campo) : linha;
}

// Prontos por objeto financiado (sem sanfona: são poucos itens; o nome do objeto é só um rótulo)
function gruposProntos(prontos) {
  const e = S.estado;
  const itens = e.operacao.itens || [];
  const grupos = itens.map((it) => ({ chave: it.id, nome: R.nomeItem(it), ic: R.ehBovino(it) ? "vaca" : "cerca", us: prontos.filter((u) => u.item_id === it.id) }))
    .concat([{ chave: "laudo", nome: "Requisitos da fiscalização", ic: "lista", us: prontos.filter((u) => !itens.some((i) => i.id === u.item_id)) }])
    .filter((g) => g.us.length);
  return grupos.flatMap((g) => [h("p", { class: "obj-rot" }, h("span", {}, g.nome)), h("div", { class: "sub-itens" }, g.us.map((u) => linhaPronta(u)))]);
}

function listaRecusas() {
  const e = S.estado;
  const turnos = Object.entries(S.guardas).filter(([, v]) => v.some((x) => x.tipo === "pressao" || x.tipo === "injecao"));
  abrirModal(R.maiuscula(R.textoRecusas((e.ocorrencias || []).length)), h("div", { class: "texto" },
    h("ul", { class: "lista-recusas" }, (e.ocorrencias || []).map((o) => {
      const t = turnos.find(([, v]) => v.some((x) => x.tipo === o.tipo))?.[0];
      return h("li", {}, h("span", { class: "si si-guarda" }, icone("escudo-cheio")), h("span", { class: "txt" }, R.textoOcorrencia(e, o)),
        t ? h("button", { class: "btn btn-ter", type: "button", onclick: () => verNaConversa(t) }, "Ver na conversa") : null);
    })),
    h("p", { class: "t-sec" }, "Cada pedido recusado fica registrado no laudo, com a hora e a regra.")));
}

function verNaConversa(turno) {
  fecharModal();
  abrirItens(false);
  const alvo = S.el.chat.querySelector(`.msg.agente[data-turno="${CSS.escape(String(turno))}"]`);
  if (!alvo) return;
  alvo.scrollIntoView({ block: "center", behavior: "smooth" });
  alvo.classList.add("lembrar");
  S.timers.push(setTimeout(() => alvo.classList.remove("lembrar"), 2000));
}

// ---------------------------------------------------------------- prova do item (gaveta)
function abrirProva(campo) {
  if (!S) return;
  S.provaCampo = campo;
  abrirItens(false);
  S.el.grade.classList.add("prova-aberta");
  S.el.colProva.setAttribute("aria-hidden", "false");
  if (ehMovel()) alternarFolha(S.el.colProva, true);
  else document.getElementById("veu-global").hidden = false;
  renderProva();
  S.el.colProva.querySelector(".fechar-prova")?.focus({ preventScroll: true });
}
function fecharProva() {
  if (!S || !S.el.grade.classList.contains("prova-aberta")) return;
  S.el.grade.classList.remove("prova-aberta");
  S.el.colProva.setAttribute("aria-hidden", "true");
  alternarFolha(S.el.colProva, false);
  if (!ehMovel() && document.getElementById("tecnico")?.hidden !== false) document.getElementById("veu-global").hidden = true;
  S.miniMapa?.remove?.(); S.miniMapa = null;
  const volta = S.el.painelCorpo.querySelector(`[data-campo="${CSS.escape(S.provaCampo || "")}"] .ver-prova`);
  S.provaCampo = null;
  volta?.focus({ preventScroll: true });
}

// A prova do item como a fiscal o vê (a foto da cerca junta integridade, localização e conclusão). Um status só, no
// topo; cada bloco mostra o que a checagem viu, sem repetir status. Fonte, regra, tolerância e sha256 ficam no fim, em
// "Regra e detalhes".
function renderProva() {
  S.miniMapa?.remove?.(); S.miniMapa = null;
  const e = S.estado;
  const l0 = (e.matriz || []).find((x) => x.campo === S.provaCampo);
  if (!l0) { S.el.prova.replaceChildren(h("p", {}, "Item não encontrado.")); return; }
  const u = R.unidadeDoCampo(e, l0.campo) || { linhas: [l0], principal: l0, alvo: l0, pronta: R.pronta(l0), justificada: R.justificada(l0) };
  const ls = u.linhas;
  const r = u.campos ? R.rotuloUnidade(e, u) : R.rotuloItem(e, l0);
  const it = (e.operacao.itens || []).find((i) => i.id === l0.item_id);
  S.el.tituloProva.textContent = u.pronta ? r.pronto : r.titulo;
  S.el.subProva.textContent = it ? R.nomeItem(it) : u.agente ? "O agente verificou" : "Requisitos da fiscalização";
  const status = u.pronta ? (u.justificada ? "divergente-j" : "verificado") : u.divAberta ? "divergente" : u.alvo?.status || l0.status;
  const apoio = u.pronta ? (u.justificada ? "Divergência justificada." : r.prontoApoio || r.apoio) : r.apoio;
  const nos = [h("div", { class: "prova-st" }, chipStatus(status), h("span", { class: "t-sec" }, apoio))];
  for (const l of ls) if (l.justificativa) nos.push(justificativa(l.justificativa));
  const vistos = new Set();
  const chks = ls.flatMap((l) => R.checagensDaLinha(e, l)).filter((c) => !vistos.has(c.id) && vistos.add(c.id)).slice().reverse();
  if (!chks.length) {
    const pl = R.planoFalta(e, u.alvo || l0);
    nos.push(h("div", { class: "vazio" }, h("p", {}, u.pronta ? (u.agente ? "O agente verificou com os dados da operação." : "Este item foi registrado na conversa.")
      : "Ainda não há prova para este item."),
    !u.pronta && ehFiscal() ? h("button", { class: "btn btn-sec", type: "button", onclick: () => { fecharProva(); executarAcao(pl.acoes[0].acao); } },
      pl.acoes[0].ic ? icone(pl.acoes[0].ic) : null, pl.acoes[0].rot) : null));
  }
  const varias = chks.length > 1;
  const nGeo = chks.filter((c) => c.ferramenta === "geofence").length;
  let kGeo = nGeo;
  chks.forEach((c) => nos.push(blocoProva(c, { varias, ordem: c.ferramenta === "geofence" && nGeo > 1 ? kGeo-- : 0 })));
  // regra e detalhes (auditoria): por linha do laudo
  const det = [];
  for (const l of ls) {
    const v = l.valor && typeof l.valor === "object" ? l.valor : null;
    det.push(kv([ls.length > 1 ? ["Linha do laudo", R.rotuloItem(e, l).pronto] : null, ["Regra", l.regra_id || "—", "mono"], l.regra_id ? ["Em resumo", regraCurta(l.regra_id)] : null,
      v?.limite_inferior !== undefined ? ["Mínimo aceito", `${fmtNum(v.limite_inferior)} (tolerância de ${fmtNum(v.tolerancia_pct)}%)`] : null,
      ["Motivo do verificador", legivel(l.motivo || "—")], l.proveniencia?.length ? ["Origem", l.proveniencia.join("; ")] : null]));
  }
  for (const c of chks) {
    det.push(kv([["Checagem", `${rotuloFerramenta(c.ferramenta)} · ${ROTULO_STATUS_CHK[c.status] || c.status}`], ["Fonte", c.fonte_versao || "—", "mono"],
      ...(c.prova?.motivos || []).slice(0, 4).map((m, i) => [i ? "" : "Notas", legivel(m)])]));
  }
  const evs = [...new Set(ls.flatMap((l) => l.evidencias || []))];
  if (evs.length) det.push(kv(evs.map((id) => { const ev = (e.evidencias || []).find((x) => x.id === id); return ev ? [`sha256 · ${ev.nome}`, ev.sha256 || "—", "mono"] : null; })));
  nos.push(h("details", { class: "regra-det" }, h("summary", {}, "Regra e detalhes"), det));
  S.el.prova.replaceChildren(...nos);
  S.el.prova.scrollTop = 0;
}

const ROTULO_STATUS_CHK = { ok: "verificado", divergente: "divergente", indeterminado: "sem conclusão", erro: "erro", pendente: "falta" };

function blocoProva(c, { varias = false, ordem = 0 } = {}) {
  const p = c.prova || {};
  // um status só por tela (o do topo): o bloco diz o que a checagem viu. Com várias checagens no mesmo item (a foto da
  // cerca), cada bloco mostra o seu resultado em palavras, sem pílula de status.
  let resultado = null;
  if (c.ferramenta === "geofence") resultado = c.status === "ok" ? "dentro da área" : "fora da área";
  else if (varias) resultado = c.status === "ok" ? "verificado" : ROTULO_STATUS_CHK[c.status] || c.status;
  const titulo = `${rotuloFerramenta(c.ferramenta)}${ordem ? ` · ${ordem}ª foto` : ""}`;
  const corpo = [h("div", { class: "bloco-cab" }, h("strong", {}, titulo), resultado ? h("span", { class: `resultado${c.status === "ok" ? " ok" : ""}` }, resultado) : null)];
  if (p.tipo === "contagem") {
    corpo.push(h("p", { class: "contagem-grande" }, h("span", { class: "num-g" }, fmtNum(p.contagem)),
      h("span", {}, Array.isArray(p.intervalo) ? ` contados · de ${p.intervalo[0]} a ${p.intervalo[1]} com a incerteza` : Number(p.contagem) === 1 ? " animal" : " animais")));
    if (p.quadros?.length) {
      const contados = (n) => `${R.fmtInt(n)} ${Number(n) === 1 ? "contado" : "contados"}`;
      const quando = (q) => `${mmss(q.t_s)}`;
      const melhor = p.quadros.reduce((a, q) => (!a || q.contagem_ate_aqui > a.contagem_ate_aqui ? q : a), null);
      const quadro = (q, grande) => h("figure", { class: grande ? "q-grande" : "q-peq" },
        h("span", { class: "q-img" }, h("img", { src: q.url, alt: `Quadro do vídeo em ${quando(q)}, com as caixas do detector em cada animal; ${contados(q.contagem_ate_aqui)} até aqui`, loading: "lazy" })),
        h("figcaption", {}, h("b", {}, contados(q.contagem_ate_aqui)), ` até ${quando(q)}`));
      corpo.push(quadro(melhor, true));
      const resto = p.quadros.filter((q) => q !== melhor);
      if (resto.length) corpo.push(h("div", { class: "quadros", style: { "--n": String(resto.length) } }, resto.map((q) => quadro(q, false))));
    }
    if (p.video_url) corpo.push(h("a", { class: "btn btn-ter", href: p.video_url, target: "_blank", rel: "noopener" }, icone("video"), "Ver o vídeo"));
  } else if (p.tipo === "foto_mapa") {
    if (p.foto_url) corpo.push(h("img", { class: "foto", src: p.foto_url, alt: "Foto enviada como prova", loading: "lazy" }));
    corpo.push(kv([p.gps ? ["Local", `${p.gps.lat.toFixed(6)}, ${p.gps.lon.toFixed(6)} (±${String(p.gps.precisao_m ?? "?").replace(".", ",")} m)`] : ["Local", "sem GPS"],
      p.distancia_borda_m !== undefined && p.distancia_borda_m !== null && c.ferramenta === "geofence"
        ? ["Distância da borda", c.status === "ok" ? "dentro da área" : `${String(p.distancia_borda_m).replace(".", ",")} m`] : null]));
    if (c.ferramenta === "geofence" && (p.glebas?.length || p.gps)) {
      const mm = h("div", { class: "mini-mapa", role: "img", "aria-label": "Área financiada e o ponto da foto" });
      corpo.push(mm);
      setTimeout(() => { if (!S || !mm.isConnected) return; S.miniMapa?.remove?.(); S.miniMapa = miniMapa(mm, p.glebas || [], p.gps, c.status === "ok" ? null : p.distancia_borda_m); }, 30);
    }
  } else if (p.tipo === "documento") {
    if (p.criterios?.length) {
      corpo.push(h("ul", { class: "criterios" }, p.criterios.map((k) => h("li", {}, chipStatus(k.status === "ok" ? "verificado" : k.status),
        h("span", {}, legivel(k.motivo))))));
    }
    if (p.trecho_url) {
      const alvo = h("div");
      corpo.push(h("button", { class: "btn btn-sec", type: "button", onclick: async (ev) => {
        ev.currentTarget.disabled = true;
        try { alvo.replaceChildren(trechoDoc(await api.trecho(p.trecho_url))); } catch (er) { alvo.textContent = er.message; }
      } }, icone("nota"), "Ver trecho do documento"), alvo);
    }
  } else if (p.dados) {
    corpo.push(kv(Object.entries(p.dados).filter(([, v]) => typeof v !== "object").slice(0, 8).map(([k, v]) => [k.replaceAll("_", " "), fmtNum(v)])));
  } else if (p.tipo === "plano") corpo.push(h("p", {}, p.justificativa || ""));
  return h("div", { class: "bloco-prova" }, corpo);
}

function trechoDoc(t) {
  const nos = [kv((t.campos || []).map((c) => [c.rotulo, c.valor]))];
  if (t.produtos?.length) nos.push(h("ul", { class: "t-sec" }, t.produtos.map((p) => h("li", {}, `${p.descricao || "—"} · ${p.quantidade || ""} ${p.unidade || ""} · ${p.valor || ""}`))));
  return h("div", { class: "trecho" }, nos);
}

// ---------------------------------------------------------------- detalhes técnicos
function secaoFis() {
  const e = S.estado;
  const idx = (e.etapas || []).findIndex((x) => x.id === e.etapa);
  const g = [...(e.governanca || [])].reverse();
  return h("div", {},
    blocoTec(`Decisões da política (${g.length})`, g.length ? h("ol", { class: "tec-lista" }, g.map((d) => h("li", {},
      h("strong", { class: "mono" }, d.rule_id), ` · ${rotuloFerramenta(d.acao)} · ${d.resultado}: ${d.motivo || ""}`))) : h("p", { class: "t-sec" }, "Nenhuma decisão ainda.")),
    blocoTec("Conversa (texto original do agente)", h("p", { class: "t-sec" }, "Na conversa, a fala aparece em linguagem de campo; aqui fica o texto como a API devolveu."),
      h("ol", { class: "tec-lista" }, (e.conversa || []).filter((c) => c.agente).slice().reverse().map((c) => h("li", {},
        h("strong", {}, `Turno ${c.turno}`), ` · ${c.agente}`, (c.acoes || []).length ? h("div", { class: "t-sec mono" }, (c.acoes || []).map((a) => (typeof a === "string" ? a : a.acao)).join(" · ")) : null)))),
    blocoTec("Checagens e ferramentas", h("ol", { class: "tec-lista" }, (e.checagens || []).slice().reverse().map((c) => h("li", {},
      h("strong", {}, rotuloFerramenta(c.ferramenta)), ` (${c.ferramenta}) · ${c.status} · ${c.fonte_versao || ""}`,
      h("div", { class: "t-sec mono" }, `${c.id}${c.span_id ? ` · span ${c.span_id}` : ""}`))))),
    blocoTec("Etapas", h("ol", { class: "tec-etapas" }, (e.etapas || []).map((x, i) => h("li", { class: `${i < idx ? "feita" : ""}${i === idx ? " atual" : ""}`,
      "aria-current": i === idx ? "step" : null }, x.id))),
    kv([["Etapa", e.etapa, "mono"], ["Método", e.metodo ? `${e.metodo_rotulo || ""} (${e.metodo})` : "—"], ["Regras", e.rulebook || "—", "mono"],
      ["Fiscalização", e.id, "mono"], S.ultimoLat ? ["Último turno", S.ultimoLat] : null])),
    blocoTec("Evidências", h("ol", { class: "tec-lista" }, (e.evidencias || []).map((x) => h("li", {}, `${x.nome} · ${x.tipo} · ${fmtData(x.recebida_em)}`,
      h("div", { class: "t-sec mono" }, `sha256 ${x.sha256 || "—"}`))))),
    blocoTec("Trace", h("p", { class: "t-sec" }, `${e.n_spans ?? "?"} registros nesta fiscalização.`),
      h("div", { class: "acoes-linha" }, h("a", { class: "btn btn-sec", href: e.trace_url || `/api/fiscalizacoes/${encodeURIComponent(e.id)}/trace`, target: "_blank", rel: "noopener" }, icone("codigo"), "Trace completo"),
        h("a", { class: "btn btn-sec", href: `/api/fiscalizacoes/${encodeURIComponent(e.id)}`, target: "_blank", rel: "noopener" }, icone("codigo"), "Estado (JSON)"))),
    blocoAmostra(e.amostra, e.triagem?.motivos || []));
}

// ---------------------------------------------------------------- controle da demonstração (roteiro)
function renderRoteiro() {
  const r = S.estado.roteiro;
  const bar = S.el.roteiro;
  const ativo = !!r && ehFiscal();
  bar.hidden = !ativo;
  S.el.grade.classList.toggle("com-roteiro", ativo);
  // no celular a marca da demonstração passa para a barra (uma marca só; a faixa do topo some enquanto a barra existe)
  document.body.classList.toggle("com-roteiro", ativo);
  window.dispatchEvent(new Event("lv:topo"));
  if (!ativo) return;
  const p = r.passos[r.proximo - 1];
  const movel = ehMovel();
  // no telão a barra fica recolhida; quando a demonstração abre no meio, ela fica aberta para o operador escolher
  const recolhida = document.body.classList.contains("apresentacao") && !movel && !S.retomar;
  bar.classList.toggle("recolhida", recolhida);
  bar.classList.toggle("retomar", !!S.retomar);
  const foco = usaTeclado && bar.contains(document.activeElement) ? document.activeElement.dataset.k : null;
  const fala = p ? (p.fala ? `“${p.fala}”` : p.evidencia ? rotuloEnvio(p, r) : p.acao === "residual" ? "a fiscal lê no papel só o que o agente pediu"
    : p.acao === "assinar" ? "a fiscal revisa e assina com o PIN" : "") : "Use “Recomeçar” no ⋯ para rodar de novo.";
  const rotExec = p?.acao === "assinar" ? "Ir para assinatura" : S.retomar ? `Continuar do passo ${r.proximo}` : movel ? "Executar" : "Executar passo";
  const exec = p ? h("button", { class: "btn btn-pri", type: "button", onclick: proximoPasso, disabled: S.ocupado ? true : null, dataset: { k: "executar" },
    title: "Executar o passo (→)" }, icone("play"), h("span", { class: "rot-exec" }, rotExec)) : null;
  const pular = p && p.acao !== "assinar" && !movel && !S.retomar ? h("button", { class: "btn btn-esc ok-alvo", type: "button", onclick: pularPasso, disabled: S.ocupado ? true : null,
    dataset: { k: "pular" }, "aria-label": "Pular este passo", title: "Pular este passo (avança sem executar)" }, icone("pular")) : null;
  const recomecar = S.retomar ? h("button", { class: "btn btn-esc com-texto", type: "button", dataset: { k: "recomecar" }, disabled: S.ocupado ? true : null,
    onclick: () => { S.confirmarReinicio = true; reiniciarDemo(null); } }, icone("recomecar"), h("span", {}, "Recomeçar do passo 1")) : null;
  const mais = h("button", { class: "btn btn-esc ok-alvo", type: "button", dataset: { k: "mais" }, "aria-label": "Mais opções da demonstração", "aria-haspopup": "menu",
    title: "Mais opções", onclick: (ev) => menuRoteiro(ev.currentTarget) }, icone("opcoes"));
  // o menu é um nó só (no celular ele vai para o <body> enquanto está aberto, como folha acima do véu)
  S.el.menuRoteiro ||= h("div", { class: "menu roteiro-menu", id: "menu-roteiro", role: "menu", hidden: true });
  const titulo = S.retomar ? `A demonstração parou no passo ${r.proximo}` : p ? tituloPasso(p.titulo) : "Demonstração concluída";
  const apoio = S.retomar ? `Continue de onde parou ou recomece do início. Próximo: ${tituloPasso(p?.titulo || "")}.` : fala;
  bar.replaceChildren(
    ehDemo() ? h("p", { class: "roteiro-marca marca-demo so-movel" }, "Demonstração · dados sintéticos") : null,
    h("div", { class: "roteiro-barra ok-pequeno" },
      h("span", { class: "pos" }, `${Math.min(r.proximo, r.total)} / ${r.total}`),
      h("span", { class: "titulo", title: p?.fala || null }, h("span", { class: "titulo-txt" }, titulo), apoio ? h("span", { class: "fala-passo" }, apoio) : null),
      exec, recomecar, pular, mais,
      S.el.menuRoteiro.parentElement === document.body ? null : S.el.menuRoteiro));
  if (foco) bar.querySelector(`[data-k="${foco}"]`)?.focus({ preventScroll: true });
}

function menuRoteiro(botao) {
  const r = S.estado.roteiro;
  const menu = S.el.menuRoteiro;
  const p = r?.passos?.[r.proximo - 1];
  const itemRecomecar = { rot: S.confirmarReinicio ? "Recomeçar a demo? Toque de novo" : "Recomeçar a demonstração", ic: "recomecar", perigo: S.confirmarReinicio, manter: !S.confirmarReinicio,
    acao: () => reiniciarDemo(botao) };
  const proximos = (r?.passos || []).filter((x) => x.n > r.proximo && x.acao !== "assinar" && (x.n < (r.passos.find((y) => y.acao === "assinar")?.n || 99)));
  abrirMenu(menu, botao, [
    p && p.acao !== "assinar" ? { rot: "Pular este passo", sub: "Avança sem executar", ic: "pular", acao: () => pularPasso() } : null,
    itemRecomecar,
    proximos.length ? { rot: "Avançar até o passo…", ic: "pular", manter: true, acao: () => abrirMenu(menu, botao, proximos.map((x) => ({ rot: `${x.n} · ${tituloPasso(x.titulo)}`, acao: () => avancarAte(x.n) })),
      { titulo: ehMovel() ? "Avançar até o passo" : null }) } : null,
  ], { titulo: ehMovel() ? "Controle da demonstração" : null });
}

function rotuloEnvio(p, r) {
  const a = (r.arquivos || []).find((x) => x.nome === p.evidencia);
  const base = ENVIO_TIPO[a?.tipo] || "a fiscal envia o arquivo do caso";
  return a?.tipo === "gta" && /instru/i.test(p.titulo) ? `${base}; o documento traz uma instrução escondida` : base;
}

async function proximoPasso() {
  if (!S || S.ocupado) return;
  const r = S.estado.roteiro;
  const p = r?.passos[r.proximo - 1];
  if (!p) return;
  marcarVista();
  fecharMenus();
  if (p.acao === "assinar") { S.irLaudo(S.id, true); return; }
  const arq = p.evidencia ? (r.arquivos || []).find((a) => a.nome === p.evidencia) : null;
  // o texto do roteiro que estava no compositor (o "Justificar" na gravação) vai pelo passo: sai do campo
  if (p.fala && norm(S.el.texto.value) === norm(p.fala)) { S.el.texto.value = ""; ajustarAltura(S.el.texto); }
  await executar(() => api.proximoPasso(S.id), {
    fala: p.fala || (p.acao === "residual" ? `${p.fala_prefixo || ""}…` : ""), evidencia: arq?.tipo || null, nome: p.evidencia || null,
    texto: arq ? STATUS_ENVIO[arq.tipo] : p.acao === "residual" ? "Conferindo os campos lidos…" : "Conferindo…" });
}

async function avancarAte(n) {
  while (S && S.estado.roteiro && S.estado.roteiro.proximo < n) {
    const antes = S.estado.roteiro.proximo;
    await proximoPasso();
    if (!S || S.falhou || S.estado.roteiro?.proximo === antes) break;
  }
}

async function pularPasso() {
  if (!S || S.ocupado) return;
  marcarVista();
  try {
    const r = await api.pularPasso(S.id);
    atualizar(r.estado);
    avisar(r.aviso || "Passo pulado.");
  } catch (e) { avisar(e.message, true); }
}

async function reiniciarDemo(botao) {
  const r = S.estado.roteiro;
  if (!r) return;
  if (!S.confirmarReinicio) {
    S.confirmarReinicio = true;
    menuRoteiro(botao);
    clearTimeout(S.tReinicio);
    S.tReinicio = setTimeout(() => { if (S?.confirmarReinicio) { S.confirmarReinicio = false; fecharMenus(); } }, 3000);
    return;
  }
  S.confirmarReinicio = false;
  clearTimeout(S.tReinicio);
  fecharMenus();
  marcarVista();
  try {
    const e = await api.abrirCaso(r.caso_id, true);
    S.eco = {}; guardarEco();
    Object.assign(S, { confirmacao: null, falhou: null, expandido: {}, resposta: {}, eventosVivos: {}, gruposAbertos: null, ultimoPronto: null, realce: null });
    fecharProva();
    atualizar(e);
    avisar("Demonstração recomeçada.");
  } catch (e) { avisar(e.message, true); }
  atualizarSaude();
}

// ---------------------------------------------------------------- ações
function ocupar(opcoes) {
  S.ocupado = !!opcoes;
  S.ocupadoTexto = opcoes?.texto || "";
  S.pendente = opcoes && (opcoes.fala || opcoes.evidencia) ? { texto: opcoes.fala, evidencia: opcoes.evidencia, nome: opcoes.nome } : null;
  if (!opcoes) S.progresso = null;
  renderChat();
  renderRoteiro();
  renderCompositor();
}

async function executar(fn, opcoes = {}, extra = {}) {
  if (!S) return null;
  S.falhou = null;
  ocupar({ texto: opcoes.texto || "Conferindo…", fala: opcoes.fala, evidencia: opcoes.evidencia, nome: opcoes.nome });
  const t0 = performance.now();
  let r;
  try { r = await fn(); } catch (e) {
    if (!S) return null;
    S.falhou = { texto: opcoes.fala, erro: e.message, rede: !!e.rede, amigavel: !!e.amigavel, status: e.status || null, restaurar: opcoes.restaurar || null,
      repetir: () => executar(fn, opcoes, extra) };
    if (opcoes.restaurar && !S.el.texto.value.trim()) { S.el.texto.value = opcoes.restaurar; ajustarAltura(S.el.texto); }
    ocupar(null);
    atualizarSaude();
    return null;
  }
  if (!S) return r;
  S.ocupado = false; S.pendente = null; S.progresso = null;
  atualizarSaude();
  tratarResposta(r, Math.round(performance.now() - t0), extra);
  return r;
}

function tratarResposta(r, latTotal, extra = {}) {
  if (r.confirmacao) {
    S.confirmacao = r.confirmacao;
    if (r.estado) S.estado = r.estado;
    renderTudo();
    tts.falar(r.fala_voz || r.confirmacao.pergunta);
    anunciar(r.confirmacao.pergunta);
    return;
  }
  if (r.aviso && !r.resposta) {
    avisar(r.aviso);
    tts.falar(r.fala_voz || r.aviso);
    if (r.estado) atualizar(r.estado); else renderTudo();
    return;
  }
  S.confirmacao = null;
  if (r.aviso) avisar(r.aviso, false, Math.max(3000, 60 * r.aviso.length));
  const resp = r.resposta;
  S.ultimoLat = `turno ${((r.latencia_ms || 0) / 1000).toFixed(1)} s · total ${(latTotal / 1000).toFixed(1)} s${extra.origem ? ` · ${extra.origem}` : ""}`;
  const g = R.guardaDoTurno(r.eventos || []);
  const ultimo = r.estado?.conversa?.at(-1);
  const ult = ultimo?.turno;
  S.realce = g ? ult : null;
  if (extra.eco && ultimo && !String(ultimo.fiscal || "").trim()) { S.eco[ult] = extra.eco; guardarEco(); }
  atualizar(r.estado, r.eventos || [], resp);
  if (g) anunciar(R.GUARDAS[g.tipo]?.anuncio || "O agente recusou o pedido e registrou.");
  else if (resp?.fala) anunciar(falaDoAgente(resp.fala), (r.eventos || []).some((x) => ["bloqueio", "abstencao"].includes(x.nivel)));
  if (resp?.fala) tts.falar(r.fala_voz || resp.fala);
  if (r.acao_humana === "assinar" || r.passo?.acao === "assinar") S.irLaudo(S.id, true);
}

function enviarFala(t) { return executar(() => api.turno(S.id, t), { fala: t }, { origem: "texto" }); }

async function enviarTexto() {
  const t = S.el.texto.value.trim();
  if (!t || S.ocupado) return;
  if (emReplay()) {
    // na gravação, só a fala do próximo passo (a mesma frase): ela vai pelo roteiro; o resto fica no campo, com o aviso
    const p = passoAtual();
    if (p && p.acao === "turno" && !p.evidencia && p.fala && norm(t) === norm(p.fala)) { proximoPasso(); return; }
    avisoRoteiro();
    return;
  }
  marcarVista();
  S.el.texto.value = "";
  ajustarAltura(S.el.texto);
  renderCompositor();
  await executar(() => api.turno(S.id, t), { fala: t, restaurar: t }, { origem: "texto" });
  S?.el.texto.focus({ preventScroll: true });
}

async function confirmar(aceitar, texto) {
  S.confirmacao = null;
  await executar(() => api.confirmar(S.id, aceitar, texto), aceitar ? { fala: texto } : { texto: "Descartando…" }, { origem: "voz" });
}

// "Enviar leitura": confere cada campo antes (todos pedidos; dígitos no tamanho certo; as duas digitações iguais) e mostra
// na conversa o que a fiscal leu ("Chave: …9439 · CNPJ/CPF do emitente: 12.345…").
function validarResidual() {
  const campos = S.estado.residual?.campos || [];
  let primeiro = null; const eco = [];
  for (const inp of S.el.residual || []) {
    const nome = inp.dataset.campo;
    const base = nome.replace(/#2$/, "");
    const c = campos.find((x) => (x.campos || []).includes(base)) || {};
    const v = inp.value.trim();
    const digitos = v.replace(/\D/g, "");
    let erro = "";
    if (!v) erro = "Preencha este campo.";
    else if (c.formato === "digitos" && c.n_digitos && digitos.length !== c.n_digitos) erro = `São ${c.n_digitos} dígitos; você digitou ${digitos.length}.`;
    else if (c.formato === "documento" && ![11, 14].includes(digitos.length)) erro = "O CNPJ tem 14 dígitos e o CPF, 11.";
    else if (nome.endsWith("#2")) {
      const outro = (S.el.residual || []).find((x) => x.dataset.campo === base);
      if (outro && outro.value.replace(/\s/g, "") !== v.replace(/\s/g, "")) erro = "As duas digitações não batem.";
    }
    const msg = inp.parentElement.querySelector(`.erro-campo[data-de="${CSS.escape(nome)}"]`);
    if (msg) { msg.textContent = erro; msg.hidden = !erro; }
    inp.setAttribute("aria-invalid", erro ? "true" : "false");
    if (erro && !primeiro) primeiro = inp;
    if (!nome.endsWith("#2") && v) {
      const rot = R.maiuscula(String(c.rotulo || base).replace(/^(o|a) /, ""));
      eco.push(`${rot}: ${c.formato === "digitos" && digitos.length > 4 ? `…${digitos.slice(-4)}` : v}`);
    }
  }
  if (primeiro) { primeiro.focus(); primeiro.scrollIntoView({ block: "center" }); return null; }
  return eco.join(" · ");
}

function enviarResidual() {
  const eco = validarResidual();
  if (eco === null) return;
  const residual = Object.fromEntries((S.el.residual || []).map((i) => [i.dataset.campo, i.value.trim()]).filter(([, v]) => v));
  marcarVista();
  const fala = `Li no papel: ${eco}`;
  executar(() => api.turno(S.id, "", residual), { texto: "Conferindo os campos…", fala }, { origem: "texto", eco: fala });
}

async function pedirRascunho() { await executar(() => api.rascunho(S.id), { texto: "Conferindo tudo antes de emitir…" }); }

async function enviarDoCaso(nome, tipo) {
  if (emReplay()) {
    const p = passoAtual();
    if (p?.evidencia === nome) proximoPasso(); else avisoRoteiro();
    return;
  }
  marcarVista();
  const texto = S.el.texto.value.trim();
  S.el.texto.value = "";
  ajustarAltura(S.el.texto);
  await executar(() => api.evidenciaCaso(S.id, nome, texto), { fala: texto, evidencia: tipo, nome, texto: STATUS_ENVIO[tipo], restaurar: texto });
}

// Demonstração pública: o arquivo cabe nos limites (tamanho e, no vídeo, a duração)? A mensagem para a tela, ou null.
// Acima de 32 MiB o front-end do Cloud Run barra o pedido com uma página HTML, antes do app: por isso confere aqui.
async function foraDoLimitePublico(arquivo, tipo) {
  const lim = S.saude?.demo_publica?.limites;
  const msg = R.conferirArquivoPublico({ tipo, bytes: arquivo.size }, lim);
  if (msg || tipo !== "video") return msg;
  return R.conferirArquivoPublico({ tipo, bytes: arquivo.size, duracao: await duracaoDoVideo(arquivo) }, lim);
}
// a duração pelos metadados, num <video> fora da página; null quando o navegador não lê o formato (aí a API confere)
function duracaoDoVideo(arquivo, espera = 5000) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    let url = null; let feito = false;
    const fim = (d) => {
      if (feito) return;
      feito = true;
      clearTimeout(t);
      v.onloadedmetadata = null; v.onerror = null;
      v.removeAttribute("src");
      if (url) URL.revokeObjectURL(url);
      resolve(Number.isFinite(d) && d > 0 ? d : null);
    };
    const t = setTimeout(() => fim(null), espera);
    v.preload = "metadata";
    v.muted = true;
    v.onloadedmetadata = () => fim(v.duration);
    v.onerror = () => fim(null);
    try { url = URL.createObjectURL(arquivo); v.src = url; } catch { fim(null); }
  });
}

async function enviarArquivo(arquivo, tipo, itemId) {
  if (S.ocupado || S.conferindoArquivo) return;
  if (publica()) {
    S.conferindoArquivo = true;
    let msg = null;
    try { msg = await foraDoLimitePublico(arquivo, tipo); } finally { if (S) S.conferindoArquivo = false; }
    if (!S) return;
    // nada sai do aparelho: o comentário fica no campo
    if (msg) { avisar(msg, true); return; }
  }
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
  // demonstração pública: a localização do visitante não sai do aparelho (só os presets do caso têm GPS)
  if ((tipo === "foto" || tipo === "video") && !publica()) {
    ocupar({ ...base, texto: "Lendo a localização…" });
    const g = await lerGPS();
    if (!S) return;
    if (!g.erro) { form.append("lat", g.lat); form.append("lon", g.lon); form.append("precisao_m", g.precisao_m); form.append("gps_capturado_em", g.capturado_em); }
    ocupar(null);
  }
  S.progresso = 0;
  await executar(() => postFormProgresso(`/api/fiscalizacoes/${encodeURIComponent(S.id)}/evidencias`, form, (f) => {
    if (!S) return;
    S.progresso = f;
    if (f >= 1) {
      S.ocupadoTexto = publica() && tipo === "video" ? "Contando os animais do vídeo na CPU… pode levar ~1 min" : STATUS_ENVIO[tipo] || "Conferindo…";
      S.progresso = null;
    }
    const t = document.querySelector("#pensando .pensando-txt");
    if (t) t.textContent = S.ocupadoTexto;
    const i = document.querySelector("#pensando .barra-envio i");
    if (i && S.progresso !== null) i.style.width = `${Math.round(S.progresso * 100)}%`;
  }), { ...base, texto: `Enviando (${(arquivo.size / 1e6).toFixed(1)} MB)…` });
}

// ---------------------------------------------------------------- voz (segurar para falar)
function ligarFalar(btn, residual = false) {
  btn.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (!vozDisponivel()) { avisar("Voz desligada nesta execução: digite a mensagem."); return; }
    e.preventDefault(); btn.setPointerCapture?.(e.pointerId); iniciarGravacao(residual);
  });
  const parar = (e) => { if (S?.gravando) { e.preventDefault(); pararGravacao(); } };
  btn.addEventListener("pointerup", parar);
  btn.addEventListener("pointercancel", parar);
  btn.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); if (vozDisponivel()) iniciarGravacao(residual); else avisar("Voz desligada nesta execução: digite a mensagem."); } });
  btn.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); pararGravacao(); } });
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
}

function mostrarGravando(sim) {
  S.el.falar.classList.toggle("gravando-on", sim);
  S.el.falar.setAttribute("aria-pressed", sim ? "true" : "false");
  S.el.gravando.hidden = !sim;
  S.el.texto.hidden = sim;
  clearInterval(S.tRec);
  if (sim) {
    const t0 = Date.now();
    S.tRec = setInterval(() => { const s = Math.floor((Date.now() - t0) / 1000); S.el.gravando.querySelector(".rec-t").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }, 500);
  }
}

async function iniciarGravacao() {
  if (!S || S.gravando || S.ocupado) return;
  if (emReplay()) { avisoRoteiro(); return; }
  try { if (localStorage.getItem("lv.avisoVoz") !== "1") { S.el.avisoVoz.hidden = false; localStorage.setItem("lv.avisoVoz", "1"); } } catch { /* */ }
  S.gravando = true;
  mostrarGravando(true);
  try {
    if (!S.gravador) S.gravador = new Gravador();
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
  form.append("confirmar_numeros", confirmarNumeros() ? "true" : "false");
  await executar(() => postForm(`/api/fiscalizacoes/${encodeURIComponent(S.id)}/turno-audio`, form), { texto: "Transcrevendo a fala…" }, { origem: "voz" });
}
