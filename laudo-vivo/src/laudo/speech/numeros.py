"""Números falados em pt-BR → algarismos, com pedido de confirmação quando o número é crítico.

O ASR devolve ora "quarenta e duas cabeças", ora "42 cabeças", ora "2 mil metros". Antes de o texto ir para o
condutor, `normalizar()` troca números por extenso por algarismos ("quarenta e duas cabeças" → "42 cabeças",
"oitocentos metros" → "800 metros", "dois mil e quinhentos reais" → "2500 reais") e marca como **crítico**
todo número ligado a uma grandeza que vira alegação no laudo (cabeças/animais, metros, hectares, reais).
Número crítico pede confirmação do fiscal ("Entendi 42 cabeças. Confirma?") antes do turno: um "quarenta"
ouvido como "catorze" não pode virar alegação sem o humano ver.

Regras de leitura (determinísticas, sem LLM):
- composição com "e" só quando a ordem casa ("quarenta e duas" = 42; "cinco e seis" fica "5 e 6");
- "um"/"uma" isolados são artigo, salvo antes de unidade ("uma cabeça" = 1; "uma cerca" fica);
- "mil", "milhão" multiplicam ("dois mil e quinhentos" = 2500; "2 mil" = 2000; "um milhão" = 1000000);
- "e meio"/"e meia" somam 0,5 ("dois e meio hectares" = 2,5); "vírgula" abre a parte decimal
  ("três vírgula cinco" = 3,5);
- algarismos que já vieram do ASR ficam como estão, mas também contam como número (e podem ser críticos).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------

_UNIDADES = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezasseis": 16,
    "dezessete": 17,
    "dezassete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "dezanove": 19,
}
_DEZENAS = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
_CENTENAS = {
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
_MULTIPLICADORES = {
    "mil": 1000,
    "milhao": 1_000_000,
    "milhoes": 1_000_000,
    "bilhao": 1_000_000_000,
    "bilhoes": 1_000_000_000,
}
_MEIO = {"meio", "meia"}
_VIRGULA = {"virgula"}
_ARTIGOS = {"um", "uma"}

# Unidade (forma normalizada sem acento) → (grandeza, unidade canônica). A grandeza define se é crítico.
_UNIDADES_MEDIDA: dict[str, tuple[str, str]] = {}
for _p in (
    "cabeca",
    "cabecas",
    "boi",
    "bois",
    "vaca",
    "vacas",
    "garrote",
    "garrotes",
    "novilha",
    "novilhas",
    "novilho",
    "novilhos",
    "bezerro",
    "bezerros",
    "bezerra",
    "bezerras",
    "animal",
    "animais",
    "res",
    "reses",
    "bovino",
    "bovinos",
    "touro",
    "touros",
    "matriz",
    "matrizes",
    "cab",
):
    _UNIDADES_MEDIDA[_p] = ("quantidade", "cabeca")
for _p in ("metro", "metros", "m", "metro linear", "metros lineares"):
    _UNIDADES_MEDIDA[_p] = ("comprimento", "m")
for _p in ("quilometro", "quilometros", "km"):
    _UNIDADES_MEDIDA[_p] = ("comprimento", "km")
for _p in ("hectare", "hectares", "ha"):
    _UNIDADES_MEDIDA[_p] = ("area", "ha")
for _p in ("alqueire", "alqueires"):
    _UNIDADES_MEDIDA[_p] = ("area", "alqueire")
for _p in ("real", "reais"):
    _UNIDADES_MEDIDA[_p] = ("valor", "R$")
for _p in ("ua", "uas", "unidade animal", "unidades animais"):
    _UNIDADES_MEDIDA[_p] = ("quantidade", "UA")
_GRANDEZAS_CRITICAS = {"quantidade", "comprimento", "area", "valor"}
_ROTULO_UNIDADE = {
    "cabeca": ("cabeça", "cabeças"),
    "m": ("metro", "metros"),
    "km": ("quilômetro", "quilômetros"),
    "ha": ("hectare", "hectares"),
    "alqueire": ("alqueire", "alqueires"),
    "R$": ("real", "reais"),
    "UA": ("UA", "UA"),
}

_TOKEN = re.compile(r"R\$|\d+(?:[.,]\d+)*|[^\W\d_]+|\S", re.UNICODE)
_SIM = re.compile(
    r"^\s*(sim|isso|confirmo|confirmado|correto|certo|exato|pode( mandar| enviar| seguir)?|"
    r"t[aá] certo|positivo|ok|beleza)\b",
    re.IGNORECASE,
)
_NAO = re.compile(r"^\s*(n[aã]o|errado|negativo|cancela|corrige|corrigir|t[aá] errado)\b", re.IGNORECASE)


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()


@dataclass
class _Tok:
    texto: str
    norm: str
    ini: int
    fim: int


@dataclass
class NumeroFalado:
    valor: float
    original: str  # trecho como veio do ASR
    inicio: int  # posição no texto original
    fim: int
    escrito: str  # como ficou no texto normalizado (ex.: "42")
    grandeza: str | None = None  # quantidade | comprimento | area | valor
    unidade: str | None = None  # cabeca | m | km | ha | alqueire | R$ | UA
    critico: bool = False
    por_extenso: bool = False  # veio por extenso (e não em algarismos)
    unidade_texto: str | None = None  # a palavra dita ("garrotes", "hectare")

    def rotulo(self) -> str:
        """Ex.: "42 garrotes", "800 metros", "R$ 2.500"."""
        v = formatar_br(self.valor)
        if self.unidade == "R$":
            return f"R$ {v}"
        if self.unidade_texto and self.unidade == "cabeca" and len(self.unidade_texto) > 3:
            return f"{v} {self.unidade_texto.lower()}"
        if self.unidade in _ROTULO_UNIDADE:
            sing, plur = _ROTULO_UNIDADE[self.unidade]
            return f"{v} {sing if self.valor == 1 else plur}"
        return v


@dataclass
class ResultadoNumeros:
    original: str
    texto: str  # normalizado (algarismos)
    numeros: list[NumeroFalado] = field(default_factory=list)

    @property
    def criticos(self) -> list[NumeroFalado]:
        return [n for n in self.numeros if n.critico]

    @property
    def precisa_confirmar(self) -> bool:
        return bool(self.criticos)

    def pedido_confirmacao(self) -> str | None:
        """Frase curta para a tela e para a voz ("Entendi 42 cabeças e 800 metros. Confirma?")."""
        crit = self.criticos
        if not crit:
            return None
        rotulos = [n.rotulo() for n in crit]
        lista = rotulos[0] if len(rotulos) == 1 else ", ".join(rotulos[:-1]) + " e " + rotulos[-1]
        return f"Entendi {lista}. Confirma?"

    def como_dict(self) -> dict:
        return {
            "original": self.original,
            "texto": self.texto,
            "numeros": [n.__dict__ | {"rotulo": n.rotulo()} for n in self.numeros],
            "precisa_confirmar": self.precisa_confirmar,
            "pedido_confirmacao": self.pedido_confirmacao(),
        }


def formatar_br(v: float) -> str:
    """1200 → "1.200"; 2.5 → "2,5"."""
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    s = f"{v:,.6f}".rstrip("0").rstrip(".")
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _escrever(v: float) -> str:
    """Forma que vai para o condutor: algarismos sem separador de milhar ("2500", "2,5")."""
    if float(v).is_integer():
        return str(int(v))
    return (f"{v:.6f}".rstrip("0").rstrip(".")).replace(".", ",")


def _tokens(texto: str) -> list[_Tok]:
    return [_Tok(m.group(0), _sem_acento(m.group(0)), m.start(), m.end()) for m in _TOKEN.finditer(texto)]


def _classe(norm: str) -> tuple[str, int] | None:
    if norm in _UNIDADES:
        return "unidade", _UNIDADES[norm]
    if norm in _DEZ_A_DEZENOVE:
        return "dezena_baixa", _DEZ_A_DEZENOVE[norm]
    if norm in _DEZENAS:
        return "dezena", _DEZENAS[norm]
    if norm in _CENTENAS:
        return "centena", _CENTENAS[norm]
    if norm in _MULTIPLICADORES:
        return "mult", _MULTIPLICADORES[norm]
    return None


def _digitos(t: str) -> float | None:
    """Algarismos vindos do ASR: "42", "1.200" (milhar), "2,5" (decimal)."""
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", t):
        return None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", t):
        return float(t.replace(".", ""))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d+", t):
        return float(t.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d+[.,]\d+", t):
        return float(t.replace(",", "."))
    if re.fullmatch(r"\d+", t):
        return float(t)
    return None


# Lugar de cada classe dentro de um grupo de três algarismos; um componente só pode seguir outro de lugar
# maior ("quarenta" (10) → "duas" (1) ok; "cinco" (1) → "seis" (1) não).
_LUGAR = {"centena": 100, "dezena": 10, "dezena_baixa": 10, "unidade": 1}


class _Leitor:
    """Lê um número por extenso a partir da posição `i`; devolve (valor, índice após o número) ou None."""

    def __init__(self, toks: list[_Tok]):
        self.toks = toks

    def _pode_continuar_grupo(self, j: int, lugar_atual: int | None, ultimo: str | None) -> bool:
        if j >= len(self.toks):
            return False
        c = _classe(self.toks[j].norm)
        if c is None or c[0] == "mult":
            return False
        if ultimo == "cem":  # "cem" não admite complemento ("cento e ...", sim)
            return False
        return (
            lugar_atual is None
            or _LUGAR[c[0]] < lugar_atual
            and not (ultimo in ("dezena_baixa",) and c[0] in ("unidade",))
        )

    def ler(self, i: int) -> tuple[float, int] | None:
        toks = self.toks
        total = 0.0
        grupo = 0.0
        lugar: int | None = None
        ultimo: str | None = None
        maior_mult = 0
        j = i
        lido_algum = False
        while j < len(toks):
            n = toks[j].norm
            c = _classe(n)
            dig = _digitos(toks[j].texto)
            if (
                dig is not None
                and not lido_algum
                and j + 1 < len(toks)
                and toks[j + 1].norm in _MULTIPLICADORES
            ):
                # "2 mil", "1,5 milhão"
                grupo, lugar, ultimo, lido_algum = dig, 1, "digito", True
                j += 1
                continue
            if c is None:
                if n == "e" and lido_algum and j + 1 < len(toks):
                    prox = toks[j + 1].norm
                    if prox in _MEIO:
                        break  # tratado fora
                    if lugar is None and ultimo == "mult":
                        # "mil e duzentos", "dois mil e cinquenta"
                        if _classe(prox) and _classe(prox)[0] != "mult":
                            j += 1
                            continue
                    elif self._pode_continuar_grupo(j + 1, lugar, ultimo):
                        j += 1
                        continue
                break
            classe, valor = c
            if classe == "mult":
                if not lido_algum and n != "mil":
                    break  # "milhão" sozinho não é número
                base = grupo if (lido_algum and grupo) else 1.0
                if valor > maior_mult and maior_mult:
                    total = (total + base) * valor
                else:
                    total += base * valor
                maior_mult = max(maior_mult, int(valor))
                grupo, lugar, ultimo, lido_algum = 0.0, None, "mult", True
                j += 1
                continue
            # componente de grupo
            if lido_algum and ultimo not in ("mult",) and not self._pode_continuar_grupo(j, lugar, ultimo):
                break
            grupo += valor
            lugar = _LUGAR[classe]
            ultimo = "cem" if n == "cem" else classe
            lido_algum = True
            j += 1
        if not lido_algum:
            return None
        return total + grupo, j


def _unidade_apos(toks: list[_Tok], j: int) -> tuple[str, str, int] | None:
    """Unidade nas próximas palavras (pula "de"/"do"): devolve (grandeza, unidade, índice após)."""
    k = j
    while k < len(toks) and toks[k].norm in ("de", "do", "da"):
        k += 1
    if k >= len(toks):
        return None
    dois = f"{toks[k].norm} {toks[k + 1].norm}" if k + 1 < len(toks) else ""
    if dois in _UNIDADES_MEDIDA:
        g, u = _UNIDADES_MEDIDA[dois]
        return g, u, k + 2
    if toks[k].norm in _UNIDADES_MEDIDA:
        g, u = _UNIDADES_MEDIDA[toks[k].norm]
        return g, u, k + 1
    return None


def _nome_proprio(texto: str, t: _Tok) -> bool:
    """Palavra-número com maiúscula no meio da frase é nome próprio ("Três Ranchos", "Sete Lagoas")."""
    if not t.texto[:1].isupper():
        return False
    antes = texto[: t.ini].rstrip()
    return bool(antes) and antes[-1] not in ".!?:;\"'«(—-"


def _decimais(toks: list[_Tok], i: int, leitor: _Leitor) -> tuple[str, int] | None:
    """Parte decimal depois de "vírgula": "cinco" → "5", "zero cinco" → "05", "25" → "25"."""
    zeros = 0
    q = i
    while q < len(toks) and toks[q].norm == "zero":
        zeros += 1
        q += 1
    if q < len(toks) and (d := _digitos(toks[q].texto)) is not None and float(d).is_integer():
        return "0" * zeros + str(int(d)), q + 1
    lido = leitor.ler(q) if q < len(toks) else None
    if lido is None:
        return ("0" * zeros, q) if zeros else None
    return "0" * zeros + str(int(lido[0])), lido[1]


def normalizar(texto: str) -> ResultadoNumeros:
    """Troca números por extenso por algarismos e marca os críticos (com unidade de alegação)."""
    texto = texto or ""
    toks = _tokens(texto)
    leitor = _Leitor(toks)
    saida: list[str] = []
    numeros: list[NumeroFalado] = []
    cursor = 0  # posição no texto original já copiada
    i = 0
    while i < len(toks):
        t = toks[i]
        # "R$ 2.500" / "R$ dois mil"
        prefixo_rs = t.texto == "R$"
        k = i + 1 if prefixo_rs else i
        if k >= len(toks):
            break
        lido = None
        por_extenso = False
        dig = _digitos(toks[k].texto)
        if dig is not None and not (k + 1 < len(toks) and toks[k + 1].norm in _MULTIPLICADORES):
            lido = (dig, k + 1)
        else:
            lido = leitor.ler(k)
            por_extenso = lido is not None and _digitos(toks[k].texto) is None
        if lido is None or (por_extenso and _nome_proprio(texto, toks[k])):
            i += 1
            continue
        valor, j = lido
        so_uma_palavra = j == k + 1
        # "e meio" / "vírgula X"
        if j + 1 < len(toks) and toks[j].norm == "e" and toks[j + 1].norm in _MEIO:
            so_uma_palavra = False
            valor += 0.5
            j += 2
        elif j + 1 < len(toks) and toks[j].norm in _VIRGULA:
            dec = _decimais(toks, j + 1, leitor)
            if dec is not None:
                valor = float(f"{int(valor)}.{dec[0]}")
                j = dec[1]
                so_uma_palavra = False
        # artigo "um"/"uma" isolado: só é número antes de unidade ("uma cabeça"; "uma cerca" fica)
        if (
            por_extenso
            and so_uma_palavra
            and toks[k].norm in _ARTIGOS
            and (_unidade_apos(toks, j) is None or (j < len(toks) and toks[j].norm in ("de", "do", "da")))
        ):
            i += 1
            continue
        unidade = _unidade_apos(toks, j)
        grandeza, unid = (unidade[0], unidade[1]) if unidade else (None, None)
        unid_txt = toks[unidade[2] - 1].texto if unidade else None
        if prefixo_rs:
            grandeza, unid = "valor", "R$"
        ini, fim = toks[k].ini, toks[j - 1].fim
        escrito = _escrever(valor)
        if por_extenso or escrito != texto[ini:fim]:
            saida.append(texto[cursor:ini])
            saida.append(escrito)
            cursor = fim
        numeros.append(
            NumeroFalado(
                valor=valor,
                original=texto[ini:fim],
                inicio=ini,
                fim=fim,
                escrito=escrito,
                grandeza=grandeza,
                unidade=unid,
                critico=grandeza in _GRANDEZAS_CRITICAS,
                por_extenso=por_extenso,
                unidade_texto=unid_txt,
            )
        )
        i = j
    saida.append(texto[cursor:])
    return ResultadoNumeros(original=texto, texto="".join(saida), numeros=numeros)


def eh_confirmacao(texto: str) -> bool | None:
    """Resposta curta a um pedido de confirmação: True (sim), False (não) ou None (outra fala)."""
    t = (texto or "").strip()
    if not t or len(t) > 40:
        return None
    if _NAO.search(t):
        return False
    if _SIM.search(t):
        return True
    return None
