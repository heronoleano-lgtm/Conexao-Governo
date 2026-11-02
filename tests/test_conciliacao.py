"""Erros que a conciliação entre equipes independentes e o painel encontrou em 01/11/2026 (dados reais)."""
from datetime import date

import pandas as pd
import pytest

from custodia import marts, motores_gestor as mg
from custodia.normaliza import conta_valida


def test_classificacao_dos_lancamentos():
    desc = pd.Series(["APL AUTOM", "APL FUNDO", "AP CDB FLX", "BB-APLIC C.PRZ-APL.AUT", "Aplicao em BB Fix",
                      "Estorno Resgate Automtico", "Emissão de Ordem Bancária", "Emisso de Ordem Bancria",
                      "DOC/TED INTERNET", "Impostos", "PAG GPS", "ENVIO TED", "Transmissão", "TED", "PAGTO X"])
    docs = pd.Series([""] * 14 + ["00394460000141"])
    t = list(marts.tipo_movimento(desc, docs))
    assert t[:6] == ["aplicação/resgate"] * 6                       # "APL AUTOM" e "APL FUNDO" eram pagamento
    assert t[6:8] == ["pagamento/transferência"] * 2                # "emISSão" de OB era tributo
    assert t[8:11] == ["tributos/tarifas"] * 3
    assert t[11:14] == ["pagamento/transferência"] * 3
    assert t[14] == "devolução"                                     # GRU ao Tesouro


def test_conta_sem_numero_nao_identifica_conta():
    assert list(conta_valida(pd.Series(["3351-0", "3351-", "0095-576017788", None, "1-1"]))) == \
        [False, False, True, False, True]


def test_a_receber_separa_firme_de_previsto():
    pipe = pd.DataFrame({"modulo": "Especiais", "id_instrumento": ["1", "2"], "cnpj_ente": ["a", "b"],
                         "nome_ente": ["A", "B"], "uf": "MG", "grupo_banco": "CAIXA", "area": None,
                         "etapa": [marts.ETAPA_EMPENHO, marts.ETAPA_MINUTA], "a_creditar": [100.0, 0.0],
                         "valor_minuta": [0.0, 300.0], "data_empenho": ["2026-10-01", "2026-10-20"],
                         "data_ob": [None, None], "dias_ate_pagamento": [None, None]})
    instr = pd.DataFrame({"modulo": "Discricionárias", "id_instrumento": ["c1", "c2"], "cnpj_ente": ["a", "b"],
                          "nome_ente": ["A", "B"], "uf": "MG", "grupo_banco": "CAIXA", "area": None,
                          "valor": [1000.0, 900.0], "desembolsado": [0.0, 0.0], "ativo": True,
                          "fim_vigencia": "2027-12-31", "data_referencia": ["2025-03-10", None]})
    r = mg.a_receber(pipe, instr, date(2026, 11, 1))
    firme = r[r["firme"]]
    assert firme["valor_a_receber"].sum() == pytest.approx(1100)          # empenho 100 + convênio assinado 1000
    prev = r[~r["firme"]]
    assert prev["valor_a_receber"].sum() == pytest.approx(1200)           # minuta 300 + proposta sem assinatura 900
    assert set(prev["regra"]) == {"REC-04"} and (prev["faixa_prazo"] == mg.FAIXA_PREVISTO).all()


def test_permanencia_mede_banco_parado_e_conta_sem_saida():
    contas = pd.DataFrame({"modulo": "Especiais", "cnpj_ente": ["a", "b", "c"], "nome_ente": ["A", "B", "C"],
                           "uf": "MG", "grupo_banco": ["CAIXA", "BB", "BB"], "id_agencia_conta": ["1-1", "2-2", "3-3"],
                           "saldo": [365.0, 730.0, 500.0]})
    fluxo = pd.DataFrame({"modulo": "Especiais", "cnpj_ente": ["a", "b"], "grupo_origem": ["CAIXA", "BB"],
                          "tipo_movimento": "pagamento/transferência", "valor": [365.0, 365.0],
                          "data": ["2025-05-30", "2026-10-30"]})
    p = mg.permanencia(contas, fluxo, {}, {("Especiais", "CAIXA")}).set_index("cnpj_ente")
    assert p.at["a", "dias_permanencia"] == pytest.approx(365) and "parou" in p.at["a", "base_permanencia"]
    assert p.at["b", "dias_permanencia"] == pytest.approx(730)
    assert p.at["c", "base_permanencia"] == mg.MEDIDO_PARADO           # sem saída em 12 meses = parado
    bb = p[p["grupo_banco"] == "BB"].reset_index()
    assert mg.giro_dias(bb) == pytest.approx(365 * 1230 / 365)         # estoque ÷ fluxo, não média ponderada


def test_retencao_no_proprio_banco():
    from custodia import analise_fluxo as af
    fl = pd.DataFrame({"modulo": "Especiais", "grupo_origem": ["CAIXA", "CAIXA", "BB", "BB"],
                       "grupo_destino": ["CAIXA", "BB", "BB", "CAIXA"], "tipo_movimento": "pagamento/transferência",
                       "proprio_ente": False, "valor": [20.0, 80.0, 60.0, 40.0],
                       "data": ["2025-05-01", "2025-05-02", "2025-05-01", "2025-05-02"],
                       "cnpj_ente": "x", "id_agencia_conta": "1-1", "uf": "MG"})
    de = af.destino({"fato_fluxo": fl}, (None, None, None, ()))
    cp = de["comparavel"].set_index("grupo_origem")
    assert cp.at["CAIXA", "pct_fica_no_banco"] == pytest.approx(.2)
    assert cp.at["BB", "pct_fica_no_banco"] == pytest.approx(.6)
    assert any("Retenção no próprio banco" in f for f in af.leitura_destino(de, str, lambda v: f"{v:.0%}"))


def test_concentracao_nao_trata_saldo_sem_ente_como_ente():
    contas = pd.DataFrame({"modulo": "Especiais", "grupo_banco": "CAIXA", "cnpj_ente": ["a", None, "b"],
                           "nome_ente": ["A", None, "B"], "uf": "MG", "saldo": [50.0, 30.0, 20.0]})
    c = mg.concentracao(contas)
    assert list(c["cnpj_ente"]) == ["a", "b"]                         # sem ente fica fora do ranking…
    assert c["pct_do_saldo"].tolist() == pytest.approx([.5, .2])      # …mas continua no denominador


def test_estimativa_do_que_o_banco_parado_nao_publicou():
    from custodia import analise_fluxo as af
    datas = pd.date_range("2024-06-01", "2025-05-01", freq="MS").strftime("%Y-%m-%d").tolist()
    fl = pd.DataFrame({"modulo": "Especiais", "grupo_origem": "CAIXA", "grupo_destino": "BB",
                       "tipo_movimento": "pagamento/transferência", "proprio_ente": False, "valor": 100.0,
                       "data": datas, "cnpj_ente": "x", "id_agencia_conta": "1-1", "uf": "MG"})
    aplic = fl.assign(tipo_movimento="aplicação/resgate", valor=10_000.0)   # aplicação não é saída efetiva
    de = af.destino({"fato_fluxo": pd.concat([fl, aplic]), "meta": {"dia": "2026-11-01"}}, (None, None, None, ()))
    r = de["nao_publicado"].iloc[0]
    assert r["saidas_mes_antes"] == pytest.approx(100)
    assert r["estimativa_nao_publicada"] == pytest.approx(100 * r["meses_sem_extrato"], rel=.01)


# ---------------------------------------------------------------- red team de veracidade (02/11)
def test_lancamento_isolado_nao_reabre_banco_parado():
    """C-05: um único lançamento depois da parada não pode apagar o alerta nem mover a janela."""
    meses = pd.date_range("2024-01-15", "2025-05-15", freq="MS")
    normal = pd.DataFrame([{"modulo": "Especiais", "grupo_origem": "CAIXA", "data": d.strftime("%Y-%m-%d"),
                            "tipo_movimento": "pagamento/transferência", "valor": 1.0, "cnpj_ente": "a"}
                           for d in meses for _ in range(50)])
    canario = normal.head(1).assign(data="2026-09-15")
    contas = pd.DataFrame({"modulo": "Especiais", "grupo_banco": ["CAIXA"], "saldo": [100.0], "data_saldo": ["2025-04-30"],
                           "id_agencia_conta": ["1-1"], "cnpj_ente": ["a"]})
    assert ("Especiais", "CAIXA") in mg.fontes_interrompidas(pd.concat([normal, canario]), contas, date(2026, 11, 1))
    from custodia import normaliza
    ult = normaliza.ultimo_extrato_efetivo(pd.concat([normal, canario]))
    assert ult[("Especiais", "CAIXA")] < pd.Timestamp("2025-06-01")


def test_so_o_contratado_entra_nos_valores():
    """C-04: anulado, cancelado, rescindido e rejeitado = cancelado; impedido à parte; proposta e elaboração = previsto."""
    i = pd.DataFrame({"modulo": ["Discricionárias"] * 4 + ["Especiais"] * 3 + ["Fundo a Fundo"] * 2,
                      "situacao": ["Em execução", "Convênio Anulado", "Proposta/Plano de Trabalho Aprovado", "Cancelado",
                                   "CIENTE", "IMPEDIDO", "AGUARDANDO_CIENCIA", "AUTORIZADO", "EM_ELABORACAO"],
                      "data_referencia": ["2024-01-01", "2023-01-01", None, "2022-01-01", "x", "x", "x", "x", "x"]})
    assert list(marts.etapa_instrumento(i)) == ["contratado", "cancelado", "previsto", "cancelado", "contratado",
                                                "impedido", "previsto", "contratado", "previsto"]


def test_fpm_sem_banco_publicado():
    """C-03: o Tesouro não publica o banco do FPM; o painel não pode afirmar 'BB'."""
    from pathlib import Path
    src = Path(marts.__file__).with_name("marts_outras.py").read_text("utf-8")
    assert '"FPE"]), "BB"' not in src
