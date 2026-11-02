import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia import regras  # noqa: E402
from custodia.ui import baixar, cartoes, pagina, secao  # noqa: E402

ctx = pagina("Regras e premissas",
             "Todas as regras de negócio que geram números, alertas e recomendações, com parâmetros e base. "
             "Ajuste em config/regras.yaml e rode completar_carga.bat.", filtros=False)
rg = regras.tabela()
cartoes([
    {"rotulo": "Regras", "valor": len(rg), "sub": f"{rg['frente'].nunique()} frentes"},
    {"rotulo": "Ativas", "valor": int((rg["status_regra"] == "ativa").sum()), "cor": "#00A19A"},
    {"rotulo": "Premissas a validar", "valor": int((rg["status_regra"] == "validar").sum()), "cor": "#F39200",
     "sub": "confirmar com a área de negócio"},
])
frente = st.multiselect("Frente", sorted(rg["frente"].dropna().unique()), placeholder="Todas")
v = rg[rg["frente"].isin(frente)] if frente else rg
for f, gpo in v.groupby("frente", sort=False):
    secao(f)
    for r in gpo.itertuples():
        selo = "🟠 validar" if r.status_regra == "validar" else "🟢 ativa"
        with st.expander(f"{r.codigo} · {r.nome_regra}  —  {selo}"):
            st.markdown(r.descricao_regra)
            st.markdown(f"**Parâmetros:** `{r.parametros}`")
            st.caption(f"Base: {r.base}")
baixar("regras_e_premissas", {"regras": rg})
