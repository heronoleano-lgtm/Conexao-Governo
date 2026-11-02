import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import streamlit as st  # noqa: E402

from custodia import acesso  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia.ui import escolher, baixar, cartoes, pagina, ranking, tabela  # noqa: E402

ctx = pagina("Oportunidades", "Ranking de prospecção, janelas abertas e vazamentos. "
                              "Fundo a Fundo fica fora: a conta é sempre do BB.")
d = ctx.d
sc = d["mart_score"].copy()
if ctx.ufs:
    sc = sc[sc["uf"].isin(ctx.ufs)]
cart = acesso.carteira()
if not cart.empty:
    sc = sc.merge(cart[["cnpj_ente", "status", "responsavel"]], on="cnpj_ente", how="left")
else:
    sc["status"], sc["responsavel"] = None, None
sc["status"] = sc["status"].fillna("não abordado")

f1, f2, f3 = st.columns(3)
minimo = f1.slider("Score mínimo", 0, 100, 40)
perfis = f2.multiselect("Perfil", sorted(sc["perfil"].dropna().unique()), placeholder="Todos")
status = f3.multiselect("Status na carteira", list(acesso.STATUS_CARTEIRA), placeholder="Todos")
v = sc[sc["score"] >= minimo]
if perfis:
    v = v[v["perfil"].isin(perfis)]
if status:
    v = v[v["status"].isin(status)]

cartoes([
    {"rotulo": "Entes no ranking", "valor": f"{len(v):,}".replace(",", "."), "sub": f"score ≥ {minimo}"},
    {"rotulo": "Valor recente no concorrente", "valor": q.brl(v["valor_concorrente_recente"].sum()), "cor": "#D1495B"},
    {"rotulo": "Saldo no concorrente", "valor": q.brl(v["saldo_concorrente"].sum()), "cor": "#F39200"},
    {"rotulo": "Em janelas abertas", "valor": q.brl(v["valor_janelas"].sum()), "cor": "#00A19A"},
    {"rotulo": "Ainda não abordados", "valor": int((v["status"] == "não abordado").sum())},
])
c1, c2 = st.columns(2)
with c1:
    ranking(v.sort_values("score", ascending=False), "score", "int", n=12, titulo="Maiores scores", rotulo="nome_ente")
with c2:
    mot = v.groupby("motivo_principal", as_index=False)["saldo_concorrente"].sum().rename(columns={"motivo_principal": "nome"})
    ranking(mot, "saldo_concorrente", "brl", n=8, titulo="Saldo no concorrente por motivo")

aba_rank, aba_jan, aba_vaz, aba_cart = st.tabs(
    [f"Ranking ({len(v)})", f"Janelas ({len(d['mart_janelas'])})", "Vazamento", "Atualizar carteira"])
with aba_rank:
    cols = ["score", "nome_ente", "uf", "motivo_principal", "perfil", "valor_concorrente_recente",
            "saldo_concorrente", "valor_janelas", "status", "responsavel", "cnpj_ente"]
    tabela(v[cols], moedas=("valor_concorrente_recente", "saldo_concorrente", "valor_janelas"))
    baixar("lista_de_alvos", {"alvos": v[cols]})
with aba_jan:
    jan = ctx.f("mart_janelas", modulos=False, anos=False)
    motivos = st.multiselect("Motivo", sorted(jan["motivo"].unique()) if not jan.empty else [], placeholder="Todos")
    if motivos:
        jan = jan[jan["motivo"].isin(motivos)]
    tabela(jan, moedas=("valor",))
    if not jan.empty:
        baixar("janelas", {"janelas": jan})
with aba_vaz:
    vaz = d["mart_vazamento"]
    if ctx.ufs and not vaz.empty:
        vaz = vaz[vaz["uf"].isin(ctx.ufs)]
    tabela(vaz, moedas=("valor_executor",))
with aba_cart:
    if ctx.usuario["perfil"] not in ("comercial", "administrador"):
        st.info("Seu perfil pode consultar, mas não alterar a carteira.")
    else:
        nomes = sc.sort_values("score", ascending=False)
        nomes = nomes.assign(_rot=nomes["nome_ente"].fillna("?") + " (" + nomes["cnpj_ente"].astype(str) + ")")
        escolha = escolher("Ente", nomes, "cnpj_ente", "_rot", "oport_cart")
        if escolha:
            atual = cart[cart["cnpj_ente"] == escolha]
            with st.form("carteira"):
                st_ = st.selectbox("Status", acesso.STATUS_CARTEIRA,
                                   index=acesso.STATUS_CARTEIRA.index(atual["status"].iloc[0]) if len(atual) else 0)
                resp = st.text_input("Responsável", atual["responsavel"].iloc[0] if len(atual) else ctx.usuario["nome"])
                obs = st.text_area("Observação", atual["observacao"].iloc[0] if len(atual) else "")
                if st.form_submit_button("Salvar"):
                    acesso.salvar_carteira(escolha, st_, resp, obs, ctx.usuario["login"])
                    st.success("Carteira atualizada.")
