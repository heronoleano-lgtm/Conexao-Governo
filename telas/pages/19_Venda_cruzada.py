import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.ui import baixar, cartoes, leitura, pagina, rosca, secao  # noqa: E402

ctx = pagina("Venda cruzada",
             "Ofertas que nascem dos dados: consolidar modalidades na CAIXA, conta para a transferência do Fundo a "
             "Fundo, domicílio de fornecedores, aplicação de saldo parado e relacionamento antes do crédito "
             "(regras VC-01 a VC-05).")
d = ctx.d
vc = d["mart_venda_cruzada"].copy()
if ctx.ufs and not vc.empty:
    vc = vc[vc["uf"].isin(ctx.ufs)]
if vc.empty:
    st.info("Nenhuma oferta gerada pelas regras com os filtros atuais.")
    st.stop()
po = vc.groupby(["regra", "oferta"], as_index=False).agg(entes=("cnpj_ente", "nunique"),
                                                         valor_oportunidade=("valor_oportunidade", "sum"))
multi = vc.groupby("cnpj_ente").size()
cartoes([
    {"rotulo": "Ofertas geradas", "valor": f"{len(vc):,}".replace(",", ".")},
    {"rotulo": "Entes com oferta", "valor": f"{vc['cnpj_ente'].nunique():,}".replace(",", ".")},
    {"rotulo": "Valor das oportunidades", "valor": q.brl(vc["valor_oportunidade"].sum()), "cor": "#00A19A"},
    {"rotulo": "Entes com 2 ou mais ofertas", "valor": f"{int((multi >= 2).sum()):,}".replace(",", "."), "cor": "#005CA9",
     "sub": "pacote de relacionamento"},
])
c1, c2 = st.columns([3, 2])
with c1:
    secao("Ofertas por tipo")
    g.barras(po.sort_values("valor_oportunidade", ascending=False), "oferta", {"valor_oportunidade": "Oportunidade"},
             chave="vc_tipos", horizontal=True, altura=320, cores={"Oportunidade": "#00A19A"})
with c2:
    secao("Entes por tipo de oferta")
    rosca(po.set_index("oferta")["entes"], "", None, altura=320)
leitura("Como usar", [f"<b>{r.oferta}</b> ({r.regra}): {r.entes} entes, {q.brl(r.valor_oportunidade)}." for r in po.itertuples()])

secao("Matriz de ofertas por UF")
mat = vc.groupby(["uf", "oferta"], as_index=False)["valor_oportunidade"].sum()
top = mat.groupby("uf")["valor_oportunidade"].sum().nlargest(15).index.tolist()
g.heatmap(mat[mat["uf"].isin(top)], "uf", "oferta", "valor_oportunidade", chave="vc_heat", formato="brl", altura=320,
          ordem_x=top)

secao("Lista de ofertas", "Clique numa linha para abrir o ente no Assessor.")
f1, f2 = st.columns(2)
tipos = f1.multiselect("Oferta", sorted(vc["oferta"].unique()), placeholder="Todas")
minimo = f2.number_input("Oportunidade mínima (R$)", min_value=0.0, value=0.0, step=100000.0)
v = vc[vc["valor_oportunidade"] >= minimo]
if tipos:
    v = v[v["oferta"].isin(tipos)]
sel = g.grade(v.sort_values("valor_oportunidade", ascending=False), chave="vc_lista", selecao=True)
if sel and sel.get("cnpj_ente"):
    ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
            {ui.ENTE: sel["cnpj_ente"]}, chave="vc_abrir")
baixar("venda_cruzada", {"ofertas": v, "por_tipo": po})
