import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.ui import escolher, baixar, cartoes, leitura, pagina, secao, tabela  # noqa: E402

ctx = pagina("CRM · Rede de relacionamento",
             "Quem manda o dinheiro (parlamentares), quem recebe (entes), em que banco fica e quem é pago "
             "(fornecedores), com as sanções. Comece pelo resumo das principais relações (80/20) e use a rede "
             "completa para explorar a partir de qualquer ponto.", filtros=False)
d = ctx.d
rd = q.rede_legivel(d)
if rd is None or rd.empty:
    st.info("A rede nasce na carga diária (emendas do Portal + instrumentos e pagamentos do Transferegov).")
    st.stop()

# banco predominante de cada ente (pelos instrumentos): base da leitura "CAIXA × concorrente"
eb = rd[rd["destino_tipo"] == "banco"].pivot_table(index="origem_id", columns="destino_id", values="valor",
                                                   aggfunc="sum").fillna(0)
part_ente = (eb.get("CAIXA", 0) / eb.sum(axis=1).replace(0, float("nan"))) if not eb.empty else pd.Series(dtype=float)

if st.session_state.pop("_rede_modo_pend", None):      # clique no resumo abre a rede completa
    st.session_state["rede_modo"] = "Rede completa"
modo = st.radio("Visão", ["Principais relações (80/20)", "Rede completa"], horizontal=True, key="rede_modo",
                help="80/20: as poucas relações que concentram 80% do valor de cada tipo. Completa: tudo, a partir de "
                     "um ponto escolhido.")

# ================================================================ resumo 80/20
if modo.startswith("Principais"):
    c1, c2, c3 = st.columns([2, 2, 3])
    rels = sorted(rd["relacao"].unique())
    escolha = c1.multiselect("Tipos de relação", rels, default=rels, key="rede_rels")
    corte = c2.select_slider("Concentração", [0.5, 0.6, 0.7, 0.8, 0.9], value=0.8, key="rede_corte",
                             format_func=lambda v: f"{int(v * 100)}% do valor")
    maximo = c3.slider("Máximo de relações por tipo no gráfico", 10, 80, 30, key="rede_max")
    base = rd[rd["relacao"].isin(escolha)] if escolha else rd
    principais, resumo = q.pareto(base, corte, maximo)
    if resumo.empty:
        st.info("Sem relações para esses tipos.")
        st.stop()
    tot_rel, tot_80 = int(resumo["relacoes"].sum()), int(resumo["relacoes_no_corte"].sum())
    cartoes([
        {"rotulo": "Relações na rede", "valor": f"{tot_rel:,}".replace(",", "."), "sub": "todas as fontes"},
        {"rotulo": f"Relações que somam {int(corte * 100)}% do valor", "valor": f"{tot_80:,}".replace(",", "."),
         "sub": f"{q.pct(tot_80 / tot_rel) if tot_rel else '—'} das relações", "cor": "#7E5BB5"},
        {"rotulo": "No gráfico", "valor": len(principais), "sub": f"até {maximo} por tipo, as maiores"},
        {"rotulo": "Sanções entre as principais", "valor": int((principais["destino_tipo"] == "sanção").sum()),
         "cor": "#D1495B"},
    ])
    leitura("Concentração (regra 80/20)", [
        f"<b>{r.relacao}</b>: {int(r.relacoes_no_corte):,} de {int(r.relacoes):,} relações "
        f"({q.pct(r.pct_relacoes_no_corte)}) concentram {q.pct(r.pct_valor_no_corte)} do valor "
        f"({q.brl(r.valor_no_corte)}).".replace(",", ".") for r in resumo.itertuples()])
    clic = g.rede(principais, chave=f"rede80_{int(corte * 100)}_{maximo}_{len(escolha)}", altura=640, rotulos_todos=True)
    if clic:
        st.session_state["crm_rede_foco"] = clic
        st.session_state["_rede_modo_pend"] = True
        st.rerun()
    st.caption("Cores: roxo = parlamentar · azul-escuro = ente · azul = CAIXA · amarelo = concorrente · verde = "
               "fornecedor · vermelho = sanção. Clique num ponto para abrir a rede completa a partir dele.")

    secao("Principais redes por protagonista", "Quem está no centro do dinheiro: maiores parlamentares, entes e "
                                                "fornecedores pelo valor das suas relações.")
    t1, t2, t3 = st.tabs(["Parlamentares", "Entes", "Fornecedores"])

    def protagonistas(tipo: str) -> pd.DataFrame:
        o = rd[rd["origem_tipo"] == tipo].groupby("origem_id").agg(nome=("origem", "first"), valor=("valor", "sum"),
                                                                     relacoes=("destino_id", "nunique"))
        de = rd[rd["destino_tipo"] == tipo].groupby("destino_id").agg(nome=("destino", "first"), valor=("valor", "sum"),
                                                                        relacoes=("origem_id", "nunique"))
        x = pd.concat([o, de]).groupby(level=0).agg(nome=("nome", "first"), valor=("valor", "sum"),
                                                     relacoes=("relacoes", "sum"))
        x = x.sort_values("valor", ascending=False)
        x["part_do_total"] = x["valor"] / x["valor"].sum() if x["valor"].sum() else None
        x["pct_acumulado"] = x["part_do_total"].cumsum()
        return x.reset_index(names="id")

    with t1:
        p = protagonistas("parlamentar")
        if not p.empty:
            pe = rd[(rd["origem_tipo"] == "parlamentar") & (rd["destino_tipo"] == "ente")].copy()
            pe["part"] = pe["destino_id"].map(part_ente)
            pe["no_concorrente"] = pe["valor"] * (1 - pe["part"].fillna(0)) * pe["part"].notna()
            p["valor_concorrente"] = p["id"].map(pe.groupby("origem_id")["no_concorrente"].sum()).fillna(0)
            p = p.rename(columns={"nome": "parlamentar", "relacoes": "entes"})
            tabela(p[["parlamentar", "valor", "entes", "part_do_total", "pct_acumulado", "valor_concorrente"]],
                   chave="rede_parl")
    with t2:
        p = protagonistas("ente")
        if not p.empty:
            p["part_caixa"] = p["id"].map(part_ente)
            tabela(p.rename(columns={"nome": "nome_ente", "id": "cnpj_ente"})[
                ["nome_ente", "valor", "relacoes", "part_do_total", "pct_acumulado", "part_caixa", "cnpj_ente"]],
                chave="rede_entes")
    with t3:
        p = protagonistas("fornecedor")
        if not p.empty:
            p["sancionado"] = p["id"].isin(set(rd.loc[rd["destino_tipo"] == "sanção", "origem_id"]))
            tabela(p.rename(columns={"nome": "favorecido", "id": "doc_favorecido"})[
                ["favorecido", "valor", "relacoes", "part_do_total", "pct_acumulado", "sancionado", "doc_favorecido"]],
                chave="rede_forn")
    secao("Resumo por tipo de relação")
    tabela(resumo)
    baixar("rede_principais", {"principais": principais, "resumo": resumo})

# ================================================================ rede completa
else:
    TIPOS = {"Parlamentar": "parlamentar", "Ente": "ente", "Fornecedor": "fornecedor"}
    c1, c2, c3, c4 = st.columns([1, 3, 1, 1])
    tipo = TIPOS[c1.selectbox("Partir de", list(TIPOS))]
    pontos = pd.concat([rd.loc[rd["origem_tipo"] == tipo, ["origem_id", "origem", "valor"]].rename(
                            columns={"origem_id": "id", "origem": "nome"}),
                        rd.loc[rd["destino_tipo"] == tipo, ["destino_id", "destino", "valor"]].rename(
                            columns={"destino_id": "id", "destino": "nome"})])
    if pontos.empty:
        st.info("Sem pontos deste tipo na rede.")
        st.stop()
    pontos = pontos.groupby("id", as_index=False).agg(nome=("nome", "first"), valor=("valor", "sum")).sort_values(
        "valor", ascending=False)
    pedido = st.session_state.get("crm_rede_foco")
    pontos = pontos.assign(_rot=pontos["nome"].astype(str) + " · " + pontos["valor"].map(q.brl))
    with c2:
        foco = escolher("Quem", pontos, "id", "_rot", f"rede_foco_{tipo}", pedido=pedido)
    if foco is None:
        st.stop()
    passos = c3.radio("Passos", [1, 2], index=1, horizontal=True)
    minimo = c4.number_input("Valor mínimo (R$ mil)", min_value=0, value=0, step=50) * 1000

    viz = {foco}
    arestas = rd[(rd["origem_id"] == foco) | (rd["destino_id"] == foco)]
    if passos == 2:
        viz |= set(arestas["origem_id"]) | set(arestas["destino_id"])
        arestas = rd[rd["origem_id"].isin(viz) | rd["destino_id"].isin(viz)]
    total_viz = len(arestas)
    arestas = arestas[arestas["valor"] >= minimo].sort_values("valor", ascending=False)
    mostradas = arestas.head(300)

    cartoes([
        {"rotulo": "Relações", "valor": f"{len(arestas):,}".replace(",", "."),
         "sub": f"até {passos} passo(s)" + (f" · {len(mostradas)} no gráfico (as maiores)" if len(arestas) > 300 else "")},
        {"rotulo": "Entes envolvidos", "valor": int(pd.concat([arestas.loc[arestas["origem_tipo"] == "ente", "origem_id"],
                                                                arestas.loc[arestas["destino_tipo"] == "ente", "destino_id"]]).nunique())},
        {"rotulo": "Valor das relações", "valor": q.brl(arestas["valor"].sum()), "sub": "soma por tipo de fonte, sem misturar"},
        {"rotulo": "Sanções na vizinhança", "valor": int((arestas["destino_tipo"] == "sanção").sum()), "cor": "#D1495B"},
    ])
    clic = g.rede(mostradas, chave=f"rede_{foco}_{passos}_{minimo}", foco=foco)
    if clic and clic != foco and clic in set(rd["origem_id"]) | set(rd["destino_id"]):
        st.session_state["crm_rede_foco"] = clic
        st.rerun()
    st.caption("Cores: roxo = parlamentar · azul-escuro = ente · azul = CAIXA · amarelo = concorrente · verde = fornecedor · "
               "vermelho = sanção. Arraste os pontos, use a roda para aproximar, clique para recentrar.")
    secao("Todas as relações deste recorte", f"{total_viz:,} relações; a tabela traz todas, com busca e páginas."
          .replace(",", "."))
    tabela(arestas[["relacao", "origem", "destino", "valor", "fonte", "origem_id", "destino_id"]]
           .assign(origem_id=lambda x: x["origem_id"].map(q.cnpj_fmt), destino_id=lambda x: x["destino_id"].map(q.cnpj_fmt)),
           chave=f"rede_tab_{foco}")

    # ---------------------------------------------------------------- leituras com foco CAIXA
    secao("Quem leva o dinheiro para o concorrente", "Parlamentares por valor de emendas pagas a entes que operam "
                                                      "majoritariamente fora da CAIXA (pelos instrumentos do ente).")
    pe = rd[(rd["origem_tipo"] == "parlamentar") & (rd["destino_tipo"] == "ente")].copy()
    if pe.empty:
        st.caption("Sem emendas com favorecido identificado ainda.")
    else:
        pe["part_caixa_ente"] = pe["destino_id"].map(part_ente)
        pe["no_concorrente"] = pe["valor"] * (1 - pe["part_caixa_ente"].fillna(0)) * pe["part_caixa_ente"].notna()
        t = pe.groupby("origem", as_index=False).agg(entes=("destino_id", "nunique"), valor=("valor", "sum"),
                                                     no_concorrente=("no_concorrente", "sum"))
        t["part_caixa"] = 1 - t["no_concorrente"] / t["valor"].replace(0, float("nan"))
        t = t.sort_values("no_concorrente", ascending=False).rename(columns={"origem": "parlamentar",
                                                                             "no_concorrente": "valor_concorrente"})
        leitura("Leitura", [f"<b>{r.parlamentar}</b>: {q.brl(r.valor)} em emendas a {r.entes} entes; "
                            f"{q.brl(r.valor_concorrente)} chegam a entes que operam no concorrente."
                            for r in t.head(3).itertuples()])
        tabela(t, chave="rede_parl_conc")

    secao("Fornecedores que recebem de entes CAIXA", "Quem é pago com dinheiro de entes cuja custódia é da CAIXA: "
                                                     "relacionamento a construir (domicílio bancário, folha, convênios).")
    ef = rd[(rd["origem_tipo"] == "ente") & (rd["destino_tipo"] == "fornecedor")].copy()
    if not ef.empty:
        ef["ente_caixa"] = ef["origem_id"].map(part_ente).fillna(0) >= 0.5
        tf = ef[ef["ente_caixa"]].groupby(["destino_id", "destino"], as_index=False).agg(
            entes=("origem_id", "nunique"), valor=("valor", "sum")).sort_values("valor", ascending=False)
        tabela(tf.rename(columns={"destino_id": "doc_favorecido", "destino": "favorecido"})
               .assign(doc_favorecido=lambda x: x["doc_favorecido"].map(q.cnpj_fmt)), chave="rede_forn_cx")
