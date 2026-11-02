"""Marts do CRM: a visão 360 de cada ente com os dados do Portal da Transparência + o que o painel já sabe.

Regras de integridade (conferidas também pela auditoria do painel):
  * cada fato tem uma chave natural; linha repetida idêntica é removida e CONTADA; mesma chave com valores
    diferentes é contradição — fica a versão mais recente e o caso vai para crm_qualidade;
  * carteira do ente: recebido_12m = caixa_conhecido_12m + concorrente_conhecido_12m + sem_banco_12m.
    O "conhecido" vem de fontes com banco (FNS e ordens bancárias das Especiais) e NUNCA é somado ao recebido
    (seria dupla contagem): é uma parte dele. Se o conhecido passar do recebido, é contradição e é reportada;
  * números do Portal chegam como texto brasileiro ("1.234,56"; "- 26.002,00"); ilegível vira vazio, nunca zero.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import portal_api as pa
from .normaliza import sem_acento

# campos esperados por conjunto: (nome canônico, candidatos na API, obrigatório)
ESPERADOS = {
    "recursos": [("doc", ("codigoPessoa", "codigoFavorecido", "cpfCnpj", "cnpj"), True),
                 ("nome", ("nomePessoa", "nomeFavorecido", "nome"), False),
                 ("mes", ("anoMes", "mesAno", "mes", "dataReferencia"), False),
                 ("valor", ("valor", "valorRecebido", "valorTransferido"), True),
                 ("uf", ("siglaUFPessoa", "ufPessoa", "siglaUf", "uf"), False),
                 ("municipio", ("municipioPessoa", "nomeMunicipioPessoa", "nomeMunicipio", "municipio"), False),
                 ("orgao_superior", ("nomeOrgaoSuperior", "orgaoSuperior"), False),
                 ("orgao", ("nomeOrgao", "orgao"), False),
                 ("ug", ("nomeUG", "nomeUnidadeGestora", "unidadeGestora"), False),
                 ("cod_orgao_superior", ("codigoOrgaoSuperior",), False), ("cod_orgao", ("codigoOrgao",), False),
                 ("cod_ug", ("codigoUG", "codigoUnidadeGestora"), False),
                 ("tipo", ("tipoPessoa", "tipoFavorecido"), False)],
    "emendas": [("codigo", ("codigoEmenda",), True), ("ano", ("ano",), False), ("tipo", ("tipoEmenda",), False),
                ("autor", ("nomeAutor", "autor"), True), ("numero", ("numeroEmenda",), False),
                ("localidade", ("localidadeDoGasto",), False), ("funcao", ("funcao",), False),
                ("empenhado", ("valorEmpenhado",), True), ("liquidado", ("valorLiquidado",), True),
                ("pago", ("valorPago",), True), ("resto_pago", ("valorRestoPago",), False)],
    "emenda_docs": [("codigo_documento", ("codigoDocumento", "documento"), True), ("fase", ("fase",), True),
                    ("data", ("data", "dataDocumento"), False), ("valor", ("valor", "valorDocumento"), False)],
    "documento": [("codigo_documento", ("documento", "codigoDocumento"), True),
                  ("doc_favorecido", ("codigoFavorecido", "favorecido.codigo", "cpfCnpjFavorecido",
                                      "codigoFormatadoFavorecido"), True),
                  ("favorecido", ("nomeFavorecido", "favorecido.nome"), False),
                  ("valor", ("valor", "valorDocumento"), True), ("uf", ("ufFavorecido", "uf"), False),
                  ("data", ("data", "dataEmissao"), False)],
    # documento SÓ de pessoa jurídica: 'sancionado.codigoFormatado' pode trazer CPF completo e não é lido
    "sancao": [("doc", ("pessoa.cnpjFormatado", "pessoaJuridica.cnpjFormatado"), True),
               ("nome", ("pessoa.nome", "pessoaJuridica.nome"), False),
               ("inicio", ("dataInicioSancao", "dataReferencia"), False), ("fim", ("dataFimSancao",), False),
               ("tipo", ("tipoSancao.descricaoResumida", "tipoSancao.descricaoPortal", "motivo"), False),
               ("orgao", ("orgaoSancionador.nome", "orgaoSuperior.nome", "orgaoSancionador"), False),
               ("id", ("id",), False)],
    "presenca": [("cod_ibge", ("municipio.codigoIBGE", "codigoIbge", "codigoIBGE"), True),
                 ("mes", ("dataReferencia", "mesAno"), False), ("valor", ("valor",), True),
                 ("beneficiarios", ("quantidadeBeneficiados", "quantidade"), False)],
}
# raízes de CNPJ de bancos: aparecem como "favorecidos" (tarifas, repasses operacionais), mas não são entes nem
# clientes de custódia; contar o que o banco "recebe" como receita do ente inflaria a carteira
BANCOS_RAIZ = {"00000000": "Banco do Brasil", "00360305": "CAIXA", "07237373": "Banco do Nordeste",
               "04902979": "Banco da Amazônia", "33657248": "BNDES"}


def eh_banco(doc: pd.Series) -> pd.Series:
    return doc.fillna("").astype(str).str[:8].isin(BANCOS_RAIZ) & (doc.fillna("").astype(str).str.len() == 14)


NUMERICOS = {"valor", "empenhado", "liquidado", "pago", "resto_pago", "beneficiarios"}


def _canonico(df: pd.DataFrame, conjunto: str, chave_esperados: str | None = None) -> tuple[pd.DataFrame, list[dict]]:
    esp = ESPERADOS[chave_esperados or conjunto]
    campos, out = [], pd.DataFrame(index=df.index)
    for nome, cand, obrig in esp:
        c = pa.campo(df, *cand) if not df.empty else None
        campos.append({"conjunto": conjunto, "campo": nome, "coluna_api": c, "obrigatorio": obrig,
                       "encontrado": c is not None, "linhas": int(len(df))})
        if c is None:
            out[nome] = np.nan if nome in NUMERICOS else None
        elif nome in NUMERICOS:
            out[nome] = df[c].map(pa.num_br)
        else:
            out[nome] = df[c].astype(object).where(df[c].notna(), None)
    if "_unidade" in df:
        out["_unidade"] = df["_unidade"]
    return out, campos


def _dedup(df: pd.DataFrame, chave: list[str], conjunto: str, qual: list[dict], ordem: str | None = None) -> pd.DataFrame:
    """Remove linhas idênticas (contando) e resolve chaves conflitantes pela versão mais recente (contando)."""
    if df.empty:
        qual.append({"conjunto": conjunto, "linhas": 0, "duplicadas_identicas": 0, "chaves_conflitantes": 0})
        return df
    cols = [c for c in df.columns if c != "_unidade" and not c.startswith("_ord")]
    n0 = len(df)
    sem_ident = df.drop_duplicates(cols)
    ident = n0 - len(sem_ident)
    if ordem and ordem in sem_ident:
        sem_ident = sem_ident.sort_values(ordem)
    conflito = int(sem_ident.duplicated(chave, keep=False).sum())
    final = sem_ident.drop_duplicates(chave, keep="last")
    qual.append({"conjunto": conjunto, "linhas": int(len(final)), "duplicadas_identicas": int(ident),
                 "chaves_conflitantes": conflito})
    return final


def _ordem_unidade(df: pd.DataFrame, idx: dict) -> pd.Series:
    return df["_unidade"].map(lambda u: idx.get(u, {}).get("baixado_em", "")) if "_unidade" in df else ""


def _mes(serie: pd.Series, padrao: pd.Series | None = None) -> pd.Series:
    """'202608', '08/2026', '2026-08-01', '01/08/2026' → '2026-08'."""
    s = serie.fillna("").astype(str).str.strip()
    out = pd.Series(None, index=s.index, dtype="object")
    m = s.str.fullmatch(r"\d{6}")
    out[m] = s[m].str[:4] + "-" + s[m].str[4:]
    m2 = s.str.fullmatch(r"\d{2}/\d{4}")
    out[m2] = s[m2].str[3:] + "-" + s[m2].str[:2]
    m3 = s.str.match(r"\d{4}-\d{2}")
    out[m3] = s[m3].str[:7]
    m4 = s.str.fullmatch(r"\d{2}/\d{2}/\d{4}")
    out[m4] = s[m4].str[6:] + "-" + s[m4].str[3:5]
    if padrao is not None:
        out = out.fillna(padrao)
    return out


def _ratear_documentos(x: pd.DataFrame) -> pd.DataFrame:
    """Uma ordem bancária pode pagar várias emendas; o detalhe traz o valor TOTAL da ordem. Sem rateio, o mesmo
    dinheiro contaria uma vez por emenda. Regra: documentos exclusivos valem inteiros; os compartilhados são
    divididos na proporção do que falta pagar em cada emenda (valor pago − exclusivos). Soma por documento = valor
    da ordem (conta reversa conferida pela auditoria)."""
    if x.empty:
        return x.assign(compartilhado=False)
    n = x.groupby("codigo_documento")["codigo_emenda"].transform("nunique")
    x = x.assign(compartilhado=n > 1)
    if not x["compartilhado"].any():
        return x
    exclusivo = x[~x["compartilhado"]].groupby("codigo_emenda")["valor_pago_doc"].sum()
    falta = (x["_pago_emenda"].fillna(0) - x["codigo_emenda"].map(exclusivo).fillna(0)).clip(lower=0)
    sh = x["compartilhado"]
    peso = falta.where(sh, 0.0)
    soma = peso.groupby(x["codigo_documento"]).transform("sum")
    igual = 1.0 / n
    fator = (peso / soma.replace(0, np.nan)).fillna(igual)
    x.loc[sh, "valor_pago_doc"] = x.loc[sh, "valor_pago_doc"] * fator[sh]
    return x


# ------------------------------------------------------------------ consolidação dos conjuntos
def consolidar(bruto) -> dict[str, pd.DataFrame]:
    qual, campos = [], []
    out = {}

    # recursos recebidos (por favorecido, mês, órgão). Cada unidade = (UF, mês, tipo de favorecido): um fato só
    # pode estar numa unidade. Unidades antigas sem tipo (versão anterior da fila) sobrepõem as novas e são ignoradas.
    raw = pa.ler_conjunto(bruto, "recursos")
    idx = pa.indice(bruto, "recursos")
    legadas = {u for u, reg in idx.items() if "tipoFavorecido" not in reg.get("params", {})}
    cob = [{"uf": reg["params"].get("uf"), "mes": _mes(pd.Series([reg["params"].get("mesAnoInicio", "")])).iloc[0],
            "tipo_consulta": reg["params"].get("tipoFavorecido"), "ok": bool(reg.get("ok")),
            "linhas": reg.get("linhas"), "erro": reg.get("erro")} for u, reg in idx.items() if u not in legadas]
    out["crm_cobertura"] = pd.DataFrame(cob, columns=["uf", "mes", "tipo_consulta", "ok", "linhas", "erro"])
    n_leg = int(raw["_unidade"].isin(legadas).sum()) if "_unidade" in raw else 0
    if n_leg:
        raw = raw[~raw["_unidade"].isin(legadas)]
    r, c = _canonico(raw, "recursos")
    campos += c
    bancos = pd.DataFrame()
    agregadas = 0
    if not r.empty:
        par = r["_unidade"].map(lambda u: idx.get(u, {}).get("params", {}))
        r["mes"] = _mes(r["mes"], par.map(lambda p: _mes(pd.Series([p.get("mesAnoInicio", "")])).iloc[0]))
        r["uf"] = r["uf"].fillna(par.map(lambda p: p.get("uf")))
        r["tipo_consulta"] = par.map(lambda p: p.get("tipoFavorecido"))
        r["doc"] = pa.doc_limpo(r["doc"])
        r = r[r["doc"].str.len() == 14]
        b = eh_banco(r["doc"])
        bancos, r = r[b], r[~b].copy()
        r["_ord"] = _ordem_unidade(r, idx)
    # chave pelos CÓDIGOS (nomes mudam de grafia); sem código, cai no nome
    for cod, nome in (("cod_orgao_superior", "orgao_superior"), ("cod_orgao", "orgao"), ("cod_ug", "ug")):
        if cod in r:
            r["_k_" + cod] = r[cod].astype(object).where(r[cod].notna(), r[nome]).astype(str)
    chave = ["doc", "mes", "_k_cod_orgao_superior", "_k_cod_orgao", "_k_cod_ug"]
    if not r.empty:
        # linha idêntica (todas as colunas) = duplicação → removida e contada; mesma chave com valores diferentes
        # DENTRO da mesma unidade = lançamentos distintos do mesmo órgão no mês → somados (e contados)
        cols = [x for x in r.columns if not x.startswith("_")]
        n0 = len(r)
        r = r.drop_duplicates(cols + ["_unidade"])
        ident = n0 - len(r)
        agregadas = int(r.duplicated(chave + ["_unidade"], keep=False).sum())
        r = r.groupby(chave + ["_unidade"], as_index=False, dropna=False).agg(
            {**{x: "last" for x in r.columns if x not in chave + ["_unidade", "valor"]}, "valor": lambda v: v.sum(min_count=1)})
        conflito = int(r.duplicated(chave, keep=False).sum())     # mesma chave em unidades diferentes: não deveria
        r = r.sort_values("_ord").drop_duplicates(chave, keep="last")
    else:
        ident = conflito = 0
    qual.append({"conjunto": "recursos", "linhas": int(len(r)), "duplicadas_identicas": int(ident),
                 "chaves_conflitantes": conflito, "linhas_agregadas": agregadas, "linhas_unidades_legadas": n_leg,
                 "linhas_de_bancos_excluidas": int(len(bancos)),
                 "valor_de_bancos_excluido": float(bancos["valor"].sum()) if not bancos.empty else 0.0})
    base_cols = ["cnpj", "nome", "mes", "valor", "uf", "municipio", "orgao_superior", "orgao", "ug", "cod_orgao_superior",
                 "cod_orgao", "cod_ug", "tipo", "tipo_consulta"]
    out["crm_recebido"] = r.rename(columns={"doc": "cnpj"}).reindex(columns=base_cols) if not r.empty else \
        pd.DataFrame(columns=base_cols)

    # emendas
    raw = pa.ler_conjunto(bruto, "emendas")
    idx = pa.indice(bruto, "emendas")
    e, c = _canonico(raw, "emendas")
    campos += c
    if not e.empty:
        e["_ord"] = _ordem_unidade(e, idx)
        e["codigo"] = e["codigo"].astype(str)
    e = _dedup(e, ["codigo"], "emendas", qual, "_ord")
    out["crm_emenda"] = e.drop(columns=[c for c in ("_ord", "_unidade") if c in e]) if not e.empty else \
        pd.DataFrame(columns=[n for n, _, _ in ESPERADOS["emendas"]])

    # documentos das emendas: vale só a unidade mais recente de cada emenda (o valor pago entra na chave da unidade)
    raw = pa.ler_conjunto(bruto, "emenda_docs")
    idx = pa.indice(bruto, "emenda_docs")
    dcs, c = _canonico(raw, "emenda_docs")
    campos += c
    if not dcs.empty:
        dcs["codigo_emenda"] = dcs["_unidade"].map(lambda u: str(idx.get(u, {}).get("params", {}).get("codigoEmenda", "")))
        dcs["_ord"] = _ordem_unidade(dcs, idx)
        ultima = dcs.sort_values("_ord").groupby("codigo_emenda")["_unidade"].last()
        dcs = dcs[dcs["_unidade"] == dcs["codigo_emenda"].map(ultima)]
        dcs["fase"] = dcs["fase"].fillna("").astype(str)
    dcs = _dedup(dcs, ["codigo_emenda", "codigo_documento", "fase"], "emenda_docs", qual, "_ord")

    # detalhe dos pagamentos (quem recebeu)
    raw = pa.ler_conjunto(bruto, "documento")
    dt, c = _canonico(raw, "documento")
    campos += c
    if not dt.empty:
        dt["doc_favorecido"] = pa.doc_limpo(dt["doc_favorecido"])
    dt = _dedup(dt, ["codigo_documento"], "documento", qual)
    if not dcs.empty:
        pag = dcs[dcs["fase"].str.lower().str.contains("pagamento")]
        x = pag.merge(dt[["codigo_documento", "doc_favorecido", "favorecido", "valor", "uf"]].rename(
            columns={"valor": "valor_detalhe"}), on="codigo_documento", how="left") if not dt.empty else \
            pag.assign(doc_favorecido=None, favorecido=None, valor_detalhe=np.nan, uf=None)
        x["valor_pago_doc"] = x["valor"].fillna(x["valor_detalhe"])
        x = x.merge(out["crm_emenda"][["codigo", "autor", "tipo", "ano", "pago"]].rename(
            columns={"codigo": "codigo_emenda", "pago": "_pago_emenda"}), on="codigo_emenda", how="left")
        x = _ratear_documentos(x)
        x = x.drop(columns=["_pago_emenda"])
        out["crm_emenda_pagamento"] = x.drop(columns=[c for c in ("_ord", "_unidade") if c in x])
    else:
        out["crm_emenda_pagamento"] = pd.DataFrame(columns=["codigo_emenda", "codigo_documento", "fase", "data", "valor",
                                                            "doc_favorecido", "favorecido", "valor_detalhe",
                                                            "valor_pago_doc", "autor", "tipo", "ano", "uf"])

    # sanções
    partes = []
    for nome in pa.SANCOES:
        raw = pa.ler_conjunto(bruto, nome)
        s, c = _canonico(raw, nome, "sancao")
        campos += c
        if not s.empty:
            s["cadastro"] = nome.upper()
            s["doc"] = pa.doc_limpo(s["doc"])
            s = s[s["doc"].str.len() == 14]            # pessoas físicas ficam de fora
            if nome == "cepim":                         # o CEPIM não informa o início do impedimento
                s["inicio"] = None
            partes.append(s)
    s = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if not s.empty:
        s["id"] = s["id"].fillna(s["doc"] + "|" + s["inicio"].fillna("").astype(str) + "|" + s["tipo"].fillna("").astype(str))
        s["id"] = s["id"].astype(str)
    s = _dedup(s, ["cadastro", "id"], "sancoes", qual)
    out["crm_sancao"] = s.drop(columns=[c for c in ("_unidade",) if c in s]).rename(columns={"doc": "cnpj"}) \
        if not s.empty else pd.DataFrame(columns=["cnpj", "nome", "inicio", "fim", "tipo", "orgao", "id", "cadastro"])

    # presença CAIXA (Novo Bolsa Família por município)
    raw = pa.ler_conjunto(bruto, "presenca")
    idx = pa.indice(bruto, "presenca")
    p, c = _canonico(raw, "presenca")
    campos += c
    if not p.empty:
        cod_param = p["_unidade"].map(lambda u: idx.get(u, {}).get("params", {}).get("codigoIbge"))
        mes_param = p["_unidade"].map(lambda u: _mes(pd.Series([idx.get(u, {}).get("params", {}).get("mesAno", "")])).iloc[0])
        p["cod_ibge"] = p["cod_ibge"].fillna(cod_param).astype(str).str.replace(r"\.0$", "", regex=True)
        p["mes"] = _mes(p["mes"], mes_param)
    p = _dedup(p, ["cod_ibge", "mes"], "presenca", qual)
    out["crm_presenca_bruta"] = p.drop(columns=[c for c in ("_unidade",) if c in p]) if not p.empty else \
        pd.DataFrame(columns=["cod_ibge", "mes", "valor", "beneficiarios"])

    out["crm_integridade"] = pa.integridade(bruto)
    out["crm_qualidade"] = pd.DataFrame(qual)
    out["crm_campos"] = pd.DataFrame(campos)
    return out


# ------------------------------------------------------------------ carteira total do ente
GRUPOS_ORGAO = [("Saúde", r"saude"), ("Educação", r"educacao"),
                ("Assistência social", r"desenvolvimento social|assistencia|cidadania"),
                ("Constitucionais (Fazenda)", r"fazenda|economia|transferencias a estados")]


def _grupo_orgao(s: pd.Series) -> pd.Series:
    n = s.fillna("").map(sem_acento).str.lower()
    out = pd.Series("Outros", index=s.index, dtype="object")
    for nome, padrao in reversed(GRUPOS_ORGAO):
        out[n.str.contains(padrao, regex=True)] = nome
    return out


def carteira(recebido: pd.DataFrame, repasses_outros: pd.DataFrame, pipeline: pd.DataFrame, ente_resumo: pd.DataFrame,
             mun_ref: pd.DataFrame, dia, cobertura: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por CNPJ que recebeu recursos nos 12 últimos meses publicados.
    Partes com banco conhecido: FNS (banco da conta do fundo de saúde) + ordens bancárias das Especiais."""
    cols = ["cnpj", "nome", "tipo_pessoa", "uf", "municipio", "cod_ibge", "recebido_12m", "saude_12m", "educacao_12m",
            "assistencia_12m", "constitucionais_12m", "outros_12m", "caixa_conhecido_12m", "concorrente_conhecido_12m",
            "sem_banco_12m", "meses_cobertos", "pct_banco_conhecido", "part_caixa_conhecido", "conhecido_excede", "custodia_caixa",
            "part_caixa_painel", "segmento"]
    if recebido.empty:
        return pd.DataFrame(columns=cols)
    r = recebido.dropna(subset=["mes"])
    fim = r["mes"].max()
    ini = (pd.Period(fim, "M") - 11).strftime("%Y-%m")
    r = r[(r["mes"] >= ini) & (r["mes"] <= fim)].assign(grupo=lambda x: _grupo_orgao(x["orgao_superior"].fillna(x["orgao"])))
    g = r.groupby("cnpj").agg(nome=("nome", "last"), uf=("uf", "last"), municipio=("municipio", "last"),
                              tipo_pessoa=("tipo", "last"), recebido_12m=("valor", "sum"))
    for grupo, col in (("Saúde", "saude_12m"), ("Educação", "educacao_12m"), ("Assistência social", "assistencia_12m"),
                       ("Constitucionais (Fazenda)", "constitucionais_12m"), ("Outros", "outros_12m")):
        g[col] = r[r["grupo"] == grupo].groupby("cnpj")["valor"].sum()
    g = g.fillna({c: 0.0 for c in cols if c.endswith("_12m")})

    # meses em que o recebido do ente está COMPLETO no Portal: a unidade (UF, mês, tipo do ente) foi baixada inteira.
    # As partes com banco conhecido só contam nesses meses — senão o "conhecido" de um mês sem recebido carregado
    # passaria do recebido (contradição falsa, causada por cobertura parcial).
    tipo_c = r.groupby("cnpj")["tipo_consulta"].last() if "tipo_consulta" in r else pd.Series(dtype=object)
    meses_ok = None
    if cobertura is not None and not cobertura.empty and tipo_c.notna().any():
        ok = cobertura[cobertura["ok"].astype(bool) & (cobertura["mes"] >= ini) & (cobertura["mes"] <= fim)]
        meses_ok = ok[["uf", "tipo_consulta", "mes"]].drop_duplicates()
        chave_ente = pd.DataFrame({"cnpj": g.index, "uf": g["uf"].values, "tipo_consulta": tipo_c.reindex(g.index).values})
        mc = chave_ente.merge(meses_ok, on=["uf", "tipo_consulta"], how="left")
        g["meses_cobertos"] = mc.groupby("cnpj")["mes"].nunique().reindex(g.index).fillna(0).astype(int)
        cobertos = mc.dropna(subset=["mes"])[["cnpj", "mes"]]
    else:
        g["meses_cobertos"] = r.groupby("cnpj")["mes"].nunique().reindex(g.index).fillna(0).astype(int)
        cobertos = None

    def _no_coberto(df: pd.DataFrame, col_cnpj: str) -> pd.DataFrame:
        if cobertos is None:
            return df
        return df.merge(cobertos.rename(columns={"cnpj": col_cnpj}), on=[col_cnpj, "mes"], how="inner")

    # partes com banco conhecido no mesmo período (sem somar ao recebido: são parte dele)
    cx = pd.Series(0.0, index=g.index)
    co = pd.Series(0.0, index=g.index)
    if repasses_outros is not None and not repasses_outros.empty:
        f = repasses_outros[(repasses_outros["fonte"] == "FNS") & repasses_outros["grupo_banco"].notna()].copy()
        f["mes"] = f["ano"].astype(int).astype(str) + "-" + f["mes"].astype(int).astype(str).str.zfill(2)
        f = _no_coberto(f[(f["mes"] >= ini) & (f["mes"] <= fim)], "cnpj")
        cx = cx.add(f[f["grupo_banco"] == "CAIXA"].groupby("cnpj")["valor"].sum(), fill_value=0)
        co = co.add(f[f["grupo_banco"] != "CAIXA"].groupby("cnpj")["valor"].sum(), fill_value=0)
    if pipeline is not None and not pipeline.empty and "data_ob" in pipeline:
        p = pipeline.assign(mes=pd.to_datetime(pipeline["data_ob"], errors="coerce").dt.strftime("%Y-%m"))
        p = p[(p["mes"] >= ini) & (p["mes"] <= fim) & (p["grupo_banco"] != "(sem banco)")]
        p = _no_coberto(p, "cnpj_ente")
        cx = cx.add(p[p["grupo_banco"] == "CAIXA"].groupby("cnpj_ente")["valor_pago"].sum(), fill_value=0)
        co = co.add(p[p["grupo_banco"] != "CAIXA"].groupby("cnpj_ente")["valor_pago"].sum(), fill_value=0)
    g["caixa_conhecido_12m"] = cx.reindex(g.index).fillna(0)
    g["concorrente_conhecido_12m"] = co.reindex(g.index).fillna(0)
    conhecido = g["caixa_conhecido_12m"] + g["concorrente_conhecido_12m"]
    positivo = g["recebido_12m"] > 0
    # recebido líquido ≤ 0 (devoluções maiores que repasses) não tem "parte conhecida": é caso à parte na auditoria
    g["conhecido_excede"] = positivo & (conhecido > g["recebido_12m"] * 1.005 + 1)
    g["sem_banco_12m"] = (g["recebido_12m"] - conhecido).clip(lower=0)
    g["pct_banco_conhecido"] = (conhecido / g["recebido_12m"].where(positivo)).clip(lower=0, upper=1)
    g["part_caixa_conhecido"] = g["caixa_conhecido_12m"] / conhecido.replace(0, np.nan)

    # o que o painel já sabe do ente (custódia e participação nos instrumentos)
    if ente_resumo is not None and not ente_resumo.empty:
        er = ente_resumo.set_index("cnpj_ente")
        for a, b in (("custodia_caixa", "saldo_caixa"), ("part_caixa_painel", "part_caixa"), ("segmento", "segmento"),
                     ("cod_ibge", "cod_ibge")):
            if b in er:
                g[a] = er[b].reindex(g.index)
    for c in ("custodia_caixa", "part_caixa_painel", "segmento", "cod_ibge"):
        if c not in g:
            g[c] = np.nan
    # município pelo nome quando o ente não está no painel
    if mun_ref is not None and not mun_ref.empty:
        chave = g["uf"].fillna("") + "|" + g["municipio"].fillna("").map(sem_acento)
        mapa = mun_ref.drop_duplicates("chave_nome").set_index("chave_nome")["cod_ibge"]
        g["cod_ibge"] = g["cod_ibge"].fillna(chave.map(mapa))
    return g.reset_index().reindex(columns=cols)


# ------------------------------------------------------------------ presença CAIXA por município
def presenca(presenca_bruta: pd.DataFrame, cart: pd.DataFrame, ente_resumo: pd.DataFrame,
             mun_ref: pd.DataFrame) -> pd.DataFrame:
    cols = ["cod_ibge", "municipio", "uf", "mes", "bolsa_familia_mes", "beneficiarios", "valor_por_beneficiario",
            "recebido_12m_municipio", "valor_instrumentos", "part_caixa_instrumentos", "saldo_concorrente",
            "classe"]
    if presenca_bruta is None or presenca_bruta.empty:
        return pd.DataFrame(columns=cols)
    p = presenca_bruta.sort_values("mes").drop_duplicates("cod_ibge", keep="last")
    out = p.rename(columns={"valor": "bolsa_familia_mes"})[["cod_ibge", "mes", "bolsa_familia_mes", "beneficiarios"]].copy()
    out["valor_por_beneficiario"] = out["bolsa_familia_mes"] / out["beneficiarios"].replace(0, np.nan)
    if mun_ref is not None and not mun_ref.empty:
        m = mun_ref.drop_duplicates("cod_ibge").set_index("cod_ibge")
        out["municipio"], out["uf"] = out["cod_ibge"].map(m["municipio"]), out["cod_ibge"].map(m["uf"])
    if cart is not None and not cart.empty:
        out["recebido_12m_municipio"] = out["cod_ibge"].map(cart.groupby("cod_ibge")["recebido_12m"].sum())
    if ente_resumo is not None and not ente_resumo.empty:
        e = ente_resumo.assign(cod_ibge=ente_resumo["cod_ibge"].astype(str))
        agg = e.groupby("cod_ibge").agg(v=("valor_caixa", "sum"), t=("valor", "sum"), s=("saldo_concorrente", "sum"))
        com = (e["valor_caixa"] + e["valor_concorrente"]).groupby(e["cod_ibge"]).sum() \
            if "valor_concorrente" in e else agg["t"]
        out["valor_instrumentos"] = out["cod_ibge"].map(agg["t"])
        out["part_caixa_instrumentos"] = out["cod_ibge"].map(agg["v"] / com.replace(0, np.nan))
        out["saldo_concorrente"] = out["cod_ibge"].map(agg["s"])
    for c in cols:
        if c not in out:
            out[c] = np.nan
    part = out["part_caixa_instrumentos"]
    out["classe"] = np.select(
        [(out["bolsa_familia_mes"].fillna(0) > 0) & part.lt(0.5).fillna(False),
         (out["bolsa_familia_mes"].fillna(0) > 0) & part.ge(0.5).fillna(False)],
        ["Presença CAIXA, custódia no concorrente", "Presença CAIXA e custódia CAIXA"], "Sem dado de custódia")
    return out[cols]


# ------------------------------------------------------------------ conformidade
def data_br(v: pd.Series) -> pd.Series:
    """Datas das fontes vêm como ISO ('2026-06-10', com ou sem hora) ou brasileiras ('10/06/2026').
    pandas com dayfirst=True inverte dia e mês do ISO; por isso cada formato é lido separadamente."""
    t = v.astype(str).str.strip()
    iso = pd.to_datetime(t.str[:10].where(t.str.match(r"^\d{4}-\d{2}-\d{2}")), format="%Y-%m-%d", errors="coerce")
    br = pd.to_datetime(t.str[:10].where(t.str.match(r"^\d{2}/\d{2}/\d{4}")), format="%d/%m/%Y", errors="coerce")
    return iso.fillna(br)


def _juntar(v: pd.Series) -> str:
    return "; ".join(sorted({str(x) for x in v.dropna() if str(x).strip()}))


def _data_txt(v: pd.Series) -> pd.Series:
    return pd.to_datetime(v, errors="coerce").dt.strftime("%d/%m/%Y")


def _uma_por_cnpj(s: pd.DataFrame) -> pd.DataFrame:
    """Vários registros de sanção do mesmo CNPJ viram uma linha (senão o valor recebido contaria uma vez por registro)."""
    if s.empty:
        return s.assign(registros=pd.Series(dtype=int))
    ini = data_br(s["inicio"])
    fim = data_br(s["fim"])
    x = s.assign(_ini=ini, _fim=fim)
    g = x.groupby("cnpj").agg(nome=("nome", "first"), cadastro=("cadastro", _juntar), tipo=("tipo", _juntar),
                              _ini=("_ini", "min"), _fim=("_fim", lambda v: pd.NaT if v.isna().any() else v.max()),
                              registros=("cadastro", "size")).reset_index()
    g["inicio"], g["fim"] = _data_txt(g["_ini"]), _data_txt(g["_fim"])
    return g


def sancoes_vigentes(sanc: pd.DataFrame, data) -> pd.DataFrame:
    if sanc.empty:
        return sanc
    ini = data_br(sanc["inicio"])
    fim = data_br(sanc["fim"])
    d = pd.Timestamp(data)
    return sanc[(ini.isna() | (ini <= d)) & (fim.isna() | (fim >= d))]


def alertas_conformidade(sanc: pd.DataFrame, fluxo: pd.DataFrame, pagamentos: pd.DataFrame, recebido: pd.DataFrame,
                         potencial: pd.DataFrame, contas: pd.DataFrame, dia) -> pd.DataFrame:
    """CON-01: fornecedor com sanção vigente NA DATA do pagamento, pago com dinheiro de conta de transferência.
    CON-02: entidade no CEPIM recebendo recursos federais depois do início do impedimento.
    CON-03: ente da lista de prospecção com sanção vigente hoje (não prospectar sem análise)."""
    cols = ["regra", "gravidade", "cnpj", "nome", "cadastro", "tipo_sancao", "inicio", "fim", "cnpj_ente", "nome_ente",
            "banco_conta", "valor", "data", "detalhe"]
    if sanc is None or sanc.empty:
        return pd.DataFrame(columns=cols)
    s = sanc[sanc["cnpj"].str.len() == 14].copy()
    s["_ini"] = data_br(s["inicio"])
    s["_fim"] = data_br(s["fim"])
    out = []
    pags = []
    if fluxo is not None and not fluxo.empty and "doc_favorecido" in fluxo:
        f = fluxo[fluxo["doc_favorecido"].fillna("").str.len() == 14]
        f = f[~f["proprio_ente"].fillna(False).astype(bool)] if "proprio_ente" in f else f
        banco = pd.Series(dtype=object)
        if contas is not None and not contas.empty:
            banco = contas.drop_duplicates("id_agencia_conta").set_index("id_agencia_conta")["grupo_banco"]
        pags.append(pd.DataFrame({"cnpj": f["doc_favorecido"], "nome": f["favorecido"], "cnpj_ente": f["cnpj_ente"],
                                  "nome_ente": f["nome_ente"], "valor": f["valor"], "data": f["data"],
                                  "banco_conta": f["id_agencia_conta"].map(banco).fillna(f.get("grupo_origem")),
                                  "_fonte": "fluxo"}))
    if pagamentos is not None and not pagamentos.empty:
        p = pagamentos[pagamentos["doc_recebedor"].fillna("").astype(str).str.len() == 14]
        pags.append(pd.DataFrame({"cnpj": p["doc_recebedor"].astype(str), "nome": p["nome_recebedor"],
                                  "cnpj_ente": p["cnpj_ente"], "nome_ente": p["nome_ente"], "valor": p["valor"],
                                  "data": p["data"], "banco_conta": None, "_fonte": "pagamento"}))
    if pags:
        # o mesmo pagamento pode vir das duas fontes (fluxo das contas e fato_pagamento): vale o do fluxo (tem banco)
        pg = pd.concat(pags, ignore_index=True)
        pg["_d"] = data_br(pg["data"])
        pg["_k"] = (pg["cnpj"] + "|" + pg["cnpj_ente"].astype(str) + "|" + pd.to_numeric(pg["valor"], errors="coerce")
                    .round(2).astype(str) + "|" + pg["_d"].dt.strftime("%Y-%m-%d").fillna(""))
        do_fluxo = set(pg.loc[pg["_fonte"] == "fluxo", "_k"])
        pg = pg[(pg["_fonte"] == "fluxo") | ~pg["_k"].isin(do_fluxo)].reset_index(drop=True)
        pg["_pid"] = pg.index
        x = pg.merge(s[s["cadastro"].isin(["CEIS", "CNEP"])], on="cnpj", how="inner", suffixes=("", "_s"))
        x = x[(x["_ini"].isna() | (x["_d"] >= x["_ini"])) & (x["_fim"].isna() | (x["_d"] <= x["_fim"]))]
        if not x.empty:
            # um pagamento coberto por várias sanções conta UMA vez (as sanções são listadas juntas)
            um = x.groupby("_pid").agg(cnpj=("cnpj", "first"), nome=("nome", "first"), cnpj_ente=("cnpj_ente", "first"),
                                       nome_ente=("nome_ente", "first"), banco_conta=("banco_conta", "first"),
                                       valor=("valor", "first"), data=("data", "first"),
                                       cadastro=("cadastro", _juntar), tipo=("tipo", _juntar),
                                       inicio=("_ini", "min"), fim=("_fim", "max"), sancoes=("cadastro", "size"))
            g = um.groupby(["cnpj", "cnpj_ente", "banco_conta"], dropna=False).agg(
                nome=("nome", "first"), nome_ente=("nome_ente", "first"), cadastro=("cadastro", _juntar),
                tipo=("tipo", _juntar), inicio=("inicio", "min"), fim=("fim", "max"), valor=("valor", "sum"),
                data=("data", "max"), pagamentos=("valor", "size"), sancoes=("sancoes", "max")).reset_index()
            g["inicio"], g["fim"] = _data_txt(g["inicio"]), _data_txt(g["fim"])
            g["regra"], g["tipo_sancao"] = "CON-01", g["tipo"]
            g["gravidade"] = np.where(g["banco_conta"] == "CAIXA", "alta (conta CAIXA)", "média")
            g["detalhe"] = g["pagamentos"].astype(str) + " pagamento(s) durante a sanção; " + \
                g["sancoes"].astype(str) + " registro(s) de sanção"
            out.append(g)
    cep = _uma_por_cnpj(s[s["cadastro"] == "CEPIM"])
    if recebido is not None and not recebido.empty and not cep.empty:
        r = recebido.merge(cep, on="cnpj", how="inner", suffixes=("", "_s"))
        r["_m"] = pd.to_datetime(r["mes"] + "-01", errors="coerce")
        r = r[r["_ini"].isna() | (r["_m"] >= r["_ini"].dt.to_period("M").dt.to_timestamp())]
        if not r.empty:
            g = r.groupby(["cnpj"], dropna=False).agg(
                nome=("nome", "first"), cadastro=("cadastro", "first"), tipo_sancao=("tipo_s", "first"),
                inicio=("inicio", "first"), fim=("fim", "first"), registros=("registros", "first"),
                valor=("valor", "sum"), data=("mes", "max")).reset_index()
            g["regra"], g["gravidade"] = "CON-02", "alta"
            g["detalhe"] = ("entidade hoje no CEPIM (" + g["registros"].astype(str) + " registro(s)), impedida de receber "
                            "transferências, com recursos federais recebidos no período; o cadastro não informa desde "
                            "quando: verificar a data do impedimento")
            out.append(g)
    if potencial is not None and not potencial.empty:
        vig = _uma_por_cnpj(sancoes_vigentes(s, dia))
        z = potencial[["cnpj_ente", "nome_ente"]].drop_duplicates("cnpj_ente").merge(
            vig.rename(columns={"cnpj": "cnpj_ente"}), on="cnpj_ente")
        if not z.empty:
            z = z.assign(regra="CON-03", gravidade="atenção", cnpj=z["cnpj_ente"], tipo_sancao=z["tipo"],
                         detalhe="ente ou entidade (inclui OSC) da lista de prospecção com " + z["registros"].astype(str)
                         + " registro(s) vigente(s) em " + z["cadastro"].astype(str))
            out.append(z)
    if not out:
        return pd.DataFrame(columns=cols)
    return pd.concat(out, ignore_index=True).reindex(columns=cols).sort_values(["regra", "valor"], ascending=[True, False])


# ------------------------------------------------------------------ rede de relacionamento
def rede(emenda_pag: pd.DataFrame, ente_resumo: pd.DataFrame, fluxo: pd.DataFrame, alertas: pd.DataFrame,
         max_fornecedores_por_ente: int = 10) -> pd.DataFrame:
    """Arestas: parlamentar → ente (emendas pagas) · ente → banco (instrumentos) · ente → fornecedor (pagamentos)
    · fornecedor → sanção. Cada aresta tem valor e fonte; nada é somado entre fontes diferentes."""
    cols = ["origem_tipo", "origem", "origem_id", "destino_tipo", "destino", "destino_id", "valor", "fonte", "banco"]
    partes = []
    if emenda_pag is not None and not emenda_pag.empty:
        e = emenda_pag[emenda_pag["doc_favorecido"].fillna("").str.len() == 14]
        g = e.groupby(["autor", "doc_favorecido"], dropna=False).agg(destino=("favorecido", "first"),
                                                                    valor=("valor_pago_doc", "sum")).reset_index()
        partes.append(pd.DataFrame({"origem_tipo": "parlamentar", "origem": g["autor"], "origem_id": g["autor"],
                                    "destino_tipo": "ente", "destino": g["destino"], "destino_id": g["doc_favorecido"],
                                    "valor": g["valor"], "fonte": "Portal · emendas pagas", "banco": None}))
    if ente_resumo is not None and not ente_resumo.empty:
        for col, banco in (("valor_caixa", "CAIXA"), ("valor_concorrente", "concorrente")):
            if col in ente_resumo:
                x = ente_resumo[ente_resumo[col] > 0]
                partes.append(pd.DataFrame({"origem_tipo": "ente", "origem": x["nome_ente"], "origem_id": x["cnpj_ente"],
                                            "destino_tipo": "banco", "destino": banco, "destino_id": banco,
                                            "valor": x[col], "fonte": "Transferegov · instrumentos", "banco": banco}))
    if fluxo is not None and not fluxo.empty and "doc_favorecido" in fluxo:
        f = fluxo[(fluxo["doc_favorecido"].fillna("").str.len() == 14) & ~fluxo["proprio_ente"].fillna(False).astype(bool)]
        if not f.empty:
            g = f.groupby(["cnpj_ente", "doc_favorecido"]).agg(origem=("nome_ente", "first"), destino=("favorecido", "first"),
                                                               valor=("valor", "sum")).reset_index()
            g = g.sort_values("valor", ascending=False).groupby("cnpj_ente").head(max_fornecedores_por_ente)
            partes.append(pd.DataFrame({"origem_tipo": "ente", "origem": g["origem"], "origem_id": g["cnpj_ente"],
                                        "destino_tipo": "fornecedor", "destino": g["destino"],
                                        "destino_id": g["doc_favorecido"], "valor": g["valor"],
                                        "fonte": "Transferegov · pagamentos", "banco": None}))
    if alertas is not None and not alertas.empty:
        a = alertas[alertas["regra"] == "CON-01"].drop_duplicates(["cnpj", "cadastro"])
        partes.append(pd.DataFrame({"origem_tipo": "fornecedor", "origem": a["nome"], "origem_id": a["cnpj"],
                                    "destino_tipo": "sanção", "destino": a["cadastro"] + " · " + a["tipo_sancao"].fillna(""),
                                    "destino_id": a["cadastro"] + "|" + a["cnpj"], "valor": a["valor"],
                                    "fonte": "Portal · sanções", "banco": None}))
    return pd.concat(partes, ignore_index=True).reindex(columns=cols) if partes else pd.DataFrame(columns=cols)


# ------------------------------------------------------------------ prioridade do CRM
def prioridade(cart: pd.DataFrame, potencial: pd.DataFrame, presenca_m: pd.DataFrame, janela: pd.DataFrame,
               alertas: pd.DataFrame, emenda_pag: pd.DataFrame, ente_resumo: pd.DataFrame | None = None) -> pd.DataFrame:
    """CRM-01: nota 0–100 = 35% potencial de custódia + 25% dinheiro sem banco conhecido + 20% valor na janela de
    escolha + 10% presença CAIXA no município + 10% emendas recebidas; sanção vigente zera a nota."""
    cols = ["cnpj_ente", "nome_ente", "uf", "cod_ibge", "prioridade", "potencial_custodia", "sem_banco_12m",
            "valor_em_disputa", "bolsa_familia_mes", "emendas_12m", "alerta_conformidade", "proxima_acao"]
    if potencial is None or potencial.empty:
        return pd.DataFrame(columns=cols)
    b = potencial[["cnpj_ente", "nome_ente", "uf", "potencial_custodia"]].copy()
    if cart is not None and not cart.empty:
        c = cart.drop_duplicates("cnpj").set_index("cnpj")
        b["sem_banco_12m"] = b["cnpj_ente"].map(c["sem_banco_12m"])
        b["cod_ibge"] = b["cnpj_ente"].map(c["cod_ibge"])
    # município do ente pelo cadastro do painel (antes só vinha do Portal: quem ainda não aparecia no Portal
    # ficava sem município e perdia o componente de presença — 67% dos entes na carga de 01/11)
    if ente_resumo is not None and not ente_resumo.empty and "cod_ibge" in ente_resumo:
        cod = ente_resumo.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["cod_ibge"]
        b["cod_ibge"] = b.get("cod_ibge", pd.Series(index=b.index, dtype=object)).fillna(b["cnpj_ente"].map(cod))
    if "cod_ibge" in b:
        b["cod_ibge"] = b["cod_ibge"].astype(str).str.replace(r"\.0$", "", regex=True).replace({"nan": None, "None": None})
    if janela is not None and not janela.empty and "valor_em_disputa" in janela:
        b["valor_em_disputa"] = b["cnpj_ente"].map(janela.groupby("cnpj_ente")["valor_em_disputa"].sum())
    if presenca_m is not None and not presenca_m.empty and "cod_ibge" in b:
        b["bolsa_familia_mes"] = b["cod_ibge"].astype(str).map(presenca_m.set_index("cod_ibge")["bolsa_familia_mes"])
    if emenda_pag is not None and not emenda_pag.empty:
        ep = emenda_pag.assign(_d=data_br(emenda_pag["data"]))
        if ep["_d"].notna().any():                     # 12 meses de verdade (antes somava o histórico todo)
            ep = ep[ep["_d"] > ep["_d"].max() - pd.Timedelta(days=365)]
        b["emendas_12m"] = b["cnpj_ente"].map(ep.groupby("doc_favorecido")["valor_pago_doc"].sum())
    for ccol in cols:
        if ccol not in b:
            b[ccol] = np.nan
    al = set(alertas.loc[alertas["regra"].isin(["CON-02", "CON-03"]), "cnpj"]) if alertas is not None and not alertas.empty else set()
    b["alerta_conformidade"] = b["cnpj_ente"].isin(al)

    def pct(s):
        """Percentil SÓ entre quem tem valor (> 0); zero vale zero. Antes o percentil incluía os zeros e o menor
        valor positivo já valia ~0,6 (um potencial de R$ 1 dava ~20 pontos)."""
        s = pd.to_numeric(s, errors="coerce").fillna(0)
        return s.where(s > 0).rank(pct=True).fillna(0)
    # presença: a CAIXA paga o Bolsa Família em todos os municípios, então "tem ou não tem" não diferencia;
    # vale a intensidade da relação (percentil do valor pago no município)
    nota = (0.35 * pct(b["potencial_custodia"]) + 0.25 * pct(b["sem_banco_12m"]) + 0.20 * pct(b["valor_em_disputa"])
            + 0.10 * pct(b["bolsa_familia_mes"]) + 0.10 * pct(b["emendas_12m"]))
    b["prioridade"] = (nota * 100).round(0).where(~b["alerta_conformidade"], 0)
    b["proxima_acao"] = np.select(
        [b["alerta_conformidade"], b["valor_em_disputa"].fillna(0) > 0, b["sem_banco_12m"].fillna(0) > 0,
         b["bolsa_familia_mes"].fillna(0) > 0],
        ["Analisar com a Conformidade antes de abordar", "Agir antes da escolha do banco (janela aberta)",
         "Apresentar centralização da movimentação na CAIXA", "Usar a relação já existente (benefícios pagos pela CAIXA)"],
        "Visita de relacionamento")
    return b.sort_values("prioridade", ascending=False)[cols]
