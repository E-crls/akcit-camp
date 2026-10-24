// Mapas, como folha de carta. Carteira: Leaflet (vendorizado), sem fundo baixado, com o contorno de Goiás (IBGE) em
// tinta, algumas cidades de referência e os piquetes quadrados de prioridade (tinta = alta; menor, em pedra = média); o
// caso de demonstração é o piquete verde-cerrado com o esquadro branco. Prova da foto: Leaflet com o fundo do OpenStreetMap quando há internet. Cartão
// de resultado: SVG puro (a área financiada contornada, o ponto da foto em terracota e a distância numa régua graduada de 100
// em 100 m). As cores vêm dos tokens de app.css (nenhuma cor fixa aqui; a reserva abaixo é a mesma paleta Cerrado).

import { h } from "./ui.js";

// cor de um token de app.css (com o valor de reserva se a folha ainda não carregou)
const RESERVA = { "--tinta": "#14201A", "--grafite": "#3B4A42", "--branco": "#FFFFFF", "--destaque": "#C0582E", "--papel-mapa": "#FAF9F5",
  "--cal-2": "#ECE9E1", "--poeira": "#E3DFD5" };
export function cor(token) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return v || RESERVA[token] || "#000";
}

const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATRIB = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const CIDADES = [["Goiânia", -16.686, -49.264], ["Anápolis", -16.328, -48.953], ["Rio Verde", -17.792, -50.919],
  ["Jataí", -17.881, -51.714], ["Catalão", -18.166, -47.946], ["Itumbiara", -18.419, -49.215], ["Porangatu", -13.441, -49.149],
  ["Posse", -14.093, -46.369], ["Iporá", -16.442, -51.118]];

export function leafletDisponivel() { return typeof window.L !== "undefined"; }

export function criarMapaCarteira(el) {
  if (!leafletDisponivel()) return null;
  const L = window.L;
  const m = L.map(el, { zoomControl: true, attributionControl: false, zoomSnap: 0.25, minZoom: 5, maxZoom: 16 }).setView([-15.9, -49.6], 6.5);
  // os nomes das cidades ficam numa camada própria, acima dos piquetes, com halo do papel: um piquete nunca come o nome
  // (os piquetes são pequenos e o nome, curto; o balão e a legenda ficam por cima de tudo)
  m.createPane("cidades");
  m.getPane("cidades").style.zIndex = 620;
  m.getPane("cidades").style.pointerEvents = "none";
  CIDADES.forEach(([n, la, lo]) => L.marker([la, lo], { interactive: false, keyboard: false, pane: "cidades",
    icon: L.divIcon({ className: "cidade", html: `<span>${n}</span>`, iconSize: [0, 0] }) }).addTo(m));
  return m;
}

export function desenharContorno(m, contorno) {
  if (!m || !contorno?.aneis) return null;
  return window.L.polygon(contorno.aneis, { color: cor("--tinta"), weight: 2.5, fillColor: cor("--papel-mapa"), fillOpacity: 1, interactive: false })
    .addTo(m).bringToBack();
}

// Ícone do piquete: nível alta|media|baixa|demo; o selecionado fica enquadrado em tinta. O caso da demonstração é o
// piquete verde-cerrado com o esquadro branco (sem letra).
export function iconeOperacao(nivel, selecionado = false) {
  const L = window.L;
  const demo = nivel === "demo";
  const miolo = demo ? '<svg class="pino-demo" viewBox="0 0 30 30" aria-hidden="true"><use href="#pino-demo"/></svg>'
    : `<span class="ponto ${nivel || "baixa"}"></span>`;
  const tam = selecionado ? 48 : demo ? 30 : 22;
  return L.divIcon({ className: `marcador${selecionado ? " sel" : ""}${demo ? " demo" : ""}`, html: `<span class="anel">${miolo}</span>`,
    iconSize: [tam, tam], iconAnchor: [tam / 2, tam / 2] });
}

// ---------------------------------------------------------------- prova da foto (gaveta): Leaflet com fundo, se houver
export function miniMapa(el, glebas, gps, distancia = null) {
  if (!leafletDisponivel()) { el.replaceChildren(svgMiniMapa(glebas, gps, distancia, { w: 520, h: 240 })); return null; }
  const L = window.L;
  const m = L.map(el, { zoomControl: true, attributionControl: true, scrollWheelZoom: false })
    .setView(gps ? [gps.lat, gps.lon] : (glebas?.[0]?.[0] || [-16, -49]), 15);
  if (navigator.onLine !== false) {
    let ok = false; let erros = 0;
    // O OpenStreetMap exige o Referer (sem ele, devolve o tile "Access blocked"); o site manda no-referrer, então só
    // os tiles levam a origem (nunca o caminho da página)
    const t = L.tileLayer(OSM, { maxZoom: 19, attribution: ATRIB, crossOrigin: true, referrerPolicy: "strict-origin-when-cross-origin" });
    t.on("tileload", () => { ok = true; });
    t.on("tileerror", () => { erros += 1; if (!ok && erros >= 3) m.removeLayer(t); });
    t.addTo(m);
  }
  const grupo = [];
  for (const anel of glebas || []) grupo.push(L.polygon(anel, { color: cor("--tinta"), weight: 2.5, fillColor: cor("--tinta"), fillOpacity: 0.12 }).addTo(m));
  if (gps) {
    const p = L.circleMarker([gps.lat, gps.lon], { radius: 8, color: cor("--tinta"), weight: 2.5, fillColor: cor("--destaque"), fillOpacity: 1 }).addTo(m);
    grupo.push(p);
    if (gps.precisao_m) grupo.push(L.circle([gps.lat, gps.lon], { radius: gps.precisao_m, color: cor("--tinta"), weight: 1, fillOpacity: 0.08 }).addTo(m));
    const alvo = pontoMaisProximo(glebas, gps);
    if (alvo && distancia !== null && distancia > 0) {
      L.polyline([[gps.lat, gps.lon], alvo], { color: cor("--tinta"), weight: 2.5, dashArray: "6 6" }).addTo(m)
        .bindTooltip(`${String(distancia).replace(".", ",")} m`, { permanent: true, direction: "center", className: "dist-tip" });
    }
  }
  if (grupo.length) m.fitBounds(L.featureGroup(grupo).getBounds().pad(0.25));
  setTimeout(() => m.invalidateSize(), 50);
  return m;
}

// Ponto da borda mais próximo (lat, lon), em projeção local (metros).
export function pontoMaisProximo(glebas, gps) {
  if (!gps || !glebas?.length) return null;
  const k = Math.cos(gps.lat * Math.PI / 180);
  const P = (la, lo) => [(lo - gps.lon) * 111320 * k, (la - gps.lat) * 110540];
  let melhor = null;
  for (const anel of glebas) {
    for (let i = 0; i < anel.length - 1; i++) {
      const [ax, ay] = P(...anel[i]); const [bx, by] = P(...anel[i + 1]);
      const dx = bx - ax; const dy = by - ay;
      const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) || 1)));
      const x = ax + t * dx; const y = ay + t * dy;
      const d = Math.hypot(x, y);
      if (!melhor || d < melhor.d) melhor = { d, la: anel[i][0] + t * (anel[i + 1][0] - anel[i][0]), lo: anel[i][1] + t * (anel[i + 1][1] - anel[i][1]) };
    }
  }
  return melhor ? [melhor.la, melhor.lo] : null;
}

// ---------------------------------------------------------------- mini-mapa do cartão de resultado (SVG)
// O mesmo papel do mapa da carteira: fundo papel-mapa, a área financiada só contornada em tinta, o ponto da foto em
// terracota e, fora da área, a régua graduada de 100 em 100 m da foto até a borda, com a distância grande numa etiqueta tinta.
export function svgMiniMapa(glebas, gps, distancia, { w = 260, h: alt = 128, rotulo = null } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const mk = (tag, at) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(at)) e.setAttribute(k, v); return e; };
  const svg = mk("svg", { viewBox: `0 0 ${w} ${alt}`, class: "mini-svg", role: "img",
    "aria-label": distancia ? `Área financiada e o ponto da foto, a ${rotulo || `${distancia} m`} da borda` : "Área financiada e o ponto da foto" });
  svg.append(mk("rect", { x: 0, y: 0, width: w, height: alt, fill: cor("--papel-mapa") }));
  const pts = (glebas || []).flat().concat(gps ? [[gps.lat, gps.lon]] : []);
  if (!pts.length) return svg;
  const lat0 = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const k = Math.cos(lat0 * Math.PI / 180);
  const xy = ([la, lo]) => [lo * k, -la];
  const P = pts.map(xy);
  const [x0, x1] = [Math.min(...P.map((p) => p[0])), Math.max(...P.map((p) => p[0]))];
  const [y0, y1] = [Math.min(...P.map((p) => p[1])), Math.max(...P.map((p) => p[1]))];
  // a etiqueta da distância fica embaixo, à esquerda: o desenho usa o resto
  const padX = 18; const padTop = 14; const padBase = distancia ? 46 : 14;
  const esc = Math.min((w - 2 * padX) / ((x1 - x0) || 1e-9), (alt - padTop - padBase) / ((y1 - y0) || 1e-9));
  const ox = (w - (x1 - x0) * esc) / 2; const oy = padTop + (alt - padTop - padBase - (y1 - y0) * esc) / 2;
  const tela = (p) => { const [x, y] = xy(p); return [ox + (x - x0) * esc, oy + (y - y0) * esc]; };
  for (const anel of glebas || []) {
    const pts2 = anel.map((p) => tela(p).map((v) => v.toFixed(1)).join(",")).join(" ");
    svg.append(mk("polygon", { points: pts2, fill: cor("--branco"), stroke: cor("--tinta"), "stroke-width": 2.5, "stroke-linejoin": "round" }));
  }
  if (gps) {
    const [gx, gy] = tela([gps.lat, gps.lon]);
    const alvo = pontoMaisProximo(glebas, gps);
    if (alvo && distancia) {
      const [ax, ay] = tela(alvo);
      const dx = ax - gx; const dy = ay - gy; const L = Math.hypot(dx, dy) || 1;
      const ux = dx / L; const uy = dy / L; const nx = -uy; const ny = ux;
      // régua: a linha cheia e um tracinho a cada 100 m (maior a cada 500 m)
      svg.append(mk("line", { x1: gx, y1: gy, x2: ax, y2: ay, stroke: cor("--tinta"), "stroke-width": 2.5 }));
      const passo = 100 * L / Number(distancia);
      if (Number.isFinite(passo) && passo >= 3) {
        for (let i = 1, s = passo; s < L - 1; i += 1, s += passo) {
          const c = i % 5 === 0 ? 6 : 4;
          const px = gx + ux * s; const py = gy + uy * s;
          svg.append(mk("line", { x1: px - nx * c, y1: py - ny * c, x2: px + nx * c, y2: py + ny * c, stroke: cor("--tinta"), "stroke-width": 1.75 }));
        }
      }
      svg.append(mk("line", { x1: ax - nx * 7, y1: ay - ny * 7, x2: ax + nx * 7, y2: ay + ny * 7, stroke: cor("--tinta"), "stroke-width": 2.5 }));
      // a distância, grande, numa etiqueta tinta no pé do desenho
      const txt = rotulo || `${distancia} m`;
      const th = 32; const tw = 16 + txt.length * 11.5;
      const tx = 8; const ty = alt - th - 8;
      svg.append(mk("rect", { x: tx, y: ty, width: tw, height: th, rx: 2, fill: cor("--tinta") }));
      const t = mk("text", { x: tx + tw / 2, y: ty + th / 2 + 8.5, "text-anchor": "middle", class: "mm-dist" });
      t.textContent = txt;
      svg.append(t);
    }
    svg.append(mk("rect", { x: gx - 8, y: gy - 8, width: 16, height: 16, rx: 2, fill: cor("--destaque"), stroke: cor("--tinta"), "stroke-width": 2.5 }));
  }
  return svg;
}

export function contornoSimples(texto) { return h("div", { class: "mapa-vazio" }, texto); }
