import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import auditoria as au  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao, tabela  # noqa: E402

ctx = pagina("Auditoria da carga",
             "Conferência diária da carga bruta antes de virar informação: completude, estrutura, chaves, domínios, "
             "integridade entre tabelas, coerência, frescor da fonte e reconciliação com o painel (regra QLD-03).",
             filtros=False)
d = ctx.d
aud, hist = d.get("mart_auditoria", pd.DataFrame()), d.get("mart_auditoria_historico", pd.DataFrame())
if aud.empty:
    st.info("A auditoria roda junto com a carga diária. Rode carga_diaria.bat ou auditar_carga.bat.")
    st.stop()
cont = aud["status"].value_counts()
cor = {au.CRITICO: "#D1495B", au.ATENCAO: "#F39200", au.OK: "#00A19A", au.NV: "#9AA4B1"}
veredito = ("Números confiáveis" if not cont.get(au.CRITICO) else "Há pontos críticos")
cartoes([{"rotulo": "Veredito do dia", "valor": veredito, "sub": f"carga de {aud['dia'].iloc[0]}",
          "cor": cor[au.CRITICO] if cont.get(au.CRITICO) else cor[au.OK]}] +
        [{"rotulo": s.capitalize(), "valor": int(cont.get(s, 0)), "cor": cor[s]} for s in (au.CRITICO, au.ATENCAO, au.OK, au.NV)])
leitura("Leitura da auditoria", au.interpretar(aud))

c1, c2 = st.columns([3, 2])
with c1:
    secao("Por família de checagem")
    pf = aud.pivot_table(index="familia", columns="status", values="checagem", aggfunc="count").fillna(0).reset_index()
    g.barras(pf, "familia", {s: s for s in (au.CRITICO, au.ATENCAO, au.OK, au.NV) if s in pf.columns},
             chave="aud_familia", formato="int", horizontal=True, altura=340, cores=cor)
with c2:
    secao("Evolução", "Checagens por status em cada carga.")
    if not hist.empty and hist["dia"].nunique() > 1:
        g.linha_tempo(hist, "dia", "checagens", chave="aud_hist", cor_por="status", formato="int", area=False,
                      cores=cor, altura=340)
    else:
        st.caption("A evolução aparece a partir da segunda carga auditada.")

secao("Checagens", "Comece pelas críticas: a coluna Impacto diz o que fica comprometido no painel.")
f1, f2 = st.columns(2)
sts = f1.multiselect("Status", [au.CRITICO, au.ATENCAO, au.NV, au.OK], default=[au.CRITICO, au.ATENCAO])
fams = f2.multiselect("Família", sorted(aud["familia"].unique()), placeholder="Todas")
v = aud[aud["status"].isin(sts)] if sts else aud
if fams:
    v = v[v["familia"].isin(fams)]
g.grade(v.drop(columns=["dia"]), chave="aud_lista", altura=460)
st.caption("Relatório do dia em HTML: C:/PainelCustodia/data/auditoria/relatorio_AAAA-MM-DD.html "
           "(pasta de dados configurada no config.yaml).")
baixar("auditoria_da_carga", {"auditoria": aud})

# ---------------------------------------------------------------- auditoria do que o painel mostra
secao("Auditoria do que o painel mostra",
      "Os números que chegam às telas: percentuais entre 0% e 100%, parte ≤ todo, linhas repetidas, valores "
      "negativos, mesmos totais em todas as telas e território coerente.")
ap = d.get("mart_auditoria_painel", pd.DataFrame())
if ap.empty:
    st.info("Esta auditoria roda na carga diária (ou avulsa: auditar_painel.bat).")
else:
    cp = ap["status"].value_counts()
    cartoes([{"rotulo": "Checagens das telas", "valor": int(len(ap)), "sub": f"carga de {ap['dia'].iloc[0]}"}] +
            [{"rotulo": s.capitalize(), "valor": int(cp.get(s, 0)), "cor": cor[s]} for s in (au.CRITICO, au.ATENCAO, au.OK)])
    falhas = ap[ap["status"] != au.OK]
    if falhas.empty:
        st.success("Nenhum número impossível ou incoerente nas telas.")
    else:
        g.grade(falhas[["familia", "tabela", "checagem", "status", "valor", "referencia", "detalhe"]],
                chave="aud_painel", altura=360)
        ex = d.get("mart_auditoria_painel_exemplos", pd.DataFrame())
        if not ex.empty:
            alvo = st.selectbox("Ver as linhas que falharam em", sorted(ex["_checagem"].unique()))
            tabela(ex[ex["_checagem"] == alvo].drop(columns="_checagem").replace("", None).dropna(axis=1, how="all"))
    baixar("auditoria_do_painel", {"painel": ap, "exemplos": d.get("mart_auditoria_painel_exemplos", pd.DataFrame())})
