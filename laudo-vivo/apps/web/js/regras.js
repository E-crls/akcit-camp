// Regras derivadas do estado da API (ESPEC v3.1 §7): indicador do laudo, faltas agrupadas e ordenadas, rótulo curto de
// cada item, cartão "Agora", resumo por objeto, nome da operação, motivo da amostra em linguagem simples, textos dos
// pedidos recusados e o código do laudo. Funções puras, sem DOM: a mesma conta no celular, no computador e no laudo.
// A API não muda: tudo sai de campos que o estado já devolve.

export const PRE_RASCUNHO = ["BRIEFING", "COLETA", "CHECAGEM", "CONCILIACAO", "REVISAO"];

// ---------------------------------------------------------------- números e textos
export function fmtInt(n) {
  const v = Number(n);
  return Number.isFinite(v) ? v.toLocaleString("pt-BR", { maximumFractionDigits: 0 }) : String(n ?? "");
}
export function fmtDec(n, casas = 1) {
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n ?? "");
  return v.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: casas });
}
export function dataBR(iso) {
  const m = String(iso || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(iso || "");
}
export function dataHora(iso, { ano = true, segundos = false } = {}) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso || "");
  const data = d.toLocaleDateString("pt-BR", ano ? { day: "2-digit", month: "2-digit", year: "numeric" } : { day: "2-digit", month: "2-digit" });
  const hora = d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", ...(segundos ? { second: "2-digit" } : {}) });
  return `${data}, ${hora}`;
}
export function maiuscula(t) { const s = String(t || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
export function minuscula(t) { const s = String(t || ""); return s.charAt(0).toLowerCase() + s.slice(1); }
const plural = (n, um, varios) => (Number(n) === 1 ? um : varios);

// "COOPERATIVA DE CRÉDITO DEMONSTRAÇÃO (fictícia)" → "Cooperativa de Crédito Demonstração"
export function instituicaoLimpa(s) {
  const t = String(s || "").replace(/\s*\(fict[ií]cia\)\s*/gi, " ").trim();
  if (!t || t !== t.toUpperCase()) return t;
  const peq = new Set(["de", "da", "do", "das", "dos", "e"]);
  return t.toLowerCase().split(/\s+/).map((w, i) => (i && peq.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ").replace(/\bS\.a\.?/gi, "S.A.");
}

// ---------------------------------------------------------------- operação e itens financiados
function pluralPt(p) {
  if (/[aeiouáéíóú]$/i.test(p)) return `${p}s`;
  if (/ão$/i.test(p)) return p.replace(/ão$/i, "ões");
  if (/[rzs]$/i.test(p)) return `${p}es`;
  if (/l$/i.test(p)) return p.replace(/l$/i, "is");
  if (/m$/i.test(p)) return p.replace(/m$/i, "ns");
  return `${p}s`;
}

export function obraDe(it) {
  const t = String(it?.tipo || "").toLowerCase();
  if (t === "cerca") return { nome: "cerca", art: "a", nova: "nova", concl: "concluída", Nome: "Cerca" };
  if (t === "curral") return { nome: "curral", art: "o", nova: "novo", concl: "concluído", Nome: "Curral" };
  return { nome: "obra", art: "a", nova: "nova", concl: "concluída", Nome: "Obra" };
}

export function ehBovino(it) { return it?.tipo === "bovinos" || it?.unidade === "cabeca" || it?.unidade === "UA_450kg"; }

// "29 vacas leiteiras" (curto: "29 vacas"); "1.200 m de cerca"
export function nomeItem(it, curto = false) {
  if (!it) return "";
  const q = Number(it.quantidade);
  if (ehBovino(it)) {
    const cat = String(it.categoria_animal || "bovino").trim();
    let palavras = cat.split(/\s+/);
    if (curto) palavras = palavras.slice(0, 1);
    const pl = q === 1 ? palavras : palavras.map(pluralPt);
    return `${fmtInt(q)} ${pl.join(" ")}`;
  }
  const obra = obraDe(it);
  if (it.unidade === "m") return `${fmtInt(q)} m de ${obra.nome}`;
  if (it.unidade === "m2") return `${fmtInt(q)} m² de ${obra.nome}`;
  if (it.unidade === "ha") return `${fmtDec(q)} ha de ${obra.nome}`;
  if (Number.isFinite(q) && q > 0 && obra.nome !== "obra") return `${fmtInt(q)} ${q === 1 ? obra.nome : pluralPt(obra.nome)}`;
  return descricaoCurta(it.descricao, 48);
}

export function descricaoCurta(desc, max = 64) {
  let c = String(desc || "").split(/ — Sicor:| — | \(projeto sintético;/)[0].trim();
  if (c.length > max) c = `${c.slice(0, max - 1).trimEnd()}…`;
  return c;
}

export function nomeOperacao(op, curto = false) {
  const nomes = (op?.itens || []).map((i) => nomeItem(i, curto)).filter(Boolean);
  if (!nomes.length) return op?.ref_bacen ? `Operação ${op.ref_bacen}` : "Operação";
  if (nomes.length === 1) return nomes[0];
  return `${nomes.slice(0, -1).join(", ")} e ${nomes.at(-1)}`;
}

export function localOperacao(op) {
  const m = op?.municipio_nome || op?.municipio || "";
  return m ? `${m}/${op?.uf || "GO"}` : (op?.uf || "");
}

// ---------------------------------------------------------------- linhas do laudo e indicador (§7.2)
export function linhas(e) { return (e?.matriz || []).filter((l) => !l.agregado); }
export function antesDoPlano(e) { return !e || e.etapa === "BRIEFING" || !e.metodo; }
export function justificada(l) { return l.status === "divergente" && !!l.justificativa; }
export function pronta(l) { return l.status === "verificado" || justificada(l); }
export function divergenteAberta(l) { return l.status === "divergente" && !l.justificativa; }
export function ehFalta(l) { return l.status === "pendente" || l.status === "abstencao" || divergenteAberta(l); }
export function temEvidencia(l) { return (l?.evidencias || []).length > 0; }
const sufixo = (campo) => String(campo || "").split(":").pop();

// ---------------------------------------------------------------- unidades: o que a fiscal vê como "um item"
// As linhas do mesmo objeto que pedem a mesma prova viram um item só (a foto da cerca vale pela integridade, pela
// localização e pela conclusão). As linhas que o agente verifica sozinho, sem prova da fiscal (método, prazo do
// cronograma, satélite), ficam à parte, em "O agente verificou", e não entram na conta: o total do indicador é
// fixo do plano até o selo, e só muda quando a fiscal faz alguma coisa.
export function ehDoAgente(l) { return !(l?.tipos_evidencia || []).length; }

function escolherPrincipal(ls) {
  const loc = ls.find((l) => sufixo(l.campo) === "localizacao");
  if (ls.length > 1 && loc) return loc;
  return ls.find(divergenteAberta) || ls.find((l) => l.status === "abstencao") || ls.find((l) => ehFalta(l) && temEvidencia(l)) || ls.find(ehFalta) || ls[0];
}

export function unidades(e) {
  const mapa = new Map();
  const out = [];
  for (const l of linhas(e)) {
    const agente = ehDoAgente(l);
    const tev = l.tipos_evidencia?.[0];
    const chave = agente ? `agente:${l.campo}` : l.item_id && tev ? `${l.item_id}:${tev}` : l.campo;
    let u = mapa.get(chave);
    if (!u) { u = { chave, linhas: [], agente, item_id: l.item_id || null, tev: tev || null }; mapa.set(chave, u); out.push(u); }
    u.linhas.push(l);
  }
  for (const u of out) {
    u.campos = u.linhas.map((l) => l.campo);
    u.pronta = u.linhas.every(pronta);
    u.divAberta = u.linhas.some(divergenteAberta);
    u.justificada = u.pronta && u.linhas.some(justificada);
    u.comEvidencia = u.linhas.some(temEvidencia);
    u.principal = escolherPrincipal(u.linhas);
    u.alvo = u.linhas.find(divergenteAberta) || u.linhas.find((l) => l.status === "abstencao") || u.linhas.find((l) => ehFalta(l) && temEvidencia(l))
      || u.linhas.find(ehFalta) || u.principal;
  }
  return out;
}

// Rótulo do item como a fiscal o vê: { titulo, apoio (falta), pronto, prontoApoio, ic, tipo: falta | div | sem | ok | divj }
export function rotuloUnidade(e, u) {
  if (u.linhas.length === 1) {
    const l = u.linhas[0];
    const r = rotuloItem(e, l);
    return { ...r, tipo: justificada(l) ? "divj" : r.tipo, prontoApoio: justificada(l) ? "Divergência justificada." : r.apoio };
  }
  const it = (e?.operacao?.itens || []).find((i) => i.id === u.item_id);
  const obra = obraDe(it);
  const sufs = new Set(u.linhas.map((l) => sufixo(l.campo)));
  const nome = u.tev === "foto" ? `Foto da ${obra.nome}` : u.tev === "video" ? "Vídeo do lote" : rotuloItem(e, u.principal).titulo;
  const pronto = u.tev === "foto" && sufs.has("localizacao") ? `Foto da ${obra.nome} dentro da área` : nome;
  const extras = [sufs.has("integridade_foto") ? "sem edição" : null, sufs.has("conclusao") ? `${obra.art} ${obra.nome} está ${obra.concl}` : null].filter(Boolean);
  const prontoApoio = u.justificada ? "Divergência justificada." : extras.length ? `${maiuscula(extras.join("; "))}.` : "Verificado.";
  if (u.pronta) return { titulo: pronto, apoio: prontoApoio, pronto, prontoApoio, ic: "check", tipo: u.justificada ? "divj" : "ok" };
  if (!u.comEvidencia) return { titulo: nome, apoio: "Ainda não enviada.", pronto, prontoApoio, ic: u.tev === "foto" ? "camera" : u.tev === "video" ? "video" : "falta", tipo: "falta" };
  const r = rotuloItem(e, u.alvo);
  return { ...r, pronto, prontoApoio };
}
export function unidadeDoCampo(e, campo) { return unidades(e).find((u) => u.campos.includes(campo)) || null; }

export function indicador(e) {
  const us = unidades(e).filter((u) => !u.agente);
  if (antesDoPlano(e) || !us.length) return { antes: true, T: 0, N: 0, D: 0, J: 0, F: 0, selado: false, segs: [] };
  const N = us.filter((u) => u.pronta).length;
  const J = us.filter((u) => u.justificada).length;
  const D = us.filter((u) => u.divAberta).length;
  const T = us.length;
  const segs = [...Array(N - J).fill("ok"), ...Array(J).fill("divj"), ...Array(D).fill("div"), ...Array(Math.max(0, T - N - D)).fill("falta")];
  // a vez: o item que o cartão AGORA pede (o primeiro que falta, quando ele não é uma divergência a justificar)
  const primeira = faltasUnidades(e).find((u) => !u.agente);
  const iFalta = segs.indexOf("falta");
  if (primeira && !primeira.divAberta && iFalta >= 0 && e.etapa !== "SELADO") segs[iFalta] = "vez";
  return { antes: false, T, N, D, J, F: unidades(e).filter((u) => !u.pronta).length, selado: e.etapa === "SELADO", segs };
}

export function textoIndicador(ind) {
  if (ind.antes) return "Itens do laudo";
  if (ind.selado) return `Laudo selado · ${ind.T} ${plural(ind.T, "item pronto", "itens prontos")}`;
  return `${ind.N} de ${ind.T} ${plural(ind.T, "item pronto", "itens prontos")}`;
}
export function textoDivergentes(d) { return d ? `${d} ${plural(d, "divergente", "divergentes")}` : ""; }
export function textoJustificadas(j) { return j ? `${j} ${plural(j, "divergência justificada", "divergências justificadas")}` : ""; }
// o que vai em vermelho ao lado do número: as divergências abertas; sem elas, as justificadas (a marca não some)
export function textoMarcaDiv(ind) { return ind.D ? textoDivergentes(ind.D) : ind.J ? textoJustificadas(ind.J) : ""; }
export function ariaIndicador(ind) {
  if (ind.antes) return "Itens do laudo: a lista sai com a sua primeira prova. Abrir a lista do laudo";
  const m = textoMarcaDiv(ind);
  return `${textoIndicador(ind)}${m ? `, ${m}` : ""}. Abrir a lista do laudo`;
}

export function estadoLaudo(e) {
  if (e?.etapa === "SELADO") return { rot: "Selado", ic: "cadeado-cheio", cls: "st-selado" };
  if (["RASCUNHO", "ASSINATURA"].includes(e?.etapa) && e?.laudo) return { rot: "Para assinar", ic: "assinar", cls: "st-falta" };
  return { rot: "Em campo", ic: "relogio", cls: "st-neutro" };
}

// Trilha do laudo: Em campo → Rascunho → Assinado → Selado, com quando e quem (a palavra é sempre "Selado").
// Sai só do estado: a 1ª conversa (em campo), o último pedido de emissão aceito (rascunho), a assinatura e o selo.
// Com `segundos` (o lacre), a hora vai com os segundos: a demonstração percorre as quatro etapas em poucos minutos, e
// quatro "09:10" iguais pareceriam dado inventado. Quem fez: a fiscal, o agente (que só prepara), a fiscal e o sistema,
// que gera o código do selo.
export function etapasLaudo(e, { fiscal = "a fiscal", segundos = false } = {}) {
  const etapa = e?.etapa;
  const conv = e?.conversa || [];
  const ass = (e?.assinaturas || [])[0] || null;
  const temRascunho = !PRE_RASCUNHO.includes(etapa) && (!!e?.laudo || etapa === "SELADO");
  const emitiu = [...conv].reverse().find((c) => (c.acoes || []).some((a) => /^emitir_rascunho(:ok)?$/.test(typeof a === "string" ? a : `${a?.acao}:${a?.permitido === false ? "negado" : "ok"}`)));
  const curto = (iso) => (iso ? dataHora(iso, { ano: false, segundos }).replace(", ", " · ") : "");
  const selado = etapa === "SELADO";
  return [
    { rot: "Em campo", estado: temRascunho ? "feita" : "atual", quando: curto(conv[0]?.em), quem: ass?.nome_ref || fiscal },
    { rot: "Rascunho", estado: selado ? "feita" : temRascunho ? "atual" : "", quando: temRascunho ? curto(emitiu?.em) : "", quem: temRascunho ? "Agente" : "" },
    { rot: "Assinado", estado: ass ? "feita" : "", quando: ass ? curto(ass.em) : "", quem: ass ? ass.nome_ref : "" },
    { rot: "Selado", estado: selado ? "feita" : "", quando: selado ? curto(e?.laudo?.selado_em || ass?.em) : "", quem: selado ? "Código gerado" : "" },
  ];
}

// ---------------------------------------------------------------- checagens e provas
export function checagensDaLinha(e, l) {
  const ids = new Set(l?.checagens || []);
  return (e?.checagens || []).filter((c) => ids.has(c.id));
}
function ultimaChecagem(e, l, ferramenta) {
  return checagensDaLinha(e, l).filter((c) => !ferramenta || c.ferramenta === ferramenta).at(-1) || null;
}
export function distanciaFoto(e, l) {
  const c = ultimaChecagem(e, l, "geofence") || checagensDaLinha(e, l).find((x) => x.prova?.distancia_borda_m !== undefined);
  const d = c?.prova?.distancia_borda_m;
  return d === undefined || d === null ? null : Number(d);
}
export const arred10 = (m) => Math.round(Number(m) / 10) * 10;

// "GTA GO-B-418038 emitida 4 dias antes da NF-e; …" → "GTA emitida 4 dias antes da nota"
export function motivoGta(l) {
  const m = String(l?.motivo || "").match(/emitida\s+(\d+)\s+dias?\s+antes\s+da\s+NF-e/i);
  if (m) return `GTA emitida ${m[1]} ${m[1] === "1" ? "dia" : "dias"} antes da nota`;
  if (/depois|após/i.test(String(l?.motivo || ""))) return "GTA com data fora da compra";
  return "GTA não confere com a compra";
}

function contagemDe(e, l) {
  const v = l?.valor && typeof l.valor === "object" ? l.valor : {};
  const it = (e?.operacao?.itens || []).find((i) => i.id === l?.item_id);
  return { c: v.contagem, max: Array.isArray(v.intervalo) ? v.intervalo[1] : v.contagem, fin: v.financiado ?? it?.quantidade };
}

function serieSatelite(e) {
  const c = (e?.checagens || []).filter((x) => x.ferramenta === "serie_ndvi").at(-1);
  return c?.prova?.dados?.n_obs_limpas ?? null;
}

// ---------------------------------------------------------------- rótulo curto de cada item (§7.4)
// { titulo, apoio, pronto (título na lista de prontos), ic (ícone de falta), tipo: "falta" | "div" | "ok" | "sem" }
export function rotuloItem(e, l) {
  const it = (e?.operacao?.itens || []).find((i) => i.id === l.item_id);
  const obra = obraDe(it);
  const suf = sufixo(l.campo);
  const ev = temEvidencia(l);
  const st = l.status;
  const tipo = st === "verificado" || justificada(l) ? "ok" : st === "divergente" ? "div" : st === "abstencao" ? "sem" : "falta";
  const r = (titulo, apoio, pronto = titulo, ic = "falta") => ({ titulo, apoio, pronto, ic: tipo === "div" ? "diverge" : tipo === "sem" ? "sem-conclusao" : ic, tipo });
  const apoioDiv = justificada(l) ? "Divergência justificada." : "Divergente: falta justificar.";
  if (suf === "quantidade") {
    const { c, fin } = contagemDe(e, l);
    if (st === "abstencao") return r("Contagem sem conclusão", "O vídeo não deu para contar.", "Contagem", "video");
    if (st === "pendente" || c === undefined || c === null) {
      return r(ev ? "Vídeo do lote: contagem em andamento" : "Vídeo do lote", ev ? "O agente está contando os animais." : "Ainda não enviado.", "Vídeo do lote", "video");
    }
    if (st === "divergente") return r(`Contagem: ${fmtInt(c)} de ${fmtInt(fin)} financiados`, apoioDiv, `Contagem: ${fmtInt(c)} de ${fmtInt(fin)}`, "video");
    return r(`Contagem: ${fmtInt(c)} de ${fmtInt(fin)}`, "Confere com o financiado.", `Contagem: ${fmtInt(c)} de ${fmtInt(fin)}`, "video");
  }
  if (suf === "comprovante_nfe" || suf === "nfe") {
    if (st === "divergente") return r("Nota fiscal não confere", apoioDiv, "Nota fiscal não confere", "nota");
    if (st === "verificado") return r("Nota fiscal da compra", "Confere com a compra.", "Nota fiscal da compra", "nota");
    if (st === "abstencao") return r("Nota fiscal sem conclusão", "A foto da nota não deu para ler.", "Nota fiscal da compra", "nota");
    if (ev && e?.residual) return r("Nota fiscal: faltam campos do papel", "Lida pela foto; faltam campos que só o papel mostra.", "Nota fiscal da compra", "nota");
    if (ev) return r("Nota fiscal: falta o arquivo da NF-e", "Lida pela foto; o arquivo fecha a conferência.", "Nota fiscal da compra", "nota");
    return r("Nota fiscal da compra", "Ainda não enviada.", "Nota fiscal da compra", "nota");
  }
  if (suf === "gta") {
    if (st === "divergente") return r(motivoGta(l), apoioDiv, motivoGta(l), "gta");
    if (st === "verificado") return r("GTA da compra", "Confere com a compra.", "GTA da compra", "gta");
    if (ev) return r("GTA ilegível ou incompleta", "A guia não deu para ler.", "GTA da compra", "gta");
    return r("GTA da compra", "Ainda não enviada.", "GTA da compra", "gta");
  }
  if (suf === "integridade_foto") {
    if (st === "verificado") return r("Foto original, sem edição", "Saiu do app, com os dados originais.", "Foto original, sem edição", "camera");
    return r("Foto editada ou sem dados", "A foto precisa sair do app, sem edição.", "Foto original, sem edição", "camera");
  }
  if (suf === "localizacao") {
    if (st === "verificado") return r("Foto dentro da área financiada", "Tirada dentro da área financiada.", "Foto dentro da área financiada", "pino");
    const d = distanciaFoto(e, l);
    if (ev && d !== null) return r(`Foto da ${obra.nome}: a ${fmtInt(arred10(d))} m da área`, "Precisa ser de dentro da área financiada.", "Foto dentro da área financiada", "pino");
    return r(`Foto da ${obra.nome}`, ev ? "Precisa ser de dentro da área financiada." : "Ainda não enviada.", "Foto dentro da área financiada", "pino");
  }
  if (suf === "conclusao") {
    if (st === "verificado") return r(`${obra.Nome} ${obra.concl}`, "A foto mostra a obra e a fiscal confirmou em campo.", `${obra.Nome} ${obra.concl}`, "camera");
    return r(ev ? "Obra ainda não confirmada" : `Foto da ${obra.nome}`, ev ? "Falta a foto da obra inteira ou a sua declaração." : "Ainda não enviada.", `${obra.Nome} ${obra.concl}`, "camera");
  }
  if (suf === "existencia") {
    if (st === "verificado") return r(`${obra.Nome} fotografada na área`, "Existe e está na área financiada.", `${obra.Nome} fotografada na área`, "camera");
    return r(`Foto da ${obra.nome}`, ev ? "Precisa ser de dentro da área financiada." : "Ainda não enviada.", `${obra.Nome} fotografada na área`, "camera");
  }
  if (suf === "prazo_cronograma") {
    const fim = l.valor?.cronograma_fim || (String(l.valor_fmt || "").match(/\d{4}-\d{2}-\d{2}/) || [])[0];
    if (st === "verificado") return r(fim ? `Prazo da obra: até ${dataBR(fim)}` : "Prazo da obra", "Dentro do cronograma.", fim ? `Prazo da obra: até ${dataBR(fim)}` : "Prazo da obra", "relogio");
    return r("Prazo da obra", "Falta a data do cronograma.", "Prazo da obra", "relogio");
  }
  if (l.campo === "laudo:metodo") {
    const m = e?.metodo_rotulo || String(e?.metodo || "").replaceAll("_", " ").replace("autofiscalizacao", "autofiscalização");
    if (st === "verificado") return r(`Método: ${m}`, "Definido pela regra.", `Método: ${m}`, "lista");
    return r("Método da fiscalização", "O agente define com a primeira mensagem.", "Método da fiscalização", "lista");
  }
  if (l.campo === "laudo:independencia_fiscal") {
    return r("Sua declaração de independência", st === "verificado" ? "Registrada na conversa." : "Falta declarar.", "Sua declaração de independência", "usuario");
  }
  if (l.campo === "laudo:metadados_sensoriamento") {
    const n = serieSatelite(e);
    const pronto = n ? `Pasto visto do satélite (${n} ${plural(n, "data sem nuvem", "datas sem nuvem")})` : "Pasto visto do satélite";
    return r(st === "verificado" ? pronto : "Pasto visto do satélite", st === "verificado" ? "Série do satélite registrada." : "Falta a série.", pronto, "satelite");
  }
  const base = maiuscula(String(l.aspecto || suf).replace(/\s*\(.*?\)\s*/g, " ").replaceAll("_", " ").trim());
  const apoio = tipo === "div" ? apoioDiv : tipo === "sem" ? "Sem conclusão: falta uma captura nova." : tipo === "ok" ? "Verificado." : ev ? "Falta concluir." : "Ainda não enviado.";
  return r(base, apoio, base, "falta");
}

// Título e frase do item no laudo (documento): "Contagem no vídeo" · "12 contadas de 29 financiadas; mesmo contando 17, faltam 12."
export function itemNoLaudo(e, l) {
  const suf = sufixo(l.campo);
  const it = (e?.operacao?.itens || []).find((i) => i.id === l.item_id);
  const obra = obraDe(it);
  if (suf === "quantidade") {
    const { c, max, fin } = contagemDe(e, l);
    if (c === undefined || c === null) return { titulo: "Contagem no vídeo", frase: "Sem contagem." };
    const min = Array.isArray(l?.valor?.intervalo) ? l.valor.intervalo[0] : c;
    const faixa = Number(min) === Number(max) ? `${fmtInt(max)} animais` : `de ${fmtInt(min)} a ${fmtInt(max)} animais`;
    const frase = Number(c) >= Number(fin) ? `${fmtInt(c)} contadas de ${fmtInt(fin)} financiadas.`
      : `Contamos ${faixa} no vídeo; o financiado é ${fmtInt(fin)}.`;
    return { titulo: "Contagem no vídeo", frase };
  }
  if (suf === "comprovante_nfe" || suf === "nfe") {
    return { titulo: "Nota fiscal (NF-e)", frase: l.status === "verificado" ? "Todos os critérios conferem." : l.status === "divergente" ? "A nota não confere com a compra." : "Lida pela foto; falta o arquivo." };
  }
  if (suf === "gta") {
    const m = motivoGta(l).replace(/^GTA /, "");
    return { titulo: "GTA", frase: l.status === "verificado" ? "Confere com a compra." : `${maiuscula(m).replace(/da nota$/, "da nota fiscal")}.` };
  }
  if (suf === "localizacao") {
    const c = checagensDaLinha(e, l).filter((x) => x.ferramenta === "geofence");
    const ok = c.filter((x) => x.status === "ok").at(-1);
    const prec = ok?.prova?.gps?.precisao_m ?? ok?.prova?.precisao_m;
    const ord = c.length > 1 ? "A segunda foto" : "A foto";
    return { titulo: "Foto dentro da área financiada",
      frase: l.status === "verificado" ? `${ord}${prec ? `, com GPS ±${fmtDec(prec)} m,` : ""} foi tirada dentro da área.` : "A foto não foi tirada dentro da área." };
  }
  if (suf === "integridade_foto") return { titulo: "Foto original, sem edição", frase: l.status === "verificado" ? "Saiu do app, com os dados originais." : "A foto não tem os dados originais." };
  if (suf === "conclusao") return { titulo: `${obra.Nome} ${obra.concl}`, frase: l.status === "verificado" ? "A foto mostra a obra e a fiscal confirmou em campo." : "Ainda não confirmada." };
  if (suf === "prazo_cronograma") {
    const v = l.valor || {};
    return { titulo: "Prazo da obra", frase: v.data_fiscalizacao && v.cronograma_fim ? `Fiscalização em ${dataBR(v.data_fiscalizacao)}, antes do fim do cronograma (${dataBR(v.cronograma_fim)}).` : "Dentro do cronograma." };
  }
  if (l.campo === "laudo:metodo") return { titulo: "Método da fiscalização", frase: `${maiuscula(e?.metodo_rotulo || "autofiscalização assistida")}.` };
  if (l.campo === "laudo:independencia_fiscal") return { titulo: "Declaração de independência da fiscal", frase: "Registrada na conversa." };
  if (l.campo === "laudo:metadados_sensoriamento") {
    const n = serieSatelite(e);
    return { titulo: "Pasto visto do satélite", frase: n ? `${n} ${plural(n, "data sem nuvem", "datas sem nuvem")} (Sentinel-2).` : "Série do satélite registrada." };
  }
  const r = rotuloItem(e, l);
  return { titulo: r.pronto, frase: r.apoio };
}

// ---------------------------------------------------------------- faltas: ordem do "Agora" e agrupamento (§7.1, §7.3)
const ORDEM_TIPO = { video: 0, nfe_xml: 1, documento: 1, gta: 2, foto: 3 };

function categoria(l) {
  if (divergenteAberta(l)) return 2;
  if (l.campo === "laudo:independencia_fiscal") return 1;
  return 0;
}

export function faltas(e) {
  const ls = linhas(e);
  return ls.map((l, i) => ({ l, i })).filter(({ l }) => ehFalta(l)).sort((a, b) => {
    const ca = categoria(a.l), cb = categoria(b.l);
    if (ca !== cb) return ca - cb;
    const ta = (ORDEM_TIPO[a.l.tipos_evidencia?.[0]] ?? 4) + (a.l.status === "abstencao" ? -0.5 : 0);
    const tb = (ORDEM_TIPO[b.l.tipos_evidencia?.[0]] ?? 4) + (b.l.status === "abstencao" ? -0.5 : 0);
    return ta !== tb ? ta - tb : a.i - b.i;
  }).map(({ l }) => l);
}

// Uma linha por item que falta (a foto da cerca é uma linha só, mesmo valendo por integridade, local e conclusão), na
// ordem do "Agora": a ordem da primeira linha de cada item na lista de faltas.
export function faltasUnidades(e) {
  const ordem = faltas(e);
  const pos = (u) => Math.min(...u.linhas.map((l) => { const i = ordem.indexOf(l); return i < 0 ? 999 : i; }));
  return unidades(e).filter((u) => !u.pronta).sort((a, b) => pos(a) - pos(b));
}
export function faltasAgrupadas(e) {
  return faltasUnidades(e).map((u) => {
    const r = rotuloUnidade(e, u);
    return { unidade: u, campos: u.campos, linhas: u.linhas, principal: u.principal, alvo: u.alvo, titulo: r.titulo, apoio: r.apoio, ic: r.ic,
      tipo: r.tipo === "divj" ? "ok" : r.tipo, n: 1 };
  });
}

// ---------------------------------------------------------------- ações de cada falta (o mesmo verbo no Agora e na lista)
// acao: filmar | galeria-video | fotografar-nota | arquivo-nfe | fotografar-gta | arquivo-gta | fotografar-cerca |
// refazer-foto | justificar:<campo> | declarar | anexar | perguntar:<texto> | escrever:<texto>
export function planoFalta(e, l) {
  const suf = sufixo(l.campo);
  const it = (e?.operacao?.itens || []).find((i) => i.id === l.item_id);
  const obra = obraDe(it);
  const tev = l.tipos_evidencia?.[0];
  const ev = temEvidencia(l);
  if (divergenteAberta(l)) {
    if (suf === "quantidade") {
      const { c, fin } = contagemDe(e, l);
      return { titulo: "Justifique a contagem", inf: "justificar a contagem", apoio: `${fmtInt(c)} de ${fmtInt(fin)} financiados. Conte o que você viu.`,
        curto: "pela contagem", acoes: [{ rot: "Justificar", acao: `justificar:${l.campo}`, ic: "caneta" }] };
    }
    if (suf === "gta") {
      return { titulo: "Justifique a GTA", inf: "justificar a GTA", apoio: `${maiuscula(motivoGta(l).replace(/^GTA /, ""))}. Conte o que você sabe.`,
        curto: "pela GTA", acoes: [{ rot: "Justificar", acao: `justificar:${l.campo}`, ic: "caneta" }] };
    }
    const nome = minuscula(rotuloItem(e, l).titulo);
    return { titulo: "Justifique a divergência", inf: "justificar a divergência", apoio: `${maiuscula(nome)}. Conte o que você viu.`,
      curto: "pela divergência", acoes: [{ rot: "Justificar", acao: `justificar:${l.campo}`, ic: "caneta" }] };
  }
  if (l.status === "abstencao") {
    const dica = tev === "video" ? "Apoie o celular e deixe a câmera parada." : tev === "foto" ? "Segure firme, com o GPS ligado, e mostre a estrutura inteira." : "Fotografe de cima, sem sombra.";
    const acao = tev === "video" ? { rot: "Filmar de novo", acao: "filmar", ic: "video" } : tev === "foto" ? { rot: "Fotografar de novo", acao: "fotografar-cerca", ic: "camera" }
      : { rot: "Fotografar de novo", acao: "fotografar-nota", ic: "camera" };
    return { titulo: "Refaça a captura", inf: "refazer a captura", apoio: dica, curto: "pela nova captura", acoes: [acao] };
  }
  if (l.campo === "laudo:independencia_fiscal") {
    return { titulo: "Declare a sua independência", inf: "declarar a independência",
      apoio: "Você não presta assistência técnica ao produtor nem tem vínculo com empresa dele.", curto: "pela declaração",
      acoes: [{ rot: "Declarar", acao: "declarar", ic: "caneta" }] };
  }
  if (suf === "quantidade" || tev === "video") {
    return { titulo: "Filme o lote no corredor", inf: "filmar o lote no corredor", apoio: "Os animais passando em fila, com a câmera parada.",
      curto: "pelo vídeo do lote", acoes: [{ rot: "Filmar", acao: "filmar", ic: "video" }, { rot: "Galeria", acao: "galeria-video", ic: "galeria" }] };
  }
  if (suf === "comprovante_nfe" || suf === "nfe" || tev === "nfe_xml") {
    const foto = { rot: "Fotografar", acao: "fotografar-nota", ic: "camera" };
    const arq = { rot: "Arquivo da NF-e", acao: "arquivo-nfe", ic: "arquivo" };
    return { titulo: "Envie a nota fiscal da compra", inf: "enviar a nota fiscal da compra",
      apoio: ev ? "Falta o arquivo da NF-e para fechar a nota." : "Foto da nota impressa ou o arquivo da NF-e.", curto: "pela nota fiscal",
      acoes: ev ? [arq, foto] : [foto, arq] };
  }
  if (suf === "gta" || tev === "gta") {
    return { titulo: "Envie a GTA da compra", inf: "enviar a GTA da compra", apoio: "Foto da guia ou o arquivo da GTA.", curto: "pela GTA",
      acoes: [{ rot: "Fotografar", acao: "fotografar-gta", ic: "camera" }, { rot: "Arquivo da GTA", acao: "arquivo-gta", ic: "arquivo" }] };
  }
  if (tev === "foto") {
    if (ev && suf === "localizacao") {
      return { titulo: `Refaça a foto da ${obra.nome} de dentro da área`, inf: `refazer a foto da ${obra.nome} de dentro da área`,
        apoio: "Ou justifique (por exemplo, obra na sede).", curto: `pela foto da ${obra.nome}`,
        acoes: [{ rot: "Refazer foto", acao: "refazer-foto", ic: "camera" }, { rot: "Justificar", acao: `justificar:${l.campo}`, ic: "caneta" }] };
    }
    if (ev && suf === "integridade_foto") {
      return { titulo: `Refaça a foto da ${obra.nome} pelo app`, inf: "refazer a foto pelo app", apoio: "A foto precisa sair do app, sem edição.",
        curto: `pela foto da ${obra.nome}`, acoes: [{ rot: "Refazer foto", acao: "refazer-foto", ic: "camera" }] };
    }
    if (ev && suf === "conclusao") {
      return { titulo: `Mostre ${obra.art} ${obra.nome} inteir${obra.art}`, inf: "confirmar a conclusão da obra",
        apoio: "Fotografe a estrutura inteira ou declare que está concluída.", curto: `pela foto da ${obra.nome}`,
        acoes: [{ rot: "Fotografar", acao: "fotografar-cerca", ic: "camera" }, { rot: "Declarar", acao: `escrever:A ${obra.nome} está concluída: `, ic: "caneta" }] };
    }
    return { titulo: `Fotografe ${obra.art} ${obra.nome} ${obra.nova} de dentro da área`, inf: `fotografar ${obra.art} ${obra.nome} ${obra.nova} de dentro da área`,
      apoio: "Com o GPS ligado, mostrando mourões e fios.", curto: `pela foto da ${obra.nome}`,
      acoes: [{ rot: "Fotografar", acao: "fotografar-cerca", ic: "camera" }] };
  }
  if (l.campo === "laudo:metadados_sensoriamento") {
    return { titulo: "Peça a série do satélite", inf: "pedir a série do satélite", apoio: "O agente lê o pasto da área financiada no satélite.",
      curto: "pelo satélite", acoes: [{ rot: "Perguntar ao agente", acao: "perguntar:Como está o pasto no satélite?", ic: "satelite" }] };
  }
  if (suf === "prazo_cronograma") {
    return { titulo: "Informe o prazo da obra", inf: "informar o prazo da obra", apoio: "A data de fim do cronograma do projeto.", curto: "pelo prazo",
      acoes: [{ rot: "Escrever", acao: "escrever:O prazo da obra é ", ic: "caneta" }] };
  }
  const nome = minuscula(rotuloItem(e, l).titulo);
  return { titulo: `Envie: ${nome}`, inf: `enviar ${nome}`, apoio: "Use o + para anexar.", curto: `por ${nome}`,
    acoes: [{ rot: "Anexar", acao: "anexar", ic: "mais" }] };
}

// ---------------------------------------------------------------- turnos: bloqueio, checagens e guardas
const ehStr = (a) => typeof a === "string";
function nomesAcoes(c) { return (c?.acoes || []).map((a) => (ehStr(a) ? a : `${a.acao}:${a.permitido === false ? "negado" : "ok"}`)); }

export function ultimoTurnoBloqueado(e) {
  const c = (e?.conversa || []).at(-1);
  if (!c || e?.laudo) return false;
  return nomesAcoes(c).some((a) => a.startsWith("emitir_rascunho")) && faltas(e).length > 0;
}

// Checagens de cada turno: a k-ésima ação "ferramenta:ok" de um nome casa com a k-ésima checagem dessa ferramenta.
export function checagensPorTurno(e) {
  const fila = {};
  for (const c of e?.checagens || []) (fila[c.ferramenta] ||= []).push(c);
  const pos = {};
  const out = {};
  for (const t of e?.conversa || []) {
    const lista = [];
    for (const a of nomesAcoes(t)) {
      const [nome, st] = a.split(":");
      if (!nome || st === "negado" || !fila[nome]) continue;
      const k = pos[nome] || 0;
      if (k < fila[nome].length) { lista.push(fila[nome][k]); pos[nome] = k + 1; }
    }
    out[t.turno] = lista;
  }
  return out;
}

// Evidências enviadas pela fiscal (sem os quadros-chave nem o rascunho) casadas com os turnos que as trouxeram.
export function evidenciasEnviadas(e) {
  return (e?.evidencias || []).filter((x) => x.tipo !== "quadro_chave" && !x.laudo && !/^rascunho_/.test(x.nome || ""));
}
export function evidenciaPorTurno(e) {
  const fila = {};
  for (const x of evidenciasEnviadas(e)) (fila[x.tipo] ||= []).push(x);
  const pos = {};
  const out = {};
  for (const t of e?.conversa || []) {
    if (!t.evidencia || !fila[t.evidencia]) continue;
    const k = pos[t.evidencia] || 0;
    if (k < fila[t.evidencia].length) { out[t.turno] = fila[t.evidencia][k]; pos[t.evidencia] = k + 1; }
  }
  return out;
}

// Tipo de guarda de cada turno, reconstruído das decisões da política (quando a aba não guardou os eventos do turno).
const GUARDA_REGRA = [[/POL-07/, "pressao"], [/POL-06/, "injecao"], [/POL-03/, "assinatura"], [/POL-04/, "selado"], [/POL-01|POL-02/, "bloqueio"]];
export function guardasReconstruidas(e) {
  const negadas = (e?.governanca || []).filter((g) => /^negar/.test(String(g.resultado || "")));
  let k = 0;
  const out = {};
  for (const t of e?.conversa || []) {
    const acoes = nomesAcoes(t);
    const negou = acoes.filter((a) => /:(negado)$/.test(a) && /^(guarda|evento)/.test(a)).length;
    const pedidos = acoes.filter((a) => a.startsWith("emitir_rascunho")).length;
    const tipos = [];
    for (let i = 0; i < negou + pedidos && k < negadas.length; i++) {
      const g = negadas[k];
      const tipo = (GUARDA_REGRA.find(([re]) => re.test(g.rule_id || "")) || [null, "negado"])[1];
      if (tipo === "bloqueio" && !pedidos) break;
      if (tipo !== "bloqueio" && i >= negou) break;
      tipos.push({ tipo, nivel: "bloqueio", rule_id: g.rule_id, texto: g.motivo, titulo: "" });
      k += 1;
    }
    if (tipos.length) out[t.turno] = tipos;
  }
  return out;
}

export const GUARDAS = {
  pressao: { ic: "escudo-cheio", texto: "Pedido recusado e registrado", anuncio: "O agente recusou o pedido e registrou." },
  injecao: { ic: "escudo-cheio", texto: "Instrução escondida no documento: ignorada e registrada", anuncio: "O agente ignorou uma instrução escondida no documento e registrou." },
  assinatura: { ic: "escudo-cheio", texto: "O agente não assina. A assinatura é sua.", anuncio: "O agente não assina: a assinatura é sua." },
  selado: { ic: "cadeado-cheio", texto: "Laudo selado: nada muda", anuncio: "Laudo selado: nada muda." },
  negado: { ic: "cadeado-cheio", texto: "A política não permitiu este pedido", anuncio: "A política não permitiu este pedido." },
};
export function guardaDoTurno(eventos) {
  // "negado" genérico (o agente tentou uma ferramenta fora de hora) não é pedido da fiscal: vai só para Detalhes técnicos
  for (const t of ["pressao", "injecao", "assinatura", "selado"]) {
    const ev = (eventos || []).find((x) => x.tipo === t && !(t === "selado" && x.nivel === "ok"));
    if (ev) return { tipo: t, ev };
  }
  return null;
}

// ---------------------------------------------------------------- pedidos recusados e registrados (§7.5)
export function textoRecusas(n) { return `${n} ${plural(n, "pedido recusado e registrado", "pedidos recusados e registrados")}`; }

export function textoOcorrencia(e, o, { laudo = false } = {}) {
  const desc = String(o?.descricao || "");
  if (o?.tipo === "pressao") {
    const q = (desc.match(/['‘’"“”]([^'‘’"“”]+)['‘’"“”]/) || [])[1];
    const n = q && (q.match(/^(?:marcar|mudar para|muda para|colocar)?\s*(\d+)$/i) || [])[1];
    if (laudo && n) return `Marcar ${n} animais sem nova prova: recusado.`;
    return `Pedido para mudar um número sem nova prova: recusado.${q ? ` (“${q}”)` : ""}`;
  }
  if (o?.tipo === "injecao") {
    const ev = (e?.evidencias || []).find((x) => x.id === o.evidencia_ref);
    const onde = ev?.tipo === "gta" || /gta/i.test(desc) ? "na GTA" : ev?.tipo === "nfe_xml" ? "na NF-e" : "no documento";
    return laudo ? `Instrução escondida ${onde}: ignorada.` : `Instrução escondida num documento (${onde.replace(/^n[ao] /, "")}): ignorada.`;
  }
  if (o?.tipo === "fora_de_escopo") return "Pedido fora do escopo: recusado.";
  if (o?.tipo === "falha_ferramenta") return "Falha de ferramenta: registrada.";
  return maiuscula(desc.replace(/^POL-\d+:\s*/, "").replace(/\s*\([^)]*\)/g, "")) || "Ocorrência registrada.";
}

// ---------------------------------------------------------------- resumo por objeto (§7.6)
export function resumoPorObjeto(e, { daFiscal = true } = {}) {
  const ls = linhas(e);
  const us = unidades(e).filter((u) => !u.agente);
  const Dj = us.filter((u) => u.justificada).length;
  const V = us.filter((u) => u.pronta && !u.justificada).length;
  const T = us.length;
  const doAgente = unidades(e).filter((u) => u.agente);
  const quem = daFiscal ? "com a sua justificativa" : "com a justificativa da fiscal";
  const total = Dj ? `${T} ${plural(T, "item pronto", "itens prontos")}: ${V} ${plural(V, "verificado", "verificados")} e ${Dj} ${plural(Dj, "divergente", "divergentes")} ${quem}`
    : `${T} ${plural(T, "item pronto", "itens prontos")}: ${V} ${plural(V, "verificado", "verificados")}`;
  const ag = Object.fromEntries((e?.matriz || []).filter((l) => l.agregado).map((l) => [l.campo, l]));
  const objetos = (e?.operacao?.itens || []).map((it) => {
    const filhos = ls.filter((l) => l.item_id === it.id);
    if (!filhos.length) return null;
    const st = ag[`item:${it.id}`]?.status || (filhos.some((l) => l.status === "divergente") ? "divergente" : filhos.every((l) => l.status === "verificado") ? "verificado" : "pendente");
    const partes = [];
    if (ehBovino(it)) {
      const q = filhos.find((l) => sufixo(l.campo) === "quantidade");
      const { c } = q ? contagemDe(e, q) : {};
      if (c !== undefined && c !== null) partes.push(`${fmtInt(c)} ${plural(c, "contada", "contadas")}`);
      const gta = filhos.find((l) => sufixo(l.campo) === "gta");
      if (gta?.status === "divergente") partes.push(motivoGta(gta).replace(/emitida \d+ dias? /, "").replace(/^GTA /, "GTA "));
      const nfe = filhos.find((l) => /nfe/.test(sufixo(l.campo)));
      if (nfe?.status === "divergente") partes.push("nota não confere");
      if (filhos.some((l) => l.status === "pendente")) partes.push("faltam itens");
    } else {
      const ok = filhos.every((l) => l.status === "verificado");
      if (ok) partes.push(`${maiuscula(obraDe(it).concl)} e fotografada dentro da área`.replace("Concluído e fotografada", "Concluído e fotografado"));
      else filhos.filter((l) => l.status !== "verificado").forEach((l) => partes.push(minuscula(rotuloItem(e, l).titulo)));
    }
    let frase = partes.length ? `${maiuscula(partes.join("; "))}.` : "";
    if (filhos.some(justificada)) frase += " Justificado.";
    // divergência justificada: o selo do objeto vira "Divergente · justificada" (contorno), não o roxo cheio
    const just = st === "divergente" && filhos.some(justificada) && !filhos.some(divergenteAberta);
    return { it, nome: nomeItem(it), status: just ? "divergente-j" : st, justificada: just, frase: frase.trim(), ic: ehBovino(it) ? "vaca" : "cerca" };
  }).filter(Boolean);
  return { total, objetos, T, V, Dj, doAgente };
}

// ---------------------------------------------------------------- código do laudo (§7.7)
export function codigoCurto(hx) {
  const s = String(hx || "");
  return s.length < 12 ? s : `${s.slice(0, 4)} ${s.slice(4, 8)} … ${s.slice(-4)}`;
}
export function codigoBlocos(hx) { return (String(hx || "").match(/.{1,4}/g) || []).join(" "); }

// ---------------------------------------------------------------- motivo da amostra em linguagem simples (§7.9)
export function motivoSimples(texto, animal = "animais") {
  let t = String(texto || "").replace(/\s*\(\+\d+\)\s*$/, "").trim();
  t = t.replace(/lota[çc][ãa]o impl[íi]cita de ([\d.,]+)\s*(cab|UA)\/ha na compra de matrizes\/reprodutores \(acima de ([\d.,]+)\)/i,
    (m, n, u, lim) => `${fmtDec(Number(String(n).replace(",", ".")), 1)} ${animal} por hectare na compra de matrizes, acima do limite de triagem (${lim})`);
  t = t.replace(/lota[çc][ãa]o impl[íi]cita de ([\d.,]+)\s*(cab|UA)\/ha na aquisi[çc][ãa]o para recria\/engorda \(acima de ([\d.,]+)\)/i,
    (m, n, u, lim) => `${fmtDec(Number(String(n).replace(",", ".")), 1)} ${animal} por hectare na compra para recria, acima do limite de triagem (${lim})`);
  t = t.replace(/;\s*(\d+) vezes a densidade bovina do munic[íi]pio \([^)]*\)/i, "; $1 vezes a média de bovinos do município");
  t = t.replace(/gleba sobreposta em [\d.,]+%[^;]*?com \d+ outra\(s\) opera[çc][ãa]o\(ões\)[^;]*/i, "área sobreposta a outra operação");
  t = t.replace(/\bgleba\b/gi, "área");
  return maiuscula(t);
}

// "Compra de matrizes" a partir da modalidade e da variedade do Sicor
export function objetoCarteira(o) {
  const mod = String(o?.modalidade || "").toUpperCase();
  const v = String(o?.variedade || "").toUpperCase();
  if (/AQUISI/.test(mod) && /ANIMA/.test(mod)) {
    if (/LEITE/.test(v)) return "Compra de vacas leiteiras";
    if (/MATRIZ/.test(v)) return "Compra de matrizes";
    if (/REPRODUTOR|TOURO/.test(v)) return "Compra de touros";
    if (/RECRIA|ENGORDA|BEZERR|GARROT/.test(v)) return "Compra de animais para recria";
    return "Compra de animais";
  }
  if (!mod) return "Operação de investimento";
  return maiuscula(mod.toLowerCase());
}

// ---------------------------------------------------------------- cartão "Agora" (§7.1)
// ctx: { papel: "fiscal" | "analista", confirmacao, telaGrande }
export function agora(e, ctx = {}) {
  const papel = ctx.papel || "fiscal";
  const ind = indicador(e);
  const fs = faltasUnidades(e).map((u) => u.alvo);
  const etapa = e?.etapa;
  const conf = ctx.confirmacao || e?.confirmacao_pendente || null;
  const acomp = (inf) => ({ acomp: true, rot: "Acompanhando", titulo: `Aguardando a fiscal: ${inf}`,
    apoio: ind.antes ? "A fiscal ainda não enviou a primeira prova. Você recebe o laudo para ler quando ele for selado."
      : `${plural(ind.F, "Falta 1 item", `Faltam ${ind.F} itens`)}. Você recebe o laudo para ler quando ele for selado.`, acoes: [] });
  if (etapa === "SELADO") {
    const quando = e?.laudo?.selado_em || e?.assinaturas?.[0]?.em;
    if (papel === "analista") {
      return { rot: "Selado", titulo: quando ? `Laudo selado em ${dataHora(quando, { ano: false })}` : "Laudo selado",
        apoio: "Nada muda daqui em diante.", acoes: [{ rot: "Ler o laudo", acao: "ver-laudo", ic: "nota" }], selado: true };
    }
    return { rot: "Selado", titulo: "Laudo selado", apoio: "Nada muda daqui em diante.", selado: true,
      acoes: [{ rot: "Ver laudo", acao: "ver-laudo", ic: "nota" }, { rot: "Baixar pacote", acao: "baixar-pacote", ic: "baixar" }] };
  }
  if (conf) {
    if (papel === "analista") return acomp("confirmar os números");
    const nums = (conf.numeros || []).filter((n) => n.critico).map((n) => n.rotulo).join(" · ");
    return { rot: "Agora", titulo: "Confirme os números", apoio: nums || conf.pergunta || "", confirmacao: conf,
      acoes: [{ rot: "Confirmar", acao: "confirmar", ic: "check" }, { rot: "Corrigir", acao: "corrigir", ic: "caneta" }] };
  }
  if (e?.residual) {
    const doc = e.residual.tipo_documento === "gta" ? "a GTA" : "a nota";
    if (papel === "analista") return acomp(`completar ${doc}`);
    return { rot: "Agora", titulo: `Complete ${doc}`, apoio: "Leia no papel só estes campos.", residual: e.residual,
      acoes: [{ rot: "Enviar leitura", acao: "completar-nota", ic: "enviar" }, { rot: "Falar", acao: "falar", ic: "mic" }] };
  }
  if (ultimoTurnoBloqueado(e)) {
    const n = fs.length;
    const primeira = fs[0];
    const pl = planoFalta(e, primeira);
    if (papel === "analista") return acomp(`resolver ${n === 1 ? "a falta" : `as ${n} faltas`}`);
    const just = fs.find((l) => divergenteAberta(l) || (temEvidencia(l) && sufixo(l.campo) === "localizacao"));
    const acoes = [{ ...pl.acoes[0] }];
    if (pl.acoes[1]) acoes.push(pl.acoes[1]);
    else if (just && just !== primeira) acoes.push({ rot: "Justificar", acao: `justificar:${just.campo}`, ic: "caneta" });
    return { rot: "Agora", titulo: `Faltam ${n} para emitir`, bloqueio: true, faltasCurtas: faltasAgrupadas(e).slice(0, 3),
      apoio: `Veja ao lado o que falta. Comece ${pl.curto}.`, apoioMovel: `Comece ${pl.curto}.`, acoes: acoes.slice(0, 2) };
  }
  if (antesDoPlano(e)) {
    const l = fs[0];
    const pl = l ? planoFalta(e, l) : { titulo: "Fale com o agente", inf: "começar a fiscalização", apoio: "Ele pede as provas e confere cada item.", acoes: [] };
    if (papel === "analista") return acomp(pl.inf);
    return { rot: "Para começar", titulo: pl.titulo, apoio: pl.apoio, acoes: pl.acoes.slice(0, 2), inicio: true };
  }
  if (fs.length) {
    const l = fs[0];
    const pl = planoFalta(e, l);
    if (papel === "analista") return acomp(pl.inf);
    return { rot: "Agora", titulo: pl.titulo, apoio: pl.apoio, acoes: pl.acoes.slice(0, 2), campo: l.campo };
  }
  const reemitir = e?.laudo && e.laudo.valido_para_assinar === false;
  if (PRE_RASCUNHO.includes(etapa) || !e?.laudo || reemitir) {
    if (papel === "analista") return acomp("emitir o rascunho");
    return { rot: "Agora", titulo: reemitir ? "Há prova nova: emita o rascunho de novo" : "Tudo pronto: emita o rascunho",
      apoio: "O agente confere tudo de novo antes de emitir.", acoes: [{ rot: reemitir ? "Emitir de novo" : "Emitir rascunho", acao: "emitir", ic: "nota" }], emitir: true };
  }
  if (papel === "analista") return acomp("revisar e assinar o laudo");
  return { rot: "Agora", titulo: "Revise e assine o laudo", apoio: "Quem assina é você, com o seu PIN.",
    acoes: [{ rot: "Revisar e assinar", acao: "revisar-assinar", ic: "assinar" }] };
}
