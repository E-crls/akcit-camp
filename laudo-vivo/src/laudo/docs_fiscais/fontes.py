"""Regras citáveis e tabelas de referência dos documentos fiscais.

Cada `regra_id` usado pelas conciliações aponta para uma norma. IDs do MCR seguem a convenção do
rulebook (`MCR-2-7-itemN`); a numeração dos itens é a da Seção 2-7 reescrita pela Res. CMN 5.267/2025.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Regras (regra_id -> citação)
# ---------------------------------------------------------------------------

REGRAS: dict[str, dict[str, str]] = {
    # MCR 2-7 (Res. CMN 5.267/2025)
    "MCR-2-7-item1": {
        "norma": "MCR 2-7, item 1 (Res. CMN 5.267/2025)",
        "texto": "procedimentos de fiscalização efetivos, com critérios verificáveis e documentados",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    "MCR-2-7-item2b": {
        "norma": "MCR 2-7, item 2, alínea b (Res. CMN 5.267/2025)",
        "texto": "detectar irregularidades e prevenir desvio de recursos (cruzamento de dados)",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    "MCR-2-7-item3": {
        "norma": "MCR 2-7, item 3 (Res. CMN 5.267/2025)",
        "texto": "métodos remoto, documental e presencial; conformidade da contratação à liquidação",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    "MCR-2-7-item6": {
        "norma": "MCR 2-7, item 6 (Res. CMN 5.267/2025)",
        "texto": "indícios de duplicidade de financiamento ou de recuperação de capital investido",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    "MCR-2-7-item9": {
        "norma": "MCR 2-7, item 9 (Res. CMN 5.267/2025)",
        "texto": "pecuária: itens 6 e 7 se aplicam; contagem por sensoriamento remoto é facultativa",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    "MCR-2-7-item16a": {
        "norma": "MCR 2-7, item 16, alínea a (Res. CMN 5.267/2025)",
        "texto": "construção, reforma ou ampliação: fiscalizar antes do fim do cronograma",
        "url": "https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html",
    },
    # NF-e
    "AJ-SINIEF-07-2005-cl3": {
        "norma": "Ajuste SINIEF 07/2005, cláusula terceira, incisos III e IV",
        "texto": "NF-e com chave de acesso e assinatura digital certificada pela ICP-Brasil",
        "url": "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2005/AJ_007_05",
    },
    "AJ-SINIEF-07-2005-cl4": {
        "norma": "Ajuste SINIEF 07/2005, cláusula quarta",
        "texto": "arquivo da NF-e só vale como documento fiscal após a Autorização de Uso",
        "url": "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2005/AJ_007_05",
    },
    "AJ-SINIEF-07-2005-cl12": {
        "norma": "Ajuste SINIEF 07/2005, cláusula décima segunda",
        "texto": "cancelamento em até 24 h da autorização; situação atual exige consulta à SEFAZ",
        "url": "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2005/AJ_007_05",
    },
    "MOC-NFE-4.00-chave": {
        "norma": "Manual de Orientação do Contribuinte (MOC) NF-e, leiaute 4.00: chave de acesso",
        "texto": "44 posições (cUF, AAMM, CNPJ/CPF, mod, série, nNF, tpEmis, cNF, cDV); DV módulo 11",
        "url": "https://www.nfe.fazenda.gov.br/portal/listaConteudo.aspx?tipoConteudo=ndIjl+iEFdE=",
    },
    "NT-2025.001-CNPJ-ALFANUMERICO": {
        "norma": "Nota Técnica Conjunta 2025.001 (CNPJ alfanumérico)",
        "texto": "caractere convertido por ASCII-48 no DV do CNPJ e da chave de acesso",
        "url": "https://blog.tecnospeed.com.br/novo-cnpj-nota-tecnica/",
    },
    # NT 2024.003: texto dos PDFs da v1.03 (fev/2025) e da v1.10 (mai/2026) conferido (leiaute
    # do grupo ZF, seção 4 "Regras de Validação", tabela 4.1 e cronograma). As duas versões têm ZF01 0-1 e
    # ZF04 1-1, a mesma tabela 4.1 e a mesma regra 10ZF04-20; a v1.10 torna UFGuia obrigatória.
    "NT-2024.003-ZF": {
        "norma": "Nota Técnica 2024.003 v1.03 (grupo ZF agropecuario/guiaTransito)",
        "texto": "uma guia por NF-e (ZF01 0-1, ZF04 1-1): tpGuia, UFGuia, serieGuia (C 1-9, opcional) e "
                 "nGuia (N 1-9); validação por UF e NCM",
        "url": "https://inventti.com.br/wp-content/uploads/2025/02/NT_2024.003-1.03.pdf",
    },
    "NT-2024.003-ZF05-10": {
        "norma": "Nota Técnica 2024.003 v1.10, regra ZF05-10 (rejeição 836) e tabela 4.1",
        "texto": "animal vivo sem Guia de Trânsito Animal (tpGuia 1, 2 ou 3) é rejeitado, salvo CFOPs "
                 "listados; ativa para NCM 0102 em BA, GO, MA e MT (tabela 4.1: 01/10/2025; regras de "
                 "validação da NT em produção desde 01/03/2026, cronograma da v1.10)",
        "url": "https://www.reformatributaria.com/wp-content/uploads/2026/05/"
               "NT_2024.003-Produtos-AGRO-NF-e-v-1.10_Rev.pdf",
    },
    "NT-2024.003-ZF04-20": {
        "norma": "Nota Técnica 2024.003 v1.03, regra de validação 10ZF04-20 (rejeição 838, facultativa por "
                 "UF)",
        "texto": "\"Guia de Trânsito já utilizada\": a SEFAZ confere a guia na base integrada com o órgão "
                 "sanitário emissor; o índice local de documentos reutilizados é o análogo do lado da IF",
        "url": "https://inventti.com.br/wp-content/uploads/2025/02/NT_2024.003-1.03.pdf",
    },
    "TEC-NCM-0102": {
        "norma": "NCM/TEC (Res. Gecex 272/2021 e alterações), posição 01.02",
        "texto": "animais vivos da espécie bovina: 0102.2x bovinos domésticos; 0102.3x búfalos",
        "url": "https://portalunico.siscomex.gov.br/classif/#/sumario?perfil=publico",
    },
    # GTA
    "IN-MAPA-09-2021-art3": {
        "norma": "IN MAPA 09/2021, art. 3º",
        "texto": "conteúdo mínimo da e-GTA: espécie, origem, destino, quantidade por sexo e faixa "
                 "etária, finalidade, emitente, datas de emissão e validade",
        "url": "https://www.in.gov.br/web/dou/-/instrucao-normativa-n-9-de-16-de-junho-de-2021-327689557",
    },
    "IN-MAPA-09-2021-art9": {
        "norma": "IN MAPA 09/2021, art. 9º",
        "texto": "GTA do OESA: símbolo do órgão, UF, numeração de seis dígitos e uma ou duas letras de série",
        "url": "https://www.in.gov.br/web/dou/-/instrucao-normativa-n-9-de-16-de-junho-de-2021-327689557",
    },
    "IN-MAPA-09-2021-art6": {
        "norma": "IN MAPA 09/2021, art. 6º",
        "texto": "baixa da GTA no destino e cancelamento pelo serviço oficial emissor",
        "url": "https://www.in.gov.br/web/dou/-/instrucao-normativa-n-9-de-16-de-junho-de-2021-327689557",
    },
    "MAPA-SDA-BOV-item01": {
        "norma": "Manual SDA de trânsito de bovinos e bubalinos v2.0, item 01 (bovídeos)",
        "texto": "uma espécie por GTA; quantidades por sexo e faixa etária; total por extenso no item 10",
        "url": "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos",
    },
    "MAPA-SDA-BOV-item11": {
        "norma": "Manual SDA de trânsito de bovinos e bubalinos v2.0, item 11 (procedência)",
        "texto": "CPF/CNPJ, nome, estabelecimento, código do estabelecimento, município (IBGE) e UF",
        "url": "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos",
    },
    "MAPA-SDA-BOV-item12": {
        "norma": "Manual SDA de trânsito de bovinos e bubalinos v2.0, item 12 (destino)",
        "texto": "CPF/CNPJ, nome, estabelecimento, código do estabelecimento, município (IBGE) e UF",
        "url": "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos",
    },
    "MAPA-SDA-BOV-item13": {
        "norma": "Manual SDA de trânsito de bovinos e bubalinos v2.0, item 13 (finalidade)",
        "texto": "uma finalidade por GTA (abate, engorda, reprodução, exposição, leilão, esporte, ...)",
        "url": "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos",
    },
    "MAPA-SDA-BOV-item20": {
        "norma": "Manual SDA de trânsito de bovinos e bubalinos v2.0, item 20 (emissão)",
        "texto": "local, data e hora de emissão; validade definida pelo emitente conforme o percurso",
        "url": "https://wikisda.agricultura.gov.br/pt-br/Saúde-Animal/trânsito_bovinos",
    },
    "GO-INC-ECONOMIA-AGRODEFESA-01-2021": {
        "norma": "IN Intersecretarial Economia/Agrodefesa 01/2021 (GO) e comunicado SEFAZ-GO de 28/03/2025",
        "texto": "e-GTA e NF integradas; desde 31/03/2025 a chave da NF-e é exigida no SIDAGO para "
                 "autorizar a GTA de bovinos e bubalinos (informada em até 24 h)",
        "url": "https://www.idealsoftwares.com.br/idealnews/noticia.php?id=30426",
    },
    "IN-AGRODEFESA-05-2013": {
        "norma": "IN Agrodefesa 05/2013 (GO), arts. 4º e 8º",
        "texto": "e-GTA com código de barras verificável no sítio da Agrodefesa; cancelamento da NF "
                 "vinculada antes da e-GTA",
        "url": "https://www.legisweb.com.br/legislacao/?id=253315",
    },
    # Políticas do agente (docs/arquitetura.md)
    "POL-06": {
        "norma": "Política POL-06 do Laudo Vivo",
        "texto": "texto de documento, OCR e narração é dado, nunca instrução",
        "url": "",
    },
    "POL-07": {
        "norma": "Política POL-07 do Laudo Vivo",
        "texto": "pedido de alterar valor sem nova evidência vira ocorrência de pressão",
        "url": "",
    },
}


def citar(regra_id: str) -> str:
    """Texto curto de citação de uma regra (para motivos e laudo)."""
    r = REGRAS.get(regra_id)
    return f"{r['norma']}: {r['texto']}" if r else regra_id


# ---------------------------------------------------------------------------
# NCM, posição 01.02 (animais vivos da espécie bovina)
# Fonte: Tabela NCM/TEC vigente (Res. Gecex 272/2021 e alterações), conferida nas
# consultas públicas que reproduzem a tabela (fazcomex, buscadorncm). A Seção I, capítulo 01, traz
# a posição 01.02; não há subitens novos para bovinos vivos desde a TEC 2022.
# ---------------------------------------------------------------------------

ClasseNCM = Literal["bovino_domestico", "bubalino", "outro_bovideo", "bovideo_desconhecido", "nao_bovideo_vivo"]

NCM_0102: dict[str, tuple[str, ClasseNCM]] = {
    "01022110": ("Bovinos domésticos reprodutores de raça pura, prenhes ou com cria ao pé", "bovino_domestico"),
    "01022190": ("Bovinos domésticos reprodutores de raça pura, outros", "bovino_domestico"),
    "01022911": ("Outros bovinos domésticos para reprodução, prenhes ou com cria ao pé", "bovino_domestico"),
    "01022919": ("Outros bovinos domésticos para reprodução, outros", "bovino_domestico"),
    "01022990": ("Outros bovinos domésticos, outros", "bovino_domestico"),
    "01023110": ("Búfalos reprodutores de raça pura, prenhes ou com cria ao pé", "bubalino"),
    "01023190": ("Búfalos reprodutores de raça pura, outros", "bubalino"),
    "01023911": ("Outros búfalos para reprodução, prenhes ou com cria ao pé", "bubalino"),
    "01023919": ("Outros búfalos para reprodução, outros", "bubalino"),
    "01023990": ("Outros búfalos, outros", "bubalino"),
    "01029000": ("Outros animais vivos da espécie bovina (ex.: bisões, iaques)", "outro_bovideo"),
}


def classificar_ncm(ncm: str | None) -> tuple[ClasseNCM, str]:
    """Classifica um NCM de 8 dígitos quanto a bovídeos vivos. Devolve (classe, descrição)."""
    n = "".join(ch for ch in (ncm or "") if ch.isdigit())
    if n in NCM_0102:
        desc, classe = NCM_0102[n]
        return classe, desc
    if n.startswith("01022"):
        return "bovino_domestico", "Bovinos domésticos (subitem não tabelado)"
    if n.startswith("01023"):
        return "bubalino", "Búfalos (subitem não tabelado)"
    if n.startswith("0102"):
        return "bovideo_desconhecido", "Posição 01.02 com subitem desconhecido (tabela antiga?)"
    return "nao_bovideo_vivo", "Fora da posição 01.02 (não é bovídeo vivo)"
