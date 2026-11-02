"""Tabelas do painel para FUNDEB, Saúde (FNS), Educação (FNDE) e Assistência social (FNAS)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .ingest_api import ultimo_bruto
from .normaliza import doc, grupo_banco, serie_banco

FONTE_TESOURO = {"FUNDEB": ("Educação · FUNDEB", "FUNDEB"), "AJUSTE FUNDEB": ("Educação · FUNDEB", "FUNDEB"),
                 "FPM": ("Constitucional", "FPM"), "FPM 1%": ("Constitucional", "FPM"), "FPE": ("Constitucional", "FPE")}
COLS = ["fonte", "area", "ano", "mes", "uf", "cod_ibge", "municipio", "cnpj", "favorecido", "valor", "grupo_banco",
        "detalhe"]


def _mun7(cod6: pd.Series, mun_ref: pd.DataFrame | None) -> pd.Series:
    c = cod6.fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
    if mun_ref is None or mun_ref.empty:
        return c.where(c.str.len() == 7, None)
    mapa = mun_ref.assign(_6=mun_ref["cod_ibge"].astype(str).str[:6]).drop_duplicates("_6").set_index("_6")["cod_ibge"]
    return np.where(c.str.len() == 7, c, c.map(mapa))


def construir(bruto: Path, mun_ref: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    L = lambda n: ultimo_bruto(bruto, "outras", n)  # noqa: E731
    partes, siafi = [], {}
    t = L("tesouro_transferencias")
    if not t.empty:
        f = t["transferencia"].map(lambda x: FONTE_TESOURO.get(str(x).strip(), ("Constitucional", str(x).strip())))
        partes.append(pd.DataFrame({
            "fonte": f.map(lambda x: x[1]), "area": f.map(lambda x: x[0]),
            "ano": pd.to_numeric(t["ano"], errors="coerce"), "mes": pd.to_numeric(t["mes"], errors="coerce"),
            "uf": t["uf"], "cod_ibge": t["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True),
            "municipio": t["municipio"], "cnpj": None, "favorecido": None,
            "valor": pd.to_numeric(t["valor"], errors="coerce").fillna(0),
            # o Tesouro não publica o banco do FPM/FPE (red team 02/11: o "BB" fixo aparecia como banco publicado e
            # contradizia a regra OUT-01); fica vazio
            "grupo_banco": None,
            "detalhe": t["transferencia"]}))
        if "codigo_siafi" in t:
            siafi = t.drop_duplicates("codigo_siafi").set_index(t.drop_duplicates("codigo_siafi")["codigo_siafi"].astype(str))["cod_ibge"].astype(str).to_dict()

    ent, ct, pg, sd = L("fns_entidades"), L("fns_contas"), L("fns_pagamentos"), L("fns_saldos")
    contas = pd.DataFrame()
    if not ent.empty:
        ent = ent.assign(cnpj=doc(ent["cpfCnpj"]), cod_ibge=_mun7(ent["codigoMunicipioIBGE"], mun_ref))
        ent.loc[ent["esferaAdministrativa"] == "ESTADUAL", "cod_ibge"] = None
        info = ent.drop_duplicates("cnpj").set_index("cnpj")
    else:
        # sem o cadastro de entidades os repasses e as contas continuam valendo (só faltam nome e município);
        # antes, a falta desse arquivo apagava a saúde inteira do painel
        info = pd.DataFrame(columns=["cod_ibge", "municipio", "razaoSocial", "uf", "esferaAdministrativa"],
                            index=pd.Index([], name="cnpj"))
    if not pg.empty or not ct.empty:
        if not pg.empty:
            # a fonte repete linhas idênticas (01/11: 276 linhas, R$ 109,7 mi); identidade total = mesma linha
            pg = pg.drop_duplicates()
            p = pg.assign(cnpj=doc(pg["cpfCnpj"]))
            banco = serie_banco(p.get("codigoBanco", pd.Series("", index=p.index)).astype(str))
            partes.append(pd.DataFrame({
                "fonte": "FNS", "area": "Saúde", "ano": pd.to_numeric(p.get("anoPagamento"), errors="coerce"),
                "mes": pd.to_numeric(p.get("mesPagamento"), errors="coerce"), "uf": p.get("uf"),
                "cod_ibge": p["cnpj"].map(info["cod_ibge"]), "municipio": p["cnpj"].map(info["municipio"]),
                "cnpj": p["cnpj"], "favorecido": p["cnpj"].map(info["razaoSocial"]),
                "valor": pd.to_numeric(p.get("valorLiquido", p.get("valorTotal")), errors="coerce").fillna(0),
                "grupo_banco": banco.map(grupo_banco), "detalhe": p.get("nomeBloco")}))
        if not ct.empty:
            c = ct.assign(cnpj=doc(ct["cpfCnpj"]))
            b = serie_banco(c["codigoBanco"].astype(str))
            # UF pelo cadastro; sem cadastro, pela UF dos pagamentos ao mesmo CNPJ (red team 02/11: UF 100% vazia)
            uf_pag = (pg.assign(cnpj=doc(pg["cpfCnpj"])).dropna(subset=["uf"]).drop_duplicates("cnpj").set_index("cnpj")["uf"]
                      if not pg.empty and "uf" in pg else pd.Series(dtype=object))
            contas = pd.DataFrame({
                "cnpj": c["cnpj"], "favorecido": c["cnpj"].map(info["razaoSocial"]),
                "uf": c["cnpj"].map(info["uf"]).fillna(c["cnpj"].map(uf_pag)),
                "cod_ibge": c["cnpj"].map(info["cod_ibge"]), "municipio": c["cnpj"].map(info["municipio"]),
                "esfera": c["cnpj"].map(info["esferaAdministrativa"]).map(
                    lambda v: v.capitalize() if isinstance(v, str) else v),
                "bloco": c.get("codigoBloco"), "grupo_banco": b.map(grupo_banco),
                "agencia": c["codigoAgencia"].astype(str), "conta": c["contaCorrente"].astype(str)})
            if not sd.empty:
                s = sd.assign(k=sd["codigoBanco"].astype(str) + "|" + sd["codigoAgencia"].astype(str) + "|" +
                              sd["contaCorrente"].astype(str)).drop_duplicates("k").set_index("k")
                k = c["codigoBanco"].astype(str) + "|" + contas["agencia"] + "|" + contas["conta"]
                contas["saldo"] = pd.to_numeric(k.map(s["saldo"]), errors="coerce").values
                contas["data_saldo"] = k.map(s["data_saldo"]).values
            contas = contas.drop_duplicates(["cnpj", "grupo_banco", "agencia", "conta"])
            # a mesma conta pode servir a mais de um bloco: saldo uma vez só
            dup = contas.duplicated(["grupo_banco", "agencia", "conta"])
            if "saldo" in contas:
                contas.loc[dup, "saldo"] = 0.0

    pt = L("portal_educacao_assistencia")
    if not pt.empty:
        # bancos aparecem como favorecidos (ex.: tarifas, agente operador); não são o ente nem custódia dele
        from .marts_crm import eh_banco
        pt = pt[~eh_banco(doc(pt["doc_favorecido"]))]
        cod = pt["codigo_siafi"].astype(str).str.replace(r"\.0$", "", regex=True).str.lstrip("0").map(
            {k.lstrip("0"): v for k, v in siafi.items()})
        partes.append(pd.DataFrame({
            "fonte": np.where(pt["area"] == "Educação", "FNDE", "FNAS"), "area": pt["area"],
            "ano": pd.to_numeric(pt["anomes"].str[:4], errors="coerce"), "mes": pd.to_numeric(pt["anomes"].str[4:], errors="coerce"),
            "uf": pt["uf"], "cod_ibge": cod, "municipio": pt["municipio"], "cnpj": doc(pt["doc_favorecido"]),
            "favorecido": pt["favorecido"], "valor": pd.to_numeric(pt["valor"], errors="coerce").fillna(0),
            "grupo_banco": None, "detalhe": pt["acao"]}))
    fato = pd.concat([x.reindex(columns=COLS) for x in partes], ignore_index=True) if partes else pd.DataFrame(columns=COLS)
    return {"fato_repasse_outros": fato, "fato_conta_saude": contas}


def doze_meses(fato: pd.DataFrame) -> pd.DataFrame:
    if fato.empty:
        return fato
    per = fato["ano"] * 12 + fato["mes"]
    fim = per.groupby(fato["fonte"]).transform("max")
    return fato[per > fim - 12]


def por_municipio(fato: pd.DataFrame, contas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por município com os repasses de 12 meses por área e a custódia da saúde por banco."""
    cols = ["cod_ibge", "uf", "municipio", "fundeb_12m", "fpm_12m", "saude_12m", "saude_caixa_12m", "educacao_12m",
            "assistencia_12m", "saldo_saude_caixa", "saldo_saude_concorrente", "part_caixa_saude"]
    if fato.empty:
        return pd.DataFrame(columns=cols)
    f = doze_meses(fato[fato["cod_ibge"].notna() & (fato["cod_ibge"].astype(str).str.len() == 7)])
    soma = lambda m: f[m].groupby("cod_ibge")["valor"].sum()  # noqa: E731
    out = f.groupby("cod_ibge").agg(uf=("uf", "first"), municipio=("municipio", "first"))
    out["fundeb_12m"] = soma(f["fonte"] == "FUNDEB")
    out["fpm_12m"] = soma(f["fonte"] == "FPM")
    out["saude_12m"] = soma(f["fonte"] == "FNS")
    out["saude_caixa_12m"] = soma((f["fonte"] == "FNS") & (f["grupo_banco"] == "CAIXA"))
    out["educacao_12m"] = soma(f["fonte"] == "FNDE")
    out["assistencia_12m"] = soma(f["fonte"] == "FNAS")
    if not contas.empty and "saldo" in contas:
        c = contas[contas["cod_ibge"].notna()]
        out["saldo_saude_caixa"] = c[c["grupo_banco"] == "CAIXA"].groupby("cod_ibge")["saldo"].sum()
        out["saldo_saude_concorrente"] = c[c["grupo_banco"] != "CAIXA"].groupby("cod_ibge")["saldo"].sum()
    # zero só onde a fonte existe e o município não recebeu; fonte ausente (ou sem município identificado) fica
    # vazia — não é R$ 0 (red team 02/11: sem o cadastro de entidades do FNS, a saúde aparecia zerada nos 5.570)
    presentes = {"fundeb_12m": "FUNDEB", "fpm_12m": "FPM", "saude_12m": "FNS", "saude_caixa_12m": "FNS",
                 "educacao_12m": "FNDE", "assistencia_12m": "FNAS"}
    com_mun = set(f["fonte"].unique())
    zerar = [c for c, fonte in presentes.items() if fonte in com_mun]
    if not contas.empty and "saldo" in contas and contas["cod_ibge"].notna().any():
        zerar += ["saldo_saude_caixa", "saldo_saude_concorrente"]
    out = out.fillna({c: 0.0 for c in zerar})
    out["part_caixa_saude"] = out["saude_caixa_12m"] / out["saude_12m"].replace(0, np.nan)
    return out.reset_index().reindex(columns=cols)


def oportunidades_saude(contas: pd.DataFrame, minimo: float = 100000) -> pd.DataFrame:
    """Fundos de saúde com saldo em conta do concorrente: o ente pode pedir conta em outro banco oficial (validar com jurídico e conformidade)."""
    cols = ["cnpj", "favorecido", "uf", "municipio", "esfera", "contas", "saldo_concorrente", "saldo_caixa",
            "banco_atual", "regra"]
    if contas.empty or "saldo" not in contas:
        return pd.DataFrame(columns=cols)
    g = contas.groupby("cnpj").agg(favorecido=("favorecido", "first"), uf=("uf", "first"), municipio=("municipio", "first"),
                                   esfera=("esfera", "first"), contas=("conta", "nunique"))
    g["saldo_concorrente"] = contas[contas["grupo_banco"] != "CAIXA"].groupby("cnpj")["saldo"].sum()
    g["saldo_caixa"] = contas[contas["grupo_banco"] == "CAIXA"].groupby("cnpj")["saldo"].sum()
    g["banco_atual"] = contas.groupby("cnpj")["grupo_banco"].agg(lambda s: ", ".join(sorted(set(s.dropna()))))
    g = g.fillna({"saldo_concorrente": 0.0, "saldo_caixa": 0.0})
    g["regra"] = "SAU-01"
    return g[g["saldo_concorrente"] >= minimo].sort_values("saldo_concorrente", ascending=False).reset_index()[cols]
