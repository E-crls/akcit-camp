// Imprime em PDF um HTML local (o laudo selado de exemplo) com o Microsoft Edge instalado na máquina,
// via playwright-core (canal "msedge", headless). Não baixa navegador nem pacote: usa o playwright-core que já
// existe em outra pasta, indicada por NODE_PATH.
//
// Uso (Git Bash, na raiz do repositório):
//   NODE_PATH=../../personas-ux/app/node_modules node docs/exemplos/gerar_pdf.cjs \
//       docs/exemplos/laudo_selado.html docs/exemplos/laudo_selado.pdf
// (normalmente chamado por docs/exemplos/gerar_exemplo.sh, que já define o NODE_PATH)
//
// O PDF é só uma visão impressa do HTML: o que vale como prova é o JSON selado (laudo.audit.selo confere o
// JSON e o HTML; o PDF não entra no hash raiz). Antes de imprimir, os links relativos do laudo (evidências e
// trace, que apontam para a pasta de dados da instalação) viram texto sem link, para o PDF não carregar o
// caminho desta máquina. O rodapé de cada página repete a marca "DEMONSTRAÇÃO — dados sintéticos".
// Só para a impressão, o script acrescenta CSS de diagramação (CSS_IMPRESSAO): o carimbo "SELADO · ASSINADO"
// desce para fora da faixa de demonstração, texto longo sem espaço (o pseudônimo hmac:…, ids) quebra na margem
// e a marca d'água diagonal cabe na página. O texto é o do HTML selado; nada é escrito no HTML.
// O Edge roda sem GPU (--disable-gpu): a GPU da máquina fica para o Ollama.
"use strict";

const path = require("path");
const fs = require("fs");
const { pathToFileURL } = require("url");

let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (e) {
  console.error(
    "playwright-core não encontrado. Defina NODE_PATH para uma pasta node_modules que o tenha " +
      "(ex.: NODE_PATH=../../personas-ux/app/node_modules)."
  );
  process.exit(2);
}

const RODAPE =
  '<div style="font:9.5px Segoe UI,system-ui,sans-serif;width:100%;padding:0 12mm;color:#444;' +
  'display:flex;justify-content:space-between">' +
  "<span>DEMONSTRAÇÃO — dados sintéticos · operação fictícia · laudo selado de exemplo</span>" +
  '<span>página <span class="pageNumber"></span> de <span class="totalPages"></span></span></div>';

// Diagramação só da impressão (o template do laudo é de src/ e não muda aqui).
const CSS_IMPRESSAO = `
@media print {
  main { padding-top: 34px !important; }
  .marca { top: 0 !important; right: 8mm !important; }
  dl.grade dd, code, .mono { overflow-wrap: anywhere; word-break: break-word; }
  .marca-dagua span { font-size: 46px !important; }
}`;

async function main() {
  const [entrada, saida] = process.argv.slice(2);
  if (!entrada || !saida) {
    console.error("uso: node gerar_pdf.cjs entrada.html saida.pdf");
    process.exit(2);
  }
  if (!fs.existsSync(entrada)) {
    console.error(`não existe: ${entrada}`);
    process.exit(2);
  }
  const navegador = await chromium.launch({ channel: "msedge", headless: true, args: ["--disable-gpu"] });
  try {
    const pagina = await navegador.newPage();
    await pagina.goto(pathToFileURL(path.resolve(entrada)).href, { waitUntil: "load" });
    const semLink = await pagina.evaluate(() => {
      let n = 0;
      for (const a of document.querySelectorAll("a[href]")) {
        const h = a.getAttribute("href") || "";
        if (!/^https?:\/\//i.test(h)) {
          a.removeAttribute("href");
          n += 1;
        }
      }
      return n;
    });
    await pagina.addStyleTag({ content: CSS_IMPRESSAO });
    await pagina.emulateMedia({ media: "print" });
    await pagina.pdf({
      path: saida,
      format: "A4",
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: "<span></span>",
      footerTemplate: RODAPE,
      margin: { top: "12mm", bottom: "14mm", left: "10mm", right: "10mm" },
    });
    const kib = Math.round(fs.statSync(saida).size / 1024);
    console.log(`PDF: ${saida} (${kib} KiB; ${semLink} link(s) relativo(s) virou(viraram) texto)`);
  } finally {
    await navegador.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
