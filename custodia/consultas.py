"""Leitura dos marts publicados e cálculos usados pelas telas (sem Streamlit; testável)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import normaliza
from . import config, storage
from .dados import Marts, memo

MARTS = ["fato_instrumento", "fato_conta", "fato_pipeline", "fato_pagamento", "fato_executor", "dim_ente", "mart_participacao", "mart_custodia",
         "mart_pipeline", "mart_vazamento", "mart_perfil_ente", "mart_janelas", "mart_score", "mart_alertas",
         "mart_qualidade", "serie_diaria", "ref_coordenadas",
         "fato_destinacao", "fato_emenda", "fato_fluxo", "mart_sankey", "mart_matriz_destino", "mart_parlamentares",
         "mart_rede_parlamentar", "mart_orgaos", "mart_destinacao", "mart_destino_ente", "mart_fornecedores",
         "mart_velocidade", "mart_potencial", "mart_conformidade", "mart_transferencia_secundaria",
         "mart_ente_resumo", "mart_uf_modalidade",
         # gestor de custódia
         "mart_permanencia", "mart_concentracao", "mart_a_receber", "mart_sazonalidade", "mart_escolha_ente",
         "mart_transicoes", "mart_matriz_modalidades", "mart_entes_perdidos", "mart_radar", "mart_venda_cruzada",
         "mart_priorizacao", "mart_ente_dimensoes", "mart_variacao_ente", "mart_variacao_banco", "mart_variacao_uf",
         "mart_evolucao_saldo", "mart_defasagem", "repo_catalogo", "repo_registro_cargas", "repo_verificacao", "mart_auditoria", "mart_auditoria_historico",
         "mart_janela_escolha", "mart_calendario_escolha", "mart_risco_agentes", "mart_fora_caixa",
         "mart_fora_caixa_agentes",
         "fato_repasse_outros", "fato_conta_saude", "mart_outras_municipio", "mart_oport_saude", "mart_auditoria_painel", "mart_auditoria_painel_exemplos",
         "crm_recebido", "crm_emenda", "crm_emenda_pagamento", "crm_sancao", "crm_presenca", "crm_carteira", "crm_alertas",
         "crm_rede", "crm_prioridade", "crm_qualidade", "crm_campos", "crm_cobertura", "crm_integridade",
         "mart_auditoria_profunda", "mart_anomalias_entes", "mart_extremos"]


def execucao_atual(cam: config.Caminhos | None = None) -> str | None:
    cam = cam or config.caminhos()
    p = cam.marts / "ATUAL.txt"
    return p.read_text("utf-8").strip() if p.exists() else None


def carregar(execucao: str, cam: config.Caminhos | None = None) -> Marts:
    """Marts da execução, lidos sob demanda (cada tabela uma vez, sem cópia a cada uso)."""
    cam = cam or config.caminhos()
    return Marts(cam.marts / execucao, MARTS, execucao)


# ------------------------------------------------------------------ formatação
def brl(v, curto: bool = True) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    v = float(v)
    if curto:
        for lim, suf in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
            if abs(v) >= lim:
                return f"R$ {v / lim:,.1f} {suf}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.0%}".replace(".", ",")


# ------------------------------------------------------------------ filtros e KPIs
def filtrar(df: pd.DataFrame, modulos=None, anos=None, ufs=None, extra: dict | None = None) -> pd.DataFrame:
    """Filtros da barra lateral + filtros de clique (`extra` = {coluna: [valores]}, aplicado onde a coluna existe)."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    m = pd.Series(True, index=df.index)
    if modulos and "modulo" in df:
        m &= df["modulo"].isin(modulos)
    if anos and "ano" in df:
        m &= df["ano"].isin(anos)
    if ufs and "uf" in df:
        m &= df["uf"].isin(ufs)
    for col, vals in (extra or {}).items():
        if vals and col in df:
            m &= df[col].astype(str).isin([str(v) for v in vals])
    return df if bool(m.all()) else df[m]


@memo(64)
def filtrada(d, nome: str, modulos=None, anos=None, ufs=None, extra: dict | None = None) -> pd.DataFrame:
    """`filtrar` sobre um mart, memorizado: o mesmo recorte não é refeito a cada clique."""
    return filtrar(d.get(nome, pd.DataFrame()), modulos, anos, ufs, extra)


@memo(32)
def kpis(d: dict, modulos=None, anos=None, ufs=None) -> dict:
    instr = filtrada(d, "fato_instrumento", modulos, anos, ufs)
    com_banco = instr[instr["grupo_banco"] != "(sem banco)"]
    total = com_banco["valor"].sum()
    caixa = com_banco.loc[com_banco["grupo_banco"] == "CAIXA", "valor"].sum()
    contas = filtrada(d, "fato_conta", modulos, None, ufs).drop_duplicates(["modulo", "id_agencia_conta"])
    cx = contas[contas["grupo_banco"] == "CAIXA"]
    pipe = filtrar(d["fato_pipeline"], modulos, None, ufs)
    jan = filtrar(d["mart_janelas"], modulos, None, ufs)
    vaz = d["mart_vazamento"]
    if ufs and not vaz.empty:
        vaz = vaz[vaz["uf"].isin(ufs)]
    return {
        "valor_total": total, "valor_caixa": caixa,
        "part_caixa": caixa / total if total else np.nan,
        "saldo_caixa": cx["saldo"].sum(),
        **{f"saldo_caixa_{k}": cx[c].sum() if c in cx else cx["saldo"].sum()
           for k, c in (("estimado", "saldo_estimado"), ("est_min", "saldo_est_min"), ("est_max", "saldo_est_max"))},
        "cobertura_caixa": cx["saldo"].notna().mean() if len(cx) else np.nan,
        "a_creditar_caixa": pipe.loc[pipe["grupo_banco"] == "CAIXA", "a_creditar"].sum() if not pipe.empty else 0,
        "valor_janelas": jan["valor"].sum() if not jan.empty else 0,
        "n_janelas": len(jan),
        "vazamento": vaz.loc[vaz["direcao"] == "saída da CAIXA", "valor_executor"].sum() if not vaz.empty else 0,
    }


def paradas_texto(d) -> str:
    """Frase com os bancos cujo extrato parou e desde quando (mm/aaaa), a partir da carga (sem texto fixo)."""
    mc = d.get("mart_custodia") if hasattr(d, "get") else None
    if mc is None or mc.empty or "extrato_parado_em" not in mc:
        return ""
    x = mc[mc["extrato_parado_em"].notna()]
    partes = []
    for r in x.itertuples():
        dt = pd.to_datetime(r.extrato_parado_em, errors="coerce")
        partes.append(f"{r.grupo_banco} em {r.modulo} desde {dt:%m/%Y}" if pd.notna(dt) else f"{r.grupo_banco} em {r.modulo}")
    return "; ".join(dict.fromkeys(partes))


def parada_saldo(d) -> str | None:
    """Data (dd/mm/aaaa) do último saldo publicado do banco cujo extrato parou (regra SAL-01), ou None."""
    mc = d.get("mart_custodia") if hasattr(d, "get") else None
    if mc is None or mc.empty or "extrato_parado_em" not in mc:
        return None
    x = mc[mc["extrato_parado_em"].notna() & (pd.to_numeric(mc["saldo"], errors="coerce").fillna(0) > 0)]
    if x.empty:
        return None
    dt = normaliza.data(x["data_saldo_max"].astype(object)).max()
    return dt.strftime("%d/%m/%Y") if pd.notna(dt) else None


def saldo_resumo(contas: pd.DataFrame) -> dict:
    """Saldo publicado e estimado (regra SAL-01) de um conjunto de contas, contando cada conta uma vez.
    `parado_em`: data do último saldo publicado das contas cujo extrato parou (None se nenhuma parou)."""
    if contas is None or contas.empty:
        return {"publicado": 0.0, "estimado": 0.0, "minimo": 0.0, "maximo": 0.0, "parado_em": None, "parado": 0.0}
    c = contas.drop_duplicates(["modulo", "id_agencia_conta"]) if "id_agencia_conta" in contas else contas
    s = pd.to_numeric(c["saldo"], errors="coerce").fillna(0)
    g = lambda col: pd.to_numeric(c[col], errors="coerce").fillna(0).sum() if col in c else s.sum()  # noqa: E731
    par = c["extrato_parado_em"].notna() if "extrato_parado_em" in c else pd.Series(False, index=c.index)
    datas = normaliza.data(c.loc[par & (s != 0), "data_saldo"]) if par.any() and "data_saldo" in c else pd.Series(dtype="datetime64[ns]")
    return {"publicado": float(s.sum()), "estimado": float(g("saldo_estimado")), "minimo": float(g("saldo_est_min")),
            "maximo": float(g("saldo_est_max")), "parado": float(s[par].sum()),
            "parado_em": datas.max().strftime("%d/%m/%Y") if len(datas) and pd.notna(datas.max()) else None}


def participacao_por(instr: pd.DataFrame, dimensao: str) -> pd.DataFrame:
    """Tabela dimensão x banco com participação da CAIXA, ordenada pelo valor do concorrente."""
    x = instr[instr["grupo_banco"] != "(sem banco)"]
    if x.empty:
        return pd.DataFrame()
    t = x.pivot_table(index=dimensao, columns="grupo_banco", values="valor", aggfunc="sum", fill_value=0)
    t["Total"] = t.sum(axis=1)
    if "CAIXA" not in t:
        t["CAIXA"] = 0.0
    t["% CAIXA"] = t["CAIXA"] / t["Total"]
    t["Concorrência"] = t["Total"] - t["CAIXA"]
    return t.sort_values("Concorrência", ascending=False)


def serie_participacao_ano(instr: pd.DataFrame) -> pd.DataFrame:
    x = instr[(instr["grupo_banco"] != "(sem banco)") & instr["ano"].notna()]
    if x.empty:
        return pd.DataFrame()
    t = x.pivot_table(index="ano", columns="grupo_banco", values="valor", aggfunc="sum", fill_value=0)
    t.index = t.index.astype(int).astype(str)
    return t


@memo(16)
def mapa_entes(d: dict, modulos=None, anos=None, ufs=None) -> pd.DataFrame:
    instr = filtrada(d, "fato_instrumento", modulos, anos, ufs)
    coords = d["ref_coordenadas"]
    if instr.empty or coords.empty:
        return pd.DataFrame()
    x = instr[instr["cod_ibge"].notna() & (instr["grupo_banco"] != "(sem banco)")].copy()
    x["cod_ibge"] = x["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True)
    g = x.groupby(["cod_ibge", "nome_ente", "uf"], as_index=False).agg(valor=("valor", "sum"))
    g["valor_caixa"] = x[x["grupo_banco"] == "CAIXA"].groupby("cod_ibge")["valor"].sum().reindex(g["cod_ibge"]).fillna(0).values
    g["part_caixa"] = g["valor_caixa"] / g["valor"].replace(0, np.nan)
    g = g.merge(coords, on="cod_ibge", how="inner")
    # vermelho = concorrente lidera, azul = CAIXA lidera; tamanho pelo valor
    g["cor"] = g["part_caixa"].map(lambda p: "#1f6fd1" if p >= 0.5 else "#d1495b")
    g["raio"] = (np.sqrt(g["valor"] / max(g["valor"].max(), 1)) * 25000 + 2000).round()
    return g


def simular(saldo: float, dias: float, taxa_aa: float, repasse: float = 1.0) -> dict:
    """Valor econômico aproximado da custódia: saldo médio × dias × taxa (% a.a.) × fração aproveitada."""
    receita = saldo * (taxa_aa / 100) * (dias / 365) * repasse
    return {"receita": receita, "saldo_dia": saldo * dias}


def ficha(d: dict, cnpj: str) -> dict:
    f = {}
    for nome, df in (("instrumentos", d["fato_instrumento"]), ("contas", d["fato_conta"]),
                     ("janelas", d["mart_janelas"]), ("pipeline", d["fato_pipeline"])):
        f[nome] = df[df["cnpj_ente"] == cnpj] if not df.empty else df
    sc = d["mart_score"]
    f["score"] = sc[sc["cnpj_ente"] == cnpj].iloc[0].to_dict() if not sc.empty and (sc["cnpj_ente"] == cnpj).any() else {}
    pe = d["mart_perfil_ente"]
    f["perfil"] = pe[pe["cnpj_ente"] == cnpj].iloc[0].to_dict() if not pe.empty and (pe["cnpj_ente"] == cnpj).any() else {}
    de = d["dim_ente"]
    f["ente"] = de[de["cnpj_ente"] == cnpj].iloc[0].to_dict() if not de.empty and (de["cnpj_ente"] == cnpj).any() else {}
    vaz = d["mart_vazamento"]
    f["vazamento"] = vaz[vaz["cnpj_ente"] == cnpj] if not vaz.empty else vaz
    return f


def para_excel(tabelas: dict[str, pd.DataFrame]) -> bytes | None:
    import io
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return None
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nome, df in tabelas.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()


# ------------------------------------------------------------------ visão territorial
METRICAS = {
    # rótulo: (coluna, escala de cor, formato)
    "Participação CAIXA": ("part_caixa", "RdBu", "pct"),
    "Valor total": ("valor", "Blues", "brl"),
    "Valor no concorrente": ("valor_concorrente", "Oranges", "brl"),
    "Saldo no concorrente": ("saldo_concorrente", "Oranges", "brl"),
    "Saldo na CAIXA": ("saldo_caixa", "Blues", "brl"),
    "Potencial de custódia": ("potencial", "Greens", "brl"),
    "Janelas abertas": ("janelas", "Purples", "brl"),
    "Transferência secundária FaF (12 meses)": ("transf_secundaria", "Greens", "brl"),
    # CRM (Portal da Transparência)
    "Oportunidades CRM (entes priorizados)": ("crm_priorizados", "Purples", "int"),
    "Potencial dos entes priorizados (CRM)": ("crm_potencial", "Greens", "brl"),
    "Recebido da União sem banco conhecido (12m)": ("crm_sem_banco", "Oranges", "brl"),
    "Recebido da União (12m, Portal)": ("crm_recebido", "Blues", "brl"),
    "Bolsa Família pago pela CAIXA (mês)": ("crm_bolsa_familia", "Blues", "brl"),
}

# faixas de participação CAIXA (filtro "mais CAIXA / menos CAIXA" do mapa)
FAIXAS_CAIXA = [("CAIXA forte (70% ou mais)", 0.70, 1.01), ("CAIXA lidera (50% a 70%)", 0.50, 0.70),
                ("Disputa (30% a 50%)", 0.30, 0.50), ("Concorrente lidera (menos de 30%)", 1e-9, 0.30),
                ("Sem CAIXA (0%)", -1.0, 1e-9)]
SEM_FAIXA = "Sem valor com banco"
LIMIAR_PRIORIDADE = 70


def faixa_caixa(part: pd.Series) -> pd.Series:
    out = pd.Series(SEM_FAIXA, index=part.index, dtype="object")
    p = pd.to_numeric(part, errors="coerce")
    for nome, a, b in FAIXAS_CAIXA:
        out[(p >= a) & (p < b)] = nome
    return out


@memo(8)
def crm_por_area(d, nivel: str = "UF", uf: str | None = None, limiar: int = LIMIAR_PRIORIDADE) -> pd.DataFrame:
    """Indicadores do CRM por área (UF ou município): entes priorizados, potencial, recebido sem banco, Bolsa Família.
    Chave `codarea` igual à de `territorio`."""
    from .referencias import UF_COD
    cols = ["codarea", "crm_priorizados", "crm_prioridade_max", "crm_potencial", "crm_sem_banco", "crm_recebido",
            "crm_bolsa_familia", "crm_alertas"]
    pr, cart, pres = d.get("crm_prioridade"), d.get("crm_carteira"), d.get("crm_presenca")

    def chave(df):
        if df is None or df.empty:
            return None
        x = df.copy()
        if "cod_ibge" in x:
            x["cod_ibge"] = x["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True)
        if nivel == "UF":
            if "uf" not in x:
                return None
            return x.assign(codarea=x["uf"].map(UF_COD))
        x = x[(x["uf"] == uf)] if "uf" in x else x[x["cod_ibge"].str[:2] == UF_COD.get(uf, "")]
        return x.assign(codarea=x["cod_ibge"])

    partes = []
    p = chave(pr)
    if p is not None and not p.empty:
        pri = pd.to_numeric(p["prioridade"], errors="coerce").fillna(0)
        alto = p[pri >= limiar]
        partes.append(alto.groupby("codarea")["cnpj_ente"].nunique().rename("crm_priorizados"))
        partes.append(p.assign(_p=pri).groupby("codarea")["_p"].max().rename("crm_prioridade_max"))
        partes.append(alto.groupby("codarea")["potencial_custodia"].sum().rename("crm_potencial"))
        if "alerta_conformidade" in p:
            partes.append(p[p["alerta_conformidade"].fillna(False).astype(bool)].groupby("codarea")["cnpj_ente"]
                          .nunique().rename("crm_alertas"))
    if cart is not None and not cart.empty and "tipo_pessoa" in cart:   # custódia: só administração pública
        cart = cart[cart["tipo_pessoa"].fillna("").astype(str).str.contains("Administra", case=False)]
    c = chave(cart)
    if c is not None and not c.empty:
        partes.append(c.groupby("codarea")["sem_banco_12m"].sum().rename("crm_sem_banco"))
        partes.append(c.groupby("codarea")["recebido_12m"].sum().rename("crm_recebido"))
    b = chave(pres.assign(uf=pres["uf"]) if pres is not None and not pres.empty and "uf" in pres else pres)
    if b is not None and not b.empty:
        partes.append(b.groupby("codarea")["bolsa_familia_mes"].sum().rename("crm_bolsa_familia"))
    if not partes:
        return pd.DataFrame(columns=cols)
    out = pd.concat(partes, axis=1)
    out.index.name = "codarea"
    out = out.reset_index()
    out = out[out["codarea"].notna()]
    for c_ in cols:
        if c_ not in out:
            out[c_] = 0.0
    return out[cols].fillna({c_: 0 for c_ in cols if c_ != "codarea"})


@memo(4)
def _mapa_territorial(d: dict) -> pd.DataFrame:
    """cnpj_ente -> uf, cod_ibge, cod_uf, municipio, esfera."""
    from .referencias import UF_COD
    de = d["dim_ente"].copy()
    if de.empty:
        return pd.DataFrame(columns=["cnpj_ente", "uf", "cod_ibge", "cod_uf", "municipio", "esfera"])
    for c in ("municipio", "esfera"):
        if c not in de:
            de[c] = None
    de["cod_uf"] = de["uf"].map(UF_COD)
    return de[["cnpj_ente", "uf", "cod_ibge", "cod_uf", "municipio", "esfera", "nome_ente"]]


@memo(48)
def territorio(d: dict, nivel: str = "UF", uf: str | None = None, modulos=None, anos=None,
               cnpjs=None) -> pd.DataFrame:
    """Indicadores por UF (nivel='UF') ou por município de uma UF (nivel='Município').
    Coluna `codarea` casa com a propriedade `codarea` das malhas do IBGE."""
    cols = ["codarea", "nome", "uf", "valor", "valor_caixa", "valor_concorrente", "part_caixa", "instrumentos", "entes",
            "saldo_caixa", "saldo_concorrente", "saldo_caixa_estimado", "saldo_concorrente_estimado", "potencial",
            "janelas", "transf_secundaria"]
    terr = _mapa_territorial(d)
    if terr.empty:
        return pd.DataFrame(columns=cols)
    if nivel == "UF":
        terr = terr.assign(codarea=terr["cod_uf"], nome=terr["uf"])
    else:
        terr = terr[(terr["uf"] == uf) & (terr["cod_ibge"].fillna("").str.len() == 7)]
        terr = terr.assign(codarea=terr["cod_ibge"], nome=terr["municipio"].fillna(terr["nome_ente"]))
    terr = terr.dropna(subset=["codarea"])
    if cnpjs is not None:
        terr = terr[terr["cnpj_ente"].isin(set(cnpjs))]
    chave = terr.set_index("cnpj_ente")[["codarea"]]

    def por_area(df, valor, filtro=None):
        if df is None or df.empty:
            return pd.Series(dtype=float)
        x = df if filtro is None else df[filtro(df)]
        x = x.merge(chave, left_on="cnpj_ente", right_index=True, how="inner")
        return x.groupby("codarea")[valor].sum()

    instr = filtrada(d, "fato_instrumento", modulos, anos, [uf] if uf else None)
    com = instr[instr["grupo_banco"] != "(sem banco)"]
    base = terr.groupby("codarea").agg(nome=("nome", "first"), uf=("uf", "first"))
    base["valor"] = por_area(com, "valor")
    base["valor_caixa"] = por_area(com, "valor", lambda x: x["grupo_banco"] == "CAIXA")
    x = com.merge(chave, left_on="cnpj_ente", right_index=True, how="inner")
    base["instrumentos"] = x.groupby("codarea")["id_instrumento"].count()
    base["entes"] = x.groupby("codarea")["cnpj_ente"].nunique()
    contas = filtrada(d, "fato_conta", modulos, None, [uf] if uf else None)
    if not contas.empty:
        contas = contas.drop_duplicates(["modulo", "id_agencia_conta"])
    base["saldo_caixa"] = por_area(contas, "saldo", lambda c: c["grupo_banco"] == "CAIXA")
    base["saldo_concorrente"] = por_area(contas, "saldo", lambda c: c["grupo_banco"] != "CAIXA")
    est = "saldo_estimado" if contas is not None and "saldo_estimado" in contas else "saldo"   # regra SAL-01
    base["saldo_caixa_estimado"] = por_area(contas, est, lambda c: c["grupo_banco"] == "CAIXA")
    base["saldo_concorrente_estimado"] = por_area(contas, est, lambda c: c["grupo_banco"] != "CAIXA")
    base["potencial"] = por_area(d.get("mart_potencial"), "potencial_custodia")
    base["janelas"] = por_area(filtrar(d.get("mart_janelas", pd.DataFrame()), modulos, None, None), "valor")
    base["transf_secundaria"] = por_area(d.get("mart_transferencia_secundaria"), "valor_12_meses")
    num = [c for c in cols if c not in ("codarea", "nome", "uf", "part_caixa", "valor_concorrente")]
    base[num] = base[num].fillna(0)
    base["valor_concorrente"] = base["valor"] - base["valor_caixa"]
    base["part_caixa"] = base["valor_caixa"] / base["valor"].replace(0, np.nan)
    out = base.reset_index()
    out = out[out[["valor", "saldo_caixa", "saldo_concorrente", "potencial", "transf_secundaria"]].sum(axis=1) > 0][cols]
    crm = crm_por_area(d, nivel, uf)
    if crm is not None and not crm.empty:
        out = out.merge(crm, on="codarea", how="left")
    for c_ in ("crm_priorizados", "crm_prioridade_max", "crm_potencial", "crm_sem_banco", "crm_recebido",
               "crm_bolsa_familia", "crm_alertas"):
        out[c_] = pd.to_numeric(out.get(c_, 0), errors="coerce").fillna(0)
    out["faixa_caixa"] = faixa_caixa(out["part_caixa"])
    return out


@memo(32)
def entes_da_area(d: dict, cod_ibge: str, modulos=None, anos=None) -> pd.DataFrame:
    """Entes de um município (ou do estado, código de 2 dígitos) com os principais indicadores."""
    terr = _mapa_territorial(d)
    alvo = terr[terr["cod_ibge"] == cod_ibge]["cnpj_ente"]
    instr = filtrada(d, "fato_instrumento", modulos, anos, None)
    i = instr[instr["cnpj_ente"].isin(alvo)]
    if i.empty:
        return pd.DataFrame(columns=["cnpj_ente", "nome_ente", "valor", "part_caixa", "bancos", "acao_recomendada"])
    g = i.groupby(["cnpj_ente", "nome_ente"], as_index=False).agg(
        valor=("valor", "sum"), bancos=("grupo_banco", lambda s: " + ".join(sorted(set(s)))),
        modulos=("modulo", lambda s: ", ".join(sorted(set(s)))))
    cx = i[i["grupo_banco"] == "CAIXA"].groupby("cnpj_ente")["valor"].sum()
    g["part_caixa"] = g["cnpj_ente"].map(cx).fillna(0) / g["valor"].replace(0, np.nan)
    pot = d.get("mart_potencial")
    if pot is not None and not pot.empty:
        g = g.merge(pot[["cnpj_ente", "segmento", "potencial_custodia", "acao_recomendada"]], on="cnpj_ente", how="left")
    return g.sort_values("valor", ascending=False)


@memo(32)
def serie_anual_area(d: dict, cnpjs=None, modulos=None, uf=None) -> pd.DataFrame:
    instr = filtrada(d, "fato_instrumento", modulos, None, [uf] if uf else None)
    if cnpjs is not None:
        instr = instr[instr["cnpj_ente"].isin(cnpjs)]
    return serie_participacao_ano(instr)


def malha(nome: str) -> dict | None:
    from .referencias import malha as _m
    return _m(config.caminhos().referencias, nome)



# ------------------------------------------------------------------ cockpit executivo
MODALIDADE_COLUNA = {"Especiais": "valor_especiais", "Fundo a Fundo": "valor_fundo_a_fundo",
                     "Discricionárias": "valor_convenios"}


def filtrar_entes(er: pd.DataFrame, modulos=None, bancos=None, segmentos=None, esferas=None, portes=None,
                  acoes=None, ufs=None) -> pd.DataFrame:
    """Filtra o resumo por ente. `valor_filtro` = soma das modalidades escolhidas."""
    if er is None or er.empty:
        return pd.DataFrame()
    e = er.copy()
    cols = [MODALIDADE_COLUNA[m] for m in (modulos or MODALIDADE_COLUNA) if m in MODALIDADE_COLUNA]
    e["valor_filtro"] = e[cols].sum(axis=1) if cols else 0.0
    m = e["valor_filtro"] > 0
    for col, sel in (("banco_principal", bancos), ("segmento", segmentos), ("esfera", esferas), ("porte", portes),
                     ("acao_recomendada", acoes), ("uf", ufs)):
        if sel:
            m &= e[col].isin(sel)
    return e[m]


def leituras(d: dict, entes: pd.DataFrame, uf_df: pd.DataFrame, modulos=None) -> list[str]:
    """Frases automáticas para o executivo: o que os números do recorte dizem."""
    out = []
    if entes.empty:
        return out
    v, cx = uf_df["valor"].sum(), uf_df["valor_caixa"].sum()
    if v:
        out.append(f"A CAIXA tem <b>{pct(cx / v)}</b> do valor com banco definido neste recorte "
                   f"({brl(cx)} de {brl(v)}).")
    lidera = uf_df[uf_df["part_caixa"] < 0.5]
    if not uf_df.empty:
        out.append(f"O concorrente lidera em <b>{len(lidera)} de {len(uf_df)}</b> UFs"
                   + (f"; a maior bolsa está em <b>{uf_df.sort_values('valor_concorrente').iloc[-1]['nome']}</b> "
                      f"({brl(uf_df['valor_concorrente'].max())} no concorrente)." if len(uf_df) else "."))
    serie = serie_participacao_ano(filtrar(d["fato_instrumento"], modulos, None, None)[
        lambda x: x["cnpj_ente"].isin(set(entes["cnpj_ente"]))])
    if len(serie) >= 2 and "CAIXA" in serie:
        part = serie["CAIXA"] / serie.sum(axis=1)
        a, b = part.index[-2], part.index[-1]
        delta = part.iloc[-1] - part.iloc[-2]
        from datetime import date as _date
        parcial = str(b) == str(_date.today().year)
        out.append(f"Participação CAIXA {'subiu' if delta >= 0 else 'caiu'} de {pct(part.iloc[-2])} ({a}) "
                   f"para <b>{pct(part.iloc[-1])}</b> ({b}{', ano em curso: pode mudar até dezembro' if parcial else ''}).")
    seg = entes.groupby("segmento").agg(n=("cnpj_ente", "count"), pot=("potencial_custodia", "sum"))
    if "Território concorrente" in seg.index:
        r = seg.loc["Território concorrente"]
        out.append(f"<b>{int(r['n'])}</b> entes são território do concorrente, com potencial de custódia de "
                   f"<b>{brl(r['pot'])}</b>.")
    if "Disputado" in seg.index:
        r = seg.loc["Disputado"]
        out.append(f"<b>{int(r['n'])}</b> entes estão em disputa (usam CAIXA e concorrente).")
    ts = entes["transf_secundaria"].sum()
    if ts > 0:
        out.append(f"Nos últimos 12 meses, <b>{brl(ts)}</b> saíram de contas Fundo a Fundo (BB) para contas dos "
                   f"próprios entes ({int((entes['transf_secundaria'] > 0).sum())} entes).")
    pt = pagamentos_terceiros_por_ente(d)
    if not pt.empty:
        x = pt[pt["cnpj_ente"].isin(set(entes["cnpj_ente"]))]
        tot = float(x["pago_terceiros"].sum())
        if tot:
            out.append(f"<b>{pct(float(x['pago_caixa'].sum()) / tot)}</b> do que os entes pagaram a terceiros com banco "
                       f"informado caiu em conta CAIXA ({x['periodo'].iloc[0] if len(x) else ''}, mesma janela para "
                       "todos os bancos): os fornecedores são público de prospecção.")
    return out


# ------------------------------------------------------------------ cenários e assessoria
def cenario(er: pd.DataFrame, por: str, meta: float, taxa_aa: float, fracao: float) -> pd.DataFrame:
    """Quanto a CAIXA ganha se alcançar `meta` de participação em cada grupo (só o que falta para a meta)."""
    if er.empty:
        return pd.DataFrame()
    g = er.groupby(por, dropna=False).agg(entes=("cnpj_ente", "count"), valor=("valor", "sum"),
                                          valor_caixa=("valor_caixa", "sum"), saldo_caixa=("saldo_caixa", "sum"),
                                          saldo_concorrente=("saldo_concorrente", "sum")).reset_index()
    g["part_caixa"] = g["valor_caixa"] / g["valor"].replace(0, np.nan)
    saldo_tot = g["saldo_caixa"] + g["saldo_concorrente"]
    g["part_saldo_caixa"] = g["saldo_caixa"] / saldo_tot.replace(0, np.nan)
    g["ganho_valor"] = (meta * g["valor"] - g["valor_caixa"]).clip(lower=0)
    g["ganho_custodia"] = (meta * saldo_tot - g["saldo_caixa"]).clip(lower=0)
    g["ganho_resultado_ano"] = g["ganho_custodia"] * taxa_aa / 100 * fracao
    return g.sort_values("ganho_custodia", ascending=False)


def _linha(df: pd.DataFrame, cnpj: str) -> dict:
    if df is None or df.empty or "cnpj_ente" not in df:
        return {}
    x = df[df["cnpj_ente"] == cnpj]
    return x.iloc[0].to_dict() if not x.empty else {}


def assessor(d: dict, cnpj: str) -> dict:
    """Diagnóstico, recomendações e argumentos para um ente, a partir dos motores."""
    er = d.get("mart_ente_resumo", pd.DataFrame())
    e = _linha(er, cnpj)
    dims = _linha(d.get("mart_ente_dimensoes"), cnpj)
    pri = _linha(d.get("mart_priorizacao"), cnpj)
    perd = _linha(d.get("mart_entes_perdidos"), cnpj)
    sel = lambda nome: (d.get(nome, pd.DataFrame()).pipe(  # noqa: E731
        lambda x: x[x["cnpj_ente"] == cnpj] if not x.empty and "cnpj_ente" in x else x.iloc[0:0]))
    riscos, ofertas, receber, esc = sel("mart_radar"), sel("mart_venda_cruzada"), sel("mart_a_receber"), sel("mart_escolha_ente")
    if riscos.empty is False:
        riscos = riscos[riscos["regra"] != "RIS-06"]

    pares = er[(er["uf"] == e.get("uf")) & (er["porte"] == e.get("porte")) & (er["valor"] > 0)] if e else er.iloc[0:0]
    comp = {"pares": len(pares), "part_caixa_pares": float(pares["valor_caixa"].sum() / pares["valor"].sum())
            if len(pares) and pares["valor"].sum() else None,
            "saldo_mediano_pares": float(pares[["saldo_caixa", "saldo_concorrente"]].sum(axis=1).median()) if len(pares) else None}

    rec, arg = [], []
    q = pri.get("quadrante")
    if q == "Atacar já":
        rec.append(f"<b>Prioridade máxima</b>: potencial de {brl(pri.get('potencial_custodia'))} com chance de conversão "
                   f"{int(pri.get('chance_conversao', 0))}/100.")
    elif q == "Construir relação":
        rec.append(f"<b>Construir relação</b>: potencial alto ({brl(pri.get('potencial_custodia'))}), mas o ente está "
                   "distante da CAIXA. Comece pelo relacionamento institucional e pela bancada.")
    elif q == "Ganho rápido":
        rec.append("<b>Ganho rápido</b>: o ente está perto da CAIXA; uma abordagem simples tende a converter.")
    if perd:
        rec.append(f"<b>Reconquista</b>: escolheu a CAIXA pela última vez em {perd['ultimo_ano_caixa']} e em "
                   f"{perd['ultimo_ano']} foi para {perd['banco_atual']} ({brl(perd['valor_concorrente_depois'])} desde então).")
    if not receber.empty:
        receber = receber[~receber["faixa_prazo"].str.startswith("Empenho antigo")]
        if "firme" in receber:
            receber = receber[receber["firme"].fillna(False).astype(bool)]
    rc = receber[receber["grupo_banco"] != "CAIXA"]["valor_a_receber"].sum() if not receber.empty else 0
    if rc > 0:
        rec.append(f"<b>Antes do próximo crédito</b>: {brl(rc)} ainda vão cair em conta do concorrente. A conta desses "
                   "instrumentos já está aberta; o foco é o banco dos próximos planos e convênios.")
    for o in ofertas.itertuples() if not ofertas.empty else []:
        arg.append(f"<b>{o.oferta}</b> ({o.regra}): {o.argumento}")
    mitig = {"RIS-01": "visitar para entender a troca e apresentar condição de retorno",
             "RIS-02": "planejar a retenção do saldo antes do fim da vigência",
             "RIS-03": "verificar a causa da saída do saldo com o gestor do ente",
             "RIS-04": "oferecer pagamento a fornecedores e domicílio bancário",
             "RIS-05": "ampliar o relacionamento além de um único autor de emendas"}
    for r in riscos.itertuples() if not riscos.empty else []:
        rec.append(f"<b>Risco · {r.risco}</b> ({r.severidade}): {r.detalhe} Ação: {mitig.get(r.regra, 'acompanhar')}.")
    if comp["part_caixa_pares"] is not None and e:
        arg.append(f"Entes de porte {e.get('porte')} em {e.get('uf')} têm {pct(comp['part_caixa_pares'])} na CAIXA; "
                   f"este ente tem {pct(e.get('part_caixa'))}.")
    return {"ente": e, "dimensoes": dims, "priorizacao": pri, "perdido": perd, "riscos": riscos, "ofertas": ofertas,
            "a_receber": receber, "escolhas": esc, "comparacao": comp, "recomendacoes": rec, "argumentos": arg}


# ------------------------------------------------------------------ rede de relacionamento (CRM)
RELACOES = {("parlamentar", "ente"): "Parlamentar → ente (emendas pagas)",
            ("ente", "banco"): "Ente → banco (instrumentos)",
            ("ente", "fornecedor"): "Ente → fornecedor (pagamentos)",
            ("fornecedor", "sanção"): "Fornecedor → sanção"}


def cnpj_fmt(v) -> str:
    s = "".join(ch for ch in str(v) if ch.isdigit())
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}" if len(s) == 14 else str(v)


def _parece_doc(v) -> bool:
    s = str(v or "").replace(".", "").replace("/", "").replace("-", "").strip()
    return s == "" or s.lower() in ("nan", "none") or (s.isdigit() and len(s) >= 11)


@memo(4)
def nomes_rede(d) -> dict:
    """id → nome legível para os pontos da rede (ente, fornecedor, parlamentar), juntando todas as fontes."""
    nomes: dict = {}
    for nome, col_id, col_nome in (("dim_ente", "cnpj_ente", "nome_ente"), ("mart_ente_resumo", "cnpj_ente", "nome_ente"),
                                   ("crm_carteira", "cnpj", "nome"), ("mart_fornecedores", "doc_favorecido", "favorecido"),
                                   ("crm_sancao", "cnpj", "nome")):
        df = d.get(nome)
        if df is not None and not df.empty and col_id in df and col_nome in df:
            x = df[[col_id, col_nome]].dropna()
            x = x[~x[col_nome].map(_parece_doc)]
            for k, v in zip(x[col_id].astype(str), x[col_nome].astype(str)):
                nomes.setdefault(k, v)
    return nomes


@memo(8)
def rede_legivel(d) -> pd.DataFrame:
    """A rede com nomes no lugar de CNPJ (o CNPJ vira dado de apoio, formatado) e o tipo de relação."""
    rd = d.get("crm_rede", pd.DataFrame())
    if rd is None or rd.empty:
        return pd.DataFrame(columns=["origem_tipo", "origem", "origem_id", "destino_tipo", "destino", "destino_id",
                                     "valor", "fonte", "relacao"])
    nomes = nomes_rede(d)
    rd = rd.assign(valor=pd.to_numeric(rd["valor"], errors="coerce").fillna(0), origem_id=rd["origem_id"].astype(str),
                   destino_id=rd["destino_id"].astype(str))
    for lado in ("origem", "destino"):
        ids, atual = rd[f"{lado}_id"], rd[lado]
        ruim = atual.map(_parece_doc)
        rd[lado] = atual.where(~ruim, ids.map(nomes)).fillna(ids.map(lambda v: f"CNPJ {cnpj_fmt(v)}"))
    rd["relacao"] = [RELACOES.get((a, b), f"{a} → {b}") for a, b in zip(rd["origem_tipo"], rd["destino_tipo"])]
    return rd


def pareto(rd: pd.DataFrame, corte: float = 0.8, max_por_relacao: int = 40) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Regra 80/20: por tipo de relação, as maiores relações até somar `corte` do valor (no máximo
    `max_por_relacao` para o gráfico ficar legível). Devolve (arestas principais, resumo por relação)."""
    cols_r = ["relacao", "relacoes", "valor", "relacoes_no_corte", "pct_relacoes_no_corte", "valor_no_corte",
              "pct_valor_no_corte"]
    if rd is None or rd.empty:
        return rd, pd.DataFrame(columns=cols_r)
    partes, resumo = [], []
    for rel, x in rd.groupby("relacao", sort=False):
        x = x.sort_values("valor", ascending=False)
        tot = float(x["valor"].sum())
        acum = x["valor"].cumsum()
        n80 = int((acum.shift(fill_value=0) < corte * tot).sum()) if tot > 0 else len(x)
        n80 = max(1, n80)
        sel = x.head(min(n80, max_por_relacao))
        partes.append(sel)
        resumo.append({"relacao": rel, "relacoes": len(x), "valor": tot, "relacoes_no_corte": n80,
                       "pct_relacoes_no_corte": n80 / len(x) if len(x) else None,
                       "valor_no_corte": float(x.head(n80)["valor"].sum()),
                       "pct_valor_no_corte": float(x.head(n80)["valor"].sum()) / tot if tot else None})
    return pd.concat(partes, ignore_index=True), pd.DataFrame(resumo, columns=cols_r)


@memo(16)
def sankey_modalidade(d, modulos=None, cnpjs=None) -> pd.DataFrame:
    """Fluxo modalidade → banco → destino do Cockpit, memorizado."""
    from . import motores_fluxo as mf
    return mf.sankey_modalidade(filtrada(d, "fato_instrumento", modulos), filtrada(d, "fato_fluxo", modulos), cnpjs)


@memo(8)
def outros_doze_meses(d, ufs=None) -> pd.DataFrame:
    """Outros repasses (FUNDEB, FPM, FNS, FNDE, FNAS) dos 12 últimos meses de cada fonte, memorizado."""
    from .marts_outras import doze_meses
    return doze_meses(filtrada(d, "fato_repasse_outros", None, None, ufs))


@memo(8)
def outros_por_mes(d, ufs=None) -> pd.DataFrame:
    """Outros repasses por mês × fonte (24 últimos meses), memorizado."""
    f = filtrada(d, "fato_repasse_outros", None, None, ufs)
    if f is None or f.empty:
        return pd.DataFrame()
    g = f.groupby(["ano", "mes", "fonte"])["valor"].sum().reset_index()
    g["periodo"] = g["ano"].astype(int).astype(str) + "-" + g["mes"].astype(int).astype(str).str.zfill(2)
    return g.groupby(["periodo", "fonte"])["valor"].sum().unstack(fill_value=0).sort_index().tail(24).reset_index()


@memo(4)
def opcoes_entes(d) -> pd.DataFrame:
    """Todos os entes que o CRM conhece (painel + Portal), ordenados pela prioridade CRM-01, com texto de busca."""
    er, cart, pr = d.get("mart_ente_resumo"), d.get("crm_carteira"), d.get("crm_prioridade")
    partes = []
    if er is not None and not er.empty:
        partes.append(er[[c for c in ("cnpj_ente", "nome_ente", "uf", "municipio") if c in er]])
    if cart is not None and not cart.empty:
        partes.append(cart.rename(columns={"cnpj": "cnpj_ente", "nome": "nome_ente"})[
            [c for c in ("cnpj_ente", "nome_ente", "uf", "municipio") if c in cart.rename(columns={"cnpj": "cnpj_ente",
                                                                                                  "nome": "nome_ente"})]])
    if not partes:
        return pd.DataFrame(columns=["cnpj_ente", "nome_ente", "uf", "rotulo", "busca", "prioridade"])
    o = pd.concat(partes, ignore_index=True).drop_duplicates("cnpj_ente")
    o["prioridade"] = o["cnpj_ente"].map(pr.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["prioridade"]) \
        if pr is not None and not pr.empty else None
    o = o.sort_values("prioridade", ascending=False, na_position="last")
    mun = o["municipio"].fillna("") if "municipio" in o else ""
    o["rotulo"] = o["nome_ente"].fillna("?") + " · " + o["uf"].fillna("?") + " (" + o["cnpj_ente"].map(cnpj_fmt) + ")"
    from .normaliza import sem_acento
    o["busca"] = (o["nome_ente"].fillna("") + " " + mun + " " + o["cnpj_ente"].astype(str) + " " + o["uf"].fillna("")) \
        .map(sem_acento).str.lower()
    return o.reset_index(drop=True)


def buscar_entes(d, texto: str = "", limite: int = 300, incluir: str | None = None) -> pd.DataFrame:
    """Até `limite` entes que casam com o texto (nome, município, UF ou CNPJ; sem acento), mais `incluir`."""
    from .normaliza import sem_acento
    o = opcoes_entes(d)
    if texto and texto.strip():
        t = sem_acento(texto.strip()).lower()
        dig = "".join(ch for ch in t if ch.isdigit())
        m = o["busca"].str.contains(t, regex=False)
        if len(dig) >= 4:
            m |= o["cnpj_ente"].astype(str).str.contains(dig, regex=False)
        x = o[m].head(limite)
    else:
        x = o.head(limite)
    if incluir and incluir not in set(x["cnpj_ente"]):
        x = pd.concat([o[o["cnpj_ente"] == incluir], x], ignore_index=True)
    return x


FONTES_TRANSF = {"FPM": "FPM (Tesouro)", "FUNDEB": "FUNDEB (Tesouro)", "FNS": "Saúde · FNS", "FNDE": "Educação · FNDE",
                 "FNAS": "Assistência · FNAS", "Royalties": "Royalties"}


@memo(64)
def transferencias_municipio(d, cod_ibge: str) -> pd.DataFrame:
    """Transferências ao município nos 12 últimos meses de cada fonte (FPM, FUNDEB, FNS, FNDE, FNAS, royalties),
    com o banco quando a fonte publica (só o FNS). Complementa o Portal, que não traz essas transferências."""
    from .marts_outras import doze_meses
    o = d.get("fato_repasse_outros")
    cols = ["fonte", "nome_fonte", "valor_12m", "valor_caixa", "valor_outro_banco", "banco_publicado"]
    if o is None or o.empty or not cod_ibge:
        return pd.DataFrame(columns=cols)
    x = doze_meses(o[o["cod_ibge"].astype(str) == str(cod_ibge)])
    if x.empty:
        return pd.DataFrame(columns=cols)
    g = x.groupby("fonte").agg(valor_12m=("valor", "sum")).reset_index()
    cx = x[x["grupo_banco"] == "CAIXA"].groupby("fonte")["valor"].sum()
    ob = x[x["grupo_banco"].notna() & (x["grupo_banco"] != "CAIXA")].groupby("fonte")["valor"].sum()
    g["valor_caixa"] = g["fonte"].map(cx).fillna(0)
    g["valor_outro_banco"] = g["fonte"].map(ob).fillna(0)
    g["banco_publicado"] = g["fonte"].map(x.groupby("fonte")["grupo_banco"].apply(lambda s: s.notna().any()))
    g["nome_fonte"] = g["fonte"].map(FONTES_TRANSF).fillna(g["fonte"])
    return g.sort_values("valor_12m", ascending=False)[cols]


@memo(4)
def pagamentos_terceiros_por_ente(d) -> pd.DataFrame:
    """Pago a terceiros (com banco do recebedor informado) por ente, numa janela de 12 meses comum a todos os
    bancos pagadores: se o extrato de um banco parou (CAIXA nas Especiais desde mai/2025), a janela termina ali —
    senão a comparação favorece o banco que continuou publicando."""
    fl = d.get("fato_fluxo")
    cols = ["cnpj_ente", "pago_terceiros", "pago_caixa", "periodo"]
    if fl is None or fl.empty:
        return pd.DataFrame(columns=cols)
    f = fl[(fl["tipo_movimento"] == "pagamento/transferência") & ~fl["proprio_ente"].fillna(False).astype(bool)
           & fl["grupo_destino"].notna() & (fl["grupo_destino"] != "(sem banco)")]
    if f.empty:
        return pd.DataFrame(columns=cols)
    from .normaliza import data as _data
    dt = _data(f["data"])
    ult = dt.groupby([f["modulo"], f["grupo_origem"]]).max()
    corte = ult.min()
    if pd.isna(corte):
        return pd.DataFrame(columns=cols)
    m = (dt <= corte) & (dt > corte - pd.Timedelta(days=365))
    x = f[m]
    g = x.groupby("cnpj_ente").agg(pago_terceiros=("valor", "sum")).reset_index()
    g["pago_caixa"] = g["cnpj_ente"].map(x[x["grupo_destino"] == "CAIXA"].groupby("cnpj_ente")["valor"].sum()).fillna(0)
    g["periodo"] = f"{(corte - pd.Timedelta(days=364)).strftime('%m/%Y')} a {corte.strftime('%m/%Y')}"
    return g[cols]


# ------------------------------------------------------------------ ciclo da escolha do banco (Janela de escolha)
@memo(8)
def ciclo_escolha(d: dict) -> dict:
    """Quando o banco é escolhido (aceite/ciência do plano) × quando o dinheiro cai (ordem bancária), nas
    Transferências Especiais, e o que acontece entre uma escolha e a próxima. Tudo medido nos dados:
    - meses de escolha e de crédito (% do valor de cada mês, todos os anos);
    - janelas de cada ano (meses que somam 80% das escolhas do ano) e participação CAIXA nelas;
    - dias do aceite à primeira ordem bancária (mediana, P25, P75);
    - contas por plano (desde 2024 cada transferência tem conta própria) e troca de banco entre anos."""
    from .motores_gestor import MESES
    out: dict = {}
    cal = d.get("mart_calendario_escolha", pd.DataFrame())
    cal = cal[cal["modulo"] == "Especiais"] if not cal.empty else cal
    saz = d.get("mart_sazonalidade", pd.DataFrame())
    if not cal.empty:
        esc = cal.groupby("mes")["valor"].sum().reindex(range(1, 13), fill_value=0)
        cre = (saz.set_index("mes")["valor_pago"].reindex(range(1, 13), fill_value=0) if not saz.empty
               else pd.Series(0.0, index=range(1, 13)))
        out["meses"] = pd.DataFrame({"mes": range(1, 13), "mes_nome": MESES,
                                     "escolha_pct": (esc / max(esc.sum(), 1)).values,
                                     "credito_pct": (cre / max(cre.sum(), 1)).values})
        anos = []
        for ano, g in cal.groupby("ano"):
            g = g.sort_values("valor", ascending=False)
            acum = g["valor"].cumsum() / max(g["valor"].sum(), 1)
            jan = g[acum.shift(fill_value=0) < 0.8].sort_values("mes")
            anos.append({"ano": int(ano), "meses_da_janela": ", ".join(MESES[int(m) - 1] for m in jan["mes"]),
                         "planos": int(g["instrumentos"].sum()), "valor": float(g["valor"].sum()),
                         "part_caixa": float(g["valor_caixa"].sum() / g["valor"].sum()) if g["valor"].sum() else np.nan})
        out["janelas"] = pd.DataFrame(anos).sort_values("ano", ascending=False)
    fi = d.get("fato_instrumento", pd.DataFrame())
    pi = d.get("fato_pipeline", pd.DataFrame())
    if not fi.empty and not pi.empty and "data_ob" in pi:
        e = fi[fi["modulo"] == "Especiais"][["id_instrumento", "data_referencia", "id_agencia_conta", "ano"]].copy()
        e["_ac"] = normaliza.data(e["data_referencia"])
        ob = pi.assign(_ob=normaliza.data(pi["data_ob"])).dropna(subset=["_ob"]).groupby("id_instrumento")["_ob"].min()
        e["_ob"] = e["id_instrumento"].astype(str).map(ob.rename(index=str))
        dias = (e["_ob"] - e["_ac"]).dt.days
        dias = dias[(dias >= 0) & dias.notna()]
        if not dias.empty:
            out["dias_ate_credito"] = {"mediana": float(dias.median()), "p25": float(dias.quantile(.25)),
                                       "p75": float(dias.quantile(.75)), "n": int(len(dias))}
        c = e.dropna(subset=["id_agencia_conta", "ano"])
        if not c.empty:
            out["contas_por_ano"] = (c.groupby("ano").agg(planos=("id_instrumento", "count"),
                                                          contas=("id_agencia_conta", "nunique"))
                                     .assign(planos_por_conta=lambda x: x["planos"] / x["contas"]).reset_index())
    ee = d.get("mart_escolha_ente", pd.DataFrame())
    if not ee.empty:
        x = ee[ee["modulo"] == "Especiais"].dropna(subset=["ano"])
        piv = x.pivot_table(index="cnpj_ente", columns=x["ano"].astype(int), values="grupo_banco", aggfunc="first")
        trocas = []
        anos = sorted(piv.columns)
        for a, b in zip(anos, anos[1:]):
            z = piv[[a, b]].dropna()
            if len(z):
                trocas.append({"de": a, "para": b, "entes": len(z), "trocaram": int((z[a] != z[b]).sum()),
                               "para_caixa": int(((z[a] != "CAIXA") & (z[b] == "CAIXA")).sum()),
                               "sairam_caixa": int(((z[a] == "CAIXA") & (z[b] != "CAIXA")).sum())})
        out["trocas"] = pd.DataFrame(trocas)
    return out
