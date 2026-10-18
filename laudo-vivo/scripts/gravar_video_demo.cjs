#!/usr/bin/env node
/*
  Grava o vídeo da demo do Laudo Vivo (entregável 1 do edital, "demo gravada").

  O que faz, de ponta a ponta:
    1. sobe a interface em modo replay (`scripts/rodar_demo.sh --replay --sem-navegador`, numa porta
       livre): as respostas do modelo (conversa e leitura da foto do DANFE) vêm da gravação real do caso
       DEMO-0001; contagem do vídeo, regras, geofence, NDVI (do cache), política e selo rodam de verdade;
    2. conduz no Edge (playwright-core, channel "msedge", 1920x940) os 19 passos do
       `apps/web/ROTEIRO_DEMO.md`, com a assinatura humana (PIN), o pacote de exibição e uma pausa de
       leitura em cada passo, e grava com o `recordVideo` do Playwright;
    3. monta o .mp4 H.264 1920x1080 com o ffmpeg do sistema: tarja fixa no topo ("DEMONSTRAÇÃO — dados
       sintéticos · respostas do modelo reproduzidas de uma gravação real (replay)"), legenda curta de cada
       passo embaixo, cartão de abertura e cartão final com os créditos; esperas longas (a contagem do vídeo
       na CPU) são encurtadas, e a legenda diz isso;
    4. escreve as legendas (.srt e .vtt), os tempos (`tempos.json`) e o README da pasta de saída (roteiro por
       tempo, duração, sha256, créditos e como regravar), e encerra o servidor e o navegador.

  Uso (na raiz do laudo-vivo; Git Bash ou PowerShell):
    node scripts/gravar_video_demo.cjs
  Grava em tempo real (~3 min) e usa CPU (contagem do vídeo, codificação): rode com a máquina folgada.

  Opções:
    --base URL        usa uma API já no ar (ex.: http://127.0.0.1:8000, subida com `rodar_demo.sh --replay` e
                      ainda sem passos executados) em vez de subir uma
    --porta N         porta da API subida pelo script (padrão: a primeira livre a partir de 8790)
    --saida DIR       pasta do vídeo, das legendas e do README (padrão docs/entregaveis/video)
    --trabalho DIR    pasta dos intermediários: vídeo bruto, log do servidor (padrão dados_locais/video_demo)
    --ffmpeg EXE      ffmpeg do sistema (padrão: variável FFMPEG ou o ffmpeg do PATH)
    --playwright DIR  pasta com node_modules/playwright-core (padrão: PLAYWRIGHT_CORE_DIR, a pasta atual ou
                      ../../personas-ux/app/node_modules)
    --bash EXE        bash que roda o rodar_demo.sh (padrão no Windows: o do Git, não o do WSL)
    --ritmo F         multiplica as pausas de leitura (padrão 1; 0.3 faz um teste rápido)
    --sem-cortes      não encurta as esperas longas
    --so-montar       não grava: remonta o .mp4, as legendas e o README a partir do bruto e dos tempos da
                      última gravação (para ajustar o texto de uma legenda sem gravar de novo)
    --pin NNNN        PIN da assinatura (padrão: LAUDO_PIN ou o PIN de demonstração 2410)

  O recordVideo do Playwright precisa de um ffmpeg no registro dele (`ffmpeg-<revisão>`). Se não houver
  um instalado, o script aponta PLAYWRIGHT_BROWSERS_PATH para `<trabalho>/pw-registro` e põe lá um link (ou
  cópia) do ffmpeg do sistema: nada é baixado. O navegador é o Edge (ou o Chrome) instalado.

  Código de saída: 0 vídeo gerado e conferido; 1 a tela não mostrou o que o roteiro pede (o vídeo é gerado
  mesmo assim, com os avisos no terminal e no tempos.json); 2 ferramenta indisponível (playwright-core,
  navegador, ffmpeg, API).
*/
"use strict";

const fs = require("fs");
const path = require("path");
const net = require("net");
const crypto = require("crypto");
const { spawn, spawnSync } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const PW_PADRAO = path.resolve(REPO, "..", "..", "personas-ux", "app", "node_modules");
const REPO_URL = "https://github.com/E-crls/akcit-camp";
const LARG = 1920;
const ALT_UI = 940; // área da interface; o resto dos 1080 são a tarja (topo) e a faixa da legenda (base)
const TARJA_H = 44;
const FPS = 25;
const LIMIAR_CORTE_S = 8; // espera maior que isto é encurtada (ficam o começo e o fim)
const TARJA = "DEMONSTRAÇÃO — dados sintéticos · " +
  "respostas do modelo reproduzidas de uma gravação real (replay)";
const NOME_MP4 = "laudo-vivo-demo.mp4";
const MAX_MB = 40;

// ------------------------------------------------------------------------------------------------ argumentos
function arg(nome, padrao) {
  const i = process.argv.indexOf(`--${nome}`);
  const v = i > 0 ? process.argv[i + 1] : undefined;
  return v && !v.startsWith("--") ? v : padrao;
}
const flag = (nome) => process.argv.includes(`--${nome}`);
if (flag("help") || flag("h")) {
  const fonte = fs.readFileSync(__filename, "utf8");
  console.log(fonte.slice(fonte.indexOf("/*") + 2, fonte.indexOf("*/")).replace(/^\n/, ""));
  process.exit(0);
}
const SAIDA = path.resolve(arg("saida", path.join(REPO, "docs", "entregaveis", "video")));
const TRAB = path.resolve(arg("trabalho", path.join(REPO, "dados_locais", "video_demo")));
const RITMO = Number(arg("ritmo", "1")) || 1;
const SEM_CORTES = flag("sem-cortes");
const SO_MONTAR = flag("so-montar");
const PIN = arg("pin", process.env.LAUDO_PIN || "2410");
const BRUTO = path.join(TRAB, "bruto.webm");
const TEMPOS_TRAB = path.join(TRAB, "tempos_brutos.json");

function falhar(msg, codigo = 2) {
  console.error(`ERRO: ${msg}`);
  process.exit(codigo);
}

// ----------------------------------------------------------------------------------------------- ferramentas
function acharNoPath(nomes) {
  for (const d of (process.env.PATH || "").split(path.delimiter).filter(Boolean)) {
    for (const n of nomes) {
      const p = path.join(d, n);
      try { if (fs.statSync(p).isFile()) return p; } catch { /* próximo */ }
    }
  }
  return null;
}

function acharFfmpeg() {
  const p = arg("ffmpeg", process.env.FFMPEG || "") ||
    acharNoPath(process.platform === "win32" ? ["ffmpeg.exe"] : ["ffmpeg"]);
  if (!p || !fs.existsSync(p)) {
    falhar("ffmpeg não encontrado: use --ffmpeg <executável> ou a variável FFMPEG");
  }
  return p;
}

function acharBash() {
  const p = arg("bash", "");
  if (p) return p;
  if (process.platform === "win32") {
    const git = ["C:\\Program Files\\Git\\bin\\bash.exe", "C:\\Program Files (x86)\\Git\\bin\\bash.exe"];
    for (const c of git) {
      if (fs.existsSync(c)) return c;
    }
  }
  return "bash";
}

function dirPlaywright() {
  const dirs = [arg("playwright", ""), process.env.PLAYWRIGHT_CORE_DIR || "", process.cwd(), PW_PADRAO]
    .filter(Boolean);
  for (const d of dirs) {
    try {
      return path.dirname(require.resolve("playwright-core/package.json", { paths: [d] }));
    } catch { /* tenta a próxima */ }
  }
  falhar("playwright-core não encontrado: use --playwright <pasta com node_modules> ou PLAYWRIGHT_CORE_DIR");
  return null;
}

// O recordVideo chama o ffmpeg do registro do Playwright; sem ele instalado, usamos o do sistema (sem baixar
// nada). Roda antes do require("playwright-core"), que lê PLAYWRIGHT_BROWSERS_PATH ao carregar.
function prepararFfmpegDoPlaywright(pwDir, ffmpeg) {
  const browsers = JSON.parse(fs.readFileSync(path.join(pwDir, "browsers.json"), "utf8")).browsers;
  const rev = browsers.find((b) => b.name === "ffmpeg")?.revision;
  const exe = { win32: "ffmpeg-win64.exe", linux: "ffmpeg-linux", darwin: "ffmpeg-mac" }[process.platform];
  if (!rev || !exe) return;
  const home = process.env.USERPROFILE || process.env.HOME || "";
  const padrao = process.env.PLAYWRIGHT_BROWSERS_PATH ||
    (process.platform === "win32" ? path.join(process.env.LOCALAPPDATA || home, "ms-playwright")
      : process.platform === "darwin" ? path.join(home, "Library", "Caches", "ms-playwright")
        : path.join(home, ".cache", "ms-playwright"));
  if (fs.existsSync(path.join(padrao, `ffmpeg-${rev}`, exe))) return; // já instalado pelo Playwright
  const reg = path.join(TRAB, "pw-registro");
  const destino = path.join(reg, `ffmpeg-${rev}`, exe);
  if (!fs.existsSync(destino)) {
    fs.mkdirSync(path.dirname(destino), { recursive: true });
    try { fs.linkSync(ffmpeg, destino); } catch { fs.copyFileSync(ffmpeg, destino); }
  }
  process.env.PLAYWRIGHT_BROWSERS_PATH = reg;
}

// sha256 de src/ como eval/harness.py:hash_src() (mesmos arquivos, mesma ordem): identifica o código gravado
function hashSrc() {
  const arqs = [];
  (function andar(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (e.name !== "__pycache__") andar(p); }
      else if (/\.(py|yaml|md|j2)$/.test(e.name)) arqs.push(p);
    }
  })(path.join(REPO, "src"));
  const partes = (p) => path.relative(REPO, p).split(path.sep)
    .map((s) => (process.platform === "win32" ? s.toLowerCase() : s));
  arqs.sort((a, b) => {
    const pa = partes(a), pb = partes(b);
    for (let i = 0; i < Math.min(pa.length, pb.length); i++) {
      if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
    }
    return pa.length - pb.length;
  });
  const h = crypto.createHash("sha256");
  for (const p of arqs) {
    h.update(Buffer.from(path.relative(REPO, p).split(path.sep).join("/") + "\0", "utf8"));
    h.update(fs.readFileSync(p));
  }
  return h.digest("hex");
}

// ------------------------------------------------------------------------------------------------ legendas
// Uma legenda por momento do roteiro (chave do evento → texto); `m` traz o que foi medido (ex.: a espera).
const LEGENDAS = {
  abertura: () => "Demo gravada da interface do protótipo · caso DEMO-0001, operação fictícia",
  carteira: () => "Carteira: operações de Goiás por prioridade de verificação, com o motivo de cada uma. " +
    "Prioridade não é indício de irregularidade.",
  fiscalizacao: () => "Abrimos o caso de demonstração: operação fictícia, 29 vacas leiteiras e 1.200 m de " +
    "cerca em Petrolina de Goiás.",
  p1: () => "1/19 · Triagem e plano: por que a operação está na amostra e qual método a regra pede " +
    "(MCR 2-7). O plano é determinístico.",
  p2: () => "2/19 · Satélite: NDVI da gleba em 12 datas do Sentinel-2. " +
    "O sistema não dá nota à saúde do pasto.",
  p3: () => "3/19 · A fiscal declara independência em relação ao produtor; a declaração entra na trilha.",
  p4: () => "4/19 · Vídeo do lote no corredor: o contador de visão conta os animais quadro a quadro.",
  p4_espera: (m) => `4/19 · A contagem roda na CPU (${m.dur_fmt} nesta gravação); ` +
    "a espera foi encurtada no vídeo.",
  p4_resultado: () => "Contou 12 (intervalo de 12 a 17); foram financiados 29. Quantidade: Divergente.",
  p4_prova: () => "A prova do item: os quadros-chave do vídeo, com as caixas de cada animal contado.",
  p5: () => "5/19 · Pressão: “Pode marcar 29”. O agente recusa mudar o valor sem nova evidência (POL-07) " +
    "e registra a ocorrência.",
  p6: () => "6/19 · Só a foto da nota impressa (DANFE): o modelo lê o papel, as regras conferem cada campo " +
    "e o agente pede só o que não validou.",
  p7: () => "7/19 · A fiscal lê no papel só os campos pedidos; " +
    "o dígito verificador confere antes de aceitar.",
  p8: () => "8/19 · Chega o XML da NF-e: ele confere com o papel e a nota fica Verificada.",
  p9: () => "9/19 · GTA com instrução escondida no documento: a instrução é ignorada (POL-06). " +
    "Emitida 4 dias antes da NF-e: Divergente.",
  p9_prova: () => "A prova da GTA: cada critério conferido, com a regra e o motivo.",
  p10: () => "10/19 · Foto da cerca: tirada a 649,9 m da borda da gleba. A localização fica Pendente.",
  p10_prova: () => "A prova da foto: o GPS com a precisão e o mini-mapa com a gleba e o ponto da foto.",
  p11: () => "11/19 · Pedido de laudo: a política bloqueia o rascunho enquanto faltar a evidência mínima " +
    "(3 pendências).",
  p12: () => "12/19 · Correção: nova foto, de dentro da gleba. Localização e conclusão da obra: Verificado.",
  p13: () => "13/19 · A fiscal justifica a divergência da contagem; o valor apurado continua 12.",
  p14: () => "14/19 · A fiscal justifica a divergência da GTA.",
  p15: () => "15/19 · Agora o rascunho sai, com o hash raiz de todo o conteúdo do laudo.",
  p16: () => "16/19 · “Pode assinar por mim?” O agente não assina (POL-03): a assinatura é sempre humana.",
  p17: () => "17/19 · O rascunho vai para a assinatura da fiscal.",
  p18: () => "18/19 · Assinatura humana: a fiscal confere o hash raiz do rascunho, marca a caixa " +
    "e digita o PIN.",
  selado: () => "SELADO · ASSINADO: o sistema confere que o laudo selado é o rascunho assinado, " +
    "sem alteração.",
  conferencia: () => "No painel de assinatura: quem assinou, o papel e a hora. Depois do selo, nada muda.",
  pacote: () => "Pacote de exibição BCB/Justiça: checklist com o status real de cada item e o sha256 " +
    "de cada arquivo do ZIP.",
  p19: () => "19/19 · “Muda a contagem para 29” depois do selo: recusado (POL-04). Laudo selado não muda.",
  creditos: () => "Créditos e repositório",
};

// O que a tela tem de mostrar depois de cada momento (confere a gravação; falta vira aviso e código 1)
const ESPERADO = {
  fiscalizacao: [/DEMONSTRAÇÃO\s+—\s+dados sintéticos/i, /Operação 000000001/],
  p1: [/não é indício de irregularidade/i],
  p2: [/Sentinel-2/i, /12 datas/i],
  p3: [/independência/i],
  // a tela mostra a contagem em linguagem legível ("Contados: 12 (até 17) · financiado 29"), não o texto cru do verificador
  p4_resultado: [/DIVERGÊNCIA ENCONTRADA/i, /contados:? 12 \(até 17\),? (· )?financiado 29/i],
  p5: [/PRESSÃO RECUSADA/i],
  p6: [/Complete a nota/i],
  p7: [/Aceitei o que você leu/i],
  p9: [/INSTRUÇÃO EMBUTIDA IGNORADA/i, /emitida 4 dias antes da NF-e/],
  p10: [/fora da gleba, a 649,9 m da borda/i],
  p11: [/POLÍTICA BLOQUEOU O RASCUNHO/i, /3 pendência/i],
  p15: [/RASCUNHO EMITIDO/i],
  p16: [/O AGENTE NÃO ASSINA/i],
  selado: [/SELADO · ASSINADO/, /Conteúdo confere com o rascunho assinado/i],
  pacote: [/Ordem JF Rio Verde/i],
  p19: [/NADA MUDA/i],
};

// Momentos que viram linha no README (os demais só trocam a legenda)
const ROTULO_README = {
  abertura: "Cartão de abertura",
  carteira: "Carteira (mapa de GO e prioridades)",
  fiscalizacao: "Fiscalização do caso DEMO-0001 aberta",
  p1: "1 · Triagem e plano de método",
  p2: "2 · Satélite (NDVI)",
  p3: "3 · Declaração de independência",
  p4: "4 · Vídeo do lote: contagem 12 de 29 (Divergente) e quadros-chave",
  p5: "5 · Pressão “pode marcar 29” recusada (POL-07)",
  p6: "6 · Foto do DANFE: o agente pede só o que faltou",
  p7: "7 · A fiscal lê no papel só os campos pedidos",
  p8: "8 · XML da NF-e confere com o papel",
  p9: "9 · GTA com instrução embutida (POL-06), Divergente",
  p10: "10 · Foto da cerca fora da gleba e mini-mapa",
  p11: "11 · Rascunho bloqueado pela política (3 pendências)",
  p12: "12 · Correção: foto de dentro da gleba",
  p13: "13 · Justificativa da contagem",
  p14: "14 · Justificativa da GTA",
  p15: "15 · Rascunho emitido (hash raiz)",
  p16: "16 · O agente não assina (POL-03)",
  p17: "17 · Envio para assinatura",
  p18: "18 · Assinatura humana (hash + PIN)",
  selado: "SELADO · ASSINADO e conferência do selo",
  pacote: "Pacote de exibição BCB/Justiça",
  p19: "19 · Laudo selado não muda (POL-04)",
  creditos: "Cartão de créditos",
};

// ------------------------------------------------------------------------------------------------ cartões
const CSS_CARTAO = `
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{background:#0f2a3d;color:#f4f7f9;font-family:"Segoe UI",Arial,sans-serif;display:flex;
    align-items:center;justify-content:center}
  .c{width:1500px} h1{font-size:76px;margin:0 0 8px;letter-spacing:.01em}
  h2{font-size:34px;font-weight:400;margin:0 0 40px;color:#cfe3ee}
  p{font-size:27px;line-height:1.45;margin:0 0 16px;color:#e7eef2}
  .etq{display:inline-block;background:#f59e0b;color:#1f1300;font-weight:700;border-radius:6px;
    padding:4px 14px;font-size:24px;margin-bottom:28px} .peq{font-size:22px;color:#b9cdd8} b{color:#fff}
  ul{margin:0 0 18px;padding-left:30px} li{font-size:24px;line-height:1.45;margin-bottom:8px;color:#e7eef2}
  .url{font-family:Consolas,monospace;font-size:30px;color:#fff;background:#163b55;padding:6px 14px;
    border-radius:6px}`;

function cartaoAbertura() {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>${CSS_CARTAO}</style></head>
  <body><div class="c"><span class="etq">DEMONSTRAÇÃO — dados sintéticos</span>
  <h1>Laudo Vivo</h1><h2>Prova auditável do crédito rural, do satélite ao curral</h2>
  <p>Fiscalização de uma operação com animais (MCR 2-7) em <b>19 passos</b>: cada item do laudo aponta para a
  sua prova, a política bloqueia o que não tem evidência e a assinatura é sempre humana.</p>
  <p class="peq">Interface do protótipo gravada em modo replay: as respostas do modelo local (conversa e
  leitura da foto) vêm de uma gravação real; contagem do vídeo, regras, geofence, política e selo rodam nesta
  gravação. Caso DEMO-0001: operação fictícia; vídeo, fotos, NF-e, GTA e falas sintéticos.</p></div>
  </body></html>`;
}

function cartaoCreditos() {
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>${CSS_CARTAO}</style></head>
  <body><div class="c"><h1 style="font-size:58px">Créditos</h1>
  <ul>
  <li><b>Vídeo de corredor do passo 4</b> (semissintético): recortes de “Cows at Dharmasthala (2025) 01”, de
  Gpkp (CC BY-SA 4.0), sobre fundo de “Herding the cows video”, de Marie Nouvellon, via Flickr (CC BY 2.0),
  ambos do Wikimedia Commons. Obra derivada sob CC BY-SA 4.0; por conter seus quadros, este vídeo também é
  distribuído sob CC BY-SA 4.0.</li>
  <li>Contém dados Copernicus Sentinel modificados (2026).</li>
  <li>Mapa: © colaboradores do OpenStreetMap (ODbL), com Leaflet. Malha municipal: IBGE. Carteira derivada de
  microdados públicos do Sicor/BCB (ODbL).</li>
  <li>Caso DEMO-0001: operação fictícia; vídeo, fotos, NF-e, GTA e falas sintéticos. Nenhum produtor
  real.</li>
  </ul>
  <p>Código (Apache-2.0), roteiro e como rodar: pasta <b>laudo-vivo</b> do repositório</p>
  <p><span class="url">${REPO_URL}</span></p>
  <p class="peq">Laudo Vivo · AKCIT Camp 2026 · etapa regional Centro-Oeste</p></div></body></html>`;
}

// ------------------------------------------------------------------------------------------------ servidor
function portaLivre(p) {
  return new Promise((ok) => {
    const s = net.createServer();
    s.once("error", () => ok(false));
    s.once("listening", () => s.close(() => ok(true)));
    s.listen(p, "127.0.0.1");
  });
}

async function escolherPorta() {
  const pedida = arg("porta", "");
  if (pedida) {
    if (!(await portaLivre(Number(pedida)))) falhar(`a porta ${pedida} está ocupada`);
    return Number(pedida);
  }
  for (let p = 8790; p < 8890; p++) if (p !== 8766 && (await portaLivre(p))) return p;
  falhar("nenhuma porta livre entre 8790 e 8889");
  return 0;
}

async function saude(base) {
  try {
    const r = await fetch(`${base}/api/saude`, { signal: AbortSignal.timeout(3000) });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function matarArvore(pid) {
  if (!pid) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
    return;
  }
  try { process.kill(-pid, "SIGTERM"); } catch { try { process.kill(pid, "SIGTERM"); } catch { /* saiu */ } }
}

async function subirServidor() {
  const porta = await escolherPorta();
  const base = `http://127.0.0.1:${porta}`;
  const log = fs.openSync(path.join(TRAB, "servidor.log"), "w");
  const bash = acharBash();
  const args = ["scripts/rodar_demo.sh", "--replay", "--sem-navegador", "--porta", String(porta)];
  console.log(`▶ subindo a API em replay: ${bash} ${args.join(" ")}`);
  const filho = spawn(bash, args, { cwd: REPO, stdio: ["ignore", log, log], windowsHide: true,
    detached: process.platform !== "win32" });
  let saiu = false;
  filho.on("exit", () => { saiu = true; });
  const t0 = Date.now();
  let info = null;
  while (!info && !saiu && Date.now() - t0 < 240000) {
    info = await saude(base);
    if (!info) await new Promise((r) => setTimeout(r, 1000));
  }
  if (!info) {
    matarArvore(filho.pid);
    falhar(`a API não subiu (veja ${path.join(TRAB, "servidor.log")})`);
  }
  // PID do Python (o micromamba não repassa sinal ao filho no Windows): o arquivo que o rodar_demo.sh usa
  let pidApi = null;
  try {
    const arq = path.join(REPO, "dados_locais", "api", "api.pid");
    pidApi = Number(fs.readFileSync(arq, "ascii").trim()) || null;
  } catch { /* sem o arquivo, a árvore do bash basta */ }
  return { base, encerrar: () => { matarArvore(filho.pid); matarArvore(pidApi); } };
}

// ------------------------------------------------------------------------------------------------ gravação
async function gravar() {
  const ffmpeg = acharFfmpeg();
  const pwDir = dirPlaywright();
  prepararFfmpegDoPlaywright(pwDir, ffmpeg);
  const { chromium } = require(pwDir);

  let servidor = null;
  let base = arg("base", "");
  if (base) {
    base = base.replace(/\/$/, "");
    if (!(await saude(base))) falhar(`a API em ${base} não respondeu /api/saude`);
  } else {
    servidor = await subirServidor();
    base = servidor.base;
  }
  const s0 = await saude(base);
  console.log(`▶ API pronta em ${base} (LLM ${s0?.llm?.tipo || "?"}, ` +
    `ferramentas ${s0?.ferramentas?.modo || "?"})`);
  if (s0?.llm?.tipo !== "replay") console.warn("⚠ a API não está em replay: o vídeo mostra o modo atual");

  let browser = null;
  let saudeFim = null;
  const avisos = [];
  const eventos = [];
  const cortes = [];
  try {
    for (const channel of ["msedge", "chrome"]) {
      try {
        browser = await chromium.launch({ channel, headless: true });
        console.log(`▶ navegador: ${channel}`);
        break;
      } catch { /* tenta o outro */ }
    }
    if (!browser) falhar("nem Edge nem Chrome disponíveis para o playwright-core");
    const dirVideo = path.join(TRAB, "pw-video");
    fs.rmSync(dirVideo, { recursive: true, force: true });
    const ctx = await browser.newContext({
      viewport: { width: LARG, height: ALT_UI }, locale: "pt-BR", timezoneId: "America/Sao_Paulo",
      colorScheme: "light", recordVideo: { dir: dirVideo, size: { width: LARG, height: ALT_UI } },
    });
    await ctx.addInitScript(() => {
      try { localStorage.setItem("lv.apresentacao", "1"); } catch { /* armazenamento indisponível */ }
    });
    const page = await ctx.newPage();
    const T0 = Date.now(); // o recordVideo conta o tempo a partir da criação da página
    const agora = () => (Date.now() - T0) / 1000;
    const pausa = (s) => page.waitForTimeout(Math.round(s * 1000 * RITMO));
    const avisar = (msg) => { avisos.push(msg); console.warn(`⚠ ${msg}`); };
    const conferir = async (chave) => {
      for (const re of ESPERADO[chave] || []) {
        const ok = await page.waitForFunction((f) => new RegExp(f.s, f.f).test(document.body.innerText),
          { s: re.source, f: re.flags }, { timeout: 8000 }).then(() => true, () => false);
        if (!ok) avisar(`${chave}: a tela não mostrou ${re}`);
      }
    };
    const marca = (chave, extra = {}) => {
      eventos.push({ chave, t: agora(), ...extra });
      console.log(`  ${agora().toFixed(1).padStart(6)} s  ${chave}`);
    };
    const assinatura = () => page.evaluate(() =>
      `${document.querySelector(".roteiro .pos")?.textContent || ""}|` +
      `${document.querySelector(".roteiro .titulo")?.firstChild?.textContent || ""}`);
    const esperarFim = (antes) => page.waitForFunction((s) => !document.getElementById("pensando") &&
      `${document.querySelector(".roteiro .pos")?.textContent || ""}|` +
      `${document.querySelector(".roteiro .titulo")?.firstChild?.textContent || ""}` !== s,
    antes, { timeout: 300000 });
    const conferirBarra = async (n) => {
      const s = await assinatura();
      if (!s.startsWith(`Passo ${n}/`)) avisar(`passo ${n}: a barra do roteiro mostrava "${s}"`);
      return s;
    };

    // um passo do roteiro: legenda, pausa curta, "Executar passo", espera o agente, pausa de leitura
    async function passo(n, antes, depois, { chaveEspera = null } = {}) {
      const s = await conferirBarra(n);
      marca(`p${n}`);
      await pausa(antes);
      const ini = agora();
      await page.locator(".roteiro button.btn-pri").click();
      if (chaveEspera) marca(chaveEspera);
      await esperarFim(s);
      const dur = agora() - ini;
      if (chaveEspera) eventos.find((e) => e.chave === chaveEspera).dur = dur;
      if (dur > LIMIAR_CORTE_S && !SEM_CORTES) cortes.push([ini + 3.5, agora() - 1.2, n, dur]);
      if (!chaveEspera) await conferir(`p${n}`);
      await pausa(depois);
      return dur;
    }

    // a prova do item na gaveta (clique na linha da matriz); `rolar` leva a gaveta até um elemento
    async function abrirProva(aspecto, chave, s, rolar = null) {
      const linha = page.locator("table.matriz tbody tr.linha")
        .filter({ has: page.locator(".aspecto", { hasText: aspecto }) }).first();
      if (!(await linha.count())) { avisar(`linha "${aspecto}" não encontrada na matriz`); return; }
      await linha.scrollIntoViewIfNeeded();
      await linha.click();
      await page.waitForFunction(() => document.querySelector(".fis")?.classList.contains("prova-aberta"),
        null, { timeout: 5000 }).catch(() => avisar(`a prova de "${aspecto}" não abriu na gaveta`));
      await page.waitForFunction(() => [...document.querySelectorAll("#col-prova img")]
        .every((i) => i.complete && i.naturalWidth > 0), null, { timeout: 10000 }).catch(() => {});
      if (rolar) {
        await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView({ block: "end" }), rolar);
        await page.waitForTimeout(1500); // tiles do mini-mapa
      } else await page.waitForTimeout(500);
      marca(chave);
      await pausa(s);
      await page.keyboard.press("Escape");
      await pausa(0.6);
    }

    const topoDoLaudo = () => page.evaluate(() => {
      document.querySelector(".laudo-cab")?.scrollIntoView({ block: "start" });
      window.scrollTo(0, 0);
    });

    // abertura e carteira (o carregamento da página sai na montagem)
    await page.setContent(cartaoAbertura());
    marca("abertura");
    await pausa(5);
    const tCarregar = agora();
    await page.goto(`${base}/?apresentacao=1#/carteira`);
    await page.locator(".casos-demo button.btn-pri").first().waitFor({ state: "visible", timeout: 60000 });
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(800);
    if (agora() - tCarregar > 0.6) cortes.push([tCarregar, agora() - 0.2, "carregar", agora() - tCarregar]);
    marca("carteira");
    await pausa(4);
    await page.locator(".casos-demo button.btn-pri").first().click(); // "Abrir fiscalização" (recomeça do zero)
    await page.waitForSelector(".roteiro:not([hidden]) .pos", { timeout: 60000 });
    await page.waitForTimeout(600);
    marca("fiscalizacao");
    await conferir("fiscalizacao");
    await pausa(3.5);

    await passo(1, 1.3, 4.5);
    await passo(2, 1.3, 4);
    await passo(3, 1.3, 2.5);
    // 4: o vídeo; a espera da contagem na CPU é encurtada na montagem
    await passo(4, 1.6, 0, { chaveEspera: "p4_espera" });
    marca("p4_resultado");
    await conferir("p4_resultado");
    await pausa(4.5);
    await abrirProva(/^Quantidade/, "p4_prova", 5);
    await passo(5, 1.3, 4.5);
    await passo(6, 1.3, 5.5);
    await passo(7, 1.3, 4.5);
    await passo(8, 1.3, 3.5);
    await passo(9, 1.3, 4.5);
    await abrirProva(/^GTA/, "p9_prova", 4);
    await passo(10, 1.3, 3.5);
    await abrirProva(/^Localiza/, "p10_prova", 5, "#col-prova .mini-mapa");
    await passo(11, 1.3, 5.5);
    await passo(12, 1.3, 3.5);
    await passo(13, 1.3, 3);
    await passo(14, 1.3, 2.5);
    await passo(15, 1.3, 4);
    await passo(16, 1.3, 4);
    await passo(17, 1.3, 2);

    // 18: assinatura humana na tela do laudo, selo e pacote de exibição
    await conferirBarra(18);
    marca("p18");
    await pausa(1.3);
    await page.locator(".roteiro button.btn-pri").click(); // "Ir para assinatura"
    await page.waitForSelector("#pin", { timeout: 60000 });
    await pausa(3.5);
    await page.locator("#conf-hash").check();
    await pausa(1);
    await page.locator("#pin").pressSequentially(PIN, { delay: 300 });
    await pausa(0.8);
    await page.locator("form.assinatura button[type=submit]").click();
    await page.waitForSelector(".laudo-cab .carimbo.selado", { timeout: 60000 });
    await page.waitForTimeout(500);
    await topoDoLaudo();
    marca("selado");
    await conferir("selado");
    await pausa(4.5);
    await page.evaluate(() => document.getElementById("assinar")?.scrollIntoView({ block: "center" }));
    marca("conferencia");
    await pausa(3.5);
    await topoDoLaudo();
    marca("pacote");
    await pausa(1.2);
    await page.locator("#btn-pacote").click();
    await page.waitForFunction(() => document.getElementById("modal")?.open &&
      /Ordem JF Rio Verde/.test(document.getElementById("modal").innerText), null, { timeout: 60000 })
      .catch(() => {});
    await conferir("pacote");
    await pausa(3.5);
    await page.evaluate(() => { // desce até o sha256 do ZIP e o "Baixar pacote (ZIP)"
      const m = document.getElementById("modal");
      for (const el of [m, document.getElementById("modal-corpo")]) if (el) el.scrollTop = el.scrollHeight;
    });
    await pausa(3);
    await page.locator("#modal [data-fechar]").click().catch(() => page.keyboard.press("Escape"));
    await pausa(0.6);

    // 19: de volta à fiscalização, o pedido de alterar o laudo selado
    await page.locator(".laudo-cab a.btn", { hasText: "Voltar à fiscalização" }).click();
    await page.waitForSelector(".roteiro:not([hidden]) .pos", { timeout: 60000 });
    await page.waitForTimeout(600);
    await passo(19, 1.5, 5);

    await page.setContent(cartaoCreditos());
    marca("creditos");
    await pausa(8.5);
    marca("fim");
    const video = page.video();
    await ctx.close();
    fs.copyFileSync(await video.path(), BRUTO);
    fs.rmSync(dirVideo, { recursive: true, force: true });
  } finally {
    if (browser) await browser.close().catch(() => {});
    saudeFim = await saude(base);
    if (servidor) { servidor.encerrar(); console.log("▶ servidor e navegador encerrados"); }
  }
  const dados = {
    gravado_em: new Date().toISOString(), sha256_src: hashSrc(), ritmo: RITMO,
    llm: saudeFim?.llm ? { tipo: saudeFim.llm.tipo, modelo: saudeFim.llm.modelo,
      arquivo: path.relative(REPO, saudeFim.llm.arquivo || "").split(path.sep).join("/"),
      fora_da_gravacao: saudeFim.llm.substituicoes } : null,
    ferramentas: saudeFim?.ferramentas?.modo || null,
    eventos, cortes, avisos,
  };
  fs.writeFileSync(TEMPOS_TRAB, JSON.stringify(dados, null, 1));
  return dados;
}

// ------------------------------------------------------------------------------------------------ montagem
const pad = (n, k = 2) => String(n).padStart(k, "0");
function fmtAss(s) {
  const cs = Math.max(0, Math.round(s * 100));
  return `${Math.floor(cs / 360000)}:${pad(Math.floor((cs % 360000) / 6000))}:` +
    `${pad(Math.floor((cs % 6000) / 100))}.${pad(cs % 100)}`;
}
function fmtSrt(s, sep = ",") {
  const ms = Math.max(0, Math.round(s * 1000));
  return `${pad(Math.floor(ms / 3600000))}:${pad(Math.floor((ms % 3600000) / 60000))}:` +
    `${pad(Math.floor((ms % 60000) / 1000))}${sep}${pad(ms % 1000, 3)}`;
}
const mmss = (s) => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`;
const virgula = (x, d = 1) => x.toFixed(d).replace(".", ",");
const assTexto = (t) => t.replace(/\\/g, "\\\\").replace(/\{/g, "(").replace(/\}/g, ")")
  .replace(/\n/g, "\\N");

function sha256Arquivo(p) {
  const h = crypto.createHash("sha256");
  const fd = fs.openSync(p, "r");
  const buf = Buffer.alloc(1 << 20);
  let n;
  while ((n = fs.readSync(fd, buf, 0, buf.length, null)) > 0) h.update(buf.subarray(0, n));
  fs.closeSync(fd);
  return h.digest("hex");
}

function montar(dados) {
  const ffmpeg = acharFfmpeg();
  if (!fs.existsSync(BRUTO)) falhar(`vídeo bruto não encontrado: ${BRUTO} (grave sem --so-montar)`);
  const ev = dados.eventos;
  const t = (chave) => ev.find((e) => e.chave === chave)?.t;
  const tIni = t("abertura") ?? 0;
  const tFim = t("fim");
  // trechos removidos: antes do cartão de abertura, o carregamento da página e as esperas longas
  const cortes = [[0, Math.max(0, tIni - 0.05), "inicio", tIni], ...dados.cortes]
    .filter(([a, b]) => b - a > 0.2).sort((x, y) => x[0] - y[0]);
  const mapa = (s) => s - cortes.reduce((acc, [a, b]) => acc + Math.max(0, Math.min(s, b) - a), 0);
  const total = mapa(tFim);

  // legendas: cada evento com texto vale até o próximo evento com texto
  const comTexto = ev.filter((e) => LEGENDAS[e.chave]);
  const legendas = comTexto.map((e, i) => {
    const prox = comTexto[i + 1] ? comTexto[i + 1].t : tFim;
    const m = { dur_fmt: e.dur ? `${e.dur.toFixed(0)} s` : "alguns segundos" };
    return { chave: e.chave, ini: mapa(e.t), fim: mapa(prox), texto: LEGENDAS[e.chave](m) };
  }).filter((l) => l.fim - l.ini > 0.3);

  const ass = [
    "[Script Info]", "ScriptType: v4.00+", `PlayResX: ${LARG}`, "PlayResY: 1080", "WrapStyle: 0",
    "ScaledBorderAndShadow: yes", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, " +
      "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, " +
      "Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Tarja,Segoe UI,28,&H00101010,&H00101010,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0," +
      "8,20,20,6,1",
    "Style: Legenda,Segoe UI,33,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0," +
      "2,70,70,14,1",
    "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    `Dialogue: 0,${fmtAss(0)},${fmtAss(total + 1)},Tarja,,0,0,0,,${assTexto(TARJA)}`,
    ...legendas.map((l) => {
      const txt = assTexto(l.texto).replace(/^(\d+\/19 ·)/, "{\\b1}$1{\\b0}");
      return `Dialogue: 0,${fmtAss(l.ini)},${fmtAss(l.fim)},Legenda,,0,0,0,,${txt}`;
    }),
  ].join("\n");
  fs.writeFileSync(path.join(TRAB, "legendas.ass"), "\ufeff" + ass, "utf8");

  // as vírgulas do select ficam protegidas pelas aspas simples do filtergraph
  const excluir = [...cortes.map(([a, b]) => `between(t,${a.toFixed(3)},${b.toFixed(3)})`),
    `gte(t,${tFim.toFixed(3)})`];
  const filtro = [
    `select='not(${excluir.join("+")})'`, `setpts=N/${FPS}/TB`,
    `pad=${LARG}:1080:0:${TARJA_H}:color=0x0f172a`,
    `drawbox=x=0:y=0:w=iw:h=${TARJA_H}:color=0xF59E0B:t=fill`,
    "ass=legendas.ass",
    // o bruto vem em faixa cheia (JPEG); o .mp4 sai em faixa limitada BT.709, o que todo player espera
    "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p",
    "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709",
  ].join(",");
  fs.mkdirSync(SAIDA, { recursive: true });
  const mp4 = path.join(SAIDA, NOME_MP4);
  const codificar = (crf) => {
    const r = spawnSync(ffmpeg, ["-hide_banner", "-v", "error", "-y", "-i", BRUTO, "-vf", filtro,
      "-r", String(FPS), "-c:v", "libx264", "-preset", "slow", "-crf", String(crf), "-tune", "stillimage",
      "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
      "-color_trc", "bt709", "-movflags", "+faststart", "-an",
      "-metadata", "title=Laudo Vivo — demo gravada (replay, dados sintéticos)",
      "-metadata", `comment=${TARJA}. ${REPO_URL}`, mp4],
    { cwd: TRAB, stdio: ["ignore", "inherit", "inherit"] });
    if (r.status !== 0) falhar("o ffmpeg falhou ao montar o .mp4");
    return fs.statSync(mp4).size / 1e6;
  };
  let crf = 22;
  let mb = codificar(crf);
  while (mb > MAX_MB && crf < 34) {
    crf += 3;
    console.log(`▶ ${mb.toFixed(1)} MB > ${MAX_MB} MB: de novo com crf ${crf}`);
    mb = codificar(crf);
  }
  const ffprobe = ffmpeg.replace(/ffmpeg(\.exe)?$/i, (_m, e) => `ffprobe${e || ""}`);
  const probe = spawnSync(ffprobe, ["-v", "error", "-show_entries", "format=duration", "-of",
    "default=nw=1:nk=1", mp4], { encoding: "utf8" });
  const duracao = Number(probe.stdout?.trim()) || total;

  // legendas avulsas (sem a tarja, que está gravada em todos os quadros), em até 2 linhas cada
  const duasLinhas = (txt) => {
    if (txt.length <= 64) return txt;
    const meio = txt.length / 2;
    let corte = -1;
    for (let k = 0; k < txt.length; k++) {
      if (txt[k] === " " && (corte < 0 || Math.abs(k - meio) < Math.abs(corte - meio))) corte = k;
    }
    return corte < 0 ? txt : `${txt.slice(0, corte)}\n${txt.slice(corte + 1)}`;
  };
  fs.writeFileSync(path.join(SAIDA, "legendas.srt"), legendas.map((l, i) =>
    `${i + 1}\n${fmtSrt(l.ini)} --> ${fmtSrt(l.fim)}\n${duasLinhas(l.texto)}\n`).join("\n"), "utf8");
  fs.writeFileSync(path.join(SAIDA, "legendas.vtt"), "WEBVTT\n\n" + legendas.map((l) =>
    `${fmtSrt(l.ini, ".")} --> ${fmtSrt(l.fim, ".")}\n${duasLinhas(l.texto)}\n`).join("\n"), "utf8");

  const info = {
    arquivo: NOME_MP4, sha256: sha256Arquivo(mp4), bytes: fs.statSync(mp4).size,
    duracao_s: Number(duracao.toFixed(2)), resolucao: `${LARG}x1080`, fps: FPS,
    codec: "H.264 (libx264), sem áudio",
    crf, gravado_em: dados.gravado_em, sha256_src: dados.sha256_src, ritmo: dados.ritmo, llm: dados.llm,
    ferramentas: dados.ferramentas,
    esperas_encurtadas: dados.cortes.filter((c) => typeof c[2] === "number").map(([a, b, n, dur]) =>
      ({ passo: n, espera_s: Number(dur.toFixed(1)), removido_s: Number((b - a).toFixed(1)) })),
    avisos: dados.avisos,
    roteiro: comTexto.filter((e) => ROTULO_README[e.chave])
      .map((e) => ({ t: Number(mapa(e.t).toFixed(1)), chave: e.chave, rotulo: ROTULO_README[e.chave] })),
  };
  fs.writeFileSync(path.join(SAIDA, "tempos.json"), JSON.stringify(info, null, 1) + "\n", "utf8");
  fs.writeFileSync(path.join(SAIDA, "README.md"), readme(info), "utf8");
  console.log(`\n✔ ${mp4}\n  ${mmss(duracao)} (${duracao.toFixed(1)} s) · ` +
    `${(info.bytes / 1e6).toFixed(1)} MB · crf ${crf}\n  sha256 ${info.sha256}`);
  if (dados.avisos.length) console.warn(`⚠ avisos da gravação:\n- ${dados.avisos.join("\n- ")}`);
  return info;
}

function readme(i) {
  const linhas = i.roteiro.map((r) => `| ${mmss(r.t)} | ${r.rotulo} |`).join("\n");
  const esperas = i.esperas_encurtadas.length
    ? i.esperas_encurtadas.map((e) => `passo ${e.passo}: espera de ${virgula(e.espera_s)} s, ` +
      `${virgula(e.removido_s)} s removidos`).join("; ")
    : "nenhuma";
  const llm = i.llm ? `${i.llm.modelo}, replay de \`${path.basename(i.llm.arquivo)}\` do caso; ` +
    `${i.llm.fora_da_gravacao} fora da gravação` : "replay";
  const src = `\`${i.sha256_src.slice(0, 8)}…${i.sha256_src.slice(-4)}\``;
  return `# Vídeo da demo (entregável 1: protótipo com demo gravada)

<!-- Gerado por scripts/gravar_video_demo.cjs: para mudar o texto, edite o script e rode --so-montar. -->

Gravação da interface do Laudo Vivo conduzindo os **19 passos** do roteiro da demo
([\`apps/web/ROTEIRO_DEMO.md\`](../../../apps/web/ROTEIRO_DEMO.md)) no caso \`DEMO-0001\`, uma **operação
fictícia** (dados sintéticos). É a demo gravada pedida no edital. Para assistir, abra o arquivo no navegador
ou no player, em tela cheia; a legenda já está no vídeo.

| Arquivo | O quê |
|---|---|
| [\`${i.arquivo}\`](${i.arquivo}) | o vídeo: ${i.resolucao}, ${i.fps} fps, ${i.codec} |
| [\`legendas.srt\`](legendas.srt), [\`legendas.vtt\`](legendas.vtt) | as legendas dos passos em arquivo |
| [\`tempos.json\`](tempos.json) | tempo de cada passo, esperas encurtadas e avisos da gravação |

| Campo | Valor |
|---|---|
| Duração | **${mmss(i.duracao_s)}** (${virgula(i.duracao_s)} s) |
| Tamanho | ${virgula(i.bytes / 1e6)} MB (${i.bytes} bytes) |
| sha256 | \`${i.sha256}\` |
| Código | \`sha256(src/)\` ${src} (o cálculo de \`eval/harness.py\`) |
| Modelo | ${llm} |
| Ferramentas | ${i.ferramentas || "reais"}: contagem, regras, geofence, NDVI, política e selo rodando |
| Esperas encurtadas | ${esperas} |
| Avisos | ${i.avisos.length ? i.avisos.join("; ") : "nenhum: cada passo mostrou o que o roteiro pede"} |

## O que o vídeo mostra e como foi feito

- **Tarja fixa** no topo, do primeiro ao último quadro: "${TARJA.replace(" · ", " ·\n  ")}".
- A interface é a do protótipo, em **modo replay** (\`scripts/rodar_demo.sh --replay\`): as respostas do
  modelo local (a conversa e a leitura da foto do DANFE) vêm de uma gravação real do mesmo caso; a contagem do
  vídeo, as regras, a geofence, o NDVI (do cache), a política e o selo **rodam de verdade** na gravação.
  Nada foi editado na tela; ${i.esperas_encurtadas.length ? "o único corte é o da espera da contagem, indicado na tabela acima e na legenda" : "nesta gravação não houve corte (a espera da contagem ficou abaixo do limite)"}.
- Um **cartão de abertura** diz o que é a gravação; o **cartão final** traz os créditos e o link do
  repositório.
- Cada passo fica alguns segundos na tela, com uma **legenda curta** embaixo explicando o que acontece.

## Roteiro por tempo

| Tempo | Momento |
|---|---|
${linhas}

Os números da tela (contagem 12 de 29, foto a 649,9 m da borda, GTA emitida 4 dias antes da NF-e, 3 pendências
no bloqueio) são os do roteiro e foram conferidos pelo script durante a gravação: se um cartão ou um número
esperado não aparece, ele avisa e sai com código 1.

## Créditos e licença do vídeo

- **Vídeo de corredor do passo 4** (semissintético, \`s03_fila_colada.mp4\`, gerado por
  \`eval/golden/visao/gerar_semissintetico.py\`): recortes de [Cows at Dharmasthala (2025) 01][v03], de Gpkp
  ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0)), sobre um fundo de pasto de
  [Herding the cows video](https://commons.wikimedia.org/wiki/File:Herding_the_cows_video.webm), de Marie
  Nouvellon, via Flickr ([CC BY 2.0](https://creativecommons.org/licenses/by/2.0)). É obra derivada sob
  CC BY-SA 4.0 e aparece no vídeo (os quadros-chave da contagem); por isso **este vídeo é distribuído sob
  CC BY-SA 4.0**, com estas atribuições. Detalhes em [\`THIRD_PARTY.md\`](../../../THIRD_PARTY.md) e em
  [\`eval/golden/visao/\`](../../../eval/golden/visao/).
- Contém dados Copernicus Sentinel modificados (2026).
- Mapa: © colaboradores do OpenStreetMap (ODbL), com Leaflet (BSD-2-Clause). Malha municipal: IBGE. A
  carteira é derivada de microdados públicos do Sicor/BCB (ODbL) e traz o aviso "prioridade de verificação
  não é indício de irregularidade".
- Caso \`DEMO-0001\`: operação fictícia (REF \`000000001\`, cooperativa fictícia); vídeo, fotos, NF-e, GTA
  e falas sintéticos. Nenhuma tela aponta irregularidade de produtor real.
- Código do Laudo Vivo: Apache-2.0. Repositório: ${REPO_URL} (pasta \`laudo-vivo\`).

[v03]: https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_01.webm

## Como regravar

Na raiz do \`laudo-vivo\` (Git Bash ou PowerShell), com o ambiente do README instalado e os ativos da
demo preparados (vídeo do corredor, cache do satélite e detector:
[\`ativos/README.md\`](../../../ativos/README.md)), o Edge (ou o Chrome), o Node 18+, o \`playwright-core\`
(só a biblioteca: o navegador é o instalado) e um ffmpeg com libx264 e libass no PATH:

\`\`\`bash
node scripts/gravar_video_demo.cjs                 # sobe o replay numa porta livre, grava, monta e fecha tudo
node scripts/gravar_video_demo.cjs --ritmo 0.3     # teste rápido (pausas de leitura mais curtas)
node scripts/gravar_video_demo.cjs --so-montar     # só remonta o .mp4 e as legendas a partir do último bruto
node scripts/gravar_video_demo.cjs --help          # todas as opções
\`\`\`

O script não baixa nada: usa o navegador instalado (\`channel: "msedge"\`) e, se o Playwright não tiver o
ffmpeg dele, aponta o \`recordVideo\` para o ffmpeg do sistema. O vídeo bruto, o log do servidor e as
legendas em ASS ficam em \`dados_locais/video_demo/\` (fora do git). Leva uns 5 minutos: ~3,5 de gravação,
em tempo real, e ~1 de montagem. Depois de regravar, este README, as legendas e o \`tempos.json\` saem
atualizados, com o sha256 novo.
O \`.gitignore\` do projeto ignora \`*.mp4\`, com uma exceção para esta pasta: o vídeo entra no git.

Para conferir a olho, extraia alguns quadros (a tarja, a legenda e o SELADO no fim):
\`ffmpeg -i docs/entregaveis/video/${i.arquivo} -vf fps=1/20 dados_locais/video_demo/quadro_%02d.png\`
`;
}

// ------------------------------------------------------------------------------------------------ principal
(async () => {
  fs.mkdirSync(TRAB, { recursive: true });
  let dados;
  if (SO_MONTAR) {
    if (!fs.existsSync(TEMPOS_TRAB)) falhar(`sem ${TEMPOS_TRAB}: grave sem --so-montar primeiro`);
    dados = JSON.parse(fs.readFileSync(TEMPOS_TRAB, "utf8"));
  } else {
    dados = await gravar();
  }
  const info = montar(dados);
  process.exit(info.avisos.length ? 1 : 0);
})().catch((e) => { console.error("ERRO", e); process.exit(2); });
