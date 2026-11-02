"""Motores de inteligência de custódia.

Cada função recebe os fatos do dia e devolve um DataFrame pronto para o painel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CAIXA = "CAIXA"


def participacao(instr: pd.DataFrame) -> pd.DataFrame:
    """Valor e número de instrumentos por módulo, ano, UF e banco."""
    if instr.empty:
        return pd.DataFrame(columns=["modulo", "ano", "uf", "grupo_banco", "valor", "instrumentos", "entes"])
    g = (instr.assign(uf=instr["uf"].fillna("?"))
         .groupby(["modulo", "ano", "uf", "grupo_banco"], dropna=False, as_index=False)
         .agg(valor=("valor", "sum"), instrumentos=("id_instrumento", "count"), entes=("cnpj_ente", "nunique")))
    return g


def custodia(contas: pd.DataFrame) -> pd.DataFrame:
    """Saldo publicado por módulo e banco, com cobertura (contas com saldo / contas)."""
    cols = ["modulo", "grupo_banco", "contas", "contas_com_saldo", "cobertura", "saldo", "data_saldo_max",
            "saldo_estimado", "saldo_est_min", "saldo_est_max", "extrato_parado_em"]
    if contas.empty:
        return pd.DataFrame(columns=cols)
    c = contas.drop_duplicates(["modulo", "id_agencia_conta"])
    agg = dict(contas=("id_agencia_conta", "count"), contas_com_saldo=("saldo", lambda s: int(s.notna().sum())),
               saldo=("saldo", "sum"), data_saldo_max=("data_saldo", "max"))
    # saldo estimado (regra SAL-01) ao lado do publicado; sem reconstituição, estimado = publicado
    for x in ("saldo_estimado", "saldo_est_min", "saldo_est_max"):
        agg[x] = (x if x in c else "saldo", "sum")
    agg["extrato_parado_em"] = ("extrato_parado_em" if "extrato_parado_em" in c else "data_saldo",
                                lambda s: s.dropna().max() if "extrato_parado_em" in c and s.notna().any() else None)
    g = c.groupby(["modulo", "grupo_banco"], as_index=False).agg(**agg)
    g["cobertura"] = (g["contas_com_saldo"] / g["contas"]).round(3)
    return g[cols]


def pipeline(pipe: pd.DataFrame) -> pd.DataFrame:
    if pipe.empty:
        return pd.DataFrame(columns=["modulo", "grupo_banco", "uf", "a_creditar", "empenhos"])
    p = pipe[pipe["a_creditar"] > 0]
    return p.groupby(["modulo", "grupo_banco", "uf"], dropna=False, as_index=False).agg(
        a_creditar=("a_creditar", "sum"), empenhos=("id_empenho", "count"))


def vazamento(executores: pd.DataFrame) -> pd.DataFrame:
    """Planos com conta numa instituição e executor recebendo em outra."""
    cols = ["cnpj_ente", "nome_ente", "uf", "id_instrumento", "nome_executor", "cnpj_executor",
            "grupo_banco_plano", "grupo_banco", "valor_executor", "direcao"]
    if executores.empty:
        return pd.DataFrame(columns=cols)
    e = executores[(executores["grupo_banco_plano"].notna()) &
                   (executores["grupo_banco"] != executores["grupo_banco_plano"]) &
                   (executores["grupo_banco"] != "(sem banco)") &
                   (executores["grupo_banco_plano"] != "(sem banco)")].copy()
    e["direcao"] = np.where(e["grupo_banco_plano"] == CAIXA, "saída da CAIXA",
                            np.where(e["grupo_banco"] == CAIXA, "entrada na CAIXA", "entre concorrentes"))
    return e[cols].sort_values("valor_executor", ascending=False)


def perfil_entes(instr: pd.DataFrame, anos_recentes: int = 2) -> pd.DataFrame:
    """Perfil bancário de cada ente e rotação entre os dois últimos anos com dados."""
    cols = ["cnpj_ente", "nome_ente", "uf", "valor_total", "valor_caixa", "valor_concorrente", "part_caixa",
            "bancos", "perfil", "banco_ano_anterior", "banco_ano_atual", "rotacao"]
    i = instr[(instr["cnpj_ente"].fillna("") != "") & (instr["grupo_banco"] != "(sem banco)")]
    if i.empty:
        return pd.DataFrame(columns=cols)
    base = i.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "last"), uf=("uf", "last"),
                                      valor_total=("valor", "sum"),
                                      bancos=("grupo_banco", lambda s: " + ".join(sorted(set(s)))))
    base["valor_caixa"] = i[i["grupo_banco"] == CAIXA].groupby("cnpj_ente")["valor"].sum()
    base["valor_caixa"] = base["valor_caixa"].fillna(0)
    base["valor_concorrente"] = base["valor_total"] - base["valor_caixa"]
    base["part_caixa"] = (base["valor_caixa"] / base["valor_total"].replace(0, np.nan)).round(3)
    tem_caixa = base["bancos"].str.contains(CAIXA)
    so_caixa = base["bancos"] == CAIXA
    base["perfil"] = np.where(so_caixa, "só CAIXA", np.where(tem_caixa, "multibanco", "só concorrente"))

    # banco principal por ano (maior valor) e rotação
    anos = sorted(i["ano"].dropna().unique())
    if len(anos) >= 2:
        a_ant, a_atu = anos[-2], anos[-1]

        def principal(ano):
            x = i[i["ano"] == ano].groupby(["cnpj_ente", "grupo_banco"])["valor"].sum().reset_index()
            return x.sort_values("valor").drop_duplicates("cnpj_ente", keep="last").set_index("cnpj_ente")["grupo_banco"]

        base["banco_ano_anterior"] = principal(a_ant)
        base["banco_ano_atual"] = principal(a_atu)
        ant, atu = base["banco_ano_anterior"], base["banco_ano_atual"]
        base["rotacao"] = np.select(
            [ant.isna() | atu.isna(), (ant != CAIXA) & (atu == CAIXA), (ant == CAIXA) & (atu != CAIXA), ant != atu],
            ["sem comparação", "conquistado", "perdido", "trocou entre concorrentes"], default="estável")
    else:
        base["banco_ano_anterior"], base["banco_ano_atual"], base["rotacao"] = None, None, "sem comparação"
    return base.reset_index()[cols]


def janelas(instr: pd.DataFrame, contas: pd.DataFrame, perfil: pd.DataFrame, vaz: pd.DataFrame,
            saldo_alto: float = 1_000_000) -> pd.DataFrame:
    """Oportunidades em que a escolha ou a permanência do banco ainda pode mudar."""
    cols = ["cnpj_ente", "nome_ente", "uf", "modulo", "motivo", "valor", "referencia", "detalhe"]
    linhas = []
    esp = instr[instr["modulo"] == "Especiais"]
    sem = esp[esp["grupo_banco"] == "(sem banco)"]
    for motivo, filtro in [
        ("Plano sem banco definido", ~sem["situacao"].fillna("").str.upper().str.contains("IMPEDIDO")),
        ("Plano impedido e sem banco", sem["situacao"].fillna("").str.upper().str.contains("IMPEDIDO")),
    ]:
        x = sem[filtro]
        linhas.append(pd.DataFrame({"cnpj_ente": x["cnpj_ente"], "nome_ente": x["nome_ente"], "uf": x["uf"],
                                    "modulo": x["modulo"], "motivo": motivo, "valor": x["valor"],
                                    "referencia": x["codigo"], "detalhe": x["situacao"]}))
    pend = instr[(instr["grupo_banco"] != CAIXA) & (instr["grupo_banco"] != "(sem banco)") &
                 instr["situacao_conta"].fillna("").str.contains("Aguardando", case=False)]
    linhas.append(pd.DataFrame({"cnpj_ente": pend["cnpj_ente"], "nome_ente": pend["nome_ente"], "uf": pend["uf"],
                                "modulo": pend["modulo"], "motivo": "Conta ainda não ativa no concorrente",
                                "valor": pend["valor"], "referencia": pend["codigo"],
                                "detalhe": pend["grupo_banco"] + ": " + pend["situacao_conta"].fillna("")}))
    if not perfil.empty:
        ano_max = esp["ano"].max() if not esp.empty else None
        if pd.notna(ano_max):
            novos = esp[(esp["ano"] == ano_max) & (esp["grupo_banco"] != CAIXA) & (esp["grupo_banco"] != "(sem banco)")]
            multi = set(perfil.loc[perfil["perfil"] == "multibanco", "cnpj_ente"])
            n = novos[novos["cnpj_ente"].isin(multi)]
            linhas.append(pd.DataFrame({"cnpj_ente": n["cnpj_ente"], "nome_ente": n["nome_ente"], "uf": n["uf"],
                                        "modulo": n["modulo"],
                                        "motivo": "Ente multibanco com plano novo no concorrente",
                                        "valor": n["valor"], "referencia": n["codigo"],
                                        "detalhe": n["grupo_banco"] + f" em {int(ano_max)}"}))
    if not contas.empty:
        alto = contas[(contas["grupo_banco"] != CAIXA) & (contas["saldo"].fillna(0) >= saldo_alto)]
        linhas.append(pd.DataFrame({"cnpj_ente": alto["cnpj_ente"], "nome_ente": alto["nome_ente"], "uf": alto["uf"],
                                    "modulo": alto["modulo"], "motivo": "Saldo alto parado no concorrente",
                                    "valor": alto["saldo"], "referencia": alto["id_agencia_conta"],
                                    "detalhe": alto["grupo_banco"] + " · saldo em " + alto["data_saldo"].fillna("?").astype(str)}))
    if not vaz.empty:
        v = vaz[vaz["direcao"] == "saída da CAIXA"]
        linhas.append(pd.DataFrame({"cnpj_ente": v["cnpj_ente"], "nome_ente": v["nome_ente"], "uf": v["uf"],
                                    "modulo": "Especiais", "motivo": "Executor recebe em outro banco",
                                    "valor": v["valor_executor"], "referencia": v["id_instrumento"],
                                    "detalhe": v["nome_executor"].fillna("") + " · " + v["grupo_banco"]}))
    out = pd.concat([l for l in linhas if not l.empty] or [pd.DataFrame(columns=cols)], ignore_index=True)
    return out[cols].sort_values("valor", ascending=False)


def score(perfil: pd.DataFrame, contas: pd.DataFrame, jan: pd.DataFrame, vaz: pd.DataFrame,
          instr: pd.DataFrame, pesos: dict, anos_recentes: int = 2) -> pd.DataFrame:
    """Score 0-100 de prospecção por ente, com o motivo principal da nota."""
    cols = ["cnpj_ente", "nome_ente", "uf", "score", "motivo_principal", "valor_concorrente_recente",
            "saldo_concorrente", "valor_janelas", "multibanco", "valor_vazamento", "perfil", "rotacao"]
    if perfil.empty:
        return pd.DataFrame(columns=cols)
    s = perfil.set_index("cnpj_ente")[["nome_ente", "uf", "perfil", "rotacao"]].copy()
    anos = sorted(instr["ano"].dropna().unique())
    recentes = anos[-anos_recentes:] if anos else []
    conc = instr[(instr["ano"].isin(recentes)) & (instr["grupo_banco"] != CAIXA) & (instr["grupo_banco"] != "(sem banco)")]
    s["valor_concorrente_recente"] = conc.groupby("cnpj_ente")["valor"].sum()
    sal = contas[contas["grupo_banco"] != CAIXA]
    s["saldo_concorrente"] = sal.groupby("cnpj_ente")["saldo"].sum()
    s["valor_janelas"] = jan.groupby("cnpj_ente")["valor"].sum() if not jan.empty else 0
    s["multibanco"] = (s["perfil"] == "multibanco").astype(float)
    s["valor_vazamento"] = (vaz[vaz["direcao"] == "saída da CAIXA"].groupby("cnpj_ente")["valor_executor"].sum()
                            if not vaz.empty else 0)
    s = s.fillna({"valor_concorrente_recente": 0, "saldo_concorrente": 0, "valor_janelas": 0, "valor_vazamento": 0})

    fatores = {"valor_concorrente": "valor_concorrente_recente", "saldo_concorrente": "saldo_concorrente",
               "janelas_abertas": "valor_janelas", "multibanco": "multibanco", "vazamento": "valor_vazamento"}
    rotulos = {"valor_concorrente": "emendas recentes no concorrente", "saldo_concorrente": "saldo no concorrente",
               "janelas_abertas": "janela aberta", "multibanco": "já é cliente em parte (multibanco)",
               "vazamento": "executor recebe fora da CAIXA"}
    contrib = pd.DataFrame(index=s.index)
    total_peso = sum(pesos.values()) or 1
    for nome, coluna in fatores.items():
        v = s[coluna].astype(float)
        r = v.rank(pct=True) if v.max() > 0 else v * 0
        r[v <= 0] = 0
        contrib[nome] = r * pesos.get(nome, 0) / total_peso * 100
    s["score"] = contrib.sum(axis=1).round(0).astype(int)
    s["motivo_principal"] = contrib.idxmax(axis=1).map(rotulos).where(s["score"] > 0, "sem sinal")
    out = s.reset_index().sort_values("score", ascending=False)
    return out[cols]


def alertas(mudancas: dict[str, pd.DataFrame], saldo_alto: float) -> pd.DataFrame:
    """Alertas do dia a partir das mudanças registradas no histórico."""
    cols = ["tipo", "modulo", "referencia", "descricao", "valor"]
    linhas = []
    pa = mudancas.get("especiais/planos-acao-especiais", pd.DataFrame())
    if not pa.empty:
        from .normaliza import codigo_banco, grupo_banco
        val = pd.to_numeric(pa.get("valor_custeio_plano_acao"), errors="coerce").fillna(0) + \
            pd.to_numeric(pa.get("valor_investimento_plano_acao"), errors="coerce").fillna(0)
        pa = pa.assign(_v=val)
        for _, r in pa[pa["primeira_vez"]].iterrows():
            b = grupo_banco(codigo_banco(r.get("codigo_banco_plano_acao"), r.get("nome_banco_plano_acao")))
            linhas.append(("Plano novo", "Especiais", r.get("codigo_plano_acao"),
                           f"Novo plano ({b}) · {r.get('nome_parlamentar_emenda_plano_acao') or ''}", r["_v"]))
        if "codigo_banco_plano_acao_anterior" in pa.columns:
            mud = pa[~pa["primeira_vez"]]
            for _, r in mud.iterrows():
                antes = grupo_banco(codigo_banco(r.get("codigo_banco_plano_acao_anterior")))
                agora = grupo_banco(codigo_banco(r.get("codigo_banco_plano_acao")))
                if antes != agora:
                    linhas.append(("Troca de banco", "Especiais", r.get("codigo_plano_acao"),
                                   f"{antes} → {agora}", r["_v"]))
                elif r.get("situacao_plano_acao") != r.get("situacao_plano_acao_anterior") and \
                        pd.notna(r.get("situacao_plano_acao_anterior")):
                    linhas.append(("Mudança de situação", "Especiais", r.get("codigo_plano_acao"),
                                   f"{r.get('situacao_plano_acao_anterior')} → {r.get('situacao_plano_acao')}", r["_v"]))
    sal = mudancas.get("especiais/saldo-conta-gestao-financeira-especiais", pd.DataFrame())
    if not sal.empty:
        v = pd.to_numeric(sal["saldo_final_gestao_financeira"], errors="coerce")
        ant = pd.to_numeric(sal.get("saldo_final_gestao_financeira_anterior"), errors="coerce")
        x = sal[(v >= saldo_alto) & ~(ant >= saldo_alto)]
        for _, r in x.iterrows():
            linhas.append(("Saldo alto", "Especiais", r["id_agencia_conta"], "Conta passou do limite de saldo",
                           float(r["saldo_final_gestao_financeira"])))
    return pd.DataFrame(linhas, columns=cols)
