"""`scripts/checar_pii.py`: marcadores falsos passam, dado com forma real é apontado, e `eval/`, `bench/` e
`tests/contract/` estão limpos (regra do AGENTS.md: nada de CPF, nome ou telefone reais nessas pastas).

Todo valor com forma real usado aqui é montado em tempo de execução: nada de documento, telefone, e-mail ou
nome real fica literal neste arquivo (que também é varrido)."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("checar_pii", REPO / "scripts" / "checar_pii.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["checar_pii"] = P
_spec.loader.exec_module(P)


def _cpf_com_dv(base9: str) -> str:
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append(sum(d[i] * (n + 1 - i) for i in range(n)) * 10 % 11 % 10)
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def _so_digitos(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def _tipos(texto: str, arquivo: str | None = None) -> list[str]:
    return [t for t, _ in P.achados_na_linha(texto, arquivo=arquivo)]


@pytest.mark.parametrize("texto", [
    "CPF 000.000.001-91 do produtor teste",
    "cnpj 99.999.999/0001-91",
    "telefone (62) 99999-0000",
    "fone 62 3333-0000",
    "formatos: (62) 99999-9999 · +55 62 99999-9999 · 62 3333-4444",
    "produtor.teste@example.com e fulano@laudo.test",
    "contato x@y.invalid, --contato \"<seu e-mail>\"",
    "rulebook-mcr-2-7@0.1.0 e contador@0.2.0",
    "chave 52260799999999502456550010000075101195312624",
    "empreendimento: '23271300078002'",
    "sha 3e55df35d1927e2802c22a37dcbda1e38ccc73a2ee70388376dea399f977282b",
    "meu nome é Fulano Sintético da Silva",
    "a Sra. Beltrana de Tal e o produtor Ciclano Pereira",
    "<xNome>PRODUTOR TESTE 01</xNome>",
    "<xNome>NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL</xNome>",
    '"nome": "AGROPECUARIA VENDEDORA TESTE 03",',
    "<tr><th>Nome</th><td>PRODUTOR TESTE 21</td></tr>",
    "Pequeno Produtor Rural",
])
def test_marcadores_falsos_e_codigos_publicos_passam(texto):
    assert _tipos(texto) == [], texto


def test_documentos_do_gerador_sintetico_passam():
    """Tudo o que `laudo.docs_fiscais.sintetico` gera é marcador (formatado ou não)."""
    from laudo.docs_fiscais.sintetico import cnpj_sintetico, cpf_sintetico

    for n in range(1, 1000, 7):  # n=0 daria CPF de zeros, que nem tem DV válido
        cpf, cnpj = cpf_sintetico(n), cnpj_sintetico(n)
        assert P.dv_cpf_ok(cpf) and P.dv_cnpj_ok(cnpj)  # têm DV válido: só passam por serem marcadores
        fmt_cpf = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        fmt_cnpj = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
        assert _tipos(f"cpf {cpf} {fmt_cpf} cnpj {cnpj} {fmt_cnpj}") == [], (cpf, cnpj)


def test_dado_com_forma_real_e_apontado():
    cpf = _cpf_com_dv("123456789")  # montado em tempo de execução: o arquivo não guarda o número
    assert "CPF" in _tipos(f"o cpf é {cpf}")
    assert "CPF (sem formatação)" in _tipos("doc " + cpf.replace(".", "").replace("-", ""))
    assert "telefone" in _tipos("liga no (62) 9" + "8123-4567")
    assert "e-mail" in _tipos("manda para alguem@" + "provedor.com.br")


def test_cpf_valido_inventado_na_hora_e_apontado_em_toda_forma():
    """CPF válido sorteado agora (fora da faixa 000.000) é acusado formatado, cru, ditado e pelo `main`."""
    rng = random.Random(20261008)
    for _ in range(50):
        base = "".join(str(rng.randrange(10)) for _ in range(9))
        if base.startswith("000000") or len(set(base)) == 1:
            continue
        cpf = _cpf_com_dv(base)
        cru = _so_digitos(cpf)
        assert P.dv_cpf_ok(cru)
        assert "CPF" in _tipos(f"produtor com cpf {cpf}")
        assert "CPF (sem formatação)" in _tipos(f"documento {cru}")
        assert "CPF (ditado)" in _tipos(f"o CPF é {cru[:3]} {cru[3:6]} {cru[6:9]} {cru[9:]}")
        # a lista de permissões é por valor: estar num arquivo com permissão não libera outro CPF
        for perm in P.PERMITIDOS:
            assert "CPF" in _tipos(f"cpf {cpf}", arquivo=perm.arquivos[0])


def test_cpf_inventado_em_arquivo_faz_o_main_falhar(tmp_path, capsys):
    cpf = _cpf_com_dv("528193746")
    arq = tmp_path / "vazamento.py"
    arq.write_text(f'PRODUTOR = {{"cpf": "{cpf}"}}\n', encoding="utf-8")
    assert P.main([str(arq)]) == 1
    saida = capsys.readouterr().out
    assert "CPF" in saida and cpf not in saida  # acusa sem repetir o dado


def test_telefone_quase_marcador_e_apontado():
    assert "telefone" in _tipos("liga (62) 99999-999" + "8")  # blocos não são todos de um dígito
    assert "telefone" in _tipos("liga 62 3333-444" + "5")
    assert "telefone" in _tipos("liga (62) 9" + "9999-1000")


def test_nome_apos_gatilho_e_apontado():
    nome = "Tobias" + " Wanderley" + " Quintela"  # montado aqui; o arquivo não guarda um nome após gatilho
    for texto in (f"meu nome é {nome}", f"me chamo {nome}", f"o produtor {nome} ligou", f"Sra. {nome}",
                  f"nome do produtor é {nome}", f'"nome": "{nome}"', f"nome_produtor: {nome}",
                  f"<xNome>{nome.upper()}</xNome>", f"<th>Nome</th><td>{nome.upper()}</td>"):
        assert "nome" in _tipos(texto), texto
    trechos = [t for _, t in P.achados_na_linha(f"meu nome é {nome}")]
    assert trechos and all(nome not in t for t in trechos)


def test_relatorio_nao_repete_o_dado():
    cpf = _cpf_com_dv("987654321")
    trechos = [t for _, t in P.achados_na_linha(f"cpf {cpf}")]
    assert trechos and all(cpf not in t for t in trechos)


def test_lista_de_permissoes_e_auditavel():
    assert P.PERMITIDOS, "sem entradas, este teste perde o sentido: remova-o junto"
    for perm in P.PERMITIDOS:
        assert len(perm.motivo) >= 30, perm  # motivo com a fonte, não só um rótulo
        assert perm.arquivos, perm
        for arq in perm.arquivos:
            assert "\\" not in arq and not arq.startswith("/"), arq  # relativo à raiz, com "/"
            assert (REPO / arq).is_file(), f"entrada aponta para arquivo que não existe: {arq}"
        # a entrada só existe porque o valor é acusado sem ela
        assert _tipos(f"valor {perm.valor}"), perm


def test_valor_permitido_so_passa_nos_arquivos_listados(tmp_path):
    for perm in P.PERMITIDOS:
        texto = f"exemplo {perm.valor}"
        for arq in perm.arquivos:
            assert _tipos(texto, arquivo=arq) == [], arq
        for outro in ("eval/golden/casos/GLD-0001/caso.yaml", "bench/fiscal_go/README.md", "tests/unit/outro.py",
                      "src/" + perm.arquivos[0]):
            assert _tipos(texto, arquivo=outro), outro
        vaza = tmp_path / Path(perm.arquivos[0]).name  # mesmo nome de arquivo, outro caminho: continua acusado
        vaza.write_text(texto + "\n", encoding="utf-8")
        assert P.main([str(vaza)]) == 1


def test_eval_bench_e_contratos_sem_pii():
    alvos = [str(REPO / "eval"), str(REPO / "bench"), str(REPO / "tests" / "contract")]
    assert P.main(alvos) == 0
