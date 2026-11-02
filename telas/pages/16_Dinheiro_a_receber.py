import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.motores_gestor import ORDEM_FAIXAS  # noqa: E402
from custodia.semantica import cor_banco, nome_modalidade  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao  # noqa: E402

ctx = pagina("Dinheiro a receber",
             "O que ainda vai entrar nas contas. Firme: emendas empenhadas e não pagas (Transferências Especiais, "
             "REC-01) e repasses ainda não liberados dos convênios assinados (REC-02). Previsto, à parte: minutas de "
             "empenho e propostas aprovadas sem convênio assinado (REC-04). O banco é o da conta já aberta.")
d = ctx.d
ar = ctx.f("mart_a_receber", anos=False)
if ar.empty:
    st.info("Nada a receber com os filtros atuais.")
    st.stop()
antigo = ar["faixa_prazo"].str.startswith("Empenho antigo")
firme = ar["firme"].fillna(False).astype(bool) if "firme" in ar else pd.Series(True, index=ar.index)
previsto = ar[~firme]
vivo = ar[~antigo & firme]
cx = vivo[vivo["grupo_banco"] == "CAIXA"]
prox = vivo[vivo["dias_para_credito"].fillna(9999) <= 90]
conc_prox = prox[prox["grupo_banco"] != "CAIXA"]
cartoes([
    {"rotulo": "A receber (firme)", "valor": q.brl(vivo["valor_a_receber"].sum()),
     "sub": f"{vivo['cnpj_ente'].nunique():,} entes".replace(",", "."),
     "ajuda": "Empenho emitido e não pago + repasse a liberar de convênio assinado"},
    {"rotulo": "Em contas CAIXA", "valor": q.brl(cx["valor_a_receber"].sum()), "cor": "#005CA9",
     "sub": q.pct(cx["valor_a_receber"].sum() / max(vivo["valor_a_receber"].sum(), 1))},
    {"rotulo": "Chega em até 90 dias", "estimado": True, "valor": q.brl(prox["valor_a_receber"].sum()), "cor": "#00A19A"},
    {"rotulo": "Em 90 dias no concorrente", "estimado": True, "valor": q.brl(conc_prox["valor_a_receber"].sum()), "cor": "#D1495B",
     "sub": f"{conc_prox['cnpj_ente'].nunique():,} entes".replace(",", ".")},
    {"rotulo": "Empenhos antigos sem pagamento", "valor": q.brl(ar.loc[antigo, "valor_a_receber"].sum()), "cor": "#9AA4B1",
     "sub": "fora da previsão — verificar"},
    {"rotulo": "Previsto (ainda não firme)", "valor": q.brl(previsto["valor_a_receber"].sum()), "cor": "#B6BFCC",
     "sub": " · ".join(f"{e.split(',')[0].split(' (')[0]}: {q.brl(v)}" for e, v in
                       previsto.groupby("etapa")["valor_a_receber"].sum().items()) if not previsto.empty else "",
     "ajuda": "Minutas de empenho e propostas aprovadas sem convênio assinado (REC-04)"},
])
if not ar.empty and "etapa" in ar:
    et = ar.groupby(["etapa", "grupo_banco"], as_index=False)["valor_a_receber"].sum()
    with st.expander("Do previsto ao firme: valor por etapa e banco"):
        g.grade(et.pivot_table(index="etapa", columns="grupo_banco", values="valor_a_receber", aggfunc="sum")
                .fillna(0).reset_index(), chave="rec_etapas", altura=240)

secao("Calendário do dinheiro", "Por prazo previsto e banco da conta.")
c1, c2 = st.columns([3, 2])
fx = vivo.groupby(["faixa_prazo", "grupo_banco"], as_index=False)["valor_a_receber"].sum()
piv = fx.pivot_table(index="faixa_prazo", columns="grupo_banco", values="valor_a_receber", aggfunc="sum").fillna(0)
piv = piv.reindex([f for f in ORDEM_FAIXAS if f in piv.index]).reset_index()
with c1:
    g.barras(piv, "faixa_prazo", {b: b for b in piv.columns if b != "faixa_prazo"}, chave="rec_faixas", altura=380,
             cores={b: cor_banco(b) for b in piv.columns})
with c2:
    por_mod = vivo.groupby("modulo")["valor_a_receber"].sum()
    g.funil([(nome_modalidade(m, True) + " · total", v) for m, v in por_mod.items()] +
            [("Em contas CAIXA", cx["valor_a_receber"].sum()), ("Chega em 90 dias", prox["valor_a_receber"].sum())],
            chave="rec_funil", titulo="Do total ao que chega logo", altura=360)

secao("Sazonalidade dos créditos", "Em que meses as ordens bancárias das Transferências Especiais caem (todos os anos).")
sz = d["mart_sazonalidade"]
if not sz.empty:
    g.barras(sz, "mes_nome", {"valor_pago": "Pago"}, chave="rec_saz", altura=300)
    top = sz.nlargest(3, "valor_pago")
    leitura("Leitura", [f"Os meses de pico são {', '.join(top['mes_nome'])}: juntos, {q.pct(top['pct_do_total'].sum())} dos "
                        "créditos. Antecipe a abordagem dos entes antes desses meses."])

secao("Agir antes do crédito", "Entes com crédito previsto em conta do concorrente nos próximos 90 dias.")
alvo = conc_prox.groupby(["cnpj_ente", "nome_ente", "uf", "grupo_banco"], as_index=False).agg(
    valor_a_receber=("valor_a_receber", "sum"), instrumentos=("id_instrumento", "nunique"),
    dias_para_credito=("dias_para_credito", "min")).sort_values("valor_a_receber", ascending=False)
g.grade(alvo, chave="rec_alvos")
leitura("Como usar", ["A conta destes instrumentos já está aberta no concorrente: o crédito vai cair lá. A conversa é "
                      "sobre os próximos planos e convênios — e sobre o relacionamento do ente com a CAIXA."])
with st.expander("Todos os créditos previstos"):
    g.grade(ar.sort_values("valor_a_receber", ascending=False).head(5000), chave="rec_todos")
baixar("dinheiro_a_receber", {"a_receber": ar, "agir_antes": alvo, "sazonalidade": sz})
