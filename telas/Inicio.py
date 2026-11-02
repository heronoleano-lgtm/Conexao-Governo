import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import interacao  # noqa: E402
from custodia.semantica import (BANCO_CORES, CAIXA_AZUL, CAIXA_LARANJA, MODALIDADES, SEGMENTO_CORES,  # noqa: E402
                                nome_modalidade)
from custodia.ui import (baixar, barras_modalidade, cartoes, filtros_ativos, leitura,  # noqa: E402
                         linha_participacao, pagina, ranking, rosca, sankey, secao, tabela)

ctx = pagina("Cockpit executivo · Custódia de recursos federais",
             "Onde está o dinheiro das transferências federais, em que banco, por qual modalidade e onde a CAIXA "
             "pode ampliar a custódia. Use os filtros para recortar os entes; o mapa e todos os números acompanham.",
             filtros=False)
d = ctx.d
er = d.get("mart_ente_resumo", pd.DataFrame())
if er is None or er.empty:
    st.info("O resumo por ente ainda não foi gerado. Rode a carga diária.")
    st.stop()

# ---------------------------------------------------------------- filtros dos entes
with st.expander("🔎  Filtros dos entes", expanded=True):
    f1, f2, f3, f4 = st.columns(4)
    mods = f1.multiselect("Modalidade", list(MODALIDADES), default=list(MODALIDADES), format_func=nome_modalidade)
    bancos = f2.multiselect("Banco principal do ente", sorted(er["banco_principal"].dropna().unique()),
                            placeholder="Todos")
    segs = f3.multiselect("Segmento", sorted(er["segmento"].dropna().unique()), placeholder="Todos")
    ufs = f4.multiselect("UF", sorted(er["uf"].dropna().unique()), placeholder="Todas")
    g1, g2, g3, g4 = st.columns(4)
    tipos_todos = sorted(er["tipo_ente"].dropna().unique()) if "tipo_ente" in er else []
    publicos = [t for t in tipos_todos if "sociedade civil" not in t and "Empresa" not in t]
    tipos = g1.multiselect("Tipo de ente", tipos_todos, default=publicos, placeholder="Todos")
    esferas = []
    portes = g2.multiselect("Porte", sorted(er["porte"].dropna().unique()), placeholder="Todos")
    acoes = g3.multiselect("Ação recomendada", sorted(er["acao_recomendada"].dropna().unique()), placeholder="Todas")
    metrica = g4.selectbox("Ordenar estados por", list(q.METRICAS), index=0)

# cliques nos gráficos desta tela (UF, segmento, banco, porte) somam-se aos filtros acima
ex = interacao.extras()
ufs_clique = list(st.session_state.get("f_uf") or [])
filtros_ativos([], [], ufs_clique, {k: v for k, v in ex.items() if k in ("segmento", "banco_principal", "porte")})
ufs = ufs or ufs_clique
segs = segs or ex.get("segmento", [])
bancos = bancos or ex.get("banco_principal", [])
portes = portes or ex.get("porte", [])
entes = q.filtrar_entes(er, mods, bancos, segs, esferas, portes, acoes, ufs)
if tipos and "tipo_ente" in entes:
    entes = entes[entes["tipo_ente"].isin(tipos)]
cod = entes["cod_ibge"].fillna("").astype(str)
n_mun = cod[cod.str.len() == 7].nunique()
if entes.empty:
    st.warning("Nenhum ente com esses filtros.")
    st.stop()
cnpjs = set(entes["cnpj_ente"])
uf_df = q.territorio(d, "UF", None, mods, None, cnpjs)

# ---------------------------------------------------------------- indicadores
v_tot, v_cx = uf_df["valor"].sum(), uf_df["valor_caixa"].sum()
cartoes([
    {"rotulo": "Municípios no recorte", "valor": f"{n_mun:,}".replace(",", "."),
     "sub": f"de 5.570 · {entes['uf'].nunique()} UFs · {len(entes):,} CNPJs".replace(",", "."),
     "ajuda": "Um município tem vários CNPJs (prefeitura, fundos, secretarias); aqui conta cada município uma vez"},
    {"rotulo": "Valor contratado", "valor": q.brl(entes["valor_filtro"].sum()), "sub": "modalidades selecionadas",
     "ajuda": "Valor pactuado dos instrumentos contratados (planos com ciência, convênios assinados, planos FaF "
              "autorizados), pago ou não. Propostas sem assinatura e planos em elaboração ficam em \"previsto\"; "
              "anulados, cancelados, rescindidos e impedidos ficam fora (veja Qualidade e auditoria)."},
    {"rotulo": "Participação CAIXA", "valor": q.pct(v_cx / v_tot) if v_tot else "—",
     "sub": f"{q.brl(v_cx)} na CAIXA", "cor": CAIXA_AZUL},
    ui.cartao_saldo("Custódia CAIXA (saldo)", entes["saldo_caixa"].sum(),
                    entes["saldo_caixa_estimado"].sum() if "saldo_caixa_estimado" in entes else None,
                    parado_em=q.parada_saldo(d)),
    ui.cartao_saldo("Saldo no concorrente", entes["saldo_concorrente"].sum(),
                    entes["saldo_concorrente_estimado"].sum() if "saldo_concorrente_estimado" in entes else None,
                    cor=CAIXA_LARANJA, sub="custódia a disputar"),
    {"rotulo": "Potencial de custódia", "estimado": True, "valor": q.brl(entes["potencial_custodia"].sum()), "cor": "#00A19A",
     "sub": f"resultado estimado {q.brl(entes['resultado_estimado_ano'].sum())}/ano"},
    {"rotulo": "Transf. secundária FaF", "valor": q.brl(entes["transf_secundaria"].sum()), "cor": "#00A19A",
     "sub": "BB → conta do ente, 12 meses"},
])

# ---------------------------------------------------------------- onde está o dinheiro (o mapa fica em Mapa e território)
secao("Onde está o dinheiro", "Estados ordenados pela métrica escolhida. O mapa interativo, com municípios e entes, "
                              "fica em Mapa e território.")
coluna, escala, formato = q.METRICAS[metrica]
c_rank, c_lado = st.columns([3, 2])
with c_rank:
    ranking(uf_df, coluna, formato, n=27, titulo=f"{metrica} por estado", filtro="uf", valores="uf",
            chave="ck_rank_uf")
    if hasattr(st, "page_link"):
        st.page_link("pages/02_Mapa_da_custodia.py", label="Abrir o mapa (Mapa e território)", icon=":material/map:")
with c_lado:
    por_banco = uf_df[["valor_caixa", "valor_concorrente"]].sum().rename({"valor_caixa": "CAIXA",
                                                                          "valor_concorrente": "Concorrentes"})
    rosca(por_banco, "Valor por banco da conta", {"CAIXA": CAIXA_AZUL, "Concorrentes": BANCO_CORES["BB"]}, altura=280)
    por_mod = pd.Series({nome_modalidade(m, True): entes[q.MODALIDADE_COLUNA[m]].sum() for m in mods})
    rosca(por_mod, "Valor por modalidade", {v["curto"]: v["cor"] for v in MODALIDADES.values()}, altura=280)
    seg = entes.groupby("segmento")["cnpj_ente"].count()
    rosca(seg, "Entes por segmento (clique para filtrar)", SEGMENTO_CORES, altura=280, chave="ck_seg",
          filtro="segmento")
    bp = entes.groupby("banco_principal")["valor_filtro"].sum()
    rosca(bp, "Banco principal dos entes (clique para filtrar)", {b: BANCO_CORES.get(b) for b in bp.index},
          altura=280, chave="ck_banco", filtro="banco_principal")

leitura("O que este recorte mostra", q.leituras(d, entes, uf_df, mods))

# ---------------------------------------------------------------- movimento por modalidade
secao("Movimento do dinheiro por modalidade",
      "De qual modalidade vem, em que banco fica a conta e para onde sai (pagamentos e transferências).")
a1, a2, a3 = st.tabs(["Fluxo modalidade → banco → destino", "Por UF", "Ao longo dos anos"])
instr = q.filtrada(d, "fato_instrumento", mods)
with a1:
    sankey(q.sankey_modalidade(d, mods, cnpjs), altura=520)
    st.caption("A etapa \"conta → quem recebe\" usa os lançamentos bancários das Transferências Especiais e do Fundo a "
               "Fundo. No Fundo a Fundo o banco de quem recebe não é informado pela API.")
with a2:
    um = d.get("mart_uf_modalidade", pd.DataFrame())
    um = um[um["modulo"].isin(mods)] if not um.empty else um
    if ufs and not um.empty:
        um = um[um["uf"].isin(ufs)]
    b1, b2 = st.columns(2)
    with b1:
        barras_modalidade(um, "uf", titulo="Valor por UF e modalidade")
    with b2:
        barras_modalidade(um[um["grupo_banco"] != "(sem banco)"] if not um.empty else um, "uf", cor_por="grupo_banco",
                          titulo="Valor por UF e banco da conta")
with a3:
    i2 = instr[instr["cnpj_ente"].isin(cnpjs)]
    b1, b2 = st.columns(2)
    with b1:
        barras_modalidade(i2.assign(ano=i2["ano"].astype("Int64").astype(str)), "ano", titulo="Valor por ano e modalidade", ordenar=False)
    with b2:
        linha_participacao(q.serie_participacao_ano(i2))

# ---------------------------------------------------------------- onde agir
secao("Onde agir primeiro", "Estados e entes com mais custódia a disputar no recorte.")
r1, r2 = st.columns(2)
with r1:
    ranking(uf_df, "valor_concorrente", "brl", n=12, titulo="UFs com mais valor no concorrente", filtro="uf",
            valores="uf", chave="ck_rank_conc")
with r2:
    top = entes.sort_values("potencial_custodia", ascending=False).head(12)
    ranking(top, "potencial_custodia", "brl", n=12, titulo="Entes com maior potencial de custódia", rotulo="nome_ente")

with st.expander("Lista de entes do recorte", expanded=False):
    cols = ["nome_ente", "uf", "esfera", "porte", "segmento", "banco_principal", "valor_filtro", "part_caixa",
            "saldo_caixa", "saldo_concorrente", "potencial_custodia", "transf_secundaria", "acao_recomendada", "cnpj_ente"]
    lista = entes.sort_values("potencial_custodia", ascending=False)[[c for c in cols if c in entes]]
    tabela(lista, altura=420, chave="ck_lista")
    baixar("entes_do_recorte", {"entes": lista})
