import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.ui import baixar, cartoes, leitura, pagina, sankey, secao  # noqa: E402
from custodia.ui import AUREA  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Matriz de escolhas",
             "Qual banco cada ente escolhe em cada modalidade e ano, quão fiel ele é e para onde vão os que trocam "
             "(regras ESC-01 e ESC-02). Transferências Especiais e convênios — o Fundo a Fundo é sempre BB.")
d = ctx.d
esc = d["mart_escolha_ente"].copy()
if ctx.ufs and not esc.empty:
    esc = esc[esc["uf"].isin(ctx.ufs)]
if esc.empty:
    st.info("Sem escolhas de banco carregadas.")
    st.stop()
tr = d["mart_transicoes"]
fiel = tr[tr["banco_de"] == tr["banco_para"]]["entes"].sum() if not tr.empty else 0
total_tr = tr["entes"].sum() if not tr.empty else 0
cx_para_conc = tr[(tr["banco_de"] == "CAIXA") & (tr["banco_para"] != "CAIXA")]["entes"].sum() if not tr.empty else 0
conc_para_cx = tr[(tr["banco_de"] != "CAIXA") & (tr["banco_para"] == "CAIXA")]["entes"].sum() if not tr.empty else 0
ult = int(esc["ano"].max())
ua = esc[esc["ano"] == ult]
cartoes([
    {"rotulo": f"Entes com instrumentos em {ult}", "valor": f"{ua['cnpj_ente'].nunique():,}".replace(",", ".")},
    {"rotulo": f"Escolheram a CAIXA em {ult}", "valor": q.pct((ua["grupo_banco"] == "CAIXA").mean()), "cor": "#005CA9"},
    {"rotulo": "Fidelidade ano a ano", "valor": q.pct(fiel / total_tr) if total_tr else "—", "sub": "mesmo banco no ano seguinte"},
    {"rotulo": "Trocas da CAIXA para o concorrente", "valor": f"{cx_para_conc:,}".replace(",", "."), "cor": "#D1495B"},
    {"rotulo": "Trocas do concorrente para a CAIXA", "valor": f"{conc_para_cx:,}".replace(",", "."), "cor": "#00A19A",
     "sub": f"saldo líquido {conc_para_cx - cx_para_conc:+,}".replace(",", ".")},
])

secao("Banco nas Transferências Especiais × banco nos convênios", "Entes nos últimos 3 anos, pelo banco predominante em cada modalidade.")
mm = d["mart_matriz_modalidades"]
c1, c2 = st.columns(AUREA)
with c1:
    ordem = ["CAIXA", "BB", "BNB", "não usa"]
    g.heatmap(mm, "banco_convenios", "banco_especiais", "entes", chave="esc_matriz", formato="int", altura=380,
              ordem_x=[o for o in ordem if o in set(mm["banco_convenios"])] + sorted(set(mm["banco_convenios"]) - set(ordem)),
              ordem_y=[o for o in ordem if o in set(mm["banco_especiais"])] + sorted(set(mm["banco_especiais"]) - set(ordem)),
              titulo="Linhas: Transferências Especiais · Colunas: convênios")
with c2:
    divid = mm[((mm["banco_especiais"] == "CAIXA") & ~mm["banco_convenios"].isin(["CAIXA", "não usa"])) |
               ((mm["banco_convenios"] == "CAIXA") & ~mm["banco_especiais"].isin(["CAIXA", "não usa"]))]
    leitura("O que a matriz mostra", [
        f"<b>{int(divid['entes'].sum()):,}</b> entes usam a CAIXA numa modalidade e o concorrente na outra "
        f"({q.brl(divid['valor'].sum())}): são o alvo da regra VC-01, consolidar na CAIXA.".replace(",", "."),
        "A diagonal mostra os entes que usam o mesmo banco nas duas modalidades."])

secao("Para onde vão os que trocam de banco", "De um ano com instrumentos para o seguinte, por modalidade.")
mod = st.radio("Modalidade", sorted(tr["modulo"].unique()) if not tr.empty else [], horizontal=True,
               format_func=lambda m: {"Especiais": "Transferências Especiais", "Discricionárias": "Convênios"}.get(m, m))
t = tr[(tr["modulo"] == mod) & (tr["banco_de"] != tr["banco_para"])] if not tr.empty else tr
c1, c2 = st.columns(2)
with c1:
    if not t.empty:
        sankey(pd.DataFrame({"etapa": "troca", "origem": t["banco_de"] + " (antes)", "destino": t["banco_para"] + " (depois)",
                             "valor": t["entes"]}), altura=360)
with c2:
    g.heatmap(tr[tr["modulo"] == mod] if not tr.empty else tr, "banco_para", "banco_de", "entes", chave="esc_trans",
              formato="int", altura=360, titulo="Linhas: banco antes · Colunas: banco depois")

secao("Escolhas por ente", "Uma linha por ente, modalidade e ano.")
pv = esc.pivot_table(index=["cnpj_ente", "nome_ente", "uf", "modulo"], columns="ano", values="grupo_banco", aggfunc="first")
anos = [a for a in sorted(pv.columns)][-6:]
pv = pv[anos].reset_index()
pv.columns = [f"ano_{c}" if isinstance(c, (int, float)) or str(c).isdigit() else str(c) for c in pv.columns]
st.caption("Bancos escolhidos nos últimos anos (vazio = sem instrumento no ano).")
g.grade(pv, chave="esc_entes", altura=420)
baixar("matriz_de_escolhas", {"escolhas": esc, "transicoes": tr, "matriz": mm})
