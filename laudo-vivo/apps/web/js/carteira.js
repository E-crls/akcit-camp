// Tela da carteira (analista da cooperativa): casos de demonstração no topo, mapa de GO com as operações coloridas
// (e marcadas por letra/forma) pela prioridade de verificação e a lista lado a lado. "Abrir fiscalização" abre o caso.

import { api } from "./api.js";
import { COR_PRIO, criarMapa, desenharContorno, iconePrioridade, leafletDisponivel, mapaSVG } from "./mapa.js";
import { avisar, fmtNum, h, icone } from "./ui.js";

const ROT_PRIO = { alta: "Prioridade alta", media: "Prioridade média", baixa: "Prioridade baixa", sem_sinal: "Sem sinal", demo: "Demonstração" };
const CURTO_PRIO = { alta: "Alta", media: "Média", baixa: "Baixa", sem_sinal: "Sem sinal", demo: "Demo" };
const LETRA = { alta: "A", media: "M", baixa: "B", demo: "D", sem_sinal: "·" };
let mapa = null;
let marcadores = new Map();
let camadas = [];

function badgePrio(nivel, pontos) {
  return h("span", { class: `prio ${nivel}`, title: ROT_PRIO[nivel] || nivel },
    h("span", { class: `marcador mini ${nivel}`, "aria-hidden": "true" }, h("span", {}, LETRA[nivel] || "")),
    CURTO_PRIO[nivel] || nivel, pontos !== undefined && pontos !== null ? h("span", { class: "prio-pt" }, `${pontos} pt`) : null);
}

export async function telaCarteira(raiz, { abrirFis }) {
  const avisoMapa = h("div", { class: "mapa-aviso", hidden: true, role: "status" });
  const elMapa = h("div", { class: "mapa", id: "mapa-carteira", role: "region", "aria-label": "Mapa das operações de Goiás" });
  const legenda = h("div", { class: "legenda" }, h("strong", {}, "Prioridade de verificação"),
    h("ul", {}, ["alta", "media", "baixa", "demo"].map((n) => h("li", {}, h("span", { class: `marcador ${n}` },
      h("span", {}, LETRA[n])), ROT_PRIO[n]))));
  // esqueletos com a altura final enquanto carrega (a tela não pula quando os dados chegam)
  const lista = h("ol", { class: "ops", "aria-label": "Operações ordenadas por prioridade", "aria-busy": "true" },
    [1, 2, 3].map(() => h("li", { class: "op esqueleto", "aria-hidden": "true" }, h("i"), h("i"), h("i"))));
  const casosBox = h("div", { class: "casos-lista", "aria-busy": "true" },
    [1, 2].map(() => h("div", { class: "caso esqueleto", "aria-hidden": "true" }, h("i"), h("i"))));
  const fMun = h("input", { type: "search", id: "f-mun", placeholder: "Município (ex.: Goiânia)", autocomplete: "off",
    "aria-label": "Filtrar por município" });
  const fPrio = h("select", { id: "f-prio", "aria-label": "Prioridade mínima" }, h("option", { value: "1" }, "Todas as prioridades"),
    h("option", { value: "2" }, "Média ou alta"), h("option", { value: "4" }, "Só alta"));
  const resumo = h("p", { class: "nota resumo-lista", role: "status" }, "Carregando a carteira…");
  const form = h("form", { class: "filtros", role: "search", onsubmit: (e) => { e.preventDefault(); carregar(); } },
    h("label", { class: "campo-busca" }, icone("lupa"), fMun), fPrio,
    h("button", { class: "btn btn-sec", type: "submit" }, "Filtrar"));
  const avisoTri = h("p", { class: "aviso-triagem" });
  raiz.replaceChildren(h("div", { class: "carteira" },
    h("div", { class: "pagina-cab" },
      h("div", {}, h("h1", { id: "t-cart" }, "Carteira de fiscalização"),
        h("p", { class: "nota" }, "Goiás 2026 · operações do Sicor/BCB ordenadas pela prioridade de verificação")),
      form),
    h("section", { class: "casos-demo", "aria-labelledby": "t-casos" },
      h("div", { class: "casos-cab" }, h("h2", { id: "t-casos" }, "Casos de demonstração"),
        h("span", { class: "etiqueta fake" }, "dados sintéticos"),
        h("span", { class: "nota" }, "Operações fictícias, com defeitos plantados para a demonstração.")),
      casosBox),
    h("div", { class: "carteira-grade" },
      h("section", { class: "cartao mapa-wrap", "aria-label": "Mapa" },
        h("div", { class: "mapa-area" }, elMapa, legenda, avisoMapa)),
      h("section", { class: "cartao lista-ops", "aria-labelledby": "t-lista" },
        h("div", { class: "cab" }, h("h2", { id: "t-lista" }, "Amostra para fiscalizar"), resumo),
        lista, avisoTri))));

  if (mapa) { mapa.remove(); mapa = null; }
  marcadores = new Map();
  if (leafletDisponivel()) {
    mapa = criarMapa(elMapa, { aviso: avisoMapa });
    api.contornoGO().then((c) => desenharContorno(mapa, c)).catch(() => {});
  }

  function selecionar(chave, rolar = true) {
    lista.querySelectorAll(".op").forEach((li) => li.classList.toggle("ativo", li.dataset.chave === chave));
    const li = lista.querySelector(`[data-chave="${CSS.escape(chave)}"]`);
    if (li && rolar) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const m = marcadores.get(chave);
    if (m && mapa) { mapa.setView(m.getLatLng(), Math.max(mapa.getZoom(), 12)); m.openPopup(); }
  }

  async function abrir(o) {
    try {
      const est = o.caso_id ? await api.abrirCaso(o.caso_id, true) : await api.abrirRef(o.ref_bacen);
      abrirFis(est.id);
    } catch (e) { avisar(`Não abri a fiscalização: ${e.message}`, true); }
  }

  function desenhar(itens) {
    camadas.forEach((c) => c.remove());
    camadas = [];
    marcadores = new Map();
    if (!mapa) {
      mapaSVG(elMapa, itens, (o) => selecionar(o.chave));
      return;
    }
    const L = window.L;
    const limites = [];
    for (const o of itens) {
      const cor = COR_PRIO[o.nivel] || "#555";
      for (const anel of o.glebas || []) {
        const p = L.polygon(anel, { color: cor, weight: 2, fillOpacity: 0.25 }).addTo(mapa);
        p.on("click", () => selecionar(o.chave));
        camadas.push(p);
        limites.push(...anel);
      }
      if (o.lat && o.lon) {
        const mk = L.marker([o.lat, o.lon], { icon: iconePrioridade(o.nivel), title: `${o.titulo} — ${ROT_PRIO[o.nivel] || o.nivel}`,
          keyboard: true, alt: o.titulo });
        const pop = h("div", { class: "pop" }, h("strong", {}, o.titulo), h("div", { class: "nota" }, ROT_PRIO[o.nivel] || ""),
          o.local ? h("div", { class: "nota" }, o.local) : null,
          h("button", { class: "btn btn-pri btn-peq", type: "button", onclick: () => abrir(o) }, "Abrir fiscalização"));
        mk.bindPopup(pop);
        mk.on("click", () => selecionar(o.chave, true));
        mk.addTo(mapa);
        camadas.push(mk);
        marcadores.set(o.chave, mk);
        limites.push([o.lat, o.lon]);
      }
    }
    if (limites.length) mapa.fitBounds(L.latLngBounds(limites).pad(0.08), { maxZoom: 11 });
    setTimeout(() => mapa.invalidateSize(), 60);
  }

  function itemLista(o) {
    const motivo = o.motivos?.length ? o.motivos.join("; ") : "sem motivo de triagem";
    return h("li", { class: "op", dataset: { chave: o.chave }, tabindex: "0",
      "aria-label": `${o.titulo}, ${ROT_PRIO[o.nivel] || o.nivel}, ${o.local}. Enter abre a fiscalização.`,
      onclick: () => selecionar(o.chave, false), ondblclick: () => abrir(o),
      onkeydown: (e) => { if (e.key === "Enter" && e.target === e.currentTarget) abrir(o); } },
    h("div", { class: "op-l1" }, badgePrio(o.nivel, o.pontos), h("strong", { class: "op-titulo" }, o.titulo),
      o.valor ? h("span", { class: "op-valor" }, o.valor) : null),
    h("div", { class: "op-l2" }, icone("pino"), h("span", {}, o.local)),
    h("div", { class: "op-motivo", title: motivo }, motivo),
    h("div", { class: "op-acoes" },
      h("button", { class: "btn btn-sec btn-peq", type: "button", onclick: (e) => { e.stopPropagation(); abrir(o); } },
        "Abrir fiscalização", icone("direita"))));
  }

  function cartaoCaso(c) {
    const [cod, ...resto] = String(c.titulo || "").split(": ");
    const nome = resto.length ? resto.join(": ") : cod;
    return h("article", { class: `caso${c.padrao ? " padrao" : ""}`, title: c.descricao || null },
      h("div", { class: "caso-ic", "aria-hidden": "true" }, h("span", { class: "marcador demo" }, h("span", {}, "D"))),
      h("div", { class: "caso-txt" },
        h("div", { class: "caso-l1" }, h("strong", {}, nome), c.padrao ? h("span", { class: "etiqueta destaque" }, "demo do palco") : null),
        h("div", { class: "nota" }, [resto.length ? cod : null, c.municipio, c.n_passos ? `${c.n_passos} passos de roteiro` : null,
          c.nivel_rotulo ? `prioridade ${c.nivel_rotulo}` : null].filter(Boolean).join(" · "))),
      c.padrao ? h("button", { class: "btn btn-pri", type: "button", onclick: () => abrir(c) }, icone("play"), "Abrir fiscalização")
        : h("button", { class: "btn btn-sec", type: "button", onclick: () => abrir(c), title: "Caso de teste (não é o da demo do palco)" },
          "Abrir caso de teste"));
  }

  // Sem a API, a tela diz que deu errado (antes parecia uma carteira vazia: "0 operações").
  function estadoErro(e) {
    const tentar = () => carregar();
    const caixa = (txt) => h("div", { class: "erro-carga", role: "alert" }, icone("alerta"),
      h("div", {}, h("strong", {}, txt), h("p", { class: "nota" }, e.rede ? "Confira a conexão com o servidor." : e.message)),
      h("button", { class: "btn btn-sec", type: "button", onclick: tentar }, icone("reiniciar"), "Tentar de novo"));
    resumo.textContent = "Carteira indisponível";
    resumo.removeAttribute("title");
    lista.removeAttribute("aria-busy");
    casosBox.removeAttribute("aria-busy");
    lista.replaceChildren(h("li", { class: "op-erro" }, caixa("Não foi possível carregar a carteira.")));
    casosBox.replaceChildren(caixa("Não foi possível carregar os casos de demonstração."));
    avisoTri.replaceChildren(icone("info"), h("span", {}, "Prioridade de verificação não é indício de irregularidade."));
    desenhar([]);
  }

  async function carregar() {
    resumo.textContent = "Carregando…";
    let dados;
    try {
      dados = await api.carteira({ limite: 60, municipio: fMun.value.trim(), prioridade_minima: fPrio.value });
    } catch (e) {
      estadoErro(e);
      return;
    }
    lista.removeAttribute("aria-busy");
    casosBox.removeAttribute("aria-busy");
    // L56: o caso padrão (o da demo do palco) vem primeiro e é o único com o botão primário
    const casos = [...(dados.casos || [])].sort((a, b) => (b.padrao ? 1 : 0) - (a.padrao ? 1 : 0)).map((c) => ({
      chave: `caso:${c.id}`, caso_id: c.id, padrao: !!c.padrao, nivel: "demo", titulo: c.titulo, ref_bacen: c.ref_bacen,
      municipio: c.municipio, n_passos: c.n_passos, descricao: c.descricao, nivel_rotulo: c.amostra?.nivel_rotulo,
      local: c.municipio || "", motivos: c.triagem?.motivos || [], glebas: c.glebas, lat: c.lat, lon: c.lon,
    }));
    const ops = (dados.operacoes || []).map((o) => ({
      chave: `op:${o.ref_bacen}`, ref_bacen: o.ref_bacen, nivel: o.prioridade_nivel, pontos: o.prioridade_verificacao,
      titulo: `Operação ${o.ref_bacen}`, valor: o.valor_rs ? `R$ ${fmtNum(o.valor_rs)}` : "",
      local: [o.municipio_nome || "município ?", o.instituicao, o.qtd_bovinos ? `${fmtNum(o.qtd_bovinos)} ${o.unidade_qtd_bovinos || ""}`.trim() : null,
        o.lotacao_implicita_cab_ha ? `lotação ${fmtNum(o.lotacao_implicita_cab_ha)}/ha` : null].filter(Boolean).join(" · "),
      motivos: (o.motivos || []).map((m) => m.replace(/\s*\(\+\d+\)\s*$/, "")), glebas: o.glebas, lat: o.lat, lon: o.lon,
    }));
    casosBox.replaceChildren(...casos.map(cartaoCaso));
    lista.replaceChildren(...(ops.length ? ops.map(itemLista) : [h("li", { class: "vazio" }, "Nenhuma operação neste filtro.")]));
    if (dados.ok !== false) {
      const pn = dados.por_nivel || {};
      resumo.textContent = `${fmtNum(dados.total_filtrado)} operações · alta ${pn.alta || 0} · média ${pn.media || 0} · baixa ${pn.baixa || 0}` +
        (ops.length < (dados.total_filtrado || 0) ? ` · mostrando ${ops.length}` : "");
      resumo.title = `Fonte: ${dados.fonte_versao || "Fiscal-GO 2026"}`;
    }
    avisoTri.replaceChildren(icone("info"), h("span", {}, dados.aviso || "Prioridade de verificação não é indício de irregularidade."));
    desenhar([...casos, ...ops]);
  }
  await carregar();
}
