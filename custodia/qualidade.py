"""Checagens de qualidade que acompanham cada carga."""
from __future__ import annotations

import pandas as pd


def checar(manifestos: list[dict], custodia_hoje: pd.DataFrame, serie: pd.DataFrame, cfg_q: dict) -> pd.DataFrame:
    linhas = []
    for m in manifestos:
        if m.get("erro"):
            linhas.append(("erro", m["modulo"], "fonte", f"Falha geral: {m['erro']}"))
        for c in m.get("cargas", []):
            nome = c.get("endpoint") or c.get("arquivo")
            if c.get("erro"):
                linhas.append(("erro", m["modulo"], nome, c["erro"]))
            elif "esperado" in c:
                dif = abs(c["esperado"] - c["carregado"])
                tol = cfg_q.get("tolerancia_contagem", 0) * max(c["esperado"], 1)
                st = "ok" if dif <= tol else "alerta"
                linhas.append((st, m["modulo"], nome, f"{c['carregado']:,} de {c['esperado']:,} linhas".replace(",", ".")))
            else:
                linhas.append(("ok", m["modulo"], nome, c.get("motivo") or f"{c.get('linhas') or 0:,} linhas".replace(",", ".")))
        for mud in m.get("mudancas_esquema", []):
            linhas.append(("alerta", m["modulo"], mud["endpoint"], f"Esquema: {mud['tipo']} {mud['colunas']}".strip()))
    if not custodia_hoje.empty:
        for _, r in custodia_hoje.iterrows():
            if r["contas"] and r["cobertura"] < 0.5:
                linhas.append(("alerta", r["modulo"], f"saldo {r['grupo_banco']}",
                               f"Cobertura de saldo de {r['cobertura']:.0%}: trate o saldo como estimativa"))
    if not serie.empty and serie["dia"].nunique() >= 2:
        dias = sorted(serie["dia"].unique())
        a, b = serie[serie["dia"] == dias[-2]], serie[serie["dia"] == dias[-1]]
        j = b.merge(a, on=["modulo", "grupo_banco"], suffixes=("", "_ant"))
        lim = cfg_q.get("variacao_max_custodia", 0.25)
        for _, r in j.iterrows():
            if r["valor_ant"] and abs(r["valor"] / r["valor_ant"] - 1) > lim:
                linhas.append(("alerta", r["modulo"], f"valor {r['grupo_banco']}",
                               f"Variação de {r['valor'] / r['valor_ant'] - 1:+.0%} em um dia"))
    return pd.DataFrame(linhas, columns=["status", "modulo", "item", "detalhe"])
