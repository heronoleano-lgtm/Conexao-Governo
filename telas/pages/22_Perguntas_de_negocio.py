import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia import regras  # noqa: E402
from custodia.ui import cartoes, leitura, pagina, secao  # noqa: E402

ctx = pagina("Perguntas de negócio",
             "O catálogo de perguntas de um gestor de custódia, onde cada uma é respondida e com quais regras. "
             "Para incluir uma pergunta nova, acrescente em config/perguntas.yaml.", filtros=False)
pg = regras.perguntas()
if pg.empty:
    st.info("Catálogo vazio (config/perguntas.yaml).")
    st.stop()
cont = pg["situacao"].value_counts()
cartoes([
    {"rotulo": "Perguntas", "valor": len(pg), "sub": f"{pg['frente'].nunique()} frentes de negócio"},
    {"rotulo": "Respondidas", "valor": int(cont.get("respondida", 0)), "cor": "#00A19A"},
    {"rotulo": "Parciais", "valor": int(cont.get("parcial", 0)), "cor": "#F39200", "sub": "histórico acumulando ou aproximação"},
    {"rotulo": "Precisam de fonte externa", "valor": int(cont.get("fonte externa", 0)), "cor": "#9AA4B1"},
])
icone = {"respondida": "✅", "parcial": "🟠", "fonte externa": "⚪"}
busca = st.text_input("Buscar pergunta", placeholder="ex.: vigência, parlamentar, saldo")
for frente, gpo in pg.groupby("frente", sort=False):
    if busca:
        gpo = gpo[gpo["pergunta"].str.contains(busca, case=False, na=False)]
    if gpo.empty:
        continue
    secao(frente)
    for r in gpo.itertuples():
        c1, c2 = st.columns([5, 2])
        c1.markdown(f"{icone.get(r.situacao, '•')} {r.pergunta}" + (f"  \n<small>{r.observacao}</small>" if r.observacao else ""),
                    unsafe_allow_html=True)
        if r.tela:
            try:
                c2.page_link(r.tela, label="Ver resposta" + (f" · {r.regras}" if r.regras else ""), icon="➡️")
            except Exception:
                c2.caption(r.tela)
leitura("Fontes externas que destravam as próximas perguntas",
        ["Agências do Banco Central (presença CAIXA × concorrente por município).",
         "LOA e indicações de emendas (Siop / Câmara) para o volume do próximo ano.",
         "Base interna CAIXA: saldo das contas das Transferências Especiais (o extrato parou de chegar ao Transferegov "
         "em 30/04/2025), folha de pagamento e arrecadação dos entes."])
