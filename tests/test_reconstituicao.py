"""Regra SAL-01: saldo estimado ao lado do publicado onde o extrato parou."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from custodia import reconstituicao as rc


def _cenario(n=240, seed=1):
    """BB publica tudo; CAIXA parou em 2025-05; BNB nunca publicou. Cada conta recebe 1 crédito e gasta 10%/mês."""
    rng = np.random.default_rng(seed)
    contas, cred, fluxo = [], [], []
    meses = pd.period_range("2022-01", "2026-10", freq="M")
    for i in range(n):
        b = "BB" if i % 3 == 0 else "CAIXA" if i % 3 == 1 else ("BNB" if i % 30 == 2 else "CAIXA")
        k = f"{i}-{570000000 + i}"
        m0 = int(rng.integers(0, len(meses) - 4))
        c0 = float(rng.integers(100_000, 1_000_000))
        cred.append({"modulo": "Especiais", "id_instrumento": str(i), "id_agencia_conta": k, "grupo_banco": b,
                     "cnpj_ente": f"{i:014d}", "data": meses[m0].to_timestamp().strftime("%Y-%m-10"), "valor": c0})
        s = 0.0
        ult_pub = None
        for j in range(m0, len(meses)):
            s = s * 1.008 + (c0 if j == m0 else 0)
            saida = 0.10 * s
            s -= saida
            dia = meses[j].to_timestamp()
            publica = b == "BB" or (b == "CAIXA" and dia < pd.Timestamp("2025-06-01"))
            if publica:
                fluxo.append({"modulo": "Especiais", "id_agencia_conta": k, "grupo_origem": b,
                              "tipo_movimento": "pagamento/transferência", "valor": saida,
                              "data": dia.strftime("%Y-%m-20"), "cnpj_ente": f"{i:014d}"})
                ult_pub = (s, (dia + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"))
        saldo, data = (ult_pub if ult_pub and b != "BNB" else (np.nan, None))
        contas.append({"modulo": "Especiais", "id_instrumento": str(i), "grupo_banco": b, "id_agencia_conta": k,
                       "origem": "plano de ação", "saldo": saldo, "data_saldo": data, "cnpj_ente": f"{i:014d}"})
    return pd.DataFrame(contas), pd.DataFrame(cred), pd.DataFrame(fluxo)


def test_reconstituicao_mantem_publicado_e_estima_so_onde_parou():
    contas, cred, fluxo = _cenario()
    r = rc.reconstituir(contas, cred, fluxo, date(2026, 11, 1), {("Especiais", "CAIXA")})
    c = r["contas"].set_index("id_agencia_conta")
    bb = c[c["grupo_banco"] == "BB"]
    assert (bb["base_saldo"] == rc.BASE_PUBLICADO).all()
    assert np.allclose(bb["saldo_estimado"], bb["saldo_publicado"])           # banco que publica: nada inventado
    cx = c[c["grupo_banco"] == "CAIXA"]
    assert cx["base_saldo"].isin([rc.BASE_PARADO_ANCORA, rc.BASE_PARADO_NOVA]).all()
    assert (cx["saldo_est_min"] <= cx["saldo_estimado"] + 1e-6).all() and \
        (cx["saldo_estimado"] <= cx["saldo_est_max"] + 1e-6).all()
    novas = cx[cx["base_saldo"] == rc.BASE_PARADO_NOVA]
    assert len(novas) and (novas["saldo_estimado"] > 0).all()                 # contas creditadas depois da parada
    bnb = c[c["grupo_banco"] == "BNB"]
    assert (bnb["base_saldo"] == rc.BASE_NUNCA).all()                          # débito zero não é "não gastou"
    q = r["qualidade"]
    assert q["teste"].str.startswith("Calibração").any() and q["teste"].str.startswith("Teto medido").any()


def test_estimativa_acerta_a_ordem_de_grandeza_no_cenario_sintetico():
    contas, cred, fluxo = _cenario(n=600, seed=7)
    r = rc.reconstituir(contas, cred, fluxo, date(2026, 11, 1), {("Especiais", "CAIXA")})
    c = r["contas"]
    cal = r["qualidade"].set_index("teste").loc["Calibração do rendimento (bancos que publicam)"]
    assert abs(cal["erro_total"]) < .05                                         # calibra o rendimento sintético
    teto = r["qualidade"][r["qualidade"]["teste"].str.startswith("Teto")]["soma_reconstituida"].iloc[0]
    cx = c[c["grupo_banco"] == "CAIXA"]
    assert 0 < cx["saldo_estimado"].sum() < teto                                # abaixo do teto medido


def test_aplicar_nao_mexe_no_saldo_publicado():
    contas, cred, fluxo = _cenario()
    r = rc.reconstituir(contas, cred, fluxo, date(2026, 11, 1), {("Especiais", "CAIXA")})
    fc = rc.aplicar(contas, r["contas"])
    assert fc["saldo"].equals(contas["saldo"])
    assert {"saldo_estimado", "saldo_est_min", "saldo_est_max", "base_saldo", "extrato_parado_em"} <= set(fc.columns)
