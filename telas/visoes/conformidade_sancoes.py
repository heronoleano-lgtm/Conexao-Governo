import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao, tabela  # noqa: E402

ctx = pagina("CRM · Conformidade",
             "Cruzamento dos cadastros de sanções do Portal da Transparência (CEIS, CNEP, CEPIM) com quem recebe e com "
             "quem é pago pelas contas de transferência. Os alertas são pontos de atenção: a leitura jurídica e a "
             "decisão cabem à Conformidade da CAIXA.", filtros=False)
d = ctx.d
al = d.get("crm_alertas", pd.DataFrame())
sanc = d.get("crm_sancao", pd.DataFrame())
if (sanc is None or sanc.empty) and (al is None or al.empty):
    st.info("Os cadastros de sanções chegam pela API do Portal na carga diária.")
    st.stop()

REGRAS = {"CON-01": "Fornecedor sancionado pago durante a sanção",
          "CON-02": "Entidade impedida (CEPIM) recebendo recursos federais",
          "CON-03": "Ente da prospecção com sanção vigente"}
cont = al.groupby("regra")["valor"].agg(["size", "sum"]) if not al.empty else pd.DataFrame()
cartoes([{"rotulo": "Registros de sanção no cadastro", "valor": f"{len(sanc):,}".replace(",", "."),
          "sub": " · ".join(f"{k}: {v}" for k, v in sanc["cadastro"].value_counts().items()) if not sanc.empty else ""}] +
        [{"rotulo": nome, "valor": int(cont.loc[r, "size"]) if r in cont.index else 0,
          "sub": q.brl(cont.loc[r, "sum"]) if r in cont.index else "", "cor": "#D1495B" if r != "CON-03" else "#F39200"}
         for r, nome in REGRAS.items()])
if not al.empty:
    cx = al[(al["regra"] == "CON-01") & (al["banco_conta"] == "CAIXA")]
    leitura("Leitura", [
        f"<b>{len(cx)}</b> casos de pagamento a fornecedor sancionado saíram de conta CAIXA "
        f"({q.brl(cx['valor'].sum())}): exposição reputacional e de prevenção à lavagem de dinheiro." if len(cx) else "",
        "Pagamentos a CPF não entram no cruzamento (o documento vem mascarado na fonte)."])

for regra, nome in REGRAS.items():
    x = al[al["regra"] == regra] if not al.empty else pd.DataFrame()
    secao(nome, {"CON-01": "Data do pagamento dentro do período da sanção (CEIS/CNEP).",
                 "CON-02": "Recebimento no Portal depois do início do impedimento.",
                 "CON-03": "Sanção vigente hoje: analisar antes de abordar."}[regra])
    if x.empty:
        st.caption("Nenhum caso.")
    else:
        tabela(x.drop(columns=["regra"]))

secao("Consultar um CNPJ nos cadastros")
alvo = st.text_input("CNPJ (só números)", max_chars=18)
if alvo:
    dig = "".join(ch for ch in alvo if ch.isdigit())
    r = sanc[sanc["cnpj"] == dig] if not sanc.empty else pd.DataFrame()
    if r.empty:
        st.success("Nenhum registro nos cadastros carregados (CEIS, CNEP, CEPIM).")
    else:
        tabela(r)
baixar("conformidade_crm", {"alertas": al, "sancoes": sanc})
