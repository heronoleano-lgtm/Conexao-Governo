"""Histórico de mudanças (SCD tipo 2).

A API só mostra o estado de hoje. Aqui gravamos uma versão nova de cada registro
apenas quando algo mudou, com valido_de / valido_ate. Isso permite saber quando um
plano trocou de banco, quando um saldo subiu e reconstruir qualquer dia passado.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd

from . import storage

META = ["_hash", "valido_de", "valido_ate"]
CHAVE_LINHA = "_chave_linha"   # usada quando a tabela não tem identificador único: a própria linha é a chave
REPETICOES = "_repeticoes"      # linhas idênticas na fonte viram uma linha com a contagem


def _hash(df: pd.DataFrame, colunas: list[str]) -> pd.Series:
    """Impressão digital de cada linha (vetorizada; rápida em milhões de linhas)."""
    partes = df[colunas].astype("object")
    partes = partes.where(partes.notna(), "∅").astype(str)
    partes.columns = [str(c) for c in partes.columns]
    h = pd.util.hash_pandas_object(partes, index=False, categorize=False)
    return h.map(lambda v: f"{v:016x}")


def escolher_chave(df: pd.DataFrame, sugerida: str | None = None) -> str:
    """Chave do histórico: a sugerida (se única), senão a primeira coluna id_* única, senão a própria linha."""
    if sugerida and sugerida in df.columns and not df[sugerida].duplicated().any():
        return sugerida
    for c in df.columns:
        if str(c).startswith("id_") and df[c].notna().all() and not df[c].duplicated().any():
            return c
    return CHAVE_LINHA


def preparar(df: pd.DataFrame, chave: str) -> pd.DataFrame:
    """Para chave = linha: junta linhas idênticas (guardando quantas eram) e cria a chave pelo conteúdo."""
    if chave != CHAVE_LINHA:
        return df
    cols = [c for c in df.columns if c not in META]
    h = _hash(df, cols)
    out = df.assign(**{CHAVE_LINHA: h.values})
    cont = out.groupby(CHAVE_LINHA).size()
    out = out.drop_duplicates(CHAVE_LINHA).copy()
    out[REPETICOES] = out[CHAVE_LINHA].map(cont).astype(int)
    return out


ARQUIVO_ATE = "__ate_"   # sufixo do histórico arquivado quando a chave muda: <tabela>__ate_AAAA-MM-DD


def arquivar(arquivo: Path, dia: date) -> Path:
    """Guarda o histórico inteiro com outro nome (nada se perde) para começar um novo com outra chave."""
    base = f"{arquivo.name}{ARQUIVO_ATE}{dia.isoformat()}"
    destino, n = storage.caminho(arquivo.parent, base), 1
    while destino.exists():
        n += 1
        destino = storage.caminho(arquivo.parent, f"{base}_{n}")
    storage.caminho(arquivo.parent, arquivo.name).rename(destino)
    return destino


def atualizar(atual: pd.DataFrame, chave: str, arquivo: Path, dia: date) -> dict:
    """Mescla o estado de hoje no histórico. Devolve contagem de novos, alterados e removidos."""
    dia_s = dia.isoformat()
    hist = storage.ler(arquivo)
    if atual.empty:
        return {"novos": 0, "alterados": 0, "removidos": 0, "versoes": len(hist)}
    if not hist.empty and chave not in hist.columns:
        # o histórico existente foi gravado com outra chave (ex.: id deixou de ser único na fonte):
        # arquiva inteiro e começa um novo hoje — antes isto derrubava a carga (KeyError '_chave_linha')
        arquivar(arquivo, dia)
        hist = hist.iloc[0:0]

    atual = preparar(atual, chave)
    atual = atual.drop_duplicates(chave, keep="last").copy()
    colunas = sorted(c for c in atual.columns if c not in META)
    atual["_hash"] = _hash(atual, colunas)
    atual[chave] = atual[chave].astype(str)
    if not hist.empty and len(str(hist["_hash"].iloc[0])) != 16:
        # histórico gravado com a impressão digital antiga: recalcula para não gerar versões falsas
        cols_h = sorted(c for c in hist.columns if c not in META)
        hist = hist.copy()
        hist["_hash"] = _hash(hist, cols_h).values

    if hist.empty:
        atual["valido_de"], atual["valido_ate"] = dia_s, None
        storage.gravar(atual, arquivo)
        return {"novos": len(atual), "alterados": 0, "removidos": 0, "versoes": len(atual)}

    hist[chave] = hist[chave].astype(str)
    # rodar de novo no mesmo dia: desfaz o que foi gravado hoje antes de mesclar
    if (hist["valido_de"] == dia_s).any() and (hist["valido_de"] < dia_s).any():
        hist = hist[hist["valido_de"] != dia_s].copy()
        hist.loc[hist["valido_ate"] == dia_s, "valido_ate"] = None
    elif (hist["valido_de"] == dia_s).all():
        hist = hist.iloc[0:0]
        atual["valido_de"], atual["valido_ate"] = dia_s, None
        storage.gravar(atual, arquivo)
        return {"novos": len(atual), "alterados": 0, "removidos": 0, "versoes": len(atual)}
    vigente = hist["valido_ate"].isna()
    cur = hist.loc[vigente, [chave, "_hash"]]

    junto = atual[[chave, "_hash"]].merge(cur, on=chave, how="outer", suffixes=("", "_ant"), indicator=True)
    novos = junto.loc[junto["_merge"] == "left_only", chave]
    removidos = junto.loc[junto["_merge"] == "right_only", chave]
    alterados = junto.loc[(junto["_merge"] == "both") & (junto["_hash"] != junto["_hash_ant"]), chave]

    fechar = vigente & hist[chave].isin(set(removidos) | set(alterados))
    hist.loc[fechar, "valido_ate"] = dia_s

    entrar = atual[atual[chave].isin(set(novos) | set(alterados))].copy()
    entrar["valido_de"], entrar["valido_ate"] = dia_s, None
    saida = pd.concat([hist, entrar], ignore_index=True)
    storage.gravar(saida, arquivo)
    return {"novos": len(novos), "alterados": len(alterados), "removidos": len(removidos), "versoes": len(saida)}


def mudancas_do_dia(arquivo: Path, chave: str, dia: date, campos: list[str]) -> pd.DataFrame:
    """Registros que mudaram no dia, com o valor anterior dos campos de interesse."""
    hist = storage.ler(arquivo)
    if hist.empty:
        return pd.DataFrame()
    dia_s = dia.isoformat()
    hoje = hist[hist["valido_de"] == dia_s]
    antes = hist[hist["valido_ate"] == dia_s]
    if hoje.empty:
        return pd.DataFrame()
    campos = [c for c in campos if c in hist.columns]
    ant = antes[[chave] + campos].rename(columns={c: f"{c}_anterior" for c in campos})
    out = hoje.merge(ant, on=chave, how="left")
    out["primeira_vez"] = ~out[chave].isin(set(hist.loc[hist["valido_de"] < dia_s, chave]))
    return out


def serie_diaria(arquivo: Path, linhas: pd.DataFrame, dia: date) -> pd.DataFrame:
    """Acrescenta (ou substitui) as linhas do dia numa série temporal agregada."""
    hist = storage.ler(arquivo)
    linhas = linhas.assign(dia=dia.isoformat())
    if not hist.empty:
        hist = hist[hist["dia"] != dia.isoformat()]
    out = pd.concat([hist, linhas], ignore_index=True)
    storage.gravar(out, arquivo)
    return out


def como_era(hist: pd.DataFrame, dia: date) -> pd.DataFrame:
    d = dia.isoformat()
    if hist.empty:
        return hist
    vale = (hist["valido_de"] <= d) & (hist["valido_ate"].isna() | (hist["valido_ate"] > d))
    return hist[vale]


def verificar(atual: pd.DataFrame, chave: str, arquivo: Path, dia: date) -> dict:
    """Prova de que o histórico não perdeu nada: o estado reconstruído para o dia é idêntico à fonte do dia
    (mesmas linhas, mesmos valores, mesmas repetições)."""
    hist = storage.ler(arquivo)
    rec = como_era(hist, dia)
    fonte = preparar(atual, chave).drop_duplicates(chave, keep="last")
    cols = sorted(c for c in fonte.columns if c not in META)
    h_fonte = set(_hash(fonte.assign(**{chave: fonte[chave].astype(str)}), cols))
    h_rec = set(rec["_hash"]) if not rec.empty else set()
    linhas_fonte = int(len(atual))
    linhas_rec = int(rec[REPETICOES].sum()) if REPETICOES in rec else int(len(rec))
    perdeu = h_fonte - h_rec
    return {"ok": not perdeu and linhas_fonte == linhas_rec, "linhas_fonte": linhas_fonte,
            "linhas_reconstruidas": linhas_rec, "diferencas": len(perdeu ^ (h_rec - h_fonte))}
