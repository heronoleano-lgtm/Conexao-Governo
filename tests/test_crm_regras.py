"""Regras do CRM que a primeira carga real expôs: duplicação nos alertas, unidades antigas, corte de paginação."""
from datetime import date

import pandas as pd
import pytest

from custodia import marts_crm, portal_api


def _sancoes():
    return pd.DataFrame([
        # o mesmo fornecedor com DUAS sanções vigentes ao mesmo tempo (CEIS e CNEP)
        {"cnpj": "88888888000188", "nome": "CONSTRUTORA Y", "inicio": "01/01/2026", "fim": "31/12/2027",
         "tipo": "Impedimento", "orgao": "X", "id": "1", "cadastro": "CEIS"},
        {"cnpj": "88888888000188", "nome": "CONSTRUTORA Y", "inicio": "01/03/2026", "fim": None,
         "tipo": "Multa", "orgao": "Y", "id": "2", "cadastro": "CNEP"},
        # ente com três registros vigentes
        *[{"cnpj": "11111111000101", "nome": "MUNICIPIO DE ALFA", "inicio": "01/01/2025", "fim": None,
           "tipo": f"T{i}", "orgao": "Z", "id": f"e{i}", "cadastro": "CEIS"} for i in range(3)],
        # entidade com dois registros no CEPIM
        *[{"cnpj": "55555555000155", "nome": "ASSOCIACAO X", "inicio": None, "fim": None, "tipo": f"C{i}",
           "orgao": "W", "id": f"c{i}", "cadastro": "CEPIM"} for i in range(2)],
    ])


def test_con01_pagamento_conta_uma_vez():
    """Mesmo pagamento nas duas fontes e coberto por duas sanções: R$ 100 mil, não R$ 400 mil."""
    fluxo = pd.DataFrame([{"doc_favorecido": "88888888000188", "favorecido": "CONSTRUTORA Y",
                           "cnpj_ente": "11111111000101", "nome_ente": "ALFA", "valor": 100_000.0,
                           "data": "2026-06-10", "id_agencia_conta": "c1", "proprio_ente": False}])
    pag = pd.DataFrame([{"doc_recebedor": "88888888000188", "nome_recebedor": "CONSTRUTORA Y",
                         "cnpj_ente": "11111111000101", "nome_ente": "ALFA", "valor": 100_000.0,
                         "data": "10/06/2026"},
                        # outro pagamento, só nesta fonte: conta
                        {"doc_recebedor": "88888888000188", "nome_recebedor": "CONSTRUTORA Y",
                         "cnpj_ente": "11111111000101", "nome_ente": "ALFA", "valor": 20_000.0,
                         "data": "2026-07-01"}])
    contas = pd.DataFrame([{"id_agencia_conta": "c1", "grupo_banco": "CAIXA"}])
    al = marts_crm.alertas_conformidade(_sancoes(), fluxo, pag, pd.DataFrame(), pd.DataFrame(), contas,
                                        date(2026, 11, 1))
    c1 = al[al["regra"] == "CON-01"]
    assert c1["valor"].sum() == pytest.approx(120_000)
    assert set(c1["banco_conta"].fillna("?")) == {"CAIXA", "?"}
    caixa = c1[c1["banco_conta"] == "CAIXA"].iloc[0]
    assert "CEIS" in caixa["cadastro"] and "CNEP" in caixa["cadastro"]


def test_con02_e_con03_uma_linha_por_cnpj():
    rec = pd.DataFrame([{"cnpj": "55555555000155", "nome": "ASSOCIACAO X", "mes": m, "valor": 50_000.0, "tipo": "E"}
                        for m in ("2026-09", "2026-10")])
    pot = pd.DataFrame([{"cnpj_ente": "11111111000101", "nome_ente": "ALFA"}] * 2)   # lista com linha repetida
    al = marts_crm.alertas_conformidade(_sancoes(), pd.DataFrame(), pd.DataFrame(), rec, pot, pd.DataFrame(),
                                        date(2026, 11, 1))
    c2, c3 = al[al["regra"] == "CON-02"], al[al["regra"] == "CON-03"]
    assert len(c2) == 1 and c2["valor"].iloc[0] == pytest.approx(100_000)    # não 200 mil (2 registros)
    assert len(c3) == 1 and "3 registro(s) vigente(s)" in c3["detalhe"].iloc[0]


def test_unidades_antigas_sem_tipo_sao_ignoradas(tmp_path):
    bruto = tmp_path
    linha = {"anoMes": 202610, "codigoPessoa": "11.111.111/0001-01", "nomePessoa": "ALFA", "valor": 10.0,
             "codigoOrgaoSuperior": "1", "codigoOrgao": "2", "codigoUG": "3", "nomeOrgaoSuperior": "Fazenda",
             "nomeOrgao": "STN", "nomeUG": "STN", "siglaUFPessoa": "MG", "tipoPessoa": "Administração Pública Municipal"}
    repo = portal_api.Repositorio(bruto, "recursos")
    base = {"mesAnoInicio": "10/2026", "mesAnoFim": "10/2026", "uf": "MG"}
    repo.gravar(base, pd.DataFrame([linha]), True, date(2026, 11, 1), 1)                       # fila antiga
    repo.gravar({**base, "tipoFavorecido": "Administração Pública Municipal"}, pd.DataFrame([linha]), True,
                date(2026, 11, 2), 1)
    c = marts_crm.consolidar(bruto)
    assert len(c["crm_recebido"]) == 1 and c["crm_recebido"]["valor"].sum() == pytest.approx(10)
    q = c["crm_qualidade"].set_index("conjunto").loc["recursos"]
    assert q["linhas_unidades_legadas"] == 1 and q["chaves_conflitantes"] == 0
    # arquivo da consulta antiga apagado: não é perda (não entra nas somas nem é pedida de novo)
    from custodia import storage
    storage.caminho(repo.pasta, portal_api._id("recursos", base)).unlink()
    integ = portal_api.integridade(bruto).set_index("conjunto").loc["recursos"]
    assert integ["sem_arquivo"] == 0 and integ["obsoletas"] == 1


def test_paginacao_cortada_marca_falha_e_nao_grava():
    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None, **kw):
            class R:
                status_code = 200
                content = b'[{"a": 1}]'
                headers = {}

                def json(self):
                    return [{"a": 1}]

                def raise_for_status(self):
                    pass
            return R()
    cli = portal_api.ClientePortal("k", "t", sessao=Sess(), limitador=portal_api.Limitador(intervalo=0))
    with pytest.raises(portal_api.ErroIncompleto):
        cli.paginas("/x", {}, max_paginas=3)
    assert cli.chamadas == 3


def test_poda_do_bruto_nao_apaga_cache_do_portal_e_cache_se_recupera(tmp_path):
    """A poda diária mantinha 30 arquivos por pasta e apagava unidades do Portal (1ª carga real: presença 30/5.571)."""
    from custodia import ingest_api, storage
    repo = portal_api.Repositorio(tmp_path, "presenca")
    for k in range(40):
        repo.gravar({"mesAno": "202609", "codigoIbge": str(3100000 + k)}, pd.DataFrame([{"valor": 1.0}]), True,
                    date(2026, 11, 1), 1)
    foto = tmp_path / "especiais" / "planos"          # fotos diárias continuam podadas
    for k in range(5):
        storage.gravar(pd.DataFrame([{"a": k}]), foto / f"2026-10-0{k + 1}")
    ingest_api.limpar_bruto(tmp_path, 2)
    assert len(portal_api.ler_conjunto(tmp_path, "presenca")) == 40
    assert len(list(foto.iterdir())) == 2
    # arquivo apagado por fora: a integridade acusa e a fila baixa de novo
    alvo = {"mesAno": "202609", "codigoIbge": "3100000"}
    storage.caminho(repo.pasta, portal_api._id("presenca", alvo)).unlink()
    integ = portal_api.integridade(tmp_path).set_index("conjunto")
    assert integ.loc["presenca", "sem_arquivo"] == 1
    assert portal_api.Repositorio(tmp_path, "presenca").precisa(alvo, True, 3650, date(2026, 11, 2))


def test_carteira_com_recebido_negativo_nao_gera_percentual_absurdo():
    rec = pd.DataFrame([{"cnpj": "11111111000101", "nome": "A", "mes": "2026-10", "valor": -500.0, "uf": "MG",
                         "municipio": "A", "orgao_superior": "Ministério da Saúde", "orgao": "FNS", "tipo": "M",
                         "tipo_consulta": "M"}])
    fns = pd.DataFrame([{"fonte": "FNS", "grupo_banco": "CAIXA", "ano": 2026, "mes": 10, "cnpj": "11111111000101",
                         "valor": 600_000.0}])
    c = marts_crm.carteira(rec, fns, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), date(2026, 11, 1))
    r = c.iloc[0]
    assert pd.isna(r["pct_banco_conhecido"]) and not r["conhecido_excede"]


def test_rede_80_20_e_nomes_no_lugar_de_cnpj():
    from custodia import consultas as q
    rd = pd.DataFrame({"origem_tipo": "ente", "destino_tipo": "fornecedor", "origem": "MUNICIPIO A",
                       "origem_id": "11111111000101", "destino": ["12345678000190", "LOJA B", None, "D"],
                       "destino_id": ["12345678000190", "22222222000102", "33333333000103", "44444444000104"],
                       "valor": [60.0, 25.0, 10.0, 5.0], "fonte": "x"})
    d = {"crm_rede": rd, "mart_fornecedores": pd.DataFrame({"doc_favorecido": ["12345678000190"],
                                                            "favorecido": ["CONSTRUTORA ALFA"]})}
    leg = q.rede_legivel(d)
    assert list(leg["destino"]) == ["CONSTRUTORA ALFA", "LOJA B", "CNPJ 33.333.333/0001-03", "D"]
    principais, resumo = q.pareto(leg, 0.8)
    assert list(principais["destino"]) == ["CONSTRUTORA ALFA", "LOJA B"]          # 60 + 25 ≥ 80% de 100
    r = resumo.iloc[0]
    assert r["relacoes_no_corte"] == 2 and r["pct_valor_no_corte"] == pytest.approx(0.85)
    assert r["pct_relacoes_no_corte"] == pytest.approx(0.5)
