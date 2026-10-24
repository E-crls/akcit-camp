// Aceite do modo apresentação (interface v4, identidade "Esquadro"): a fiscalização e o laudo em 1920×1080, 1366×768 e 1280×720.
// Confere, em cada tamanho: a conversa com pelo menos 40% da largura; sem rolagem horizontal; a barra da demonstração
// sem cobrir as colunas que ficam sobre ela; pelo menos 5 linhas da lista do laudo (#col-itens .item) à vista, sem
// linha cortada à direita e com o apoio em até 2 linhas; texto no piso (20 px em 1920×1080, 15 px em 1366/1280; a hora e
// a marca da demonstração são exceção declarada, .ok-pequeno); alvos de 40 px (na base); um só botão principal (ipê) fora
// da barra da demonstração; uma só marca de demonstração; nenhum termo técnico no caminho principal. Salva as capturas.
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

// Roda na página: as medidas da tela atual.
function medir() {
  const vis = (e) => {
    if (!e || !e.isConnected) return false;
    const b = e.getBoundingClientRect();
    if (b.width < 1 || b.height < 1 || b.bottom <= 0 || b.top >= innerHeight || b.right <= 0 || b.left >= innerWidth) return false;
    for (let x = e; x; x = x.parentElement) {
      const s = getComputedStyle(x);
      if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
    }
    return true;
  };
  const caixa = (sel) => { const e = document.querySelector(sel); if (!vis(e)) return null; const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, w: b.width }; };
  const esc = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16;
  const piso = (innerWidth >= 1900 ? 20 : 15) - 0.06;
  const alvoMin = 39.5 * esc;
  const barra = caixa(".roteiro .roteiro-barra") || caixa(".roteiro");
  const conversa = caixa("#col-conversa");
  // a barra fica abaixo da conversa, na mesma coluna: só conta coluna que se sobrepõe a ela na horizontal
  const cols = ["#col-conversa", "#col-itens"].map(caixa).filter(Boolean);
  const cobre = barra ? Math.max(0, ...cols.filter((c) => c.left < barra.right && c.right > barra.left).map((c) => Math.round(c.bottom - barra.top))) : 0;
  const corpo = document.querySelector("#col-itens .painel-corpo")?.getBoundingClientRect();
  const itens = [...document.querySelectorAll("#col-itens .item")];
  const aVista = corpo ? itens.filter((i) => { const b = i.getBoundingClientRect(); return b.height > 0 && b.top >= corpo.top - 1 && b.bottom <= corpo.bottom + 1; }).length : 0;
  const cortadas = itens.filter((i) => vis(i) && i.scrollWidth > i.clientWidth + 1).map((i) => i.textContent.trim().slice(0, 30));
  const apoio = [...document.querySelectorAll("#col-itens .item-estado")].filter(vis).map((m) => {
    const lh = parseFloat(getComputedStyle(m).lineHeight) || 20; return Math.round(m.getBoundingClientRect().height / lh);
  });
  const fora = "#tecnico, #col-prova, #modal, .roteiro, .leaflet-container, svg, .ok-pequeno, .so-leitor";
  const pequenos = [];
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest(fora) || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) || !vis(el)) continue;
    const f = parseFloat(getComputedStyle(el).fontSize);
    if (f < piso) pequenos.push(`${f.toFixed(1)} px: ${el.textContent.trim().slice(0, 30)}`);
  }
  const alvos = [];
  for (const el of document.querySelectorAll("button, a, input, [role=button], label.toque")) {
    if (el.closest("#tecnico, #col-prova, #modal, .roteiro, .leaflet-container, .ok-alvo") || el.classList.contains("ok-alvo") || el.type === "file" || !vis(el)) continue;
    const b = el.getBoundingClientRect();
    if (b.height < alvoMin) alvos.push(`${Math.round(b.width)}x${Math.round(b.height)}: ${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)}`);
  }
  // termos técnicos (R3) fora de Detalhes, da prova, do modal, da barra da demonstração e das falas (da fiscal e do agente)
  const textos = [];
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    const p = n.parentElement;
    if (!p || p.closest("#tecnico, #col-prova, #modal, .msg .fala, .roteiro, .so-leitor, script, style, #sprite") || !n.textContent.trim() || !vis(p)) continue;
    textos.push(n.textContent);
  }
  const R3 = /POL-\d|sha256|VLM|NDVI|fis_demo|nome_ref|fiscal-demo|hash raiz|XML|gleba|replay|span|\bMCR\b/g;
  const de = document.documentElement;
  return {
    apresentacao: document.body.classList.contains("apresentacao"), raiz_px: Math.round(esc * 16 * 100) / 100,
    fracao_conversa: conversa ? conversa.w / innerWidth : 0,
    itens: itens.length, itens_a_vista: aVista, itens_cortados: cortadas.slice(0, 4), apoio_linhas_max: Math.max(0, ...apoio),
    barra_cobre_px: cobre, overflow_x: de.scrollWidth > de.clientWidth + 1,
    pequenos: pequenos.slice(0, 5), alvos: alvos.slice(0, 5),
    verdes: [...document.querySelectorAll(".btn-pri")].filter((e) => vis(e) && !e.closest(".roteiro")).map((e) => e.textContent.trim()),
    marcas_demo: [...document.querySelectorAll(".marca-demo")].filter(vis).length,
    termos: [...new Set((textos.join(" ").match(R3) || []))],
    topo_px: Math.round(document.querySelector(".topo").getBoundingClientRect().height),
  };
}

(async () => {
  const { chromium } = carregarPlaywright();
  fs.mkdirSync(SAIDA, { recursive: true });
  let browser;
  for (const channel of ["msedge", "chrome"]) {
    try { browser = await chromium.launch({ channel, headless: true }); break; } catch { /* outro navegador */ }
  }
  if (!browser) { console.error("nem Edge nem Chrome disponíveis para o playwright"); process.exit(2); }
  const falhas = [];
  const medidas = [];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: "pt-BR" });
    const page = await ctx.newPage();
    const erros = [];
    page.on("pageerror", (e) => erros.push(e.message));
    await page.goto(`${BASE}/?apresentacao=1#/carteira`);
    // o caso de demonstração vem selecionado, com o balão aberto: o botão cheio é "Abrir fiscalização"
    await page.locator('.balao-op[data-caso="DEMO-0001"] button.btn-pri').first().click();
    await page.waitForSelector(".roteiro:not([hidden])", { state: "attached" });
    for (let i = 0; i < PASSOS; i++) {
      const sig = await page.evaluate(() => document.querySelector(".roteiro .pos")?.textContent + document.querySelector(".roteiro .titulo")?.textContent);
      const botao = page.locator(".roteiro button.btn-pri");
      if (!(await botao.count())) break;
      await botao.click();
      await page.mouse.move(4, 400);
      await page.waitForFunction((s) => !document.getElementById("pensando") &&
        (document.querySelector(".roteiro .pos")?.textContent + document.querySelector(".roteiro .titulo")?.textContent) !== s,
      sig, { timeout: 180000 });
    }
    await page.waitForTimeout(3500); // o realce da guarda (3 s) já passou
    for (const [w, hgt] of TAMANHOS) {
      await page.setViewportSize({ width: w, height: hgt });
      await page.waitForTimeout(600);
      const m = await page.evaluate(medir);
      medidas.push({ tela: "fiscalizacao", w, h: hgt, ...m });
      const tag = `${w}x${hgt}`;
      if (!m.apresentacao) falhas.push(`${tag}: modo apresentação desligado`);
      if (m.fracao_conversa < 0.4) falhas.push(`${tag}: conversa com ${(100 * m.fracao_conversa).toFixed(0)}% da largura (< 40%)`);
      if (m.overflow_x) falhas.push(`${tag}: rolagem horizontal`);
      if (m.barra_cobre_px > 2) falhas.push(`${tag}: a barra da demonstração cobre ${m.barra_cobre_px} px das colunas`);
      if (m.itens && m.itens_a_vista < Math.min(5, m.itens)) falhas.push(`${tag}: só ${m.itens_a_vista} linha(s) da lista do laudo à vista`);
      if (m.itens_cortados.length) falhas.push(`${tag}: linha da lista cortada à direita (${m.itens_cortados.join(" | ")})`);
      if (m.apoio_linhas_max > 2) falhas.push(`${tag}: apoio de uma linha da lista com ${m.apoio_linhas_max} linhas (> 2)`);
      if (m.pequenos.length) falhas.push(`${tag}: texto abaixo do piso (${m.pequenos.join(" | ")})`);
      if (m.alvos.length) falhas.push(`${tag}: alvo abaixo de 40 px (${m.alvos.join(" | ")})`);
      if (m.verdes.length !== 1) falhas.push(`${tag}: ${m.verdes.length} botões principais (ipê) (${m.verdes.join(" | ")})`);
      if (m.marcas_demo !== 1) falhas.push(`${tag}: ${m.marcas_demo} marcas de demonstração à vista`);
      if (m.termos.length) falhas.push(`${tag}: termos técnicos no caminho principal (${m.termos.join(", ")})`);
      console.log(`${tag}: raiz ${m.raiz_px} px · conversa ${(100 * m.fracao_conversa).toFixed(0)}% · lista ${m.itens_a_vista}/${m.itens} à vista · ` +
        `barra cobre ${m.barra_cobre_px} px · ovX ${m.overflow_x} · principais ${m.verdes.length} · marcas ${m.marcas_demo} · topo ${m.topo_px} px`);
      await page.screenshot({ path: path.join(SAIDA, `fis_${tag}.png`) });
    }
    // prova do item na gaveta ("Ver prova" da lista do laudo) e o laudo
    await page.setViewportSize({ width: 1366, height: 768 });
    const ver = page.locator("#col-itens .item[data-campo] .ver-prova").first();
    if (await ver.count()) {
      await ver.click();
      await page.waitForTimeout(500);
      const aberta = await page.evaluate(() => document.querySelector(".fis").classList.contains("prova-aberta"));
      if (!aberta) falhas.push("1366x768: a prova do item não abriu na gaveta");
      await page.screenshot({ path: path.join(SAIDA, "fis_prova_1366x768.png") });
      await page.keyboard.press("Escape");
    } else falhas.push("1366x768: nenhuma linha com \"Ver prova\" na lista do laudo");
    const fis = await page.evaluate(() => location.hash.split("/")[2]);
    for (const [w, hgt] of TAMANHOS) {
      await page.setViewportSize({ width: w, height: hgt });
      await page.goto(`${BASE}/#/fis/${fis}/laudo`);
      await page.waitForSelector(".laudo-tela");
      await page.waitForTimeout(500);
      const ov = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      if (ov) falhas.push(`laudo ${w}x${hgt}: rolagem horizontal`);
      await page.screenshot({ path: path.join(SAIDA, `laudo_${w}x${hgt}.png`), fullPage: false });
    }
    if (erros.length) falhas.push(`erros na página: ${[...new Set(erros)].join(" | ")}`);
    await ctx.close();
  } finally {
    fs.writeFileSync(path.join(SAIDA, "medidas.json"), JSON.stringify({ medidas, falhas }, null, 1));
    await browser.close();
  }
  if (falhas.length) { console.error(`FALHOU:\n- ${falhas.join("\n- ")}`); process.exit(1); }
  console.log(`aceite ok: capturas em ${SAIDA}`);
})().catch((e) => { console.error("ERRO", e); process.exit(1); });
