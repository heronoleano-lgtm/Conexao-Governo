import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import streamlit as st  # noqa: E402

from custodia import config  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia.semantica import SEGMENTO_CORES  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, ranking, rosca, secao, tabela  # noqa: E402
from custodia.ui import AUREA_INV  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Potencial e ações",
             "Quanto pode vir para a CAIXA em cada ente e o que fazer primeiro. Potencial = saldo hoje no concorrente "
             "+ metade do que ainda vai ser creditado no concorrente + janelas abertas.")
d = ctx.d
p = d["mart_potencial"].copy()
if ctx.ufs and not p.empty:
    p = p[p["uf"].isin(ctx.ufs)]
if p.empty:
    st.info("Sem dados.")
    st.stop()
mc = config.carregar().get("motores", {})
conquista = p[~p["acao_recomendada"].str.startswith("Manter")]

cartoes([
    {"rotulo": "Potencial de custódia", "estimado": True, "valor": q.brl(p["potencial_custodia"].sum()), "cor": "#00A19A"},
    {"rotulo": "Resultado estimado por ano", "estimado": True, "valor": q.brl(p["resultado_estimado_ano"].sum()),
     "ajuda": f"Taxa {mc.get('taxa_referencia_aa')}% a.a. × fração {mc.get('fracao_resultado')} (config.yaml)"},
    {"rotulo": "Entes com ação de conquista", "valor": f"{len(conquista):,}".replace(",", "."), "cor": "#F39200"},
    {"rotulo": "Pagamentos que saem para outros bancos", "valor": q.brl(p["pagamentos_fora_caixa"].sum()),
     "cor": "#D1495B"},
])

seg = p.groupby("segmento", as_index=False).agg(entes=("cnpj_ente", "count"),
                                                potencial_custodia=("potencial_custodia", "sum"),
                                                resultado_estimado_ano=("resultado_estimado_ano", "sum"))
ac = p.groupby("acao_recomendada", as_index=False).agg(entes=("cnpj_ente", "count"),
                                                       potencial_custodia=("potencial_custodia", "sum"))
secao("Onde está o potencial")
c1, c2 = st.columns(AUREA_INV)
with c1:
    rosca(seg.set_index("segmento")["potencial_custodia"], "Potencial por segmento", SEGMENTO_CORES, altura=340)
with c2:
    ranking(ac.rename(columns={"acao_recomendada": "nome"}), "potencial_custodia", "brl", n=10,
            titulo="Potencial por ação recomendada")
top = p.sort_values("potencial_custodia", ascending=False).head(3)
leitura("Leitura", [f"<b>{r.nome_ente} ({r.uf})</b>: {q.brl(r.potencial_custodia)} · {r.acao_recomendada}"
                    for r in top.itertuples()] if "nome_ente" in p else [])
c1, c2 = st.columns(2)
with c1:
    tabela(seg.sort_values("potencial_custodia", ascending=False))
with c2:
    tabela(ac.sort_values("potencial_custodia", ascending=False))

secao("Fila de trabalho")
f1, f2 = st.columns(2)
segs = f1.multiselect("Segmento", sorted(p["segmento"].unique()), placeholder="Todos")
acoes = f2.multiselect("Ação", sorted(p["acao_recomendada"].unique()), placeholder="Todas")
v = p
if segs:
    v = v[v["segmento"].isin(segs)]
if acoes:
    v = v[v["acao_recomendada"].isin(acoes)]
tabela(v.sort_values("potencial_custodia", ascending=False).head(3000), altura=460)
baixar("potencial_e_acoes", {"fila": v, "segmentos": seg, "acoes": ac})
st.caption("O resultado estimado é uma ordem de grandeza para priorizar, não um cálculo oficial. Ajuste as premissas "
           "em config/config.yaml (motores.taxa_referencia_aa e motores.fracao_resultado).")
