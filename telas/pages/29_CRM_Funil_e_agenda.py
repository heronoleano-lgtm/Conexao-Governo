import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import acesso  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.ui import cartoes, leitura, pagina, secao, tabela  # noqa: E402
from custodia.ui import AUREA_INV  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("CRM · Funil e agenda",
             "Quem abordar primeiro (prioridade CRM-01), em que etapa está cada ente e o que vence na agenda da equipe.")
d = ctx.d
pr = d.get("crm_prioridade", pd.DataFrame())
if pr is None or pr.empty:
    st.info("A prioridade do CRM nasce na carga diária, com os dados do Portal da Transparência.")
    st.stop()
if ctx.ufs:
    pr = pr[pr["uf"].isin(ctx.ufs)]
cart = acesso.carteira()
base = pr.merge(cart[["cnpj_ente", "status", "responsavel"]], on="cnpj_ente", how="left") if not cart.empty else \
    pr.assign(status=None, responsavel=None)
base["status"] = base["status"].fillna("não abordado")
ag = acesso.agenda()
hoje = date.today().isoformat()
semana = (date.today() + timedelta(days=7)).isoformat()
atras = ag[ag["data_proxima"] < hoje] if not ag.empty else ag
prox7 = ag[(ag["data_proxima"] >= hoje) & (ag["data_proxima"] <= semana)] if not ag.empty else ag

cartoes([
    {"rotulo": "Entes priorizados", "valor": f"{int((base['prioridade'] > 0).sum()):,}".replace(",", "."),
     "sub": f"{int((base['prioridade'] >= 70).sum())} com prioridade ≥ 70"},
    {"rotulo": "Ainda não abordados (prioridade ≥ 70)",
     "valor": int(((base["prioridade"] >= 70) & (base["status"] == "não abordado")).sum()), "cor": "#F39200"},
    {"rotulo": "Em negociação", "valor": int(base["status"].isin(["abordado", "proposta enviada"]).sum()),
     "sub": "abordados + proposta enviada", "cor": "#005CA9"},
    {"rotulo": "Conquistados", "valor": int((base["status"] == "conquistado").sum()), "cor": "#00A19A"},
    {"rotulo": "Ações atrasadas", "valor": int(len(atras)), "cor": "#D1495B"},
    {"rotulo": "Ações nos próximos 7 dias", "valor": int(len(prox7))},
])

c1, c2 = st.columns(AUREA_INV)
with c1:
    secao("Funil", "Entes por etapa e potencial de custódia envolvido.")
    etapas = [s for s in acesso.STATUS_CARTEIRA if s != "perdido"]
    g.funil([(f"{s} · {int((base['status'] == s).sum())}", float(base.loc[base["status"] == s, "potencial_custodia"].sum()))
             for s in etapas], chave="crm_funil", altura=330)
    perdidos = base[base["status"] == "perdido"]
    if len(perdidos):
        st.caption(f"Perdidos: {len(perdidos)} entes ({q.brl(perdidos['potencial_custodia'].sum())} de potencial).")
with c2:
    secao("Agenda da equipe", "Próxima ação de cada ente (a da atividade mais recente).")
    if ag.empty:
        st.caption("Nenhuma ação agendada. Registre atividades na Visão 360 do ente.")
    else:
        nomes = base.set_index("cnpj_ente")["nome_ente"]
        v = ag.assign(nome_ente=ag["cnpj_ente"].map(nomes),
                      status=ag["data_proxima"].map(lambda x: "atrasada" if x < hoje else ("esta semana" if x <= semana
                                                                                          else "agendada")))
        tabela(v[["data_proxima", "status", "nome_ente", "proxima_acao", "responsavel", "cnpj_ente"]], altura=330)

secao("Lista priorizada", "Ordenada pela prioridade CRM-01. Clique numa linha para abrir a Visão 360.")
f1, f2, f3 = st.columns(3)
sts = f1.multiselect("Etapa", list(acesso.STATUS_CARTEIRA), default=["não abordado", "abordado", "proposta enviada"])
resp = f2.multiselect("Responsável", sorted(base["responsavel"].dropna().unique()), placeholder="Todos")
minimo = f3.slider("Prioridade mínima", 0, 100, 40)
v = base[base["prioridade"] >= minimo]
if sts:
    v = v[v["status"].isin(sts)]
if resp:
    v = v[v["responsavel"].isin(resp)]
leitura("Leitura", [
    f"<b>{len(v)}</b> entes no filtro, com {q.brl(v['potencial_custodia'].sum())} de potencial de custódia e "
    f"{q.brl(v['sem_banco_12m'].sum())} recebidos em 12 meses sem banco conhecido.",
    f"<b>{int(v['alerta_conformidade'].sum())}</b> têm alerta de conformidade (prioridade zerada até análise)."
    if v["alerta_conformidade"].any() else ""])
cols = ["prioridade", "nome_ente", "uf", "status", "responsavel", "proxima_acao", "potencial_custodia", "sem_banco_12m",
        "valor_em_disputa", "bolsa_familia_mes", "emendas_12m", "alerta_conformidade", "cnpj_ente"]
sel = g.grade(v[cols].head(2000), chave="crm_lista", selecao=True, altura=480)
if sel and sel.get("cnpj_ente"):
    ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} na Visão 360", ui.TELA_ENTE, ("ente_visao", "360 · CRM"),
             {ui.ENTE: sel["cnpj_ente"]}, chave="crm_abrir")

secao("Últimas atividades da equipe")
at = acesso.atividades()
if at.empty:
    st.caption("Nenhuma atividade registrada ainda.")
else:
    tabela(at.head(50).assign(nome_ente=lambda x: x["cnpj_ente"].map(base.set_index("cnpj_ente")["nome_ente"]))[
        ["data_atividade", "nome_ente", "atividade", "resultado", "proxima_acao", "data_proxima", "registrado_por"]])
