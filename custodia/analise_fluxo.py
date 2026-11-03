"""Análises do Fluxo do dinheiro em três etapas: de onde vem → onde fica (custódia) → para onde vai.

Cada função recebe os marts e os filtros, é memorizada (a tela não recalcula a cada clique) e devolve tabelas
prontas + as contas reversas que provam que nada foi perdido ou contado duas vezes:
  * etapa 1: Σ por órgão = Σ por modalidade = valor transferido;
  * etapa 2: saldo contado UMA vez por conta (a mesma conta aparece em vários instrumentos);
  * etapa 3: Σ destinos = Σ saídas das contas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .consultas import filtrada
from .dados import memo
from . import normaliza
from .normaliza import data as _data
from .semantica import nome_modalidade

DESTINOS = ["Recebedor na CAIXA", "Recebedor no BB", "Recebedor em outro banco", "Banco do recebedor não informado",
            "Conta do próprio ente", "Aplicação financeira", "Tributos e tarifas", "Devolução"]


def _hhi(s: pd.Series) -> float:
    t = s.sum()
    return float(((s / t) ** 2).sum()) if t else float("nan")


def _f(d, nome, f, anos=True):
    m, a, u, e = f
    return filtrada(d, nome, m, a if anos else None, u, e)


def nome_orgao(s: pd.Series) -> pd.Series:
    """Um nome por órgão, mesmo que as fontes escrevam diferente ("Ministério da Cultura" × "MINISTERIO DA CULTURA"):
    agrupa sem acento e sem caixa e mostra a grafia com acentos e minúsculas quando ela existir."""
    from .normaliza import sem_acento
    s = s.astype("object").where(s.notna(), None)
    chave = s.map(lambda v: sem_acento(str(v)).upper().strip() if v is not None else None)
    def bonito(v):
        return (sum(c.islower() for c in v), sum(not c.isascii() for c in v))
    melhor = {}
    for k, v in zip(chave, s):
        if k is not None and (k not in melhor or bonito(str(v)) > bonito(melhor[k])):
            melhor[k] = str(v)
    return chave.map(melhor)


# ------------------------------------------------------------------ etapa 1 · de onde vem
@memo(16)
def origem(d, filtros: tuple) -> dict:
    instr = _f(d, "fato_instrumento", filtros)
    if instr.empty:
        return {}
    instr = instr.assign(orgao=nome_orgao(instr["orgao"]))
    com = instr[instr["grupo_banco"] != "(sem banco)"]
    tot = float(instr["valor"].sum())
    g = instr.groupby("orgao", dropna=False).agg(valor=("valor", "sum"), instrumentos=("id_instrumento", "count"),
                                                 entes=("cnpj_ente", "nunique"),
                                                 com_emenda=("parlamentar", lambda s: s.notna().mean()))
    cb = com.groupby("orgao")["valor"].sum()
    cx = com[com["grupo_banco"] == "CAIXA"].groupby("orgao")["valor"].sum()
    g["valor_caixa"] = cx.reindex(g.index).fillna(0)
    g["valor_concorrente"] = (cb.reindex(g.index).fillna(0) - g["valor_caixa"]).clip(lower=0)
    # onde o ente ESCOLHE o banco (Especiais e convênios); no Fundo a Fundo a conta é gerada automaticamente
    # pela plataforma no BB e o ente só indica a agência — não é disputa comercial
    esc = com[com["modulo"] != "Fundo a Fundo"]
    cbe = esc.groupby("orgao")["valor"].sum()
    cxe = esc[esc["grupo_banco"] == "CAIXA"].groupby("orgao")["valor"].sum()
    g["valor_concorrente_escolha"] = (cbe.reindex(g.index).fillna(0) - cxe.reindex(g.index).fillna(0)).clip(lower=0)
    g["part_caixa_escolha"] = cxe.reindex(g.index).fillna(0) / cbe.reindex(g.index).replace(0, np.nan)
    g["valor_faf"] = instr[instr["modulo"] == "Fundo a Fundo"].groupby("orgao")["valor"].sum().reindex(g.index).fillna(0)
    g["part_caixa"] = g["valor_caixa"] / cb.reindex(g.index).replace(0, np.nan)
    g["part_do_total"] = g["valor"] / tot if tot else np.nan
    g = g.sort_values("valor", ascending=False).reset_index()
    g["orgao"] = g["orgao"].fillna("(órgão não informado)")
    mod = instr.groupby("modulo")["valor"].sum()
    ano = instr.dropna(subset=["ano"]).assign(ano=lambda x: x["ano"].astype(int)).pivot_table(
        index="ano", columns="modulo", values="valor", aggfunc="sum", fill_value=0)
    prog = instr.groupby(["orgao", "programa"], dropna=False)["valor"].sum().reset_index().sort_values(
        "valor", ascending=False)
    top3 = float(g["valor"].head(3).sum() / tot) if tot else np.nan
    return {"tabela": g, "por_modalidade": mod, "por_ano": ano, "programas": prog.head(200), "total": tot,
            "top3": top3, "hhi": _hhi(g["valor"]), "com_emenda": float(instr["parlamentar"].notna().mean()),
            "confere": abs(float(g["valor"].sum()) - tot) < 0.01 and abs(float(mod.sum()) - tot) < 0.01}


def leitura_origem(o: dict, brl, pct) -> list[str]:
    if not o:
        return []
    t = o["tabela"]
    out = [f"<b>{t.iloc[0]['orgao']}</b> é a maior origem: {brl(t.iloc[0]['valor'])} "
           f"({pct(t.iloc[0]['part_do_total'])} do total)."]
    out.append(f"Os 3 maiores órgãos concentram <b>{pct(o['top3'])}</b> do dinheiro"
               + (" — concentração alta: poucos órgãos decidem o volume." if o["top3"] >= 0.6 else "."))
    col = "valor_concorrente_escolha" if "valor_concorrente_escolha" in t else "valor_concorrente"
    conc = t[t[col] > 0].sort_values(col, ascending=False).head(1)
    if not conc.empty:
        r = conc.iloc[0]
        pc = r.get("part_caixa_escolha", r["part_caixa"])
        out.append(f"Onde o ente escolhe o banco (Especiais e convênios), o órgão com mais valor contratado em conta "
                   f"de concorrente é <b>{r['orgao']}</b>: {brl(r[col])} (CAIXA tem {pct(pc)} desse valor). "
                   "Soma de todos os anos do filtro.")
    if "valor_faf" in t and t["valor_faf"].sum() > 0:
        f = t.sort_values("valor_faf", ascending=False).iloc[0]
        out.append(f"No Fundo a Fundo a conta é gerada automaticamente pela plataforma no BB (o ente só indica a "
                   f"agência), então não é perda comercial: {brl(t['valor_faf'].sum())} contratados, "
                   f"{pct(f['valor_faf'] / t['valor_faf'].sum())} de <b>{f['orgao']}</b>.")
    out.append(f"{pct(o['com_emenda'])} dos instrumentos vêm de emenda parlamentar.")
    return out


# ------------------------------------------------------------------ etapa 2 · onde fica
@memo(16)
def custodia(d, filtros: tuple) -> dict:
    instr = _f(d, "fato_instrumento", filtros)
    contas = _f(d, "fato_conta", filtros, anos=False)
    if instr.empty:
        return {}
    val = instr[instr["grupo_banco"] != "(sem banco)"].groupby("grupo_banco")["valor"].sum()
    c = contas.drop_duplicates(["modulo", "id_agencia_conta"]) if not contas.empty else contas   # saldo 1× por conta
    repetidas = int(len(contas) - len(c)) if not contas.empty else 0
    if not c.empty:
        c = c.assign(saldo=pd.to_numeric(c["saldo"], errors="coerce").fillna(0),
                     _d=_data(c["data_saldo"]) if "data_saldo" in c else pd.NaT)
    saldo = c.groupby("grupo_banco")["saldo"].sum() if not c.empty else pd.Series(dtype=float)
    saldo_est = (c.assign(_e=pd.to_numeric(c["saldo_estimado"], errors="coerce").fillna(0)).groupby("grupo_banco")["_e"].sum()
                 if not c.empty and "saldo_estimado" in c else saldo)
    ref = c["_d"].max() if not c.empty else pd.NaT
    idade = (c[c["saldo"] > 0].assign(_i=(ref - c["_d"]).dt.days).groupby("grupo_banco")["_i"].median()
             if not c.empty and pd.notna(ref) else pd.Series(dtype=float))
    b = pd.DataFrame({"valor": val, "saldo": saldo, "saldo_estimado": saldo_est}).fillna(0)
    b["contas"] = c.groupby("grupo_banco")["id_agencia_conta"].nunique() if not c.empty else 0
    b["saldo_x_repasse"] = b["saldo"] / b["valor"].replace(0, np.nan)
    b["part_valor"] = b["valor"] / b["valor"].sum() if b["valor"].sum() else np.nan
    b["part_saldo"] = b["saldo"] / b["saldo"].sum() if b["saldo"].sum() else np.nan
    b["idade_saldo_dias"] = idade.reindex(b.index)
    b = b.sort_values("valor", ascending=False).reset_index(names="grupo_banco")
    # por modalidade × banco
    mb = instr[instr["grupo_banco"] != "(sem banco)"].groupby(["modulo", "grupo_banco"])["valor"].sum().unstack(fill_value=0)
    # por UF: onde a CAIXA guarda e onde perde
    com = instr[instr["grupo_banco"] != "(sem banco)"]
    uf = com.groupby("uf").agg(valor=("valor", "sum"))
    uf["valor_caixa"] = com[com["grupo_banco"] == "CAIXA"].groupby("uf")["valor"].sum()
    uf = uf.fillna(0)
    uf["valor_concorrente"] = uf["valor"] - uf["valor_caixa"]
    uf["part_caixa"] = uf["valor_caixa"] / uf["valor"].replace(0, np.nan)
    if not c.empty:
        uf["saldo_concorrente"] = c[c["grupo_banco"] != "CAIXA"].groupby("uf")["saldo"].sum()
    uf = uf.fillna({"saldo_concorrente": 0}).sort_values("valor", ascending=False).reset_index()
    # entes com mais dinheiro parado no concorrente (alvo comercial)
    ent = pd.DataFrame()
    if not c.empty:
        alvo = c[(c["grupo_banco"] != "CAIXA") & (c["cnpj_ente"].fillna("").astype(str) != "")]   # saldo sem ente fica fora
        ent = alvo.groupby(["cnpj_ente", "nome_ente", "uf", "grupo_banco"], dropna=False).agg(
            saldo=("saldo", "sum"), contas=("id_agencia_conta", "nunique")).reset_index().sort_values(
            "saldo", ascending=False).head(500)
    sem_banco = float(instr.loc[instr["grupo_banco"] == "(sem banco)", "valor"].sum())
    return {"bancos": b, "modalidade_banco": mb, "uf": uf, "entes_concorrente": ent, "contas_repetidas": repetidas,
            "sem_banco": sem_banco, "data_saldo": ref}


def leitura_custodia(cu: dict, brl, pct) -> list[str]:
    if not cu:
        return []
    b = cu["bancos"].set_index("grupo_banco")
    out = []
    if "CAIXA" in b.index:
        r = b.loc["CAIXA"]
        out.append(f"A CAIXA guarda <b>{pct(r['part_valor'])}</b> do valor com banco definido e <b>{pct(r['part_saldo'])}</b> "
                   "do saldo de hoje" + (" — o saldo pesa mais que o valor: o dinheiro fica mais tempo na CAIXA."
                                         if r["part_saldo"] > r["part_valor"] else
                                         " — o saldo pesa menos que o valor: o dinheiro sai mais rápido das contas CAIXA."
                                         if r["part_saldo"] < r["part_valor"] else "."))
    lider = b.drop(index="CAIXA", errors="ignore").sort_values("saldo", ascending=False).head(1)
    if not lider.empty:
        out.append(f"No concorrente, <b>{lider.index[0]}</b> tem o maior saldo: {brl(lider.iloc[0]['saldo'])}.")
    uf = cu["uf"]
    if not uf.empty:
        pior = uf[uf["valor"] > uf["valor"].median()].sort_values("part_caixa").head(1)
        if not pior.empty:
            out.append(f"Entre os estados de maior volume, <b>{pior.iloc[0]['uf']}</b> tem a menor participação CAIXA "
                       f"({pct(pior.iloc[0]['part_caixa'])}); {brl(pior.iloc[0]['valor_concorrente'])} estão no concorrente.")
    if cu["sem_banco"] > 0:
        out.append(f"{brl(cu['sem_banco'])} ainda não têm banco definido: é custódia em aberto.")
    if cu["contas_repetidas"]:
        out.append(f"{cu['contas_repetidas']:,} linhas repetiam a mesma conta (uma conta serve a vários instrumentos); "
                   "o saldo foi contado uma vez por conta.".replace(",", "."))
    return out


# ------------------------------------------------------------------ etapa 3 · para onde vai
def classificar(f: pd.DataFrame) -> pd.Series:
    pag = f["tipo_movimento"] == "pagamento/transferência"
    proprio = f["proprio_ente"].fillna(False).astype(bool)
    return pd.Series(np.select(
        [~pag & (f["tipo_movimento"] == "aplicação/resgate"), ~pag & (f["tipo_movimento"] == "tributos/tarifas"),
         ~pag, proprio, f["grupo_destino"] == "CAIXA", f["grupo_destino"] == "BB",
         f["grupo_destino"].isin(["(sem banco)"]) | f["grupo_destino"].isna()],
        ["Aplicação financeira", "Tributos e tarifas", "Devolução", "Conta do próprio ente", "Recebedor na CAIXA",
         "Recebedor no BB", "Banco do recebedor não informado"], "Recebedor em outro banco"), index=f.index)


@memo(16)
def destino(d, filtros: tuple) -> dict:
    fluxo = _f(d, "fato_fluxo", filtros, anos=False)
    if fluxo.empty:
        return {}
    f = fluxo.assign(valor=pd.to_numeric(fluxo["valor"], errors="coerce").fillna(0))
    for c in ("favorecido", "doc_favorecido", "grupo_destino", "proprio_ente", "cnpj_ente", "data"):
        if c not in f:
            f[c] = None
    f = f.assign(destino=classificar(f), origem="Conta " + f["grupo_origem"].fillna("?").astype(str))
    tot = float(f["valor"].sum())
    matriz = f.pivot_table(index="origem", columns="destino", values="valor", aggfunc="sum", fill_value=0)
    matriz = matriz.reindex(columns=[c for c in DESTINOS if c in matriz.columns])
    pct_linha = matriz.div(matriz.sum(axis=1).replace(0, np.nan), axis=0)
    # mês a mês
    mes = f.assign(_m=_data(f["data"]).dt.strftime("%Y-%m")).dropna(subset=["_m"])
    por_mes = mes.pivot_table(index="_m", columns="destino", values="valor", aggfunc="sum", fill_value=0).sort_index()
    # quem recebe: recebedores pagos com dinheiro das contas, por banco do recebedor
    terc = f[f["destino"].str.startswith("Recebedor") | (f["destino"] == "Banco do recebedor não informado")]
    rec = terc.groupby(["favorecido", "doc_favorecido", "grupo_destino"], dropna=False).agg(
        valor=("valor", "sum"), pagamentos=("valor", "size"), entes_pagadores=("cnpj_ente", "nunique")).reset_index()
    rec = rec.sort_values("valor", ascending=False)
    # vazamento: das contas CAIXA para recebedores em outros bancos (e o inverso: entrada na CAIXA)
    # vazamento = SÓ o que comprovadamente foi para outro banco; banco não informado fica à parte
    # (auditoria 01/11: misturar os dois inflava o vazamento de R$ 5,9 bi para R$ 15,0 bi)
    outro = terc["destino"].isin(["Recebedor no BB", "Recebedor em outro banco"])
    saida_cx = terc[(terc["grupo_origem"] == "CAIXA") & outro]
    sem_info_cx = terc[(terc["grupo_origem"] == "CAIXA") & (terc["destino"] == "Banco do recebedor não informado")]
    entrada_cx = terc[(terc["grupo_origem"] != "CAIXA") & (terc["destino"] == "Recebedor na CAIXA")]
    # comparação justa entre bancos: mesma janela de 12 meses até o último extrato do banco que parou primeiro
    f["_d"] = _data(f["data"])
    ult = normaliza.ultimo_extrato_efetivo(f)          # lançamento isolado depois de uma parada não conta
    comparavel = pd.DataFrame()
    # só modalidades com mais de um banco pagador (no Fundo a Fundo só o BB paga: não há o que comparar)
    mods = [m for m, n in ult.reset_index().groupby("modulo")["grupo_origem"].nunique().items() if n > 1] \
        if not ult.empty else []
    ult = ult[ult.index.get_level_values(0).isin(mods)] if mods else ult.iloc[0:0]
    if not ult.empty:
        corte = ult.min()
        jan = f[f["modulo"].isin(mods) & (f["_d"] <= corte) & (f["_d"] > corte - pd.Timedelta(days=365))]
        tj = jan[jan["destino"].str.startswith("Recebedor")]
        if not tj.empty:
            proprio = {"CAIXA": "Recebedor na CAIXA", "BB": "Recebedor no BB"}
            # retenção = o pago a terceiros que fica no MESMO banco da conta (conciliação 01/11: a equipe
            # independente mostrou que o BB retém ~46% e a CAIXA ~16%; o painel só mostrava "% para a CAIXA")
            comparavel = tj.groupby("grupo_origem").apply(lambda x: pd.Series({
                "pago_terceiros": x["valor"].sum(),
                "pct_recebedor_caixa": x.loc[x["destino"] == "Recebedor na CAIXA", "valor"].sum() / x["valor"].sum(),
                "pct_fica_no_banco": x.loc[x["destino"] == proprio.get(x.name, "—"), "valor"].sum() / x["valor"].sum()}),
                include_groups=False).reset_index()
            comparavel["periodo"] = f"{(corte - pd.Timedelta(days=364)).strftime('%m/%Y')} a {corte.strftime('%m/%Y')}"
    # o que não aparece: banco que parou de publicar → saídas efetivas (sem aplicação) não publicadas desde então,
    # pelo ritmo dos 12 meses anteriores à parada (conciliação 01/11: a equipe B estimou R$ 12–14 bi com os
    # débitos brutos, que incluem aplicação — dinheiro que fica no banco; pelo efetivo, a ordem é ~R$ 6 bi)
    nao_publicado = []
    hoje = pd.Timestamp(str((d.get("meta") or {}).get("dia") or pd.Timestamp.today().date()))
    ult_all = normaliza.ultimo_extrato_efetivo(f)
    for (m, b), u in ult_all.items():
        if pd.isna(u) or (hoje - u).days <= 60:
            continue
        x = f[(f["modulo"] == m) & (f["grupo_origem"] == b) & (f["_d"] > u - pd.Timedelta(days=365))
              & (f["destino"] != "Aplicação financeira")]
        meses = (hoje - u).days / 30.44
        nao_publicado.append({"modulo": m, "grupo_banco": b, "ultimo_extrato": u.strftime("%d/%m/%Y"),
                              "meses_sem_extrato": round(meses, 1), "saidas_mes_antes": x["valor"].sum() / 12,
                              "estimativa_nao_publicada": x["valor"].sum() / 12 * meses})
    fora = rec[~rec["grupo_destino"].isin(["CAIXA"])].head(500)
    return {"tabela": f.groupby(["origem", "destino"], as_index=False)["valor"].sum(), "matriz": matriz,
            "matriz_pct": pct_linha, "por_mes": por_mes, "recebedores": rec.head(1000), "recebedores_fora": fora,
            "total": tot, "vazamento": float(saida_cx["valor"].sum()), "entrada": float(entrada_cx["valor"].sum()),
            "sem_info_caixa": float(sem_info_cx["valor"].sum()), "comparavel": comparavel,
            "nao_publicado": pd.DataFrame(nao_publicado),
            "por_destino": f.groupby("destino")["valor"].sum().reindex(DESTINOS).dropna(),
            "confere": abs(float(matriz.to_numpy().sum()) - tot) < 0.01,
            "periodo": (mes["_m"].min(), mes["_m"].max()) if not mes.empty else (None, None)}


def leitura_destino(de: dict, brl, pct) -> list[str]:
    if not de:
        return []
    pdst = de["por_destino"]
    tot = de["total"]
    out = []
    terc = pdst[[i for i in pdst.index if i.startswith("Recebedor")]].sum()
    if terc:
        cx = pdst.get("Recebedor na CAIXA", 0)
        out.append(f"Dos {brl(terc)} pagos a terceiros com banco conhecido, <b>{pct(cx / terc)}</b> foram para recebedores "
                   "com conta na CAIXA (período inteiro; se o extrato de um banco parou, a parte dele fica "
                   "subestimada — a comparação justa, na mesma janela, está abaixo).")
    nao = pdst.get("Banco do recebedor não informado", 0)
    if nao and tot:
        out.append(f"{pct(nao / tot)} das saídas não informam o banco de quem recebe (a fonte não publica).")
    if de["vazamento"]:
        out.append(f"<b>{brl(de['vazamento'])}</b> saíram de contas CAIXA para recebedores com conta em outro banco "
                   f"(vazamento comprovado); outros {brl(de.get('sem_info_caixa', 0))} saíram sem o banco de quem recebe "
                   f"informado. No sentido contrário, {brl(de['entrada'])} saíram de contas do concorrente para recebedores "
                   "na CAIXA.")
    cp = de.get("comparavel")
    if cp is not None and not cp.empty and len(cp) > 1:
        out.append("Comparação justa (mesmos 12 meses, " + cp["periodo"].iloc[0] + ", antes de o extrato CAIXA parar): "
                   + "; ".join(f"das contas {r.grupo_origem}, {pct(r.pct_recebedor_caixa)} do pago a terceiros foi para "
                               "recebedor na CAIXA" for r in cp.itertuples()) + ".")
        if "pct_fica_no_banco" in cp:
            ret = {r.grupo_origem: r.pct_fica_no_banco for r in cp.itertuples()}
            if "CAIXA" in ret and "BB" in ret:
                out.append(f"<b>Retenção no próprio banco</b>, na mesma janela: das contas BB, <b>{pct(ret['BB'])}</b> do "
                           f"pago a terceiros fica no BB; das contas CAIXA, só <b>{pct(ret['CAIXA'])}</b> fica na CAIXA. "
                           "Os fornecedores e recebedores dos entes com conta CAIXA operam, na maioria, em outros "
                           "bancos: é a maior fuga de recursos da cadeia e o alvo de produtos de pagamento a "
                           "fornecedores e de conta para recebedores.")
    np_ = de.get("nao_publicado")
    if np_ is not None and not np_.empty:
        out.append("<b>O que a fonte não mostra:</b> " + "; ".join(
            f"{r.grupo_banco} em {r.modulo} está sem extrato desde {r.ultimo_extrato} ({r.meses_sem_extrato:.0f} meses). "
            f"No ritmo dos 12 meses anteriores ({brl(r.saidas_mes_antes)} por mês, sem contar aplicações), cerca de "
            f"<b>{brl(r.estimativa_nao_publicada)}</b> de saídas não estão nos dados" for r in np_.itertuples())
            + ". Os totais de saída desse banco ficam subestimados nesse tamanho.")
    ap = pdst.get("Aplicação financeira", 0)
    if ap and tot:
        out.append(f"{pct(ap / tot)} das saídas são aplicações financeiras: dinheiro que continua no banco da conta.")
    return out


def filtros_ctx(ctx) -> tuple:
    """Os filtros do contexto da tela em forma imutável (chave da memória de cálculo)."""
    ex = tuple(sorted((k, tuple(v)) for k, v in (ctx.extra or {}).items()))
    return (tuple(ctx.modulos or ()) or None, tuple(ctx.anos or ()) or None, tuple(ctx.ufs or ()) or None,
            dict(ex) or None)


def nomes_modalidade(index) -> list[str]:
    return [nome_modalidade(m, True) for m in index]
