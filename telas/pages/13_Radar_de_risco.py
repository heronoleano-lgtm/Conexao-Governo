import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.semantica import SEVERIDADE_CORES  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, mapa_coropletico, pagina, secao  # noqa: E402

ctx = pagina("Radar de risco e relacionamento",
             "Onde a CAIXA pode perder recursos (troca de banco, queda de participação, janela tendendo ao concorrente, "
             "vigência vencendo, saldo saindo) e quem não direciona recursos à CAIXA — com os motivos prováveis.")
d = ctx.d
rd = d["mart_radar"].copy()
if ctx.usuario["perfil"] not in ("gestao", "administrador") and not rd.empty:
    rd = rd[rd["regra"] != "RIS-06"]
if ctx.ufs and not rd.empty:
    rd = rd[rd["uf"].isin(ctx.ufs)]
ag = d.get("mart_risco_agentes", pd.DataFrame())
fc = d.get("mart_fora_caixa", pd.DataFrame())
fa = d.get("mart_fora_caixa_agentes", pd.DataFrame())
if ctx.ufs and not fc.empty:
    fc = fc[fc["uf"].isin(ctx.ufs)]
if rd.empty and fc.empty and ag.empty:
    st.info("As tabelas de risco nascem na carga diária. Rode carga_diaria.bat para gerá-las.")
    st.stop()

crit = rd[rd["severidade"] == "Crítico"] if not rd.empty else rd
cartoes([
    {"rotulo": "Valor em risco", "valor": q.brl(rd["valor_em_risco"].sum() if not rd.empty else 0), "cor": "#D1495B",
     "sub": f"{rd['cnpj_ente'].nunique() if not rd.empty else 0:,} entes".replace(",", ".")},
    {"rotulo": "Sinais críticos", "valor": len(crit), "cor": "#D1495B",
     "sub": q.brl(crit["valor_em_risco"].sum() if not crit.empty else 0)},
    {"rotulo": "Parlamentares e órgãos migrando", "valor": len(ag), "cor": "#8C1D40",
     "sub": q.brl(ag["valor_em_risco"].sum() if not ag.empty else 0)},
    {"rotulo": "Entes fora da CAIXA", "valor": f"{len(fc):,}".replace(",", "."), "cor": "#F39200",
     "sub": q.brl(fc["valor_recente"].sum() if not fc.empty else 0) + " em 3 anos"},
    {"rotulo": "Agentes fora da CAIXA", "valor": len(fa), "cor": "#F39200", "sub": "parlamentares e órgãos"},
])

aba1, aba2, aba3 = st.tabs(["Risco de perder recursos", "Parlamentares e órgãos migrando",
                            "Quem não direciona à CAIXA — e por quê"])
with aba1:
    if rd.empty:
        st.success("Nenhum sinal de risco por ente com os filtros atuais.")
    else:
        por = rd.groupby("risco", as_index=False).agg(valor_em_risco=("valor_em_risco", "sum"),
                                                      entes=("cnpj_ente", "nunique")).sort_values("valor_em_risco", ascending=False)
        leitura("Leitura", [f"<b>{r.risco}</b>: {q.brl(r.valor_em_risco)} em {r.entes} entes." for r in por.head(5).itertuples()])
        c1, c2 = st.columns([3, 2])
        with c1:
            pe = rd.groupby("cnpj_ente", as_index=False).agg(
                valor=("valor_em_risco", "sum"),
                severidade=("severidade", lambda s: "Crítico" if (s == "Crítico").any() else "Atenção"))
            b = pe.merge(d["mart_ente_resumo"][["cnpj_ente", "nome_ente", "uf", "cod_ibge", "municipio", "lat", "lon",
                                                "part_caixa", "banco_principal"]], on="cnpj_ente", how="left")
            uf = q.territorio(d, "UF", None, ctx.modulos, None, set(pe["cnpj_ente"]))
            mapa_coropletico(uf, q.malha("BR"), "valor_caixa", "brl", "Blues", chave="radar_mapa", altura=480,
                             bolhas=b, cor_bolha="severidade")
        with c2:
            g.barras(por, "risco", {"valor_em_risco": "Valor em risco"}, chave="radar_tipos", horizontal=True,
                     altura=480, cores={"Valor em risco": "#D1495B"})
        f1, f2 = st.columns(2)
        tipos = f1.multiselect("Risco", sorted(rd["risco"].unique()), placeholder="Todos")
        sevs = f2.multiselect("Severidade", ["Crítico", "Atenção"], placeholder="Todas")
        v = rd
        if tipos:
            v = v[v["risco"].isin(tipos)]
        if sevs:
            v = v[v["severidade"].isin(sevs)]
        sel = g.grade(v.sort_values("valor_em_risco", ascending=False), chave="radar_lista", selecao=True)
        if sel and sel.get("cnpj_ente"):
            ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
                    {ui.ENTE: sel["cnpj_ente"]}, chave="radar_abrir")
with aba2:
    if ag.empty:
        st.success("Nenhum parlamentar ou órgão com queda relevante de participação CAIXA.")
    else:
        leitura("Por que importa", ["Quando um autor de emendas ou um ministério passa a levar menos à CAIXA, todos os "
                                    "entes que ele atende ficam em risco: é uma conversa de relacionamento institucional."])
        g.barras(ag.head(15), "agente", {"valor_em_risco": "Valor fora da CAIXA no último ano"}, chave="ag_barras",
                 horizontal=True, altura=420, cores={"Valor fora da CAIXA no último ano": "#8C1D40"})
        g.grade(ag, chave="ag_lista")
with aba3:
    if fc.empty and fa.empty:
        st.success("Nenhum ente ou agente relevante fora da CAIXA pelas regras FOR-01 e FOR-02.")
    else:
        if not fc.empty:
            mot = fc["motivos"].str.split("; ").explode().str.replace(r" \(.*?\)| há \d+ anos| leva \d+%.*| opera \d+%.*", "",
                                                                      regex=True)
            mc = mot.value_counts().rename_axis("motivo").reset_index(name="entes")
            c1, c2 = st.columns([2, 3])
            with c1:
                g.barras(mc, "motivo", {"entes": "Entes"}, chave="for_motivos", formato="int", horizontal=True,
                         altura=320, cores={"Entes": "#F39200"}, titulo="Motivos mais frequentes")
            with c2:
                leitura("Como agir", ["Cada ente vem com os motivos que os dados sugerem e a ação correspondente. "
                                      "Valide o motivo na visita antes de apresentar a proposta.",
                                      "Motivos ligados a parlamentar ou ministério se resolvem no relacionamento "
                                      "institucional; os ligados a fornecedores e Fundo a Fundo, com produto."])
            sel = g.grade(fc, chave="for_lista", selecao=True, altura=420)
            if sel and sel.get("cnpj_ente"):
                ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
                        {ui.ENTE: sel["cnpj_ente"]}, chave="for_abrir")
        if not fa.empty:
            secao("Parlamentares e órgãos com pouca CAIXA")
            g.grade(fa, chave="for_agentes", altura=320)
baixar("radar_de_risco", {"riscos_entes": rd, "riscos_agentes": ag, "fora_da_caixa": fc, "agentes_fora": fa})
