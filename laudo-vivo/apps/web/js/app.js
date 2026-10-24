// Laudo Vivo — roteamento por hash, topo (usuário, Detalhes técnicos), estado do sistema e modo apresentação.
//   #/fiscalizacoes        Suas fiscalizações (a fiscal; padrão no celular)
//   #/carteira             Carteira: mapa + lista (o analista; padrão no computador e no modo apresentação)
//   #/fis/<id>             Fiscalização: conversa com o agente + laudo (?campo= abre a prova de um item)
//   #/fis/<id>/laudo       rascunho → Revisar e assinar; selado → Laudo selado (?pacote=1 abre o pacote; ?completo=1
//                          mostra o laudo inteiro no celular)
// Modo apresentação (telão): `?apresentacao=1`, o menu do usuário ou localStorage "lv.apresentacao"; só a raiz muda
// (tudo em rem), a barra da demonstração fica recolhida e a carteira abre com o caso de demonstração selecionado.

import { api } from "./api.js";
import { telaCarteira } from "./carteira.js";
import { sairFiscalizacao, telaFiscalizacao } from "./fiscalizacao.js";
import { telaFiscalizacoes } from "./fiscalizacoes.js";
import { telaLaudo } from "./laudo.js";
import { PERFIS, apresentacaoLigada, definirTela, demoPelaUrl, modoDemo, papel, papelEscolhido, perfil, salvarPapel, telaAtual,
  trocarPapel } from "./sessao.js";
import { abrirMenu, abrirTecnico, avisar, blocoTec, definirDemo, definirTopo, ehMovel, fecharMenus, h, icone, iniciarModal, kv,
  limparAnuncios, secaoTecnica, tecnicoAberto } from "./ui.js";
import { preferenciasVoz } from "./voz.js";

const raiz = document.getElementById("conteudo");
let saude = null;
let semConexaoAvisado = false;

function linhaEstado(rotulo, valor, nivel) {
  return h("div", { class: "tec-linha" }, h("span", { class: `pt ${nivel || ""}`, "aria-hidden": "true" }),
    h("span", { class: "tec-rot" }, rotulo), h("span", { class: "tec-val" }, valor));
}

function secaoSistema() {
  if (!saude) return blocoTec("Sistema", h("p", {}, "Sem conexão com o servidor: a interface não recebe o estado."));
  const llm = saude.llm || {};
  const asr = saude.asr || {};
  const fer = saude.ferramentas || {};
  const modo = llm.tipo === "replay" ? "Contingência: respostas do modelo reproduzidas de uma gravação real deste caso (replay)"
    : llm.tipo === "publico" ? "Demonstração pública: cada passo do roteiro sai de uma gravação real deste caso; o texto livre vai ao modelo ao vivo"
      : llm.tipo === "roteiro" ? "Roteiro fixo, sem modelo (testes)" : "Ao vivo";
  const vivo = llm.ao_vivo ? `gravação + ${llm.ao_vivo.modelo || llm.ao_vivo.nome} ao vivo` : "gravação; fora dela, as regras e as falas prontas";
  return blocoTec("Sistema",
    linhaEstado("Modo", modo, llm.tipo === "replay" || llm.tipo === "publico" ? "alerta" : "ok"),
    linhaEstado("Modelo de linguagem", llm.tipo === "replay" ? "gravação do modelo local" : llm.tipo === "publico" ? vivo
      : llm.tipo === "roteiro" ? "sem modelo" : "modelo local, nesta máquina", llm.disponivel ? "ok" : "erro"),
    llm.tipo === "replay" ? linhaEstado("Fora da gravação", `${llm.substituicoes || 0}`, llm.substituicoes ? "alerta" : "ok") : null,
    llm.tipo === "publico" ? linhaEstado("Fora da gravação", `${llm.fora_da_gravacao || 0}`, "ok") : null,
    linhaEstado("Voz (transcrição)", !asr.disponivel ? "desligada (digite)" : asr.carregado ? `${asr.dispositivo === "cuda" ? "GPU" : "CPU"} (Whisper)` : "carrega no 1º uso",
      asr.disponivel ? "ok" : ""),
    linhaEstado("Ferramentas", fer.modo || "?", fer.modo === "reais" ? "ok" : "alerta"),
    fer.falsas?.length ? h("p", { class: "t-sec" }, `Simuladas nesta execução: ${fer.falsas.join(", ")}.`) : null,
    kv([["Versão", saude.versao || "—", "mono"], ["Perfil", saude.config?.perfil || "—"], ["Caso padrão", saude.caso_padrao || "—"]]));
}

// Demonstração pública (QR code do slide): o caso de demonstração abre direto, cada visitante com a sua cópia
function publica() { return !!saude?.config?.demo_publica; }

async function carregarSaude() {
  try { saude = await api.saude(); semConexaoAvisado = false; } catch { saude = null; }
  if (saude) {
    document.body.classList.toggle("demo-publica", publica());
    const faixa = document.getElementById("faixa-publica");
    if (faixa) faixa.hidden = !publica();
  }
  const ponto = document.getElementById("ponto-tec");
  if (!saude) {
    ponto.className = "ponto-tec erro";
    if (!semConexaoAvisado) { avisar("Sem conexão com o servidor.", true); semConexaoAvisado = true; }
  } else {
    const llm = saude.llm || {};
    const fer = saude.ferramentas || {};
    ponto.className = `ponto-tec ${!llm.disponivel ? "erro" : (llm.substituicoes || fer.falsas?.length) ? "alerta" : "ok"}`;
    ponto.title = llm.tipo === "replay" ? `Replay: ${llm.substituicoes || 0} fora da gravação` : "";
  }
  secaoTecnica("sistema", secaoSistema);
}

// ---------------------------------------------------------------- usuário (canto superior direito em todas as telas)
function renderUsuario() {
  const p = perfil();
  document.getElementById("usuario-ini").textContent = p.iniciais;
  document.getElementById("usuario-nome").textContent = `${p.nome} · ${p.titulo}`;
  document.getElementById("usuario-vendo").hidden = !modoDemo();
  document.getElementById("btn-usuario").setAttribute("aria-label", `${modoDemo() ? "Vendo como " : ""}${p.nome}, ${p.titulo}. Abrir o menu`);
}

const CASA = { fiscal: "#/fiscalizacoes", analista: "#/carteira" };
const ROT_CASA = { fiscal: "Suas fiscalizações", analista: "Carteira" };

// Trocar de papel: nas telas de início, leva ao início do outro papel (a fiscal vai para "Suas fiscalizações"; o
// analista, para a carteira); na fiscalização e no laudo, a tela fica e muda o que a pessoa pode fazer.
function irComo(p) {
  const t = telaAtual();
  const inicio = t === "carteira" || t === "fiscalizacoes" || t === "inicio";
  if (!modoDemo()) salvarPapel(p);
  if (inicio) {
    if (modoDemo()) { location.hash = CASA[p]; return; }
    if (location.hash === CASA[p]) rotear(); else location.hash = CASA[p];
    return;
  }
  trocarPapel(p);
}

function menuUsuario() {
  const atual = papel();
  const outro = atual === "fiscal" ? "analista" : "fiscal";
  const o = PERFIS[outro];
  const ap = apresentacaoLigada();
  const naCasa = location.hash.split("?")[0] === CASA[atual];
  abrirMenu(document.getElementById("menu-usuario"), document.getElementById("btn-usuario"), [
    { rot: `Ver como ${o.titulo.toLowerCase()}`, sub: `${o.nome}, ${o.rotulo}`, ic: "usuario", acao: () => irComo(outro) },
    naCasa ? null : { rot: ROT_CASA[atual], ic: "lista", acao: () => { location.hash = CASA[atual]; } },
    ehMovel() ? { rot: "Detalhes técnicos", ic: "codigo", acao: () => abrirTecnico(true) } : null,
    { rot: "Voz", sub: "Resposta falada e microfone", ic: "mic", acao: () => preferenciasVoz() },
    { rot: ap ? "Sair do modo apresentação" : "Modo apresentação", sub: ap ? null : "Telão: tudo maior, a demonstração em destaque", ic: "compartilhar",
      acao: () => aplicarApresentacao(!ap) },
  ], { titulo: ehMovel() ? `${perfil().nome} · ${perfil().titulo}` : null });
}

// Primeiro uso (sem papel salvo e fora da demonstração): a pessoa diz quem é, e cada um entra no seu início.
function telaInicio() {
  definirTela("inicio");
  document.body.dataset.tela = "inicio";
  definirDemo(null);
  definirTopo({ casa: true, trilha: [{ rot: "Início" }] });
  const opcao = (p, titulo, texto, ic) => h("button", { class: "papel-op", type: "button", dataset: { papel: p },
    onclick: () => { salvarPapel(p); location.hash = CASA[p]; } },
  h("span", { class: "papel-ic" }, icone(ic)), h("span", { class: "txt" }, h("strong", {}, titulo), h("span", {}, texto)), icone("direita"));
  raiz.replaceChildren(h("div", { class: "pagina estreita inicio" },
    h("h1", { class: "t-display" }, "Como você vai usar o Laudo Vivo?"),
    h("p", { class: "t-sec" }, "Cada papel tem a sua tela. Dá para trocar depois, no menu com o seu nome."),
    h("div", { class: "papeis" },
      opcao("fiscal", "Sou fiscal de campo", "Vou à fazenda, envio as provas pelo celular e assino o laudo.", "camera"),
      opcao("analista", "Sou analista da cooperativa", "Escolho as operações para fiscalizar e leio os laudos selados.", "lista"))));
}

// ---------------------------------------------------------------- rotas
function rotaPadrao() {
  if (publica() && saude.demo_publica?.fis_id) return `#/fis/${encodeURIComponent(saude.demo_publica.fis_id)}`;
  if (apresentacaoLigada() || demoPelaUrl()) return papelEscolhido() && papel() === "fiscal" && ehMovel() ? "#/fiscalizacoes" : "#/carteira";
  return CASA[papel()] || "#/carteira";
}

async function rotear() {
  fecharMenus();
  const [caminho, consulta] = (location.hash || "").replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(consulta || "");
  const [tela, id, sub] = caminho.split("/").filter(Boolean);
  limparAnuncios();
  if (!tela) {
    if (!papelEscolhido() && !demoPelaUrl() && !apresentacaoLigada() && !publica()) { sairFiscalizacao(); telaInicio(); renderUsuario(); return; }
    location.replace(rotaPadrao()); return;
  }
  if (tela !== "fis" || sub === "laudo") sairFiscalizacao();
  definirDemo(null);
  secaoTecnica("fis", null);
  secaoTecnica("laudo", null);
  secaoTecnica("carteira", null);
  document.body.dataset.tela = tela === "fis" ? (sub === "laudo" ? "laudo" : "fis") : tela;
  if (tela === "fis" && id && sub === "laudo") {
    const focar = sessionStorage.getItem("lv.focarAssinatura") === "1";
    sessionStorage.removeItem("lv.focarAssinatura");
    await telaLaudo(raiz, decodeURIComponent(id), { focarAssinatura: focar, abrirPacote: params.get("pacote") === "1", completo: params.get("completo") === "1", saude });
  } else if (tela === "fis" && id) {
    await telaFiscalizacao(raiz, decodeURIComponent(id), { saude, irLaudo, campo: params.get("campo") });
  } else if (tela === "fiscalizacoes") {
    await telaFiscalizacoes(raiz, { saude });
  } else {
    await telaCarteira(raiz, { saude, abrirFis: (fid) => { location.hash = `#/fis/${encodeURIComponent(fid)}`; } });
  }
  renderUsuario();
  if (!document.activeElement || document.activeElement === document.body) raiz.focus({ preventScroll: true });
}

function irLaudo(fid, focarAssinatura = false) {
  if (focarAssinatura) sessionStorage.setItem("lv.focarAssinatura", "1");
  location.hash = `#/fis/${encodeURIComponent(fid)}/laudo`;
}

// ---------------------------------------------------------------- modo apresentação e medidas
function medirTopo() {
  const c = document.getElementById("cabecalho");
  document.documentElement.style.setProperty("--topo-h", `${c?.offsetHeight || 0}px`);
}

function lerApresentacao() {
  const url = new URLSearchParams(location.search).get("apresentacao");
  if (url === "1" || url === "0") {
    try { localStorage.setItem("lv.apresentacao", url); } catch { /* */ }
    return url === "1";
  }
  try { return localStorage.getItem("lv.apresentacao") === "1"; } catch { return false; }
}

function aplicarApresentacao(ligado) {
  document.body.classList.toggle("apresentacao", ligado);
  document.documentElement.classList.toggle("apresentacao", ligado);
  try { localStorage.setItem("lv.apresentacao", ligado ? "1" : "0"); } catch { /* */ }
  setTimeout(medirTopo, 0);
  window.dispatchEvent(new Event("lv:layout"));
}

window.matchMedia?.("(min-width: 1100px)").addEventListener?.("change", () => { window.dispatchEvent(new Event("lv:layout")); renderUsuario(); });

iniciarModal();
aplicarApresentacao(lerApresentacao());
document.getElementById("btn-usuario").addEventListener("click", () => {
  if (!document.getElementById("menu-usuario").hidden) { fecharMenus(); return; }
  menuUsuario();
});
document.getElementById("btn-tecnico").addEventListener("click", () => abrirTecnico());
document.querySelector("[data-fechar-tec]").addEventListener("click", () => abrirTecnico(false));
document.getElementById("veu-global").addEventListener("click", () => {
  fecharMenus();
  if (tecnicoAberto()) abrirTecnico(false);
  window.dispatchEvent(new Event("lv:veu"));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && tecnicoAberto() && !document.getElementById("modal").open) { e.stopImmediatePropagation(); abrirTecnico(false); }
}, true);
if ("ResizeObserver" in window) new ResizeObserver(medirTopo).observe(document.getElementById("cabecalho"));
window.addEventListener("hashchange", rotear);
window.addEventListener("resize", medirTopo);
window.addEventListener("lv:topo", () => setTimeout(medirTopo, 0));
window.addEventListener("lv:saude", carregarSaude);
window.addEventListener("lv:papel", (e) => { renderUsuario(); if (e.detail?.manual) rotear(); });
window.addEventListener("lv:apresentacao", (e) => aplicarApresentacao(!!e.detail));
medirTopo();
carregarSaude().then(rotear);
setInterval(carregarSaude, 30000);
