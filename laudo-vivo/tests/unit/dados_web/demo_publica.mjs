// Testes das regras da interface na demonstração pública (apps/web/js/regras.js e api.js: funções puras, sem DOM).
// Rodado por tests/unit/test_web_demo_publica.py com o Node; o 1º argumento, opcional, é um JSON com os estados reais
// da demo pública ao longo do roteiro ({"estados": [...], "selado": {...}}), gravados pelo teste em Python.
// Uso direto: node tests/unit/dados_web/demo_publica.mjs [estados.json]
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const WEB = new URL("../../../apps/web/js/", import.meta.url);
const R = await import(new URL("regras.js", WEB));
const A = await import(new URL("api.js", WEB));
const MIB = 1024 * 1024;
let n = 0;
const teste = async (nome, fn) => {
  try { await fn(); n += 1; } catch (e) { e.message = `${nome}: ${e.message}`; throw e; }
};

// ------------------------------------------------------------------ P3: a câmera não é a ação principal fora do passo
const FILMAR = [{ rot: "Filmar", acao: "filmar", ic: "video" }, { rot: "Galeria", acao: "galeria-video", ic: "galeria" }];
const ACAO_ARQ = ["filmar", "galeria-video", "fotografar-nota", "arquivo-nfe", "fotografar-gta", "arquivo-gta", "fotografar-cerca", "refazer-foto", "galeria-foto"];
const TIPO_ACAO = { filmar: "video", "galeria-video": "video", "fotografar-nota": "documento", "arquivo-nfe": "nfe_xml", "fotografar-gta": "documento",
  "arquivo-gta": "gta", "fotografar-cerca": "foto", "refazer-foto": "foto", "galeria-foto": "foto" };
const COMPATIVEL = { video: ["video"], documento: ["documento"], nfe_xml: ["nfe_xml"], gta: ["gta", "documento"], foto: ["foto"] };

await teste("ações de arquivo", () => {
  for (const a of ACAO_ARQ) assert.ok(R.ehAcaoDeArquivo(a), a);
  for (const a of ["justificar:item:bov1:quantidade", "declarar", "perguntar:Como está o pasto?", "escrever:O prazo é ", "emitir", "anexar", "confirmar",
    "revisar-assinar", "executar-passo", "", null]) assert.ok(!R.ehAcaoDeArquivo(a), String(a));
});

await teste("passo sem arquivo: Executar passo vira a principal, Filmar e Galeria secundárias", () => {
  const out = R.acoesAgoraPublica(FILMAR, { n: 1, acao: "turno", fala: "Bom dia." });
  assert.deepEqual(out.map((a) => a.acao), ["executar-passo", "filmar", "galeria-video"]);
  assert.equal(out[0].rot, "Executar passo");
  assert.equal(FILMAR.length, 2); // não muda a lista de quem chamou
});

await teste("passo que pede o vídeo: Filmar continua a principal (abre o arquivo da demonstração)", () => {
  const passo = { n: 4, acao: "evidencia", evidencia: "s03_fila_colada.mp4" };
  assert.equal(R.acoesAgoraPublica(FILMAR, passo, { doPasso: (a) => TIPO_ACAO[a] === "video" }), FILMAR);
});

await teste("passo que pede outro arquivo: a câmera não fica principal", () => {
  const passo = { n: 8, acao: "evidencia", evidencia: "nfe_1.xml" };
  assert.equal(R.acoesAgoraPublica(FILMAR, passo, { doPasso: () => false })[0].acao, "executar-passo");
});

await teste("ação principal que não abre arquivo, roteiro no fim e passo da assinatura: nada muda", () => {
  const just = [{ rot: "Justificar", acao: "justificar:item:bov1:quantidade" }];
  assert.equal(R.acoesAgoraPublica(just, { n: 13, acao: "turno" }), just);
  assert.equal(R.acoesAgoraPublica(FILMAR, null), FILMAR);
  assert.equal(R.acoesAgoraPublica(FILMAR, { n: 18, acao: "assinar" }), FILMAR);
  assert.deepEqual(R.acoesAgoraPublica([], { n: 1, acao: "turno" }), []);
});

// ------------------------------------------------------------------ VA-04: tamanho e duração antes de enviar
await teste("limites padrão iguais aos da API e a dica do vídeo", () => {
  assert.deepEqual(R.limitesPublicos(), { upload_mb: { foto: 10, video: 30, nfe_xml: 2 }, video_max_s: 20 });
  assert.equal(R.regraVideoPublico(), "até 20 s e 30 MB");
  assert.equal(R.regraVideoPublico({ upload_mb: { video: 25 }, video_max_s: 15 }), "até 15 s e 25 MB");
});

await teste("vídeo acima de 30 MB é barrado com mensagem em português", () => {
  assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 36.4 * MIB }),
    "Vídeo de 36,4 MB: na demonstração, o vídeo vai até 20 s e 30 MB. Grave um trecho mais curto ou use o vídeo pronto do caso.");
  assert.match(R.conferirArquivoPublico({ tipo: "video", bytes: 30 * MIB + 1 }), /^Vídeo de 30,1 MB: /); // nunca "30 MB: até 30 MB"
  assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 30 * MIB }), null);
  assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 1.2 * MIB, duracao: 17.3 }), null);
});

await teste("vídeo acima de 20 s é barrado pela duração (com a folga de 0,5 s da API)", () => {
  assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 5 * MIB, duracao: 25.04 }),
    "Vídeo de 25 s: na demonstração, o vídeo vai até 20 s e 30 MB. Grave um trecho mais curto ou use o vídeo pronto do caso.");
  assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 5 * MIB, duracao: 20.4 }), null);
  for (const d of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) assert.equal(R.conferirArquivoPublico({ tipo: "video", bytes: 5 * MIB, duracao: d }), null, String(d));
});

await teste("foto acima de 10 MB e XML acima de 2 MB", () => {
  assert.equal(R.conferirArquivoPublico({ tipo: "foto", bytes: 12.7 * MIB }), "Foto de 12,7 MB: na demonstração, a foto vai até 10 MB.");
  assert.equal(R.conferirArquivoPublico({ tipo: "foto", bytes: 5.9 * MIB }), null);
  assert.equal(R.conferirArquivoPublico({ tipo: "nfe_xml", bytes: 3 * MIB }), "Arquivo de 3 MB: na demonstração, o XML da NF-e vai até 2 MB.");
});

await teste("os limites da saúde valem por cima dos padrões", () => {
  const lim = { upload_mb: { foto: 10, video: 25, nfe_xml: 2 }, video_max_s: 15 };
  assert.match(R.conferirArquivoPublico({ tipo: "video", bytes: 26 * MIB }, lim), /^Vídeo de 26 MB: na demonstração, o vídeo vai até 15 s e 25 MB\./);
  assert.match(R.conferirArquivoPublico({ tipo: "video", bytes: 1 * MIB, duracao: 16 }, lim), /^Vídeo de 16 s: /);
});

// ------------------------------------------------------------------ VA-04: 413/429 sem JSON e a mensagem do servidor
await teste("fora da demonstração pública, nada muda: 'erro 413'", () => {
  A.definirDemoPublica(null);
  const e = A.erroHttp(413, "<html>Request Entity Too Large</html>");
  assert.equal(e.message, "erro 413");
  assert.equal(e.status, 413);
  assert.equal(e.amigavel, false);
  assert.equal(A.erroHttp(422, { detail: [{ msg: "x" }] }).message, '[{"msg":"x"}]');
});

await teste("demonstração pública: 413 e 429 sem JSON viram frase em português", () => {
  A.definirDemoPublica({ upload_mb: { foto: 10, video: 30, nfe_xml: 2 }, video_max_s: 20 });
  const e = A.erroHttp(413, null);
  assert.equal(e.message, "Arquivo grande demais para a demonstração: o vídeo vai até 20 s e 30 MB, a foto até 10 MB. Nada foi enviado.");
  assert.ok(e.amigavel);
  assert.equal(A.erroHttp(429, "<html>Rate exceeded.</html>").message, "Muita gente usando a demonstração agora. Espere alguns segundos e tente de novo.");
  const outro = A.erroHttp(502, "<html>Bad Gateway</html>");
  assert.equal(outro.message, "erro 502");
  assert.equal(outro.amigavel, false);
  A.definirDemoPublica(null);
});

await teste("429 com JSON: a mensagem do servidor vai para a tela", () => {
  A.definirDemoPublica({});
  const msg = "Limite da demonstração: até 40 mensagens livres por visitante.";
  const e = A.erroHttp(429, { erro: msg });
  assert.equal(e.message, msg);
  assert.ok(e.amigavel);
  assert.equal(A.erroHttp(413, { erro: "Arquivo acima de 30 MB (vídeo)." }).message, "Arquivo acima de 30 MB (vídeo).");
  A.definirDemoPublica(null);
});

await teste("fetch: página HTML do 413 vira a frase (api.get)", async () => {
  const orig = globalThis.fetch;
  globalThis.fetch = async () => new Response("<html><title>413</title></html>", { status: 413, headers: { "content-type": "text/html; charset=UTF-8" } });
  try {
    A.definirDemoPublica({});
    await assert.rejects(A.get("/api/x"), (e) => e.status === 413 && e.amigavel && /^Arquivo grande demais para a demonstração/.test(e.message));
    globalThis.fetch = async () => new Response(JSON.stringify({ erro: "Voz ocupada: tente de novo em alguns segundos." }), { status: 429, headers: { "content-type": "application/json" } });
    await assert.rejects(A.postForm("/api/x", null), (e) => e.status === 429 && e.amigavel && e.message === "Voz ocupada: tente de novo em alguns segundos.");
    A.definirDemoPublica(null);
    globalThis.fetch = async () => new Response("<html></html>", { status: 413, headers: { "content-type": "text/html" } });
    await assert.rejects(A.get("/api/x"), (e) => e.message === "erro 413" && !e.amigavel);
  } finally { globalThis.fetch = orig; A.definirDemoPublica(null); }
});

await teste("upload com progresso (XMLHttpRequest): 413 sem JSON e 429 com JSON", async () => {
  class XHRFalso {
    constructor() { this.upload = {}; XHRFalso.ultimo = this; }
    open() {}
    send() { queueMicrotask(() => { this.status = XHRFalso.status; this.response = XHRFalso.resposta; this.onload(); }); }
  }
  globalThis.XMLHttpRequest = XHRFalso;
  try {
    A.definirDemoPublica({});
    XHRFalso.status = 413; XHRFalso.resposta = null; // responseType "json": a página HTML chega como null
    await assert.rejects(A.postFormProgresso("/api/x", null), (e) => e.status === 413 && e.amigavel && /vídeo vai até 20 s e 30 MB/.test(e.message));
    XHRFalso.status = 429; XHRFalso.resposta = { erro: "Limite da demonstração: até 12 arquivos por visitante." };
    await assert.rejects(A.postFormProgresso("/api/x", null), (e) => e.status === 429 && e.message === "Limite da demonstração: até 12 arquivos por visitante.");
    A.definirDemoPublica(null);
    XHRFalso.status = 413; XHRFalso.resposta = null;
    await assert.rejects(A.postFormProgresso("/api/x", null), (e) => e.message === "erro 413");
    XHRFalso.status = 422; XHRFalso.resposta = { detail: [{ msg: "x" }] };
    await assert.rejects(A.postFormProgresso("/api/x", null), (e) => e.message === "erro 422"); // como antes: sem o detalhe
  } finally { delete globalThis.XMLHttpRequest; A.definirDemoPublica(null); }
});

// ------------------------------------------------------------------ P5: passo do roteiro depois do selo
await teste("passo depois do selo", () => {
  assert.equal(R.passoDepoisDoSelo({ etapa: "SELADO", roteiro: { proximo: 19, total: 19 } }), 19);
  assert.equal(R.passoDepoisDoSelo({ etapa: "SELADO", roteiro: { proximo: 20, total: 19 } }), null);
  assert.equal(R.passoDepoisDoSelo({ etapa: "RASCUNHO", roteiro: { proximo: 18, total: 19 } }), null);
  assert.equal(R.passoDepoisDoSelo({ etapa: "SELADO" }), null);
  assert.equal(R.passoDepoisDoSelo(null), null);
});

// ------------------------------------------------------------------ estados reais da demo pública (do teste em Python)
if (process.argv[2]) {
  const { estados, selado, depois } = JSON.parse(readFileSync(process.argv[2], "utf8"));
  const passoDe = (e) => e.roteiro?.passos?.[e.roteiro.proximo - 1] || null;
  const arquivoDe = (e, p) => (p?.evidencia ? (e.roteiro.arquivos || []).find((a) => a.nome === p.evidencia) || null : null);
  let trocas = 0;
  await teste("estados reais: a câmera só é a principal quando o passo pede aquele arquivo", () => {
    assert.ok(estados.length >= 15, `${estados.length} estados`);
    for (const e of estados) {
      const p = passoDe(e);
      const arq = arquivoDe(e, p);
      const doPasso = (acao) => !!arq && (COMPATIVEL[TIPO_ACAO[acao]] || []).includes(arq.tipo);
      const a = R.agora(e, { papel: "fiscal" });
      const out = R.acoesAgoraPublica(a.acoes, p, { doPasso });
      if (out !== a.acoes) trocas += 1;
      const pri = out[0];
      if (pri && R.ehAcaoDeArquivo(pri.acao)) assert.ok(doPasso(pri.acao), `passo ${p?.n}: ${pri.acao} principal sem o arquivo do passo (${arq?.tipo || "nenhum"})`);
    }
    const p1 = estados[0];
    assert.equal(p1.roteiro.proximo, 1);
    const a1 = R.agora(p1, { papel: "fiscal" });
    if (R.ehAcaoDeArquivo(a1.acoes[0]?.acao)) assert.equal(R.acoesAgoraPublica(a1.acoes, passoDe(p1), { doPasso: () => false })[0].acao, "executar-passo");
    assert.ok(trocas >= 1, "nenhum estado trocou a ação principal: o teste ficou vazio");
  });
  await teste("estado real depois do selo: ainda há o passo 19; depois dele, nada", () => {
    assert.equal(selado.etapa, "SELADO");
    assert.equal(R.passoDepoisDoSelo(selado), selado.roteiro.total);
    assert.equal(R.passoDepoisDoSelo(depois), null);
  });
}

console.log(`ok ${n}`);
