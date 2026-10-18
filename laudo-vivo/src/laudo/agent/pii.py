"""Mascaramento de dados pessoais (POL-08): CPF, CNPJ, telefone, e-mail, PIN ditado e, opcionalmente, nomes.

Usado em logs, traces, gravações de LLM e em qualquer texto que vá para um provedor de LLM externo.
Prefere mascarar demais a vazar: em log, falso positivo custa pouco; falso negativo é incidente de LGPD.
Os marcadores são fixos (`[CPF]`, `[CNPJ]`, `[TELEFONE]`, `[EMAIL]`, `[PIN]`, `[NOME]`) e não carregam hash
do valor (hash de CPF ou de PIN é reversível por força bruta). O PIN é a credencial da assinatura humana
(POL-03): dito na conversa ("a senha é ...", "meu PIN é ..."), vira `[PIN]`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

CPF = "[CPF]"
CNPJ = "[CNPJ]"
TELEFONE = "[TELEFONE]"
EMAIL = "[EMAIL]"
PIN = "[PIN]"
NOME = "[NOME]"

# Domínio de topo alfabético (.com, .br, .invalid): versão de ferramenta ou de rulebook (`mcr_2_7@0.3.0`,
# `contador@0.2.0`) não é e-mail e não pode virar "[EMAIL]" no trace.
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}(?![\w-])")
# CNPJ formatado, inclusive o alfanumérico (IN RFB 2.229/2024, em uso desde 07/2026).
_CNPJ_FMT = re.compile(r"(?<![0-9A-Za-z])[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-?\d{2}(?!\d)")
_CPF_FMT = re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-?\d{2}(?![\d])")
# "CPF 123 456 789 00", "cpf: 12345678900", "CPF é 123.456.789-00" (ditado pelo ASR com espaços)
_CPF_GATILHO = re.compile(r"(\bc\.?p\.?f\.?\b[^\d\n]{0,25})((?:\d[\s.\-]?){10}\d)(?!\d)", re.IGNORECASE)
_CNPJ_GATILHO = re.compile(
    r"(\bc\.?n\.?p\.?j\.?\b[^\dA-Z\n]{0,25})((?:[\dA-Z][\s./\-]?){13}\d)(?!\d)", re.IGNORECASE
)
_DIG14 = re.compile(r"(?<!\d)\d{14}(?!\d)")
_DIG11 = re.compile(r"(?<!\d)\d{11}(?!\d)")
# (62) 99999-9999 · +55 62 99999-9999 · 62 3333-4444 · 62999999999 (já tratado em _DIG11)
_TELEFONE = re.compile(
    r"(?<![\d/])(?:\+?55[\s.-]?)?(?:\(\d{2}\)|\d{2})[\s.-]?(?:9[\s.]?)?\d{4}[\s.-]\d{4}(?![\d/])"
)
_TEL_GATILHO = re.compile(
    r"(\b(?:telefone|celular|fone|whats(?:app)?|zap)\b[^\d\n]{0,25})((?:\d[\s.\-]?){7,12}\d)", re.IGNORECASE
)
# PIN ditado: gatilho (pin, senha, código de assinatura/acesso/pessoal, "meu código"), até 3 palavras de
# complemento seguidas de ligação explícita ("o PIN do laudo é", "a senha que eu uso é", "minha senha de
# assinatura é") ou só a ligação ("é", "e", ":", "=", ",", "?", "-", "é o"), e o valor: de 1 a 12 dígitos (a API
# aceita PIN de 1 a 12 caracteres; com espaço, ponto ou hífen, como o ASR transcreve) ou o número por extenso
# com pelo menos duas palavras ("quatro três dois um"; "uma" sozinho, como em "a senha é uma só", não é PIN).
_EXTENSO = (r"(?:zero|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|"
            r"(?:c|qu)atorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|"
            r"sessenta|setenta|oitenta|noventa|cem|cento|duzentos|trezentos|quatrocentos|quinhentos|"
            r"seiscentos|setecentos|oitocentos|novecentos|mil)")
_LIGA_PIN = r"(?:[\s:=,?\-]|\b[ée]\b)"
_PIN_GATILHO = re.compile(
    r"(\b(?:pin|senha|c[oó]digo (?:de assinatura|de acesso|pessoal|secreto)|meu c[oó]digo)\b"
    rf"(?:(?:\s+(?![ée]\b)[^\W\d_]+){{1,3}}?\s*(?:[:=,?\-]|\b[ée]\b))?{_LIGA_PIN}{{0,4}}(?:\bo\s+)?)"
    rf"((?<!\d)\d(?:[\s.\-]?\d){{0,11}}(?!\d)|\b{_EXTENSO}\b(?:(?:\s+e\s+|[\s,.\-]+){_EXTENSO}\b)+)",
    re.IGNORECASE,
)
_MAIUSC = "A-ZÁÉÍÓÚÂÊÔÃÕÇ"
_MINUSC = "a-záéíóúâêôãõç"
_NOME = re.compile(
    rf"(\b(?:meu nome é|me chamo|nome do produtor é|nome da produtora é|produtora?|sr\.?|sra\.?|"
    rf"senhora?|dona)"
    rf"\s+)([{_MAIUSC}][{_MINUSC}]+(?:\s+(?:d[aeo]s?\s+)?[{_MAIUSC}][{_MINUSC}]+)*)"
)


def _dv_cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        dv = (s * 10) % 11 % 10
        if dv != int(d[n]):
            return False
    return True


def _dv_cnpj_ok(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, n in ((pesos1, 12), (pesos2, 13)):
        s = sum(int(d[i]) * pesos[i] for i in range(n))
        r = s % 11
        dv = 0 if r < 2 else 11 - r
        if dv != int(d[n]):
            return False
    return True


def _parece_celular(d: str) -> bool:
    return len(d) == 11 and 11 <= int(d[:2]) <= 99 and d[2] == "9"


def mascarar(texto: str | None, nomes: bool = True) -> str:
    """Devolve o texto com CPF, CNPJ, telefone, e-mail (e nomes após gatilhos) mascarados. A chave de acesso da
    NF-e (que embute o CPF/CNPJ do emitente) vira `522604…59429439` (`laudo.privacidade.mascarar_texto`)."""
    if not texto:
        return texto or ""
    from laudo.privacidade import mascarar_texto

    t = _EMAIL.sub(EMAIL, mascarar_texto(texto))
    t = _PIN_GATILHO.sub(lambda m: m.group(1) + PIN, t)
    t = _CNPJ_FMT.sub(CNPJ, t)
    t = _CPF_FMT.sub(CPF, t)
    t = _CPF_GATILHO.sub(lambda m: m.group(1) + CPF, t)
    t = _CNPJ_GATILHO.sub(lambda m: m.group(1) + CNPJ, t)
    t = _DIG14.sub(lambda m: CNPJ if _dv_cnpj_ok(m.group(0)) else m.group(0), t)

    def _onze(m: re.Match) -> str:
        d = m.group(0)
        if _dv_cpf_ok(d):
            return CPF
        if _parece_celular(d):
            return TELEFONE
        return d

    t = _DIG11.sub(_onze, t)
    t = _TEL_GATILHO.sub(lambda m: m.group(1) + TELEFONE, t)
    t = _TELEFONE.sub(TELEFONE, t)
    if nomes:
        t = _NOME.sub(lambda m: m.group(1) + NOME, t)
    return t


def mascarar_obj(obj: Any, nomes: bool = True) -> Any:
    """Aplica `mascarar` recursivamente a strings dentro de dicts, listas e tuplas."""
    if isinstance(obj, str):
        return mascarar(obj, nomes=nomes)
    if isinstance(obj, dict):
        return {k: mascarar_obj(v, nomes=nomes) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mascarar_obj(v, nomes=nomes) for v in obj]
    return obj


def contem_pii(texto: str | None) -> list[str]:
    """Lista os tipos de dado pessoal encontrados (para testes e alertas)."""
    if not texto:
        return []
    m = mascarar(texto)
    return [tipo for tipo in (CPF, CNPJ, TELEFONE, EMAIL, PIN, NOME) if tipo in m and tipo not in texto]


class FiltroLogPII(logging.Filter):
    """Filtro de `logging` que mascara a mensagem já formatada (POL-08 nos logs)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mascarar(record.getMessage())
        record.args = None
        return True


def instalar_filtro_log(logger: logging.Logger | None = None) -> FiltroLogPII:
    """Instala o filtro nos handlers do logger (raiz por padrão) e no próprio logger."""
    alvo = logger or logging.getLogger()
    filtro = FiltroLogPII()
    alvo.addFilter(filtro)
    for h in alvo.handlers:
        h.addFilter(filtro)
    return filtro
