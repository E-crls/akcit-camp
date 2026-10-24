// Fala do agente em linguagem de campo (identidade.md §2): sem ids, nomes de ferramenta, etapas internas, siglas
// técnicas (NDVI, VLM, XML, hash, MCR, gleba) e sem "o fiscal" na terceira pessoa: o agente fala com a fiscal.
// O texto original da API não se perde: fica em Detalhes técnicos → Conversa (texto original). Funções puras.

import { ROT_FERRAMENTA, semIds } from "./ui.js";

const ETAPA_LEGIVEL = { BRIEFING: "início", COLETA: "coleta", CHECAGEM: "conferência", CONCILIACAO: "conferência", REVISAO: "revisão",
  REVISÃO: "revisão", RASCUNHO: "rascunho", ASSINATURA: "assinatura", SELADO: "selado" };
const RE_ETAPA = /\b(BRIEFING|COLETA|CHECAGEM|CONCILIACAO|REVIS[AÃ]O|RASCUNHO|ASSINATURA|SELADO)\b/g;

// Frases que só descrevem o funcionamento interno (ferramenta negada numa etapa, nota de execução): saem da tela.
const FRASE_INTERNA = [
  /não (?:é|foi|está) permitid[ao] na etapa/i,
  /^Não executei\b/i,
  /\bna etapa (?:BRIEFING|COLETA|CHECAGEM|CONCILIACAO|REVIS[AÃ]O|RASCUNHO|ASSINATURA|SELADO)\b/,
  /registre (?:a )?conclusão da obra com o trecho/i,
  /^Entendid[oa] a declaração/i,
];

// Divide em frases sem quebrar dentro de parênteses nem de aspas.
function frases(s) {
  const out = [];
  let ini = 0; let prof = 0; let aspas = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "(") prof += 1;
    else if (c === ")") prof = Math.max(0, prof - 1);
    else if (c === "“") aspas = true;
    else if (c === "”") aspas = false;
    else if (c === '"') aspas = !aspas;
    else if (".!?".includes(c) && !prof && !aspas && /\s/.test(s[i + 1] || "") && /[A-ZÁÉÍÓÚÂÊÔÃÕÇ"“(]/.test(s.slice(i + 1).trimStart()[0] || "")) {
      out.push(s.slice(ini, i + 1).trim());
      ini = i + 1;
    }
  }
  out.push(s.slice(ini).trim());
  return out.filter(Boolean);
}

const ROT_SUFIXO = { quantidade: "a contagem", gta: "a GTA", comprovante_nfe: "a nota fiscal", nfe: "a nota fiscal", localizacao: "a foto fora da área",
  integridade_foto: "a foto", conclusao: "a conclusão da obra", existencia: "a foto" };

function artigo(palavra) {
  const p = String(palavra || "").toLowerCase();
  if (/^(gta|foto|nota|nova|declaração|justificativa|série)/.test(p)) return "a";
  if (/^(fotos|notas)/.test(p)) return "as";
  return "o";
}

function agrupar4(hx) { return (String(hx).match(/.{1,4}/g) || []).join(" "); }

// ctx: { itens: [{ id, nome }], animal: "vacas" }
export function falaSimples(texto, ctx = {}) {
  let s = String(texto || "");
  if (!s.trim()) return "";
  // 1. trechos de diagnóstico interno entre parênteses
  s = s.replace(/\s*\(checagem inconclusiva[\s\S]*?\)(?=\.?(?:\s|$))/gi, "");
  s = s.replace(/\s*\((?:MCR|Res\.? CMN)[^)]*\)/g, "");
  s = s.replace(/\s*\(entre \d+ e \d+ m\)/g, "");
  s = s.replace(/\s*\(enquadramento [^)]*\)/gi, "");
  s = s.replace(/\s*\([^()]*\borigem:[^()]*\)/gi, "");
  s = s.replace(/\s*\(DANFE\)/g, "");
  s = s.replace(/\bNCM \d+,\s*/g, "");
  s = s.replace(/\s*\(?\b[a-z_]+=[\w.-]+\)?/g, "");
  s = s.replace(/justificativa d[oa] fiscal \(ou nova evidência\)\s*\(item[: ][\w-]+:(\w+)\)/g,
    (m, suf) => `justifique ${ROT_SUFIXO[suf] || "a divergência"} ou envie nova prova`);
  // 2. frases sobre ferramentas e etapas internas
  s = frases(s).filter((f) => !FRASE_INTERNA.some((re) => re.test(f))).join(" ");
  // 3. motivo da amostra (o mesmo texto da carteira)
  const animal = ctx.animal || "animais";
  s = s.replace(/lota[çc][ãa]o impl[íi]cita de ([\d.,]+)\s*(?:cab|UA)\/ha na compra de matrizes\/reprodutores \(acima de ([\d.,]+)\)/gi,
    (m, n, lim) => `${String(Math.round(Number(String(n).replace(",", ".")) * 10) / 10).replace(".", ",").replace(/,0$/, "")} ${animal} por hectare na compra de matrizes, acima do limite de triagem (${lim})`);
  s = s.replace(/\bcab\/ha\b/g, "cabeças por hectare");
  s = s.replace(/Prioridade de verificação/g, "Prioridade de visita");
  s = s.replace(/Método pela regra:/g, "Método:");
  // 4. siglas e termos técnicos → palavra do campo
  s = s.replace(/\b(fora|dentro) d[ae] glebas?\b/gi, (m, a) => `${a} da área financiada`);
  s = s.replace(/\bglebas\b/gi, "áreas").replace(/\bgleba\b/gi, "área");
  s = s.replace(/\bO NDVI só mede\b/g, "O índice só mede").replace(/\bNDVI\b/g, "índice de verde");
  s = s.replace(/\bO VLM confere que\b/g, "A leitura da imagem confirma que").replace(/\bO VLM\b/g, "A leitura da imagem").replace(/\b(?:por|pelo) VLM\b/g, "pela leitura da imagem")
    .replace(/\bVLM\b/g, "leitura da imagem");
  s = s.replace(/\bXMLs? da NF-e\b/g, "arquivo da NF-e").replace(/\bo XML\b/g, "o arquivo da NF-e").replace(/\bprocNFe\b/g, "arquivo completo da NF-e")
    .replace(/\bXML\b/g, "arquivo");
  s = s.replace(/\(com EXIF e GPS\)/g, "(com data e GPS)").replace(/\bEXIF\b/g, "dados da câmera");
  s = s.replace(/em GO a chave da NF-e é exigida no SIDAGO para autorizar a GTA/g, "em Goiás a GTA só sai com a chave da nota fiscal")
    .replace(/\bSIDAGO\b/g, "sistema da Agrodefesa");
  s = s.replace(/\(hash ([0-9a-f]{8,64})\)/gi, (m, hx) => `(código ${agrupar4(hx)})`)
    .replace(/\bhash(?: raiz)?\b/gi, "código");
  s = s.replace(/\bMCR(?: [\d-]+)?\b/g, "regras do crédito rural");
  // 5. "pendência" → "falta"; "evidência" → "prova"
  s = s.replace(/(\d+) pendência\(s\)/g, (m, n) => (n === "1" ? "falta 1 item" : `faltam ${n} itens`));
  s = s.replace(/\bitens pendentes\b/g, "itens que faltam").replace(/\bpendências\b/g, "faltas").replace(/\bpendência\b/g, "falta")
    .replace(/:\s*pendente\b/g, ": falta").replace(/\bpendentes?\b/g, "em falta");
  s = s.replace(/\bevidências documentais\b/g, "provas").replace(/\bnova evidência\b/g, "nova prova").replace(/\bevidência ausente:\s*/g, "")
    .replace(/\bevidências\b/g, "provas").replace(/\bevidência\b/g, "prova");
  // 6. o agente fala com a fiscal (segunda pessoa)
  s = s.replace(/solicite que (?:o|a) fiscal emita o laudo/gi, "você já pode emitir o laudo");
  s = s.replace(/\bpe[çc]a (?:ao|à) fiscal (?:que )?/gi, "envie ").replace(/\bpedir (?:ao|à) fiscal\b/gi, "enviar")
    .replace(/\bpe[çc]a (?=(?:a|as|o|os|uma|um) )/g, "envie ");
  s = s.replace(/\bou registre (?:a )?justificativa(?: d[oa] fiscal)?/gi, "ou justifique").replace(/\bregistre (?:a )?justificativa d[oa] fiscal\b/gi, "justifique");
  s = s.replace(/\b(?:[Aa] )?([Jj]ustificativa|[Dd]eclaração(?: de independência)?) d[oa] fiscal\b/g, (m, n, off, str) => {
    const antes = str.slice(0, off).trimEnd();
    const inicio = !antes || /[.!?(]$/.test(antes);
    return `${inicio ? "Sua" : "sua"} ${n.charAt(0).toLowerCase()}${n.slice(1)}`;
  });
  s = s.replace(/\b(Sua (?:justificativa|declaração(?: de independência)?)) registrada\b/g, "$1 foi registrada");
  s = s.replace(/\b(?:pel[ao]) fiscal\b/g, "por você").replace(/\b(?:ao|à) fiscal\b/g, "a você").replace(/\bd[oa] fiscal\b/g, "sua")
    .replace(/\b[oa] fiscal\b/g, "você");
  s = s.replace(/\bsolicitar\b/g, "enviar");
  // 7. "Próximo passo: enviar o …"
  s = s.replace(/Próximo passo: (?:nova coleta:\s*)?(vídeo|arquivo|GTA|fotos?|notas?|nova foto|declaração)\b/g,
    (m, w) => `Próximo passo: enviar ${artigo(w)} ${w}`);
  s = s.replace(/\b(enviar|envie) (arquivo|vídeo)\b/g, "$1 o $2").replace(/\b(enviar|envie) (GTA|foto|nota)\b/g, "$1 a $2");
  s = s.replace(/O próximo passo é enviar/g, "Próximo passo: enviar");
  // 8. ids que sobraram: item da operação vira o nome curto; ferramenta vira o rótulo; etapa vira palavra
  s = semIds(s);
  for (const it of ctx.itens || []) {
    if (!it?.id) continue;
    s = s.replace(new RegExp(`\\s*\\((?:item[: ])?${it.id}(?::[\\w-]+)?\\)`, "g"), "").replace(new RegExp(`\\b${it.id}\\b`, "g"), it.nome || "");
  }
  s = s.replace(/\b([a-z]+(?:_[a-z]+)+)\b/g, (m) => (ROT_FERRAMENTA[m] ? ROT_FERRAMENTA[m].toLowerCase() : m.replaceAll("_", " ")));
  s = s.replace(RE_ETAPA, (m) => ETAPA_LEGIVEL[m] || m.toLowerCase());
  // 9. arremate
  s = s.replace(/\(\s*\)/g, "").replace(/\s{2,}/g, " ").replace(/\s+([.,;:)])/g, "$1").replace(/([.;:])\1+/g, "$1")
    .replace(/:\s*\./g, ".").replace(/;\s*\./g, ".").trim();
  return s || "Anotei. O próximo passo está no cartão Agora.";
}

// Fala da fiscal registrada pelos botões ("(botão) Emitir rascunho do laudo") em linguagem natural.
export function falaFiscal(texto) {
  const s = String(texto || "").trim();
  if (!s) return "";
  const b = s.match(/^\(botão\)\s*(.*)$/i);
  if (!b) return s;
  const t = b[1];
  if (/emitir rascunho/i.test(t)) return "Emitir o laudo";
  return t.charAt(0).toUpperCase() + t.slice(1);
}
