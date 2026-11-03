import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.ui import (baixar, cartoes, dispersao, leitura, mapa_coropletico, pagina, ranking, secao,  # noqa: E402
                         tabela)
from custodia.ui import AUREA  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Parlamentares",
             "Para onde vão as emendas de cada autor e em que banco caem. Quem escolhe o banco é o ente; "
             "o parlamentar é canal de relacionamento institucional, não de decisão bancária.")
d = ctx.d
p = d["mart_parlamentares"].copy()
rede = d["mart_rede_parlamentar"]
if ctx.ufs and not p.empty:
    p = p[p["uf_principal"].isin(ctx.ufs)]
if p.empty:
    st.info("Sem emendas vinculadas a parlamentares nos dados carregados.")
    st.stop()

base = p["valor_caixa"].sum() + p["valor_concorrente"].sum()
cartoes([
    {"rotulo": "Parlamentares", "valor": f"{len(p):,}".replace(",", ".")},
    {"rotulo": "Valor das emendas", "valor": q.brl(p["valor"].sum())},
    {"rotulo": "Parte que cai na CAIXA", "valor": q.pct(p["valor_caixa"].sum() / base) if base else "—"},
    {"rotulo": "Base majoritária no concorrente", "valor": int((p["part_caixa"] < 0.4).sum()), "cor": "#D1495B",
     "sub": "menos de 40% na CAIXA"},
    {"rotulo": "Valor desses autores no concorrente", "valor": q.brl(p.loc[p["part_caixa"] < 0.4, "valor_concorrente"].sum()),
     "cor": "#F39200"},
])

secao("Quadrante de prioridade", "Cada bolha é um parlamentar: à direita, mais valor; embaixo, menos CAIXA. "
                                 "O canto inferior direito concentra a agenda institucional prioritária.")
c1, c2 = st.columns(AUREA)
with c1:
    dispersao(p, "valor", "part_caixa", "entes", "parlamentar")
with c2:
    ranking(p.assign(nome=p["parlamentar"]), "valor_concorrente", "brl", n=12, titulo="Mais valor no concorrente")

secao("Lista de parlamentares")
f1, f2 = st.columns(2)
faixa = f1.slider("Participação CAIXA entre (%)", 0, 100, (0, 100))
minimo = f2.number_input("Valor mínimo no concorrente (R$)", min_value=0.0, value=0.0, step=1_000_000.0)
v = p[(p["part_caixa"].fillna(0) * 100).between(*faixa) & (p["valor_concorrente"] >= minimo)]
tabela(v[["parlamentar", "uf_principal", "area_principal", "valor", "valor_concorrente", "part_caixa", "entes",
          "entes_so_concorrente", "hhi_entes", "leitura", "modulos"]], altura=420)
baixar("parlamentares", {"parlamentares": v})

secao("A base de um parlamentar", "Entes atendidos, com o banco de cada conta.")
nome = st.selectbox("Parlamentar", v["parlamentar"].tolist())
if nome:
    r = rede[rede["parlamentar"] == nome].sort_values("valor", ascending=False)
    linha = p.set_index("parlamentar").loc[nome]
    leitura(nome, [linha["leitura"], f"{int(linha['entes'])} entes; {q.pct(linha['part_caixa'])} do valor na CAIXA."])
    er = d.get("mart_ente_resumo", pd.DataFrame())
    c1, c2 = st.columns(AUREA)
    with c1:
        if not er.empty:
            b = r.groupby("cnpj_ente", as_index=False).agg(valor=("valor", "sum"), grupo_banco=("grupo_banco", "first"))
            b = b.merge(er[["cnpj_ente", "nome_ente", "uf", "lat", "lon", "part_caixa", "banco_principal",
                            "potencial_custodia", "acao_recomendada"]], on="cnpj_ente", how="left")
            ufs = sorted(b["uf"].dropna().unique())
            mapa_coropletico(pd.DataFrame(), q.malha(ufs[0] if len(ufs) == 1 else "BR"), "valor", "brl", "Blues",
                             chave=f"parl_{nome}", altura=460, bolhas=b, cor_bolha="grupo_banco", tam_bolha="valor")
    with c2:
        tabela(r[["nome_ente", "uf", "grupo_banco", "valor", "instrumentos"]], altura=440)
