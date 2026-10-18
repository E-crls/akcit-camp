// Laudo Vivo — roteamento por hash, estado do sistema (na gaveta "Detalhes técnicos") e modo apresentação.
//   #/carteira            mapa + amostra
//   #/fis/<id>            fiscalização (conversa, laudo ao vivo, evidências e prova)
//   #/fis/<id>/laudo      laudo + assinatura humana (?pacote=1: abre o pacote de exibição, se selado)
// Modo apresentação (telão 1920/1366/1280; L21/L36): botão no topo ou `?apresentacao=1` na URL; fica salvo neste
// navegador. Fonte maior, conversa com pelo menos 40% da largura e a prova do item numa gaveta.

import { api } from "./api.js";
import { telaCarteira } from "./carteira.js";
import { sairFiscalizacao, telaFiscalizacao } from "./fiscalizacao.js";
import { telaLaudo } from "./laudo.js";
import { abrirTecnico, blocoTec, definirAvisosModo, definirDemo, h, iniciarModal, secaoTecnica, tecnicoAberto } from "./ui.js";

const raiz = document.getElementById("conteudo");
let saude = null;

function linhaEstado(rotulo, valor, nivel, dica) {
  return h("div", { class: "tec-linha", title: dica || null }, h("span", { class: `pt ${nivel || ""}`, "aria-hidden": "true" }),
    h("span", { class: "tec-rot" }, rotulo), h("span", { class: "tec-val" }, valor));
}

function secaoSistema() {
  if (!saude) return blocoTec("Sistema", h("p", { class: "nota" }, "API fora do ar: a interface não recebe o estado do servidor."));
  const llm = saude.llm || {};
  const asr = saude.asr || {};
  const fer = saude.ferramentas || {};
  const vozTxt = !asr.disponivel ? "desligada (digite)" : asr.carregado ? `${asr.dispositivo === "cuda" ? "GPU" : "CPU"} (Whisper)` : "carrega no 1º uso";
  const nivelLlm = !llm.disponivel ? "erro" : llm.substituicoes ? "alerta" : "ok";
  return blocoTec("Sistema",
    linhaEstado("Modelo de linguagem", `${llm.tipo || "?"}${llm.modelo ? ` · ${llm.modelo}` : ""}`, nivelLlm,
      llm.disponivel ? "modelo disponível" : "indisponível: o agente segue o plano mínimo determinístico"),
    llm.tipo === "replay" ? linhaEstado("Fora da gravação", `${llm.substituicoes || 0} requisição(ões)`, llm.substituicoes ? "alerta" : "ok",
      "requisições sem gravação exata (0 = reprodução fiel da demo gravada)") : null,
    linhaEstado("Voz (transcrição)", vozTxt, asr.disponivel ? (asr.carregado ? "ok" : "alerta") : "", asr.erro_gpu ? `GPU: ${asr.erro_gpu}` : ""),
    linhaEstado("Ferramentas", fer.modo || "?", fer.modo === "reais" ? "ok" : "alerta",
      fer.falsas?.length ? `simuladas: ${fer.falsas.join(", ")}` : "todas reais"),
    fer.falsas?.length ? h("p", { class: "nota" }, `Simuladas nesta execução: ${fer.falsas.join(", ")} (resultado marcado “simulada”).`) : null,
    h("p", { class: "nota mono" }, `${saude.versao || ""}${saude.config?.perfil ? ` · perfil ${saude.config.perfil}` : ""}`));
}

async function carregarSaude() {
  try { saude = await api.saude(); } catch (e) { saude = null; }
  const est = document.getElementById("estado-api");
  const ponto = document.getElementById("ponto-tec");
  if (!saude) {
    est.hidden = false;
    est.textContent = "Sem conexão com o servidor";
    ponto.className = "ponto-tec erro";
    definirAvisosModo([]);
    secaoTecnica("sistema", secaoSistema);
    return;
  }
  est.hidden = true;
  const llm = saude.llm || {};
  const fer = saude.ferramentas || {};
  ponto.className = `ponto-tec ${!llm.disponivel ? "erro" : (llm.substituicoes || fer.falsas?.length) ? "alerta" : "ok"}`;
  const avisos = [];
  if (llm.tipo === "replay") {
    avisos.push({ curto: "Contingência: respostas do modelo reproduzidas de uma gravação",
      longo: "Contingência: as respostas do modelo de linguagem vêm de uma gravação real deste caso (sem GPU nem rede). Contagem do vídeo, regras, política e selo rodam de verdade.",
      dica: `${llm.substituicoes || 0} requisição(ões) fora da gravação` });
  }
  if (llm.tipo === "roteiro") avisos.push({ curto: "agente em roteiro fixo (testes)", longo: "Modo sem modelo: o agente segue um roteiro fixo (para testes)." });
  if (fer.falsas?.length) {
    avisos.push({ curto: `${fer.falsas.length} ferramenta(s) simulada(s)`, dica: fer.falsas.join(", "),
      longo: `Ferramentas simuladas nesta execução: ${fer.falsas.join(", ")} (resultado marcado “simulada”).` });
  }
  definirAvisosModo(avisos);
  secaoTecnica("sistema", secaoSistema);
}

function marcarNav(rota) {
  document.querySelectorAll(".nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.rota === rota ? "page" : "false"));
}

async function rotear() {
  const [caminho, consulta] = (location.hash || "#/carteira").replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(consulta || "");
  const [tela, id, sub] = caminho.split("/").filter(Boolean);
  if (tela !== "fis" || sub === "laudo") sairFiscalizacao();
  definirDemo(null); // a fiscalização ou o laudo de uma operação sintética repõe a faixa e o selo
  secaoTecnica("fis", null);
  secaoTecnica("laudo", null);
  document.body.dataset.tela = tela === "fis" ? (sub === "laudo" ? "laudo" : "fis") : "carteira";
  if (tela === "fis" && id && sub === "laudo") {
    marcarNav("laudo");
    const focar = sessionStorage.getItem("lv.focarAssinatura") === "1";
    sessionStorage.removeItem("lv.focarAssinatura");
    await telaLaudo(raiz, decodeURIComponent(id), { focarAssinatura: focar, abrirPacote: params.get("pacote") === "1" });
    document.title = "Laudo — Laudo Vivo";
  } else if (tela === "fis" && id) {
    marcarNav("fis");
    await telaFiscalizacao(raiz, decodeURIComponent(id), { saude, irLaudo, campo: params.get("campo") });
    document.title = "Fiscalização — Laudo Vivo";
  } else {
    marcarNav("carteira");
    await telaCarteira(raiz, { abrirFis: (fid) => { location.hash = `#/fis/${encodeURIComponent(fid)}`; } });
    document.title = "Carteira — Laudo Vivo";
  }
  raiz.focus({ preventScroll: true });
}

function irLaudo(fid, focarAssinatura = false) {
  if (focarAssinatura) sessionStorage.setItem("lv.focarAssinatura", "1");
  location.hash = `#/fis/${encodeURIComponent(fid)}/laudo`;
}

// Altura real do cabeçalho (faixa + topo): a fiscalização ocupa o resto da tela em qualquer resolução.
function medirTopo() {
  const c = document.getElementById("cabecalho");
  document.documentElement.style.setProperty("--topo-h", `${c?.offsetHeight || 0}px`);
}

function lerApresentacao() {
  const url = new URLSearchParams(location.search).get("apresentacao");
  if (url === "1" || url === "0") {
    try { localStorage.setItem("lv.apresentacao", url); } catch { /* armazenamento indisponível */ }
    return url === "1";
  }
  try { return localStorage.getItem("lv.apresentacao") === "1"; } catch { return false; }
}

function aplicarApresentacao(ligado) {
  document.body.classList.toggle("apresentacao", ligado);
  document.documentElement.classList.toggle("apresentacao", ligado);
  const b = document.getElementById("btn-apresentacao");
  if (b) {
    // ligado, o botão diz como sair (antes só ganhava uma borda e continuava "Modo apresentação")
    b.setAttribute("aria-pressed", ligado ? "true" : "false");
    b.title = ligado ? "Sair do modo apresentação (volta ao tamanho normal)" : "Modo apresentação (telão): fonte maior, conversa em destaque";
    const rot = b.querySelector(".rot");
    if (rot) rot.textContent = ligado ? "Sair da apresentação" : "Modo apresentação";
  }
  try { localStorage.setItem("lv.apresentacao", ligado ? "1" : "0"); } catch { /* */ }
  setTimeout(medirTopo, 0);
  window.dispatchEvent(new Event("lv:layout"));
}

// O mapa e o celular mudam de tamanho de ícone conforme a largura: a fiscalização re-renderiza as abas.
window.matchMedia?.("(max-width: 767px)").addEventListener?.("change", () => window.dispatchEvent(new Event("lv:layout")));

iniciarModal();
aplicarApresentacao(lerApresentacao());
document.getElementById("btn-apresentacao")?.addEventListener("click",
  () => aplicarApresentacao(!document.body.classList.contains("apresentacao")));
document.getElementById("btn-tecnico")?.addEventListener("click", () => abrirTecnico());
document.querySelector("[data-fechar-tec]")?.addEventListener("click", () => abrirTecnico(false));
// Esc fecha primeiro a gaveta técnica (a tela da fiscalização usa o Esc para a gaveta da prova)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && tecnicoAberto() && !document.getElementById("modal").open) {
    e.stopImmediatePropagation();
    abrirTecnico(false);
  }
}, true);
if ("ResizeObserver" in window) new ResizeObserver(medirTopo).observe(document.getElementById("cabecalho"));
window.addEventListener("hashchange", rotear);
window.addEventListener("resize", medirTopo);
window.addEventListener("lv:topo", () => setTimeout(medirTopo, 0));
window.addEventListener("lv:saude", carregarSaude); // depois de cada turno, ao abrir e ao recomeçar a demo (L34)
medirTopo();
carregarSaude().then(rotear);
setInterval(carregarSaude, 30000);
