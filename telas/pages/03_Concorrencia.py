import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.ui import baixar, barras_modalidade, cartoes, leitura, pagina, rosca, secao, tabela  # noqa: E402

ctx = pagina("Concorrência", "Onde cada banco ganha: por UF, por modalidade e pela mudança de banco dos entes.")
d = ctx.d
instr = ctx.f("fato_instrumento")
com = instr[instr["grupo_banco"] != "(sem banco)"]
pe = d["mart_perfil_ente"]
if ctx.ufs and not pe.empty:
    pe = pe[pe["uf"].isin(ctx.ufs)]
v = com["valor"].sum()
por_banco = com.groupby("grupo_banco")["valor"].sum().sort_values(ascending=False)

cartoes([
    {"rotulo": "Valor com banco definido", "valor": q.brl(v)},
    *[{"rotulo": f"Participação {b}", "valor": q.pct(x / v) if v else "—", "sub": q.brl(x),
       "cor": "#005CA9" if b == "CAIXA" else "#F2C500" if b == "BB" else "#8C1D40"} for b, x in por_banco.head(3).items()],
    {"rotulo": "Entes conquistados (último ano)", "valor": int((pe["rotacao"] == "conquistado").sum()) if not pe.empty else 0,
     "sub": "banco principal: concorrente → CAIXA", "cor": "#00A19A",
     "ajuda": "Banco principal do ente no último ano com dados comparado ao ano anterior"},
    {"rotulo": "Trocaram a CAIXA (último ano)", "valor": int((pe["rotacao"] == "perdido").sum()) if not pe.empty else 0,
     "sub": "banco principal: CAIXA → concorrente", "cor": "#D1495B",
     "ajuda": "Compara só os dois últimos anos. A tela Entes perdidos usa a regra PER-01 (5 anos) e por isso lista mais entes"},
])

secao("Por UF e banco da conta")
barras_modalidade(com, "uf", cor_por="grupo_banco", titulo="Valor por UF, empilhado por banco", altura=440)

secao("Por modalidade")
c1, c2 = st.columns(2)
with c1:
    barras_modalidade(com, "modulo", cor_por="grupo_banco", titulo="Valor por modalidade e banco", altura=360)
with c2:
    t = q.participacao_por(com, "modulo").reset_index()
    if not t.empty:
        tabela(t[["modulo", "Total", "CAIXA", "% CAIXA", "Concorrência"]])

secao("Perfil e mudança de banco dos entes", "Compara o banco principal de cada ente nos dois últimos anos com dados.")
if pe.empty:
    st.info("Sem dados de perfil.")
else:
    c1, c2 = st.columns(2)
    with c1:
        rosca(pe["perfil"].value_counts(), "Perfil bancário dos entes",
              {"só CAIXA": "#005CA9", "multibanco": "#F39200", "só concorrente": "#D1495B"})
    with c2:
        rosca(pe["rotacao"].value_counts(), "Mudança de banco",
              {"conquistado": "#00A19A", "perdido": "#D1495B", "estável": "#9AA4B1",
               "trocou entre concorrentes": "#F2C500", "sem comparação": "#C7CDD6"})
    perdidos = pe[pe["rotacao"] == "perdido"].sort_values("valor_total", ascending=False)
    leitura("Leitura", [f"<b>{len(perdidos)}</b> entes trocaram a CAIXA pelo concorrente no último ano com dados. "
                        "São a primeira lista de reconquista."] if len(perdidos) else [])
    tabela(perdidos[["nome_ente", "uf", "banco_ano_anterior", "banco_ano_atual", "valor_total", "part_caixa"]])
    baixar("concorrencia", {"perdidos": perdidos, "perfil": pe})
