"""Motores do gestor de custódia: permanência e rentabilidade, dinheiro a receber, radar de risco,
matriz de escolhas, entes perdidos, venda cruzada, priorização e radar do ente.

Cada saída carrega o código da regra (config/regras.yaml) que a gerou, para a tela explicar o porquê.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import normaliza, regras

SAIDAS = {"pagamento/transferência", "tributos/tarifas", "devolução"}
MEDIDO = "medido"
MEDIDO_LANC = "medido: lançamentos de 12 meses"
MEDIDO_PARADO = "medido: sem saída em 12 meses (parado)"


def giro_dias(x: pd.DataFrame) -> float:
    """Permanência média de um grupo = saldo ÷ saídas anuais × 365 (estoque ÷ fluxo), só no que foi medido.
    É a medida padrão de giro; a média dos dias de cada conta ponderada pelo saldo superestima (as contas
    paradas pesam mais) — conciliação 01/11."""
    m = x[x["base_permanencia"].astype(str).str.startswith(MEDIDO)]
    s = pd.to_numeric(m["saidas_12m"], errors="coerce").sum()
    return float(365 * pd.to_numeric(m["saldo"], errors="coerce").sum() / s) if s > 0 else float("nan")
DISPUTAVEIS = ["Especiais", "Discricionárias"]
SEM_BANCO = "(sem banco)"


def _p(cod: str, nome: str, padrao):
    return regras.param(cod, nome, padrao)


def _num(s, padrao=0.0):
    return pd.to_numeric(s, errors="coerce").fillna(padrao)


def _brl(v: float) -> str:
    v = float(v or 0)
    txt = f"R$ {v / 1e6:,.1f} mi" if abs(v) >= 1e6 else f"R$ {v / 1e3:,.0f} mil"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _resultado(saldo: pd.Series, mc: dict | None = None) -> pd.Series:
    mc = mc or {}
    taxa = _p("PERM-03", "taxa_referencia_aa", mc.get("taxa_referencia_aa", 10.5))
    frac = _p("PERM-03", "fracao_resultado", mc.get("fracao_resultado", 0.30))
    return saldo.clip(lower=0) * taxa / 100 * frac


# ------------------------------------------------------------------ qualidade da fonte
def fontes_interrompidas(fluxo: pd.DataFrame, contas: pd.DataFrame, hoje: date) -> set[tuple[str, str]]:
    """Modalidade × banco cujo extrato parou de chegar ao Transferegov (último lançamento ou saldo típico
    mais antigo que o limite da regra QLD-01). Ex.: CAIXA nas Transferências Especiais desde mai/2025."""
    lim = pd.Timestamp(hoje) - pd.Timedelta(days=int(_p("QLD-01", "dias_limite", 60)))
    paradas = set()
    if not fluxo.empty:
        f = fluxo.assign(_d=normaliza.data(fluxo["data"]))
        ult = normaliza.ultimo_extrato_efetivo(fluxo)
        paradas |= {k for k, v in ult.items() if pd.notna(v) and v < lim}
        # bancos com SALDO na modalidade e nenhum lançamento: há dinheiro cujo movimento não aparece.
        # Banco sem saldo e sem lançamento nunca publicou extrato — não "parou" (conciliação 01/11: BNB nas
        # Especiais, 272 contas sem saldo, aparecia como fonte interrompida)
        if not contas.empty:
            mods = set(f["modulo"].unique())
            cc = contas[contas["modulo"].isin(mods)]
            for (m, b), x in cc.groupby(["modulo", "grupo_banco"]):
                if b != SEM_BANCO and (m, b) not in ult.index and _num(x["saldo"]).gt(0).any():
                    paradas.add((m, b))
    if not contas.empty:
        # a data típica do saldo só decide onde NÃO há lançamentos: contas antigas puxam a mediana para trás
        # mesmo com o banco publicando normalmente (antes isso marcava BB e BNB das Especiais como parados)
        com_lanc = set(fluxo["modulo"].unique()) if not fluxo.empty else set()
        c = contas[~contas["modulo"].isin(com_lanc)]
        c = c.assign(_d=normaliza.data(c["data_saldo"]))
        c = c[(_num(c["saldo"]) > 0) & c["_d"].notna()]
        med = c.groupby(["modulo", "grupo_banco"])["_d"].median()
        paradas |= {k for k, v in med.items() if v < lim}
    return paradas


# ------------------------------------------------------------------ permanência e rentabilidade
def permanencia(contas: pd.DataFrame, fluxo: pd.DataFrame, mc: dict | None = None,
                paradas: set | None = None) -> pd.DataFrame:
    """Por ente × modalidade × banco: saldo, saídas em 12 meses, dias de permanência, classe e valor econômico."""
    cols = ["modulo", "cnpj_ente", "nome_ente", "uf", "grupo_banco", "saldo", "contas", "rendimento", "saidas_12m",
            "dias_permanencia", "base_permanencia", "classe_saldo", "valor_economico_ano"]
    if contas.empty:
        return pd.DataFrame(columns=cols)
    c = contas.assign(rendimento=_num(contas["rendimento"]) if "rendimento" in contas else 0.0)
    c = c[_num(c["saldo"]) > 0]
    g = c.groupby(["modulo", "cnpj_ente", "grupo_banco"], dropna=False).agg(
        nome_ente=("nome_ente", "first"), uf=("uf", "first"), saldo=("saldo", "sum"),
        contas=("id_agencia_conta", "nunique"), rendimento=("rendimento", "sum")).reset_index()
    g["saidas_12m"] = 0.0
    janela = int(_p("PERM-01", "janela_saidas_dias", 365))
    fim_grupo = {}
    if not fluxo.empty:
        f = fluxo[fluxo["tipo_movimento"].isin(SAIDAS)].copy()
        f["_d"] = normaliza.data(f["data"])
        f = f[f["_d"].notna()]
        if not f.empty:
            # cada banco na SUA janela de 12 meses até o último extrato dele: o banco que parou de publicar é
            # medido com o saldo e as saídas da mesma época (conciliação 01/11, equipe independente)
            # fim = último extrato EFETIVO do banco (um lançamento isolado depois da parada não move a janela)
            fim_grupo = normaliza.ultimo_extrato_efetivo(f).to_dict()
            fim = pd.Series([fim_grupo.get((m, b)) for m, b in zip(f["modulo"], f["grupo_origem"])], index=f.index)
            f = f[f["_d"] <= fim]
            fim = fim[f.index]
            f = f[f["_d"] >= fim - pd.Timedelta(days=janela)]
            s = f.groupby(["modulo", "cnpj_ente", "grupo_origem"])["valor"].sum().rename("_s").reset_index()
            g = g.merge(s.rename(columns={"grupo_origem": "grupo_banco"}), on=["modulo", "cnpj_ente", "grupo_banco"],
                        how="left")
            g["saidas_12m"] = _num(g.pop("_s"))
    padrao = float(_p("PERM-01", "dias_padrao", (mc or {}).get("dias_permanencia_padrao", 180)))
    maximo = float(_p("PERM-01", "dias_maximo", 1095))
    completos = set(_p("PERM-01", "modulos_extrato_completo", ["Especiais"]))
    tem = g["saidas_12m"] > 0
    # sem saída em 12 meses onde o extrato cobre todas as saídas (Especiais) = dinheiro parado, não "sem dado"
    # (conciliação 01/11: 8.930 contas BB com R$ 2,85 bi recebiam o prazo padrão de 180 dias)
    grupo_ok = pd.Series([(m, b) in fim_grupo for m, b in zip(g["modulo"], g["grupo_banco"])], index=g.index)
    parado = ~tem & g["modulo"].isin(completos) & grupo_ok
    g["dias_permanencia"] = np.select([tem, parado], [(g["saldo"] / (g["saidas_12m"] / 365.0)).clip(upper=maximo),
                                                      maximo], padrao)
    g["base_permanencia"] = np.select([tem, parado], [MEDIDO_LANC, MEDIDO_PARADO], "prazo padrão (sem lançamentos)")
    if paradas:
        par = pd.Series([(m, b) in paradas for m, b in zip(g["modulo"], g["grupo_banco"])], index=g.index)
        for (m, b), d_fim in fim_grupo.items():
            if (m, b) in paradas:
                sel = par & (g["modulo"] == m) & (g["grupo_banco"] == b) & (tem | parado)
                g.loc[sel, "base_permanencia"] = (f"{MEDIDO} até o último extrato ({d_fim:%m/%Y}; o extrato parou "
                                                  "de chegar na fonte)")
        # banco parado sem nenhum lançamento: continua sem medição
        sem = par & ~g["base_permanencia"].str.startswith(MEDIDO)
        g.loc[sem, "dias_permanencia"] = padrao
        g.loc[sem, "base_permanencia"] = "prazo padrão (extrato parou de chegar na fonte)"
    est, pas = _p("PERM-02", "estavel_dias", 365), _p("PERM-02", "passagem_dias", 90)
    g["classe_saldo"] = np.select([g["dias_permanencia"] >= est, g["dias_permanencia"] < pas],
                                  ["Estável", "Passagem"], "Médio")
    g["valor_economico_ano"] = _resultado(g["saldo"], mc)
    return g[cols]


def concentracao(contas: pd.DataFrame, n: int = 300) -> pd.DataFrame:
    """Ranking dos entes por saldo em cada modalidade × banco, com participação acumulada."""
    cols = ["modulo", "grupo_banco", "posicao", "cnpj_ente", "nome_ente", "uf", "saldo", "pct_do_saldo", "pct_acumulado"]
    if contas.empty:
        return pd.DataFrame(columns=cols)
    c = contas[_num(contas["saldo"]) > 0]
    # o denominador é todo o saldo do banco (inclui o saldo sem ente identificado); o ranking só tem entes —
    # saldo sem CNPJ não é um ente (conciliação 01/11: R$ 70 mi sem vínculo apareciam em 3º lugar; a equipe B
    # cometeu o mesmo erro, com R$ 93 mi, e chegou a 12,9% em vez de 11,1%)
    total = c.groupby(["modulo", "grupo_banco"])["saldo"].sum()
    c = c[c["cnpj_ente"].fillna("").astype(str).str.strip() != ""]
    g = c.groupby(["modulo", "grupo_banco", "cnpj_ente"]).agg(
        nome_ente=("nome_ente", "first"), uf=("uf", "first"), saldo=("saldo", "sum")).reset_index()
    g = g.sort_values(["modulo", "grupo_banco", "saldo"], ascending=[True, True, False])
    tot = pd.Series(list(zip(g["modulo"], g["grupo_banco"])), index=g.index).map(total)
    g["posicao"] = g.groupby(["modulo", "grupo_banco"]).cumcount() + 1
    g["pct_do_saldo"] = g["saldo"] / tot
    g["pct_acumulado"] = g.groupby(["modulo", "grupo_banco"])["pct_do_saldo"].cumsum()
    return g[g["posicao"] <= n][cols]


# ------------------------------------------------------------------ dinheiro que ainda vai chegar
def _faixa(dias: pd.Series) -> pd.Series:
    f1, f2, f3 = (_p("REC-03", "faixas_dias", [30, 90, 180]) + [30, 90, 180])[:3]
    return pd.Series(np.select(
        [dias.isna(), dias <= 0, dias <= f1, dias <= f2, dias <= f3],
        ["Sem data (até o fim da vigência)", "A qualquer momento", f"Até {f1} dias", f"{f1 + 1} a {f2} dias",
         f"{f2 + 1} a {f3} dias"], f"Mais de {f3} dias"), index=dias.index)


FAIXA_ANTIGO = "Empenho antigo sem pagamento (verificar)"
FAIXA_PREVISTO = "Previsto (minuta ou proposta, ainda sem empenho/convênio)"
ORDEM_FAIXAS = ["A qualquer momento", "Até 30 dias", "31 a 90 dias", "91 a 180 dias", "Mais de 180 dias",
                "Sem data (até o fim da vigência)", FAIXA_ANTIGO, FAIXA_PREVISTO]


def a_receber(pipe: pd.DataFrame, instr: pd.DataFrame, hoje: date) -> pd.DataFrame:
    cols = ["modulo", "id_instrumento", "cnpj_ente", "nome_ente", "uf", "grupo_banco", "area", "etapa", "firme",
            "valor_a_receber", "data_prevista", "dias_para_credito", "faixa_prazo", "fim_vigencia", "regra"]
    partes = []
    hoje_ts = pd.Timestamp(hoje)
    if not pipe.empty:
        p = pipe[_num(pipe["a_creditar"]) > 0].copy()
        if not p.empty:
            pagos = pipe[pipe["dias_ate_pagamento"].notna()]
            d_ob = pd.to_datetime(pagos["data_ob"], errors="coerce")
            recentes = pagos[d_ob >= hoje_ts - pd.Timedelta(days=int(_p("REC-01", "janela_mediana_dias", 365)))]
            if len(recentes) >= 20:
                pagos = recentes
            geral = float(pagos["dias_ate_pagamento"].median()) if not pagos.empty else float(_p("REC-01", "dias_padrao", 45))
            por_area = pagos.groupby("area")["dias_ate_pagamento"].median() if not pagos.empty else pd.Series(dtype=float)
            dias = p["area"].map(por_area).fillna(geral)
            emp = pd.to_datetime(p["data_empenho"], errors="coerce")
            prev = emp + pd.to_timedelta(dias, unit="D")
            p = p.assign(valor_a_receber=p["a_creditar"], data_prevista=prev.dt.strftime("%Y-%m-%d"),
                         dias_para_credito=(prev - hoje_ts).dt.days, fim_vigencia=None, regra="REC-01",
                         modulo=p.get("modulo", "Especiais"))
            idade = (hoje_ts - emp).dt.days
            p["_antigo"] = idade > int(_p("REC-01", "idade_maxima_dias", 540))
            p["etapa"], p["firme"] = "Empenho emitido, sem ordem bancária", True
            partes.append(p)
        # minutas de empenho: dinheiro previsto, ainda sem empenho emitido (REC-04) — à parte do firme
        if "valor_minuta" in pipe:
            m = pipe[_num(pipe["valor_minuta"]) > 0]
            if not m.empty:
                partes.append(m.assign(valor_a_receber=_num(m["valor_minuta"]), data_prevista=None, dias_para_credito=np.nan,
                                       fim_vigencia=None, regra="REC-04", modulo=m.get("modulo", "Especiais"),
                                       etapa="Minuta de empenho (ainda não emitido)", firme=False))
    if not instr.empty and "desembolsado" in instr:
        d = instr[(instr["modulo"] == "Discricionárias") & instr["ativo"].fillna(False).astype(bool)].copy()
        d["valor_a_receber"] = (_num(d["valor"]) - _num(d["desembolsado"])).clip(lower=0)
        d = d[d["valor_a_receber"] > 0]
        fim = pd.to_datetime(d["fim_vigencia"], errors="coerce")
        d = d[fim.isna() | (fim >= hoje_ts)]
        if not d.empty:
            # proposta aprovada e ainda sem convênio assinado não é convênio em vigência (conciliação 01/11:
            # R$ 9,3 bi de propostas somavam aos R$ 100,7 bi dos convênios assinados) — fica à parte (REC-04)
            ref = d["data_referencia"] if "data_referencia" in d else pd.Series(None, index=d.index)
            assinado = ref.notna() & (ref.astype(str).str.strip() != "")
            partes.append(d[assinado].assign(data_prevista=None, dias_para_credito=np.nan, regra="REC-02",
                                             etapa="Convênio assinado, a liberar", firme=True))
            if (~assinado).any():
                partes.append(d[~assinado].assign(data_prevista=None, dias_para_credito=np.nan, regra="REC-04",
                                                  etapa="Proposta aprovada, convênio não assinado", firme=False))
    if not partes:
        return pd.DataFrame(columns=cols)
    out = pd.concat([x.reindex(columns=cols) for x in partes], ignore_index=True)
    out["dias_para_credito"] = pd.to_numeric(out["dias_para_credito"], errors="coerce")
    out["faixa_prazo"] = _faixa(out["dias_para_credito"])
    antigo = pd.concat([x.get("_antigo", pd.Series(False, index=x.index)) for x in partes], ignore_index=True)
    out.loc[antigo.fillna(False).astype(bool).values, "faixa_prazo"] = FAIXA_ANTIGO
    out.loc[~out["firme"].fillna(False).astype(bool), "faixa_prazo"] = FAIXA_PREVISTO
    out["firme"] = out["firme"].fillna(False).astype(bool)
    return out[cols]


def _firme(r: pd.DataFrame) -> pd.Series:
    """Linhas de dinheiro firme (empenho emitido / convênio assinado); sem a coluna, tudo conta (cargas antigas)."""
    return r["firme"].fillna(False).astype(bool) if "firme" in r else pd.Series(True, index=r.index)


def _parou(ultimo_lancamento, dias_mediana, hoje: date, lim: int) -> bool:
    d = pd.to_datetime(ultimo_lancamento, errors="coerce") if ultimo_lancamento not in (None, "sem lançamentos") else None
    if d is not None and pd.notna(d):
        return bool((pd.Timestamp(hoje) - d).days > lim)
    if ultimo_lancamento == "sem lançamentos":
        return True
    return bool(dias_mediana is not None and dias_mediana > lim)


def defasagem(contas: pd.DataFrame, hoje: date, fluxo: pd.DataFrame | None = None) -> pd.DataFrame:
    """Data mais recente e idade do saldo publicado por modalidade × banco (regra QLD-01)."""
    cols = ["modulo", "grupo_banco", "contas", "saldo", "data_saldo_recente", "data_saldo_mediana",
            "dias_desde_saldo", "pct_saldo_atualizado", "ultimo_lancamento", "saldo_desatualizado"]
    if contas.empty:
        return pd.DataFrame(columns=cols)
    lim = int(_p("QLD-01", "dias_limite", 60))
    c = contas.assign(_d=pd.to_datetime(contas["data_saldo"], errors="coerce"))
    c = c[(_num(c["saldo"]) > 0) & (c["grupo_banco"] != SEM_BANCO)]
    out = []
    for (m, b), g in c.groupby(["modulo", "grupo_banco"]):
        tem = g["_d"].notna()
        rec = g.loc[tem, "_d"].max() if tem.any() else pd.NaT
        med = g.loc[tem, "_d"].median() if tem.any() else pd.NaT
        atual = g["_d"] >= pd.Timestamp(hoje) - pd.Timedelta(days=lim)
        pct = float(g.loc[atual, "saldo"].sum() / g["saldo"].sum()) if tem.any() else None
        dias = (pd.Timestamp(hoje) - med).days if pd.notna(med) else None
        ul = None
        if fluxo is not None and not fluxo.empty:
            x = fluxo[(fluxo["modulo"] == m) & (fluxo["grupo_origem"] == b)]["data"].dropna()
            ul = str(x.max())[:10] if not x.empty else ("sem lançamentos" if (fluxo["modulo"] == m).any() else None)
        out.append({"modulo": m, "grupo_banco": b, "contas": len(g), "saldo": g["saldo"].sum(), "ultimo_lancamento": ul,
                    "data_saldo_recente": rec.strftime("%Y-%m-%d") if pd.notna(rec) else "não informada",
                    "data_saldo_mediana": med.strftime("%Y-%m-%d") if pd.notna(med) else "não informada",
                    "dias_desde_saldo": dias, "pct_saldo_atualizado": pct,
                    # com lançamentos na modalidade, o que diz se o banco parou é o ÚLTIMO lançamento dele
                    # (contas sem movimento mantêm a data do último saldo e puxam a mediana para trás);
                    # sem lançamentos, vale a idade típica do saldo
                    "saldo_desatualizado": _parou(ul, dias, hoje, lim)})
    return pd.DataFrame(out, columns=cols)


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def sazonalidade(pipe: pd.DataFrame) -> pd.DataFrame:
    """Em que meses os créditos caem (ordens bancárias pagas), somando todos os anos."""
    if pipe.empty or "data_ob" not in pipe:
        return pd.DataFrame(columns=["mes", "mes_nome", "valor_pago", "pct_do_total"])
    d = pd.to_datetime(pipe["data_ob"], errors="coerce")
    p = pipe.assign(mes=d.dt.month)[d.notna()]
    g = p.groupby("mes")["valor_pago"].sum().reindex(range(1, 13), fill_value=0).rename("valor_pago").reset_index()
    g["mes_nome"] = g["mes"].map(lambda m: MESES[m - 1])
    g["pct_do_total"] = g["valor_pago"] / max(g["valor_pago"].sum(), 1)
    return g[["mes", "mes_nome", "valor_pago", "pct_do_total"]]


# ------------------------------------------------------------------ escolhas, fidelidade e perdas
def escolhas(instr: pd.DataFrame) -> pd.DataFrame:
    """Banco escolhido por ente × modalidade × ano (o de maior valor, ignorando 'sem banco')."""
    cols = ["cnpj_ente", "nome_ente", "uf", "modulo", "ano", "grupo_banco", "valor", "valor_caixa"]
    i = instr[instr["modulo"].isin(DISPUTAVEIS) & (instr["grupo_banco"] != SEM_BANCO) & instr["ano"].notna()]
    if i.empty:
        return pd.DataFrame(columns=cols)
    i = i.assign(ano=i["ano"].astype(int))
    g = i.groupby(["cnpj_ente", "modulo", "ano", "grupo_banco"], as_index=False).agg(
        valor=("valor", "sum"), nome_ente=("nome_ente", "first"), uf=("uf", "first"))
    tot = g.groupby(["cnpj_ente", "modulo", "ano"]).agg(valor_total=("valor", "sum"))
    cx = g[g["grupo_banco"] == "CAIXA"].set_index(["cnpj_ente", "modulo", "ano"])["valor"]
    esc = g.sort_values("valor").drop_duplicates(["cnpj_ente", "modulo", "ano"], keep="last").set_index(
        ["cnpj_ente", "modulo", "ano"])
    esc["valor"] = tot["valor_total"]
    esc["valor_caixa"] = cx.reindex(esc.index).fillna(0.0)
    return esc.reset_index()[cols]


def transicoes(esc: pd.DataFrame) -> pd.DataFrame:
    """De um ano com instrumentos para o seguinte: de qual banco para qual, por modalidade."""
    cols = ["modulo", "banco_de", "banco_para", "entes", "valor"]
    if esc.empty:
        return pd.DataFrame(columns=cols)
    e = esc.sort_values(["cnpj_ente", "modulo", "ano"])
    e["banco_de"] = e.groupby(["cnpj_ente", "modulo"])["grupo_banco"].shift()
    e = e[e["banco_de"].notna()]
    return e.groupby(["modulo", "banco_de", "grupo_banco"], as_index=False).agg(
        entes=("cnpj_ente", "nunique"), valor=("valor", "sum")).rename(columns={"grupo_banco": "banco_para"})[cols]


def matriz_modalidades(esc: pd.DataFrame, anos_recentes: int = 3) -> pd.DataFrame:
    """Banco predominante nas Transferências Especiais × nos convênios, nos anos recentes."""
    cols = ["banco_especiais", "banco_convenios", "entes", "valor"]
    if esc.empty:
        return pd.DataFrame(columns=cols)
    ult = int(esc["ano"].max())
    r = esc[esc["ano"] > ult - anos_recentes]
    pref = r.groupby(["cnpj_ente", "modulo", "grupo_banco"])["valor"].sum().reset_index()
    pref = pref.sort_values("valor").drop_duplicates(["cnpj_ente", "modulo"], keep="last")
    tab = pref.pivot(index="cnpj_ente", columns="modulo", values="grupo_banco")
    val = r.groupby("cnpj_ente")["valor"].sum()
    tab = tab.reindex(columns=DISPUTAVEIS).fillna("não usa")
    tab["valor"] = val
    return tab.reset_index().groupby(["Especiais", "Discricionárias"], as_index=False).agg(
        entes=("cnpj_ente", "count"), valor=("valor", "sum")).rename(
        columns={"Especiais": "banco_especiais", "Discricionárias": "banco_convenios"})[cols]


def entes_perdidos(esc: pd.DataFrame, contas: pd.DataFrame, potencial: pd.DataFrame) -> pd.DataFrame:
    cols = ["cnpj_ente", "nome_ente", "uf", "ultimo_ano_caixa", "ultimo_ano", "anos_sem_caixa", "banco_atual",
            "modalidades", "valor_caixa_historico", "valor_concorrente_depois", "saldo_concorrente",
            "potencial_custodia", "regra"]
    if esc.empty:
        return pd.DataFrame(columns=cols)
    olhar = int(_p("PER-01", "anos_olhados", 5))
    a = esc.groupby(["cnpj_ente", "ano"]).agg(valor=("valor", "sum"), valor_caixa=("valor_caixa", "sum")).reset_index()
    ult = a.groupby("cnpj_ente")["ano"].max().rename("ultimo_ano")
    a = a.join(ult, on="cnpj_ente")
    ult_cx = a[a["valor_caixa"] > 0].groupby("cnpj_ente")["ano"].max().rename("ultimo_ano_caixa")
    base = pd.concat([ult, ult_cx], axis=1).dropna(subset=["ultimo_ano_caixa"])
    base = base[(base["ultimo_ano_caixa"] < base["ultimo_ano"]) &
                (base["ultimo_ano_caixa"] >= base["ultimo_ano"] - olhar)].copy()
    if base.empty:
        return pd.DataFrame(columns=cols)
    base["anos_sem_caixa"] = (base["ultimo_ano"] - base["ultimo_ano_caixa"]).astype(int)
    hist = a.groupby("cnpj_ente")["valor_caixa"].sum().rename("valor_caixa_historico")
    depois = a.join(base["ultimo_ano_caixa"], on="cnpj_ente", how="inner")
    depois = depois[depois["ano"] > depois["ultimo_ano_caixa"]].groupby("cnpj_ente").apply(
        lambda g: (g["valor"] - g["valor_caixa"]).sum(), include_groups=False).rename("valor_concorrente_depois")
    atual = esc.merge(ult.reset_index(), on=["cnpj_ente"]).query("ano == ultimo_ano")
    atual = atual.sort_values("valor").drop_duplicates("cnpj_ente", keep="last").set_index("cnpj_ente")
    mods = esc.groupby("cnpj_ente")["modulo"].agg(lambda s: ", ".join(sorted(set(s))))
    out = base.join([hist, depois, atual[["nome_ente", "uf", "grupo_banco"]].rename(columns={"grupo_banco": "banco_atual"}),
                     mods.rename("modalidades")])
    sc = contas[(contas["grupo_banco"] != "CAIXA") & contas["modulo"].isin(DISPUTAVEIS)].groupby("cnpj_ente")["saldo"].sum()
    out["saldo_concorrente"] = sc.reindex(out.index).fillna(0.0)
    pot = potencial.set_index("cnpj_ente")["potencial_custodia"] if not potencial.empty else pd.Series(dtype=float)
    out["potencial_custodia"] = pot.reindex(out.index).fillna(0.0)
    out["regra"] = "PER-01"
    out = out.reset_index().rename(columns={"index": "cnpj_ente"})
    for c in ("ultimo_ano_caixa", "ultimo_ano"):
        out[c] = out[c].astype(int)
    return out.sort_values("valor_concorrente_depois", ascending=False)[cols]


# ------------------------------------------------------------------ radar de risco
def radar_risco(instr, contas, perdidos, dest_ente, rede, conformidade, var_ente, hoje: date) -> pd.DataFrame:
    cols = ["cnpj_ente", "nome_ente", "uf", "regra", "risco", "severidade", "valor_em_risco", "detalhe"]
    linhas = []
    nome = regras.nome
    if not perdidos.empty:
        r = perdidos[perdidos["anos_sem_caixa"] <= 2]
        for x in r.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-01",
                           "risco": nome("RIS-01"), "severidade": "Crítico" if x.anos_sem_caixa == 1 else "Atenção",
                           "valor_em_risco": x.valor_concorrente_depois,
                           "detalhe": f"Último ano na CAIXA: {x.ultimo_ano_caixa}; em {x.ultimo_ano} foi para {x.banco_atual}."})
    if not instr.empty and "fim_vigencia" in instr:
        d = instr[(instr["modulo"] == "Discricionárias") & (instr["grupo_banco"] == "CAIXA") &
                  instr["ativo"].fillna(False).astype(bool)]
        if not d.empty and not contas.empty:
            sal = contas[contas["modulo"] == "Discricionárias"].groupby("id_instrumento")["saldo"].sum()
            d = d.assign(saldo=d["id_instrumento"].map(sal).fillna(0.0),
                         dias=(pd.to_datetime(d["fim_vigencia"], errors="coerce") - pd.Timestamp(hoje)).dt.days)
            mn, crit, aten = _p("RIS-02", "saldo_minimo", 50000), _p("RIS-02", "dias_critico", 90), _p("RIS-02", "dias_atencao", 180)
            d = d[(d["saldo"] >= mn) & d["dias"].between(0, aten)]
            g = d.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"), saldo=("saldo", "sum"),
                                           convenios=("id_instrumento", "count"), dias=("dias", "min")).reset_index()
            for x in g.itertuples():
                linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-02",
                               "risco": nome("RIS-02"), "severidade": "Crítico" if x.dias <= crit else "Atenção",
                               "valor_em_risco": x.saldo,
                               "detalhe": f"{x.convenios} convênio(s) CAIXA com saldo; o primeiro vence em {int(x.dias)} dias."})
    if var_ente is not None and not var_ente.empty and "var_mes_pct" in var_ente:
        q, mn = _p("RIS-03", "queda_pct", 0.30), _p("RIS-03", "saldo_minimo", 1_000_000)
        v = var_ente[(var_ente["grupo_banco"] == "CAIXA") & (var_ente["var_mes_pct"] <= -q) &
                     (var_ente["saldo_mes_anterior"] >= mn)]
        v = v.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                       queda=("var_mes", "sum"), ant=("saldo_mes_anterior", "sum")).reset_index()
        for x in v.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-03",
                           "risco": nome("RIS-03"), "severidade": "Crítico", "valor_em_risco": -x.queda,
                           "detalhe": f"Saldo CAIXA caiu {(-x.queda / x.ant):.0%} em 30 dias."})
    if not dest_ente.empty:
        cx = set(contas.loc[(contas["grupo_banco"] == "CAIXA") & (_num(contas["saldo"]) > 0), "cnpj_ente"])
        pf, mn = _p("RIS-04", "pct_fora_minimo", 0.70), _p("RIS-04", "valor_minimo", 500000)
        de = dest_ente[dest_ente["cnpj_ente"].isin(cx) & (dest_ente["pago_terceiros_fora"] >= mn) &
                       ((1 - dest_ente["part_caixa_pagamentos"].fillna(0)) >= pf)]
        for x in de.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-04",
                           "risco": nome("RIS-04"), "severidade": "Atenção", "valor_em_risco": x.pago_terceiros_fora,
                           "detalhe": f"{1 - (x.part_caixa_pagamentos or 0):.0%} dos pagamentos a terceiros vão para outros bancos."})
    if not rede.empty:
        r = rede[rede["grupo_banco"] == "CAIXA"]
        if not r.empty:
            tot = r.groupby("cnpj_ente")["valor"].transform("sum")
            r = r.assign(pct=r["valor"] / tot, tot=tot).sort_values("valor").drop_duplicates("cnpj_ente", keep="last")
            pm, mn = _p("RIS-05", "pct_minimo", 0.70), _p("RIS-05", "valor_minimo", 1_000_000)
            for x in r[(r["pct"] >= pm) & (r["tot"] >= mn)].itertuples():
                linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-05",
                               "risco": nome("RIS-05"), "severidade": "Atenção", "valor_em_risco": x.tot,
                               "detalhe": f"{x.pct:.0%} do valor CAIXA vem de {x.parlamentar}."})
    if conformidade is not None and not conformidade.empty:
        for x in conformidade.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-06",
                           "risco": nome("RIS-06"), "severidade": "Atenção", "valor_em_risco": x.valor,
                           "detalhe": f"{x.lancamentos} lançamento(s) para conta do próprio ente após o corte."})
    return pd.DataFrame(linhas, columns=cols)


# ------------------------------------------------------------------ venda cruzada
def venda_cruzada(esc, transf, dest_ente, contas, fluxo, receber, anos_recentes: int = 2,
                  paradas: set | None = None) -> pd.DataFrame:
    cols = ["cnpj_ente", "nome_ente", "uf", "regra", "oferta", "valor_oportunidade", "argumento"]
    linhas = []
    nome = regras.nome
    if not esc.empty:
        ult = int(esc["ano"].max())
        r = esc[esc["ano"] > ult - anos_recentes]
        m = r.groupby(["cnpj_ente", "modulo"]).agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                                   valor=("valor", "sum"), valor_caixa=("valor_caixa", "sum")).reset_index()
        m["valor_conc"] = m["valor"] - m["valor_caixa"]
        cx_mods = m[m["valor_caixa"] > 0].groupby("cnpj_ente")["modulo"].agg(set)
        conc = m[(m["valor_conc"] >= _p("VC-01", "valor_minimo", 100000))]
        for x in conc.itertuples():
            outros = cx_mods.get(x.cnpj_ente, set()) - {x.modulo}
            if outros:
                de = "convênios" if "Discricionárias" in outros else "Transferências Especiais"
                para = "Transferências Especiais" if x.modulo == "Especiais" else "convênios"
                linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "VC-01",
                               "oferta": nome("VC-01"), "valor_oportunidade": x.valor_conc,
                               "argumento": f"Já é cliente CAIXA nos {de}; levou {_brl(x.valor_conc)} das "
                                            f"{para} para o concorrente nos últimos {anos_recentes} anos."})
    if transf is not None and not transf.empty:
        mn = _p("VC-02", "valor_minimo", 50000)
        for x in transf[transf["valor_transferido"] >= mn].itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "VC-02",
                           "oferta": nome("VC-02"), "valor_oportunidade": max(x.saldo_faf_hoje or 0, x.valor_12_meses or 0),
                           "argumento": "Já autoriza a saída do recurso do Fundo a Fundo para conta própria; "
                                        "a conta de destino pode ser CAIXA."})
    cx_ent = set(contas.loc[(contas["grupo_banco"] == "CAIXA") & (_num(contas["saldo"]) > 0), "cnpj_ente"]) if not contas.empty else set()
    if not dest_ente.empty:
        mn = _p("VC-03", "valor_minimo", 500000)
        for x in dest_ente[dest_ente["cnpj_ente"].isin(cx_ent) & (dest_ente["pago_terceiros_fora"] >= mn)].itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "VC-03",
                           "oferta": nome("VC-03"), "valor_oportunidade": x.pago_terceiros_fora,
                           "argumento": "Paga fornecedores em outros bancos com dinheiro que sai de conta CAIXA: "
                                        "oferecer domicílio e pagamento a fornecedores."})
    if not contas.empty:
        mn = _p("VC-04", "saldo_minimo", 1_000_000)
        c = contas[(contas["grupo_banco"] == "CAIXA") & (_num(contas["saldo"]) >= mn)].copy()
        com_aplic = set()
        if not fluxo.empty:
            com_aplic = set(fluxo.loc[fluxo["tipo_movimento"] == "aplicação/resgate", "id_agencia_conta"])
        sem = c[(c["modulo"] == "Especiais") & ~c["id_agencia_conta"].isin(com_aplic)]
        if paradas and ("Especiais", "CAIXA") in paradas:
            sem = sem.iloc[0:0]   # sem extrato recente não dá para afirmar que não há aplicação
        if "rendimento" in c:
            sem = pd.concat([sem, c[(c["modulo"] == "Discricionárias") & (_num(c["rendimento"]) <= 0)]])
        g = sem.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                         saldo=("saldo", "sum"), contas=("id_agencia_conta", "nunique")).reset_index()
        for x in g.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "VC-04",
                           "oferta": nome("VC-04"), "valor_oportunidade": x.saldo,
                           "argumento": f"{x.contas} conta(s) CAIXA com saldo alto sem aplicação registrada."})
    if receber is not None and not receber.empty:
        mn, dias = _p("VC-05", "valor_minimo", 1_000_000), _p("VC-05", "dias", 90)
        r = receber[(receber["grupo_banco"] == "CAIXA") & (receber["dias_para_credito"] <= dias) &
                    (receber["faixa_prazo"] != FAIXA_ANTIGO)]
        g = r.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                       valor=("valor_a_receber", "sum")).reset_index()
        for x in g[g["valor"] >= mn].itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "VC-05",
                           "oferta": nome("VC-05"), "valor_oportunidade": x.valor,
                           "argumento": f"Vai receber crédito na conta CAIXA nos próximos {dias} dias: momento de "
                                        "visitar e oferecer o pacote de serviços."})
    return pd.DataFrame(linhas, columns=cols)


# ------------------------------------------------------------------ priorização e radar do ente
def chance_conversao(er: pd.DataFrame, perfil: pd.DataFrame, perdidos: pd.DataFrame, vc: pd.DataFrame,
                     transf: pd.DataFrame, esc: pd.DataFrame) -> pd.Series:
    p = lambda n, d: float(_p("PRI-01", n, d))  # noqa: E731
    idx = er["cnpj_ente"]
    nota = pd.Series(20.0, index=idx.values)
    tem_cx = (er["valor_caixa"].fillna(0) > 0) | (er["saldo_caixa"].fillna(0) > 0)
    nota += np.where(tem_cx.values, p("tem_conta_caixa", 10), 0)
    vc1 = set(vc.loc[vc["regra"] == "VC-01", "cnpj_ente"]) if not vc.empty else set()
    nota += np.where(idx.isin(vc1).values, p("cliente_outra_modalidade", 35), 0)
    multi = set(perfil.loc[perfil["perfil"] == "multibanco", "cnpj_ente"]) if not perfil.empty else set()
    nota += np.where(idx.isin(multi).values, p("multibanco", 20), 0)
    rec = set(perdidos.loc[perdidos["anos_sem_caixa"] <= 2, "cnpj_ente"]) if not perdidos.empty else set()
    nota += np.where(idx.isin(rec).values, p("perdido_recente", 20), 0)
    ts = set(transf["cnpj_ente"]) if transf is not None and not transf.empty else set()
    nota += np.where(idx.isin(ts).values, p("transf_secundaria", 15), 0)
    if not esc.empty:
        anos = esc.groupby("cnpj_ente").agg(anos=("ano", "nunique"), cx=("valor_caixa", "sum"))
        so_conc = set(anos[(anos["anos"] >= 3) & (anos["cx"] <= 0)].index)
        nota += np.where(idx.isin(so_conc).values, p("so_concorrente_ha_anos", -20), 0)
    return nota.clip(0, 100)


def priorizacao(er: pd.DataFrame, chance: pd.Series) -> pd.DataFrame:
    cols = ["cnpj_ente", "nome_ente", "uf", "esfera", "porte", "segmento", "banco_principal", "potencial_custodia",
            "resultado_estimado_ano", "chance_conversao", "quadrante", "acao_recomendada"]
    if er.empty:
        return pd.DataFrame(columns=cols)
    x = er.assign(chance_conversao=chance.reindex(er["cnpj_ente"]).values)
    x = x[x["potencial_custodia"].fillna(0) > 0].copy()
    if x.empty:
        return pd.DataFrame(columns=cols)
    lim_pot = x["potencial_custodia"].quantile(float(_p("PRI-02", "percentil_potencial_alto", 0.75)))
    alta = float(_p("PRI-02", "chance_alta", 50))
    pa, ca = x["potencial_custodia"] >= lim_pot, x["chance_conversao"] >= alta
    x["quadrante"] = np.select([pa & ca, pa & ~ca, ~pa & ca], ["Atacar já", "Construir relação", "Ganho rápido"],
                               "Monitorar")
    return x.sort_values(["potencial_custodia"], ascending=False)[cols]


def _pct_rank(s: pd.Series) -> pd.Series:
    s = s.fillna(0)
    r = s.where(s > 0).rank(pct=True) * 100
    return r.fillna(0).round(0)


def dimensoes(er: pd.DataFrame, receber: pd.DataFrame, radar: pd.DataFrame, vc: pd.DataFrame,
              chance: pd.Series) -> pd.DataFrame:
    cols = ["cnpj_ente", "dim_tamanho", "dim_disputa", "dim_potencial", "dim_credito", "dim_risco", "dim_venda",
            "dim_chance", "a_receber_total", "valor_em_risco", "valor_venda_cruzada", "riscos", "ofertas"]
    if er.empty:
        return pd.DataFrame(columns=cols)
    x = er[["cnpj_ente", "valor", "part_caixa", "potencial_custodia"]].copy().set_index("cnpj_ente")
    receber = receber[(receber["faixa_prazo"] != FAIXA_ANTIGO) & _firme(receber)] if not receber.empty else receber
    x["a_receber_total"] = (receber.groupby("cnpj_ente")["valor_a_receber"].sum() if not receber.empty
                            else pd.Series(dtype=float)).reindex(x.index).fillna(0.0)
    r = radar[radar["regra"] != "RIS-06"] if not radar.empty else radar
    x["valor_em_risco"] = (r.groupby("cnpj_ente")["valor_em_risco"].sum() if not r.empty
                           else pd.Series(dtype=float)).reindex(x.index).fillna(0.0)
    x["riscos"] = (r.groupby("cnpj_ente").size() if not r.empty else pd.Series(dtype=int)).reindex(x.index).fillna(0).astype(int)
    x["valor_venda_cruzada"] = (vc.groupby("cnpj_ente")["valor_oportunidade"].sum() if not vc.empty
                                else pd.Series(dtype=float)).reindex(x.index).fillna(0.0)
    x["ofertas"] = (vc.groupby("cnpj_ente").size() if not vc.empty else pd.Series(dtype=int)).reindex(x.index).fillna(0).astype(int)
    x["dim_tamanho"] = _pct_rank(x["valor"])
    x["dim_disputa"] = ((1 - x["part_caixa"].fillna(1)) * 100).clip(0, 100).round(0).where(x["valor"].fillna(0) > 0, 0)
    x["dim_potencial"] = _pct_rank(x["potencial_custodia"])
    x["dim_credito"] = _pct_rank(x["a_receber_total"])
    x["dim_risco"] = _pct_rank(x["valor_em_risco"])
    x["dim_venda"] = _pct_rank(x["valor_venda_cruzada"])
    x["dim_chance"] = chance.reindex(x.index).fillna(0).round(0)
    return x.reset_index()[cols]


DIMENSOES = {"dim_tamanho": "Tamanho", "dim_disputa": "Disputa", "dim_potencial": "Potencial",
             "dim_credito": "Crédito a receber", "dim_risco": "Risco", "dim_venda": "Venda cruzada",
             "dim_chance": "Chance de conversão"}


# ------------------------------------------------------------------ janela de escolha do banco
ESTAGIOS = ["Banco ainda não escolhido", "Conta com erro de abertura", "Conta ainda não aberta",
            "Antes da assinatura do convênio", "Impedido (pode ser liberado)"]
_ENCERRADO = r"cancel|anulad|rejeit|exclu|prestacao de contas|encerrad|extint|rescind|arquivad|inadimpl"


def _sem_acento(s: pd.Series) -> pd.Series:
    from .normaliza import sem_acento
    return s.fillna("").astype(str).map(sem_acento)


def janela_escolha(instr: pd.DataFrame, esc: pd.DataFrame) -> pd.DataFrame:
    """Instrumentos no momento de escolha (ou troca) do banco da conta — o momento decisivo da custódia.
    Para cada um: estágio, banco indicado, tendência pelo histórico do ente e do parlamentar, e a ação."""
    cols = ["estagio", "modulo", "id_instrumento", "codigo", "ano", "cnpj_ente", "nome_ente", "uf", "cod_ibge",
            "tipo_ente", "valor", "parlamentar", "orgao", "situacao", "situacao_conta", "banco_indicado",
            "part_caixa_ente_hist", "part_caixa_parlamentar", "prob_caixa", "tendencia", "valor_em_disputa",
            "acao", "data_referencia", "regra"]
    i = instr[instr["modulo"].isin(DISPUTAVEIS)].copy()
    if i.empty:
        return pd.DataFrame(columns=cols)
    sit, sc = _sem_acento(i["situacao"]), _sem_acento(i["situacao_conta"])
    vivo = ~sit.str.contains(_ENCERRADO, regex=True)
    sem_banco = i["grupo_banco"].fillna(SEM_BANCO) == SEM_BANCO
    pre_conv = (i["modulo"] == "Discricionárias") & sit.str.contains(r"proposta/plano de trabalho|em analise|aguardando", regex=True)
    estagio = np.select(
        [vivo & sem_banco & ~sit.str.contains("impedid"),
         vivo & sc.str.contains("erro na abertura"),
         vivo & sc.str.contains(r"cadastrada|registrada|aguardando|pendente de regulariza", regex=True),
         vivo & pre_conv,
         sit.str.contains("impedid")],
        ESTAGIOS, "")
    i = i.assign(estagio=estagio)
    i = i[i["estagio"] != ""].copy()
    if i.empty:
        return pd.DataFrame(columns=cols)
    # histórico do ente: participação CAIXA nas escolhas anteriores (todas as modalidades disputáveis)
    if not esc.empty:
        h = esc.groupby("cnpj_ente").agg(v=("valor", "sum"), c=("valor_caixa", "sum"))
        part_ente = (h["c"] / h["v"].replace(0, np.nan))
    else:
        part_ente = pd.Series(dtype=float)
    com_banco = instr[instr["grupo_banco"].fillna(SEM_BANCO) != SEM_BANCO]
    p = com_banco.dropna(subset=["parlamentar"]).groupby("parlamentar").apply(
        lambda g: (g.loc[g["grupo_banco"] == "CAIXA", "valor"].sum() / max(g["valor"].sum(), 1)), include_groups=False)
    i["part_caixa_ente_hist"] = i["cnpj_ente"].map(part_ente)
    i["part_caixa_parlamentar"] = i["parlamentar"].map(p)
    pe, pp = i["part_caixa_ente_hist"], i["part_caixa_parlamentar"]
    prob = np.where(pe.notna() & pp.notna(), 0.6 * pe + 0.4 * pp, np.where(pe.notna(), pe, np.where(pp.notna(), pp, 0.5)))
    i["prob_caixa"] = np.round(prob, 3)
    # banco já indicado pesa: quem já indicou a CAIXA tende a ficar (e vice-versa), mas ainda pode mudar
    ind = i["grupo_banco"].fillna(SEM_BANCO)
    i.loc[ind == "CAIXA", "prob_caixa"] = np.maximum(i.loc[ind == "CAIXA", "prob_caixa"], 0.7)
    i.loc[(ind != "CAIXA") & (ind != SEM_BANCO), "prob_caixa"] = np.minimum(
        i.loc[(ind != "CAIXA") & (ind != SEM_BANCO), "prob_caixa"], 0.45)
    i["tendencia"] = np.select([i["prob_caixa"] >= 0.6, i["prob_caixa"] <= 0.4], ["tende à CAIXA", "tende ao concorrente"],
                               "indefinida")
    i["banco_indicado"] = ind.replace(SEM_BANCO, "ainda não indicado")
    i["valor_em_disputa"] = i["valor"] * (1 - i["prob_caixa"])
    acoes = {
        "Banco ainda não escolhido": "Contato imediato com o ente: apresentar a conta CAIXA antes da ciência/indicação",
        "Conta com erro de abertura": "Apoiar a reabertura da conta — oportunidade de indicar a CAIXA",
        "Conta ainda não aberta": "Acompanhar a abertura; se indicado o concorrente, verificar se ainda é possível trocar",
        "Antes da assinatura do convênio": "Atuar com o convenente antes da assinatura e da abertura da conta",
        "Impedido (pode ser liberado)": "Ajudar o ente a sanar o impedimento e já orientar a conta CAIXA",
    }
    i["acao"] = i["estagio"].map(acoes)
    i.loc[(i["banco_indicado"] == "CAIXA"), "acao"] = "Garantir: acompanhar até a conta CAIXA estar ativa"
    i["regra"] = "JAN-01"
    return i.sort_values("valor_em_disputa", ascending=False).reindex(columns=cols)


def calendario_escolha(instr: pd.DataFrame) -> pd.DataFrame:
    """Em que meses os entes escolhem o banco: ciência dos planos (Especiais) e assinatura (convênios)."""
    i = instr[instr["modulo"].isin(DISPUTAVEIS)].copy()
    d = normaliza.data(i["data_referencia"])      # dayfirst com ISO trocava dia e mês (dias 1 a 12)
    i = i.assign(_d=d)[d.notna()]
    if i.empty:
        return pd.DataFrame(columns=["modulo", "ano", "mes", "mes_nome", "instrumentos", "valor", "valor_caixa"])
    i["ano"], i["mes"] = i["_d"].dt.year, i["_d"].dt.month
    g = i.groupby(["modulo", "ano", "mes"]).agg(instrumentos=("id_instrumento", "count"), valor=("valor", "sum"),
                                                valor_caixa=("valor", lambda s: s[i.loc[s.index, "grupo_banco"] == "CAIXA"].sum())
                                                ).reset_index()
    g["mes_nome"] = g["mes"].map(lambda m: MESES[int(m) - 1])
    return g


# ------------------------------------------------------------------ riscos ampliados
def _part_por_ano(df: pd.DataFrame, chave: str) -> pd.DataFrame:
    a = df.groupby([chave, "ano"]).agg(v=("valor", "sum"), c=("valor_caixa", "sum")).reset_index()
    a["p"] = a["c"] / a["v"].replace(0, np.nan)
    return a.sort_values([chave, "ano"])


def _queda(a: pd.DataFrame, chave: str, minimo_ant: float):
    """Compara os dois últimos anos com dados de cada chave."""
    ult = a.groupby(chave).tail(2)
    pares = ult.groupby(chave).filter(lambda g: len(g) == 2)
    if pares.empty:
        return pd.DataFrame()
    ant = pares.groupby(chave).nth(0).set_index(chave)
    atu = pares.groupby(chave).nth(1).set_index(chave)
    out = pd.DataFrame({"ano_ant": ant["ano"], "ano_atu": atu["ano"], "p_ant": ant["p"], "p_atu": atu["p"],
                        "c_ant": ant["c"], "v_atu": atu["v"], "c_atu": atu["c"]})
    out["queda"] = out["p_ant"] - out["p_atu"]
    return out[(out["c_ant"] >= minimo_ant)]


def riscos_ampliados(esc: pd.DataFrame, instr: pd.DataFrame, janela: pd.DataFrame, contas: pd.DataFrame) -> pd.DataFrame:
    """Riscos por ente: queda de participação, janela tendendo ao concorrente, erro de abertura de conta CAIXA."""
    cols = ["cnpj_ente", "nome_ente", "uf", "regra", "risco", "severidade", "valor_em_risco", "detalhe"]
    linhas = []
    nomes = esc.drop_duplicates("cnpj_ente").set_index("cnpj_ente")[["nome_ente", "uf"]] if not esc.empty else None
    if not esc.empty:
        q = _queda(_part_por_ano(esc, "cnpj_ente"), "cnpj_ente", float(_p("RIS-07", "valor_minimo", 50000)))
        lim = float(_p("RIS-07", "queda_pp", 0.25))
        for k, r in q[q["queda"] >= lim].iterrows():
            linhas.append({"cnpj_ente": k, "nome_ente": nomes.at[k, "nome_ente"], "uf": nomes.at[k, "uf"],
                           "regra": "RIS-07", "risco": regras.nome("RIS-07"),
                           "severidade": "Crítico" if r["queda"] >= 0.5 else "Atenção",
                           "valor_em_risco": max(r["v_atu"] - r["c_atu"], 0),
                           "detalhe": f"Participação CAIXA caiu de {r['p_ant']:.0%} ({int(r['ano_ant'])}) para "
                                      f"{r['p_atu']:.0%} ({int(r['ano_atu'])})."})
    if not janela.empty:
        j = janela[(janela["tendencia"] == "tende ao concorrente") & (janela["banco_indicado"] != "CAIXA")]
        g = j.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                       valor=("valor", "sum"), n=("id_instrumento", "count"),
                                       aberto=("estagio", lambda s: (s == ESTAGIOS[0]).any())).reset_index()
        for x in g.itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-09",
                           "risco": regras.nome("RIS-09"), "severidade": "Crítico" if x.aberto else "Atenção",
                           "valor_em_risco": x.valor,
                           "detalhe": f"{x.n} instrumento(s) na janela de escolha com tendência ao concorrente."})
        e = janela[(janela["estagio"] == "Conta com erro de abertura") & (janela["banco_indicado"] == "CAIXA")]
        for x in e.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "first"), uf=("uf", "first"),
                                            valor=("valor", "sum"), n=("id_instrumento", "count")).reset_index().itertuples():
            linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": x.nome_ente, "uf": x.uf, "regra": "RIS-10",
                           "risco": regras.nome("RIS-10"), "severidade": "Atenção", "valor_em_risco": x.valor,
                           "detalhe": f"{x.n} conta(s) CAIXA com erro na abertura: o ente pode indicar outro banco."})
    return pd.DataFrame(linhas, columns=cols)


def riscos_agentes(instr: pd.DataFrame) -> pd.DataFrame:
    """Parlamentares e órgãos que estão levando menos recursos para a CAIXA do que antes (RIS-08, RIS-11)."""
    cols = ["tipo_agente", "agente", "regra", "risco", "severidade", "valor_em_risco", "entes", "detalhe"]
    i = instr[instr["modulo"].isin(DISPUTAVEIS) & (instr["grupo_banco"] != SEM_BANCO) & instr["ano"].notna()]
    if i.empty:
        return pd.DataFrame(columns=cols)
    i = i.assign(ano=i["ano"].astype(int), valor_caixa=np.where(i["grupo_banco"] == "CAIXA", i["valor"], 0.0))
    linhas = []
    for tipo, chave, cod in (("Parlamentar", "parlamentar", "RIS-08"), ("Órgão concedente", "orgao", "RIS-11")):
        x = i.dropna(subset=[chave])
        if x.empty:
            continue
        q = _queda(_part_por_ano(x, chave), chave, float(_p(cod, "valor_minimo", 1_000_000)))
        lim = float(_p(cod, "queda_pp", 0.20))
        ent = x.groupby(chave)["cnpj_ente"].nunique()
        for k, r in q[q["queda"] >= lim].iterrows():
            linhas.append({"tipo_agente": tipo, "agente": k, "regra": cod, "risco": regras.nome(cod),
                           "severidade": "Crítico" if r["queda"] >= 0.4 else "Atenção",
                           "valor_em_risco": max(r["v_atu"] - r["c_atu"], 0), "entes": int(ent.get(k, 0)),
                           "detalhe": f"Participação CAIXA caiu de {r['p_ant']:.0%} ({int(r['ano_ant'])}) para "
                                      f"{r['p_atu']:.0%} ({int(r['ano_atu'])})."})
    return pd.DataFrame(linhas, columns=cols).sort_values("valor_em_risco", ascending=False)


# ------------------------------------------------------------------ quem não direciona à CAIXA, e por quê
def fora_da_caixa(er: pd.DataFrame, esc: pd.DataFrame, instr: pd.DataFrame, dest_ente: pd.DataFrame,
                  perdidos: pd.DataFrame, anos_recentes: int = 3) -> pd.DataFrame:
    """Entes públicos com volume relevante e pouca ou nenhuma participação CAIXA, com motivos prováveis tirados
    dos dados e a ação sugerida (FOR-01)."""
    cols = ["cnpj_ente", "nome_ente", "uf", "tipo_ente", "valor_recente", "part_caixa_recente", "banco_principal",
            "motivos", "acao_recomendada", "potencial_custodia", "regra"]
    if esc.empty or er.empty:
        return pd.DataFrame(columns=cols)
    ult = int(esc["ano"].max())
    r = esc[esc["ano"] > ult - anos_recentes]
    a = r.groupby("cnpj_ente").agg(valor_recente=("valor", "sum"), c=("valor_caixa", "sum"),
                                   anos=("ano", "nunique"), bancos=("grupo_banco", lambda s: set(s))).reset_index()
    a["part_caixa_recente"] = a["c"] / a["valor_recente"].replace(0, np.nan)
    a = a[(a["valor_recente"] >= float(_p("FOR-01", "valor_minimo", 100000))) &
          (a["part_caixa_recente"] <= float(_p("FOR-01", "part_maxima", 0.2)))]
    if a.empty:
        return pd.DataFrame(columns=cols)
    info = er.set_index("cnpj_ente")
    a = a[a["cnpj_ente"].isin(info.index)]
    from .marts import TIPOS_PUBLICOS
    a = a[a["cnpj_ente"].map(info["tipo_ente"]).isin(TIPOS_PUBLICOS)] if "tipo_ente" in info else a
    # sinais para os motivos
    com_banco = instr[instr["grupo_banco"] != SEM_BANCO]
    parl_part = com_banco.dropna(subset=["parlamentar"]).groupby("parlamentar").apply(
        lambda g: g.loc[g["grupo_banco"] == "CAIXA", "valor"].sum() / max(g["valor"].sum(), 1), include_groups=False)
    parl_ente = com_banco.dropna(subset=["parlamentar"]).sort_values("valor").groupby("cnpj_ente")["parlamentar"].last()
    org_part = com_banco[com_banco["modulo"] == "Discricionárias"].dropna(subset=["orgao"]).groupby("orgao").apply(
        lambda g: g.loc[g["grupo_banco"] == "CAIXA", "valor"].sum() / max(g["valor"].sum(), 1), include_groups=False)
    org_ente = com_banco[com_banco["modulo"] == "Discricionárias"].sort_values("valor").groupby("cnpj_ente")["orgao"].last()
    pag = dest_ente.set_index("cnpj_ente")["part_caixa_pagamentos"] if not dest_ente.empty else pd.Series(dtype=float)
    perd = set(perdidos["cnpj_ente"]) if not perdidos.empty else set()
    mods = info["modulos"] if "modulos" in info else pd.Series(dtype=str)
    linhas = []
    for x in a.itertuples():
        m, acoes = [], []
        conc = sorted(b for b in x.bancos if b != "CAIXA")
        if x.anos >= 2 and len(x.bancos) == 1 and conc:
            m.append(f"fiel ao {conc[0]} há {x.anos} anos")
            acoes.append("abordagem institucional com proposta de valor (tarifa, serviços, assessoria)")
        p = parl_ente.get(x.cnpj_ente)
        if p is not None and parl_part.get(p, 1) < 0.3:
            m.append(f"principal autor de emendas ({p}) leva {parl_part[p]:.0%} à CAIXA")
            acoes.append("relacionamento com o gabinete do parlamentar")
        o = org_ente.get(x.cnpj_ente)
        if o is not None and org_part.get(o, 1) < 0.3:
            m.append(f"órgão concedente ({o}) opera {org_part[o]:.0%} na CAIXA")
            acoes.append("tratar com o órgão concedente o banco dos próximos convênios")
        if pag.get(x.cnpj_ente, 1) < 0.3:
            m.append("fornecedores do ente recebem em outros bancos")
            acoes.append("oferecer pagamento a fornecedores e domicílio bancário")
        if "Fundo a Fundo" in str(mods.get(x.cnpj_ente, "")):
            m.append("já tem conta no BB pelo Fundo a Fundo")
            acoes.append("oferecer a conta CAIXA para a transferência secundária do Fundo a Fundo")
        if x.cnpj_ente in perd:
            m.append("já foi cliente CAIXA e saiu")
            acoes.append("visita de reconquista: entender o que mudou")
        if not m:
            m.append("sem sinal claro nos dados — investigar com a agência")
            acoes.append("visita de diagnóstico")
        linhas.append({"cnpj_ente": x.cnpj_ente, "nome_ente": info.at[x.cnpj_ente, "nome_ente"],
                       "uf": info.at[x.cnpj_ente, "uf"], "tipo_ente": info.get("tipo_ente", pd.Series()).get(x.cnpj_ente),
                       "valor_recente": x.valor_recente, "part_caixa_recente": x.part_caixa_recente,
                       "banco_principal": info.at[x.cnpj_ente, "banco_principal"] if "banco_principal" in info else None,
                       "motivos": "; ".join(m), "acao_recomendada": "; ".join(dict.fromkeys(acoes)),
                       "potencial_custodia": info.at[x.cnpj_ente, "potencial_custodia"] if "potencial_custodia" in info else 0,
                       "regra": "FOR-01"})
    return pd.DataFrame(linhas, columns=cols).sort_values("valor_recente", ascending=False)


def fora_da_caixa_agentes(instr: pd.DataFrame) -> pd.DataFrame:
    """Parlamentares e órgãos com volume relevante e pouca participação CAIXA (FOR-02)."""
    cols = ["tipo_agente", "agente", "valor", "part_caixa", "entes", "uf_principal", "banco_principal", "regra"]
    i = instr[instr["modulo"].isin(DISPUTAVEIS) & (instr["grupo_banco"] != SEM_BANCO)]
    linhas = []
    for tipo, chave in (("Parlamentar", "parlamentar"), ("Órgão concedente", "orgao")):
        x = i.dropna(subset=[chave])
        if x.empty:
            continue
        g = x.groupby(chave).agg(valor=("valor", "sum"), entes=("cnpj_ente", "nunique"),
                                 uf_principal=("uf", lambda s: s.mode().iat[0] if not s.mode().empty else None))
        g["part_caixa"] = x[x["grupo_banco"] == "CAIXA"].groupby(chave)["valor"].sum().reindex(g.index).fillna(0) / g["valor"]
        g["banco_principal"] = x.groupby([chave, "grupo_banco"])["valor"].sum().reset_index().sort_values("valor") \
            .drop_duplicates(chave, keep="last").set_index(chave)["grupo_banco"]
        g = g[(g["valor"] >= float(_p("FOR-02", "valor_minimo", 1_000_000))) &
              (g["part_caixa"] <= float(_p("FOR-02", "part_maxima", 0.3)))]
        linhas.append(g.reset_index().rename(columns={chave: "agente"}).assign(tipo_agente=tipo, regra="FOR-02"))
    if not linhas:
        return pd.DataFrame(columns=cols)
    return pd.concat(linhas, ignore_index=True).reindex(columns=cols).sort_values("valor", ascending=False)
