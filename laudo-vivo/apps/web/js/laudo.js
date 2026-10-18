// Tela do laudo (analista da cooperativa e fiscal): barra de ações (voltar, conferir hash, baixar pacote), o laudo
// como documento (folha) e, ao lado, a assinatura humana com PIN ou o selo. Item → evidência → checagem → trace.
// Depois do selo, o painel mostra a conferência do conteúdo (laudo.audit.selo): o selado tem de ser o rascunho
// assinado; se não for, aviso em destaque (L87a). Rótulos legíveis, ids só no title (L98).

import { api } from "./api.js";
import { ROT_OCORRENCIA, ROT_TIPO_EV, abrirModal, anunciar, atualizarSaude, avisar, blocoTec, chipChecklist, chipRegra, chipStatus,
  copiar, curto, definirDemo, faixaDemonstracao, fmtData, fmtNum, h, hashAgrupado, icone, legivel, limparErros, motivoLegivel,
  rotuloFerramenta, secaoTecnica, semIds, valorLegivel } from "./ui.js";

let observadorCab = null; // mede a barra de ações (--lc-h): o painel fixo e a rolagem até a assinatura descontam a altura
import { tts } from "./voz.js";

const AGREGACAO = "OP-agregacao-item";
const ROT_SR = { sensor: "Sensor", datas: "Datas", resolucao: "Resolução espacial", resolucao_radiometrica: "Resolução radiométrica",
  bandas: "Bandas", metodologia: "Metodologia" };
const ROT_CONT = { verificado: "Verificados", divergente: "Divergentes", pendente: "Pendentes", abstencao: "Abstenções" };
const IC_CONT = { verificado: "verificado", divergente: "divergente", pendente: "pendente", abstencao: "abstencao" };
const ROT_PAPEL = { fiscal: "Fiscal", agronomo_responsavel: "Agrônomo responsável (ART)", analista_if: "Analista da IF" };

export async function telaLaudo(raiz, fisId, { focarAssinatura = false, voltar, abrirPacote = false, conferencia = null } = {}) {
  raiz.replaceChildren(h("p", { class: "carregando" }, "Carregando o laudo…"));
  let estado, laudo;
  try {
    estado = await api.estado(fisId);
    laudo = await api.laudo(fisId);
  } catch (e) {
    raiz.replaceChildren(h("div", { class: "laudo-tela" }, h("div", { class: "vazio grande" },
      icone("doc"), h("h1", {}, "Laudo ainda não emitido"),
      h("p", {}, e.status === 404 ? "A política só libera o rascunho quando a evidência mínima existe. Volte à fiscalização e peça o rascunho." : e.message),
      h("a", { class: "btn btn-pri", href: `#/fis/${encodeURIComponent(fisId)}` }, icone("voltar"), "Voltar à fiscalização"))));
    return;
  }
  const nav = document.getElementById("nav-laudo");
  nav.hidden = false; nav.href = `#/fis/${fisId}/laudo`;
  const navF = document.getElementById("nav-fis");
  navF.hidden = false; navF.href = `#/fis/${fisId}`;
  const selado = laudo.tipo === "selado";
  definirDemo(laudo.demonstracao);
  const evs = Object.fromEntries([...estado.evidencias, ...estado.falas].map((e) => [e.id, e]));
  const chks = Object.fromEntries(estado.checagens.map((c) => [c.id, c]));
  const ehAg = (i) => i.regra_id === AGREGACAO || i.agregado;
  // L33: os contadores contam aspectos, como o resumo; o "Resultado do item" (agregado) não entra
  const cont = { verificado: 0, divergente: 0, pendente: 0, abstencao: 0 };
  laudo.itens.filter((i) => !ehAg(i)).forEach((i) => { cont[i.status] = (cont[i.status] || 0) + 1; });
  const op = laudo.operacao || {};
  const metodo = laudo.metodo || {};
  const sr = laudo.sensoriamento_remoto || [];
  const ass = laudo.assinaturas || estado.assinaturas || [];

  // ---------------------------------------------------------------- barra de ações (uma linha, fundo sólido)
  const acoes = h("div", { class: "lc-acoes", id: "lc-acoes" },
    h("button", { class: "btn btn-sec btn-peq", type: "button", id: "btn-conferir", onclick: () => { fecharMais(); conferirHash(laudo, estado, conferencia, selado); } },
      icone("hash"), "Conferir hash"),
    botaoPacote(fisId, selado, estado.pacote),
    h("a", { class: "btn btn-fantasma btn-peq btn-icone", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo.html`, target: "_blank", rel: "noopener",
      "aria-label": "Imprimir (abre a versão para imprimir em outra aba)", title: "Imprimir (abre em outra aba)" },
    icone("imprimir"), h("span", { class: "rot-movel" }, "Imprimir")));
  // no celular as ações vão para o menu "⋯"
  const mais = h("button", { class: "btn btn-fantasma btn-icone lc-mais", type: "button", "aria-label": "Mais ações do laudo",
    "aria-expanded": "false", "aria-controls": "lc-acoes", onclick: () => alternarMais() }, icone("mais"));
  const cab = h("section", { class: "laudo-cab", "aria-label": "Ações do laudo" },
    h("a", { class: "btn btn-sec btn-peq lc-voltar", href: `#/fis/${encodeURIComponent(fisId)}`, title: "Voltar à fiscalização" },
      icone("voltar"), h("span", { class: "rot" }, "Voltar à fiscalização")),
    h("div", { class: "lc-tt" },
      h("div", { class: "lc-linha" }, h("h1", {}, h("span", { class: "lc-pre" }, "Laudo · "), `Operação ${op.ref_bacen || ""}`),
        h("span", { class: `carimbo ${selado ? "selado" : "rascunho"}` }, icone(selado ? "selo" : "doc"), selado ? "SELADO · ASSINADO" : "RASCUNHO"),
        laudo.demonstracao ? h("span", { class: "selo-barra", title: `${laudo.demonstracao.marca_dagua}. ${laudo.demonstracao.aviso || ""}` },
          icone("selo"), "Demonstração") : null),
      h("p", { class: "nota" }, selado ? `Selado em ${fmtData(estado.laudo?.selado_em || ass[0]?.em)}` : "Rascunho, ainda sem valor: confira o hash e assine")),
    mais, acoes);
  function alternarMais(abrir) {
    const vai = abrir === undefined ? !cab.classList.contains("mais-aberto") : abrir;
    cab.classList.toggle("mais-aberto", vai);
    mais.setAttribute("aria-expanded", vai ? "true" : "false");
  }
  function fecharMais() { alternarMais(false); }
  acoes.addEventListener("click", (e) => { if (e.target.closest("a, button")) setTimeout(fecharMais, 0); });

  // ---------------------------------------------------------------- folha: itens agrupados
  let nTrace = 0;
  const grupos = new Map();
  for (const it of laudo.itens) {
    const m = String(it.campo || "").match(/^item:([^:]+)/);
    const chave = m ? `item:${m[1]}` : "laudo";
    if (!grupos.has(chave)) grupos.set(chave, { agregado: null, linhas: [], descricao: null });
    const g = grupos.get(chave);
    if (ehAg(it)) g.agregado = it;
    else { g.linhas.push(it); g.descricao = g.descricao || it.item_descricao; }
  }
  const corpoTab = h("tbody");
  for (const [chave, g] of grupos) {
    const nome = chave === "laudo" ? "Requisitos do laudo" : curto(g.descricao || g.agregado?.item_descricao || "", 90);
    corpoTab.append(h("tr", { class: "grupo", title: g.descricao || null },
      h("th", { scope: "rowgroup", colspan: "2" }, nome, g.agregado?.motivo ? h("span", { class: "nota" }, ` · ${legivel(g.agregado.motivo)}`) : null),
      h("td", { colspan: "2", class: "c-res" }, g.agregado ? h("span", { class: "res-item" }, "Resultado do item: ", chipStatus(g.agregado.status)) : null)));
    for (const it of g.linhas) corpoTab.append(linhaItem(it));
  }

  function linhaItem(it) {
    const porTipo = new Map();
    for (const e of it.evidencias) {
      const t = e.tipo;
      if (!porTipo.has(t)) porTipo.set(t, []);
      porTipo.get(t).push(e);
    }
    const evNos = [...porTipo.entries()].map(([t, lista]) => {
      const rot = `${lista.length > 1 ? `${lista.length} ` : ""}${ROT_TIPO_EV[t] || t}${lista.length > 1 && !/s$/.test(ROT_TIPO_EV[t] || t) ? "s" : ""}`
        .replace("Quadro-chaves", "quadros-chave").replace("Fala do fiscals", "falas do fiscal").replace("Fotos", "fotos");
      const url = evs[lista[0].id]?.url;
      return url ? h("a", { class: "ev-link", href: url, target: "_blank", rel: "noopener", title: lista.map((e) => e.id).join(", ") }, rot)
        : h("span", { class: "ev-link", title: lista.map((e) => e.id).join(", ") }, rot);
    });
    const chkNos = it.checagens.map((c) => h("span", { class: "chk" },
      h("button", { class: "link-btn", type: "button", title: c.id, onclick: () => verChecagem(fisId, chks[c.id], c) }, rotuloFerramenta(c.ferramenta)),
      c.span_id ? h("button", { class: "link-btn trace", type: "button", title: `abrir o registro no trace (span ${c.span_id})`,
        "aria-label": `trace ${++nTrace}`, onclick: () => verSpan(fisId, c.span_id) }, icone("trace")) : null));
    const valor = valorLegivel(it);
    return h("tr", { title: it.campo },
      h("td", { class: "c-asp" }, h("strong", {}, it.aspecto),
        valor ? h("div", { class: "valor-ap", title: it.valor_fmt || null }, `${valor.rot}: `, h("strong", {}, valor.txt)) : null,
        it.motivo ? h("div", { class: "nota", title: it.motivo }, motivoLegivel(it)) : null,
        it.justificativa_humana ? h("div", { class: "just" }, icone("pessoa"), `Justificativa do fiscal: “${it.justificativa_humana}”`) : null,
        h("a", { class: "ver-prova", href: `#/fis/${encodeURIComponent(fisId)}?campo=${encodeURIComponent(it.campo)}` }, "ver prova", icone("direita"))),
      h("td", { class: "c-st" }, chipStatus(it.status)),
      h("td", { class: "c-prova" }, evNos.length || chkNos.length ? h("div", { class: "cadeia" },
        evNos.length ? h("span", { class: "evs" }, evNos) : h("span", { class: "nota" }, "sem arquivo"),
        chkNos.length ? [h("span", { class: "seta", "aria-hidden": "true" }, "→"), h("span", { class: "chks" }, chkNos)] : null) : h("span", { class: "nota" }, "—")),
      h("td", { class: "c-regra" }, it.regra_id ? chipRegra(it.regra_id) : "—"));
  }

  const meta = (rot, val, cls = "") => [h("dt", {}, rot), h("dd", { class: cls }, val || "—")];
  const metaF = (rot, val, cls = "") => h("div", {}, h("dt", {}, rot), h("dd", { class: cls }, val || "—"));
  const folha = h("article", { class: `folha${laudo.demonstracao ? " demo" : ""}`, "aria-labelledby": "t-laudo" },
    h("header", { class: "folha-cab" },
      h("div", { class: "folha-marca" }, h("span", {}, "Laudo Vivo"), h("span", {}, "Fiscalização do crédito rural")),
      h("h2", { id: "t-laudo" }, "Laudo de fiscalização de crédito rural"),
      laudo.demonstracao ? faixaDemonstracao(laudo.demonstracao) : null,
      h("dl", { class: "folha-meta" },
        metaF("Operação", op.ref_bacen), metaF("Município", `${op.municipio_nome || ""}/${op.uf || ""}`),
        metaF("Instituição", op.instituicao), metaF("Data de referência", laudo.data_referencia),
        metaF("Método", metodo.rotulo || metodo.metodo), metaF("Fiscalização", laudo.fiscalizacao_id, "mono")),
      h("div", { class: `selo-folha ${selado ? "selado" : "rascunho"}` },
        h("div", { class: "carimbo-folha" }, icone(selado ? "selo" : "doc"),
          h("span", {}, h("strong", {}, selado ? "SELADO" : "RASCUNHO"), h("small", {}, selado ? `assinado ${fmtData(ass[0]?.em)}` : "não assinado"))),
        h("div", { class: "hash-folha" }, h("p", { class: "rotulo-sec" }, selado ? "Hash raiz assinado" : "Hash raiz (confira antes de assinar)"),
          hashAgrupado(laudo.hash_raiz),
          selado && laudo.selo ? h("p", { class: "nota mono selo-txt" }, `Selo ${laudo.selo}`) : null))),
    h("section", {}, h("h3", {}, "Resumo"),
      h("p", {}, laudo.resumo?.texto || ""),
      h("div", { class: "contadores" }, Object.keys(ROT_CONT).map((k) => h("div", { class: `contador ${k}${cont[k] ? "" : " zero"}` },
        icone(IC_CONT[k]), h("b", {}, cont[k] || 0), h("span", {}, ROT_CONT[k]))))),
    h("section", {}, h("h3", {}, "Itens e prova"),
      h("p", { class: "nota" }, "Cada aspecto aponta para a evidência e para a checagem que deu o status. O status vem do verificador, nunca do modelo de linguagem."),
      h("div", { class: "tabela-rolagem" }, h("table", { class: "itens-laudo" },
        h("thead", {}, h("tr", {}, ["Aspecto", "Status", "Evidência → checagem", "Regra"].map((t) => h("th", { scope: "col" }, t)))),
        corpoTab))),
    h("section", {}, h("h3", {}, "Método e cadeia de evidências"),
      h("dl", { class: "kv" },
        meta("Método", metodo.rotulo || metodo.metodo),
        metodo.justificativa ? meta("Justificativa", metodo.justificativa) : null,
        meta("Regras (rulebook)", metodo.rulebook_versao, "mono"),
        meta("Status atribuído por", `${metodo.verificacao || "verificador"} (nunca pelo modelo de linguagem)`),
        meta("Cadeia de evidências", `${laudo.cadeia?.n} evidências · ${laudo.cadeia?.integra ? "íntegra" : "QUEBRADA"}`))),
    sr.length ? h("section", {}, h("h3", {}, "Sensoriamento remoto (MCR 2-7, item 4)"),
      sr.map((s) => h("dl", { class: "kv" }, Object.keys(ROT_SR).map((k) => meta(ROT_SR[k], s[k])))),
      (laudo.atribuicoes || []).map((a) => h("p", { class: "nota" }, `${a}.`))) : null,
    laudo.ocorrencias?.length ? h("section", {}, h("h3", {}, "Ocorrências registradas"),
      h("p", { class: "nota" }, "Pedidos recusados e instruções embutidas: ficam na cadeia de hash."),
      h("ul", { class: "ocorrencias" }, laudo.ocorrencias.map((o) => h("li", { title: o.id }, h("strong", {}, `${ROT_OCORRENCIA[o.tipo] || o.tipo}: `),
        semIds(o.descricao), h("span", { class: "nota" }, ` · ${fmtData(o.em)}`))))) : null,
    h("footer", { class: "folha-rodape" }, h("span", {}, icone("hash"), `Hash raiz ${String(laudo.hash_raiz || "").slice(0, 16)}…`),
      h("span", {}, selado ? "Documento selado: nenhuma alteração é possível." : "Rascunho: só vale depois da assinatura humana.")));

  const lado = h("aside", { class: "laudo-lado" }, painelAssinatura(fisId, estado, laudo, voltar, conferencia));
  // celular: o formulário de assinatura fica no fim de um documento longo; a barra de baixo leva ao laudo e à assinatura
  const irPara = (sel) => document.querySelector(sel)?.scrollIntoView({ block: "start", behavior: "smooth" });
  const barraMovel = h("nav", { class: "laudo-barra-movel", "aria-label": "Ir para" },
    h("button", { class: "btn btn-sec", type: "button", onclick: () => irPara(".folha") }, icone("cima"), "Revisar laudo"),
    h("button", { class: "btn btn-pri", type: "button", onclick: () => irPara("#assinar") }, icone(selado ? "selo" : "descer"),
      selado ? "Ver selo" : "Assinar"));
  raiz.replaceChildren(h("div", { class: "laudo-tela" }, cab, h("div", { class: "laudo-grade" }, folha, lado), barraMovel));
  observadorCab?.disconnect();
  const medirCab = () => document.documentElement.style.setProperty("--lc-h", `${cab.offsetHeight || 0}px`);
  medirCab();
  if ("ResizeObserver" in window) { observadorCab = new ResizeObserver(medirCab); observadorCab.observe(cab); }

  secaoTecnica("laudo", () => blocoTec("Laudo",
    h("dl", { class: "kv" }, meta("Tipo", laudo.tipo), meta("Hash raiz", laudo.hash_raiz, "mono"), laudo.selo ? meta("Selo", laudo.selo, "mono") : null,
      meta("Rulebook", metodo.rulebook_versao, "mono"), meta("Cadeia", `${laudo.cadeia?.n} evidências · ${laudo.cadeia?.integra ? "íntegra" : "QUEBRADA"}`)),
    h("div", { class: "grupo-btn" },
      h("a", { class: "btn btn-sec btn-peq", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo`, target: "_blank", rel: "noopener" }, icone("codigo"), "Laudo (JSON)"),
      h("a", { class: "btn btn-sec btn-peq", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/laudo.html`, target: "_blank", rel: "noopener" }, icone("doc"), "Laudo (HTML)"),
      h("a", { class: "btn btn-sec btn-peq", href: `/api/fiscalizacoes/${encodeURIComponent(fisId)}/trace`, target: "_blank", rel: "noopener" }, icone("trace"), "Trace (JSONL)"))));

  if (focarAssinatura) {
    // L32: o painel inteiro (carimbo, hash completo e PIN) fica à vista; o foco no PIN não rola a página de novo
    setTimeout(() => {
      document.getElementById("assinar")?.scrollIntoView({ block: "start", behavior: "auto" });
      document.getElementById("pin")?.focus({ preventScroll: true });
    }, 100);
  }
  if (abrirPacote && selado) gerarPacote(fisId);
}

// Pacote de exibição BCB/Justiça: ação humana, só depois de SELADO; sem LLM. Mostra o checklist "Ordem JF Rio
// Verde" com o status real de cada item e o link do ZIP (manifest sha256 de cada arquivo).
function botaoPacote(fisId, selado, info) {
  const btn = h("button", { class: `btn btn-peq ${selado ? "btn-pri" : "btn-sec"}`, type: "button", id: "btn-pacote", disabled: selado ? null : true,
    title: selado ? "ZIP com manifest sha256, GeoJSON, cenas do satélite, fundamento, memória de cálculo e checklist da ordem judicial"
      : "Liberado só depois de SELADO (assinatura humana com PIN)",
    onclick: () => gerarPacote(fisId) }, icone("baixar"), info?.gerado ? "Pacote de exibição" : "Baixar pacote");
  return btn;
}

async function gerarPacote(fisId) {
  const btn = document.getElementById("btn-pacote");
  if (btn) btn.disabled = true;
  try {
    const r = await api.pacote(fisId);
    const ck = r.checklist_ordem_jf || { itens: [] };
    const corpo = h("div", { class: "pacote" },
      r.demonstracao ? faixaDemonstracao(r.demonstracao) : null,
      h("div", { class: "pacote-topo" },
        h("div", {}, h("p", { class: "rotulo-sec" }, "Pacote de exibição para o BCB ou a Justiça"),
          h("p", { class: "pacote-resumo" }, `Checklist "Ordem JF Rio Verde": ${ck.resumo || ""}`)),
        h("a", { class: "btn btn-pri", href: r.url, download: r.nome || "" }, icone("baixar"), "Baixar pacote (ZIP)")),
      h("table", { class: "pacote-checklist" }, h("thead", {}, h("tr", {}, ["Item", "Status", "Motivo ou justificativa"].map((x) => h("th", { scope: "col" }, x)))),
        h("tbody", {}, ck.itens.map((it) => h("tr", {}, h("td", {}, it.titulo), h("td", {}, chipChecklist(it.status)),
          h("td", { class: "nota" }, it.justificativa || it.motivo || "—"))))),
      ck.nota ? h("p", { class: "nota" }, ck.nota) : null,
      r.por_que_na_amostra?.resumo ? h("p", { class: "nota" }, h("strong", {}, "Por que está na amostra: "), r.por_que_na_amostra.resumo) : null,
      h("dl", { class: "kv" }, h("dt", {}, "Arquivos"), h("dd", {}, `${r.n_arquivos} (manifest com sha256 de cada um)`),
        h("dt", {}, "sha256 do ZIP"), h("dd", {}, hashAgrupado(r.sha256_zip)),
        h("dt", {}, "Selo do laudo"), h("dd", { class: "mono" }, r.selo),
        h("dt", {}, "Prazo de contestação"), h("dd", {}, `${r.prazo_contestacao_dias} dias (termo de ciência do mutuário no ZIP)`)),
      r.faltas?.length ? h("p", { class: "nota", role: "alert" }, `Faltas: ${r.faltas.join("; ")}`) : null,
      h("div", { class: "grupo-btn" },
        h("a", { class: "btn btn-pri", href: r.url, download: r.nome || "" }, icone("baixar"), "Baixar pacote (ZIP)")));
    abrirModal("Pacote de exibição BCB/Justiça", corpo);
    anunciar(`Pacote de exibição gerado: ${ck.resumo || ""}`);
  } catch (e) {
    avisar(e.status === 409 ? "Pacote liberado só depois de SELADO (assinatura humana)." : `Pacote não gerado: ${e.message}`, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Conferência do selo (laudo.audit.selo): vem da resposta da assinatura (logo depois de selar) ou do estado.
function confSelo(conferencia, estado) {
  const c = conferencia || estado.laudo || {};
  return { conteudo_confere: c.conteudo_confere, verificacao: c.verificacao, avisos: c.avisos || c.avisos_verificacao || [] };
}

function blocoConferencia(conf) {
  if (!conf || conf.conteudo_confere === undefined || conf.conteudo_confere === null) return null;
  const ok = conf.conteudo_confere === true;
  return h("div", { class: `conferencia-selo ${ok ? "ok" : "falha"}`, role: ok ? "status" : "alert" },
    icone(ok ? "verificado" : "alerta"),
    h("div", {}, h("strong", {}, ok ? "Conteúdo confere com o rascunho assinado" : "Laudo selado não confere com o rascunho assinado"),
      h("div", { class: "nota" }, conf.verificacao || ""),
      (conf.avisos || []).filter((a) => !ok || !/não confere/.test(a)).map((a) => h("div", { class: "nota" }, a))));
}

function conferirHash(laudo, estado, conferencia, selado) {
  const ass = laudo.assinaturas || estado.assinaturas || [];
  const corpo = h("div", { class: "conferir" },
    h("p", {}, selado ? "O hash raiz resume todo o conteúdo do laudo. O selo prova que este é o rascunho que o fiscal conferiu e assinou."
      : "O hash raiz resume todo o conteúdo deste rascunho. Confira estes grupos de 4 caracteres antes de assinar."),
    h("p", { class: "rotulo-sec" }, "Hash raiz"), hashAgrupado(laudo.hash_raiz),
    h("div", { class: "grupo-btn" }, h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: () => copiar(laudo.hash_raiz, "Hash copiado") },
      icone("copiar"), "Copiar hash")),
    selado ? blocoConferencia(confSelo(conferencia, estado)) : null,
    ass.map((a) => {
      const igual = a.hash_assinado === laudo.hash_raiz;
      return h("div", { class: `conferencia-selo ${igual ? "ok" : "falha"}` }, icone(igual ? "verificado" : "alerta"),
        h("div", {}, h("strong", {}, igual ? "Hash assinado igual ao hash raiz" : "Hash assinado diferente do hash raiz"),
          h("div", { class: "nota" }, `${ROT_PAPEL[a.papel] || a.papel} · ${a.nome_ref} · ${fmtData(a.em)}`)));
    }),
    selado && laudo.selo ? [h("p", { class: "rotulo-sec" }, "Selo"), h("p", { class: "mono" }, laudo.selo)] : null);
  abrirModal("Conferência do hash", corpo);
}

function painelAssinatura(fisId, estado, laudo, voltar, conferencia) {
  if (laudo.tipo === "selado" || estado.etapa === "SELADO") {
    const ass = laudo.assinaturas || estado.assinaturas || [];
    return h("section", { class: "cartao painel-ass selado", id: "assinar", "aria-labelledby": "t-ass" },
      h("div", { class: "cab" }, h("h2", { id: "t-ass" }, "Assinatura humana"), h("span", { class: "carimbo selado" }, icone("selo"), "SELADO")),
      h("div", { class: "corpo" }, blocoConferencia(confSelo(conferencia, estado)),
        ass.map((a) => h("dl", { class: "kv" },
          h("dt", {}, "Papel"), h("dd", {}, ROT_PAPEL[a.papel] || a.papel), h("dt", {}, "Responsável"), h("dd", {}, a.nome_ref),
          h("dt", {}, "Assinado em"), h("dd", {}, fmtData(a.em)), h("dt", {}, "Hash assinado"), h("dd", {}, hashAgrupado(a.hash_assinado)))),
        h("p", { class: "nota" }, icone("cadeado"), " Selado: nenhuma alteração é possível; correção vira nova fiscalização (POL-04).")));
  }
  const pode = ["RASCUNHO", "ASSINATURA"].includes(estado.etapa) && estado.laudo?.tipo === "rascunho";
  const papel = h("select", { id: "papel" }, Object.entries(ROT_PAPEL).map(([v, t]) => h("option", { value: v }, t)));
  const nome = h("input", { type: "text", id: "nome-ref", value: "fiscal-demo", autocomplete: "off" });
  const pin = h("input", { type: "password", id: "pin", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "12", placeholder: "Digite o PIN",
    "aria-describedby": "erro-pin" });
  const conf = h("input", { type: "checkbox", id: "conf-hash", "aria-describedby": "erro-conf" });
  // erros junto do campo (vermelho, com ícone, role=alert); o motivo de o botão estar desligado fica à vista embaixo dele
  const erroConf = h("p", { class: "msg-ass erro", id: "erro-conf", role: "alert", hidden: true });
  const erroPin = h("p", { class: "msg-ass erro", id: "erro-pin", role: "alert", hidden: true });
  const motivo = h("p", { class: "motivo-btn", id: "motivo-ass" });
  const msg = h("p", { class: "msg-ass", role: "status" });
  const btn = h("button", { class: "btn btn-pri btn-bloco", type: "submit", disabled: true, "aria-describedby": "motivo-ass" },
    icone("assinar"), "Assinar com PIN");
  const erro = (el, campo, texto) => {
    el.hidden = !texto;
    el.replaceChildren(...(texto ? [icone("alerta"), h("span", {}, texto)] : []));
    campo.setAttribute("aria-invalid", texto ? "true" : "false");
  };
  const pinOk = () => pin.value.trim().length >= 4;
  const conferir = () => {
    const falta = !pode ? "Emita o rascunho primeiro."
      : !conf.checked ? "Marque que conferiu o hash raiz." : !pinOk() ? "Digite o PIN (4 dígitos)." : "";
    btn.disabled = !!falta || enviando;
    motivo.textContent = falta;
    motivo.hidden = !falta;
  };
  let enviando = false;
  conf.addEventListener("change", () => { if (conf.checked) erro(erroConf, conf, ""); conferir(); });
  pin.addEventListener("input", () => { erro(erroPin, pin, ""); conferir(); });
  const form = h("form", { class: "corpo assinatura", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    if (!conf.checked) { erro(erroConf, conf, "Marque que conferiu o hash raiz antes de assinar."); conf.focus(); return; }
    if (!pinOk()) { erro(erroPin, pin, "Digite o PIN (4 dígitos)."); pin.focus(); return; }
    enviando = true; conferir();
    try {
      const r = await api.assinar(fisId, { pin: pin.value, hash_confirmado: laudo.hash_raiz, papel: papel.value, nome_ref: nome.value });
      pin.value = "";
      const ok = r.estado?.etapa === "SELADO";
      tts.falar(r.fala_voz || r.resposta?.fala);
      anunciar(r.resposta?.fala || "", !ok);
      atualizarSaude();
      if (ok) {
        msg.textContent = r.resposta?.fala || "";
        limparErros(); // o "Assinatura recusada" de uma tentativa anterior não fica ao lado do "assinado e selado"
        const sel = r.resposta?.laudo || {};
        const confS = { conteudo_confere: sel.conteudo_confere, verificacao: sel.verificacao, avisos: r.resposta?.avisos || [] };
        if (sel.conteudo_confere === false) avisar("Laudo selado não confere com o rascunho assinado: veja o painel de assinatura.", true, 9000);
        else avisar("Laudo assinado e selado.");
        setTimeout(() => telaLaudo(document.getElementById("conteudo"), fisId, { voltar, conferencia: confS }), 400);
      } else if ((r.resposta?.avisos || []).some((a) => a.startsWith("laudo não selado"))) {
        erro(erroPin, pin, "Assinatura recusada: o rascunho em disco não é o assinado. Nada foi selado.");
        msg.textContent = r.resposta?.fala || "";
      } else {
        const n = r.tentativas_restantes;
        erro(erroPin, pin, `PIN não confere. Nada foi assinado${n !== undefined && n !== null ? `; ${n === 1 ? "resta 1 tentativa" : `restam ${n} tentativas`}` : ""}.`);
        pin.focus();
      }
    } catch (err) {
      erro(erroPin, pin, err.message);
      atualizarSaude();
    }
    enviando = false; conferir();
  } },
  // L32: o hash completo dentro do painel, ao lado do PIN (a banca vê o "confira o hash e assine")
  h("div", { class: "hash-ass" }, h("p", { class: "rotulo-sec" }, "Hash raiz que você vai assinar"), hashAgrupado(laudo.hash_raiz)),
  h("label", { class: "confere", for: "conf-hash" }, conf,
    h("span", {}, "Conferi o hash raiz deste rascunho e assumo a responsabilidade pela assinatura.")),
  erroConf,
  h("div", { class: "campos-ass" },
    h("div", { class: "campo" }, h("label", { for: "papel" }, "Papel"), papel),
    h("div", { class: "campo" }, h("label", { for: "nome-ref" }, "Responsável"), nome),
    h("div", { class: "campo campo-pin" }, h("label", { for: "pin" }, "PIN"), pin, erroPin)),
  btn,
  motivo,
  msg,
  h("p", { class: "nota" }, icone("escudo"), " O agente não assina: a assinatura é sempre humana (POL-03)."));
  conferir();
  return h("section", { class: "cartao painel-ass", id: "assinar", "aria-labelledby": "t-ass" },
    h("div", { class: "cab" }, h("h2", { id: "t-ass" }, "Assinar o laudo"),
      h("span", { class: "carimbo rascunho" }, "RASCUNHO")),
    !pode ? h("p", { class: "aviso-ass" }, icone("alerta"), estado.laudo?.valido_para_assinar === false
      ? "Há evidência nova depois do rascunho: emita de novo na fiscalização." : `Etapa ${estado.etapa}: emita o rascunho primeiro.`) : null,
    form);
}

async function verChecagem(fisId, chk, resumo) {
  const c = chk || {};
  const corpo = h("div", {},
    h("dl", { class: "kv" }, h("dt", {}, "Checagem"), h("dd", { title: resumo.ferramenta }, rotuloFerramenta(resumo.ferramenta)),
      h("dt", {}, "Status"), h("dd", {}, chipStatus(resumo.status)),
      h("dt", {}, "Fonte/versão"), h("dd", { class: "mono" }, c.fonte_versao || "—"), h("dt", {}, "Resumo"), h("dd", {}, semIds(c.resumo) || "—"),
      h("dt", {}, "Evidências"), h("dd", {}, `${(c.evidencias || []).length || "—"}`)),
    c.prova?.quadros?.length ? h("div", { class: "quadros" }, c.prova.quadros.map((q) => h("figure", {},
      h("img", { src: q.url, alt: `quadro-chave em ${q.t_s} s` }), h("figcaption", {}, `${q.t_s} s · ${q.contagem_ate_aqui} contados`)))) : null,
    c.prova?.foto_url ? h("img", { class: "foto", src: c.prova.foto_url, alt: "foto da evidência" }) : null,
    c.prova?.criterios?.length ? h("table", { class: "crit" }, h("tbody", {}, c.prova.criterios.map((k) =>
      h("tr", {}, h("td", { title: k.regra_id || "" }, String(k.campo || "").split(":").pop().replaceAll("_", " ")), h("td", {}, chipStatus(k.status)), h("td", {}, k.motivo))))) : null,
    resumo.span_id ? h("div", { class: "grupo-btn" }, h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: () => verSpan(fisId, resumo.span_id) },
      icone("trace"), "Abrir no trace")) : null);
  abrirModal(rotuloFerramenta(resumo.ferramenta), corpo);
}

async function verSpan(fisId, spanId) {
  try {
    const r = await api.spans(fisId, spanId);
    abrirModal(`Trace — registro ${spanId}`, h("div", {}, (r.spans || []).map((s) => h("div", { class: `span${s.span_id === spanId ? " alvo" : ""}` },
      h("h3", {}, s.name), h("div", { class: "nota mono" }, `${s.span_id} · ${s.status} · ${s.duration_ms ?? "?"} ms`),
      h("dl", { class: "kv" }, Object.entries(s.attributes || {}).map(([k, v]) => [h("dt", { class: "mono" }, k), h("dd", { class: "mono" }, fmtNum(v))]))))));
  } catch (e) { avisar(e.message, true); }
}

