"""Estimativa do tempo do pitch regional (versões A e B), lida do próprio `pitch-regional-3min.md`.

A contagem antiga ("um número conta como uma palavra") subestimava a fala: "5.267" são sete palavras faladas e
"368" são cinco. E a demo não é a soma da fala com a tela: em cada trecho vale a mais lenta das duas, e o orador
espera a tela onde lê um resultado (a contagem do vídeo, a faixa do bloqueio, o selo). Este script faz as duas
contas a partir do texto do pitch, para saber se ele cabe antes de ensaiar. O cronômetro do ensaio D-1 manda.

Uso (na raiz do repositório):
  scripts/py.sh scripts/tempo_pitch.py                 # versão A, trecho a trecho
  scripts/py.sh scripts/tempo_pitch.py --versao B      # a A até o S5 e o apêndice da B
  scripts/py.sh scripts/tempo_pitch.py --reacao 1.0    # outro tempo de reação do operador (padrão: 1,5 s)
  scripts/py.sh scripts/tempo_pitch.py --conferir      # código 1 se a A passar de 2:50 ou a B de 4:45

Modelo (as premissas, todas à vista):
- Fala a 140 palavras por minuto, com números por extenso (`extenso`) e siglas soletradas (GTA, XML e NF-e contam
  três palavras); um marcador `[[EQUIPE: ...]]` conta 10 palavras (os nomes). O texto falado de cada linha da
  tabela é o primeiro trecho entre aspas duplas da coluna "Fala"; os marcadores `<!--n:...-->` valem pelo número
  que mostram, então a conta acompanha a r4 sem editar este arquivo.
- Demo: `GATILHOS` diz em que palavra o operador clica cada passo e onde o orador espera a tela. O clique sai
  `--reacao` segundos depois da palavra, mas só depois de o passo anterior terminar (a interface roda um passo por
  vez; o operador clica 0,3 s depois do fim do anterior quando já passou da palavra). A duração de cada passo
  (`PASSOS`) é a medida em 16/10/2026 (`apps/web/ROTEIRO_DEMO.md`, L35: ferramentas reais na CPU e latência do LLM
  gravada), mais as ações humanas: a assinatura (marcar a caixa, digitar o PIN, clicar) e a janela do pacote.
- A troca da demo para os slides (Alt+Tab) custa 1 s. A troca de slide pelo passador, nada.
- Se um gatilho não for achado no texto, o script para com erro: o pitch mudou e `GATILHOS` tem de mudar junto.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "docs" / "entregaveis" / "pitch-regional-3min.md"
PPM = 140
LIMITE = {"A": 170.0, "B": 285.0}  # 2:50 (10 s antes do corte de 3:00) e 4:45 (15 s antes de 5:00)
PALAVRAS_MARCADOR_EQUIPE = 10
TROCA_DEMO_SLIDES = 1.0
ANTECIPACAO = 0.3  # clique logo depois do fim do passo anterior, quando a fala já passou do gatilho

# Duração de cada passo na tela, em segundos (ROTEIRO_DEMO.md, L35, medida em 16/10/2026).
PASSOS: dict[str, float] = {
    "abrir": 2.0,  # Alt+Tab para o navegador e "Abrir demo"
    "1": 3.4, "2": 1.9, "3": 1.2, "4": 16.0, "5": 0.1, "6": 2.5, "7": 0.3, "8": 2.0, "9": 2.3, "10": 2.5,
    "11": 0.2, "12": 2.2, "13": 2.1, "14": 1.8, "15": 0.3, "16": 0.3, "17": 0.3, "18": 0.3,
    "assinar": 6.0,  # marcar "Conferi o hash raiz", digitar o PIN, "Assinar com PIN" (o passo 19)
    "pacote": 3.6,  # botão "Pacote de exibição" (0,6 s) e a janela aberta na tela (~3 s)
    "trace": 3.0,  # versão B: fechar o pacote e abrir o "trace 1" da linha da contagem
}

# Por linha de demo da tabela (na ordem), o que acontece em que ponto da fala:
#   ("depois", "trecho", "→N") clica o passo N quando a fala termina "trecho";
#   ("antes", "trecho", "⏸N") o orador espera o passo N terminar antes de dizer "trecho".
GATILHOS_A: list[list[tuple[str, str, str]]] = [
    # início: abrir e os passos 1 a 4 em fila (cada um assim que o anterior termina): a contagem do vídeo, o
    # gargalo de 16 s, começa no fim desta frase e corre enquanto o orador fala do curral
    [("depois", "Uma operação de demonstração", "→abrir →1 →2 →3 →4"), ("antes", "e escolhe o método", "⏸1")],
    [("antes", "12, contra", "⏸4")],
    [("depois", "O produtor pressiona", "→5"), ("antes", "O agente recusa", "⏸5"), ("depois", "e registra", "→6")],
    [("antes", "e o agente pede", "⏸6"), ("depois", "pede só o que faltou", "→7 →8"), ("antes", "confirma", "⏸8"),
     ("depois", "confirma", "→9")],
    [("antes", "ignorado", "⏸9"), ("depois", "esconde um", "→10"), ("antes", "pendente", "⏸10"),
     ("depois", "pendente", "→11")],
    [("antes", "bloqueado", "⏸11"), ("depois", "3 pendências", "→12 →13 →14"), ("depois", "O laudo sai", "→15 →16"),
     ("antes", "O agente recusa", "⏸16"), ("depois", "Assinar por ela", "→17 →18 →assinar"),
     ("antes", "saiu um laudo selado", "⏸assinar"), ("depois", "saiu um laudo selado", "→pacote")],
    [("antes", "sai num clique", "⏸pacote")],
]
GATILHOS_B: dict[str, list[tuple[str, str, str]]] = {
    "Trace": [("depois", "Cada campo do laudo abre o trace", "→trace"), ("antes", "a ferramenta", "⏸trace")],
}

UNIDADES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
            "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove")
DEZENAS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
CENTENAS = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
            "oitocentos", "novecentos")
SIGLAS = {"GTA": 3, "XML": 3, "NF-E": 3, "CPF": 3, "BCB": 3, "MCR": 3, "TCU": 3, "CNPJ": 4, "GPU": 3, "LLM": 3,
          "PIN": 1, "IA": 1, "DANFE": 2, "ART": 1, "CAR": 1, "AWS": 3}


def extenso(n: int) -> str:
    """Número inteiro por extenso, em português (o que importa aqui é o número de palavras)."""
    if n < 20:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DEZENAS[d] + (f" e {UNIDADES[u]}" if u else "")
    if n < 1000:
        if n == 100:
            return "cem"
        c, r = divmod(n, 100)
        return CENTENAS[c] + (f" e {extenso(r)}" if r else "")
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        cabeca = "mil" if m == 1 else f"{extenso(m)} mil"
        return cabeca + ((" e " if r < 100 or r % 100 == 0 else " ") + extenso(r) if r else "")
    mi, r = divmod(n, 1_000_000)
    return f"{extenso(mi)} {'milhão' if mi == 1 else 'milhões'}" + (f" {extenso(r)}" if r else "")


RX_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?%?")


def palavras_faladas(texto: str) -> list[str]:
    """Quebra o texto em palavras faladas: números por extenso, siglas soletradas, marcador de equipe = 10."""
    texto = re.sub(r"\[\[EQUIPE:[^\]]*\]\]", " " + " ".join(["(nome)"] * PALAVRAS_MARCADOR_EQUIPE) + " ", texto)
    saida: list[str] = []
    for bruto in texto.replace("—", " ").replace("–", " ").split():
        tok = bruto.strip(".,;:!?\"'()`*“”‘’")
        if not tok:
            continue
        if tok == "R$":
            saida.append("reais")
            continue
        if re.fullmatch(r"\d+(?:-\d+)+", tok):  # "2-9" (item do MCR) = "dois nove"
            for parte in tok.split("-"):
                saida += extenso(int(parte)).split()
            continue
        if RX_NUMERO.fullmatch(tok):
            inteiro, _, decimal = tok.rstrip("%").replace(".", "").partition(",")
            saida += extenso(int(inteiro)).split()
            if decimal:
                saida += ["vírgula"] + extenso(int(decimal)).split()
            if tok.endswith("%"):
                saida += ["por", "cento"]
            continue
        saida += [tok] * SIGLAS.get(tok.upper(), 1)
    return saida


def numeros_citados(texto: str) -> list[str]:
    """Números que o ouvinte escuta ("9 de 9" conta um), para a regra de no máximo 3 fora da demo."""
    texto = re.sub(r"\d+ de \d+", "#", texto)
    return re.findall(r"#|\d+(?:[.,-]\d+)*%?", texto)


def limpar(celula: str) -> str:
    """Tira os marcadores de número (fica o valor), crases e negrito."""
    celula = re.sub(r"<!--(?:/n|n:[^>]*)-->", "", celula)
    celula = re.sub(r"<!--[^>]*-->", "", celula)
    return re.sub(r"\s+", " ", celula.replace("`", "").replace("**", "")).strip()


@dataclass
class Linha:
    tempo: str
    rotulo: str
    fala: str
    demo: bool
    gatilhos: list[tuple[str, str, str]] = field(default_factory=list)


def linhas_da_tabela(md: str, titulo: str) -> list[Linha]:
    """Linhas da primeira tabela depois do título `## {titulo}`, com o primeiro trecho entre aspas da coluna Fala."""
    inicio = md.index(f"\n## {titulo}")
    linhas: list[Linha] = []
    em_tabela = False
    for crua in md[inicio:].splitlines()[1:]:
        if crua.startswith("|"):
            em_tabela = True
            celulas = [c.strip() for c in crua.strip().strip("|").split(" | ")]
            if len(celulas) < 3 or celulas[0] in ("Tempo", "---") or set(celulas[0]) <= set("-"):
                continue
            achou = re.search(r"\"([^\"]+)\"", celulas[2])
            if not achou or celulas[0] in ("—", "-"):
                continue  # linha condicional (B1) ou sem fala
            rotulo = re.sub(r"^\*\*([^*]+)\*\*.*$", r"\1", celulas[1]).strip()
            linhas.append(Linha(celulas[0], rotulo, limpar(achou.group(1)), rotulo.upper().startswith("DEMO")))
        elif em_tabela:
            break
    return linhas


def fmt(s: float) -> str:
    m, r = divmod(round(s), 60)
    return f"{m}:{r:02d}"


def achar(fala: str, trecho: str, desde: int) -> int:
    i = fala.find(trecho, desde)
    if i < 0:
        raise SystemExit(f"ERRO: gatilho {trecho!r} não está na fala {fala[:60]!r}...: atualize GATILHOS.")
    return i


def simular(linhas: list[Linha], reacao: float, log: list[str] | None = None,
            ppm: int = PPM) -> list[tuple[Linha, float, float, int, float]]:
    """Devolve (linha, início, fim, palavras, espera) com o relógio do pitch; `log` recebe cada clique e espera."""
    seg_palavra = 60 / ppm
    t = 0.0
    fim_passo: dict[str, float] = {}
    ultimo_fim = 0.0
    saida = []
    estava_na_demo = False
    for ln in linhas:
        if estava_na_demo and not ln.demo:
            t = max(t, ultimo_fim) + TROCA_DEMO_SLIDES  # a tela termina o último passo e volta aos slides
        inicio, espera = t, 0.0
        # (posição no texto, 0 = antes / 1 = depois, ordem em GATILHOS, ação): no mesmo ponto, a espera vem antes
        # do clique e os cliques seguem a ordem escrita
        eventos: list[tuple[int, int, int, str]] = []
        for quando, trecho, acao in ln.gatilhos:
            i = achar(ln.fala, trecho, 0)
            pos = i if quando == "antes" else i + len(trecho)
            for a in acao.split():
                eventos.append((pos, 0 if quando == "antes" else 1, len(eventos), a))
        eventos.sort()
        cursor, n_palavras = 0, 0
        for pos, _, _, acao in eventos + [(len(ln.fala), 2, 0, "")]:
            pedaco = palavras_faladas(ln.fala[cursor:pos])
            n_palavras += len(pedaco)
            t += len(pedaco) * seg_palavra
            cursor = pos
            if acao.startswith("→"):
                passo = acao[1:]
                clique = max(t + reacao, ultimo_fim + ANTECIPACAO)
                fim_passo[passo] = ultimo_fim = clique + PASSOS[passo]
                if log is not None:
                    log.append(f"  {t:6.1f}s  fala chega ao gatilho; clique {passo} em {clique:.1f}s, "
                               f"termina em {fim_passo[passo]:.1f}s")
            elif acao.startswith("⏸"):
                alvo = fim_passo[acao[1:]]
                if alvo > t:
                    espera += alvo - t
                    if log is not None:
                        log.append(f"  {t:6.1f}s  orador espera o passo {acao[1:]} por {alvo - t:.1f}s")
                    t = alvo
        saida.append((ln, inicio, t, n_palavras, espera))
        estava_na_demo = ln.demo
    return saida


def carregar(versao: str) -> list[Linha]:
    """Versão A: a tabela da A. Versão B: a A sem o S6 e, depois do S5, as linhas da B (o S6 fecha o B4)."""
    md = PITCH.read_text(encoding="utf-8")
    a = linhas_da_tabela(md, "Versão A")
    demo = [ln for ln in a if ln.demo]
    if len(demo) != len(GATILHOS_A):
        raise SystemExit(f"ERRO: {len(demo)} linhas de demo no pitch e {len(GATILHOS_A)} em GATILHOS_A.")
    for ln, g in zip(demo, GATILHOS_A, strict=True):
        ln.gatilhos = g
    if versao == "A":
        return a
    b = linhas_da_tabela(md, "Versão B")
    for ln in b:
        ln.gatilhos = GATILHOS_B.get(ln.rotulo.split(" ")[0].rstrip("."), [])
        ln.demo = bool(ln.gatilhos)
    s6 = next((ln for ln in a if ln.rotulo.startswith("S6")), None)
    if s6 is None or not b or s6.fala not in b[-1].fala:
        raise SystemExit("ERRO: a última linha da versão B tem de terminar com a fala do S6, sem mudar uma palavra.")
    return [ln for ln in a if ln is not s6] + b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--versao", choices=("A", "B"), default="A")
    ap.add_argument("--reacao", type=float, default=1.5, help="segundos entre a palavra-gatilho e o clique")
    ap.add_argument("--conferir", action="store_true", help="código 1 se passar do limite da versão")
    ap.add_argument("--detalhe", action="store_true", help="mostra cada clique do operador e cada espera")
    ap.add_argument("--ppm", type=int, default=PPM, help="palavras por minuto (sensibilidade; a regra é 140)")
    args = ap.parse_args()

    log: list[str] = []
    resultado = simular(carregar(args.versao), args.reacao, log, args.ppm)
    if args.detalhe:
        print("\n".join(log), end="\n\n")
    print(f"Versão {args.versao}: {args.ppm} palavras/min, números e siglas por extenso; reação do operador "
          f"{args.reacao:.1f} s.\n")
    print(f"{'trecho':<34} {'no texto':>11} {'estimado':>11} {'palavras':>8} {'fala':>6} {'espera':>7}")
    total_palavras = 0
    numeros_fora: list[str] = []
    for ln, ini, fim, n, espera in resultado:
        total_palavras += n
        fala_s = n * 60 / args.ppm
        if not ln.demo:
            numeros_fora += numeros_citados(ln.fala)
        print(f"{ln.rotulo[:34]:<34} {ln.tempo:>11} {fmt(ini) + '–' + fmt(fim):>11} {n:>8} {fala_s:>5.1f}s "
              f"{espera:>6.1f}s")
    total = resultado[-1][2]
    demo = []  # o bloco da demo da versão A (na B, o trace ao vivo vem depois e não entra aqui)
    for r in resultado:
        if r[0].demo:
            demo.append(r)
        elif demo:
            break
    print(f"\nTotal: {fmt(total)} ({total:.0f} s), {total_palavras} palavras faladas; limite da conferência "
          f"{fmt(LIMITE[args.versao])}.")
    if demo:
        print(f"Demo: {fmt(demo[0][1])}–{fmt(demo[-1][2])} ({demo[-1][2] - demo[0][1]:.0f} s); "
              f"espera pela tela: {sum(r[4] for r in demo):.1f} s.")
    print(f"Números falados fora da demo: {len(numeros_fora)} ({', '.join(numeros_fora) or '—'}; "
          "'N de N' conta um).")
    if args.conferir and total > LIMITE[args.versao]:
        print(f"FALHOU: {fmt(total)} passa de {fmt(LIMITE[args.versao])}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
