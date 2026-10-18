"""Varre o repositório atrás de CPF, CNPJ, telefone, e-mail e nome de pessoa que não sejam dado sintético.

Uso (na raiz do repositório):
  scripts/py.sh scripts/checar_pii.py                 # código de saída 1 se achar algo
  scripts/py.sh scripts/checar_pii.py --parquet       # também colunas de texto dos .parquet (bench)
  scripts/py.sh scripts/checar_pii.py caminho1 caminho2   # só estes arquivos/diretórios (hook de commit)
  scripts/py.sh scripts/checar_pii.py --permitidos    # mostra também o que a lista de permissões liberou

Fica fora da varredura: `dados_locais/` (dados brutos, ignorado pelo git), `.git/`, `.venv/` e caches. Nenhum
arquivo do repositório é excluído inteiro (nem este script nem o teste dele, que monta os valores com forma
real em tempo de execução).

O que é acusado:
- CPF e CNPJ (inclusive o alfanumérico) com dígito verificador válido: formatados, sem formatação ou ditados
  depois de "CPF";
- telefone, formatado ou ditado depois de "telefone/celular/fone/whatsapp/zap";
- e-mail;
- nome de pessoa (duas ou mais palavras com inicial maiúscula) logo depois de um gatilho: "meu nome é",
  "me chamo", "nome do produtor é", "produtor(a)", "Sr.", "Sra.", "senhor(a)", "dona", as chaves `nome` e
  `nome_produtor`/`nome_proponente`/`nome_emitente`/..., a tag `<xNome>` da NF-e e a célula "Nome" da GTA.

Como marcar dado sintético (o caminho normal; `laudo.docs_fiscais.sintetico` já gera assim e
eval/README.md e eval/golden/gerador/README.md repetem a lista):
- CPF com prefixo 000.000 e DV calculado (`cpf_sintetico`), ex.: 000.000.001-91;
- CNPJ com raiz 99.999.999 e DV calculado (`cnpj_sintetico`), ex.: 99.999.999/0001-XX;
- telefone com DDD 00, ou com o assinante formado só por blocos de um dígito repetido: (62) 99999-0000,
  (62) 99999-9999, 62 3333-4444;
- e-mail em domínio reservado (RFC 2606/6761: example.com/.net/.org, .example, .test, .invalid, .localhost)
  ou nenhum e-mail (em texto de uso escreva `<seu e-mail>`); os endereços técnicos `git@github.com` e
  `*@users.noreply.github.com` também passam;
- nome com TESTE, SINTETICO/SINTÉTICO, FICTICIO/FICTÍCIO, EXEMPLO ou HOMOLOGACAO, ou com os nomes-curinga
  Fulano, Beltrano, Ciclano e Sicrano (ex.: "PRODUTOR TESTE 01", "Fulano Sintético da Silva");
- teste que precisa de documento com forma real (para provar que um detector acusa) monta o valor em tempo de
  execução (ex.: `_cpf_com_dv("123456789")`), para que o número não fique literal no arquivo.

Lista de permissões (`PERMITIDOS`, neste arquivo): só para valor que NÃO pode virar marcador porque é público e
fixo, como o exemplo oficial de um validador. Cada entrada traz o valor exato, os arquivos onde ele pode
aparecer (caminho relativo à raiz, com "/") e o motivo com a fonte; em qualquer outro arquivo o valor continua
acusado (o próprio checar_pii.py, onde a lista mora, é a única exceção). Para pedir uma entrada nova, acrescente-a
no mesmo PR com a fonte pública e cite-a no relatório para a área de Avaliação (dona de `tests/contract/`)
revisar; `tests/contract/test_contrato_checar_pii.py` confere que toda entrada tem motivo, aponta para arquivos
que existem e é de fato acusada fora deles. Dado de pessoa real nunca entra na lista: troque-o por um marcador.

Números de 11/14 dígitos sem formatação só contam como CPF/CNPJ se o dígito verificador conferir (reduz falso
positivo com códigos IBGE, chaves de acesso e hashes); sequências de dígitos coladas em letras ou outros dígitos
(hash hexadecimal, chave de 44 posições) não são consideradas, nem número sem formatação em linha (ou coluna)
de código público (empreendimento do Sicor, chave/protocolo da NF-e, código de estabelecimento).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXCLUIR_DIRS = {"dados_locais", ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".hypothesis",
                "node_modules", ".mypy_cache", ".ferramentas"}
EXT_TEXTO = {".py", ".md", ".yaml", ".yml", ".json", ".jsonl", ".xml", ".html", ".htm", ".txt", ".toml", ".csv",
             ".j2", ".cfg", ".ini", ".sh", ".js", ".ts", ".css", ".svg", ".tsv", ".env", ".sql", ".ipynb"}
NOMES_TEXTO = {".gitignore", ".gitattributes", ".python-version", "Dockerfile", "Makefile"}
MAX_BYTES = 50 * 1024 * 1024

_B = r"(?<![0-9A-Za-z_])"  # fronteira: sem letra/dígito colado antes
_A = r"(?![0-9A-Za-z_])"
CPF_FMT = re.compile(_B + r"(\d{3})\.(\d{3})\.(\d{3})-(\d{2})" + _A)
CNPJ_FMT = re.compile(_B + r"([0-9A-Z]{2})\.([0-9A-Z]{3})\.([0-9A-Z]{3})/([0-9A-Z]{4})-(\d{2})" + _A)
DIG = re.compile(_B + r"(\d{11}|\d{14})" + _A)
CPF_GATILHO = re.compile(r"\bc\.?p\.?f\.?\b[^\d\n]{0,25}((?:\d[\s.\-]?){10}\d)(?!\d)", re.IGNORECASE)
TELEFONE = re.compile(r"(?<![\d/.\w])(?:\+?55[\s.-]?)?(\(\d{2}\)|\d{2})[\s.-]?(9?[\s.]?\d{4})[\s.-](\d{4})(?![\d/.\w-])")
TEL_GATILHO = re.compile(r"\b(?:telefone|celular|fone|whats(?:app)?|zap)\b[^\d\n]{0,25}((?:\d[\s.\-]?){9,12}\d)",
                         re.IGNORECASE)
EMAIL = re.compile(r"(?<![\w.+-])([\w.+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")
# Nome: 2+ palavras com inicial maiúscula (ou todas maiúsculas), aceitando "da/de/do/das/dos/e" no meio.
_MAI = "A-ZÁÉÍÓÚÂÊÔÃÕÇÀ"
_MIN = "a-záéíóúâêôãõçà"
_PALAVRA = rf"(?:[{_MAI}][{_MIN}]+|[{_MAI}]{{2,}})"
_GATILHO_FALA = (r"\b(?:[Mm]eu nome [eé]|[Mm]e chamo|nome d[oa] (?:produtora?|proponente|mutuári[oa]|client[ea]"
                 r"|cooperad[oa])(?: [eé])?|produtora?|[Ss]enhora?|[Dd]ona)\b|\b[Ss]ra?\.")
_GATILHO_CAMPO = (r"\b(?:nome|nome_(?:produtora?|proponente|mutuario|cliente|cooperado|pessoa|responsavel"
                  r"|emitente|destinatario))[\"']?\s*[:=]|<xNome>|<th>Nome</th>\s*<td>")
NOME_GATILHO = re.compile(rf"(?:{_GATILHO_FALA}|{_GATILHO_CAMPO})[\s:\-–]*[\"']?"
                          rf"({_PALAVRA}(?:[ \t]+(?:d[aeo]s?[ \t]+|e[ \t]+)?{_PALAVRA})+)")
NOME_FALSO = re.compile(r"TESTE|SINT[EÉ]TIC|FICT[IÍ]CI|EXEMPLO|HOMOLOGA|\b(?:Fulan|Beltran|Ciclan|Sicran)[oa]\b",
                        re.IGNORECASE)
# Número sem formatação ao lado destas chaves é código público (Sicor, NF-e), não documento de pessoa.
CONTEXTO_CODIGO = re.compile(r"empreendimento|\bcd_|codigo|c[oó]digo|chave|nprot|cean|ref_bacen|cprod",
                             re.IGNORECASE)
DOMINIOS_RESERVADOS = ("example.com", "example.net", "example.org")
TLDS_RESERVADOS = (".example", ".test", ".invalid", ".localhost")
EMAILS_TECNICOS = {"git@github.com"}


@dataclass(frozen=True)
class Permissao:
    """Valor público/sintético que não dá para trocar por marcador; liberado só nos `arquivos` listados."""

    valor: str
    arquivos: tuple[str, ...]  # relativos à raiz do repositório, separados por "/"
    motivo: str  # por que não pode virar marcador, com a fonte pública


# Lista de permissões auditável (ver docstring do módulo para pedir uma entrada nova).
PERMITIDOS: tuple[Permissao, ...] = (
    Permissao(
        valor="12.ABC.345/01DE-35",
        arquivos=("tests/unit/test_docs_comum.py", "tests/unit/test_agente_pii.py"),
        motivo="exemplo oficial do Serpro para o CNPJ alfanumérico (NT Conjunta 2025.001), vetor de teste do DV; "
               "o teste precisa do valor publicado para provar que o cálculo bate com a norma",
    ),
)
ARQUIVO_DA_LISTA = Path(__file__).resolve().relative_to(REPO).as_posix()


def _chave(valor: str) -> str:
    return "".join(c for c in valor if c.isalnum()).upper()


_PERMITIDOS_POR_CHAVE = {_chave(p.valor): p for p in PERMITIDOS}


def permissao(valor: str, arquivo: str | None) -> Permissao | None:
    """Entrada de `PERMITIDOS` que libera `valor` dentro de `arquivo` (relativo à raiz, com "/"), ou None."""
    p = _PERMITIDOS_POR_CHAVE.get(_chave(valor))
    if p is None or arquivo is None:
        return None
    return p if arquivo in p.arquivos or arquivo == ARQUIVO_DA_LISTA else None


def dv_cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def dv_cnpj_ok(d: str) -> bool:
    """DV do CNPJ, inclusive alfanumérico (valor = código ASCII − 48)."""
    if len(d) != 14 or d == d[0] * 14 or not d[12:].isdigit():
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for pesos, n in ((pesos1, 12), ([6] + pesos1, 13)):
        r = sum((ord(d[i]) - 48) * pesos[i] for i in range(n)) % 11
        if (0 if r < 2 else 11 - r) != int(d[n]):
            return False
    return True


def cpf_falso(d: str) -> bool:
    return d.startswith("000000")


def cnpj_falso(d: str) -> bool:
    return d.startswith("99999999")


def telefone_falso(ddd: str, numero: str) -> bool:
    """DDD 00, ou assinante só com blocos de um dígito repetido (99999-0000, 99999-9999, 3333-4444)."""
    dig = re.sub(r"\D", "", numero)
    return ddd.strip("()") == "00" or (len(set(dig[:-4])) == 1 and len(set(dig[-4:])) == 1)


def email_falso(usuario: str, dominio: str) -> bool:
    d = dominio.lower()
    if f"{usuario}@{d}" in EMAILS_TECNICOS or d.endswith("users.noreply.github.com"):
        return True
    return d in DOMINIOS_RESERVADOS or any(d.endswith("." + x) for x in DOMINIOS_RESERVADOS) or d.endswith(
        TLDS_RESERVADOS)


def nome_falso(nome: str) -> bool:
    """Nome com marcador de teste (TESTE, SINTETICO, ...) ou nome-curinga (Fulano, Beltrano, ...)."""
    return bool(NOME_FALSO.search(nome))


@dataclass
class Achado:
    arquivo: str
    linha: int
    tipo: str
    trecho: str
    permissao: Permissao | None = None

    def __str__(self) -> str:
        extra = f" (liberado por PERMITIDOS: {self.permissao.motivo})" if self.permissao else ""
        return f"{self.arquivo}:{self.linha}: {self.tipo}: {self.trecho}{extra}"


def _mascara(s: str) -> str:
    """O relatório não repete o dado inteiro (o próprio log não pode vazar)."""
    return s[:3] + "…" + s[-2:] if len(s) > 6 else "…"


def _candidatos(texto: str, contexto: str = "") -> Iterator[tuple[str, str]]:
    """(tipo, valor bruto) de cada dado com forma real que não é marcador sintético."""
    vistos: set[tuple[int, int]] = set()
    codigo_publico = bool(CONTEXTO_CODIGO.search(contexto or texto))
    for m in CPF_FMT.finditer(texto):
        d = "".join(m.groups())
        vistos.add(m.span())
        if dv_cpf_ok(d) and not cpf_falso(d):
            yield "CPF", m.group(0)
    for m in CNPJ_FMT.finditer(texto):
        d = "".join(m.groups())
        vistos.add(m.span())
        if dv_cnpj_ok(d) and not cnpj_falso(d):
            yield "CNPJ", m.group(0)
    for m in DIG.finditer(texto) if not codigo_publico else ():
        d = m.group(1)
        if len(d) == 11 and dv_cpf_ok(d) and not cpf_falso(d):
            yield "CPF (sem formatação)", d
        elif len(d) == 14 and dv_cnpj_ok(d) and not cnpj_falso(d):
            yield "CNPJ (sem formatação)", d
    for m in CPF_GATILHO.finditer(texto):
        d = re.sub(r"\D", "", m.group(1))
        if dv_cpf_ok(d) and not cpf_falso(d) and not any(a <= m.start(1) < b for a, b in vistos):
            yield "CPF (ditado)", d
    for m in TELEFONE.finditer(texto):
        ddd, num = m.group(1), m.group(2) + m.group(3)
        if not telefone_falso(ddd, num):
            yield "telefone", m.group(0)
    for m in TEL_GATILHO.finditer(texto):
        d = re.sub(r"\D", "", m.group(1))
        if len(d) >= 10 and not telefone_falso(d[:2], d[2:]) and not TELEFONE.search(m.group(0)):
            yield "telefone (ditado)", d
    for m in EMAIL.finditer(texto):
        if not email_falso(m.group(1), m.group(2)):
            yield "e-mail", m.group(0)
    for m in NOME_GATILHO.finditer(texto):
        if not nome_falso(m.group(1)):
            yield "nome", m.group(1)


def achados_na_linha(texto: str, contexto: str = "", arquivo: str | None = None) -> Iterator[tuple[str, str]]:
    """(tipo, trecho mascarado) de cada achado; com `arquivo` (relativo à raiz), aplica `PERMITIDOS`."""
    for tipo, valor in _candidatos(texto, contexto):
        if permissao(valor, arquivo) is None:
            yield tipo, _mascara(valor)


def _achados(texto: str, contexto: str, arquivo: str, onde: str, linha: int) -> Iterator[Achado]:
    for tipo, valor in _candidatos(texto, contexto):
        yield Achado(onde, linha, tipo, _mascara(valor), permissao(valor, arquivo))


def arquivos(raizes: list[Path], parquet: bool) -> Iterator[Path]:
    for raiz in raizes:
        if raiz.is_file():
            yield raiz
            continue
        for p in sorted(raiz.rglob("*")):
            rel = p.relative_to(REPO) if p.is_relative_to(REPO) else p
            if any(parte in EXCLUIR_DIRS for parte in rel.parts) or not p.is_file():
                continue
            if p.suffix.lower() in EXT_TEXTO or p.name in NOMES_TEXTO or (parquet and p.suffix == ".parquet"):
                yield p


def _relativo(p: Path) -> str:
    return p.relative_to(REPO).as_posix() if p.is_relative_to(REPO) else str(p)


def varrer_texto(p: Path, rel: str | None = None) -> Iterator[Achado]:
    rel = rel or _relativo(p)
    if p.stat().st_size > MAX_BYTES:
        yield Achado(rel, 0, "aviso", f"arquivo > {MAX_BYTES // 2**20} MB não varrido")
        return
    with open(p, encoding="utf-8", errors="replace") as f:
        for i, linha in enumerate(f, 1):
            yield from _achados(linha, "", rel, rel, i)


def varrer_parquet(p: Path, rel: str | None = None) -> Iterator[Achado]:
    import pyarrow.parquet as pq

    rel = rel or _relativo(p)
    arq = pq.ParquetFile(p)
    for g in range(arq.num_row_groups):  # um grupo de linhas por vez (RAM baixa)
        tab = arq.read_row_group(g)
        for nome in tab.column_names:
            col = tab.column(nome)
            if not (str(col.type).startswith("string") or str(col.type).startswith("large_string")):
                continue
            for i, v in enumerate(col.to_pylist()):
                if v:
                    yield from _achados(str(v), nome, rel, f"{rel}[{nome}]", i)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caminhos", nargs="*", help="arquivos ou diretórios (padrão: o repositório inteiro)")
    ap.add_argument("--parquet", action="store_true", help="varre também as colunas de texto dos .parquet")
    ap.add_argument("--permitidos", action="store_true", help="mostra também o que a lista de permissões liberou")
    a = ap.parse_args(argv)
    raizes = [Path(c).resolve() for c in a.caminhos] or [REPO]
    achados: list[Achado] = []
    n = 0
    for p in arquivos(raizes, a.parquet):
        n += 1
        rel = _relativo(p)
        try:
            achados.extend(varrer_parquet(p, rel) if p.suffix == ".parquet" else varrer_texto(p, rel))
        except (OSError, ValueError) as e:
            achados.append(Achado(rel, 0, "aviso", f"não foi possível ler: {type(e).__name__}"))
    reais = [x for x in achados if x.tipo != "aviso" and x.permissao is None]
    liberados = [x for x in achados if x.permissao is not None]
    for x in achados:
        if x.permissao is None or a.permitidos:
            print(x)
    print(f"{n} arquivo(s) varrido(s); {len(reais)} possível(is) dado(s) pessoal(is) fora dos marcadores falsos; "
          f"{len(liberados)} ocorrência(s) liberada(s) pela lista de permissões.")
    return 1 if reais else 0


if __name__ == "__main__":
    sys.exit(main())
