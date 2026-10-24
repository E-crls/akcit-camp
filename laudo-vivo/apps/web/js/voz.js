// Voz no navegador: gravação "segurar para falar" (MediaRecorder) e resposta falada (Web Speech API).
// Nada é instalado no servidor para o TTS: a voz pt-BR é a do sistema/navegador.

import { abrirModal, h } from "./ui.js";

const PREF_VOZES = [/Francisca/i, /Thalita/i, /Antonio/i, /Google português do Brasil/i, /Luciana/i, /Maria/i, /Daniel/i];
let vozes = [];
let vozEscolhida = null;
let ttsLigado = true;
try { ttsLigado = localStorage.getItem("lv.tts") !== "0"; } catch { /* armazenamento indisponível */ }

function carregarVozes() {
  if (!("speechSynthesis" in window)) return [];
  vozes = speechSynthesis.getVoices().filter((v) => /^pt/i.test(v.lang));
  let salva = null;
  try { salva = localStorage.getItem("lv.voz"); } catch { /* */ }
  vozEscolhida = vozes.find((v) => v.name === salva) || null;
  if (!vozEscolhida) {
    const br = vozes.filter((v) => /pt[-_]BR/i.test(v.lang));
    for (const rx of PREF_VOZES) {
      vozEscolhida = br.find((v) => rx.test(v.name));
      if (vozEscolhida) break;
    }
    vozEscolhida = vozEscolhida || br[0] || vozes[0] || null;
  }
  return vozes;
}
if ("speechSynthesis" in window) {
  carregarVozes();
  speechSynthesis.addEventListener?.("voiceschanged", carregarVozes);
}

export const tts = {
  disponivel: () => "speechSynthesis" in window,
  ligado: () => ttsLigado,
  ligar(v) { ttsLigado = !!v; try { localStorage.setItem("lv.tts", v ? "1" : "0"); } catch { /* */ } if (!v) this.parar(); },
  vozes: () => carregarVozes(),
  voz: () => vozEscolhida,
  escolher(nome) { vozEscolhida = vozes.find((v) => v.name === nome) || vozEscolhida; try { localStorage.setItem("lv.voz", nome); } catch { /* */ } },
  parar() { if ("speechSynthesis" in window) speechSynthesis.cancel(); },
  falar(texto) {
    if (!ttsLigado || !("speechSynthesis" in window) || !texto) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = (vozEscolhida && vozEscolhida.lang) || "pt-BR";
    if (vozEscolhida) u.voice = vozEscolhida;
    u.rate = 1.05;
    speechSynthesis.speak(u);
  },
};

// ---------------------------------------------------------------- gravação
const TIPOS = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];

export class Gravador {
  constructor({ aoNivel } = {}) {
    this.stream = null;
    this.rec = null;
    this.partes = [];
    this.inicio = 0;
    this.aoNivel = aoNivel;
    this.ctx = null;
    this.raf = 0;
  }

  static suportado() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  static motivoIndisponivel() {
    if (!window.isSecureContext) return "o microfone só funciona em HTTPS ou em localhost";
    if (!Gravador.suportado()) return "este navegador não grava áudio (MediaRecorder)";
    return "";
  }

  async preparar() {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    try {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.an = this.ctx.createAnalyser();
      this.an.fftSize = 512;
      src.connect(this.an);
    } catch { this.an = null; }
  }

  async iniciar() {
    await this.preparar();
    tts.parar(); // o fiscal fala por cima do agente
    const tipo = TIPOS.find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
    this.rec = new MediaRecorder(this.stream, tipo ? { mimeType: tipo } : undefined);
    this.partes = [];
    this.rec.ondataavailable = (e) => { if (e.data && e.data.size) this.partes.push(e.data); };
    this.rec.start(250);
    this.inicio = performance.now();
    if (this.ctx && this.ctx.state === "suspended") await this.ctx.resume();
    this._medir();
  }

  _medir() {
    if (!this.an || !this.aoNivel) return;
    const buf = new Uint8Array(this.an.fftSize);
    const passo = () => {
      this.an.getByteTimeDomainData(buf);
      let s = 0;
      for (const v of buf) s += ((v - 128) / 128) ** 2;
      this.aoNivel(Math.min(1, Math.sqrt(s / buf.length) * 4));
      this.raf = requestAnimationFrame(passo);
    };
    passo();
  }

  parar() {
    cancelAnimationFrame(this.raf);
    if (this.aoNivel) this.aoNivel(0);
    return new Promise((resolve) => {
      if (!this.rec || this.rec.state === "inactive") return resolve(null);
      const dur = performance.now() - this.inicio;
      this.rec.onstop = () => {
        const tipo = (this.rec.mimeType || "audio/webm").split(";")[0];
        const blob = new Blob(this.partes, { type: tipo });
        resolve({ blob, duracaoMs: dur, ext: tipo.includes("ogg") ? "ogg" : tipo.includes("mp4") ? "m4a" : "webm" });
      };
      this.rec.stop();
    });
  }

  liberar() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.ctx) this.ctx.close().catch(() => {});
    this.ctx = null;
  }
}

// ---------------------------------------------------------------- GPS do navegador
export function lerGPS(timeoutMs = 9000) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve({ erro: "navegador sem GPS" });
    if (!window.isSecureContext) return resolve({ erro: "GPS só em HTTPS ou localhost" });
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, precisao_m: Math.round(p.coords.accuracy * 10) / 10,
        capturado_em: new Date(p.timestamp).toISOString() }),
      (e) => resolve({ erro: e.code === 1 ? "permissão de localização negada" : "GPS sem sinal" }),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 15000 },
    );
  });
}

// ---------------------------------------------------------------- preferências (menu do usuário e ⋯ → Voz)
export function confirmarNumeros() {
  try { return localStorage.getItem("lv.confnum") !== "0"; } catch { return true; }
}

export function preferenciasVoz() {
  const tChk = h("input", { type: "checkbox", id: "pref-tts", checked: tts.ligado() ? true : null, disabled: tts.disponivel() ? null : true });
  tChk.addEventListener("change", () => tts.ligar(tChk.checked));
  const cChk = h("input", { type: "checkbox", id: "pref-conf", checked: confirmarNumeros() ? true : null });
  cChk.addEventListener("change", () => { try { localStorage.setItem("lv.confnum", cChk.checked ? "1" : "0"); } catch { /* */ } });
  const sel = h("select", { id: "pref-voz" });
  const vs = tts.vozes();
  sel.replaceChildren(...(vs.length ? vs : [{ name: "voz padrão pt-BR", lang: "pt-BR" }]).map((v) =>
    h("option", { value: v.name, selected: tts.voz()?.name === v.name ? true : null }, `${v.name} (${v.lang})`)));
  sel.addEventListener("change", () => tts.escolher(sel.value));
  abrirModal("Voz", h("div", { class: "form-pref" },
    h("label", { class: "opcao", for: "pref-tts" }, tChk, h("span", {}, "Resposta falada", h("small", {}, "O agente lê a resposta em voz alta."))),
    h("div", { class: "campo" }, h("label", { for: "pref-voz" }, "Voz do agente"), sel),
    h("label", { class: "opcao", for: "pref-conf" }, cChk, h("span", {}, "Confirmar números falados", h("small", {}, "Antes de enviar, o agente repete os números que entendeu."))),
    h("p", { class: "t-sec" }, "A fala é transcrita neste aparelho e entra na trilha da fiscalização. Avise quem estiver presente.")));
}
