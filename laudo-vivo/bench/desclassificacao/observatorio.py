"""Observatório de desclassificações do crédito rural: leitura em streaming dos microdados do Sicor (BCB).

Porte em Python dos scripts `.awk` da análise exploratória original:

| awk original | aqui |
|---|---|
| `join.awk` (atributos da operação de cada desclassificação) | `LeitorOperacoes.juncao` |
| `agg.awk` (categoria, UF, sistema da IF, ano da operação) | `sistema`, `categoria`, `enriquecer` |
| `base.awk` (denominadores: operações por categoria, ano e UF) | `LeitorOperacoes.base` |
| `area.awk` (itens com animais por faixa de área: 0, até 300 ha, acima de 300 ha) | `LeitorOperacoes.area` |

Funções puras sobre iteradores de linhas: o download (`laudo.geo.fontes`) e a gravação ficam em
`bench/desclassificacao/build.py`. Nada aqui guarda o arquivo bruto: só agregados, os atributos da operação
de cada desclassificação e, para o retro-teste (`eval/retroteste/PROTOCOLO.md`), as linhas das operações da
população com as colunas de originação da lista fechada `CAMPOS_ORIGINACAO`.

Formato das desclassificações (`sicor_desclassificacao.gz`, cabeçalho
`#REF_BACEN;NU_ORDEM;DT_DESC;CD_MOTIVO_DESC;VL_DESC;TIPO_DESC`): `DT_DESC` vem como `MM/DD/AAAA hh:mm:ss`
(mês antes do dia), diferente das datas do arquivo de operações (`DD/MM/AAAA`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date

BCB = "https://www.bcb.gov.br/htms/sicor"
URL_DESC = f"{BCB}/DadosBrutos/sicor_desclassificacao.gz"
URL_MOTIVOS = f"{BCB}/MotivoDesclassificacao.csv"
URL_EMPREENDIMENTO = f"{BCB}/Empreendimento.csv"


def url_operacoes(ano: int) -> str:
    return f"{BCB}/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_{ano}.gz"


def url_glebas(ano: int) -> str:
    return f"{BCB}/DadosBrutos/SICOR_GLEBAS_WKT_{ano}.gz"


# Tabelas de domínio que o retro-teste usa (as mesmas de scripts/dados_sicor.py).
TABELAS_RETRO = {
    "empreendimento": URL_EMPREENDIMENTO,
    "categoria_emitente": f"{BCB}/CategoriaEmitente.csv",
    "programa": f"{BCB}/Programa.csv",
    "fonte_recursos": f"{BCB}/FonteRecursos.csv",
    "lista_ifs": f"{BCB}/DadosBrutos/SICOR_LISTA_IFS.csv",
    "fase_ciclo_producao": f"{BCB}/FaseCicloProducao.csv",
}

ANOS_OPERACOES = tuple(range(2013, 2027))  # as desclassificações publicadas apontam operações de 2013 a 2026
ANOS_RETRO = (2022, 2023, 2024)

# Lista fechada de colunas de originação gravadas para o retro-teste (PROTOCOLO.md, seção 3).
CAMPOS_ORIGINACAO = (
    "REF_BACEN",
    "NU_ORDEM",
    "CNPJ_IF",
    "DT_EMISSAO",
    "DT_VENCIMENTO",
    "CD_CATEG_EMITENTE",
    "CD_FONTE_RECURSO",
    "CD_ESTADO",
    "CD_EMPREENDIMENTO",
    "CD_PROGRAMA",
    "CD_FASE_CICLO_PRODUCAO",
    "VL_QUANTIDADE",
    "VL_PARC_CREDITO",
    "VL_REC_PROPRIO",
    "VL_AREA_FINANC",
    "CD_CNPJ_CADASTRANTE",
    "VL_AREA_INFORMADA",
    "PC_BONUS_CAR",
)
# Informação posterior à contratação (ou fora da originação) que nunca entra no retro-teste.
CAMPOS_EXCLUIDOS = (
    "VL_PRODUTIV_OBTIDA",
    "DT_INIC_COLHEITA",
    "DT_FIM_COLHEITA",
    "DT_INIC_PLANTIO",
    "DT_FIM_PLANTIO",
    "VL_PREV_PROD",
    "VL_RECEITA_BRUTA_ESPERADA",
)

# Sistemas de IF como no agg.awk: concedente (CNPJ_IF) ou cadastrante (sistemas cooperativos).
SISTEMAS_CNPJ_IF = {
    "00000000": "BB",
    "07237373": "BNB",
    "04902979": "BASA",
    "00360305": "CAIXA",
    "60746948": "BRADESCO",
}
SISTEMAS_COOP = {"02038232": "SICOOB", "01181521": "SICREDI", "01401771": "CRESOL"}


# ---------------------------------------------------------------------------
# Tabelas de domínio
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Empreendimento:
    finalidade: str
    atividade: str
    modalidade: str
    produto: str
    unidade_medida: str

    @property
    def categoria(self) -> str:
        """Chave do agg.awk: finalidade|atividade|modalidade."""
        return f"{self.finalidade}|{self.atividade}|{self.modalidade}"


def _limpar(c: str) -> str:
    return c.strip().strip('"').strip()


def ler_empreendimentos(linhas: Iterable[str]) -> dict[str, Empreendimento]:
    """`Empreendimento.csv` (separador `;`, aspas, cabeçalho com `#`). Código repetido: vale o primeiro."""
    it = iter(linhas)
    cab = [_limpar(c).lstrip("#") for c in next(it).split(";")]
    i = {
        n: cab.index(n)
        for n in ("CODIGO", "FINALIDADE", "ATIVIDADE", "MODALIDADE", "PRODUTO", "UNIDADE_MEDIDA")
    }
    out: dict[str, Empreendimento] = {}
    for ln in it:
        if not ln.strip():
            continue
        p = [_limpar(c) for c in ln.split(";")]
        cod = p[i["CODIGO"]]
        if cod and cod not in out:
            out[cod] = Empreendimento(
                p[i["FINALIDADE"]],
                p[i["ATIVIDADE"]],
                p[i["MODALIDADE"]],
                p[i["PRODUTO"]],
                p[i["UNIDADE_MEDIDA"]],
            )
    return out


def ler_motivos(linhas: Iterable[str]) -> dict[str, str]:
    """`MotivoDesclassificacao.csv` (separador `,`, aspas): código de 3 dígitos -> descrição."""
    out = {}
    for ln in linhas:
        if not ln.strip() or ln.startswith("#"):
            continue
        cod, _, desc = ln.partition(",")
        out[_limpar(cod).zfill(3)] = _limpar(desc)
    return out


def eh_compra_gado(e: Empreendimento | None) -> bool:
    """Item de compra de gado na definição do bench (bench/fiscal_go/build.py, `compra_tipo`)."""
    if e is None or e.produto != "BOVINOS":
        return False
    return (e.finalidade == "Investimento" and e.modalidade == "AQUISIÇÃO DE ANIMAIS") or (
        e.finalidade == "Custeio" and e.modalidade == "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS"
    )


def eh_animais_area(e: Empreendimento | None) -> bool:
    """Filtro do area.awk: categoria com ANIMAIS ou BOVINOCULTURA."""
    return e is not None and ("ANIMAIS" in e.categoria or "BOVINOCULTURA" in e.categoria)


def sistema(cnpj_if: str, cadastrante: str) -> str:
    """Sistema da IF como no agg.awk (BB, cooperativas pelo cadastrante, bancos públicos, Bradesco, OUTRO)."""
    if cnpj_if == "00000000":
        return "BB"
    for cnpj, nome in SISTEMAS_COOP.items():
        if cadastrante == cnpj or (nome != "CRESOL" and cnpj_if == cnpj):
            return nome
    return SISTEMAS_CNPJ_IF.get(cnpj_if, "OUTRO")


# ---------------------------------------------------------------------------
# Desclassificações
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Desclassificacao:
    ref_bacen: str
    nu_ordem: int
    dt_desc: date
    cd_motivo: str  # 3 dígitos ("001", "013", "999")
    vl_desc: float
    tipo_desc: str  # PARCIAL ou TOTAL

    @property
    def chave(self) -> tuple:
        """Identidade do registro, para comparar versões do arquivo."""
        return (
            self.ref_bacen,
            self.nu_ordem,
            self.dt_desc.isoformat(),
            self.cd_motivo,
            round(self.vl_desc * 100),
            self.tipo_desc,
        )


def _data_desc(s: str) -> date:
    """`MM/DD/AAAA hh:mm:ss` -> date."""
    m, d, a = s.split(" ")[0].split("/")
    return date(int(a), int(m), int(d))


def ler_desclassificacoes(linhas: Iterable[str]) -> Iterator[Desclassificacao]:
    for ln in linhas:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split(";")
        yield Desclassificacao(
            ref_bacen=p[0],
            nu_ordem=int(p[1]),
            dt_desc=_data_desc(p[2]),
            cd_motivo=str(int(p[3])).zfill(3),
            vl_desc=float(p[4] or 0),
            tipo_desc=p[5],
        )


# ---------------------------------------------------------------------------
# Arquivo anual de operações (base.awk + join.awk + area.awk + extração do retro-teste)
# ---------------------------------------------------------------------------


def _f(s: str) -> float:
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


@dataclass
class LeitorOperacoes:
    """Consome as linhas (com cabeçalho) de um `SICOR_OPERACAO_BASICA_ESTADO_<ano>.gz`.

    - `base[(uf, cd_empreendimento)] = [n_operacoes, n_itens, valor_itens]`: a operação conta no
      empreendimento
      do seu primeiro item (como o base.awk); itens e valores contam no empreendimento de cada item.
    - `juncao[ref] = {...}`: atributos do primeiro item e valor somado, só para as operações em `refs`.
    - `area[(escopo, faixa)] = [itens, valor]`: itens com animais por faixa de área (area.awk).
    - Com `extrair_retro`, guarda as linhas (colunas `CAMPOS_ORIGINACAO`) das operações com compra de gado
      (`retro_compra`) e de todas as operações de GO (`retro_go`), com todos os itens de cada operação.
    """

    ano: int
    refs: set[str]
    empreendimentos: dict[str, Empreendimento]
    extrair_retro: bool = False
    base: dict[tuple[str, str], list[float]] = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0.0]))
    juncao: dict[str, dict] = field(default_factory=dict)
    area: Counter = field(default_factory=Counter)
    area_valor: Counter = field(default_factory=Counter)
    retro_compra: list[str] = field(default_factory=list)
    retro_go: list[str] = field(default_factory=list)
    linhas: int = 0
    operacoes: int = 0
    fora_de_ordem: int = 0
    cabecalho: list[str] = field(default_factory=list)

    def consumir(self, linhas: Iterator[str]) -> None:
        it = iter(linhas)
        cab = [c.strip().lstrip("#") for c in next(it).split(";")]
        self.cabecalho = cab
        ix = {n: cab.index(n) for n in CAMPOS_ORIGINACAO}
        i_ref, i_if, i_dt = ix["REF_BACEN"], ix["CNPJ_IF"], ix["DT_EMISSAO"]
        i_uf, i_emp, i_val = ix["CD_ESTADO"], ix["CD_EMPREENDIMENTO"], ix["VL_PARC_CREDITO"]
        i_ai, i_af, i_cad = ix["VL_AREA_INFORMADA"], ix["VL_AREA_FINANC"], ix["CD_CNPJ_CADASTRANTE"]
        sel = [ix[n] for n in CAMPOS_ORIGINACAO]
        emp = self.empreendimentos
        compra = {c for c, e in emp.items() if eh_compra_gado(e)}
        animais = {c for c, e in emp.items() if eh_animais_area(e)}
        refs, base, juncao = self.refs, self.base, self.juncao
        ultimo, ultimo_int = None, -1
        buf: list[list[str]] = []
        for ln in it:
            if not ln:
                continue
            p = ln.split(";")
            if len(p) < len(cab):
                continue
            self.linhas += 1
            ref, cd, uf, v = p[i_ref], p[i_emp], p[i_uf], _f(p[i_val])
            nova = ref != ultimo
            if nova:
                if buf:
                    self._fechar(buf, sel, compra)
                    buf = []
                self.operacoes += 1
                base[(uf, cd)][0] += 1
                try:
                    r_int = int(ref)
                except ValueError:
                    r_int = ultimo_int
                if r_int < ultimo_int:
                    self.fora_de_ordem += 1
                ultimo, ultimo_int = ref, r_int
            b = base[(uf, cd)]
            b[1] += 1
            b[2] += v
            if ref in refs:
                j = juncao.get(ref)
                if j is None:
                    juncao[ref] = {
                        "uf": uf,
                        "cd_empreendimento": cd,
                        "if_cnpj_base": p[i_if],
                        "cadastrante_cnpj_base": p[i_cad],
                        "dt_emissao": p[i_dt],
                        "valor_rs": v,
                        "n_itens": 1,
                    }
                else:
                    j["valor_rs"] += v
                    j["n_itens"] += 1
            if cd in animais:
                a = max(_f(p[i_af]), _f(p[i_ai]))
                faixa = "0" if a == 0 else ("ate_300" if a <= 300 else "acima_300")
                self.area[("BR", faixa)] += 1
                self.area_valor[("BR", faixa)] += v
                if uf == "GO":
                    self.area[("GO", faixa)] += 1
                    self.area_valor[("GO", faixa)] += v
            if self.extrair_retro:
                buf.append(p)
        if buf:
            self._fechar(buf, sel, compra)

    def _fechar(self, buf: list[list[str]], sel: list[int], compra: set[str]) -> None:
        if not self.extrair_retro:
            return
        i_emp = sel[CAMPOS_ORIGINACAO.index("CD_EMPREENDIMENTO")]
        i_uf = sel[CAMPOS_ORIGINACAO.index("CD_ESTADO")]
        tem_compra = any(p[i_emp] in compra for p in buf)
        eh_go = buf[0][i_uf] == "GO"
        if not (tem_compra or eh_go):
            return
        for p in buf:
            linha = ";".join(p[i] for i in sel)
            if tem_compra:
                self.retro_compra.append(linha)
            if eh_go:
                self.retro_go.append(linha)


def filtrar_glebas(linhas: Iterator[str], refs: set[str]) -> tuple[list[str], int]:
    """Linhas `REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA` das operações em `refs` (sem o cabeçalho)."""
    it = iter(linhas)
    cab = [c.strip().lstrip("#") for c in next(it).split(";")]
    if cab[:4] != ["REF_BACEN", "NU_ORDEM", "NU_INDICE", "GT_GEOMETRIA"]:
        raise ValueError(f"cabeçalho inesperado nas glebas: {cab[:4]}")
    out, lidas = [], 0
    for ln in it:
        lidas += 1
        if ln.split(";", 1)[0] in refs:
            out.append(ln)
    return out, lidas


# ---------------------------------------------------------------------------
# Enriquecimento (agg.awk)
# ---------------------------------------------------------------------------


def enriquecer(
    d: Desclassificacao, j: dict | None, ano_operacao: int | None, emp: dict[str, Empreendimento]
) -> dict:
    """Linha da tabela `desclassificacoes.parquet`: o registro mais os atributos da operação."""
    e = emp.get(j["cd_empreendimento"]) if j else None
    return {
        "ref_bacen": d.ref_bacen,
        "nu_ordem": d.nu_ordem,
        "dt_desc": d.dt_desc,
        "ano_desc": d.dt_desc.year,
        "cd_motivo": d.cd_motivo,
        "vl_desc": d.vl_desc,
        "tipo_desc": d.tipo_desc,
        "ano_operacao": ano_operacao,
        "uf": j["uf"] if j else None,
        "cd_empreendimento": j["cd_empreendimento"] if j else None,
        "categoria": e.categoria if e else (f"?{j['cd_empreendimento']}" if j else None),
        "finalidade": e.finalidade if e else None,
        "atividade": e.atividade if e else None,
        "modalidade": e.modalidade if e else None,
        "produto": e.produto if e else None,
        "if_cnpj_base": j["if_cnpj_base"] if j else None,
        "cadastrante_cnpj_base": j["cadastrante_cnpj_base"] if j else None,
        "sistema": sistema(j["if_cnpj_base"], j["cadastrante_cnpj_base"]) if j else None,
        "dt_emissao_operacao": j["dt_emissao"] if j else None,
        "valor_operacao_rs": round(j["valor_rs"], 2) if j else None,
    }
