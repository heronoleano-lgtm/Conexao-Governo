"""O motor de auditoria profunda tem de acertar onde a resposta é conhecida."""
import numpy as np
import pandas as pd

from custodia import auditoria_profunda as apf


def test_benford_reconhece_dado_conforme_e_nao_conforme():
    r = np.random.default_rng(1)
    conforme = pd.Series(10 ** r.uniform(1, 7, 20000))          # log-uniforme segue Benford
    assert apf.benford(conforme)["mad"] < 0.006
    redondos = pd.Series(r.choice([100000, 200000, 250000, 500000], 5000).astype(float))
    b = apf.benford(redondos)
    assert b["mad"] > 0.015 and b["classe"] == "não conforme"
    assert apf.benford(pd.Series([1.0] * 10))["mad"] is None   # amostra pequena não é julgada


def test_conferencia_independente_pega_saldo_contado_em_dobro():
    instr = pd.DataFrame({"modulo": "Fundo a Fundo", "cnpj_ente": ["a", "b"], "uf": "MG", "grupo_banco": ["BB", "CAIXA"],
                          "valor": [100.0, 300.0]})
    contas = pd.DataFrame({"modulo": "Fundo a Fundo", "id_agencia_conta": ["1-1", "1-1", "2-2"], "cnpj_ente": ["a", "a", "b"],
                           "grupo_banco": ["BB", "BB", "CAIXA"], "saldo": [50.0, 50.0, 10.0]})
    perm = pd.DataFrame({"saldo": [100.0, 10.0]})                 # tabela que somou a conta repetida
    out = apf.conferencia_independente({"fato_instrumento": instr, "fato_conta": contas, "mart_permanencia": perm})
    st = {r["checagem"]: r["status"] for r in out}
    assert st["participação CAIXA total"] == apf.OK
    assert st["saldo total, uma vez por conta"] == apf.OK
    assert st["saldo somando linhas = saldo uma vez por conta"] == apf.CRITICO
    assert st["mart_permanencia: Σ saldo = contas distintas"] == apf.CRITICO


def test_rede_neural_acha_anomalias_plantadas_e_e_estavel():
    r = np.random.default_rng(7)
    n = 1500
    valor = 10 ** r.uniform(5, 8, n)
    er = pd.DataFrame({"cnpj_ente": [f"{i:014d}" for i in range(n)], "nome_ente": "E", "uf": "MG", "valor": valor,
                       "valor_caixa": valor * r.uniform(0, 1, n), "valor_concorrente": valor * 0.3,
                       "saldo_caixa": valor * r.uniform(0, 0.1, n), "saldo_concorrente": valor * r.uniform(0, 0.1, n),
                       "a_creditar": valor * r.uniform(0, 0.2, n), "potencial_custodia": valor * r.uniform(0, 0.1, n),
                       "pagamentos_fora_caixa": valor * r.uniform(0, 0.3, n), "transf_secundaria": 0.0,
                       "populacao": 10 ** r.uniform(3, 6, n)})
    er.loc[:9, "saldo_concorrente"] = er.loc[:9, "valor"] * 80          # 10 entes impossíveis
    an, linhas = apf.anomalias_entes(er, sementes=(0, 1, 2), topo=0.02, epocas=40)
    achados = set(an["cnpj_ente"])
    assert len(achados & set(er.loc[:9, "cnpj_ente"])) >= 9           # a rede encontra os plantados
    st = {x["checagem"]: x for x in linhas}
    assert st["validação com anomalias plantadas (recall no topo 2%)"]["status"] == apf.OK
    # o resto do topo é ruído aleatório (dado sintético): a estabilidade que importa é a dos plantados
    for semente in (3, 4):
        an2, _ = apf.anomalias_entes(er, sementes=(semente,), topo=0.02, epocas=40, validar=False)
        assert len(set(an2["cnpj_ente"]) & set(er.loc[:9, "cnpj_ente"])) >= 9
    assert an["explicacao"].str.contains("saldo_concorrente").head(10).mean() >= 0.8


def test_duplicidade_usa_identificador_quando_existe():
    p = pd.DataFrame({"modulo": "Fundo a Fundo", "id_pagamento": ["1", "2", "2"], "cnpj_ente": "a", "doc_recebedor": "x",
                      "valor": 10.0, "data": "2026-01-01"})
    out = apf.duplicidades({"fato_pagamento": p})
    assert out[0]["checagem"] == "identificador do pagamento único" and out[0]["status"] == apf.CRITICO
