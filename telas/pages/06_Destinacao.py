import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.semantica import nome_modalidade  # noqa: E402
from custodia.ui import baixar, cartoes, pagina, ranking, secao, tabela, treemap  # noqa: E402
from custodia.ui import AUREA  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Destinação dos recursos",
             "Para que o dinheiro vai: área de política pública (Transferências Especiais, rateada entre as áreas de "
             "cada executor) e natureza da despesa planejada (Fundo a Fundo).")
d = ctx.d
de = ctx.f("mart_destinacao", anos=False, ufs=False)
if de.empty:
    st.info("Sem dados de destinação carregados.")
    st.stop()

for modulo, g in de.groupby("modulo"):
    por_tipo = g.groupby("tipo", as_index=False).agg(valor=("valor", "sum"), valor_caixa=("valor_caixa", "sum"))
    por_tipo["part_caixa"] = por_tipo["valor_caixa"] / por_tipo["valor"].replace(0, float("nan"))
    secao(nome_modalidade(modulo))
    top = por_tipo.sort_values("valor", ascending=False).iloc[0]
    fraca = por_tipo[por_tipo["valor"] > por_tipo["valor"].sum() * 0.02].sort_values("part_caixa").head(1)
    cartoes([
        {"rotulo": "Valor com destinação", "valor": q.brl(por_tipo["valor"].sum())},
        {"rotulo": "Maior destinação", "valor": str(top["tipo"])[:26], "sub": q.brl(top["valor"])},
        {"rotulo": "Onde a CAIXA é mais fraca", "valor": str(fraca["tipo"].iloc[0])[:26] if not fraca.empty else "—",
         "sub": q.pct(fraca["part_caixa"].iloc[0]) if not fraca.empty else "", "cor": "#D1495B"},
    ])
    c1, c2 = st.columns(AUREA)
    with c1:
        treemap(g, ["tipo", "destinacao"], "valor", "part_caixa", altura=460)
    with c2:
        ranking(por_tipo.rename(columns={"tipo": "nome"}), "valor", "brl", n=12, titulo="Maiores destinações")
    with st.expander("Detalhe"):
        tabela(g)
baixar("destinacao", {"destinacao": de})
