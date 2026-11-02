import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.motores_gestor import ESTAGIOS, MESES  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, mapa_coropletico, pagina, secao  # noqa: E402

TEND_CORES = {"tende à CAIXA": "#005CA9", "indefinida": "#F39200", "tende ao concorrente": "#D1495B"}
ctx = pagina("Janela de escolha do banco",
             "O momento decisivo da custódia: quando o ente indica o banco da conta. Aqui estão os repasses que estão "
             "nesse momento agora, a tendência de cada um e quando as próximas escolhas acontecem (regra JAN-01).")
d = ctx.d
jn = ctx.f("mart_janela_escolha", anos=False)
if jn.empty:
    st.info("Nenhum repasse na janela de escolha com os filtros atuais (ou a tabela ainda não foi gerada: ela nasce "
            "na carga diária).")
    st.stop()

aberto = jn[jn["estagio"] == ESTAGIOS[0]]
conc = jn[jn["tendencia"] == "tende ao concorrente"]
cx = jn[jn["tendencia"] == "tende à CAIXA"]
cartoes([
    {"rotulo": "Repasses na janela", "valor": f"{len(jn):,}".replace(",", "."),
     "sub": f"{jn['cnpj_ente'].nunique():,} entes · {q.brl(jn['valor'].sum())}".replace(",", ".")},
    {"rotulo": "Banco ainda não escolhido", "valor": q.brl(aberto["valor"].sum()), "cor": "#8C1D40",
     "sub": f"{len(aberto):,} repasses — agir agora".replace(",", ".")},
    {"rotulo": "Valor em disputa", "valor": q.brl(jn["valor_em_disputa"].sum()), "cor": "#F39200",
     "sub": "valor × chance de não vir à CAIXA"},
    {"rotulo": "Tendem ao concorrente", "valor": q.brl(conc["valor"].sum()), "cor": "#D1495B",
     "sub": f"{conc['cnpj_ente'].nunique():,} entes".replace(",", ".")},
    {"rotulo": "Tendem à CAIXA (garantir)", "valor": q.brl(cx["valor"].sum()), "cor": "#005CA9"},
])
leitura("Leitura", [f"<b>{e}</b>: {q.brl(gp['valor'].sum())} em {len(gp):,} repasses; {q.brl(gp['valor_em_disputa'].sum())} em disputa."
                    .replace(",", ".") for e, gp in jn.groupby("estagio", sort=False)])

secao("Matriz de escolha", "Estágio da janela × tendência do ente. Comece pela linha de cima e pela coluna vermelha.")
c1, c2 = st.columns([3, 2])
with c1:
    mt = jn.groupby(["estagio", "tendencia"], as_index=False)["valor"].sum()
    g.heatmap(mt, "tendencia", "estagio", "valor", chave="jan_matriz", formato="brl", altura=360,
              ordem_x=[t for t in TEND_CORES if t in set(mt["tendencia"])],
              ordem_y=[e for e in ESTAGIOS if e in set(mt["estagio"])])
with c2:
    pe = jn.groupby("estagio", as_index=False)[["valor", "valor_em_disputa"]].sum()
    pe = pe.set_index("estagio").reindex([e for e in ESTAGIOS if e in set(pe["estagio"])]).reset_index()
    g.barras(pe, "estagio", {"valor": "Valor", "valor_em_disputa": "Em disputa"}, chave="jan_estagios", horizontal=True,
             empilhado=False, altura=360, cores={"Valor": "#9AA4B1", "Em disputa": "#F39200"})

secao("Onde estão as escolhas", "Cada bolha é um município com repasses na janela (cor = tendência predominante).")
er = d["mart_ente_resumo"]
b = jn.groupby("cnpj_ente", as_index=False).agg(valor=("valor", "sum"),
                                                tendencia=("tendencia", lambda s: s.mode().iat[0]))
b = b.merge(er[["cnpj_ente", "nome_ente", "uf", "cod_ibge", "municipio", "lat", "lon", "part_caixa", "banco_principal"]],
            on="cnpj_ente", how="left")
uf = q.territorio(d, "UF", None, ctx.modulos, None, set(jn["cnpj_ente"]))
mapa_coropletico(uf, q.malha("BR"), "valor", "brl", "Oranges", chave="jan_mapa", altura=520, bolhas=b,
                 cor_bolha="tendencia")

secao("Quando os entes escolhem o banco", "Ciência dos planos (Transferências Especiais) e assinatura dos convênios, por mês.")
cal = q.filtrar(d.get("mart_calendario_escolha", pd.DataFrame()), ctx.modulos, None, None)
if not cal.empty:
    c1, c2 = st.columns([3, 2])
    pm = cal.groupby(["mes", "mes_nome"], as_index=False)[["valor", "valor_caixa"]].sum().sort_values("mes")
    pm["valor_concorrente"] = pm["valor"] - pm["valor_caixa"]
    with c1:
        g.barras(pm, "mes_nome", {"valor_caixa": "Escolheram a CAIXA", "valor_concorrente": "Escolheram outro banco"},
                 chave="jan_cal", altura=320, cores={"Escolheram a CAIXA": "#005CA9", "Escolheram outro banco": "#D1495B"})
    with c2:
        top = pm.nlargest(3, "valor")
        prox = [m for m in top["mes"] if m > pd.Timestamp.today().month] or list(top["mes"])
        leitura("Calendário", [f"Os meses com mais escolhas são <b>{', '.join(top['mes_nome'])}</b> "
                               f"({q.pct(top['valor'].sum() / pm['valor'].sum())} do valor).",
                               f"Próxima janela provável: <b>{MESES[int(min(prox)) - 1]}</b>. Prepare a carteira "
                               "de entes antes desse mês.",
                               "Emendas do próximo ano (LOA) ainda não estão no Transferegov: quando os planos forem "
                               "criados, entram aqui como 'banco ainda não escolhido'."])

secao("Com quem falar", "Parlamentares com mais valor na janela e o histórico deles com a CAIXA.")
pj = jn.dropna(subset=["parlamentar"]).groupby("parlamentar", as_index=False).agg(
    valor=("valor", "sum"), entes=("cnpj_ente", "nunique"), part_caixa_parlamentar=("part_caixa_parlamentar", "first"),
    valor_em_disputa=("valor_em_disputa", "sum")).sort_values("valor_em_disputa", ascending=False)
g.grade(pj.head(300).rename(columns={"parlamentar": "agente"}), chave="jan_parl", altura=300)

secao("Repasses na janela", "Ordenados pelo valor em disputa. Clique para abrir o ente no Assessor.")
f1, f2, f3 = st.columns(3)
est = f1.multiselect("Estágio", [e for e in ESTAGIOS if e in set(jn["estagio"])], placeholder="Todos")
ten = f2.multiselect("Tendência", list(TEND_CORES), placeholder="Todas")
tip = f3.multiselect("Tipo de ente", sorted(jn["tipo_ente"].dropna().unique()), placeholder="Todos")
v = jn
if est:
    v = v[v["estagio"].isin(est)]
if ten:
    v = v[v["tendencia"].isin(ten)]
if tip:
    v = v[v["tipo_ente"].isin(tip)]
cols = ["estagio", "nome_ente", "uf", "modulo", "valor", "banco_indicado", "tendencia", "prob_caixa", "valor_em_disputa",
        "parlamentar", "situacao", "situacao_conta", "acao", "codigo", "cnpj_ente"]
sel = g.grade(v[cols], chave="jan_lista", selecao=True, altura=460)
if sel and sel.get("cnpj_ente"):
    ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
            {ui.ENTE: sel["cnpj_ente"]}, chave="jan_abrir")
baixar("janela_de_escolha", {"janela": v, "parlamentares": pj, "calendario": cal})
