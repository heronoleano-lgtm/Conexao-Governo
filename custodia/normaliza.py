"""Padronização de bancos, textos, documentos e números."""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

BANCOS = {
    "104": ("CAIXA", "CAIXA"),
    "1": ("BB", "Banco do Brasil"),
    "4": ("BNB", "Banco do Nordeste"),
    "3": ("BASA", "Banco da Amazônia"),
    "70": ("BRB", "BRB"),
    "21": ("Banestes", "Banestes"),
    "37": ("Banpará", "Banpará"),
    "41": ("Banrisul", "Banrisul"),
    "47": ("Banese", "Banese"),
    "237": ("Bradesco", "Bradesco"),
    "341": ("Itaú", "Itaú Unibanco"),
    "33": ("Santander", "Santander"),
    "756": ("Sicoob", "Sicoob"),
    "748": ("Sicredi", "Sicredi"),
    "77": ("Inter", "Banco Inter"),
}

NOMES_PARA_CODIGO = {
    "caixa economica federal": "104",
    "caixa": "104",
    "banco do brasil": "1",
    "banco do nordeste": "4",
    "banco do nordeste do brasil": "4",
}


def sem_acento(texto) -> str:
    if texto is None or (isinstance(texto, float) and np.isnan(texto)):
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def codigo_banco(codigo, nome=None) -> str:
    """'001', '1', 1, 'Banco do Brasil' -> '1'. Vazio -> ''."""
    c = "" if codigo is None or (isinstance(codigo, float) and np.isnan(codigo)) else str(codigo).strip()
    c = re.sub(r"\.0$", "", c)
    c = c.lstrip("0")
    if c:
        return c
    n = sem_acento(nome)
    if n in NOMES_PARA_CODIGO:
        return NOMES_PARA_CODIGO[n]
    # nomes livres do CSV de propostas: "CAIXA ECONOMICA FEDERAL", "BANCO DO BRASIL SA", ...
    for trecho, cod in (("caixa econ", "104"), ("banco do brasil", "1"), ("nordeste", "4"), ("amazonia", "3"),
                        ("banrisul", "41"), ("banestes", "21"), ("bradesco", "237"), ("itau", "341"),
                        ("santander", "33"), ("sicoob", "756"), ("sicredi", "748"), ("brb", "70")):
        if trecho in n:
            return cod
    return ""


def grupo_banco(codigo: str) -> str:
    """CAIXA, BB, ou nome curto do concorrente; '(sem banco)' quando vazio."""
    if not codigo:
        return "(sem banco)"
    return BANCOS.get(codigo, (f"Banco {codigo}", ""))[0]


def serie_banco(codigos: pd.Series, nomes: pd.Series | None = None) -> pd.Series:
    if nomes is None:
        nomes = pd.Series([None] * len(codigos), index=codigos.index)
    return pd.Series([codigo_banco(c, n) for c, n in zip(codigos, nomes)], index=codigos.index, dtype="object")


def doc(serie: pd.Series, tamanho: int = 14) -> pd.Series:
    """Mantém só dígitos e completa com zeros à esquerda (CNPJ=14)."""
    s = serie.astype("object").where(serie.notna(), "")
    s = s.map(lambda v: re.sub(r"\D", "", re.sub(r"\.0$", "", str(v))))
    return s.map(lambda v: v.zfill(tamanho) if v else "")


def numero(serie: pd.Series) -> pd.Series:
    """Converte números em texto brasileiro ('1.234,56') ou americano para float."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)

    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        t = str(v).strip()
        if not t:
            return np.nan
        if "," in t:
            t = t.replace(".", "").replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return np.nan

    return serie.map(conv).astype(float)


def data(serie: pd.Series) -> pd.Series:
    s = serie.astype("object").where(serie.notna(), None)
    # aceita AAAA-MM-DD e DD/MM/AAAA
    br = s.astype(str).str.match(r"^\d{2}/\d{2}/\d{4}")
    out = pd.to_datetime(s.where(~br), errors="coerce", format="mixed")
    out_br = pd.to_datetime(s.where(br), errors="coerce", format="%d/%m/%Y")
    return out.fillna(out_br)


def ultimo_extrato_efetivo(fluxo: pd.DataFrame, grupos=("modulo", "grupo_origem"), minimo: float = 0.10) -> pd.Series:
    """Data do último lançamento do último mês com volume NORMAL de cada banco: pelo menos `minimo` × o número
    mediano de lançamentos por mês do banco. Um lançamento isolado depois de uma parada não faz o banco "voltar"
    (red team 02/11: um único lançamento CAIXA em set/2026 apagava o alerta de extrato parado, com 100% do saldo
    ainda de abr/2025)."""
    if fluxo is None or fluxo.empty:
        return pd.Series(dtype="datetime64[ns]")
    f = fluxo.assign(_d=data(fluxo["data"]))
    f = f[f["_d"].notna()]
    if f.empty:
        return pd.Series(dtype="datetime64[ns]")
    f = f.assign(_m=f["_d"].dt.to_period("M"))
    n = f.groupby(list(grupos) + ["_m"]).size().rename("n").reset_index()
    tipico = n.groupby(list(grupos))["n"].transform("median")
    ok = n[n["n"] >= minimo * tipico]
    ult_m = ok.groupby(list(grupos))["_m"].max()
    fx = f.merge(ult_m.rename("_um").reset_index(), on=list(grupos))
    return fx[fx["_m"] <= fx["_um"]].groupby(list(grupos))["_d"].max()


def conta_valida(chave: pd.Series) -> pd.Series:
    """Chave 'agência-conta' que identifica uma conta: tem agência e número de conta diferente de zero."""
    k = chave.fillna("").astype(str)
    partes = k.str.split("-", n=1)
    ag, ct = partes.str[0].fillna(""), partes.str[1].fillna("")
    return (ag != "") & (ct.str.strip("0") != "") & (k.str.len() > 2)


def col(df: pd.DataFrame, candidatos: list[str], padrao=None) -> pd.Series:
    """Primeira coluna existente entre candidatos (para CSVs com nomes variáveis)."""
    for c in candidatos:
        if c in df.columns:
            return df[c]
    return pd.Series([padrao] * len(df), index=df.index, dtype="object")


def chave_conta(serie: pd.Series) -> pd.Series:
    """Chave única de conta 'agência-conta' sem zeros à esquerda nem '.0' (a API grava '0095-576017788' numa
    tabela e '95-576017788' em outra). Vazio continua vazio."""
    def norm(v):
        if v is None or (isinstance(v, float) and v != v):
            return None
        t = str(v).strip()
        if not t or t.lower() in ("none", "nan"):
            return None
        partes = [re.sub(r"\.0$", "", x.strip()).lstrip("0") or "0" for x in t.split("-", 1)]
        return "-".join(partes)
    return serie.map(norm)
