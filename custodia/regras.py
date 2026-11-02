"""Regras de negócio: leitura de config/regras.yaml e acesso aos parâmetros pelo código da regra."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def carregar() -> dict:
    arq = RAIZ / "config" / "regras.yaml"
    return yaml.safe_load(arq.read_text("utf-8")) if arq.exists() else {}


def param(codigo: str, nome: str, padrao=None):
    return (carregar().get(codigo, {}).get("parametros") or {}).get(nome, padrao)


def nome(codigo: str) -> str:
    return carregar().get(codigo, {}).get("nome", codigo)


def tabela() -> pd.DataFrame:
    linhas = []
    for cod, r in carregar().items():
        p = r.get("parametros") or {}
        linhas.append({"codigo": cod, "nome_regra": r.get("nome"), "frente": r.get("frente"),
                       "descricao_regra": " ".join(str(r.get("descricao", "")).split()),
                       "parametros": "; ".join(f"{k} = {v}" for k, v in p.items()) or "—",
                       "base": r.get("base"), "status_regra": r.get("status")})
    return pd.DataFrame(linhas)


@lru_cache(maxsize=1)
def perguntas() -> pd.DataFrame:
    arq = RAIZ / "config" / "perguntas.yaml"
    if not arq.exists():
        return pd.DataFrame()
    linhas = []
    for frente, itens in (yaml.safe_load(arq.read_text("utf-8")) or {}).items():
        for i in itens:
            linhas.append({"frente": frente, "pergunta": i["pergunta"], "tela": i.get("tela"),
                           "regras": ", ".join(i.get("regras", [])), "situacao": i.get("situacao", "respondida"),
                           "observacao": i.get("obs", "")})
    return pd.DataFrame(linhas)
