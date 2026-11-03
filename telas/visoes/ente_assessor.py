import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.motores_gestor import DIMENSOES  # noqa: E402
from custodia.semantica import cor_banco, nome_modalidade  # noqa: E402
from custodia.ui import escolher, baixar, cartoes, leitura, pagina, secao  # noqa: E402
from custodia.ui import AUREA_INV  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("Assessor do ente",
             "Diagnóstico, recomendações, argumentos e riscos de um município ou estado, gerados pelas regras do "
             "painel — o roteiro da visita.", filtros=False)
d = ctx.d
er = d["mart_ente_resumo"].sort_values("valor", ascending=False)
if er.empty:
    st.info("Sem entes carregados.")
    st.stop()
er = er.assign(_rot=er["nome_ente"].fillna("?") + " · " + er["uf"].fillna("?"))
padrao = st.session_state.get("ente_cnpj")
cnpj = escolher("Ente", er, "cnpj_ente", "_rot", "assessor", pedido=padrao)
if cnpj is None:
    st.stop()
st.session_state["ente_cnpj"] = cnpj
a = q.assessor(d, cnpj)
e, dims, pri = a["ente"], a["dimensoes"], a["priorizacao"]

cartoes([
    {"rotulo": "Valor contratado", "valor": q.brl(e.get("valor")), "sub": f"{e.get('porte', '')} · {e.get('esfera', '')}"},
    {"rotulo": "Participação CAIXA", "valor": q.pct(e.get("part_caixa")), "cor": "#005CA9",
     "sub": f"banco principal: {e.get('banco_principal', '—')}"},
    ui.cartao_saldo("Custódia CAIXA", e.get("saldo_caixa") or 0, e.get("saldo_caixa_estimado"),
                    parado_em=q.parada_saldo(d), sub=f"concorrente: {q.brl(e.get('saldo_concorrente'))}"),
    {"rotulo": "Potencial de custódia", "estimado": True, "valor": q.brl(e.get("potencial_custodia")), "cor": "#00A19A"},
    {"rotulo": "Prioridade", "valor": pri.get("quadrante", "—"),
     "sub": f"chance de conversão {int(pri['chance_conversao'])}/100" if pri else ""},
])

c1, c2 = st.columns(AUREA_INV)
with c1:
    secao("Radar do ente", "Ente × média dos entes do mesmo porte na UF (0 a 100, regra DIM-01).")
    todos = d["mart_ente_dimensoes"].merge(er[["cnpj_ente", "uf", "porte"]], on="cnpj_ente")
    pares = todos[(todos["uf"] == e.get("uf")) & (todos["porte"] == e.get("porte"))]
    if dims:
        g.radar(list(DIMENSOES.values()), {"Este ente": [dims.get(k, 0) for k in DIMENSOES],
                                           "Pares (média)": [pares[k].mean() if not pares.empty else 0 for k in DIMENSOES]},
                chave="ass_radar", cores={"Este ente": "#005CA9", "Pares (média)": "#F39200"}, altura=380)
    g.gauge(e.get("part_caixa"), "Participação CAIXA", chave="ass_gauge", meta=a["comparacao"].get("part_caixa_pares"))
    st.caption("Ponteiro laranja: participação CAIXA dos pares.")
with c2:
    secao("Recomendações")
    leitura("O que fazer", a["recomendacoes"] or ["Sem ação específica pelas regras: manter o relacionamento."])
    leitura("Argumentos para a conversa", a["argumentos"] or ["—"])

aba1, aba2, aba3, aba4 = st.tabs(["Escolhas de banco", "Dinheiro a receber", "Riscos e ofertas", "Ficha completa"])
with aba1:
    esc = a["escolhas"]
    if esc.empty:
        st.info("Sem instrumentos nas modalidades disputáveis.")
    else:
        x = esc.assign(ano=esc["ano"].astype(str), modalidade=esc["modulo"].map(lambda m: nome_modalidade(m, True)))
        piv = x.pivot_table(index="ano", columns="grupo_banco", values="valor", aggfunc="sum").fillna(0).reset_index()
        g.barras(piv, "ano", {b: b for b in piv.columns if b != "ano"}, chave="ass_esc", altura=320,
                 cores={b: cor_banco(b) for b in piv.columns})
        g.grade(esc.sort_values(["ano", "modulo"]), chave="ass_esc_tab", altura=300)
with aba2:
    g.grade(a["a_receber"], chave="ass_rec", altura=320)
with aba3:
    st.markdown("**Riscos**")
    g.grade(a["riscos"], chave="ass_ris", altura=220)
    st.markdown("**Ofertas**")
    g.grade(a["ofertas"], chave="ass_of", altura=220)
with aba4:
    from custodia import ui
    ui.abrir("Abrir a ficha técnica do ente", ui.TELA_ENTE, ("ente_visao", "Ficha técnica"), {ui.ENTE: cnpj},
             chave="ass_ficha", icone=":material/description:")
baixar(f"assessor_{cnpj}", {"riscos": a["riscos"], "ofertas": a["ofertas"], "a_receber": a["a_receber"],
                            "escolhas": a["escolhas"]})
