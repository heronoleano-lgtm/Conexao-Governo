"""Perfil dos dados publicados: resume cada tabela em CSV pequeno, para calibrar regras e conferir a carga.

    python -m custodia.perfil           # grava em <dados>/perfil/
Não grava nomes de pessoas físicas nem documentos: só contagens, somas e distribuições.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import config, storage


def _perfil_colunas(nome: str, df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for c in df.columns:
        s = df[c]
        num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        try:
            unicos = int(s.nunique(dropna=True))
        except TypeError:
            unicos = -1
        top = ""
        if not num and 0 < unicos <= 60 and not c.startswith(("cnpj", "doc", "nome", "objeto", "favorecido")):
            top = " | ".join(f"{k}={v}" for k, v in s.astype(str).value_counts().head(8).items())
        linhas.append({"tabela": nome, "coluna": c, "tipo": str(s.dtype), "linhas": len(s),
                       "pct_nulo": round(float(s.isna().mean()) * 100, 1) if len(s) else 0, "distintos": unicos,
                       "min": s.min() if num and len(s) else (str(s.dropna().min())[:20] if c.startswith("data") and s.notna().any() else ""),
                       "max": s.max() if num and len(s) else (str(s.dropna().max())[:20] if c.startswith("data") and s.notna().any() else ""),
                       "soma": float(s.sum()) if num and len(s) else "", "valores_mais_comuns": top})
    return pd.DataFrame(linhas)


def _agregados(m: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    instr, contas = m.get("fato_instrumento", pd.DataFrame()), m.get("fato_conta", pd.DataFrame())
    fluxo, pipe = m.get("fato_fluxo", pd.DataFrame()), m.get("fato_pipeline", pd.DataFrame())
    if not instr.empty:
        out["instrumentos_modulo_ano_banco"] = instr.groupby(["modulo", "ano", "grupo_banco"], dropna=False).agg(
            valor=("valor", "sum"), instrumentos=("id_instrumento", "count"), entes=("cnpj_ente", "nunique")).reset_index()
        if "fim_vigencia" in instr:
            d = instr[instr["modulo"] == "Discricionárias"].copy()
            if not d.empty:
                d["ano_fim"] = d["fim_vigencia"].astype(str).str.slice(0, 7)
                out["convenios_fim_vigencia_mes"] = d.groupby(["ano_fim", "grupo_banco", "ativo"], dropna=False).agg(
                    valor=("valor", "sum"), desembolsado=("desembolsado", "sum"), n=("id_instrumento", "count")).reset_index()
    if not contas.empty:
        c = contas.copy()
        c["mes_saldo"] = c["data_saldo"].astype(str).str.slice(0, 7)
        out["contas_saldo_por_mes_do_saldo"] = c.groupby(["modulo", "grupo_banco", "mes_saldo"], dropna=False).agg(
            saldo=("saldo", "sum"), contas=("id_instrumento", "count")).reset_index()
        faixas = pd.cut(c["saldo"].fillna(0), [-1e18, 0, 1e4, 1e5, 1e6, 1e7, 1e8, 1e18],
                        labels=["≤0", "até 10 mil", "10–100 mil", "100 mil–1 mi", "1–10 mi", "10–100 mi", ">100 mi"])
        out["contas_faixa_saldo"] = c.assign(faixa=faixas).groupby(["modulo", "grupo_banco", "faixa"], observed=True).agg(
            saldo=("saldo", "sum"), contas=("id_instrumento", "count")).reset_index()
        top = c.groupby(["modulo", "grupo_banco", "cnpj_ente"])["saldo"].sum().reset_index()
        top["rank"] = top.groupby(["modulo", "grupo_banco"])["saldo"].rank(ascending=False)
        out["concentracao_saldo"] = top.groupby(["modulo", "grupo_banco"]).apply(
            lambda g: pd.Series({"entes": len(g), "saldo": g["saldo"].sum(),
                                 "pct_top10": g.nlargest(10, "saldo")["saldo"].sum() / max(g["saldo"].sum(), 1),
                                 "pct_top100": g.nlargest(100, "saldo")["saldo"].sum() / max(g["saldo"].sum(), 1)}),
            include_groups=False).reset_index()
    if not fluxo.empty:
        out["fluxo_mes_tipo"] = fluxo.groupby(["modulo", "mes", "tipo_movimento", "grupo_origem"], dropna=False).agg(
            valor=("valor", "sum"), lancamentos=("valor", "size")).reset_index()
    if not pipe.empty:
        p = pipe.copy()
        p["mes_empenho"] = p["data_empenho"].astype(str).str.slice(0, 7)
        p["mes_ob"] = p["data_ob"].astype(str).str.slice(0, 7)
        out["pipeline_mes_empenho"] = p.groupby(["mes_empenho", "grupo_banco"], dropna=False).agg(
            empenhado=("valor_empenho", "sum"), pago=("valor_pago", "sum"), a_creditar=("a_creditar", "sum"),
            dias_mediana=("dias_ate_pagamento", "median")).reset_index()
        out["pipeline_mes_ob"] = p.groupby(["mes_ob"], dropna=False).agg(pago=("valor_pago", "sum")).reset_index()
    pe = m.get("mart_perfil_ente", pd.DataFrame())
    if not pe.empty:
        out["perfil_rotacao"] = pe.groupby(["perfil", "rotacao"], dropna=False).agg(
            entes=("cnpj_ente", "count"), valor=("valor_total", "sum")).reset_index()
    return out


def gerar(cfg: dict | None = None) -> Path:
    cfg = cfg or config.carregar()
    cam = config.caminhos(cfg)
    atual = (cam.marts / "ATUAL.txt").read_text().strip()
    pasta = cam.marts / atual
    destino = cam.dados / "perfil"
    destino.mkdir(parents=True, exist_ok=True)
    m, perfis = {}, []
    for arq in sorted(pasta.glob(f"*{storage.EXT}")):
        df = storage.ler(arq.with_suffix(""))
        m[arq.stem] = df
        perfis.append(_perfil_colunas(arq.stem, df))
    pd.concat(perfis, ignore_index=True).to_csv(destino / "colunas.csv", index=False, sep=";", decimal=",",
                                                encoding="utf-8-sig")
    for nome, df in _agregados(m).items():
        df.to_csv(destino / f"{nome}.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    print(f"Perfil gravado em {destino}")
    return destino


if __name__ == "__main__":
    gerar()
    sys.exit(0)
