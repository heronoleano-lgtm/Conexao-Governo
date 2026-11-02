import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import acesso  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia import motores_fluxo as mf  # noqa: E402
from custodia.referencias import COD_UF, UF_COD  # noqa: E402
from custodia.ui import (baixar, cartoes, leitura, linha_participacao, mapa_coropletico, pagina, ranking,  # noqa: E402
                         sankey, secao, tabela, treemap)

ctx = pagina("Mapa e território",
             "Do Brasil ao ente: clique num estado (no mapa ou no ranking) para ver os municípios e num município para "
             "ver os entes. Filtre onde a CAIXA é forte ou fraca e veja as oportunidades do CRM no território.")
d = ctx.d
ss = st.session_state
ss.setdefault("terr_uf", None)
ss.setdefault("terr_mun", None)
ss.setdefault("terr_v", 0)   # muda a cada navegação: o mapa novo não herda o clique anterior
FAIXAS = [f for f, _, _ in q.FAIXAS_CAIXA] + [q.SEM_FAIXA]
PADRAO = {"faixas": [], "aplicar_em": "Áreas (estado/município)", "part": (0, 100), "valor_min": 0.0,
          "camada": "Áreas + entes", "tipos": None, "bancos": [], "segs": [], "portes": [], "acoes": [], "esferas": [],
          "prio_min": q.LIMIAR_PRIORIDADE, "etapas": [], "sem_alerta": False}
F = {**PADRAO, **(ss.get("mapa_f") or {})}


def ir(uf_, mun_=None):
    ss["terr_uf"], ss["terr_mun"], ss["terr_v"] = uf_, mun_, ss["terr_v"] + 1


# ---------------------------------------------------------------- controles e trilha
c1, c2, c4 = st.columns([3, 2, 3])
metrica = c1.selectbox("Métrica do mapa", list(q.METRICAS), index=0)
coluna, escala, formato = q.METRICAS[metrica]
ufs_disp = sorted(UF_COD)
escolha_uf = c2.selectbox("Estado", ["Brasil"] + ufs_disp,
                          index=(ufs_disp.index(ss["terr_uf"]) + 1) if ss["terr_uf"] in ufs_disp else 0)
if (escolha_uf if escolha_uf != "Brasil" else None) != ss["terr_uf"]:
    ir(escolha_uf if escolha_uf != "Brasil" else None)
uf = ss["terr_uf"]
trilha = "Brasil" + (f" › {uf}" if uf else "")
with c4:
    st.markdown(f"**Você está em:** {trilha}" + (" › município selecionado" if ss["terr_mun"] else ""))
    if uf and st.button("← Voltar ao Brasil"):
        ir(None)
        st.rerun()

# ---------------------------------------------------------------- filtros (aplicados juntos: a tela não recalcula a cada clique)
er = d.get("mart_ente_resumo")
tem_er = er is not None and not er.empty
with st.expander("🔎  Filtros do mapa · participação CAIXA, entes e CRM", expanded=bool(ss.get("mapa_f"))):
    with st.form("mapa_filtros", border=False):
        a1, a2, a3, a4 = st.columns([3, 2, 2, 2])
        faixas = a1.multiselect("Faixa de participação CAIXA", FAIXAS, default=F["faixas"], placeholder="Todas",
                                help="Mais CAIXA ou menos CAIXA: escolha uma ou mais faixas")
        aplicar_em = a2.radio("Aplicar a faixa em", ["Áreas (estado/município)", "Entes"],
                              index=0 if F["aplicar_em"].startswith("Áreas") else 1,
                              help="Áreas: mostra estados/municípios na faixa. Entes: considera só os entes na faixa.")
        part = a3.slider("Participação CAIXA entre (%)", 0, 100, tuple(F["part"]))
        valor_min = a4.number_input("Valor mínimo da área (R$ mi)", min_value=0.0, value=float(F["valor_min"]),
                                    step=1.0, help="Esconde áreas pequenas (útil para listas de menor participação)")
        b1, b2, b3, b4, b5, b6 = st.columns(6)
        tipos_todos = sorted(er["tipo_ente"].dropna().unique()) if tem_er and "tipo_ente" in er else []
        publicos = [t for t in tipos_todos if "sociedade civil" not in t and "Empresa" not in t]
        tipos = b1.multiselect("Tipo de ente", tipos_todos,
                               default=[t for t in (F["tipos"] if F["tipos"] is not None else publicos) if t in tipos_todos],
                               placeholder="Todos")
        op = lambda c: sorted(er[c].dropna().unique()) if tem_er and c in er else []  # noqa: E731
        bancos = b2.multiselect("Banco principal", op("banco_principal"),
                                default=[x for x in F["bancos"] if x in op("banco_principal")], placeholder="Todos")
        segs = b3.multiselect("Segmento", op("segmento"), default=[x for x in F["segs"] if x in op("segmento")],
                              placeholder="Todos")
        portes = b4.multiselect("Porte", op("porte"), default=[x for x in F["portes"] if x in op("porte")],
                                placeholder="Todos")
        esferas = b5.multiselect("Esfera", op("esfera"), default=[x for x in F["esferas"] if x in op("esfera")],
                                 placeholder="Todas")
        acoes = b6.multiselect("Ação recomendada", op("acao_recomendada"),
                               default=[x for x in F["acoes"] if x in op("acao_recomendada")], placeholder="Todas")
        e1, e2, e3, e4 = st.columns([2, 2, 3, 2])
        camada = e1.selectbox("Camadas do mapa", ["Áreas + entes", "Áreas + oportunidades CRM", "Só áreas", "Só entes",
                                                  "Só oportunidades CRM"],
                              index=["Áreas + entes", "Áreas + oportunidades CRM", "Só áreas", "Só entes",
                                     "Só oportunidades CRM"].index(F["camada"]))
        prio_min = e2.slider("Prioridade CRM mínima", 0, 100, int(F["prio_min"]),
                             help="Nota CRM-01 (0 a 100) para entrar nas oportunidades e indicações")
        etapas = e3.multiselect("Etapa na carteira", list(acesso.STATUS_CARTEIRA), default=F["etapas"],
                                placeholder="Todas")
        sem_alerta = e4.toggle("Ocultar entes com alerta de conformidade", value=F["sem_alerta"])
        x1, x2 = st.columns([1, 1])
        aplicou = x1.form_submit_button("Aplicar filtros", type="primary", use_container_width=True)
        limpou = x2.form_submit_button("Limpar filtros", use_container_width=True)
    if aplicou:
        ss["mapa_f"] = {"faixas": faixas, "aplicar_em": aplicar_em, "part": part, "valor_min": valor_min,
                        "camada": camada, "tipos": tipos, "bancos": bancos, "segs": segs, "portes": portes,
                        "acoes": acoes, "esferas": esferas, "prio_min": prio_min, "etapas": etapas,
                        "sem_alerta": sem_alerta}
        st.rerun()
    if limpou:
        ss.pop("mapa_f", None)
        st.rerun()
F = {**PADRAO, **(ss.get("mapa_f") or {})}
if F["tipos"] is None:
    F["tipos"] = [t for t in (sorted(er["tipo_ente"].dropna().unique()) if tem_er and "tipo_ente" in er else [])
                  if "sociedade civil" not in t and "Empresa" not in t]

# ---------------------------------------------------------------- entes do recorte
cnpjs = None
entes_f = None
if tem_er:
    entes_f = q.filtrar_entes(er, ctx.modulos or None, F["bancos"], F["segs"], F["esferas"], F["portes"], F["acoes"],
                              ctx.ufs or None)
    tipos_todos = sorted(er["tipo_ente"].dropna().unique()) if "tipo_ente" in er else []
    if F["tipos"] and "tipo_ente" in entes_f:
        entes_f = entes_f[entes_f["tipo_ente"].isin(F["tipos"])]
    for col, vals in (ctx.extra or {}).items():          # cliques de outras telas (banco, segmento…)
        if col in entes_f and vals:
            entes_f = entes_f[entes_f[col].astype(str).isin(map(str, vals))]
    if F["aplicar_em"] == "Entes":
        pe = pd.to_numeric(entes_f["part_caixa"], errors="coerce")
        if F["faixas"]:
            entes_f = entes_f[q.faixa_caixa(pe).isin(F["faixas"])]
            pe = pd.to_numeric(entes_f["part_caixa"], errors="coerce")
        if tuple(F["part"]) != (0, 100):
            entes_f = entes_f[pe.between(F["part"][0] / 100, F["part"][1] / 100)]
    filtrado = bool(F["bancos"] or F["segs"] or F["portes"] or F["acoes"] or F["esferas"] or ctx.ufs or ctx.extra
                    or F["aplicar_em"] == "Entes" and (F["faixas"] or tuple(F["part"]) != (0, 100))) or \
        (F["tipos"] and set(F["tipos"]) != set(tipos_todos))
    cnpjs = set(entes_f["cnpj_ente"]) if filtrado else None

nivel = "Município" if uf else "UF"
dados_tudo = q.territorio(d, nivel, uf, ctx.modulos, ctx.anos, cnpjs)
dados = dados_tudo
if F["aplicar_em"].startswith("Áreas"):
    if F["faixas"]:
        dados = dados[dados["faixa_caixa"].isin(F["faixas"])]
    if tuple(F["part"]) != (0, 100):
        dados = dados[pd.to_numeric(dados["part_caixa"], errors="coerce").between(F["part"][0] / 100, F["part"][1] / 100)]
if F["valor_min"]:
    dados = dados[dados["valor"] >= F["valor_min"] * 1e6]
fora = len(dados_tudo) - len(dados)

# ---------------------------------------------------------------- oportunidades do CRM no recorte
pr = d.get("crm_prioridade", pd.DataFrame())
indic = pd.DataFrame()
if pr is not None and not pr.empty:
    indic = pr.copy()
    indic["cod_ibge"] = indic["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True)
    indic = indic[pd.to_numeric(indic["prioridade"], errors="coerce").fillna(0) >= F["prio_min"]]
    if uf:
        indic = indic[indic["uf"] == uf]
    elif ctx.ufs:
        indic = indic[indic["uf"].isin(ctx.ufs)]
    areas = set(dados["codarea"].astype(str))
    chave_area = indic["cod_ibge"] if uf else indic["uf"].map(UF_COD)
    indic = indic[chave_area.isin(areas)]
    if cnpjs is not None:
        indic = indic[indic["cnpj_ente"].isin(cnpjs)]
    if F["sem_alerta"] and "alerta_conformidade" in indic:
        indic = indic[~indic["alerta_conformidade"].fillna(False).astype(bool)]
    cart = acesso.carteira()
    indic = indic.merge(cart[["cnpj_ente", "status", "responsavel"]], on="cnpj_ente", how="left") \
        if not cart.empty else indic.assign(status=None, responsavel=None)
    indic["status"] = indic["status"].fillna("não abordado")
    if F["etapas"]:
        indic = indic[indic["status"].isin(F["etapas"])]
    indic = indic.sort_values(["prioridade", "potencial_custodia"], ascending=False)

# ---------------------------------------------------------------- indicadores
tot_v, tot_cx = dados["valor"].sum(), dados["valor_caixa"].sum()
cards = []
if entes_f is not None and not entes_f.empty:
    rec = entes_f if not uf else entes_f[entes_f["uf"] == uf]
    cod = rec["cod_ibge"].fillna("").astype(str)
    n_mun = cod[cod.str.len() == 7].nunique()
    cards.append({"rotulo": "Municípios no recorte", "valor": f"{n_mun:,}".replace(",", "."),
                  "sub": (f"de 5.570 · {rec['uf'].nunique()} UFs · {len(rec):,} CNPJs" if not uf
                          else f"{len(rec):,} CNPJs em {uf}").replace(",", "."),
                  "ajuda": "Um município tem vários CNPJs (prefeitura, fundos, secretarias); conta cada município uma vez"})
cards += [
    {"rotulo": "Valor com banco definido", "valor": q.brl(tot_v),
     "sub": f"{len(dados)} {'municípios' if uf else 'estados'}" + (f" · {fora} fora do filtro" if fora else "")},
    {"rotulo": "Participação CAIXA", "valor": q.pct(tot_cx / tot_v) if tot_v else "—", "sub": q.brl(tot_cx)},
    ui.cartao_saldo("Saldo na CAIXA", dados["saldo_caixa"].sum(),
                    dados["saldo_caixa_estimado"].sum() if "saldo_caixa_estimado" in dados else None,
                    parado_em=q.parada_saldo(d)),
    ui.cartao_saldo("Saldo no concorrente", dados["saldo_concorrente"].sum(),
                    dados["saldo_concorrente_estimado"].sum() if "saldo_concorrente_estimado" in dados else None,
                    cor="#F39200"),
    {"rotulo": "Potencial de custódia", "estimado": True, "valor": q.brl(dados["potencial"].sum()), "cor": "#00A19A"},
    {"rotulo": f"Oportunidades CRM (≥ {F['prio_min']})", "valor": f"{len(indic):,}".replace(",", "."),
     "sub": f"{q.brl(indic['potencial_custodia'].sum()) if not indic.empty else 'R$ 0'} de potencial", "cor": "#7E5BB5",
     "ajuda": "Entes com prioridade CRM-01 acima do mínimo, dentro das áreas e filtros do mapa"},
    {"rotulo": "Recebido sem banco conhecido", "valor": q.brl(dados["crm_sem_banco"].sum()), "cor": "#F39200",
     "sub": "Portal da Transparência, 12 meses", "ajuda": "Dinheiro da União que chegou à administração pública da área "
                                                          "sem banco identificado nas fontes abertas: a descobrir"},
]
cartoes(cards)

# ---------------------------------------------------------------- mapa + painel lateral
esq, dir_ = st.columns([3, 2])
with esq:
    geo = q.malha(uf if uf else "BR")
    bolhas, cor_b, tam_b = None, "segmento", "valor"
    if "entes" in F["camada"] and entes_f is not None and not entes_f.empty:
        b = entes_f if not uf else entes_f[entes_f["uf"] == uf]
        bolhas = b.assign(valor=b["valor_filtro"] if "valor_filtro" in b else b["valor"])
    elif "oportunidades" in F["camada"] and not indic.empty and tem_er and {"lat", "lon"} <= set(er.columns):
        b = indic.merge(er[[c for c in ("cnpj_ente", "lat", "lon", "municipio") if c in er]], on="cnpj_ente",
                        how="left")
        p = pd.to_numeric(b["prioridade"], errors="coerce")
        b["classe_crm"] = pd.cut(p, [-1, 69.999, 84.999, 101], labels=["Prioridade média", "Prioridade alta",
                                                                       "Prioridade muito alta"]).astype(str)
        bolhas = b.assign(valor=pd.to_numeric(b["potencial_custodia"], errors="coerce").fillna(0)
                          .where(lambda v: v > 0, 1.0), part_caixa=None)
        cor_b = "classe_crm"
    base = dados if not F["camada"].startswith("Só ") or F["camada"] == "Só áreas" else dados.iloc[0:0]
    clicado = mapa_coropletico(base, geo, coluna, formato, escala,
                               chave=f"mapa_{uf or 'BR'}_{coluna}_{F['camada']}_{ss['terr_v']}",
                               altura=600, bolhas=bolhas, cor_bolha=cor_b, tam_bolha=tam_b)
    if clicado:
        if not uf and clicado in COD_UF:
            ir(COD_UF[clicado])
            st.rerun()
        elif clicado.startswith("mun:") and len(clicado) == 11:
            mun = clicado[4:]
            if not uf:
                ir(COD_UF.get(mun[:2]), mun)
                st.rerun()
            elif mun != ss["terr_mun"]:
                ss["terr_mun"] = mun
        elif uf and len(clicado) == 7 and clicado != ss["terr_mun"]:
            ss["terr_mun"] = clicado      # mantém a chave do mapa: só desce para a lista de entes
            st.rerun()
    st.caption(("Azul: CAIXA tem mais da metade do valor. Vermelho: o concorrente lidera. " if formato == "pct" else "")
               + ("Áreas em cinza estão fora do filtro ou sem dados." if fora else ""))


def _descer(valor, nome):
    """Clique no ranking: no Brasil desce para o estado; no estado abre o município."""
    v = str(valor)
    if not uf and v in COD_UF:
        ir(COD_UF[v])
        st.rerun()
    elif uf and len(v) == 7:
        ss["terr_mun"] = v
        st.rerun()


with dir_:
    RANK = {"Métrica do mapa": (coluna, formato, False),
            "Mais valor na CAIXA": ("valor_caixa", "brl", False),
            "Mais valor no concorrente": ("valor_concorrente", "brl", False),
            "Menor participação CAIXA": ("part_caixa", "pct", True),
            "Maior saldo no concorrente": ("saldo_concorrente", "brl", False),
            "Mais oportunidades CRM": ("crm_priorizados", "int", False),
            "Mais recebido sem banco conhecido": ("crm_sem_banco", "brl", False)}
    tipo_rank = st.selectbox("Ranking", list(RANK), key="mapa_rank")
    col_r, fmt_r, crescente = RANK[tipo_rank]
    base_r = dados[dados["valor"] > 0] if col_r == "part_caixa" else dados
    ranking(base_r, col_r, fmt_r, n=15, titulo=f"{tipo_rank} · {'estados' if not uf else 'municípios'}",
            filtro=_descer, valores="codarea", chave=f"rank_{uf or 'BR'}_{col_r}", crescente=crescente)
    st.caption("Clique numa barra para " + ("abrir o estado." if not uf else "abrir o município."))
    # leitura da faixa: onde a CAIXA está forte ou fraca
    fx = dados_tudo.groupby("faixa_caixa").agg(areas=("codarea", "count"), valor=("valor", "sum"))
    if not fx.empty:
        tot = fx["valor"].sum()
        leitura("Faixas de participação CAIXA", [
            f"<b>{nome}</b>: {int(fx.at[nome, 'areas'])} {'municípios' if uf else 'estados'} · "
            f"{q.brl(fx.at[nome, 'valor'])} ({q.pct(fx.at[nome, 'valor'] / tot) if tot else '—'})"
            for nome in FAIXAS if nome in fx.index])

# ---------------------------------------------------------------- indicações para o CRM
secao("Indicações para o CRM", "Entes do recorte do mapa com maior prioridade CRM-01 (potencial de custódia, dinheiro "
                               "sem banco conhecido, janela de escolha, presença CAIXA e emendas). Selecione um para "
                               "abrir a Visão 360 ou incluir na carteira.")
if indic.empty:
    st.caption("Nenhum ente acima da prioridade mínima neste recorte. Baixe a prioridade nos filtros do mapa ou aguarde "
               "a carga do Portal da Transparência.")
else:
    k1, k2 = st.columns([3, 1])
    cols = ["prioridade", "nome_ente", "uf", "status", "responsavel", "potencial_custodia", "sem_banco_12m",
            "valor_em_disputa", "bolsa_familia_mes", "emendas_12m", "alerta_conformidade", "proxima_acao", "cnpj_ente"]
    with k1:
        sel = g.grade(indic[[c for c in cols if c in indic]], chave=f"mapa_indic_{uf or 'BR'}", selecao=True, altura=420)
    with k2:
        leitura("Resumo", [
            f"<b>{len(indic):,}</b> entes · {q.brl(indic['potencial_custodia'].sum())} de potencial".replace(",", "."),
            f"<b>{int((indic['status'] == 'não abordado').sum()):,}</b> ainda não abordados".replace(",", "."),
            f"<b>{int(indic['alerta_conformidade'].fillna(False).astype(bool).sum())}</b> com alerta de conformidade "
            "(prioridade zerada até análise)" if "alerta_conformidade" in indic and
            indic["alerta_conformidade"].fillna(False).astype(bool).any() else ""])
        if sel and sel.get("cnpj_ente"):
            st.markdown(f"**{sel.get('nome_ente', '')}**")
            ui.abrir("Abrir na Visão 360", ui.TELA_ENTE, ("ente_visao", "360 · CRM"), {ui.ENTE: sel["cnpj_ente"]},
                     chave="mapa_v360")
            ja = sel.get("status") not in (None, "não abordado")
            if st.button("Incluir na carteira (a abordar)", use_container_width=True, key="mapa_cart", disabled=ja,
                         help="Registra o ente na carteira com você como responsável" if not ja else "Já está na carteira"):
                u = ctx.usuario
                acesso.salvar_carteira(sel["cnpj_ente"], "não abordado", u.get("nome", ""), "Indicado pelo mapa (CRM-01)",
                                       u.get("login", ""))
                st.success("Incluído na carteira.")
    baixar(f"indicacoes_crm_{uf or 'BR'}", {"indicacoes": indic})

# ---------------------------------------------------------------- abas de análise do nível
aba1, aba2, aba3, aba4 = st.tabs(["Composição", "Evolução", "Fluxo do dinheiro", "Tabela completa"])
with aba1:
    if not uf:
        from custodia.referencias import REGIAO
        comp = dados.assign(regiao=dados["codarea"].str.slice(0, 1).map(REGIAO))
        treemap(comp, ["regiao", "nome"], "valor", "part_caixa")
        st.caption("Tamanho: valor. Cor: participação CAIXA. Clique numa região para ampliar.")
    else:
        treemap(dados.assign(uf=uf), ["uf", "nome"], "valor", "part_caixa")
with aba2:
    linha_participacao(q.serie_anual_area(d, None, ctx.modulos, uf))
with aba3:
    instr = q.filtrada(d, "fato_instrumento", ctx.modulos, ctx.anos, [uf] if uf else (ctx.ufs or None))
    fl = q.filtrada(d, "fato_fluxo", ctx.modulos, None, [uf] if uf else (ctx.ufs or None))
    sankey(mf.sankey(instr, fl), altura=480)
with aba4:
    tabela(dados, chave=f"terr_tab_{uf or 'BR'}")
    baixar(f"territorio_{uf or 'BR'}", {"territorio": dados})

# ---------------------------------------------------------------- nível ente
if uf:
    st.subheader("Entes")
    muni = dados_tudo[["codarea", "nome"]].sort_values("nome")
    opcoes = [f"Estado ({uf})"] + muni["codarea"].tolist()
    rot = {f"Estado ({uf})": f"Governo e órgãos estaduais · {uf}", **dict(zip(muni["codarea"], muni["nome"]))}
    idx = opcoes.index(ss["terr_mun"]) if ss["terr_mun"] in opcoes else 0
    alvo = st.selectbox("Município", opcoes, index=idx, format_func=lambda c: rot.get(c, c))
    cod = UF_COD[uf] if alvo.startswith("Estado") else alvo
    linha = dados_tudo[dados_tudo["codarea"] == cod]
    if not linha.empty:
        r = linha.iloc[0]
        cartoes([{"rotulo": "Valor com banco", "valor": q.brl(r["valor"]), "sub": r["faixa_caixa"]},
                 {"rotulo": "Participação CAIXA", "valor": q.pct(r["part_caixa"])},
                 ui.cartao_saldo("Saldo na CAIXA", r["saldo_caixa"], r.get("saldo_caixa_estimado"),
                                 parado_em=q.parada_saldo(d)),
                 ui.cartao_saldo("Saldo no concorrente", r["saldo_concorrente"], r.get("saldo_concorrente_estimado"),
                                 cor="#F39200"),
                 {"rotulo": "Entes priorizados (CRM)", "valor": int(r["crm_priorizados"]), "cor": "#7E5BB5"},
                 {"rotulo": "Recebido da União 12m", "valor": q.brl(r["crm_recebido"]),
                  "sub": f"{q.brl(r['crm_sem_banco'])} sem banco conhecido"},
                 {"rotulo": "Bolsa Família no mês", "valor": q.brl(r["crm_bolsa_familia"]), "sub": "pago pela CAIXA"}])
    entes = q.entes_da_area(d, cod, ctx.modulos, ctx.anos)
    if entes.empty:
        st.info("Sem entes com instrumentos neste recorte.")
    else:
        tabela(entes, chave=f"entes_{cod}")
        ente = st.selectbox("Abrir o ente", entes["cnpj_ente"].tolist(),
                            format_func=lambda c: entes.set_index("cnpj_ente").at[c, "nome_ente"])
        b1, b2, _ = st.columns([1, 1, 3])
        with b1:
            ui.abrir("Abrir ficha técnica", ui.TELA_ENTE, ("ente_visao", "Ficha técnica"), {ui.ENTE: ente},
                     chave="mapa_ficha")
        with b2:
            ui.abrir("Abrir na Visão 360", ui.TELA_ENTE, ("ente_visao", "360 · CRM"), {ui.ENTE: ente}, chave="mapa_360b")
