import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia.ui import cartoes, pagina, secao, tabela  # noqa: E402

ctx = pagina("Qualidade e atualização", "Confira aqui antes de levar um número para uma reunião.", filtros=False)
d = ctx.d
meta = d.get("meta", {})
mq = d["mart_qualidade"]
erros = int((mq["status"] == "erro").sum()) if not mq.empty else 0
alertas = int((mq["status"] == "alerta").sum()) if not mq.empty else 0
cartoes([
    {"rotulo": "Dia dos dados", "valor": meta.get("dia", "—")},
    {"rotulo": "Checagens com erro", "valor": erros, "cor": "#D1495B" if erros else "#00A19A"},
    {"rotulo": "Checagens em alerta", "valor": alertas, "cor": "#F39200" if alertas else "#00A19A"},
    {"rotulo": "Tabelas publicadas", "valor": len(meta.get("linhas", {}))},
])

em_dev = [v["nome"] for v in meta.get("modulos", {}).values() if not v.get("ativo")]
em_dev += ["API nova de Discricionárias (1ª entrega em 28/10/2026: só atos preparatórios, sem conta e saldo)"]
st.caption("Em desenvolvimento: " + " · ".join(em_dev))
secao("Atualização na origem")
tabela(pd.DataFrame([{"modulo": k, "data_atualizacao": v} for k, v in meta.get("data_atualizacao", {}).items()]))
secao("Checagens da carga")
ordem = {"erro": 0, "alerta": 1, "ok": 2}
tabela(mq.sort_values("status", key=lambda s: s.map(ordem)) if not mq.empty else mq)
rq = d.get("mart_reconstituicao_qualidade", pd.DataFrame())
if rq is not None and not rq.empty:
    secao("Reconstituição do saldo (regra SAL-01): como a estimativa foi testada",
          "Calibração do rendimento nos bancos que publicam, validação em banco que não entrou na calibração e testes "
          "retroativos (fingir que um banco que publica parou numa data passada e medir o erro da projeção).")
    tabela(rq, chave="rec_qualidade")
c1, c2 = st.columns(2)
with c1:
    secao("Linhas por tabela publicada")
    tabela(pd.DataFrame([{"tabela_publicada": k, "linhas": v} for k, v in meta.get("linhas", {}).items()]))
with c2:
    secao("Histórico gravado (mudanças desta carga)")
    st.json(meta.get("historico", {}))
