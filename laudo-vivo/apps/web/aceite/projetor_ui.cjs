// Aceite do modo apresentação (L21/L36): a fiscalização e o laudo em 1920×1080, 1366×768 e 1280×720.
// Confere, em cada tamanho, que a conversa tem pelo menos 40% da largura, que não há rolagem horizontal, que a barra do
// roteiro não cobre as colunas, que a matriz mostra linhas sem cortar coluna à direita (a "Regra" inteira à vista) e
// que o motivo cabe em 2 linhas; salva as capturas.
//
// Uso (com a API no ar; o padrão é http://127.0.0.1:8000):
//   node apps/web/aceite/projetor_ui.cjs [--base URL] [--passos N] [--saida DIR] [--playwright DIR]
// O playwright-core vem de --playwright, de PLAYWRIGHT_CORE_DIR ou do node_modules da pasta atual; o navegador é o
// Edge (ou o Chrome) instalado (channel "msedge"/"chrome"), sem baixar nada. Sai com código 1 se algum critério falhar.
"use strict";
const fs = require("fs");
const path = require("path");

const arg = (nome, padrao) => {
  const i = process.argv.indexOf(`--${nome}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : padrao;
};
const BASE = arg("base", "http://127.0.0.1:8000").replace(/\/$/, "");
const PASSOS = Number(arg("passos", "17")); // até o envio para assinatura: o laudo (rascunho) já existe
const SAIDA = path.resolve(arg("saida", path.join(__dirname, "..", "..", "..", "dados_locais", "aceite", "projetor")));
const TAMANHOS = [[1920, 1080], [1366, 768], [1280, 720]];

function carregarPlaywright() {
  const dirs = [arg("playwright", ""), process.env.PLAYWRIGHT_CORE_DIR || "", process.cwd()].filter(Boolean);
  for (const d of dirs) {
    try { return require(require.resolve("playwright-core", { paths: [d] })); } catch { /* tenta o próximo */ }
  }
  console.error("playwright-core não encontrado: use --playwright <pasta com node_modules> ou PLAYWRIGHT_CORE_DIR");
  process.exit(2);
}

async function medir(page) {
  return page.evaluate(() => {
    const r = (sel) => { const e = document.querySelector(sel); if (!e || !e.offsetParent && getComputedStyle(e).position !== "fixed") return null;
      const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: b.width, h: b.height }; };
    const barra = r(".roteiro");
    const conversa = r("#col-conversa");
    const wrap = document.querySelector(".matriz-wrap")?.getBoundingClientRect();
    const linhas = [...document.querySelectorAll("table.matriz tbody tr")];
    const visiveis = wrap ? linhas.filter((tr) => { const b = tr.getBoundingClientRect(); return b.top >= wrap.top - 1 && b.bottom <= wrap.bottom + 1; }).length : 0;
    const cols = ["#col-conversa", "#col-itens"].map(r).filter(Boolean);
    const cobre = barra ? Math.max(0, ...cols.map((c) => Math.round(c.bottom - barra.top))) : 0;
    const motivos = [...document.querySelectorAll("table.matriz .motivo")].map((m) => {
      const lh = parseFloat(getComputedStyle(m).lineHeight) || 18; return Math.round(m.getBoundingClientRect().height / lh);
    });
    const wrapEl = document.querySelector(".matriz-wrap");
    const card = document.querySelector("#col-itens")?.getBoundingClientRect();
    // a matriz não pode passar da borda do cartão (rolagem horizontal escondida na matriz cortava a "Regra")
    const dir = Math.min(wrap ? wrap.right : Infinity, card ? card.right : Infinity);
    const cortadas = [...document.querySelectorAll("table.matriz thead th, table.matriz tbody td")]
      .filter((c) => c.offsetParent && getComputedStyle(c).display !== "none")
      .filter((c) => c.getBoundingClientRect().right > dir + 1 || c.scrollWidth > c.clientWidth + 1)
      .map((c) => c.textContent.trim().slice(0, 30));
    const de = document.documentElement;
    return {
      apresentacao: document.body.classList.contains("apresentacao"),
      fracao_conversa: conversa ? conversa.w / innerWidth : 0,
      linhas_matriz: linhas.length, linhas_visiveis: visiveis, barra_cobre_px: cobre,
      overflow_x: de.scrollWidth > de.clientWidth + 1, linhas_motivo_max: Math.max(0, ...motivos),
      matriz_corta_px: wrapEl ? Math.max(0, wrapEl.scrollWidth - wrapEl.clientWidth) : 0,
      celulas_cortadas: [...new Set(cortadas)].slice(0, 6),
      topo_px: Math.round(document.querySelector(".topo").getBoundingClientRect().height),
    };
  });
}

(async () => {
  const { chromium } = carregarPlaywright();
  fs.mkdirSync(SAIDA, { recursive: true });
  let browser;
  for (const channel of ["msedge", "chrome"]) {
    try { browser = await chromium.launch({ channel, headless: true }); break; } catch { /* outro navegador */ }
  }
  if (!browser) { console.error("nem Edge nem Chrome disponíveis para o playwright"); process.exit(2); }
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: "pt-BR" });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/?apresentacao=1#/carteira`);
  await page.locator(".casos-demo button.btn-pri").first().click(); // só o caso padrão tem o botão primário (L56)
  await page.waitForSelector(".roteiro:not([hidden])", { state: "attached" });
  for (let i = 0; i < PASSOS; i++) {
    const sig = await page.evaluate(() => document.querySelector(".roteiro .pos")?.textContent + document.querySelector(".roteiro .titulo")?.textContent);
    const botao = page.locator(".roteiro button.btn-pri");
    if (!(await botao.count())) break;
    await botao.click();
    await page.waitForFunction((s) => !document.getElementById("pensando") &&
      (document.querySelector(".roteiro .pos")?.textContent + document.querySelector(".roteiro .titulo")?.textContent) !== s,
    sig, { timeout: 180000 });
  }
  await page.waitForTimeout(600);
  const falhas = [];
  const medidas = [];
  for (const [w, hgt] of TAMANHOS) {
    await page.setViewportSize({ width: w, height: hgt });
    await page.waitForTimeout(500);
    const m = await medir(page);
    medidas.push({ tela: "fiscalizacao", w, h: hgt, ...m });
    const tag = `${w}x${hgt}`;
    if (!m.apresentacao) falhas.push(`${tag}: modo apresentação desligado`);
    if (m.fracao_conversa < 0.4) falhas.push(`${tag}: conversa com ${(100 * m.fracao_conversa).toFixed(0)}% da largura (< 40%)`);
    if (m.overflow_x) falhas.push(`${tag}: rolagem horizontal`);
    if (m.barra_cobre_px > 2) falhas.push(`${tag}: barra do roteiro cobre ${m.barra_cobre_px} px das colunas`);
    if (m.linhas_matriz && m.linhas_visiveis < Math.min(5, m.linhas_matriz)) falhas.push(`${tag}: só ${m.linhas_visiveis} linha(s) da matriz à vista`);
    if (m.linhas_motivo_max > 2) falhas.push(`${tag}: motivo com ${m.linhas_motivo_max} linhas (> 2)`);
    if (m.matriz_corta_px > 1 || m.celulas_cortadas.length) {
      falhas.push(`${tag}: matriz cortada à direita (${m.matriz_corta_px} px; ${m.celulas_cortadas.join(" | ")})`);
    }
    console.log(`${tag}: conversa ${(100 * m.fracao_conversa).toFixed(0)}% · matriz ${m.linhas_visiveis}/${m.linhas_matriz} à vista · ` +
      `barra cobre ${m.barra_cobre_px} px · ovX ${m.overflow_x} · matriz corta ${m.matriz_corta_px} px · ` +
      `motivo ≤ ${m.linhas_motivo_max} linha(s) · topo ${m.topo_px} px`);
    await page.screenshot({ path: path.join(SAIDA, `fis_${tag}.png`) });
  }
  // prova do item na gaveta (clique numa linha da matriz) e o laudo
  await page.setViewportSize({ width: 1366, height: 768 });
  const linha = page.locator("table.matriz tbody tr").first();
  if (await linha.count()) {
    await linha.click();
    await page.waitForTimeout(400);
    const aberta = await page.evaluate(() => document.querySelector(".fis").classList.contains("prova-aberta"));
    if (!aberta) falhas.push("1366x768: a prova do item não abriu na gaveta");
    await page.screenshot({ path: path.join(SAIDA, "fis_prova_1366x768.png") });
    await page.keyboard.press("Escape");
  }
  const fis = await page.evaluate(() => location.hash.split("/")[2]);
  for (const [w, hgt] of TAMANHOS) {
    await page.setViewportSize({ width: w, height: hgt });
    await page.goto(`${BASE}/#/fis/${fis}/laudo`);
    await page.waitForSelector(".laudo-cab");
    await page.waitForTimeout(400);
    const ov = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    if (ov) falhas.push(`laudo ${w}x${hgt}: rolagem horizontal`);
    await page.screenshot({ path: path.join(SAIDA, `laudo_${w}x${hgt}.png`), fullPage: false });
  }
  fs.writeFileSync(path.join(SAIDA, "medidas.json"), JSON.stringify({ medidas, falhas }, null, 1));
  await browser.close();
  if (falhas.length) { console.error(`FALHOU:\n- ${falhas.join("\n- ")}`); process.exit(1); }
  console.log(`aceite ok: capturas em ${SAIDA}`);
})().catch((e) => { console.error("ERRO", e); process.exit(1); });
