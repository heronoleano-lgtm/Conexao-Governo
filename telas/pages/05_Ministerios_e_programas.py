import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.ui import (baixar, cartoes, dispersao, leitura, pagina, secao, tabela,  # noqa: E402
                         treemap)

ctx = pagina("Ministérios e programas",
             "Quem manda o dinheiro, por qual programa, quanto ainda está parado nas contas e quanto cai na CAIXA.")
d = ctx.d
o = ctx.f("mart_orgaos", anos=False, ufs=False)
if o.empty:
    st.info("Sem dados.")
    st.stop()

por_orgao = o.groupby(["modulo", "orgao"], as_index=False).agg(
    valor=("valor", "sum"), saldo=("saldo", "sum"), entes=("entes", "max"), instrumentos=("instrumentos", "sum"))
cx = o.assign(_cx=o["valor"] * o["part_caixa"].fillna(0)).groupby(["modulo", "orgao"])["_cx"].sum()
por_orgao["part_caixa"] = (cx.values / por_orgao["valor"].replace(0, float("nan"))).astype(float)
por_orgao["saldo_x_repasse"] = por_orgao["saldo"] / por_orgao["valor"].replace(0, float("nan"))

parado = por_orgao.sort_values("saldo", ascending=False).head(1)
cartoes([
    {"rotulo": "Órgãos", "valor": por_orgao["orgao"].nunique(), "sub": f"{o['programa'].nunique()} programas"},
    {"rotulo": "Valor contratado", "valor": q.brl(por_orgao["valor"].sum())},
    {"rotulo": "Saldo parado em contas", "valor": q.brl(por_orgao["saldo"].sum()), "cor": "#F39200",
     "sub": "Fundo a Fundo, convênios ativos e Especiais com saldo publicado"},
    {"rotulo": "Maior saldo parado", "valor": parado["orgao"].iloc[0][:28] if not parado.empty else "—",
     "sub": q.brl(parado["saldo"].iloc[0]) if not parado.empty else "", "cor": "#D1495B"},
])

secao("Mapa dos órgãos", "Tamanho = valor transferido; cor = participação CAIXA (azul) ou concorrente (vermelho).")
treemap(o.assign(modalidade=o["modulo"]), ["modalidade", "orgao", "programa"], "valor", "part_caixa", altura=560)

secao("Dinheiro parado × participação CAIXA",
      "À direita, órgãos que mandam mais; embaixo, os que caem menos na CAIXA. Bolhas maiores = mais saldo parado.")
dispersao(por_orgao.assign(saldo_b=por_orgao["saldo"].clip(lower=1)), "valor", "part_caixa", "saldo_b", "orgao")
def _parado(r):
    if r.saldo_x_repasse <= 1:
        return f"<b>{r.orgao}</b>: {q.pct(r.saldo_x_repasse)} do valor repassado ainda está em conta ({q.brl(r.saldo)})."
    vezes = f"{r.saldo_x_repasse:.1f}".replace(".", ",")
    return (f"<b>{r.orgao}</b>: o saldo em conta ({q.brl(r.saldo)}) equivale a {vezes}× o valor repassado no "
            "período — a conta acumula repasses de anos anteriores e rendimentos.")


leitura("Leitura", [_parado(r) for r in por_orgao.dropna(subset=["saldo_x_repasse"]).sort_values("saldo", ascending=False).head(4).itertuples()])

secao("Por órgão")
tabela(por_orgao.sort_values("valor", ascending=False))
with st.expander("Por programa"):
    tabela(o, altura=460)
baixar("ministerios_programas", {"orgaos": por_orgao, "programas": o})
