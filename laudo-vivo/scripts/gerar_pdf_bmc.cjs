#!/usr/bin/env node
// Exporta o BMC (docs/entregaveis/bmc-v1.html) para PDF A4 paisagem com o Edge instalado na máquina, via
// playwright-core, e confere que coube em UMA página. Serve para qualquer HTML do repositório (argumentos).
//
// Uso (na raiz do laudo-vivo, Git Bash):
//   node scripts/gerar_pdf_bmc.cjs                       # bmc-v1.html -> bmc-v1.pdf, A4 paisagem, máx. 1 página
//   node scripts/gerar_pdf_bmc.cjs ENTRADA.html SAIDA.pdf [--retrato] [--max-paginas N]
//
// O playwright-core NÃO é dependência do repositório (o projeto não instala pacotes). O script procura o módulo,
// nesta ordem: na variável LV_PLAYWRIGHT_DIR (pasta que contém node_modules/playwright-core), no diretório
// atual, ao lado deste script e em ../../personas-ux/app. Alternativas:
//   NODE_PATH=<pasta>/node_modules node scripts/gerar_pdf_bmc.cjs
//   (cd <pasta> && node <caminho>/laudo-vivo/scripts/gerar_pdf_bmc.cjs)
//
// Os números do HTML ficam entre marcadores <!--n:...-->; rode primeiro
// `scripts/py.sh scripts/gerar_numeros.py --aplicar` (a avaliação final já faz isso) e depois este script,
// para o PDF sair com os números dos relatórios. Um navegador por vez; ele é sempre fechado no fim.
'use strict';

const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');
const { pathToFileURL } = require('url');

const REPO = path.resolve(__dirname, '..');

function carregarPlaywright() {
  const bases = [
    process.env.LV_PLAYWRIGHT_DIR,
    process.cwd(),
    __dirname,
    path.resolve(REPO, '..', '..', 'personas-ux', 'app'),
  ].filter(Boolean);
  for (const base of bases) {
    try {
      return createRequire(path.join(path.resolve(base), 'noop.js'))('playwright-core');
    } catch (_) {
      // tenta a próxima base
    }
  }
  try {
    return require('playwright-core'); // NODE_PATH
  } catch (_) {
    console.error('playwright-core não encontrado. Use LV_PLAYWRIGHT_DIR=<pasta com node_modules> ou NODE_PATH.');
    process.exit(2);
  }
}

function argumentos(argv) {
  const pos = [];
  const op = { paisagem: true, maxPaginas: 1 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--retrato') op.paisagem = false;
    else if (a === '--max-paginas') op.maxPaginas = Number(argv[++i]);
    else if (a === '-h' || a === '--help') {
      console.log(fs.readFileSync(__filename, 'utf8').split('\n').slice(1, 18).join('\n'));
      process.exit(0);
    } else pos.push(a);
  }
  op.entrada = path.resolve(pos[0] || path.join(REPO, 'docs', 'entregaveis', 'bmc-v1.html'));
  op.saida = path.resolve(pos[1] || op.entrada.replace(/\.html?$/i, '.pdf'));
  return op;
}

function contarPaginas(buf) {
  // conta os objetos /Type /Page (não /Pages) do PDF gerado pelo Chromium
  const m = buf.toString('latin1').match(/\/Type\s*\/Page(?![a-z])/g);
  return m ? m.length : 0;
}

async function main() {
  const op = argumentos(process.argv.slice(2));
  if (!fs.existsSync(op.entrada)) {
    console.error(`não existe: ${op.entrada}`);
    process.exit(2);
  }
  const { chromium } = carregarPlaywright();
  const navegador = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const pagina = await navegador.newPage();
    await pagina.emulateMedia({ media: 'print', colorScheme: 'light' });
    await pagina.goto(pathToFileURL(op.entrada).href, { waitUntil: 'load' });
    // conteúdo cortado: elemento com overflow escondido cujo conteúdo passa da caixa (o CSS de impressão do BMC
    // fixa a altura do grid para caber em 1 página; texto demais some sem aviso se não conferir aqui)
    const cortados = await pagina.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll('body, body *')) {
        const cs = getComputedStyle(el);
        const esconde = /hidden|clip/.test(cs.overflowY) || /hidden|clip/.test(cs.overflow);
        if (esconde && el.scrollHeight > el.clientHeight + 1) {
          const t = (el.querySelector('h2') || el).textContent.trim().replace(/\s+/g, ' ').slice(0, 40);
          out.push(`${el.tagName.toLowerCase()}.${el.className || '-'} "${t}" (+${el.scrollHeight - el.clientHeight}px)`);
        }
      }
      return out;
    });
    const buf = await pagina.pdf({
      path: op.saida,
      format: 'A4',
      landscape: op.paisagem,
      printBackground: true,
      preferCSSPageSize: true,
    });
    const n = contarPaginas(buf);
    const rel = path.relative(REPO, op.saida).split(path.sep).join('/');
    console.log(`PDF: ${rel} (${n} página(s), ${(buf.length / 1024).toFixed(0)} KB)`);
    for (const c of cortados) console.error(`ERRO: texto cortado em ${c}`);
    if (cortados.length) process.exitCode = 1;
    if (op.maxPaginas && n > op.maxPaginas) {
      console.error(`ERRO: ${n} páginas; o limite é ${op.maxPaginas}. Encurte o texto ou ajuste o CSS de impressão.`);
      process.exitCode = 1;
    }
  } finally {
    await navegador.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
