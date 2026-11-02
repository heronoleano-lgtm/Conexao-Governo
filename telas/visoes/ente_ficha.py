import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import streamlit as st  # noqa: E402

from custodia import acesso  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia.semantica import cor_banco
from custodia.ui import escolher, baixar, cartoes, pagina, rosca, tabela  # noqa: E402

ctx = pagina("Ficha do ente", "Tudo de um município ou estado em uma página, para preparar a visita.", filtros=False)
d = ctx.d
entes = d["dim_ente"].sort_values("nome_ente")
if entes.empty:
    st.info("Sem entes carregados.")
    st.stop()
entes = entes.assign(_rot=entes["nome_ente"].fillna("?") + " · " + entes["uf"].fillna("?"))
cnpj = escolher("Ente", entes, "cnpj_ente", "_rot", "ficha",
               pedido=st.session_state.get("ente_cnpj") or st.query_params.get("cnpj"))
if cnpj is None:
    st.stop()
st.session_state["ente_cnpj"] = cnpj
f = q.ficha(d, cnpj)

e, s, p = f["ente"], f["score"], f["perfil"]
pop = e.get("populacao")
cartoes([
    {"rotulo": "Score de prospecção", "valor": s.get("score", "—"), "sub": s.get("motivo_principal") or ""},
    {"rotulo": "Perfil bancário", "valor": p.get("perfil", "—"), "sub": f"Bancos: {p.get('bancos', '—')}"},
    {"rotulo": "Participação CAIXA", "valor": q.pct(p.get("part_caixa")), "cor": "#005CA9"},
    {"rotulo": "Valor total", "valor": q.brl(p.get("valor_total"))},
    {"rotulo": "População", "valor": f"{int(pop):,}".replace(",", ".") if pop == pop and pop else "—"},
])
st.caption(f"CNPJ {cnpj} · IBGE {e.get('cod_ibge') or '—'} · módulos: {e.get('modulos', '—')} · "
           f"rotação: {p.get('rotacao', '—')}")

a1, a2, a3, a4, a6, a7, a5 = st.tabs(["Instrumentos", "Contas e saldos", "Janelas", "A creditar", "Para onde vai",
                                      "Parlamentares", "Carteira e simulador"])
with a6:
    de = d["mart_destino_ente"]
    linha = de[de["cnpj_ente"] == cnpj]
    if linha.empty:
        st.info("Sem lançamentos bancários deste ente.")
    else:
        r = linha.iloc[0]
        cartoes([
            {"rotulo": "Pago a terceiros", "valor": q.brl(r["pago_terceiros"])},
            {"rotulo": "Recebedores na CAIXA", "valor": q.pct(r["part_caixa_pagamentos"]), "cor": "#005CA9"},
            {"rotulo": "Para conta própria", "valor": q.brl(r["para_conta_propria"]), "cor": "#00A19A"},
            {"rotulo": "Aplicações", "valor": q.brl(r["aplicacoes"]), "cor": "#F39200"},
        ])
    ts = d["mart_transferencia_secundaria"]
    tl = ts[ts["cnpj_ente"] == cnpj] if not ts.empty else ts
    if not tl.empty:
        r = tl.iloc[0]
        st.info(f"Fundo a Fundo: este ente já transferiu {q.brl(r['valor_transferido'])} da conta BB para conta do "
                f"próprio CNPJ ({int(r['lancamentos'])} lançamentos, último em {r['ultima']}). Saldo FaF hoje: "
                f"{q.brl(r['saldo_faf_hoje'])}. O banco de destino não é informado pela API.")
    pot = d["mart_potencial"]
    pl = pot[pot["cnpj_ente"] == cnpj]
    if not pl.empty:
        st.success(f"Ação recomendada: {pl.iloc[0]['acao_recomendada']} ({pl.iloc[0]['motivo']}). "
                   f"Potencial de custódia: {q.brl(pl.iloc[0]['potencial_custodia'])}.")
with a7:
    rede = d["mart_rede_parlamentar"]
    tabela(rede[rede["cnpj_ente"] == cnpj].sort_values("valor", ascending=False)[
        ["parlamentar", "grupo_banco", "valor", "instrumentos"]], moedas=("valor",))
with a1:
    tabela(f["instrumentos"][["modulo", "ano", "codigo", "grupo_banco", "valor", "situacao", "situacao_conta",
                              "parlamentar", "objeto"]], moedas=("valor",))
with a2:
    if not f["contas"].empty:
        sb = f["contas"].groupby("grupo_banco")["saldo"].sum()
        rosca(sb[sb > 0], "Saldo por banco", {b: cor_banco(b) for b in sb.index}, altura=280)
    cols_c = [c for c in ["modulo", "origem", "grupo_banco", "id_agencia_conta", "situacao_conta", "saldo", "data_saldo",
                          "saldo_estimado", "saldo_est_min", "saldo_est_max", "base_saldo"] if c in f["contas"]]
    tabela(f["contas"][cols_c], moedas=("saldo",))
    if "base_saldo" in f["contas"] and f["contas"]["base_saldo"].astype(str).str.startswith("estimado").any():
        st.caption("Contas com extrato parado: \"Saldo publicado\" é o último valor publicado (parado); \"Saldo estimado "
                   "hoje\" é a reconstituição da regra SAL-01, com faixa. Conta a conta a estimativa é aproximada (no "
                   "teste retroativo, a soma acerta melhor que cada conta): use a faixa.")
    if not f["vazamento"].empty:
        st.warning("Há executores deste ente recebendo em outro banco:")
        tabela(f["vazamento"], moedas=("valor_executor",))
with a3:
    tabela(f["janelas"], moedas=("valor",))
with a4:
    pipe = f["pipeline"]
    tabela(pipe[pipe["a_creditar"] > 0] if not pipe.empty else pipe, moedas=("valor_empenho", "valor_pago", "a_creditar"))
with a5:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Histórico na carteira**")
        tabela(acesso.historico_carteira(cnpj))
    with col2:
        st.markdown("**Simulador de valor da custódia**")
        saldo_conc = float(f["contas"].loc[f["contas"]["grupo_banco"] != "CAIXA", "saldo"].fillna(0).sum()) if not f["contas"].empty else 0.0
        saldo = st.number_input("Saldo médio a conquistar (R$)", min_value=0.0, value=saldo_conc, step=100000.0)
        dias = st.slider("Dias médios em conta", 30, 720, 180)
        taxa = st.number_input("Taxa de referência (% a.a., ex.: CDI)", min_value=0.0, value=10.0, step=0.25)
        frac = st.slider("Fração aproveitada como resultado", 0.0, 1.0, 0.3, 0.05)
        r = q.simular(saldo, dias, taxa, frac)
        st.metric("Resultado estimado no período", q.brl(r["receita"], curto=False))
        st.caption("Estimativa simples para conversa interna; não é cálculo oficial de resultado.")
baixar(f"ficha_{cnpj}", {"instrumentos": f["instrumentos"], "contas": f["contas"], "janelas": f["janelas"]})
