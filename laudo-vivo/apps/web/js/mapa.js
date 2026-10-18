// Mapa: Leaflet (vendorizado) com tiles do OpenStreetMap quando há internet. Sem internet, o mapa fica sem
// fundo, com o contorno de Goiás (IBGE) e as glebas em vetor. Se nem o Leaflet carregar, desenha SVG puro.

import { h } from "./ui.js";

const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
export const COR_PRIO = { alta: "#a1191c", media: "#b35f00", baixa: "#4f6475", sem_sinal: "#8b98a5", demo: "#4a3b94" };
export const LETRA_PRIO = { alta: "A", media: "M", baixa: "B", sem_sinal: "·", demo: "D" };

export function leafletDisponivel() { return typeof window.L !== "undefined"; }

function semInternet(aviso) {
  if (aviso) {
    aviso.textContent = "Sem internet: mapa sem fundo (contorno de GO, IBGE). As glebas vêm do Sicor/BCB.";
    aviso.hidden = false;
  }
}

export function criarMapa(el, { aviso, centro = [-16.0, -49.6], zoom = 7, interativo = true } = {}) {
  if (!leafletDisponivel()) return null;
  const L = window.L;
  const m = L.map(el, { zoomControl: interativo, attributionControl: true, scrollWheelZoom: interativo,
    dragging: interativo, preferCanvas: false }).setView(centro, zoom);
  let carregou = false;
  let erros = 0;
  if (navigator.onLine === false) {
    semInternet(aviso);
  } else {
    const camada = L.tileLayer(OSM, { maxZoom: 19, attribution: ATRIB, crossOrigin: true });
    camada.on("tileload", () => { carregou = true; if (aviso) aviso.hidden = true; });
    camada.on("tileerror", () => {
      erros += 1;
      if (!carregou && erros >= 3) { m.removeLayer(camada); semInternet(aviso); }
    });
    camada.addTo(m);
  }
  return m;
}

export function desenharContorno(m, contorno) {
  if (!m || !contorno || !contorno.aneis) return null;
  return window.L.polygon(contorno.aneis, { color: "#14324f", weight: 1.5, fill: false, dashArray: "4 4",
    interactive: false }).addTo(m);
}

export function iconePrioridade(nivel, destaque = false) {
  const L = window.L;
  const n = nivel || "sem_sinal";
  // no celular o marcador é maior e a área de toque tem 44 px (o desenho fica no centro dela)
  const movel = window.matchMedia?.("(max-width: 767px)").matches;
  const tam = movel ? 44 : { alta: 26, media: 24, baixa: 20, sem_sinal: 16, demo: 26 }[n] || 18;
  return L.divIcon({
    className: movel ? "alvo-marcador" : "",
    html: `<span class="marcador ${n}${destaque ? " ativo" : ""}" title="prioridade ${n}"><span>${LETRA_PRIO[n] || ""}</span></span>`,
    iconSize: [tam, tam],
    iconAnchor: [tam / 2, tam / 2],
  });
}

// ---------------------------------------------------------------- fallback SVG (sem Leaflet)
export function mapaSVG(el, itens, aoClicar) {
  const pts = itens.flatMap((o) => (o.glebas || []).flat()).concat(itens.filter((o) => o.lat).map((o) => [o.lat, o.lon]));
  if (!pts.length) { el.replaceChildren(h("p", { class: "vazio" }, "Sem geometria para desenhar.")); return; }
  const lats = pts.map((p) => p[0]); const lons = pts.map((p) => p[1]);
  const [la0, la1, lo0, lo1] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const k = Math.cos(((la0 + la1) / 2) * Math.PI / 180);
  const W = 1000; const H = Math.max(300, Math.round(W * ((la1 - la0) || 1) / (((lo1 - lo0) || 1) * k)));
  const x = (lon) => ((lon - lo0) / ((lo1 - lo0) || 1)) * (W - 40) + 20;
  const y = (lat) => H - (((lat - la0) / ((la1 - la0) || 1)) * (H - 40) + 20);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Contorno das glebas (mapa simplificado, sem fundo)");
  svg.style.width = "100%"; svg.style.height = "100%"; svg.style.background = "#eef2f5";
  for (const o of itens) {
    const cor = COR_PRIO[o.nivel] || "#555";
    for (const anel of o.glebas || []) {
      const p = document.createElementNS(ns, "polygon");
      p.setAttribute("points", anel.map(([la, lo]) => `${x(lo).toFixed(1)},${y(la).toFixed(1)}`).join(" "));
      p.setAttribute("fill", cor); p.setAttribute("fill-opacity", ".35"); p.setAttribute("stroke", cor); p.setAttribute("stroke-width", "2");
      svg.append(p);
    }
    if (o.lat) {
      const g = document.createElementNS(ns, "g");
      g.setAttribute("tabindex", "0"); g.setAttribute("role", "button");
      g.setAttribute("aria-label", `${o.titulo || o.ref_bacen}: prioridade ${o.nivel}`);
      g.style.cursor = "pointer";
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", x(o.lon)); c.setAttribute("cy", y(o.lat)); c.setAttribute("r", "11");
      c.setAttribute("fill", cor); c.setAttribute("stroke", "#fff"); c.setAttribute("stroke-width", "2");
      const t = document.createElementNS(ns, "text");
      t.setAttribute("x", x(o.lon)); t.setAttribute("y", y(o.lat) + 4); t.setAttribute("text-anchor", "middle");
      t.setAttribute("font-size", "12"); t.setAttribute("font-weight", "800"); t.setAttribute("fill", "#fff");
      t.textContent = LETRA_PRIO[o.nivel] || "";
      g.append(c, t);
      g.addEventListener("click", () => aoClicar(o));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") aoClicar(o); });
      svg.append(g);
    }
  }
  el.replaceChildren(svg);
}

// Mini-mapa da prova: gleba + ponto da foto + círculo de precisão.
export function miniMapa(el, glebas, gps) {
  if (!leafletDisponivel()) {
    mapaSVG(el, [{ glebas, nivel: "media", lat: gps?.lat, lon: gps?.lon, titulo: "foto" }], () => {});
    return null;
  }
  const L = window.L;
  const m = criarMapa(el, { interativo: true, zoom: 14, centro: gps ? [gps.lat, gps.lon] : (glebas[0]?.[0] || [-16, -49]) });
  const grupo = [];
  for (const anel of glebas || []) grupo.push(L.polygon(anel, { color: "#1b4a74", weight: 2, fillOpacity: 0.15 }).addTo(m));
  if (gps) {
    grupo.push(L.circleMarker([gps.lat, gps.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#a1191c", fillOpacity: 1 })
      .bindTooltip(`foto (±${gps.precisao_m ?? "?"} m)`, { permanent: true, direction: "top" }).addTo(m));
    if (gps.precisao_m) grupo.push(L.circle([gps.lat, gps.lon], { radius: gps.precisao_m, color: "#a1191c", weight: 1, fillOpacity: 0.1 }).addTo(m));
  }
  if (grupo.length) m.fitBounds(L.featureGroup(grupo).getBounds().pad(0.25));
  setTimeout(() => m.invalidateSize(), 50);
  return m;
}
