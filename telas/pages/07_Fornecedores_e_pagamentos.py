import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.semantica import cor_banco  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, ranking, rosca, secao, tabela  # noqa: E402
from custodia.ui import AUREA_INV  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Fornecedores e pagamentos",
             "Quem recebe o dinheiro no fim e em que banco. Empresas que recebem muito e não têm conta na CAIXA são "
             "público para domicílio de recebimento, crédito e folha. Pessoas físicas não são listadas.")
d = ctx.d
fo = d["mart_fornecedores"].copy()
de = d["mart_destino_ente"].copy()
if ctx.ufs and not de.empty:
    de = de[de["uf"].isin(ctx.ufs)]

com_banco = fo[fo["banco_principal"].notna() & (fo["banco_principal"] != "(sem banco)")] if not fo.empty else fo
fora = com_banco[com_banco["banco_principal"] != "CAIXA"] if not com_banco.empty else com_banco
cartoes([
    {"rotulo": "Recebedores (empresas e órgãos)", "valor": f"{len(fo):,}".replace(",", ".")},
    {"rotulo": "Recebido por eles", "valor": q.brl(fo["valor_recebido"].sum() if not fo.empty else 0)},
    {"rotulo": "Recebem principalmente fora da CAIXA", "valor": f"{len(fora):,}".replace(",", "."), "cor": "#D1495B",
     "sub": q.brl(fora["valor_recebido"].sum() if not fora.empty else 0)},
    {"rotulo": "Pago a terceiros pelos entes", "valor": q.brl(de["pago_terceiros"].sum() if not de.empty else 0)},
    {"rotulo": "Desse valor, na CAIXA", "valor": q.pct(de["pago_terceiros_caixa"].sum() / de["pago_terceiros"].sum())
     if not de.empty and de["pago_terceiros"].sum() else "—", "cor": "#005CA9"},
])

if not com_banco.empty:
    secao("Em que banco os recebedores recebem")
    c1, c2 = st.columns(AUREA_INV)
    with c1:
        por_banco = com_banco.groupby("banco_principal")["valor_recebido"].sum().sort_values(ascending=False)
        rosca(por_banco, "Valor recebido, por banco principal", {b: cor_banco(b) for b in por_banco.index}, altura=340)
    with c2:
        ranking(fora.rename(columns={"recebedor": "nome"}), "valor_recebido", "brl", n=12,
                titulo="Maiores recebedores fora da CAIXA")

aba1, aba2 = st.tabs(["Fornecedores", "Pagamentos por ente"])
with aba1:
    if fo.empty:
        st.info("Sem pagamentos carregados.")
    else:
        f1, f2, f3 = st.columns(3)
        fonte = f1.multiselect("Fonte do dado", sorted(fo["fonte"].dropna().unique()), placeholder="Todas")
        so_fora = f2.checkbox("Só quem recebe principalmente fora da CAIXA", value=True)
        minimo = f3.number_input("Recebido mínimo (R$)", min_value=0.0, value=100_000.0, step=50_000.0)
        v = fo[fo["valor_recebido"] >= minimo]
        if fonte:
            v = v[v["fonte"].isin(fonte)]
        if so_fora:
            v = v[v["banco_principal"].fillna("") != "CAIXA"]
        tabela(v.head(2000), altura=460)
        leitura("Sobre os dados", ["O banco do recebedor vem dos lançamentos das Transferências Especiais (casado pelo nome). "
                                   "Nos relatórios de gestão e no Fundo a Fundo aparece o CNPJ, mas não o banco."])
        baixar("fornecedores", {"fornecedores": v})
with aba2:
    tabela(de, altura=460)
