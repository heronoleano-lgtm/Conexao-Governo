import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.ui import (baixar, barras_modalidade, cartoes, leitura, mapa_coropletico, pagina, ranking,  # noqa: E402
                         secao, tabela)
from custodia.ui import AUREA  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Transferência secundária · Fundo a Fundo",
             "Entes que autorizam a saída do recurso da conta Fundo a Fundo no BB para uma conta do próprio CNPJ. "
             "O CNPJ do favorecido é aberto na API: a identificação do próprio ente é exata. "
             "A API não informa o banco de destino.")
d = ctx.d
t = d["mart_transferencia_secundaria"].copy()
if ctx.ufs and not t.empty:
    t = t[t["uf"].isin(ctx.ufs)]
if t.empty:
    st.info("Nenhuma transferência para conta do próprio ente nos lançamentos do Fundo a Fundo carregados.")
    st.stop()

cartoes([
    {"rotulo": "Entes que já transferem", "valor": f"{len(t):,}".replace(",", "."), "sub": f"{t['uf'].nunique()} UFs"},
    {"rotulo": "Transferido (histórico)", "valor": q.brl(t["valor_transferido"].sum())},
    {"rotulo": "Transferido em 12 meses", "valor": q.brl(t["valor_12_meses"].sum()), "cor": "#00A19A"},
    {"rotulo": "Saldo FaF hoje nesses entes", "valor": q.brl(t["saldo_faf_hoje"].sum()), "cor": "#F39200",
     "sub": "pode seguir o mesmo caminho"},
    {"rotulo": "Já são clientes CAIXA", "valor": q.pct(t["tem_conta_caixa_outro_modulo"].mean()),
     "sub": "conta CAIXA em outra modalidade"},
])
leitura("Atenção", ["O banco que recebe não vem na API do Fundo a Fundo. Para confirmar que o destino é CAIXA, cruze "
                    "CNPJ do ente + data + valor com a base interna da CAIXA.",
                    "A regra que permite a transferência varia por programa: confirme o normativo antes de orientar o ente."])

er = d.get("mart_ente_resumo", pd.DataFrame())
secao("Onde acontece", "Bolhas: entes que já transferiram (tamanho = valor em 12 meses; cor = já é cliente CAIXA).")
c1, c2 = st.columns(AUREA)
with c1:
    if not er.empty:
        b = t.merge(er[["cnpj_ente", "lat", "lon", "part_caixa", "banco_principal", "potencial_custodia",
                        "acao_recomendada"]], on="cnpj_ente", how="left")
        b = b.assign(valor=b["valor_12_meses"].where(b["valor_12_meses"] > 0, b["valor_transferido"]),
                     cliente=b["tem_conta_caixa_outro_modulo"].map({True: "CAIXA", False: "BB"}))
        uf = q.territorio(d, "UF", None, ["Fundo a Fundo"], None, set(t["cnpj_ente"]))
        mapa_coropletico(uf, q.malha("BR"), "transf_secundaria", "brl", "Greens", chave="mapa_transf_sec",
                         altura=540, bolhas=b, cor_bolha="cliente", tam_bolha="valor")
with c2:
    por_uf = t.groupby("uf", as_index=False)["valor_12_meses"].sum().rename(columns={"uf": "nome"})
    ranking(por_uf, "valor_12_meses", "brl", n=12, titulo="Transferido em 12 meses, por UF")

aba1, aba2, aba3 = st.tabs(["Entes", "Por órgão e programa", "Evolução"])
with aba1:
    f1, f2 = st.columns(2)
    so_cliente = f1.checkbox("Só quem já é cliente CAIXA em outra modalidade", value=False)
    com_saldo = f2.checkbox("Só quem ainda tem saldo Fundo a Fundo no BB", value=False)
    v = t
    if so_cliente:
        v = v[v["tem_conta_caixa_outro_modulo"]]
    if com_saldo:
        v = v[v["saldo_faf_hoje"] > 0]
    tabela(v, altura=460)
    baixar("transferencia_secundaria_faf", {"entes": v})
fl = q.filtrada(d, "fato_fluxo", ["Fundo a Fundo"], None, ctx.ufs or None)
f = fl[fl["proprio_ente"].fillna(False).astype(bool)] if not fl.empty else fl
with aba2:
    if not f.empty and "orgao" in f:
        g = f.groupby(["orgao", "programa"], dropna=False, as_index=False).agg(
            valor=("valor", "sum"), lancamentos=("valor", "size"), entes=("cnpj_ente", "nunique"))
        tabela(g.sort_values("valor", ascending=False))
    else:
        st.info("Sem órgão/programa nos lançamentos carregados.")
with aba3:
    if not f.empty:
        x = f.assign(ano=f["data"].fillna("").str.slice(0, 4), modulo="Fundo a Fundo")
        barras_modalidade(x[x["ano"] != ""], "ano", titulo="Transferido para a conta do próprio ente, por ano", ordenar=False)
