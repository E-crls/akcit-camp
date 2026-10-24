// Cliente da API do Laudo Vivo.

import { fmtDec, limitesPublicos, regraVideoPublico } from "./regras.js";

// Demonstração pública (Cloud Run): um pedido acima de 32 MiB, ou com a instância cheia, é barrado pelo front-end do
// Google com uma página HTML, sem o JSON do app; a tela mostraria só "erro 413". Com a demonstração pública ligada
// (app.js, pela saúde), esses códigos sem JSON viram uma frase em português. Fora dela, nada muda.
let PUBLICA = null; // os limites da demonstração pública (saúde → demo_publica.limites), ou null
export function definirDemoPublica(limites) { PUBLICA = limites ? { ...limites } : null; }

export function mensagemSemJson(status, limites = null) {
  if (status === 413) {
    return `Arquivo grande demais para a demonstração: o vídeo vai ${regraVideoPublico(limites)}, `
      + `a foto até ${fmtDec(limitesPublicos(limites).upload_mb.foto)} MB. Nada foi enviado.`;
  }
  if (status === 429) return "Muita gente usando a demonstração agora. Espere alguns segundos e tente de novo.";
  return null;
}

// O erro de uma resposta HTTP: a mensagem do app (o JSON `erro`, escrita para a tela) quando houver. `e.amigavel` diz que
// a mensagem pode ir para a tela como está (a do app, ou a frase da demonstração pública para a resposta sem JSON).
export function erroHttp(status, corpo, { detalhe = true } = {}) {
  const doApp = corpo && typeof corpo === "object" && typeof corpo.erro === "string" && corpo.erro ? corpo.erro : null;
  const semJson = !doApp && PUBLICA ? mensagemSemJson(status, PUBLICA) : null;
  const det = detalhe && corpo && typeof corpo === "object" && corpo.detail ? JSON.stringify(corpo.detail) : null;
  const msg = doApp || det || semJson || `erro ${status}`;
  const e = new Error(msg);
  e.status = status;
  e.corpo = corpo;
  e.amigavel = !!(doApp || semJson);
  return e;
}

async function tratar(r) {
  let corpo = null;
  const tipo = r.headers.get("content-type") || "";
  if (tipo.includes("application/json")) corpo = await r.json();
  else corpo = await r.text();
  if (!r.ok) throw erroHttp(r.status, corpo);
  return corpo;
}

// Sem rede (4G ruim no campo, servidor fora do ar), o fetch lança TypeError("Failed to fetch"): vira uma mensagem
// em português que diz o que aconteceu com o pedido. `e.rede = true` deixa a tela oferecer "Tentar de novo".
function erroRede(enviando) {
  const e = new Error(enviando ? "Sem conexão com o servidor. Nada foi enviado." : "Sem conexão com o servidor.");
  e.rede = true;
  return e;
}

async function buscar(url, opcoes, enviando) {
  let r;
  try { r = await fetch(url, opcoes); } catch { throw erroRede(enviando); }
  return tratar(r);
}

export async function get(url) {
  return buscar(url, { headers: { Accept: "application/json" } }, false);
}

export async function post(url, dados) {
  return buscar(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(dados ?? {}),
  }, true);
}

export async function postForm(url, form) {
  return buscar(url, { method: "POST", body: form }, true);
}

// Upload com progresso (vídeo grande no 4G do campo): XMLHttpRequest dá o evento de progresso.
export function postFormProgresso(url, form, aoProgresso) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.responseType = "json";
    x.upload.onprogress = (e) => { if (e.lengthComputable && aoProgresso) aoProgresso(e.loaded / e.total); };
    x.onload = () => {
      if (x.status >= 200 && x.status < 300) resolve(x.response);
      // responseType "json": a página HTML do front-end do Google (413 acima de 32 MiB) chega como null
      else reject(erroHttp(x.status, x.response, { detalhe: false }));
    };
    x.onerror = () => {
      const e = new Error("Sem conexão com o servidor. O arquivo não foi enviado.");
      e.rede = true;
      reject(e);
    };
    x.send(form);
  });
}

export const api = {
  saude: () => get("/api/saude"),
  carteira: (q) => get(`/api/carteira?${new URLSearchParams(q)}`),
  contornoGO: () => get("/api/mapa/contorno-go"),
  listar: () => get("/api/fiscalizacoes"),
  abrirCaso: (caso, reiniciar = true) => post("/api/fiscalizacoes", { caso, reiniciar }),
  abrirRef: (ref_bacen) => post("/api/fiscalizacoes", { ref_bacen }),
  estado: (id) => get(`/api/fiscalizacoes/${encodeURIComponent(id)}`),
  turno: (id, texto, residual = null) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/turno`,
    residual ? { texto: texto || "", residual } : { texto }),
  confirmar: (id, aceitar, texto) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/confirmar`, { aceitar, texto }),
  evidenciaCaso: (id, nome, texto = "") => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/evidencias/caso`, { nome, texto }),
  proximoPasso: (id) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/roteiro/proximo`, {}),
  rascunho: (id) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/rascunho`, {}),
  pularPasso: (id) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/roteiro/pular`, {}),
  assinar: (id, dados) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/assinar`, dados),
  laudo: (id) => get(`/api/fiscalizacoes/${encodeURIComponent(id)}/laudo`),
  // pacote de exibição BCB/Justiça: ação humana, só depois de SELADO (a API devolve 409 antes)
  pacote: (id) => post(`/api/fiscalizacoes/${encodeURIComponent(id)}/pacote`, {}),
  spans: (id, span) => get(`/api/fiscalizacoes/${encodeURIComponent(id)}/trace?span_id=${encodeURIComponent(span)}`),
  trecho: (url) => get(url),
};
