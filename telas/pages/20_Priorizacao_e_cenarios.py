import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia import regras  # noqa: E402
from custodia.semantica import QUADRANTE_CORES  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao  # noqa: E402

ctx = pagina("Priorização e cenários",
             "Quem atacar primeiro, cruzando potencial de custódia e chance de conversão (regras PRI-01 e PRI-02), "
             "e quanto a CAIXA ganha se chegar a uma meta de participação.")
d = ctx.d
pr = d["mart_priorizacao"].copy()
if ctx.ufs and not pr.empty:
    pr = pr[pr["uf"].isin(ctx.ufs)]
aba1, aba2 = st.tabs(["Matriz de priorização", "Simulador de cenários"])
with aba1:
    if pr.empty:
        st.info("Sem entes com potencial nos filtros atuais.")
    else:
        pq = pr.groupby("quadrante", as_index=False).agg(entes=("cnpj_ente", "count"),
                                                         potencial_custodia=("potencial_custodia", "sum"),
                                                         resultado_estimado_ano=("resultado_estimado_ano", "sum"))
        get = lambda n, c: pq.loc[pq["quadrante"] == n, c].sum()  # noqa: E731
        cartoes([{"rotulo": n, "valor": q.brl(get(n, "potencial_custodia")), "cor": QUADRANTE_CORES[n],
                  "sub": f"{int(get(n, 'entes')):,} entes · {q.brl(get(n, 'resultado_estimado_ano'))}/ano".replace(",", ".")}
                 for n in ["Atacar já", "Construir relação", "Ganho rápido", "Monitorar"]])
        lim = pr["potencial_custodia"].quantile(float(regras.param("PRI-02", "percentil_potencial_alto", 0.75)))
        clicado = g.quadrante(pr, "potencial_custodia", "chance_conversao", "potencial_custodia", "nome_ente",
                              chave="pri_quad", cor_por="quadrante", cores=QUADRANTE_CORES, linha_x=lim,
                              linha_y=float(regras.param("PRI-02", "chance_alta", 50)), altura=520,
                              nome_x="Potencial de custódia", nome_y="Chance de conversão", formato_y="int")
        if clicado:
            linha = pr[pr["nome_ente"] == clicado].head(1)
            if not linha.empty:
                ui.abrir(f"Abrir {clicado} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
                        {ui.ENTE: linha["cnpj_ente"].iloc[0]}, chave="pri_abrir")
        leitura("Como ler", ["À direita, mais potencial; acima, mais chance de converter. Comece por <b>Atacar já</b> "
                             "(canto superior direito) e use <b>Ganho rápido</b> para resultados de curto prazo.",
                             "A chance de conversão é uma premissa comercial (PRI-01): calibre os pesos em "
                             "Regras e premissas conforme o resultado das abordagens."])
        quad = st.multiselect("Prioridade", list(QUADRANTE_CORES), default=["Atacar já", "Ganho rápido"])
        g.grade(pr[pr["quadrante"].isin(quad)] if quad else pr, chave="pri_lista")
with aba2:
    er = d["mart_ente_resumo"]
    if ctx.ufs:
        er = er[er["uf"].isin(ctx.ufs)]
    c1, c2, c3, c4 = st.columns(4)
    por = c1.selectbox("Agrupar por", ["uf", "regiao", "porte", "segmento", "esfera"],
                       format_func=lambda c: {"uf": "UF", "regiao": "Região", "porte": "Porte", "segmento": "Segmento",
                                              "esfera": "Esfera"}[c])
    meta = c2.slider("Meta de participação CAIXA", 0.3, 0.9, 0.6, 0.05, format="%.2f")
    taxa = c3.number_input("Taxa de referência (% a.a.)", value=float(regras.param("PERM-03", "taxa_referencia_aa", 10.5)), step=0.25)
    frac = c4.slider("Fração aproveitada", 0.05, 1.0, float(regras.param("PERM-03", "fracao_resultado", 0.3)), 0.05)
    cen = q.cenario(er, por, meta, taxa, frac)
    if cen.empty:
        st.info("Sem dados.")
    else:
        cartoes([
            {"rotulo": f"Ganho de custódia na meta de {meta:.0%}", "valor": q.brl(cen["ganho_custodia"].sum()), "cor": "#00A19A"},
            {"rotulo": "Resultado estimado / ano", "valor": q.brl(cen["ganho_resultado_ano"].sum()), "cor": "#005CA9"},
            {"rotulo": "Ganho em valor transferido", "valor": q.brl(cen["ganho_valor"].sum())},
            {"rotulo": "Grupos abaixo da meta", "valor": int((cen["part_caixa"] < meta).sum()), "sub": f"de {len(cen)}"},
        ])
        g.barras(cen.head(20), por, {"ganho_custodia": "Ganho de custódia", "ganho_resultado_ano": "Resultado / ano"},
                 chave="cen_barras", empilhado=False, altura=380)
        g.grade(cen, chave="cen_tabela")
        st.caption("O ganho considera só o que falta para a meta em cada grupo; grupos acima da meta contam zero.")
baixar("priorizacao", {"priorizacao": pr})
