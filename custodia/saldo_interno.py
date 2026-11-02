"""Saldo das contas a partir de base interna da CAIXA (quando a fonte pública está desatualizada).

Por que existe: desde mai/2025 a API do Transferegov não traz extrato (saldo e lançamentos) das contas
CAIXA das Transferências Especiais; o saldo publicado dessas contas é o de 30/04/2025. A própria CAIXA tem
esse saldo nos sistemas internos.

Como usar:
  1. A cada carga o painel grava <dados>/internos/contas_caixa_para_consulta.csv com agência e conta de todas
     as contas CAIXA das Transferências Especiais (só dados públicos do Transferegov).
  2. A área responsável extrai o saldo dessas contas no sistema interno e grava em <dados>/internos/
     um arquivo saldos_caixa*.csv (separador ;) com as colunas: agencia;conta;saldo;data_saldo
     (conta com ou sem dígito; saldo em reais com vírgula ou ponto; data AAAA-MM-DD ou DD/MM/AAAA).
  3. Na carga seguinte o saldo interno substitui o público nessas contas, e o painel
     marca a fonte como "Base interna CAIXA".
Os arquivos internos ficam só no computador onde o painel roda; não são enviados a lugar nenhum.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from . import normaliza

log = logging.getLogger(__name__)
FONTE_PUBLICA, FONTE_INTERNA = "Transferegov", "Base interna CAIXA"


def _num(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    br = t.str.contains(",")
    t = t.where(~br, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(t, errors="coerce")


def _so_digitos(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0")


def exportar_contas(contas: pd.DataFrame, pasta: Path) -> Path | None:
    c = contas[(contas["modulo"] == "Especiais") & (contas["grupo_banco"] == "CAIXA")]
    if c.empty:
        return None
    partes = c["id_agencia_conta"].astype(str).str.split("-", n=1, expand=True)
    out = pd.DataFrame({"agencia": partes[0], "conta": partes[1] if partes.shape[1] > 1 else "",
                        "cnpj_ente": c["cnpj_ente"], "ente": c["nome_ente"], "uf": c["uf"],
                        "id_plano_acao": c["id_instrumento"], "saldo_publicado": c["saldo"],
                        "data_saldo_publicado": c["data_saldo"]}).drop_duplicates(["agencia", "conta"])
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / "contas_caixa_para_consulta.csv"
    out.to_csv(arq, sep=";", index=False, decimal=",", encoding="utf-8-sig")
    return arq


def ler(pasta: Path) -> pd.DataFrame:
    arqs = sorted(pasta.glob("saldos_caixa*.csv")) if pasta.exists() else []
    if not arqs:
        return pd.DataFrame(columns=["chave", "saldo", "data_saldo"])
    partes = []
    for a in arqs:
        df = pd.read_csv(a, sep=";", dtype=str, encoding="utf-8-sig")
        df.columns = [c.strip().lower() for c in df.columns]
        if not {"agencia", "conta", "saldo"} <= set(df.columns):
            log.warning("%s sem as colunas agencia;conta;saldo — ignorado", a.name)
            continue
        d = normaliza.data(df["data_saldo"]) if "data_saldo" in df else pd.NaT
        partes.append(pd.DataFrame({"agencia": _so_digitos(df["agencia"]), "conta": _so_digitos(df["conta"]),
                                    "saldo": _num(df["saldo"]),
                                    "data_saldo": pd.Series(d).dt.strftime("%Y-%m-%d") if "data_saldo" in df else None,
                                    "_arq": a.name}))
    if not partes:
        return pd.DataFrame(columns=["chave", "saldo", "data_saldo"])
    x = pd.concat(partes, ignore_index=True).dropna(subset=["saldo"])
    x = x.sort_values(["data_saldo", "_arq"]).drop_duplicates(["agencia", "conta"], keep="last")
    return x


def aplicar(contas: pd.DataFrame, pasta: Path) -> tuple[pd.DataFrame, dict]:
    """Substitui o saldo das contas CAIXA das Especiais pelo da base interna, quando houver."""
    contas = contas.copy()
    contas["fonte_saldo"] = FONTE_PUBLICA
    interno = ler(pasta)
    resumo = {"arquivos": int(interno["_arq"].nunique()) if "_arq" in interno else 0, "contas_substituidas": 0}
    if interno.empty:
        return contas, resumo
    alvo = (contas["modulo"] == "Especiais") & (contas["grupo_banco"] == "CAIXA")
    partes = contas.loc[alvo, "id_agencia_conta"].astype(str).str.split("-", n=1, expand=True)
    ag = _so_digitos(partes[0])
    ct = _so_digitos(partes[1]) if partes.shape[1] > 1 else ag * 0
    idx = interno.set_index(["agencia", "conta"])
    # conta exata; senão, a conta interna informada com dígito (último caractere a mais)
    sem_dv = interno.assign(conta=interno["conta"].str[:-1]).drop_duplicates(["agencia", "conta"]).set_index(["agencia", "conta"])
    chaves = list(zip(ag, ct))
    saldo = [idx["saldo"].get(k, sem_dv["saldo"].get(k)) for k in chaves]
    data = [idx["data_saldo"].get(k, sem_dv["data_saldo"].get(k)) for k in chaves]
    s = pd.Series(saldo, index=ag.index, dtype="float64")
    achou = s.notna()
    i = s.index[achou]
    contas.loc[i, "saldo"] = s[achou]
    contas.loc[i, "data_saldo"] = pd.Series(data, index=ag.index)[achou]
    contas.loc[i, "fonte_saldo"] = FONTE_INTERNA
    resumo["contas_substituidas"] = int(achou.sum())
    log.info("Saldo interno CAIXA aplicado em %d contas", achou.sum())
    return contas, resumo
