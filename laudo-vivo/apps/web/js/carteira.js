// Carteira (analista da cooperativa): a lista das operações na amostra e o mapa de Goiás. Selecionar uma operação abre
// o balão com o porquê da amostra em linguagem simples e o único botão cheio da tela, "Abrir fiscalização". O caso de
// demonstração tem o piquete D e, no modo apresentação (ou com ?demo), já abre selecionado, com o balão aberto. No topo,
// o placar da amostra (operações, prioridade alta e o total financiado), calculado dos dados que a API devolveu.

import { api } from "./api.js";
import { placar } from "./componentes.js";
import { cor, criarMapaCarteira, desenharContorno, iconeOperacao, leafletDisponivel } from "./mapa.js";
import { localOperacao, motivoSimples, nomeOperacao, objetoCarteira } from "./regras.js";
import { definirTela, modoDemo } from "./sessao.js";
import { avisar, blocoAmostra, blocoTec, definirDemo, definirTopo, ehMovel, h, icone, kv, secaoTecnica, simbolo } from "./ui.js";

const ROT_NIVEL = { alta: "Alta", media: "Média", baixa: "Baixa", sem_sinal: "Sem sinal" };
let mapa = null;

export async function telaCarteira(raiz, { abrirFis, saude = null }) {
  // na gravação da demonstração (replay), só o caso gravado responde: as outras operações abrem no modo ao vivo
  const replay = saude?.llm?.tipo === "replay";
  definirTela("carteira");
  definirTopo({ trilha: [{ rot: "Carteira" }], casa: true });
  const S = { ops: [], casos: [], filtro: "todas", busca: "", sel: null, dados: null, marcadores: new Map(), mapaAberto: false };

  const resumo = h("p", { class: "t-sec", role: "status" }, "Carregando a carteira…");
  const elPlacar = h("div", { class: "placar-cart", "aria-label": "A amostra em números" });
  const inBusca = h("input", { type: "search", id: "busca-op", placeholder: "Buscar município ou operação", autocomplete: "off",
    "aria-label": "Buscar município ou operação" });
  const seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Prioridade" });
  const lista = h("div", { class: "lista-ops", "aria-busy": "true" }, [1, 2, 3, 4].map(() => h("div", { class: "op esqueleto", "aria-hidden": "true" })));
  const elMapa = h("div", { class: "mapa-leaflet", id: "mapa-carteira", role: "region", "aria-label": "Mapa das operações de Goiás" });
  const legenda = h("div", { class: "legenda" });
  const balaoMapa = h("div", { class: "balao-pos", hidden: true });
  const btnMapa = h("button", { class: "btn btn-sec btn-ver-mapa", type: "button", "aria-expanded": "false", onclick: () => alternarMapa() },
    icone("mapa"), "Ver no mapa");
  const colMapa = h("section", { class: "cart-mapa", "aria-label": "Mapa" }, elMapa, legenda, balaoMapa);
  const tela = h("div", { class: "carteira" },
    h("aside", { class: "cart-lado" },
      h("div", { class: "lado-cab" }, h("h1", { class: "t-titulo" }, "Carteira"), resumo, elPlacar,
        h("label", { class: "busca", for: "busca-op" }, icone("busca"), inBusca), seg, btnMapa),
      lista),
    colMapa);
  raiz.replaceChildren(tela);

  if (mapa) { mapa.remove(); mapa = null; }
  if (leafletDisponivel()) {
    mapa = criarMapaCarteira(elMapa);
    api.contornoGO().then((c) => desenharContorno(mapa, c)).catch(() => {});
    mapa.on("move zoom", posicionarBalao);
  } else elMapa.append(h("p", { class: "mapa-vazio" }, "Mapa indisponível neste navegador."));

  function alternarMapa(abrir) {
    S.mapaAberto = abrir === undefined ? !S.mapaAberto : abrir;
    tela.classList.toggle("mapa-aberto", S.mapaAberto);
    btnMapa.setAttribute("aria-expanded", S.mapaAberto ? "true" : "false");
    btnMapa.lastChild.textContent = S.mapaAberto ? "Esconder o mapa" : "Ver no mapa";
    setTimeout(() => { mapa?.invalidateSize(); posicionarBalao(); }, 60);
  }

  // ---------------------------------------------------------------- dados
  let tBusca = 0;
  inBusca.addEventListener("input", () => { clearTimeout(tBusca); tBusca = setTimeout(() => { S.busca = inBusca.value.trim(); carregar(); }, 350); });

  async function carregar() {
    lista.setAttribute("aria-busy", "true");
    let dados;
    try {
      dados = await api.carteira({ limite: 60, municipio: S.busca, prioridade_minima: 1 });
    } catch (e) { erro(e); return; }
    S.dados = dados;
    S.casos = (dados.casos || []).filter((c) => c.padrao).map((c) => ({
      chave: `caso:${c.id}`, caso_id: c.id, nivel: "demo", nivelReal: c.triagem?.prioridade_nivel || c.amostra?.nivel || "media",
      titulo: nomeOperacao({ itens: c.itens || [] }) || c.titulo, curto: nomeOperacao({ itens: c.itens || [] }, true),
      local: localOperacao({ municipio_nome: c.municipio, uf: "GO" }), valor: c.valor_rs ? `R$ ${Number(c.valor_rs).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}` : "",
      motivos: c.triagem?.motivos || [], amostra: c.amostra, glebas: c.glebas, lat: c.lat, lon: c.lon, demo: c.demonstracao,
      animal: (c.itens || []).find((i) => i.categoria_animal)?.categoria_animal?.split(" ")[0] }));
    S.ops = (dados.operacoes || []).map((o) => ({
      chave: `op:${o.ref_bacen}`, ref_bacen: o.ref_bacen, nivel: o.prioridade_nivel, local: localOperacao({ municipio_nome: o.municipio_nome, uf: "GO" }),
      objeto: objetoCarteira(o), valor: o.valor_rs ? `R$ ${Number(o.valor_rs).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}` : "", valor_rs: Number(o.valor_rs) || 0, motivos: o.motivos || [],
      amostra: o.amostra, glebas: o.glebas, lat: o.lat, lon: o.lon, titulo: `${o.municipio_nome}/GO` }));
    lista.removeAttribute("aria-busy");
    const n = S.ops.length;
    resumo.textContent = S.busca ? `${n} ${n === 1 ? "operação encontrada" : "operações encontradas"}`
      : `Goiás · ${n} operações na amostra, de ${Number(dados.total_filtrado || n).toLocaleString("pt-BR")}`;
    if (S.sel === null && (modoDemo() || document.body.classList.contains("apresentacao")) && S.casos[0]) S.sel = S.casos[0].chave;
    render();
    desenhar();
    secaoTecnica("carteira", () => {
      const o = [...S.casos, ...S.ops].find((x) => x.chave === S.sel);
      return h("div", {}, blocoTec("Carteira", kv([["Fonte", dados.fonte_versao || "—"], ["Total na base", String(dados.total_filtrado ?? "—")],
        ["Por nível", Object.entries(dados.por_nivel || {}).map(([k, v]) => `${k} ${v}`).join(" · ")], ["Contorno do estado", "IBGE"]]),
      h("p", { class: "t-sec" }, dados.aviso || "")), o ? blocoAmostra(o.amostra, o.motivos) : null);
    });
  }

  function erro(e) {
    lista.removeAttribute("aria-busy");
    resumo.textContent = "Carteira indisponível";
    lista.replaceChildren(h("div", { class: "vazio", role: "alert" }, h("p", {}, "Não foi possível carregar a carteira."),
      h("p", { class: "t-sec" }, e.rede ? "Confira a conexão com o servidor." : e.message),
      h("button", { class: "btn btn-sec", type: "button", onclick: carregar }, icone("recomecar"), "Tentar de novo")));
  }

  // ---------------------------------------------------------------- lista
  function visiveis() { return S.ops.filter((o) => S.filtro === "todas" || o.nivel === S.filtro); }

  function render() {
    const cont = { alta: 0, media: 0, baixa: 0 };
    S.ops.forEach((o) => { cont[o.nivel] = (cont[o.nivel] || 0) + 1; });
    const opc = [["todas", `Todas · ${S.ops.length}`], ...["alta", "media", "baixa"].filter((k) => cont[k]).map((k) => [k, `${ROT_NIVEL[k]} · ${cont[k]}`])];
    // placar da amostra (some durante a busca: ele fala da amostra inteira)
    const total = S.ops.reduce((s, o) => s + o.valor_rs, 0);
    elPlacar.hidden = !!S.busca || !S.ops.length;
    elPlacar.replaceChildren(...(elPlacar.hidden ? [] : [placar([
      { n: S.ops.length.toLocaleString("pt-BR"), rot: S.ops.length === 1 ? "operação na amostra" : "operações na amostra" },
      { n: (cont.alta || 0).toLocaleString("pt-BR"), rot: "de prioridade alta", cls: "alta" },
      total >= 1e6 ? { pre: "R$", n: (total / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 }), un: "mi", rot: "financiados na amostra" }
        : { pre: "R$", n: Math.round(total / 1e3).toLocaleString("pt-BR"), un: "mil", rot: "financiados na amostra" },
    ])]));
    seg.replaceChildren(...opc.map(([k, t]) => h("button", { type: "button", role: "radio", "aria-checked": S.filtro === k ? "true" : "false",
      class: S.filtro === k ? "on" : "", onclick: () => { S.filtro = k; render(); desenhar(); } }, t)));
    const nos = [];
    if (!S.busca) nos.push(h("div", { class: "casos-demo" }, S.casos.map(cartaoCaso)));
    const ops = visiveis();
    if (ops.length) {
      nos.push(h("h2", { class: "rotulo-secao" }, "Amostra para fiscalizar"));
      nos.push(h("ul", { class: "ops", role: "list" }, ops.map(itemOp)));
    } else if (S.busca) {
      nos.push(h("div", { class: "vazio" }, h("p", {}, "Nenhuma operação com esse nome. Tente o município."),
        h("button", { class: "btn btn-sec", type: "button", onclick: () => { inBusca.value = ""; S.busca = ""; carregar(); } }, "Limpar busca")));
    }
    lista.replaceChildren(...nos);
    renderLegenda();
    renderBalao();
  }

  function cartaoCaso(c) {
    const sel = S.sel === c.chave;
    return h("div", { class: `demo-card${sel ? " sel" : ""}`, dataset: { chave: c.chave }, "aria-current": sel ? "true" : null },
      h("button", { class: "card-alvo", type: "button", "aria-label": `${c.titulo}, ${c.local}. Selecionar`, onclick: () => selecionar(c.chave) }),
      simbolo("pino-demo", "pino-demo"),
      h("span", { class: "txt" }, h("strong", {}, c.titulo), h("span", { class: "t-sec" }, `${c.local} · Prioridade ${ROT_NIVEL[c.nivelReal]?.toLowerCase() || "média"}`)),
      // "Abrir" abre a fiscalização de uma vez (o cartão inteiro seleciona e mostra o porquê no mapa)
      sel ? null : h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: (e) => { e.stopPropagation(); abrir(c); } }, "Abrir"),
      sel && ehMovel() ? balao(c) : null);
  }

  function itemOp(o) {
    const sel = S.sel === o.chave;
    return h("li", { class: `op${sel ? " sel" : ""}`, dataset: { chave: o.chave } },
      h("button", { class: "op-alvo", type: "button", "aria-pressed": sel ? "true" : "false", onclick: () => selecionar(o.chave) },
        h("span", { class: `ponto ${o.nivel}`, "aria-hidden": "true" }),
        h("span", { class: "txt" }, h("strong", {}, o.local), h("span", {}, `${o.objeto}${o.valor ? ` · ${o.valor}` : ""}`)),
        h("span", { class: "nv" }, ROT_NIVEL[o.nivel] || "")),
      sel && ehMovel() ? balao(o) : null);
  }

  function renderLegenda() {
    legenda.replaceChildren(...[h("strong", {}, "Prioridade de visita"),
      h("span", { class: "l" }, h("span", { class: "ponto alta" }), "Alta"), h("span", { class: "l" }, h("span", { class: "ponto media" }), "Média"),
      S.casos.length ? h("span", { class: "l" }, simbolo("pino-demo", "pino-demo pino-leg"), "Caso da demonstração") : null,
      S.sel ? null : h("span", { class: "l aviso-leg" }, icone("info"), "Prioridade não é indício de irregularidade.")].filter(Boolean));
  }

  // ---------------------------------------------------------------- balão da operação selecionada
  function balao(o) {
    const demo = o.nivel === "demo";
    const nivel = demo ? o.nivelReal : o.nivel;
    const motivo = (o.motivos || []).map((m) => motivoSimples(m, demo && o.animal ? `${o.animal}s`.replace(/ss$/, "s") : "animais")).join("; ");
    return h("div", { class: "balao-op", role: "dialog", "aria-label": `Operação selecionada: ${o.local}`, dataset: demo ? { caso: o.caso_id } : { ref: o.ref_bacen } },
      h("span", { class: "nivel" }, h("span", { class: `ponto ${nivel}` }), `Prioridade ${ROT_NIVEL[nivel]?.toLowerCase() || ""}`),
      h("h3", {}, o.local),
      h("p", { class: "t-sec" }, [demo ? o.curto : o.objeto, o.valor].filter(Boolean).join(" · ")),
      motivo ? h("p", { class: "porque" }, h("strong", {}, "Por que está na amostra: "), motivo.endsWith(".") ? motivo : `${motivo}.`) : null,
      h("p", { class: "nao-indicio" }, icone("info"), "Prioridade não é indício de irregularidade: só orienta onde a visita rende mais."),
      replay && !demo
        ? [h("button", { class: "btn btn-sec btn-cheio", type: "button", disabled: true, "aria-describedby": `so-ao-vivo-${o.ref_bacen}` }, "Abrir fiscalização"),
          h("p", { class: "t-sec so-ao-vivo", id: `so-ao-vivo-${o.ref_bacen}` }, "Esta apresentação roda a gravação do caso de demonstração: esta operação abre no modo ao vivo.")]
        : h("button", { class: "btn btn-pri btn-cheio", type: "button", onclick: () => abrir(o) }, "Abrir fiscalização", icone("direita")));
  }

  function renderBalao() {
    const o = [...S.casos, ...S.ops].find((x) => x.chave === S.sel);
    if (!o || ehMovel() || !mapa) { balaoMapa.hidden = true; balaoMapa.replaceChildren(); return; }
    balaoMapa.replaceChildren(balao(o), h("button", { class: "btn-icone balao-fechar", type: "button", "aria-label": "Fechar o balão",
      onclick: () => { S.sel = null; render(); desenhar(); } }, icone("x")));
    balaoMapa.hidden = false;
    balaoMapa._ll = o.lat && o.lon ? [o.lat, o.lon] : null;
    posicionarBalao();
  }

  function posicionarBalao() {
    if (!mapa || balaoMapa.hidden || !balaoMapa._ll) return;
    const p = mapa.latLngToContainerPoint(balaoMapa._ll);
    const W = elMapa.clientWidth; const H = elMapa.clientHeight;
    const bw = balaoMapa.offsetWidth || 348; const bh = balaoMapa.offsetHeight || 300;
    const direita = p.x + 36 + bw <= W - 12;
    const x = direita ? p.x + 36 : Math.max(12, p.x - 36 - bw);
    const y = Math.min(Math.max(12, p.y - bh * 0.4), Math.max(12, H - bh - 12));
    balaoMapa.style.left = `${x}px`;
    balaoMapa.style.top = `${y}px`;
    balaoMapa.classList.toggle("a-esquerda", !direita);
    balaoMapa.style.setProperty("--seta-y", `${Math.min(Math.max(20, p.y - y), bh - 20)}px`);
  }

  function selecionar(chave) {
    S.sel = S.sel === chave && ehMovel() ? null : chave;
    render();
    desenhar(false);
    const o = [...S.casos, ...S.ops].find((x) => x.chave === S.sel);
    if (o && mapa && o.lat) {
      const p = mapa.latLngToContainerPoint([o.lat, o.lon]);
      if (p.x < 40 || p.y < 40 || p.x > elMapa.clientWidth - 420 || p.y > elMapa.clientHeight - 40) mapa.panTo([o.lat, o.lon]);
    }
    lista.querySelector(`[data-chave="${CSS.escape(chave)}"]`)?.scrollIntoView({ block: "nearest" });
  }

  async function abrir(o) {
    try {
      const est = o.caso_id ? await api.abrirCaso(o.caso_id, true) : await api.abrirRef(o.ref_bacen);
      abrirFis(est.id);
    } catch (e) { avisar(`Não abri a fiscalização: ${e.message}`, true); }
  }

  // ---------------------------------------------------------------- mapa
  function desenhar(enquadrar = true) {
    if (!mapa) return;
    const L = window.L;
    S.marcadores.forEach((m) => m.remove());
    S.marcadores = new Map();
    S.camadas?.forEach((c) => c.remove());
    S.camadas = [];
    const itens = [...S.casos, ...visiveis()];
    const limites = [];
    for (const o of itens) {
      if (!o.lat || !o.lon) continue;
      const sel = o.chave === S.sel;
      if (sel) for (const anel of o.glebas || []) S.camadas.push(L.polygon(anel, { color: cor("--carvao"), weight: 2.5, fillColor: cor("--ipe"), fillOpacity: 0.35, interactive: false }).addTo(mapa));
      const mk = L.marker([o.lat, o.lon], { icon: iconeOperacao(o.nivel, sel), title: `${o.local}${o.nivel === "demo" ? " (demonstração)" : ""}`,
        keyboard: true, alt: o.local, zIndexOffset: sel ? 1000 : o.nivel === "demo" ? 500 : 0 });
      mk.on("click", () => selecionar(o.chave));
      mk.addTo(mapa);
      S.marcadores.set(o.chave, mk);
      limites.push([o.lat, o.lon]);
    }
    if (enquadrar && limites.length && !S.enquadrado) {
      mapa.fitBounds(L.latLngBounds(limites).pad(0.08), { paddingTopLeft: [10, 10], paddingBottomRight: [ehMovel() ? 10 : 380, 60] });
      S.enquadrado = true;
    }
    setTimeout(() => { mapa?.invalidateSize(); posicionarBalao(); }, 60);
  }

  const aoLayout = () => { if (!tela.isConnected) { window.removeEventListener("lv:layout", aoLayout); return; } render(); setTimeout(() => mapa?.invalidateSize(), 60); };
  window.addEventListener("lv:layout", aoLayout);
  await carregar();
  // a marca de demonstração aparece sempre que a carteira traz o caso de demonstração (dados sintéticos)
  definirDemo(S.casos[0]?.demo || null);
}
