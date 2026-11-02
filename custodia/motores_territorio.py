"""Tabelas prontas para o mapa executivo: uma linha por ente e uma por UF × modalidade × banco."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .referencias import COD_UF, REGIAO, UF_COD

FAIXAS_PORTE = [(0, 20_000, "Até 20 mil hab."), (20_000, 100_000, "20 a 100 mil hab."),
                (100_000, 500_000, "100 a 500 mil hab."), (500_000, float("inf"), "Mais de 500 mil hab.")]


def porte(pop: pd.Series, esfera: pd.Series) -> pd.Series:
    def um(p, e):
        if e == "Estadual":
            return "Estado"
        if p is None or pd.isna(p):
            return "Porte não informado"
        return next(r for a, b, r in FAIXAS_PORTE if a <= p < b)
    return pd.Series([um(p, e) for p, e in zip(pop, esfera)], index=pop.index)


def ente_resumo(instr: pd.DataFrame, contas: pd.DataFrame, pipe: pd.DataFrame, dim_ente: pd.DataFrame,
                potencial: pd.DataFrame, transf: pd.DataFrame, mun_ref: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ente com localização, perfil e valores por modalidade e banco."""
    if instr.empty or dim_ente.empty:
        return pd.DataFrame()
    e = dim_ente.copy()
    for c in ("populacao", "municipio", "esfera"):
        if c not in e:
            e[c] = None
    e["cod_uf"] = e["uf"].map(UF_COD)
    e["regiao"] = e["cod_uf"].fillna("0").str.slice(0, 1).map(REGIAO)
    e["porte"] = porte(pd.to_numeric(e["populacao"], errors="coerce"), e["esfera"])
    # coordenadas: município pelo IBGE; estado pelo centro dos seus municípios
    if mun_ref is not None and not mun_ref.empty:
        coord = mun_ref.set_index("cod_ibge")[["lat", "lon"]]
        e = e.merge(coord, left_on="cod_ibge", right_index=True, how="left")
        centro = mun_ref.groupby("uf")[["lat", "lon"]].mean()
        sem = e["lat"].isna()
        e.loc[sem, "lat"] = e.loc[sem, "uf"].map(centro["lat"])
        e.loc[sem, "lon"] = e.loc[sem, "uf"].map(centro["lon"])
    else:
        e["lat"], e["lon"] = np.nan, np.nan

    i = instr[instr["cnpj_ente"].fillna("") != ""]
    pv = i.pivot_table(index="cnpj_ente", columns="modulo", values="valor", aggfunc="sum", fill_value=0)
    for m, c in (("Especiais", "valor_especiais"), ("Fundo a Fundo", "valor_fundo_a_fundo"),
                 ("Discricionárias", "valor_convenios")):
        e[c] = e["cnpj_ente"].map(pv[m]).fillna(0) if m in pv else 0.0
    com = i[i["grupo_banco"] != "(sem banco)"]
    tot = com.groupby("cnpj_ente")["valor"].sum()
    cx = com[com["grupo_banco"] == "CAIXA"].groupby("cnpj_ente")["valor"].sum()
    e["valor"] = e[["valor_especiais", "valor_fundo_a_fundo", "valor_convenios"]].sum(axis=1)
    e["valor_caixa"] = e["cnpj_ente"].map(cx).fillna(0)
    e["valor_concorrente"] = e["cnpj_ente"].map(tot).fillna(0) - e["valor_caixa"]
    e["part_caixa"] = e["valor_caixa"] / e["cnpj_ente"].map(tot).replace(0, np.nan)
    princ = (com.groupby(["cnpj_ente", "grupo_banco"])["valor"].sum().reset_index()
             .sort_values("valor").drop_duplicates("cnpj_ente", keep="last").set_index("cnpj_ente")["grupo_banco"])
    e["banco_principal"] = e["cnpj_ente"].map(princ).fillna("(sem banco)")
    if not contas.empty:
        c = contas.drop_duplicates(["modulo", "id_agencia_conta"])
        e["saldo_caixa"] = e["cnpj_ente"].map(c[c["grupo_banco"] == "CAIXA"].groupby("cnpj_ente")["saldo"].sum()).fillna(0)
        e["saldo_concorrente"] = e["cnpj_ente"].map(c[c["grupo_banco"] != "CAIXA"].groupby("cnpj_ente")["saldo"].sum()).fillna(0)
        est = "saldo_estimado" if "saldo_estimado" in c else "saldo"      # regra SAL-01 (estimado ao lado do publicado)
        e["saldo_caixa_estimado"] = e["cnpj_ente"].map(c[c["grupo_banco"] == "CAIXA"].groupby("cnpj_ente")[est].sum()).fillna(0)
        e["saldo_concorrente_estimado"] = e["cnpj_ente"].map(
            c[c["grupo_banco"] != "CAIXA"].groupby("cnpj_ente")[est].sum()).fillna(0)
    else:
        e["saldo_caixa"] = e["saldo_concorrente"] = 0.0
        e["saldo_caixa_estimado"] = e["saldo_concorrente_estimado"] = 0.0
    e["a_creditar"] = e["cnpj_ente"].map(pipe.groupby("cnpj_ente")["a_creditar"].sum()).fillna(0) if not pipe.empty else 0.0
    if potencial is not None and not potencial.empty:
        p = potencial.set_index("cnpj_ente")
        for c in ("segmento", "score", "potencial_custodia", "resultado_estimado_ano", "acao_recomendada",
                  "pagamentos_fora_caixa"):
            e[c] = e["cnpj_ente"].map(p[c]) if c in p else None
    for c, padrao in (("segmento", None), ("score", 0), ("potencial_custodia", 0), ("resultado_estimado_ano", 0),
                      ("acao_recomendada", None), ("pagamentos_fora_caixa", 0)):
        if c not in e:
            e[c] = padrao
    # FaF não entra no segmento (conta sempre BB): quem só tem FaF fica como "Só Fundo a Fundo"
    padrao_seg = pd.Series(np.where(e["valor_fundo_a_fundo"] > 0, "Só Fundo a Fundo", "Sem banco definido"), index=e.index)
    e["segmento"] = e["segmento"].fillna(padrao_seg)
    if transf is not None and not transf.empty:
        # quem transfere e está no cadastro fica com o valor; fundo fora do cadastro vai para o ente do plano
        conhecidos = set(e["cnpj_ente"])
        dono = transf["cnpj_ente"].where(transf["cnpj_ente"].isin(conhecidos),
                                         transf["cnpj_plano"] if "cnpj_plano" in transf else None)
        e["transf_secundaria"] = e["cnpj_ente"].map(transf.assign(_d=dono).groupby("_d")["valor_12_meses"].sum()).fillna(0)
    else:
        e["transf_secundaria"] = 0.0
    return e.drop(columns=["cod_uf"])


def uf_modalidade(instr: pd.DataFrame, contas: pd.DataFrame) -> pd.DataFrame:
    """UF × modalidade × banco: valor, instrumentos e saldo. Base dos gráficos de movimento por modalidade."""
    if instr.empty:
        return pd.DataFrame(columns=["uf", "modulo", "grupo_banco", "valor", "instrumentos", "saldo"])
    g = instr.groupby(["uf", "modulo", "grupo_banco"], dropna=False, as_index=False).agg(
        valor=("valor", "sum"), instrumentos=("id_instrumento", "count"))
    if not contas.empty:
        s = contas.drop_duplicates(["modulo", "id_agencia_conta"]).groupby(
            ["uf", "modulo", "grupo_banco"], dropna=False, as_index=False)["saldo"].sum()
        g = g.merge(s, on=["uf", "modulo", "grupo_banco"], how="outer")
    else:
        g["saldo"] = 0.0
    g[["valor", "instrumentos", "saldo"]] = g[["valor", "instrumentos", "saldo"]].fillna(0)
    g["cod_uf"] = g["uf"].map(UF_COD)
    return g
