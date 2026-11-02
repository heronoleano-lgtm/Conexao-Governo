"""Dados de referência: entes do Siconfi (CNPJ <-> IBGE), municípios (coordenadas, nomes) e malhas do IBGE."""
from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path

import pandas as pd

from . import storage
from .http import Cliente
from .normaliza import doc, sem_acento

log = logging.getLogger(__name__)

# código IBGE da UF <-> sigla
UF_COD = {"RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17", "MA": "21", "PI": "22",
          "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
          "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53"}
COD_UF = {v: k for k, v in UF_COD.items()}
REGIAO = {"1": "Norte", "2": "Nordeste", "3": "Sudeste", "4": "Sul", "5": "Centro-Oeste"}
MALHA_BR = "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=UF"
MALHA_UF = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"


def _malhas(cli: Cliente, cfg_ref: dict, pasta: Path, validade_dias: int = 30) -> str:
    """Baixa as malhas (uma vez; renova a cada 30 dias). Brasil por UF + cada UF por município."""
    destino = pasta / "malhas"
    destino.mkdir(parents=True, exist_ok=True)
    alvos = [("BR", cfg_ref.get("malha_br", MALHA_BR))] + \
            [(uf, cfg_ref.get("malha_uf", MALHA_UF).format(uf=uf)) for uf in UF_COD]
    ok, falhas = 0, 0
    for nome, url in alvos:
        arq = destino / f"{nome}.json"
        if arq.exists() and time.time() - arq.stat().st_mtime < validade_dias * 86400:
            ok += 1
            continue
        try:
            r = cli.get(url)
            j = json.loads(r.content)
            if j.get("type") != "FeatureCollection":
                raise ValueError("não é GeoJSON")
            arq.write_text(json.dumps(j), "utf-8")
            ok += 1
        except Exception as e:
            falhas += 1
            log.warning("Malha %s indisponível: %s", nome, e)
    return f"{ok} malhas ok, {falhas} falhas"


def atualizar(cli: Cliente, cfg_ref: dict, pasta: Path) -> dict:
    status = {}
    try:
        j = cli.json(cfg_ref["siconfi_entes"])
        df = pd.DataFrame(j.get("items", []))
        if not df.empty:
            df["cnpj"] = doc(df.get("cnpj", pd.Series(dtype=object)))
            storage.gravar(df, pasta / "siconfi_entes")
        status["siconfi_entes"] = len(df)
    except Exception as e:
        log.warning("Siconfi indisponível: %s", e)
        status["siconfi_entes"] = f"erro: {e}"[:200]
    try:
        r = cli.get(cfg_ref["municipios_coordenadas"])
        df = pd.read_csv(io.StringIO(r.text), dtype={"codigo_ibge": str, "codigo_uf": str})
        storage.gravar(df, pasta / "municipios_coordenadas")
        status["municipios_coordenadas"] = len(df)
    except Exception as e:
        log.warning("Coordenadas indisponíveis: %s", e)
        status["municipios_coordenadas"] = f"erro: {e}"[:200]
    status["malhas"] = _malhas(cli, cfg_ref, pasta)
    return status


def entes_siconfi(pasta: Path) -> pd.DataFrame:
    df = storage.ler(pasta / "siconfi_entes")
    if df.empty:
        return pd.DataFrame(columns=["cnpj", "cod_ibge", "populacao", "esfera"])
    cols = [c for c in ["cnpj", "cod_ibge", "populacao", "esfera", "capital", "regiao"] if c in df.columns]
    out = df[cols].copy()
    out["cod_ibge"] = out["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True)
    return out.drop_duplicates("cnpj")


def municipios(pasta: Path) -> pd.DataFrame:
    """cod_ibge, municipio, uf, lat, lon e chave de nome (para casar 'MUNICIPIO DE X' quando falta o código)."""
    df = storage.ler(pasta / "municipios_coordenadas")
    if df.empty:
        return pd.DataFrame(columns=["cod_ibge", "municipio", "uf", "lat", "lon", "chave_nome"])
    cod = df["codigo_ibge"].astype(str).str.replace(r"\.0$", "", regex=True)
    uf = df["codigo_uf"].astype(str).str.replace(r"\.0$", "", regex=True).map(COD_UF) if "codigo_uf" in df \
        else cod.str.slice(0, 2).map(COD_UF)
    out = pd.DataFrame({"cod_ibge": cod, "municipio": df.get("nome"), "uf": uf,
                        "lat": df["latitude"], "lon": df["longitude"]})
    out["chave_nome"] = out["uf"].fillna("") + "|" + out["municipio"].map(sem_acento)
    return out


def coordenadas(pasta: Path) -> pd.DataFrame:
    m = municipios(pasta)
    return m[["cod_ibge", "lat", "lon"]] if not m.empty else pd.DataFrame(columns=["cod_ibge", "lat", "lon"])


def chave_nome_ente(nome: pd.Series, uf: pd.Series) -> pd.Series:
    """'MUNICIPIO DE SAO JOSE DO NORTE' + 'RS' -> 'RS|sao jose do norte'."""
    n = nome.fillna("").map(sem_acento).str.replace(
        r"^(prefeitura municipal de |prefeitura de |municipio de |municipio da |municipio do |municipio )", "", regex=True)
    return uf.fillna("") + "|" + n.str.strip()


def malha(pasta: Path, nome: str) -> dict | None:
    arq = pasta / "malhas" / f"{nome}.json"
    return json.loads(arq.read_text("utf-8")) if arq.exists() else None
