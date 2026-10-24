// Laudo: rascunho → "Revisar e assinar" (a fiscal confere o resumo, marca que revisou e assina com o PIN; o agente
// não assina); selado → "Laudo selado" (o lacre carvão com quem assinou e quando, a trilha Em campo → Rascunho →
// Assinado → Selado e o código do laudo; o placar, os pedidos recusados e o pacote BCB/Justiça). No computador a folha
// do laudo fica ao lado; no celular, "Ler o laudo completo" abre a folha.
// A API continua recebendo `hash_confirmado: laudo.hash_raiz`: marcar a caixa é a confirmação humana.

import { api } from "./api.js";
import { cartaoResumo, justificativa, placar, trilhaEtapas, verCodigo } from "./componentes.js";
import * as R from "./regras.js";
import { PERFIS, definirTela, papel, perfil } from "./sessao.js";
import { ROT_CHECK, abrirModal, anunciar, atualizarSaude, avisar, blocoTec, chipChecklist, chipStatus, concordar, definirDemo, definirTopo, ehMovel, h,
  hashAgrupado, icone, kv, limparErros, secaoTecnica, simbolo } from "./ui.js";
import { tts } from "./voz.js";

let SAUDE = null;
export async function telaLaudo(raiz, fisId, { focarAssinatura = false, abrirPacote = false, completo = false, conferencia = null, saude = undefined } = {}) {
  if (saude !== undefined) SAUDE = saude;
  raiz.replaceChildren(h("div", { class: "pagina", "aria-busy": "true" }, h("p", { class: "so-leitor" }, "Carregando o laudo…"),
    h("div", { class: "cartao esqueleto alto" })));
  let estado; let laudo;
  try {
    estado = await api.estado(fisId);
    laudo = await api.laudo(fisId);
  } catch (e) {
    definirTela("assinar", { demo: !!estado?.demonstracao });
    definirDemo(estado?.demonstracao || null);
    definirTopo({ trilha: [{ rot: "Carteira", href: "#/carteira" }, { rot: `Op. ${estado?.operacao?.ref_bacen || ""}`, href: `#/fis/${encodeURIComponent(fisId)}` }, { rot: "Laudo" }],
      titulo: "Laudo", voltar: `#/fis/${encodeURIComponent(fisId)}` });
    raiz.replaceChildren(h("div", { class: "pagina estreita" }, h("div", { class: "vazio" }, h("h1", { class: "t-titulo" }, "O laudo ainda não foi emitido."),
      h("p", { class: "t-sec" }, e.status === 404 ? "O rascunho sai quando todos os itens estão prontos. Volte à fiscalização." : e.message),
      h("a", { class: "btn btn-pri", href: `#/fis/${encodeURIComponent(fisId)}` }, icone("voltar"), "Voltar à fiscalização"))));
    return;
  }
  const selado = laudo.tipo === "selado" || estado.etapa === "SELADO";
  const movel = ehMovel();
  definirTela(selado ? (movel ? "selado-m" : "selado") : "assinar", { demo: !!(estado.demonstracao || laudo.demonstracao) });
  definirDemo(estado.demonstracao || laudo.demonstracao || null);
  const base = `#/fis/${encodeURIComponent(fisId)}`;
  definirTopo({
    trilha: [{ rot: "Carteira", href: "#/carteira" }, { rot: `Op. ${estado.operacao.ref_bacen}`, href: base }, { rot: "Laudo" }],
    titulo: completo ? "Laudo completo" : selado ? "Laudo" : papel() === "fiscal" ? "Revisar e assinar" : "Rascunho do laudo",
    voltar: completo ? `${base}/laudo` : base,
  });
  const ctx = { fisId, estado, laudo, selado, conferencia, base, saude: SAUDE };
  let tela;
  if (movel && completo) tela = telaCompleto(ctx);
  else if (movel) tela = selado ? seladoMovel(ctx) : assinarTela(ctx, true);
  else {
    tela = h("div", { class: `laudo-tela grade-laudo${selado ? " selado" : " rascunho"}` }, folhaLaudo(ctx),
      h("aside", { class: "laudo-lado" }, selado ? ladoSelado(ctx) : assinarTela(ctx, false)));
  }
  raiz.replaceChildren(tela);
  secaoTecnica("laudo", () => blocoTec("Laudo", kv([["Tipo", laudo.tipo], ["Código (hash raiz)", laudo.hash_raiz, "mono"], laudo.selo ? ["Selo", laudo.selo, "mono"] : null,
    ["Regras", laudo.metodo?.rulebook_versao || "—", "mono"], ["Cadeia de evidências", `${laudo.cadeia?.n ?? "?"} evidências · ${laudo.cadeia?.integra ? "íntegra" : "QUEBRADA"}`]]),
  h("div", { class: "acoes-linha" },
    h("a", { class: "btn btn-sec", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo`, target: "_blank", rel: "noopener" }, icone("codigo"), "Laudo (JSON)"),
    h("a", { class: "btn btn-sec", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo.html`, target: "_blank", rel: "noopener" }, icone("imprimir"), "Para imprimir"))));
  if (focarAssinatura && !selado) setTimeout(() => document.getElementById("conf-hash")?.focus({ preventScroll: true }), 80);
  // demonstração pública no celular: quem chega pelo QR não sabe que precisa rolar até o PIN
  if (movel && !completo && !selado && publica(ctx) && papel() === "fiscal") requestAnimationFrame(mostrarCaixaEPin);
  if (abrirPacote && selado) gerarPacote(fisId);
}

function publica(ctx) { return !!ctx?.saude?.config?.demo_publica; }

// "Revisar e assinar" no celular: a tela abre com a caixa "Revisei o laudo" e o PIN (com a dica do PIN da demonstração)
// à vista, entre o topo fixo e o rodapé fixo (sem rolar, o PIN ficava atrás do rodapé e a dica, fora da tela).
function mostrarCaixaEPin() {
  const form = document.querySelector("form.assinar-m");
  const pin = form?.querySelector(".pin-campo");
  const conf = form?.querySelector(".confere-chk");
  const rod = form?.querySelector(".rodape-fixo");
  if (!pin || !conf || !rod) return;
  const y = window.scrollY;
  const topo = document.getElementById("cabecalho")?.offsetHeight || 0;
  // o mínimo para o PIN sair de trás do rodapé; o máximo sem esconder a caixa atrás do topo
  const min = pin.getBoundingClientRect().bottom + y - (window.innerHeight - rod.offsetHeight - 8);
  const max = conf.getBoundingClientRect().top + y - topo - 8;
  const alvo = Math.max(0, Math.min(Math.max(y, min), max));
  if (Math.abs(alvo - y) > 1) window.scrollTo(0, alvo);
}

// ---------------------------------------------------------------- folha do laudo (o documento)
function tituloObjeto(it) {
  return R.descricaoCurta(it.descricao, 90).replace(/\b(\d{4,})\b/g, (m) => R.fmtInt(m)).replace(/ (\d+) fios$/, ", $1 fios");
}

function folhaLaudo({ estado, laudo, selado, base }) {
  const e = estado;
  const op = e.operacao;
  const ls = R.linhas(e);
  const res = R.resumoPorObjeto(e, { daFiscal: false });
  const linhaItem = (l) => {
    const x = R.itemNoLaudo(e, l);
    return h("div", { class: "fl-item" },
      h("div", { class: "txt" }, h("strong", {}, x.titulo), h("span", { class: "t-sec" }, x.frase),
        l.justificativa ? justificativa(l.justificativa) : null),
      chipStatus(R.justificada(l) ? "divergente-j" : l.status),
      h("a", { class: "vp", href: `${base}?campo=${encodeURIComponent(l.campo)}` }, "Ver prova"));
  };
  const blocos = (op.itens || []).map((it) => {
    const filhos = ls.filter((l) => l.item_id === it.id);
    if (!filhos.length) return null;
    // um selo por item: o status fica nas linhas; o cabeçalho do objeto é só o nome
    return h("section", { class: "fl-obj" }, h("div", { class: "fl-obj-cab" }, icone(R.ehBovino(it) ? "vaca" : "cerca"), h("h3", {}, tituloObjeto(it))),
      filhos.map(linhaItem));
  }).filter(Boolean);
  const resto = ls.filter((l) => !(op.itens || []).some((i) => i.id === l.item_id));
  if (resto.length) blocos.push(h("section", { class: "fl-obj" }, h("div", { class: "fl-obj-cab" }, icone("lista"), h("h3", {}, "Requisitos da fiscalização")), resto.map(linhaItem)));
  const doAgente = (res.doAgente || []).filter((u) => u.pronta).map((u) => R.minuscula(R.rotuloUnidade(e, u).pronto.split(/[:(]/)[0].trim()));
  const agente = doAgente.length ? ` O agente verificou também, com os dados da operação: ${doAgente.length > 1 ? `${doAgente.slice(0, -1).join(", ")} e ${doAgente.at(-1)}` : doAgente[0]}.` : "";
  const concl = res.Dj ? [h("strong", {}, `${res.T} itens prontos:`), ` ${res.V} verificados e ${res.Dj} divergentes, com a justificativa da fiscal.${agente} Cada item aponta para a sua prova.`]
    : [h("strong", {}, `${res.T} itens prontos:`), ` ${res.V} verificados.${agente} Cada item aponta para a sua prova.`];
  return h("article", { class: `folha-laudo${laudo.demonstracao || e.demonstracao ? " demo" : ""}`, "aria-labelledby": "t-laudo" },
    h("header", { class: "fl-cab" }, h("span", { class: "fl-marca" }, simbolo("selo-g", "fl-ic"), "Laudo Vivo"), h("span", { class: "t-sec" }, "Laudo de fiscalização do crédito rural")),
    h("h2", { id: "t-laudo", class: "t-titulo" }, `Operação ${op.ref_bacen} · ${R.localOperacao(op)}`),
    h("p", { class: "fl-meta t-sec" }, h("span", {}, R.instituicaoLimpa(op.instituicao)), h("span", {}, R.maiuscula(laudo.metodo?.rotulo || e.metodo_rotulo || "")),
      h("span", {}, `Fiscalização em ${R.dataBR(laudo.data_referencia)}`)),
    selado ? null : h("p", { class: "fl-rascunho" }, chipStatus("pendente", papel() === "fiscal" ? "Rascunho: só vale depois da sua assinatura" : "Rascunho: só vale depois da assinatura da fiscal")),
    h("p", { class: "fl-concl" }, concl),
    blocos,
    (laudo.atribuicoes || []).length ? h("p", { class: "fl-rodape t-sec" }, laudo.atribuicoes.join(". "), ".") : null);
}

// ---------------------------------------------------------------- selado (computador): estado, código, recusas
// Um só nome e um só rótulo de papel em toda parte (lacre, trilha, tela de assinar): "Ana (fictícia) (fiscal)".
function quemAssinou(estado, laudo) {
  const a = (laudo.assinaturas || estado.assinaturas || [])[0];
  if (!a) return "Assinado.";
  const quando = R.dataHora(a.em);
  return `Assinado por ${a.nome_ref} (${a.papel === "fiscal" ? "fiscal" : a.papel}) em ${quando}`;
}

function conferenciaSelo(ctx) {
  const c = ctx.conferencia || ctx.estado.laudo || {};
  if (c.conteudo_confere === undefined || c.conteudo_confere === null) return null;
  const ok = c.conteudo_confere === true;
  return h("p", { class: `confere ${ok ? "ok" : "falha"}`, role: ok ? "status" : "alert" }, icone(ok ? "escudo-cheio" : "alerta"),
    h("span", {}, ok ? "O conteúdo confere com o rascunho assinado" : "O laudo selado não confere com o rascunho assinado"));
}

// O lacre: a chapa carvão de canto cortado com o símbolo, quem assinou e quando, a trilha das etapas e, depois do
// picote, o código do laudo em blocos de 4 (o mesmo que o agente cita), que ninguém pode alterar.
function lacre(ctx) {
  const { estado, laudo } = ctx;
  return h("div", { class: "lacre", id: "assinar" },
    h("div", { class: "lacre-topo" }, h("span", { class: "carimbo selado" }, simbolo("selo-g", "selo-ic")),
      h("div", {}, h("h1", {}, "Laudo selado"), h("p", { class: "quando" }, quemAssinou(estado, laudo)))),
    trilhaEtapas(estado, { comQuem: true, fiscal: PERFIS.fiscal.nome, segundos: true }),
    h("div", { class: "lacre-cod", role: "group", "aria-label": "Código do laudo" },
      h("p", { class: "r" }, icone("cadeado-cheio"), "Código do laudo · ninguém pode alterar"),
      h("div", { class: "h" }, h("span", { class: "codigo mono", translate: "no" }, R.codigoCurto(laudo.hash_raiz)),
        h("button", { class: "btn btn-ter link", type: "button", onclick: () => verCodigo(laudo.hash_raiz) }, "Ver todo"))));
}

// Placar do laudo selado: itens prontos · verificados · divergentes justificados
function placarLaudo(estado) {
  const r = R.resumoPorObjeto(estado);
  return placar([{ n: String(r.T), rot: r.T === 1 ? "item pronto" : "itens prontos" }, { n: String(r.V), rot: r.V === 1 ? "verificado" : "verificados", cls: "ok" },
    { n: String(r.Dj), rot: r.Dj === 1 ? "divergente justificado" : "divergentes justificados", cls: "div" }]);
}

function ladoSelado(ctx) {
  const { estado, laudo, fisId, base } = ctx;
  const oc = laudo.ocorrencias || estado.ocorrencias || [];
  return [
    h("section", { class: "laudo-cab estado-selado" },
      lacre(ctx),
      conferenciaSelo(ctx),
      placarLaudo(estado),
      h("button", { class: "btn btn-pri btn-cheio", type: "button", id: "btn-pacote", onclick: () => gerarPacote(fisId) }, icone("baixar"), "Baixar pacote BCB/Justiça"),
      h("a", { class: "btn btn-sec btn-cheio", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo.html`, target: "_blank", rel: "noopener" }, icone("imprimir"), "Imprimir"),
      h("a", { class: "btn btn-ter", href: base }, icone("voltar"), "Voltar à fiscalização")),
    oc.length ? h("section", { class: "cartao recusas-card" }, h("h2", { class: "t-sub" }, `Pedidos recusados e registrados (${oc.length})`),
      h("ul", {}, oc.map((o) => h("li", {}, icone("escudo-cheio"), h("span", {}, R.textoOcorrencia(estado, o, { laudo: true })))))) : null,
  ].filter(Boolean);
}

// ---------------------------------------------------------------- selado (celular)
function seladoMovel(ctx) {
  const { estado, base } = ctx;
  // demonstração pública: depois do selo ainda há passo do roteiro (o 19, a tentativa de alterar o laudo selado), que
  // fecha a história; o botão principal volta à fiscalização, onde a barra da demonstração mostra o passo
  const resta = publica(ctx) && papel() === "fiscal" ? R.passoDepoisDoSelo(estado) : null;
  return h("div", { class: "pagina estreita selado-m laudo-tela" },
    h("section", { class: "laudo-cab" }, lacre(ctx)),
    placarLaudo(estado),
    cartaoResumo(R.resumoPorObjeto(estado)),
    h("p", { class: "nota-cad" }, icone("cadeado-cheio"), "Ninguém pode mudar este laudo. Correção abre uma nova fiscalização."),
    h("div", { class: "rodape-fixo" },
      resta ? h("a", { class: "btn btn-pri btn-cheio", id: "btn-continuar-demo", href: base, "aria-label": `Continuar a demonstração, passo ${resta} de ${estado.roteiro.total}` },
        icone("play"), "Continuar a demonstração") : null,
      h("a", { class: `btn ${resta ? "btn-sec" : "btn-pri"} btn-cheio`, href: `${base}/laudo?completo=1` }, icone("nota"), "Ver o laudo completo"),
      // com o botão da demonstração, o rodapé fixo fica em dois botões (a seta do topo também volta)
      resta ? null : h("a", { class: "btn btn-ter", href: "#/fiscalizacoes" }, "Voltar às fiscalizações")));
}

function telaCompleto(ctx) {
  const { selado, fisId, base } = ctx;
  return h("div", { class: "pagina laudo-tela completo-m" }, folhaLaudo(ctx),
    selado ? h("div", { class: "laudo-cab completo-acoes" }, conferenciaSelo(ctx),
      h("button", { class: "btn btn-pri btn-cheio", type: "button", id: "btn-pacote", onclick: () => gerarPacote(fisId) }, icone("baixar"), "Baixar pacote BCB/Justiça"),
      h("a", { class: "btn btn-sec btn-cheio", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo.html`, target: "_blank", rel: "noopener" }, icone("imprimir"), "Imprimir"),
      h("a", { class: "btn btn-ter", href: base }, "Voltar à fiscalização"))
      : h("div", { class: "rodape-fixo" }, h("a", { class: "btn btn-pri btn-cheio", href: `${base}/laudo` }, icone("assinar"), "Voltar para assinar")));
}

// os 12 primeiros caracteres (os que o agente cita) e os 4 últimos: "53fa 05eb 8853 … cef9"
function codigoRascunho(hx) {
  const s = String(hx || "");
  return s.length < 20 ? R.codigoBlocos(s) : `${R.codigoBlocos(s.slice(0, 12))} … ${s.slice(-4)}`;
}

// Na demonstração com o PIN de demonstração, uma dica discreta (escondida até pedir): sem ela, quem não leu o roteiro
// não consegue assinar.
function dicaPin(ctx) {
  if (!ctx.saude?.config?.pin_demo || !(ctx.estado.demonstracao || ctx.laudo.demonstracao)) return null;
  // demonstração pública (QR code): quem chega sozinho vê o PIN na tela, sem precisar pedir
  if (ctx.saude?.config?.demo_publica) {
    return h("p", { class: "pin-dica t-sec" }, icone("info"), h("span", {}, "PIN da demonstração: ",
      h("strong", { class: "mono", translate: "no" }, "2410"), " (dados sintéticos; na vida real, só a fiscal sabe o PIN)"));
  }
  const valor = h("span", { class: "mono", translate: "no" }, "••••");
  const b = h("button", { class: "btn-ter link", type: "button", "aria-expanded": "false", onclick: () => {
    const ver = b.getAttribute("aria-expanded") !== "true";
    valor.textContent = ver ? "2410" : "••••";
    b.textContent = ver ? "Esconder" : "Mostrar";
    b.setAttribute("aria-expanded", ver ? "true" : "false");
  } }, "Mostrar");
  return h("p", { class: "pin-dica t-sec" }, icone("info"), h("span", {}, "PIN da demonstração: ", valor), b);
}

// ---------------------------------------------------------------- analista: o rascunho só para ler
function aguardandoTela(ctx, movel) {
  const { estado, base } = ctx;
  const f = PERFIS.fiscal;
  const corpo = h("section", { class: `assinatura aguardando${movel ? "" : " cartao"}`, id: movel ? "assinar" : null },
    movel ? null : h("h1", { class: "t-titulo" }, "Rascunho do laudo"),
    h("p", { class: "quem" }, h("span", { class: "ini" }, f.iniciais), h("span", {}, "Aguardando a assinatura de ", h("strong", {}, f.nome), ` (${f.titulo.toLowerCase()})`)),
    h("p", { class: "t-sec" }, "Só quem foi a campo assina. Você recebe o laudo selado para ler assim que ela assinar."),
    cartaoResumo(R.resumoPorObjeto(estado, { daFiscal: false }), { link: movel ? h("a", { class: "linha-link", href: `${base}/laudo?completo=1` }, h("span", {}, "Ler o rascunho completo"), icone("direita"))
      : h("button", { class: "linha-link", type: "button", onclick: () => document.querySelector(".folha-laudo")?.scrollIntoView({ block: "start", behavior: "smooth" }) },
        h("span", {}, "Ler o rascunho completo"), icone("direita")) }),
    h("a", { class: "btn btn-ter", href: base }, icone("voltar"), "Voltar à fiscalização"));
  return movel ? h("div", { class: "pagina estreita laudo-tela assinar-pagina" }, corpo) : corpo;
}

// ---------------------------------------------------------------- Revisar e assinar
function assinarTela(ctx, movel) {
  const { estado, laudo, fisId, base } = ctx;
  if (papel() !== "fiscal") return aguardandoTela(ctx, movel);
  const pode = ["RASCUNHO", "ASSINATURA"].includes(estado.etapa) && estado.laudo?.tipo === "rascunho" && estado.laudo?.valido_para_assinar !== false;
  const p = perfil();
  const conf = h("input", { type: "checkbox", id: "conf-hash", class: "ok-alvo", "aria-describedby": "motivo-ass" });
  const pin = h("input", { type: "password", id: "pin", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "12", "aria-describedby": "erro-pin motivo-ass",
    "aria-label": "Seu PIN de 4 dígitos" });
  const caixas = [0, 1, 2, 3].map(() => h("span", { class: "pin-caixa" }));
  const erroPin = h("p", { class: "erro-campo", id: "erro-pin", role: "alert", hidden: true });
  const motivo = h("p", { class: "motivo-btn", id: "motivo-ass" });
  const btn = h("button", { class: "btn btn-pri btn-cheio", type: "submit", disabled: true }, icone("assinar"), "Assinar laudo");
  let enviando = false;
  const pinOk = () => pin.value.trim().length >= 4;
  const atualizarCaixas = () => {
    const n = pin.value.length;
    caixas.forEach((c, i) => { c.classList.toggle("cheia", i < n); c.classList.toggle("atual", i === Math.min(n, 3) && document.activeElement === pin); });
  };
  const conferir = () => {
    const falta = !pode ? (estado.laudo?.valido_para_assinar === false ? "Há prova nova depois do rascunho: emita de novo na fiscalização." : "Emita o rascunho primeiro.")
      : !conf.checked ? "Marque que revisou o laudo." : !pinOk() ? "Digite o PIN de 4 dígitos." : "";
    btn.disabled = !!falta || enviando;
    motivo.textContent = falta;
    motivo.hidden = !falta;
  };
  conf.addEventListener("change", conferir);
  pin.addEventListener("input", () => { erroPin.hidden = true; atualizarCaixas(); conferir(); });
  pin.addEventListener("focus", atualizarCaixas);
  pin.addEventListener("blur", atualizarCaixas);
  const form = h("form", { class: `assinatura${movel ? " assinar-m" : " cartao"}`, id: movel ? "assinar" : null, novalidate: true, onsubmit: async (ev) => {
    ev.preventDefault();
    if (!conf.checked || !pinOk()) { conferir(); (conf.checked ? pin : conf).focus(); return; }
    enviando = true; conferir();
    try {
      const r = await api.assinar(fisId, { pin: pin.value, hash_confirmado: laudo.hash_raiz, papel: "fiscal", nome_ref: p.nome });
      pin.value = ""; atualizarCaixas();
      const ok = r.estado?.etapa === "SELADO";
      tts.falar(r.fala_voz || r.resposta?.fala);
      anunciar(r.resposta?.fala || "", !ok);
      atualizarSaude();
      if (ok) {
        limparErros();
        const sel = r.resposta?.laudo || {};
        // o lacre já diz que selou: sem aviso flutuante por cima do laudo e do botão principal (só o leitor de tela ouve)
        if (sel.conteudo_confere === false) avisar("O laudo selado não confere com o rascunho assinado.", true, 9000);
        else anunciar("Laudo assinado e selado.");
        setTimeout(() => telaLaudo(document.getElementById("conteudo"), fisId, { conferencia: { conteudo_confere: sel.conteudo_confere, verificacao: sel.verificacao } }), 300);
        return;
      }
      if ((r.resposta?.avisos || []).some((a) => a.startsWith("laudo não selado"))) erroPin.textContent = "Assinatura recusada: o rascunho mudou. Nada foi selado.";
      else {
        const n = r.tentativas_restantes;
        erroPin.textContent = `PIN não confere. Nada foi assinado${n !== undefined && n !== null ? `; ${n === 1 ? "resta 1 tentativa" : `restam ${n} tentativas`}` : ""}.`;
      }
      erroPin.hidden = false;
      pin.value = ""; atualizarCaixas();
      pin.focus({ preventScroll: true });
      // as caixas do PIN ficam à vista acima do rodapé (onde está o erro), para digitar de novo
      if (movel) pin.closest(".pin-campo")?.scrollIntoView({ block: "center" }); else erroPin.scrollIntoView({ block: "nearest" });
    } catch (err) {
      erroPin.textContent = err.message; erroPin.hidden = false;
      erroPin.scrollIntoView({ block: "nearest" });
      atualizarSaude();
    }
    enviando = false; conferir();
  } },
  movel ? null : h("h1", { class: "t-titulo" }, "Revisar e assinar"),
  h("p", { class: "t-sec" }, "Confira antes de assinar."),
  cartaoResumo(R.resumoPorObjeto(estado), { link: movel ? h("a", { class: "linha-link", href: `${base}/laudo?completo=1` }, h("span", {}, "Ler o laudo completo"), icone("direita"))
    : h("button", { class: "linha-link", type: "button", onclick: () => document.querySelector(".folha-laudo")?.scrollIntoView({ block: "start", behavior: "smooth" }) },
      h("span", {}, "Ler o laudo completo"), icone("direita")) }),
  h("label", { class: "cartao confere-chk", for: "conf-hash" }, conf, h("span", {}, h("strong", {}, "Revisei o laudo"), " e confirmo o que vi em campo.",
    // o mesmo código que o agente cita na conversa ("Rascunho emitido (código 53fa 05eb 8853)")
    laudo.hash_raiz ? h("span", { class: "codigo-rasc" }, "Código do rascunho: ", h("span", { class: "mono", translate: "no" }, codigoRascunho(laudo.hash_raiz))) : null)),
  h("p", { class: "quem" }, h("span", { class: "ini" }, p.iniciais), h("span", {}, "Assinando como ", h("strong", {}, p.nome), ` (${p.titulo.toLowerCase()})`)),
  h("div", { class: "pin-campo" }, h("label", { for: "pin", class: "pin-rot" }, "Seu PIN de 4 dígitos"),
    h("div", { class: "pin-caixas" }, caixas, pin), dicaPin(ctx)),
  h("div", { class: movel ? "rodape-fixo" : "rodape-ass" }, erroPin, btn, motivo,
    h("p", { class: "nao-assina" }, icone("escudo-cheio"), "O agente não assina. A assinatura é sua.")));
  conferir();
  return movel ? h("div", { class: "pagina estreita laudo-tela assinar-pagina" }, form) : form;
}

// ---------------------------------------------------------------- pacote BCB/Justiça (ação humana, só depois do selo)
// O checklist "Ordem JF Rio Verde" em placar (presente · parcial · ausente · não aplicável, como o placar do selado),
// cada item com o seu selo fora da regra de cor da conferência, o texto com a concordância certa e os códigos das
// regras atrás de "Ver fundamento".
const CODIGO_REGRA = /\b[A-Z]{2,}(?:-[A-Z0-9]+){2,}(?:-cl\d+)?\b|\bMCR\s\d+-\d+(?:-\d+)?\b/;
function separarFundamento(texto) {
  let corpo = concordar(texto || "");
  const fund = [];
  // parênteses com códigos de regra saem do texto e vão para "Ver fundamento"
  corpo = corpo.replace(/\s*\(([^()]*)\)/g, (m, dentro) => (CODIGO_REGRA.test(dentro) ? (fund.push(dentro.trim()), "") : m));
  // trechos "; campos sem citação literal: a, b" também
  corpo = corpo.replace(/;\s*([^;]*:\s*[^;]*)/g, (m, trecho) => (CODIGO_REGRA.test(trecho) ? (fund.push(trecho.trim()), "") : m));
  return { corpo: corpo.replace(/\s+([.,;])/g, "$1").trim(), fund };
}

function itemChecklist(it) {
  const { corpo, fund } = separarFundamento(it.justificativa || it.motivo || "");
  return h("li", {}, h("span", { class: "txt" }, h("strong", {}, it.titulo), corpo ? h("span", { class: "t-sec" }, R.maiuscula(corpo)) : null,
    fund.length ? h("details", { class: "fund-det" }, h("summary", {}, "Ver fundamento"), h("p", { class: "fonte" }, fund.map((f) => R.maiuscula(f)).join(". "))) : null),
  chipChecklist(it.status));
}

async function gerarPacote(fisId) {
  const btn = document.getElementById("btn-pacote");
  if (btn) btn.disabled = true;
  try {
    const r = await api.pacote(fisId);
    const ck = r.checklist_ordem_jf || { itens: [] };
    const cont = ck.contagem || Object.fromEntries(Object.keys(ROT_CHECK).map((k) => [k, ck.itens.filter((i) => i.status === k).length]));
    const n = (k) => Number(cont[k] || 0);
    const pl = (k, um, varios) => (n(k) === 1 ? um : varios);
    const resumo = [`${n("presente")} ${pl("presente", "presente", "presentes")}`, `${n("parcial")} ${pl("parcial", "parcial", "parciais")}`,
      `${n("ausente")} ${pl("ausente", "ausente", "ausentes")}`, `${n("nao_aplicavel")} não ${pl("nao_aplicavel", "aplicável", "aplicáveis")}, com justificativa`].join(" · ");
    abrirModal("Pacote BCB/Justiça", h("div", { class: "pacote" },
      h("p", {}, "O pacote junta o laudo selado, as provas, a área financiada, as imagens do satélite e o fundamento de cada item, com o código de cada arquivo."),
      h("h3", { class: "t-sub" }, "Checklist “Ordem JF Rio Verde”"),
      placar([{ n: String(n("presente")), rot: pl("presente", "presente", "presentes"), cls: "ok-neutro" },
        { n: String(n("parcial")), rot: pl("parcial", "parcial", "parciais"), cls: "parcial" },
        { n: String(n("ausente")), rot: pl("ausente", "ausente", "ausentes"), cls: "ausente" },
        { n: String(n("nao_aplicavel")), rot: `não ${pl("nao_aplicavel", "aplicável", "aplicáveis")}`, cls: "na" }], { cls: "placar-chk" }),
      h("p", { class: "so-leitor" }, resumo),
      h("ul", { class: "checklist" }, ck.itens.map(itemChecklist)),
      kv([["Arquivos", `${r.n_arquivos} (cada um com o seu código sha256)`], ["Código do pacote", hashAgrupado(r.sha256_zip)],
        ["Prazo de contestação", `${r.prazo_contestacao_dias} dias`]]),
      r.faltas?.length ? h("p", { class: "erro-campo", role: "alert" }, `Faltas: ${r.faltas.join("; ")}`) : null,
      h("div", { class: "acoes-linha" }, h("a", { class: "btn btn-pri", href: r.url, download: r.nome || "" }, icone("baixar"), "Baixar pacote (ZIP)"))), { largo: true });
    anunciar(`Pacote gerado: ${resumo}`);
  } catch (e) {
    avisar(e.status === 409 ? "O pacote sai só depois do laudo selado." : `Pacote não gerado: ${e.message}`, true);
  } finally { if (btn) btn.disabled = false; }
}
