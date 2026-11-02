import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.semantica import CLASSE_CORES, cor_banco, nome_modalidade  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, rosca, secao, tabela  # noqa: E402

ctx = pagina("Permanência e rentabilidade",
             "Quanto tempo o dinheiro fica na conta, que parte é estável e quanto vale a custódia por ano. "
             "Base: saldo de hoje e saídas dos últimos 12 meses (regras PERM-01 a PERM-04).")
d = ctx.d
pm = ctx.f("mart_permanencia", anos=False)
if pm.empty:
    st.info("Sem saldos carregados.")
    st.stop()
cx, conc = pm[pm["grupo_banco"] == "CAIXA"], pm[pm["grupo_banco"] != "CAIXA"]
from custodia.motores_gestor import MEDIDO, giro_dias  # noqa: E402


def pond(x):
    """Permanência média = saldo ÷ saídas anuais (giro), só no que foi medido. O prazo padrão (regra PERM-01) é
    premissa e não entra: misturá-lo fazia grupos diferentes aparecerem com a mesma média (180 dias)."""
    return giro_dias(x)


def medido(x):
    return x["base_permanencia"].astype(str).str.startswith(MEDIDO)


def cobertura(x):
    return x.loc[medido(x), "saldo"].sum() / x["saldo"].sum() if x["saldo"].sum() > 0 else 0.0


def dias_txt(v):
    return "não medido" if v != v else f"{v:,.0f} dias".replace(",", ".")
cartoes([
    ui.cartao_saldo_de("Custódia CAIXA", ctx.f("fato_conta", anos=False).pipe(lambda c: c[c["grupo_banco"] == "CAIXA"]),
                       sub=f"{cx['cnpj_ente'].nunique():,} entes com saldo publicado".replace(",", ".")),
    {"rotulo": "Valor econômico CAIXA / ano", "estimado": True, "valor": q.brl(cx["valor_economico_ano"].sum()), "cor": "#00A19A",
     "ajuda": "Saldo × taxa × fração (regra PERM-03)"},
    {"rotulo": "Permanência média CAIXA (medida)", "valor": dias_txt(pond(cx)),
     "sub": f"medida em {q.pct(cobertura(cx))} do saldo CAIXA",
     "ajuda": "Saldo ÷ saídas dos 12 meses × 365, só onde o extrato mede (inclui contas sem saída no ano). O resto "
              "usa o prazo padrão da regra PERM-01 e não entra na média"},
    {"rotulo": "Permanência média no concorrente (medida)", "valor": dias_txt(pond(conc)),
     "sub": f"medida em {q.pct(cobertura(conc))} do saldo", "cor": "#F39200"},
    {"rotulo": "Saldo estável na CAIXA", "valor": q.pct(cx.loc[cx["classe_saldo"] == "Estável", "saldo"].sum() / max(cx["saldo"].sum(), 1)),
     "sub": "fica 1 ano ou mais"},
    {"rotulo": "Valor econômico no concorrente / ano", "estimado": True, "valor": q.brl(conc["valor_economico_ano"].sum()), "cor": "#F39200",
     "sub": "o que a CAIXA deixa de ganhar"},
])
estim = pm[~medido(pm)]
if not estim.empty:
    leitura("Como ler", [f"{q.pct(estim['saldo'].sum() / pm['saldo'].sum())} do saldo não tem lançamentos recentes na fonte "
                         "(convênios e contas cujo extrato parou de chegar) e usa o prazo padrão da regra PERM-01."])

secao("Permanência por modalidade e banco", "Dias médios ponderados pelo saldo, só com o que foi medido pelos "
                                             "lançamentos. Grupo sem lançamentos aparece como \"não medido\".")
mb = pm.groupby(["modulo", "grupo_banco"]).apply(lambda x: pd.Series({
    "saldo": x["saldo"].sum(), "dias_permanencia": pond(x), "saldo_medido_pct": cobertura(x),
    "valor_economico_ano": x["valor_economico_ano"].sum()}), include_groups=False).reset_index()
mb["modalidade"] = mb["modulo"].map(lambda m: nome_modalidade(m, True))
c1, c2 = st.columns(2)
with c1:
    piv = mb.pivot_table(index="modalidade", columns="grupo_banco", values="saldo", aggfunc="sum").fillna(0).reset_index()
    g.barras(piv, "modalidade", {b: b for b in piv.columns if b != "modalidade"}, chave="perm_saldo",
             titulo="Saldo por modalidade e banco", cores={b: cor_banco(b) for b in piv.columns})
with c2:
    piv = mb.pivot_table(index="modalidade", columns="grupo_banco", values="dias_permanencia", aggfunc="first",
                         dropna=False).reset_index()
    g.barras(piv, "modalidade", {b: b for b in piv.columns if b != "modalidade"}, chave="perm_dias", formato="int",
             titulo="Permanência média medida (dias)", empilhado=False, cores={b: cor_banco(b) for b in piv.columns})
nao = mb[mb["dias_permanencia"].isna()]
leitura("Como ler a permanência", [
    "Permanência = saldo ÷ saídas do ano × 365, onde o extrato mede. Conta sem saída em 12 meses nas Transferências "
    "Especiais conta como dinheiro parado (o extrato registra todas as saídas). O banco que parou de publicar "
    f"({q.paradas_texto(d) or 'nenhum nesta carga'}) é medido na sua própria janela: saldo e saídas da época do "
    "último extrato. Onde "
    "não há lançamentos (convênios, saúde) ou eles não cobrem as saídas (Fundo a Fundo paga em lote, sem ligar à "
    "conta), o painel não inventa uma média: o grupo aparece como não medido.",
    ("<b>Não medidos:</b> " + "; ".join(f"{r.modalidade} · {r.grupo_banco} ({q.brl(r.saldo)})" for r in nao.itertuples()))
    if not nao.empty else ""])
tabela(mb[["modalidade", "grupo_banco", "saldo", "saldo_medido_pct", "dias_permanencia", "valor_economico_ano"]],
       chave="perm_mb")

secao("Qualidade do saldo", "Estável vale mais que saldo de passagem.")
c1, c2, c3 = st.columns(3)
for col, banco in zip((c1, c2, c3), ["CAIXA", "BB", "BNB"]):
    x = pm[pm["grupo_banco"] == banco]
    if not x.empty:
        with col:
            rosca(x.groupby("classe_saldo")["saldo"].sum(), f"{banco}: saldo por classe", CLASSE_CORES, altura=280)

secao("Concentração do saldo CAIXA", "Quanto do saldo está nos maiores entes (regra PERM-04).")
co = ctx.f("mart_concentracao", anos=False)
co_cx = co[co["grupo_banco"] == "CAIXA"]
if not co_cx.empty:
    co_cx = co_cx.assign(modalidade=co_cx["modulo"].map(lambda m: nome_modalidade(m, True)))
    g.linha_tempo(co_cx[co_cx["posicao"] <= 200].assign(posicao=co_cx["posicao"].astype(str).str.zfill(3)), "posicao",
                  "pct_acumulado", chave="perm_conc", cor_por="modalidade", formato="pct", area=False,
                  titulo="% acumulado do saldo CAIXA pelos maiores entes (1º ao 200º)")
    lim = 0.40
    tops = co_cx[co_cx["posicao"] == 10][["modalidade", "pct_acumulado"]]
    leitura("Concentração", [f"<b>{r.modalidade}</b>: os 10 maiores entes têm {q.pct(r.pct_acumulado)} do saldo CAIXA"
                             + (" — acima do limite de alerta." if r.pct_acumulado > lim else ".") for r in tops.itertuples()])

rend = pm[pm["rendimento"].fillna(0) > 0]
if not rend.empty:
    secao("Rendimento de aplicação dos convênios", "Rendimento acumulado informado nos convênios ativos.")
    rr = rend.groupby("grupo_banco", as_index=False).agg(rendimento=("rendimento", "sum"), saldo=("saldo", "sum"))
    g.barras(rr, "grupo_banco", {"rendimento": "Rendimento acumulado", "saldo": "Saldo"}, chave="perm_rend",
             empilhado=False, altura=300)

secao("Entes por valor econômico")
g.grade(pm.sort_values("valor_economico_ano", ascending=False).head(3000), chave="perm_lista")
baixar("permanencia", {"entes": pm, "resumo": mb})
