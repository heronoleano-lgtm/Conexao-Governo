"""Motores de origem -> caminho -> destino do dinheiro, e de potencial para a CAIXA.

Perguntas que respondem:
  de onde vem      órgão/ministério, programa, parlamentar
  para que vai     área de política, natureza da despesa
  por onde passa   banco da conta do plano/convênio, conta do executor, aplicações
  para onde vai    banco de quem recebe os pagamentos, fornecedores, conta do próprio ente
  o que fazer      potencial econômico por ente e a ação recomendada
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .normaliza import sem_acento
from .regras import param as _pr

CAIXA = "CAIXA"
GRANDES = {"CAIXA", "BB"}


def _grupo_destino(g: pd.Series) -> pd.Series:
    return g.where(g.isin(["CAIXA", "BB", "BNB", "(sem banco)"]), "outros bancos")


def _hhi(valores: pd.Series) -> float:
    t = valores.sum()
    return float(((valores / t) ** 2).sum()) if t > 0 else np.nan


# ------------------------------------------------------------------ 1. Fluxo (Sankey)
def sankey(instr: pd.DataFrame, fluxo: pd.DataFrame, modulos: list[str] | None = None) -> pd.DataFrame:
    """Arestas origem -> área -> banco da conta -> destino dos pagamentos, em R$."""
    cols = ["etapa", "origem", "destino", "valor"]
    i = instr if not modulos else instr[instr["modulo"].isin(modulos)]
    if i.empty:
        return pd.DataFrame(columns=cols)
    i = i.assign(orgao=i["orgao"].fillna("Órgão não informado"), area=i["area"].fillna("Área não informada"),
                 grupo_banco=i["grupo_banco"].replace({"(sem banco)": "Sem banco ainda"}))
    e1 = i.groupby(["orgao", "area"], as_index=False)["valor"].sum().rename(columns={"orgao": "origem", "area": "destino"})
    e1["etapa"] = "1 · origem → área"
    e2 = i.groupby(["area", "grupo_banco"], as_index=False)["valor"].sum().rename(columns={"area": "origem", "grupo_banco": "destino"})
    e2["destino"] = "Conta " + e2["destino"]
    e2["etapa"] = "2 · área → banco da conta"
    partes = [e1, e2]
    f = fluxo if not modulos else fluxo[fluxo["modulo"].isin(modulos)]
    if not f.empty:
        f = f[f["tipo_movimento"] == "pagamento/transferência"].copy()
        f["destino"] = np.where(f["proprio_ente"], "Conta do próprio ente",
                                "Recebedor no " + _grupo_destino(f["grupo_destino"]).replace({"(sem banco)": "banco não informado"}))
        e3 = f.groupby(["grupo_origem", "destino"], as_index=False)["valor"].sum().rename(columns={"grupo_origem": "origem"})
        e3["origem"] = "Conta " + e3["origem"]
        e3["etapa"] = "3 · conta → quem recebe"
        partes.append(e3)
    out = pd.concat(partes, ignore_index=True)
    return out[out["valor"] > 0][cols]


def sankey_modalidade(instr: pd.DataFrame, fluxo: pd.DataFrame, cnpjs=None) -> pd.DataFrame:
    """Modalidade -> banco da conta -> quem recebe. Mostra o movimento do dinheiro por modalidade."""
    from .semantica import nome_modalidade
    cols = ["etapa", "origem", "destino", "valor"]
    i = instr if cnpjs is None else instr[instr["cnpj_ente"].isin(set(cnpjs))]
    if i.empty:
        return pd.DataFrame(columns=cols)
    i = i.assign(origem=i["modulo"].map(nome_modalidade),
                 destino="Conta " + i["grupo_banco"].replace({"(sem banco)": "sem banco ainda"}))
    e1 = i.groupby(["origem", "destino"], as_index=False)["valor"].sum().assign(etapa="modalidade → conta")
    partes = [e1]
    f = fluxo if cnpjs is None or fluxo.empty else fluxo[fluxo["cnpj_ente"].isin(set(cnpjs))]
    if not f.empty:
        f = f[f["tipo_movimento"] == "pagamento/transferência"].copy()
        f["origem"] = "Conta " + f["grupo_origem"]
        f["destino"] = np.where(f["proprio_ente"], "Conta do próprio ente",
                                "Recebedor no " + _grupo_destino(f["grupo_destino"]).replace(
                                    {"(sem banco)": "banco não informado"}))
        partes.append(f.groupby(["origem", "destino"], as_index=False)["valor"].sum().assign(etapa="conta → quem recebe"))
    out = pd.concat(partes, ignore_index=True)
    return out[out["valor"] > 0][cols]


def matriz_destino(fluxo: pd.DataFrame) -> pd.DataFrame:
    """Banco da conta (linhas) x banco de quem recebe (colunas), só pagamentos a terceiros."""
    f = fluxo[(fluxo["tipo_movimento"] == "pagamento/transferência") & ~fluxo["proprio_ente"]]
    if f.empty:
        return pd.DataFrame()
    t = f.assign(destino=_grupo_destino(f["grupo_destino"])).pivot_table(
        index="grupo_origem", columns="destino", values="valor", aggfunc="sum", fill_value=0)
    return t


# ------------------------------------------------------------------ 2. Parlamentares
def parlamentares(instr: pd.DataFrame, emendas: pd.DataFrame, perfil: pd.DataFrame) -> pd.DataFrame:
    cols = ["parlamentar", "modulos", "valor", "valor_caixa", "valor_concorrente", "part_caixa", "entes", "uf_principal",
            "pct_uf_principal", "area_principal", "hhi_entes", "entes_so_concorrente", "valor_em_entes_so_concorrente",
            "leitura"]
    if emendas.empty:
        return pd.DataFrame(columns=cols)
    e = emendas.merge(instr[["modulo", "id_instrumento", "cnpj_ente", "uf", "grupo_banco", "area"]],
                      on=["modulo", "id_instrumento"], how="left")
    e = e[e["grupo_banco"].notna()]
    so_conc = set(perfil.loc[perfil["perfil"] == "só concorrente", "cnpj_ente"]) if not perfil.empty else set()
    linhas = []
    for nome, g in e.groupby("parlamentar"):
        com = g[g["grupo_banco"] != "(sem banco)"]
        v, vc = com["valor"].sum(), com.loc[com["grupo_banco"] == CAIXA, "valor"].sum()
        por_uf = g.groupby("uf")["valor"].sum().sort_values(ascending=False)
        por_area = g.groupby("area")["valor"].sum().sort_values(ascending=False)
        ent = g.groupby("cnpj_ente")["valor"].sum()
        sc = g[g["cnpj_ente"].isin(so_conc)]
        linhas.append({
            "parlamentar": nome, "modulos": ", ".join(sorted(g["modulo"].unique())), "valor": g["valor"].sum(),
            "valor_caixa": vc, "valor_concorrente": v - vc, "part_caixa": vc / v if v else np.nan,
            "entes": g["cnpj_ente"].nunique(),
            "uf_principal": por_uf.index[0] if len(por_uf) else None,
            "pct_uf_principal": por_uf.iloc[0] / por_uf.sum() if por_uf.sum() else np.nan,
            "area_principal": por_area.index[0] if len(por_area) else None,
            "hhi_entes": _hhi(ent), "entes_so_concorrente": sc["cnpj_ente"].nunique(),
            "valor_em_entes_so_concorrente": sc["valor"].sum()})
    out = pd.DataFrame(linhas)
    out["leitura"] = np.select(
        [out["part_caixa"] < 0.3, out["part_caixa"] < 0.6, out["hhi_entes"] > 0.25],
        ["Base majoritariamente no concorrente: agenda institucional e visita aos entes da base",
         "Base dividida: priorizar entes multibanco que ele atende",
         "Concentrado em poucos entes: relacionamento direto com esses entes"],
        default="Base majoritariamente CAIXA: manter e acompanhar novas indicações")
    return out.sort_values("valor_concorrente", ascending=False)[cols]


def rede_parlamentar_ente(instr: pd.DataFrame, emendas: pd.DataFrame) -> pd.DataFrame:
    if emendas.empty:
        return pd.DataFrame(columns=["parlamentar", "cnpj_ente", "nome_ente", "uf", "grupo_banco", "valor", "instrumentos"])
    e = emendas.merge(instr[["modulo", "id_instrumento", "cnpj_ente", "nome_ente", "uf", "grupo_banco"]],
                      on=["modulo", "id_instrumento"], how="left")
    return (e.groupby(["parlamentar", "cnpj_ente", "nome_ente", "uf", "grupo_banco"], dropna=False, as_index=False)
            .agg(valor=("valor", "sum"), instrumentos=("id_instrumento", "nunique")))


# ------------------------------------------------------------------ 3. Ministérios e programas
def orgaos(instr: pd.DataFrame, contas: pd.DataFrame) -> pd.DataFrame:
    cols = ["modulo", "orgao", "programa", "valor", "instrumentos", "entes", "part_caixa", "saldo", "saldo_x_repasse"]
    if instr.empty:
        return pd.DataFrame(columns=cols)
    chave = ["modulo", "orgao", "programa"]
    i = instr.assign(orgao=instr["orgao"].fillna("Não informado"), programa=instr["programa"].fillna("Não informado"))
    i = i.assign(_cx=np.where(i["grupo_banco"] == CAIXA, i["valor"], 0.0),
                 _com=np.where(i["grupo_banco"] != "(sem banco)", i["valor"], 0.0))
    base = i.groupby(chave, as_index=False).agg(
        valor=("valor", "sum"), instrumentos=("id_instrumento", "count"), entes=("cnpj_ente", "nunique"),
        _cx=("_cx", "sum"), _com=("_com", "sum"))
    base["part_caixa"] = base["_cx"] / base["_com"].replace(0, np.nan)
    if not contas.empty:
        s = contas.drop_duplicates(["modulo", "id_agencia_conta"]).merge(
            i[["modulo", "id_instrumento", "orgao", "programa"]], on=["modulo", "id_instrumento"], how="inner")
        sal = s.groupby(chave, as_index=False)["saldo"].sum()
        base = base.merge(sal, on=chave, how="left")
        base["saldo"] = base["saldo"].fillna(0)
    else:
        base["saldo"] = 0.0
    base["saldo_x_repasse"] = base["saldo"] / base["valor"].replace(0, np.nan)
    return base.sort_values("valor", ascending=False)[cols]


# ------------------------------------------------------------------ 4. Destinação
def destinacao(dest: pd.DataFrame, instr: pd.DataFrame) -> pd.DataFrame:
    cols = ["modulo", "tipo", "destinacao", "valor", "valor_caixa", "part_caixa"]
    if dest.empty:
        return pd.DataFrame(columns=cols)
    d = dest.merge(instr[["modulo", "id_instrumento", "grupo_banco"]], on=["modulo", "id_instrumento"], how="left")
    d = d.assign(tipo=d["tipo"].fillna("não informado"), destinacao=d["destinacao"].fillna("não informado"),
                 _cx=np.where(d["grupo_banco"] == CAIXA, d["valor"], 0.0),
                 _com=np.where(d["grupo_banco"].isin(GRANDES | {"BNB"}), d["valor"], 0.0))
    g = d.groupby(["modulo", "tipo", "destinacao"], as_index=False).agg(
        valor=("valor", "sum"), valor_caixa=("_cx", "sum"), _com=("_com", "sum"))
    g["part_caixa"] = g["valor_caixa"] / g["_com"].replace(0, np.nan)
    return g.sort_values("valor", ascending=False)[cols]


# ------------------------------------------------------------------ 5. Para onde vai: pagamentos e fornecedores
def destino_por_ente(fluxo: pd.DataFrame) -> pd.DataFrame:
    cols = ["cnpj_ente", "nome_ente", "uf", "pago_terceiros", "pago_terceiros_caixa", "pago_terceiros_fora",
            "part_caixa_pagamentos", "para_conta_propria", "aplicacoes"]
    if fluxo.empty:
        return pd.DataFrame(columns=cols)
    f = fluxo
    pag = f[f["tipo_movimento"] == "pagamento/transferência"]
    terc = pag[~pag["proprio_ente"] & (pag["grupo_destino"] != "(sem banco)")]
    g = f.groupby("cnpj_ente").agg(nome_ente=("nome_ente", "last"), uf=("uf", "last"))
    g["pago_terceiros"] = terc.groupby("cnpj_ente")["valor"].sum()
    g["pago_terceiros_caixa"] = terc[terc["grupo_destino"] == CAIXA].groupby("cnpj_ente")["valor"].sum()
    g["para_conta_propria"] = pag[pag["proprio_ente"]].groupby("cnpj_ente")["valor"].sum()
    g["aplicacoes"] = f[f["tipo_movimento"] == "aplicação/resgate"].groupby("cnpj_ente")["valor"].sum()
    g = g.fillna({"pago_terceiros": 0, "pago_terceiros_caixa": 0, "para_conta_propria": 0, "aplicacoes": 0})
    g["pago_terceiros_fora"] = g["pago_terceiros"] - g["pago_terceiros_caixa"]
    g["part_caixa_pagamentos"] = g["pago_terceiros_caixa"] / g["pago_terceiros"].replace(0, np.nan)
    return g.reset_index().sort_values("pago_terceiros_fora", ascending=False)[cols]


def fornecedores(fluxo: pd.DataFrame, pagamentos: pd.DataFrame) -> pd.DataFrame:
    """Quem recebe o dinheiro no fim, com o banco onde recebe (quando o lançamento informa)."""
    cols = ["recebedor", "documento", "tipo_doc", "valor_recebido", "entes_pagadores", "ufs", "banco_principal",
            "pct_no_banco_principal", "recebe_na_caixa", "fonte"]
    partes = []
    if not fluxo.empty:
        f = fluxo[(fluxo["tipo_movimento"] == "pagamento/transferência") & ~fluxo["proprio_ente"] &
                  fluxo["favorecido"].fillna("").str.len().gt(2)].copy()
        if not f.empty:
            f["chave"] = f["favorecido"].map(sem_acento)
            por_banco = f.groupby(["chave", "grupo_destino"])["valor"].sum().reset_index()
            princ = por_banco.sort_values("valor").drop_duplicates("chave", keep="last").set_index("chave")
            tot = f.groupby("chave").agg(recebedor=("favorecido", "first"), valor_recebido=("valor", "sum"),
                                         entes_pagadores=("cnpj_ente", "nunique"),
                                         ufs=("uf", lambda s: ", ".join(sorted(set(s.dropna()))[:5])),
                                         tipo_doc=("tipo_favorecido", "first"))
            caixa = f[f["grupo_destino"] == CAIXA].groupby("chave")["valor"].sum()
            tot["banco_principal"] = princ["grupo_destino"]
            tot["pct_no_banco_principal"] = princ["valor"] / tot["valor_recebido"]
            tot["recebe_na_caixa"] = caixa.reindex(tot.index).fillna(0) / tot["valor_recebido"]
            tot["documento"], tot["fonte"] = None, "lançamentos bancários (Especiais)"
            partes.append(tot.reset_index(drop=True))
    if not pagamentos.empty:
        p = pagamentos[pagamentos["nome_recebedor"].fillna("").str.len() > 2]
        g = p.groupby(["modulo", "doc_recebedor"], dropna=False).agg(
            recebedor=("nome_recebedor", "first"), tipo_doc=("tipo_doc", "first"), valor_recebido=("valor", "sum"),
            entes_pagadores=("cnpj_ente", "nunique"),
            ufs=("uf", lambda s: ", ".join(sorted(set(s.dropna()))[:5]))).reset_index()
        g["documento"] = g["doc_recebedor"]
        g["fonte"] = np.where(g["modulo"] == "Especiais", "relatório de gestão (Especiais)", "subtransações (Fundo a Fundo)")
        g["banco_principal"], g["pct_no_banco_principal"], g["recebe_na_caixa"] = None, np.nan, np.nan
        partes.append(g.drop(columns=["modulo", "doc_recebedor"]))
    if not partes:
        return pd.DataFrame(columns=cols)
    out = pd.concat(partes, ignore_index=True)
    # pessoa física não entra como alvo de prospecção nominal (LGPD)
    out = out[~out["tipo_doc"].fillna("").str.upper().isin(["CPF"])]
    return out.sort_values("valor_recebido", ascending=False)[cols]


# ------------------------------------------------------------------ 6. Velocidade e permanência
def velocidade(pipe: pd.DataFrame) -> pd.DataFrame:
    cols = ["recorte", "valor", "pagamentos", "dias_p25", "dias_mediana", "dias_p75"]
    if pipe.empty or "dias_ate_pagamento" not in pipe:
        return pd.DataFrame(columns=cols)
    p = pipe[pipe["dias_ate_pagamento"].between(0, 1500)]
    linhas = []
    for nome, chave in (("Banco", "grupo_banco"), ("UF", "uf"), ("Área", "area"), ("Natureza", "natureza")):
        if chave not in p:
            continue
        for k, g in p.groupby(chave):
            d = g["dias_ate_pagamento"]
            linhas.append({"recorte": f"{nome}: {k}", "valor": g["valor_pago"].sum(), "pagamentos": len(g),
                           "dias_p25": d.quantile(.25), "dias_mediana": d.median(), "dias_p75": d.quantile(.75)})
    return pd.DataFrame(linhas, columns=cols)


# ------------------------------------------------------------------ 7. Potencial e ações
def potencial(perfil: pd.DataFrame, contas: pd.DataFrame, pipe: pd.DataFrame, dest_ente: pd.DataFrame,
              janelas: pd.DataFrame, score: pd.DataFrame, vaz: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Potencial econômico estimado por ente e a próxima ação recomendada."""
    cols = ["cnpj_ente", "nome_ente", "uf", "segmento", "score", "saldo_concorrente", "a_creditar_concorrente",
            "pagamentos_fora_caixa", "valor_janelas", "potencial_custodia", "resultado_estimado_ano",
            "acao_recomendada", "motivo"]
    if perfil.empty:
        return pd.DataFrame(columns=cols)
    taxa = cfg.get("taxa_referencia_aa", 10.5) / 100
    frac = cfg.get("fracao_resultado", 0.3)
    p = perfil.set_index("cnpj_ente")[["nome_ente", "uf", "perfil", "part_caixa", "valor_concorrente"]].copy()
    c = contas[contas["grupo_banco"] != CAIXA] if not contas.empty else contas
    p["saldo_concorrente"] = c.groupby("cnpj_ente")["saldo"].sum() if not c.empty else 0
    q = pipe[(pipe["grupo_banco"] != CAIXA) & (pipe["grupo_banco"] != "(sem banco)")] if not pipe.empty else pipe
    p["a_creditar_concorrente"] = q.groupby("cnpj_ente")["a_creditar"].sum() if not q.empty else 0
    p["pagamentos_fora_caixa"] = dest_ente.set_index("cnpj_ente")["pago_terceiros_fora"] if not dest_ente.empty else 0
    p["valor_janelas"] = janelas.groupby("cnpj_ente")["valor"].sum() if not janelas.empty else 0
    p["score"] = score.set_index("cnpj_ente")["score"] if not score.empty else 0
    p["vazamento"] = vaz[vaz["direcao"] == "saída da CAIXA"].groupby("cnpj_ente")["valor_executor"].sum() if not vaz.empty else 0
    p = p.fillna({"saldo_concorrente": 0, "a_creditar_concorrente": 0, "pagamentos_fora_caixa": 0,
                  "valor_janelas": 0, "score": 0, "vazamento": 0})
    # custódia que pode mudar de banco: saldo hoje no concorrente + metade do que vai entrar + janelas abertas
    fator = float(_pr("POT-01", "fator_a_creditar", 0.5))          # premissa documentada (regra POT-01)
    p["potencial_custodia"] = p["saldo_concorrente"] + fator * p["a_creditar_concorrente"] + p["valor_janelas"]
    p["resultado_estimado_ano"] = p["potencial_custodia"] * taxa * frac
    p["segmento"] = np.select(
        [p["part_caixa"] >= 0.8, p["part_caixa"] <= 0.2, p["part_caixa"].isna()],
        ["Território CAIXA", "Território concorrente", "Sem banco definido"], default="Disputado")

    jan_motivos = janelas.groupby("cnpj_ente")["motivo"].agg(lambda s: set(s)) if not janelas.empty else pd.Series(dtype=object)
    acoes, motivos = [], []
    for cnpj, r in p.iterrows():
        m = jan_motivos.get(cnpj, set())
        if {"Plano sem banco definido", "Plano impedido e sem banco"} & m:
            a, mo = "Contatar o ente antes da indicação do banco", "há plano sem banco definido"
        elif "Conta ainda não ativa no concorrente" in m:
            a, mo = "Abordar já: a conta no concorrente ainda não foi ativada", "conta aguardando abertura"
        elif r["perfil"] == "multibanco" and r["valor_concorrente"] > 0:
            a, mo = "Ofertar a conta da próxima emenda, mostrando o histórico CAIXA do ente", "ente já usa CAIXA e concorrente"
        elif r["perfil"] == "só concorrente" and r["potencial_custodia"] > 0:
            a, mo = "Abordagem de entrada: condições de conta, aplicação e atendimento", "todo o recurso está no concorrente"
        elif r["pagamentos_fora_caixa"] > 0 and r["part_caixa"] >= 0.8:
            a, mo = "Prospectar fornecedores e prestadores pagos pelo ente", "pagamentos saem para outros bancos"
        elif r["vazamento"] > 0:
            a, mo = "Reter: executor recebe em outro banco", "vazamento do plano CAIXA"
        else:
            a, mo = "Manter relacionamento e acompanhar novas emendas", "sem sinal de disputa"
        acoes.append(a)
        motivos.append(mo)
    p["acao_recomendada"], p["motivo"] = acoes, motivos
    return p.reset_index().sort_values(["resultado_estimado_ano", "score"], ascending=False)[cols]


# ------------------------------------------------------------------ 8. Transferência secundária (Fundo a Fundo)
def transferencia_secundaria(fluxo: pd.DataFrame, instr: pd.DataFrame, contas: pd.DataFrame) -> pd.DataFrame:
    """Entes que transferem recursos da conta FaF (BB) para a conta do próprio CNPJ.

    A API do FaF não informa o banco de destino. Para priorizar, o motor mostra se o ente já tem conta CAIXA
    em outro módulo (indício, não prova, de que a conta de destino pode ser CAIXA) e quanto ainda há de saldo
    nas contas FaF do ente (o que ainda pode ser transferido)."""
    cols = ["cnpj_ente", "nome_ente", "uf", "cnpj_plano", "orgaos", "programas", "lancamentos", "valor_transferido",
            "valor_12_meses", "primeira", "ultima", "saldo_faf_hoje", "tem_conta_caixa_outro_modulo",
            "para_outro_orgao_publico", "leitura"]
    if fluxo.empty or "modulo" not in fluxo:
        return pd.DataFrame(columns=cols)
    f = fluxo[(fluxo["modulo"] == "Fundo a Fundo") & (fluxo["tipo_movimento"] == "pagamento/transferência")]
    if f.empty:
        return pd.DataFrame(columns=cols)
    prop = f[f["proprio_ente"]]
    if prop.empty:
        return pd.DataFrame(columns=cols)
    ult = pd.to_datetime(prop["data"], errors="coerce").max()
    corte = (ult - pd.DateOffset(months=12)).strftime("%Y-%m-%d") if pd.notna(ult) else "0000"
    agg = {"nome_ente": ("nome_ente", "last"), "uf": ("uf", "last"), "lancamentos": ("valor", "size"),
           "valor_transferido": ("valor", "sum"), "primeira": ("data", "min"), "ultima": ("data", "max")}
    for c in ("orgao", "programa"):
        if c in prop:
            agg[c + "s"] = (c, lambda s: ", ".join(sorted(set(s.dropna())))[:200])
    g = prop.groupby("cnpj_ente").agg(**agg)
    for c in ("orgaos", "programas"):
        if c not in g:
            g[c] = None
    g["valor_12_meses"] = prop[prop["data"].fillna("") >= corte].groupby("cnpj_ente")["valor"].sum()
    if "favorecido_publico" in f:
        outro = f[~f["proprio_ente"] & f["favorecido_publico"].fillna(False).astype(bool)]
        g["para_outro_orgao_publico"] = outro.groupby("cnpj_ente")["valor"].sum()
    else:
        g["para_outro_orgao_publico"] = 0.0
    # ente do PLANO (dono da conta FaF): fundos estaduais/municipais movimentam a conta com o próprio CNPJ, mas o
    # plano está no CNPJ do governo/prefeitura. Sem isso eles ficavam sem UF e fora do mapa (01/11: 335 fundos)
    if not contas.empty and "id_agencia_conta" in prop:
        dono = contas[contas["modulo"] == "Fundo a Fundo"].drop_duplicates("id_agencia_conta").set_index(
            "id_agencia_conta")["cnpj_ente"]
        pl = prop.assign(_p=prop["id_agencia_conta"].astype(str).map(dono)).dropna(subset=["_p"])
        g["cnpj_plano"] = pl.groupby("cnpj_ente")["_p"].agg(lambda s: s.value_counts().index[0])
    else:
        g["cnpj_plano"] = None
    uf_inst = instr.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["uf"] if not instr.empty else pd.Series(dtype=object)
    g["uf"] = g["uf"].fillna(g.index.to_series().map(uf_inst)).fillna(g["cnpj_plano"].map(uf_inst))
    caixa = set(instr.loc[(instr["grupo_banco"] == CAIXA) & (instr["modulo"] != "Fundo a Fundo"), "cnpj_ente"])
    g["tem_conta_caixa_outro_modulo"] = g.index.isin(caixa)
    sal = contas[contas["modulo"] == "Fundo a Fundo"].groupby("cnpj_ente")["saldo"].sum() if not contas.empty else pd.Series(dtype=float)
    g["saldo_faf_hoje"] = sal
    g = g.fillna({"valor_12_meses": 0, "para_outro_orgao_publico": 0, "saldo_faf_hoje": 0})
    g["leitura"] = np.select(
        [g["tem_conta_caixa_outro_modulo"] & (g["saldo_faf_hoje"] > 0),
         g["tem_conta_caixa_outro_modulo"],
         g["saldo_faf_hoje"] > 0],
        ["Já transfere, é cliente CAIXA e ainda tem saldo no BB: confirmar se a conta de destino é CAIXA e "
         "acompanhar as próximas transferências",
         "Já transfere e é cliente CAIXA: confirmar o banco de destino",
         "Já transfere e tem saldo no BB, mas sem conta CAIXA conhecida: abordagem para abertura de conta"],
        default="Histórico de transferência, sem saldo hoje: acompanhar novos repasses")
    return g.reset_index().sort_values(["valor_12_meses", "saldo_faf_hoje"], ascending=False)[cols]


# ------------------------------------------------------------------ 9. Conformidade
def conformidade(fluxo: pd.DataFrame, data_corte: str) -> pd.DataFrame:
    """Transferências Especiais: saídas para outra conta do próprio ente após a Portaria 15/2025.
    O Fundo a Fundo fica fora: a regra de movimentação varia por programa."""
    cols = ["cnpj_ente", "nome_ente", "uf", "grupo_origem", "grupo_destino", "lancamentos", "valor", "primeira", "ultima"]
    if fluxo.empty:
        return pd.DataFrame(columns=cols)
    f = fluxo[(fluxo["modulo"] == "Especiais") & fluxo["proprio_ente"] &
              (fluxo["tipo_movimento"] == "pagamento/transferência") & (fluxo["data"].fillna("") >= data_corte)]
    if f.empty:
        return pd.DataFrame(columns=cols)
    return (f.groupby(["cnpj_ente", "nome_ente", "uf", "grupo_origem", "grupo_destino"], dropna=False, as_index=False)
            .agg(lancamentos=("valor", "size"), valor=("valor", "sum"), primeira=("data", "min"), ultima=("data", "max"))
            .sort_values("valor", ascending=False)[cols])
