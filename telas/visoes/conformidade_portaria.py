import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import streamlit as st  # noqa: E402

from custodia import config  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia.ui import baixar, cartoes, pagina, ranking, tabela  # noqa: E402

ctx = pagina("Conformidade",
             "Saídas da conta da transferência para outra conta do próprio ente depois da Portaria Conjunta MF/MGI "
             "15/2025, que veda a transferência para outras contas correntes. Uso interno: risco, não prospecção.",
             filtros=False)
if ctx.usuario["perfil"] not in ("gestao", "administrador"):
    st.info("Esta tela é restrita aos perfis gestão e administrador.")
    st.stop()
d = ctx.d
corte = config.carregar().get("motores", {}).get("data_portaria_15_2025", "2025-07-28")
cf = d["mart_conformidade"]
cartoes([
    {"rotulo": "Entes", "valor": cf["cnpj_ente"].nunique() if not cf.empty else 0},
    {"rotulo": "Lançamentos", "valor": int(cf["lancamentos"].sum()) if not cf.empty else 0},
    {"rotulo": "Valor", "valor": q.brl(cf["valor"].sum() if not cf.empty else 0), "cor": "#D1495B"},
])
if not cf.empty and "uf" in cf:
    ranking(cf.groupby("uf", as_index=False)["valor"].sum().rename(columns={"uf": "nome"}), "valor", "brl", n=12,
            titulo="Valor por UF")
tabela(cf)
st.caption(f"Data de corte: {corte}. O favorecido é o próprio ente quando o CNPJ do favorecido é igual ao do ente "
           "(ou, sem CNPJ, quando o nome é igual): confira cada caso antes de qualquer conclusão. A leitura jurídica "
           "deve ser validada pelo jurídico e pela conformidade da CAIXA.")
if not cf.empty:
    baixar("conformidade", {"conformidade": cf})
