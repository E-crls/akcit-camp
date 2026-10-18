"""Documentos fiscais do Laudo Vivo: NF-e (layout 4.00) e GTA, com conciliação contra o item financiado.

Módulos:
- `comum`: identificadores (CPF/CNPJ, inclusive CNPJ alfanumérico), chave de acesso, critérios e status.
- `fontes`: regras citáveis (regra_id -> norma) e tabela NCM do capítulo 01.02.
- `cripto`: DER/X.509 mínimo e RSA PKCS#1 v1.5 em Python puro (sem dependência externa).
- `xmldsig`: C14N, DigestValue e verificação/assinatura XMLDSig enveloped.
- `nfe`: leitura e conciliação da NF-e (inclui o grupo ZF agropecuario/guiaTransito, NT 2024.003).
- `gta`: modelo, conciliação (inclui GTA × grupo ZF da NF-e) e renderização (HTML/PDF) da GTA.
- `indice`: índice local de GTA e chave de NF-e de laudos selados, por operação, só com HMAC (análogo da
  rejeição 838/ZF04-20).
- `sintetico`: construtores de documentos sintéticos (golden set, testes e demo).

Versão 0.2.0: inclui o critério `gta.nfe_guia` (só quando a NF-e traz o grupo ZF; ausência é
neutra; uma guia por NF-e, NT 2024.003 v1.03; nunca divergente sozinho) e a consulta ao índice de reuso
(`gta.reuso`, `nfe.reuso`, por operação, só quando o chamador liga o índice; o registro é da selagem).
"""

VERSAO = "0.2.0"
FONTE_VERSAO = f"docs_fiscais@{VERSAO}"
