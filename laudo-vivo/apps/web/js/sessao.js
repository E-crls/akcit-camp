// Sessão e papel (sem mudar a API). A sessão é um perfil local; na demonstração o papel segue a tela, para contar a
// história à banca: Carteira e Laudo selado → analista; Fiscalização e Revisar e assinar → fiscal. A troca manual
// pelo menu do usuário vale até sair da tela. Os nomes são personagens da demonstração (dados sintéticos).

export const PERFIS = {
  fiscal: { nome: "Ana (fictícia)", papel: "fiscal", rotulo: "técnica agrícola", titulo: "Fiscal", iniciais: "AN" },
  analista: { nome: "Paulo (fictício)", papel: "analista", rotulo: "analista da cooperativa", titulo: "Analista", iniciais: "PA" },
};
const PAPEL_DA_TELA = { carteira: "analista", selado: "analista", "selado-m": "fiscal", fis: "fiscal", assinar: "fiscal", fiscalizacoes: "fiscal" };

let tela = "carteira";
let demoTela = false;
let manual = null;

function telaPequena() { return !window.matchMedia("(min-width: 1100px)").matches; }

function lerSalvo() {
  try {
    const s = JSON.parse(localStorage.getItem("lv.sessao") || "null");
    if (s && PERFIS[s.papel]) return s.papel;
  } catch { /* armazenamento indisponível */ }
  return null;
}

export function papelPadrao() { return lerSalvo() || (telaPequena() && !apresentacaoLigada() ? "fiscal" : "analista"); }
// a pessoa já disse quem é (primeiro uso: a tela "Como você vai usar o Laudo Vivo?")
export function papelEscolhido() { return !!lerSalvo(); }
export function salvarPapel(p) {
  if (!PERFIS[p]) return;
  try { localStorage.setItem("lv.sessao", JSON.stringify({ papel: p })); } catch { /* armazenamento indisponível */ }
  manual = null;
}
export function telaAtual() { return tela; }

export function apresentacaoLigada() { return document.body.classList.contains("apresentacao"); }

export function demoPelaUrl() {
  const q = new URLSearchParams(location.search);
  const hq = new URLSearchParams((location.hash.split("?")[1]) || "");
  return q.has("demo") || hq.has("demo") || q.get("apresentacao") === "1" || apresentacaoLigada();
}

// Chamada por cada tela ao montar: `demo` = a tela mostra uma operação de demonstração (ou a URL pede a demo).
export function definirTela(nome, { demo = false } = {}) {
  if (nome !== tela) manual = null;
  tela = nome;
  demoTela = !!demo || demoPelaUrl();
  window.dispatchEvent(new Event("lv:papel"));
}

export function modoDemo() { return demoTela; }

export function papel() {
  if (manual && manual.tela === tela) return manual.papel;
  if (demoTela && PAPEL_DA_TELA[tela]) return PAPEL_DA_TELA[tela];
  return papelPadrao();
}
export function perfil() { return PERFIS[papel()]; }
export function primeiroNome() { return perfil().nome.split(" ")[0]; }

export function trocarPapel(p) {
  if (!PERFIS[p]) return;
  if (demoTela) manual = { tela, papel: p };
  else {
    try { localStorage.setItem("lv.sessao", JSON.stringify({ papel: p })); } catch { /* */ }
    manual = null;
  }
  window.dispatchEvent(new CustomEvent("lv:papel", { detail: { manual: true } }));
}
