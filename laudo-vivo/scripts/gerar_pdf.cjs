#!/usr/bin/env node
/*
  Gera o PDF dos slides do pitch (docs/entregaveis/deck.pdf) a partir de docs/entregaveis/deck/index.html,
  com o Microsoft Edge instalado na máquina, via playwright-core (nada é baixado: usa o Edge do Windows).

  Uso (Git Bash, na raiz do repositório):
    node scripts/gerar_pdf.cjs                          # escreve docs/entregaveis/deck.pdf
    node scripts/gerar_pdf.cjs --png dados_locais/deck  # e uma PNG por tela, para conferir a olho
    node scripts/gerar_pdf.cjs --entrada outro.html --saida outro.pdf
    node scripts/gerar_pdf.cjs --forcar                 # grava o PDF mesmo com tela transbordando

  O playwright-core vem de PLAYWRIGHT_CORE_DIR (a pasta node_modules que o contém) ou, se não houver, de
  ../../personas-ux/app/node_modules; NODE_PATH também funciona:
    NODE_PATH=<pasta>/node_modules node scripts/gerar_pdf.cjs

  Os números do deck ficam entre marcadores <!--n:...-->: quando os relatórios mudam,
  `scripts/py.sh scripts/gerar_numeros.py --aplicar` os reescreve (o deck está nos ALVOS); rode este script
  de novo para o PDF ficar com os mesmos números e confira com
  `scripts/py.sh scripts/gerar_numeros.py --verificar`.

  Confere antes de gravar: imagens carregadas, nenhum pedido de rede, nenhuma tela transbordando 1920x1080
  (conteúdo invadindo o rodapé conta) e, só como aviso, se o slide da equipe ainda tem [[EQUIPE: ...]].
  Código de saída: 0 ok; 1 problema na conferência (o PDF não é gravado sem --forcar); 2 playwright-core,
  Edge ou arquivo de entrada indisponível.
*/
"use strict";

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const REPO = path.resolve(__dirname, "..");
const PW_PADRAO = path.resolve(REPO, "..", "..", "personas-ux", "app", "node_modules");
const LARGURA = 1920;
const ALTURA = 1080;

function argumentos(argv) {
  const a = {
    entrada: path.join(REPO, "docs", "entregaveis", "deck", "index.html"),
    saida: path.join(REPO, "docs", "entregaveis", "deck.pdf"),
    png: null,
    forcar: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--entrada") a.entrada = path.resolve(argv[++i]);
    else if (v === "--saida") a.saida = path.resolve(argv[++i]);
    else if (v === "--png") a.png = path.resolve(argv[++i]);
    else if (v === "--forcar") a.forcar = true;
    else if (v === "-h" || v === "--help") {
      console.log(fs.readFileSync(__filename, "utf8").split("*/")[0].replace(/^[\s\S]*?\/\*/, ""));
      process.exit(0);
    } else {
      console.error(`argumento desconhecido: ${v}`);
      process.exit(2);
    }
  }
  return a;
}

function carregarPlaywright() {
  const pasta = process.env.PLAYWRIGHT_CORE_DIR || PW_PADRAO;
  for (const t of ["playwright-core", path.join(pasta, "playwright-core")]) {
    try {
      return require(t);
    } catch (e) {
      /* tenta a próxima */
    }
  }
  console.error("playwright-core não encontrado: defina PLAYWRIGHT_CORE_DIR (a pasta node_modules que o "
    + `contém) ou NODE_PATH; o padrão é ${PW_PADRAO}`);
  process.exit(2);
}

// Roda no navegador: mede cada tela (com a mídia de impressão, todas aparecem uma embaixo da outra).
function medirTelas() {
  return Array.from(document.querySelectorAll(".slide")).map((el, k) => {
    const caixa = el.getBoundingClientRect();
    const rodape = el.querySelector(".rodape");
    const limite = rodape ? rodape.getBoundingClientRect().top : caixa.bottom;
    const fora = [];
    el.querySelectorAll("*").forEach((f) => {
      const r = f.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      const noCorpo = f.closest(".corpo") !== null;
      if (r.bottom > caixa.bottom + 1 || r.right > caixa.right + 1 || (noCorpo && r.bottom > limite + 1)) {
        fora.push(`${f.tagName.toLowerCase()}.${f.className || "-"}`);
      }
    });
    return {
      n: k + 1, id: el.id, w: Math.round(caixa.width), h: Math.round(caixa.height), fora: fora.slice(0, 5),
    };
  });
}

async function main() {
  const a = argumentos(process.argv.slice(2));
  if (!fs.existsSync(a.entrada)) {
    console.error(`não existe: ${a.entrada}`);
    process.exit(2);
  }
  const { chromium } = carregarPlaywright();
  let navegador;
  try {
    navegador = await chromium.launch({ channel: "msedge", headless: true });
  } catch (e) {
    console.error(`não consegui abrir o Edge (channel msedge): ${e.message.split("\n")[0]}`);
    process.exit(2);
  }
  let codigo = 0;
  try {
    const contexto = await navegador.newContext({
      viewport: { width: LARGURA, height: ALTURA }, deviceScaleFactor: 1,
    });
    const pagina = await contexto.newPage();
    const externas = [];
    pagina.on("request", (r) => {
      if (!r.url().startsWith("file:") && !r.url().startsWith("data:")) externas.push(r.url());
    });
    await pagina.goto(pathToFileURL(a.entrada).href, { waitUntil: "load" });
    await pagina.evaluate(() => document.fonts.ready);
    await pagina.emulateMedia({ media: "print" });

    const quebradas = await pagina.evaluate(() => Array.from(document.images)
      .filter((i) => !i.complete || i.naturalWidth === 0).map((i) => i.getAttribute("src")));
    const telas = await pagina.evaluate(medirTelas);
    const preencher = await pagina.evaluate(() => document.body.innerText.includes("[[EQUIPE:"));

    for (const t of telas) {
      const ok = t.w === LARGURA && t.h === ALTURA && t.fora.length === 0;
      console.log(`tela ${t.n} (${t.id}): ${t.w}x${t.h}${ok ? " ok" : ` TRANSBORDA: ${t.fora.join(", ")}`}`);
      if (!ok) codigo = 1;
    }
    if (quebradas.length) {
      console.error(`imagens que não carregaram: ${quebradas.join(", ")}`);
      codigo = 1;
    }
    if (externas.length) {
      console.error(`o deck pediu recursos de rede (tem de funcionar sem rede): ${externas.join(", ")}`);
      codigo = 1;
    }
    if (preencher) console.warn("AVISO: o slide da equipe ainda tem [[EQUIPE: ...]] (⚠ PREENCHER).");

    if (codigo === 0 || a.forcar) {
      fs.mkdirSync(path.dirname(a.saida), { recursive: true });
      await pagina.pdf({
        path: a.saida, width: `${LARGURA}px`, height: `${ALTURA}px`, printBackground: true,
        preferCSSPageSize: true, margin: { top: "0", right: "0", bottom: "0", left: "0" },
      });
      const rel = path.relative(REPO, a.saida).split(path.sep).join("/");
      console.log(`PDF: ${rel} (${telas.length} telas)`);
    } else {
      console.error("PDF não gravado: corrija o deck (ou use --forcar).");
    }

    if (a.png) {
      fs.mkdirSync(a.png, { recursive: true });
      const els = await pagina.$$(".slide");
      for (let k = 0; k < els.length; k++) {
        await els[k].screenshot({ path: path.join(a.png, `tela-${String(k + 1).padStart(2, "0")}.png`) });
      }
      console.log(`PNG por tela em ${a.png}`);
    }
    await contexto.close();
  } finally {
    await navegador.close();
  }
  process.exit(codigo);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
