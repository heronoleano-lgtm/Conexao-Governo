"""Gravação e leitura de tabelas.

Produção: Parquet (pyarrow). Testes sem pyarrow: CUSTODIA_STORAGE=pickle.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

MODO = os.environ.get("CUSTODIA_STORAGE", "parquet")
EXT = ".parquet" if MODO == "parquet" else ".pkl"


def caminho(base: Path, nome: str) -> Path:
    return base / f"{nome}{EXT}"


def gravar(df: pd.DataFrame, destino: Path) -> Path:
    destino = destino.with_suffix(EXT)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(EXT + ".tmp")
    if MODO == "parquet":
        df.to_parquet(tmp, index=False)
    else:
        df.to_pickle(tmp)
    os.replace(tmp, destino)
    return destino


def ler(origem: Path, colunas: list[str] | None = None) -> pd.DataFrame:
    origem = origem.with_suffix(EXT)
    if not origem.exists():
        return pd.DataFrame(columns=colunas or [])
    if MODO == "parquet":
        df = pd.read_parquet(origem, columns=colunas)
    else:
        df = pd.read_pickle(origem)
        if colunas:
            df = df[[c for c in colunas if c in df.columns]]
    return df


def existe(origem: Path) -> bool:
    return origem.with_suffix(EXT).exists()
