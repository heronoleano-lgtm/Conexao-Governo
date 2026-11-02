"""Camada analítica: dimensões e fatos comuns aos módulos.

Tudo converge para o ENTE (CNPJ de 14 dígitos), com banco padronizado em `banco`
(código COMPE sem zeros) e `grupo_banco` (CAIXA, BB, BNB, ... ou '(sem banco)').

Fatos produzidos (todos com a coluna `modulo`):
  fato_instrumento   plano de ação / convênio: origem (órgão, programa, parlamentar), destino (ente),
                     banco da conta, valor, área de política
  fato_conta         contas bancárias e saldos
  fato_pipeline      empenhado ainda não pago (vai entrar nas contas)
  fato_executor      executores das Especiais (conta própria, possível vazamento)
  fato_destinacao    para que o dinheiro vai: área de política (Especiais), natureza de despesa (FaF)
  fato_fluxo         débitos das contas: banco de origem -> banco de destino, tipo de movimento
  fato_pagamento     quem recebeu no fim: fornecedores declarados (Especiais) e beneficiários (FaF)
  fato_emenda        vínculo parlamentar -> instrumento (Especiais e Discricionárias)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .ingest_api import ultimo_bruto
from .normaliza import chave_conta, col, conta_valida, data, doc, grupo_banco, numero, sem_acento, serie_banco

COLS_INSTR = ["modulo", "id_instrumento", "codigo", "ano", "cnpj_ente", "nome_ente", "uf", "cod_ibge",
              "banco", "grupo_banco", "agencia", "conta", "id_agencia_conta", "situacao", "situacao_conta",
              "valor", "parlamentar", "objeto", "data_referencia", "orgao", "programa", "area"]
COLS_FLUXO = ["modulo", "id_agencia_conta", "cnpj_ente", "nome_ente", "uf", "grupo_origem", "grupo_destino",
              "tipo_movimento", "proprio_ente", "tipo_favorecido", "favorecido", "doc_favorecido", "valor", "data", "mes"]
COLS_PAG = ["modulo", "id_instrumento", "id_pagamento", "cnpj_ente", "nome_ente", "uf", "doc_recebedor", "nome_recebedor",
            "tipo_doc", "natureza", "valor", "data"]
COLS_DEST = ["modulo", "id_instrumento", "tipo", "destinacao", "valor"]
COLS_EMENDA = ["modulo", "id_instrumento", "parlamentar", "tipo_parlamentar", "valor"]

# órgão do Fundo a Fundo -> área de política (para comparar com as Especiais)
AREA_ORGAO_FAF = {"MinC": "Cultura", "SENASP": "Segurança Pública", "DIRPP": "Segurança Pública",
                  "FNDE": "Educação", "SPPE": "Trabalho", "MCID": "Transporte"}


def _vazio(cols):
    return pd.DataFrame(columns=cols)


def _num(df, nome):
    return numero(df[nome]) if nome in df.columns else pd.Series(0.0, index=df.index)


def _str(df, nome):
    return df[nome].astype("object").where(df[nome].notna(), None) if nome in df.columns else \
        pd.Series([None] * len(df), index=df.index, dtype="object")


# Conciliação de 01/11 (equipes independentes × painel): "APL AUTOM", "APL FUNDO" e "AP CDB" (R$ 8,6 bi) são
# aplicações e caíam em pagamento sem banco; "iss" sem fronteira de palavra pegava "Emissão de Ordem Bancária"
# (R$ 1,06 bi de pagamentos contados como tributo); DOC/TED INTERNET/ELETRÔNICO/PESSOAL da CAIXA são tarifas
# (~R$ 11 cada); GRU ao Tesouro (CNPJ raiz 00394460) é devolução.
RX_APLICACAO = r"aplic|aplica?o\b|resgate|rsgte|poupan|bb fix|invest|\bcdb\b|\bap cdb|rende|\bapl\b|apl\.aut"
RX_TRIBUTO = (r"\btarifa|\biof\b|imposto|tribut|\bdarf\b|\bgps\b|\binss\b|\birrf\b|\biss\b|\bissqn\b|\bfgts\b"
              r"|doc/ted (?:internet|eletronico|pessoal)")
RX_DEVOLUCAO = r"devolu|\bgru\b"
RAIZ_TESOURO = "00394460"
ETAPA_EMPENHO, ETAPA_MINUTA = "Empenho emitido", "Minuta de empenho (ainda não emitido)"


def tipo_movimento(descricao: pd.Series, doc_favorecido: pd.Series | None = None) -> pd.Series:
    d = descricao.fillna("").map(sem_acento).str.lower()
    tesouro = (doc_favorecido.fillna("").astype(str).str.startswith(RAIZ_TESOURO).values
               if doc_favorecido is not None else np.zeros(len(d), bool))
    return pd.Series(np.select(
        [d.str.contains(RX_APLICACAO, regex=True), d.str.contains(RX_TRIBUTO, regex=True),
         d.str.contains(RX_DEVOLUCAO, regex=True) | tesouro],
        ["aplicação/resgate", "tributos/tarifas", "devolução"], default="pagamento/transferência"), index=d.index)


def _mesmo_nome(a: pd.Series, b: pd.Series) -> pd.Series:
    na, nb = a.fillna("").map(sem_acento), b.fillna("").map(sem_acento)
    return (na != "") & (na == nb)


# ---------------------------------------------------------------- Especiais
def especiais(bruto: Path) -> dict[str, pd.DataFrame]:
    L = lambda ep: ultimo_bruto(bruto, "especiais", ep)  # noqa: E731
    pa, ben, ex, sal = L("planos-acao-especiais"), L("beneficiarios-especiais"), L("executores-especiais"), \
        L("saldo-conta-gestao-financeira-especiais")
    emp, dh, ob = L("empenhos-especiais"), L("documentos-habeis-especiais"), L("ordens-pagamentos-ordens-bancarias-especiais")
    fin, rgn, dl = L("finalidade-especiais"), L("relatorios-gestao-novos-especiais"), \
        L("relatorios-gestao-documento-liquidacao-especiais")
    lanc, prog = L("gestao-financeira-lancamentos-especiais"), L("programas-especiais")
    out = {}
    if pa.empty:
        return out

    if not ben.empty:
        ben = ben.assign(cnpj_ente=doc(ben["cnpj_beneficiario"]))[
            ["id_beneficiario", "cnpj_ente", "nome_beneficiario", "uf_beneficiario"]]
        pa = pa.merge(ben, on="id_beneficiario", how="left")
    for c in ("cnpj_ente", "nome_beneficiario", "uf_beneficiario"):
        if c not in pa.columns:
            pa[c] = None
    orgao = "MGI (Transferências Especiais)"
    if not prog.empty and "sigla_orgao_superior_programa" in prog.columns:
        mapa = prog.set_index("id_programa")["sigla_orgao_superior_programa"].dropna()
        orgao_s = pa["id_programa"].map(mapa).fillna("MGI") + " (Transferências Especiais)" if "id_programa" in pa else orgao
    else:
        orgao_s = orgao

    banco = serie_banco(_str(pa, "codigo_banco_plano_acao"), _str(pa, "nome_banco_plano_acao"))
    instr = pd.DataFrame({
        "modulo": "Especiais",
        "id_instrumento": pa["id_plano_acao"].astype(str),
        "codigo": _str(pa, "codigo_plano_acao"),
        "ano": pd.to_numeric(_str(pa, "ano_plano_acao"), errors="coerce"),
        "cnpj_ente": pa["cnpj_ente"].fillna(""),
        "nome_ente": pa["nome_beneficiario"],
        "uf": pa["uf_beneficiario"],
        "cod_ibge": None,
        "banco": banco,
        "grupo_banco": banco.map(grupo_banco),
        "agencia": _str(pa, "numero_agencia_plano_acao"),
        "conta": _str(pa, "numero_conta_plano_acao"),
        "id_agencia_conta": chave_conta(_str(pa, "id_agencia_conta")),
        "situacao": _str(pa, "situacao_plano_acao"),
        "situacao_conta": _str(pa, "descricao_situacao_dado_bancario_plano_acao"),
        "valor": _num(pa, "valor_custeio_plano_acao").fillna(0) + _num(pa, "valor_investimento_plano_acao").fillna(0),
        "parlamentar": _str(pa, "nome_parlamentar_emenda_plano_acao"),
        "objeto": _str(pa, "nome_objeto"),
        "data_referencia": _str(pa, "data_aceite_plano_acao"),
        "orgao": orgao_s,
        "programa": "Emendas individuais (transferência especial)",
        "area": None,
    })

    # executores e contas
    contas_pa = instr.loc[instr["id_agencia_conta"].notna(),
                          ["modulo", "id_instrumento", "cnpj_ente", "nome_ente", "uf", "banco", "grupo_banco",
                           "id_agencia_conta", "situacao_conta"]].assign(origem="plano de ação")
    contas = [contas_pa]
    if not ex.empty:
        ex = ex.drop_duplicates("id_executor", keep="last")   # a fonte repete alguns executores
        bex = serie_banco(_str(ex, "codigo_banco_executor"), _str(ex, "nome_banco_executor"))
        inteiro = lambda v: str(int(float(v))) if v not in (None, "") else ""  # noqa: E731
        exc = pd.DataFrame({
            "modulo": "Especiais", "id_executor": ex["id_executor"].astype(str),
            "id_instrumento": ex["id_plano_acao"].astype(str),
            "banco": bex, "grupo_banco": bex.map(grupo_banco),
            "id_agencia_conta": chave_conta(_str(ex, "numero_agencia_executor").map(inteiro) + "-" +
                                            _str(ex, "numero_conta_executor").map(inteiro)),
            "situacao_conta": _str(ex, "descricao_situacao_dado_bancario_executor"),
            "origem": "executor", "cnpj_executor": doc(ex["cnpj_executor"]) if "cnpj_executor" in ex else "",
            "nome_executor": _str(ex, "nome_executor"),
            "valor_executor": _num(ex, "vl_custeio_executor").fillna(0) + _num(ex, "vl_investimento_executor").fillna(0),
        }).merge(instr[["id_instrumento", "cnpj_ente", "nome_ente", "uf", "grupo_banco"]]
                 .rename(columns={"grupo_banco": "grupo_banco_plano"}), on="id_instrumento", how="left")
        out["executores"] = exc
        contas.append(exc.drop(columns=["grupo_banco_plano", "cnpj_executor", "nome_executor", "valor_executor",
                                        "id_executor"]))

        # destinação: área de política por executor, valor rateado entre as áreas declaradas
        if not fin.empty:
            f = fin.assign(id_executor=fin["id_executor"].astype(str))
            f["_n"] = f.groupby("id_executor")["id_executor"].transform("count")
            f = f.merge(exc[["id_executor", "id_instrumento", "valor_executor"]], on="id_executor", how="inner")
            dest = pd.DataFrame({"modulo": "Especiais", "id_instrumento": f["id_instrumento"],
                                 "tipo": _str(f, "area_politica_publica_tipo_pt"),
                                 "destinacao": _str(f, "area_politica_publica_pt"),
                                 "valor": f["valor_executor"] / f["_n"]})
            out["destinacao"] = dest
            principal = (dest.groupby(["id_instrumento", "tipo"])["valor"].sum().reset_index()
                         .sort_values("valor").drop_duplicates("id_instrumento", keep="last")
                         .set_index("id_instrumento")["tipo"])
            instr["area"] = instr["id_instrumento"].map(principal)
    out["instrumentos"] = instr

    contas = pd.concat(contas, ignore_index=True)
    # conta sem número (só agência) não identifica conta nenhuma: "3351-" virava a chave "3351-0" e casava com
    # QUALQUER executor sem conta da agência (conciliação 01/11: R$ 118,7 mi atribuídos a entes por engano)
    contas = contas[conta_valida(contas["id_agencia_conta"])]
    if not sal.empty:
        s = sal.assign(id_agencia_conta=chave_conta(_str(sal, "id_agencia_conta").fillna(
            _str(sal, "agencia_batch").astype(str) + "-" + _str(sal, "conta_batch").astype(str))))
        s = s.assign(_d=_str(s, "data_saldo_conta")).sort_values("_d").drop_duplicates("id_agencia_conta", keep="last")
        s = pd.DataFrame({"id_agencia_conta": s["id_agencia_conta"], "saldo": _num(s, "saldo_final_gestao_financeira"),
                          "data_saldo": s["_d"]})
        ok = conta_valida(s["id_agencia_conta"])
        contas = contas.merge(s[ok], on="id_agencia_conta", how="left")
        # saldo que não casa com conta de plano nem de executor continua na custódia (antes sumia: R$ 81 mi),
        # sem ente; o banco vem do padrão do número quando é inequívoco (57 + 7 dígitos = CAIXA em 100% das
        # 37.918 contas com banco conhecido em 01/11) e, sem isso, fica "(sem banco)"
        orf = s[~s["id_agencia_conta"].isin(set(contas["id_agencia_conta"]))].copy()
        if not orf.empty:
            num = orf["id_agencia_conta"].fillna("").str.split("-").str[-1]
            cx = num.str.fullmatch(r"57\d{7}")
            orf = orf.assign(
                modulo="Especiais", id_instrumento=None, banco=np.where(cx, "104", None),
                grupo_banco=np.where(cx, "CAIXA", "(sem banco)"),
                id_agencia_conta=np.where(ok[orf.index], orf["id_agencia_conta"],
                                          "sem-numero-" + orf["id_agencia_conta"].fillna("?") + "-" +
                                          pd.Series(range(len(orf)), index=orf.index).astype(str)),
                situacao_conta=np.where(ok[orf.index],
                                        np.where(cx, "saldo sem plano ou executor; banco INFERIDO pelo número da conta "
                                                     "(57 + 7 dígitos = CAIXA)", "saldo sem plano ou executor"),
                                        "conta sem número na fonte"),
                origem="saldo sem vínculo", cnpj_ente=None, nome_ente=None, uf=None)
            contas = pd.concat([contas, orf.reindex(columns=contas.columns)], ignore_index=True)
    else:
        contas["saldo"], contas["data_saldo"] = np.nan, None
    contas = contas.drop_duplicates(["id_agencia_conta", "origem"])
    # uma conta pode servir ao plano e a vários executores (ou a vários planos): o saldo é da conta e entra uma
    # vez só — na linha do plano de ação, se houver; as demais linhas ficam com saldo zero
    contas = contas.assign(_o=contas["origem"].map({"plano de ação": 0, "executor": 1}).fillna(2)).sort_values("_o",
                                                                                                         kind="stable")
    repetida = contas["id_agencia_conta"].duplicated(keep="first")
    contas.loc[repetida, "saldo"] = 0.0
    contas["conta_compartilhada"] = contas["id_agencia_conta"].duplicated(keep=False)
    out["contas"] = contas.drop(columns="_o")

    # pipeline e velocidade (empenho -> ordem bancária)
    if not emp.empty:
        e = pd.DataFrame({"id_empenho": emp["id_empenho"].astype(str),
                          "id_instrumento": emp["id_plano_acao"].astype(str),
                          "valor_empenho": _num(emp, "valor_empenho").fillna(0),
                          "data_empenho": _str(emp, "data_emissao_empenho"),
                          "natureza": _str(emp, "categoria_despesa_empenho")})
        # minuta = empenho ainda não emitido (aguardando geração): é previsão, não empenho (conciliação 01/11:
        # R$ 3,9 bi de minutas somavam ao "empenhado e não pago" de R$ 1,6 bi)
        sit = _str(emp, "descricao_situacao_empenho").fillna("").map(sem_acento).str.lower()
        e["etapa"] = np.where(sit.str.contains("minuta").values, ETAPA_MINUTA, ETAPA_EMPENHO)
        e["valor_pago"], e["data_ob"] = 0.0, None
        if not dh.empty:
            d = pd.DataFrame({"id_dh": dh["id_dh"].astype(str), "id_empenho": dh["id_empenho"].astype(str),
                              "valor_dh": _num(dh, "valor_dh").fillna(0), "data_ob": None})
            if not ob.empty and "numero_ordem_bancaria" in ob.columns:
                o = ob[ob["numero_ordem_bancaria"].notna()].assign(id_dh=lambda x: x["id_dh"].astype(str))
                d = d[d["id_dh"].isin(set(o["id_dh"]))].copy()
                if "data_emissao_ob" in o.columns:
                    d["data_ob"] = d["id_dh"].map(o.groupby("id_dh")["data_emissao_ob"].min())
            d["data_ob"] = d["data_ob"].astype("object")
            # créditos na conta: cada ordem bancária, com data e valor, na conta do plano (base da reconstituição
            # do saldo, regra SAL-01). O valor é o do documento hábil que gerou a OB.
            if d["data_ob"].notna().any():
                cr = d[d["data_ob"].notna()].merge(e[["id_empenho", "id_instrumento"]], on="id_empenho", how="left")
                pl = instr.drop_duplicates("id_instrumento").set_index("id_instrumento")
                out["creditos"] = pd.DataFrame({
                    "modulo": "Especiais", "id_instrumento": cr["id_instrumento"],
                    "id_agencia_conta": cr["id_instrumento"].map(pl["id_agencia_conta"]),
                    "grupo_banco": cr["id_instrumento"].map(pl["grupo_banco"]),
                    "cnpj_ente": cr["id_instrumento"].map(pl["cnpj_ente"]),
                    "data": cr["data_ob"].astype(str), "valor": cr["valor_dh"]})
            pago = d.groupby("id_empenho").agg(valor_pago=("valor_dh", "sum"), data_ob=("data_ob", "min"))
            e["valor_pago"] = e["id_empenho"].map(pago["valor_pago"]).fillna(0)
            e["data_ob"] = e["id_empenho"].map(pago["data_ob"])
        e["a_creditar"] = (e["valor_empenho"] - e["valor_pago"]).clip(lower=0).where(e["etapa"] == ETAPA_EMPENHO, 0.0)
        e["valor_minuta"] = e["valor_empenho"].where(e["etapa"] == ETAPA_MINUTA, 0.0)
        e["dias_ate_pagamento"] = (pd.to_datetime(e["data_ob"], errors="coerce") -
                                   pd.to_datetime(e["data_empenho"], errors="coerce")).dt.days
        e = e.merge(instr[["id_instrumento", "cnpj_ente", "nome_ente", "uf", "banco", "grupo_banco", "area"]],
                    on="id_instrumento", how="left")
        out["pipeline"] = e.assign(modulo="Especiais")

    # fluxo: débitos das contas (por onde passa e para onde vai)
    if not lanc.empty:
        lanc = lanc[_str(lanc, "tipo_operacao_gestao_financeira").fillna("D") == "D"] \
            if "tipo_operacao_gestao_financeira" in lanc.columns else lanc
        bo = serie_banco(_str(lanc, "codigo_banco_gestao_financeira"))
        bd = serie_banco(_str(lanc, "codigo_banco_favorecido_gestao_financeira").map(
            lambda v: "" if v in (None, 0, "0") else v))
        datas = _str(lanc, "data_lancamento_gestao_financeira")
        fl = pd.DataFrame({
            "modulo": "Especiais", "id_agencia_conta": chave_conta(_str(lanc, "id_agencia_conta")),
            "cnpj_ente": doc(_str(lanc, "cnpj_ente_solicitante_gestao_financeira")),
            "nome_ente": _str(lanc, "nome_ente_solicitante_gestao_financeira"), "uf": None,
            "grupo_origem": bo.map(grupo_banco), "grupo_destino": bd.map(grupo_banco),
            "tipo_movimento": tipo_movimento(_str(lanc, "descricao_gestao_financeira"),
                                             doc(_str(lanc, "doc_favorecido_gestao_financeira"))),
            # próprio ente: CNPJ do favorecido = CNPJ do ente (o documento vem aberto para CNPJ; CPF vem '***');
            # sem CNPJ, cai para o nome igual
            "proprio_ente": ((doc(_str(lanc, "doc_favorecido_gestao_financeira")).replace("", np.nan) ==
                              doc(_str(lanc, "cnpj_ente_solicitante_gestao_financeira")).replace("", "x")).values
                             | _mesmo_nome(_str(lanc, "nome_favorecido_gestao_financeira"),
                                           _str(lanc, "nome_ente_solicitante_gestao_financeira")).values),
            "tipo_favorecido": _str(lanc, "tipo_favorecido_gestao_financeira").map(
                {1: "CPF", 2: "CNPJ", "1": "CPF", "2": "CNPJ"}).fillna("não identificado"),
            "favorecido": _str(lanc, "nome_favorecido_gestao_financeira"),
            # só CNPJ (14 dígitos); CPF vem mascarado e fica vazio
            "doc_favorecido": doc(_str(lanc, "doc_favorecido_gestao_financeira")).where(
                lambda x: x.fillna("").str.fullmatch(r"\d{14}"), ""),
            "valor": _num(lanc, "valor_gestao_financeira").fillna(0),
            "data": datas, "mes": datas.fillna("").str.slice(0, 7),
        })
        uf = instr.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["uf"]
        fl["uf"] = fl["cnpj_ente"].map(uf)
        out["fluxo"] = fl

    # pagamentos declarados nos relatórios de gestão
    if not dl.empty:
        ligacao = (rgn[["id_relatorio_gestao_novo", "id_plano_acao"]].astype(str).drop_duplicates("id_relatorio_gestao_novo")
                   if not rgn.empty else pd.DataFrame(columns=["id_relatorio_gestao_novo", "id_plano_acao"]))
        p = dl.assign(id_relatorio_gestao_novo=dl["id_relatorio_gestao_novo"].astype(str)).merge(
            ligacao, on="id_relatorio_gestao_novo", how="left")
        docs = _str(p, "tx_identificacao_recebedor_mascarado_relatorio_gestao_dl").fillna(
            _str(p, "tx_identificacao_recebedor_relatorio_gestao_dl"))
        pag = pd.DataFrame({
            "modulo": "Especiais", "id_instrumento": _str(p, "id_plano_acao"),
            "doc_recebedor": docs, "nome_recebedor": _str(p, "tx_nome_recebedor_relatorio_gestao_dl"),
            "tipo_doc": _str(p, "tp_doc_recebedor_relatorio_gestao_dl"),
            "natureza": _str(p, "tx_natureza_relatorio_gestao_dl"),
            "valor": _num(p, "vl_pagamento_relatorio_gestao_dl").fillna(0),
            "data": _str(p, "dt_pagamento_relatorio_gestao_dl"),
        }).merge(instr[["id_instrumento", "cnpj_ente", "nome_ente", "uf"]], on="id_instrumento", how="left")
        out["pagamentos"] = pag

    out["emendas"] = instr.loc[instr["parlamentar"].notna(), ["modulo", "id_instrumento", "parlamentar", "valor"]] \
        .assign(tipo_parlamentar="INDIVIDUAL")
    return out


# ---------------------------------------------------------------- Fundo a Fundo
def fundoafundo(bruto: Path) -> dict[str, pd.DataFrame]:
    L = lambda ep: ultimo_bruto(bruto, "fundoafundo", ep)  # noqa: E731
    pa, db, prog = L("planos-acao"), L("planos-acao-dados-bancarios"), L("programas")
    dest, sub = L("planos-acao-destinacao-recursos"), L("gestao-financeira-subtransacoes")
    out = {}
    if pa.empty:
        return out
    if not db.empty:
        b = db.assign(_banco=serie_banco(_str(db, "codigo_banco_plano_acao_dado_bancario"),
                                         _str(db, "nome_banco_plano_acao_dado_bancario")))
        principal = b.drop_duplicates("id_plano_acao", keep="last")[
            ["id_plano_acao", "_banco", "numero_agencia_plano_acao_dado_bancario",
             "numero_conta_plano_acao_dado_bancario", "id_agencia_conta", "situacao_conta_plano_acao_dado_bancario"]]
        pa = pa.merge(principal, on="id_plano_acao", how="left")
    if not prog.empty:
        cols = [c for c in ["id_programa", "nome_programa", "sigla_orgao_superior_programa",
                            "nome_orgao_superior_programa"] if c in prog.columns]
        pa = pa.merge(prog[cols].drop_duplicates("id_programa"), on="id_programa", how="left")

    banco = _str(pa, "_banco").fillna("")
    sigla = _str(pa, "sigla_orgao_superior_programa")
    instr = pd.DataFrame({
        "modulo": "Fundo a Fundo",
        "id_instrumento": pa["id_plano_acao"].astype(str),
        "codigo": _str(pa, "codigo_plano_acao"),
        "ano": _ano_faf(_str(pa, "codigo_plano_acao"), data(_str(pa, "data_inicio_vigencia_plano_acao")).dt.year),
        "cnpj_ente": doc(_str(pa, "cnpj_ente_recebedor_plano_acao")),
        "nome_ente": _str(pa, "nome_ente_recebedor_plano_acao"),
        "uf": _str(pa, "uf_ente_recebedor_plano_acao"),
        "cod_ibge": _str(pa, "codigo_ibge_municipio_ente_recebedor_plano_acao").map(
            lambda v: str(v).replace(".0", "") if v not in (None, "") else None),
        "banco": banco,
        "grupo_banco": banco.map(grupo_banco),
        "agencia": _str(pa, "numero_agencia_plano_acao_dado_bancario"),
        "conta": _str(pa, "numero_conta_plano_acao_dado_bancario"),
        "id_agencia_conta": chave_conta(_str(pa, "id_agencia_conta")),
        "situacao": _str(pa, "situacao_plano_acao"),
        "situacao_conta": _str(pa, "situacao_conta_plano_acao_dado_bancario"),
        "valor": _num(pa, "valor_total_repasse_plano_acao").fillna(0),
        "parlamentar": None,
        "objeto": _str(pa, "nome_programa"),
        "data_referencia": _str(pa, "data_inicio_vigencia_plano_acao"),
        "orgao": sigla.fillna(_str(pa, "sigla_orgao_repassador_plano_acao")),
        "programa": _str(pa, "nome_programa"),
        "area": sigla.map(AREA_ORGAO_FAF),
    })
    out["instrumentos"] = instr

    if not db.empty:
        saldo_col = next((c for c in db.columns if c.endswith("saldo_final_gestao_financeira")), None)
        bco = serie_banco(_str(db, "codigo_banco_plano_acao_dado_bancario"), _str(db, "nome_banco_plano_acao_dado_bancario"))
        out["contas"] = pd.DataFrame({
            "modulo": "Fundo a Fundo", "id_instrumento": db["id_plano_acao"].astype(str),
            "banco": bco, "grupo_banco": bco.map(grupo_banco),
            "id_agencia_conta": chave_conta(_str(db, "id_agencia_conta")),
            "situacao_conta": _str(db, "situacao_conta_plano_acao_dado_bancario"),
            "origem": "plano de ação",
            "saldo": _num(db, saldo_col) if saldo_col else np.nan,
            "data_saldo": None,
        }).merge(instr[["id_instrumento", "cnpj_ente", "nome_ente", "uf"]], on="id_instrumento", how="left")

    if not dest.empty:
        out["destinacao"] = pd.DataFrame({
            "modulo": "Fundo a Fundo", "id_instrumento": dest["id_plano_acao"].astype(str),
            "tipo": _str(dest, "tipo_despesa_destinacao_recursos_plano_acao"),
            "destinacao": _str(dest, "descricao_natureza_despesa_destinacao_recursos_plano_acao"),
            "valor": _num(dest, "valor_destinacao_recursos_plano_acao").fillna(0)})

    # fluxo FaF: débitos para CNPJ. O CNPJ do favorecido vem aberto, então "conta do próprio ente" é exato
    # (CNPJ do favorecido = CNPJ do ente). O banco de destino NÃO é informado pela API do FaF.
    lanc = L("gestao-financeira-lancamentos")
    if not lanc.empty:
        if "tipo_operacao_gestao_financeira" in lanc.columns:
            lanc = lanc[_str(lanc, "tipo_operacao_gestao_financeira").fillna("D") == "D"]
        cnpj_ente = doc(_str(lanc, "cnpj_ente_solicitante_gestao_financeira"))
        doc_fav = _str(lanc, "doc_favorecido_gestao_financeira_mask").fillna("")
        doc_fav = doc_fav.where(doc_fav.str.fullmatch(r"\d{14}"), "")
        nome_fav = _str(lanc, "nome_favorecido_gestao_financeira")
        publico = nome_fav.fillna("").map(sem_acento).str.contains(
            r"municipio|prefeitura|fundo municipal|fundo estadual|secretaria|estado d|governo d|fundacao municipal",
            regex=True)
        datas = _str(lanc, "data_lancamento_gestao_financeira")
        conta = chave_conta(_str(lanc, "id_agencia_conta"))
        prog_conta = {}
        if not db.empty and "id_agencia_conta" in db.columns:
            m = db[["id_agencia_conta", "id_plano_acao"]].astype(str).assign(
                id_agencia_conta=lambda x: chave_conta(x["id_agencia_conta"])).merge(
                instr[["id_instrumento", "orgao", "programa"]], left_on="id_plano_acao", right_on="id_instrumento", how="left")
            prog_conta = m.drop_duplicates("id_agencia_conta").set_index("id_agencia_conta")[["orgao", "programa"]]
        fl = pd.DataFrame({
            "modulo": "Fundo a Fundo", "id_agencia_conta": conta, "cnpj_ente": cnpj_ente,
            "nome_ente": _str(lanc, "nome_ente_solicitante_gestao_financeira"), "uf": None,
            "grupo_origem": "BB", "grupo_destino": "(sem banco)",
            "tipo_movimento": tipo_movimento(_str(lanc, "descricao_gestao_financeira"), doc_fav),
            "proprio_ente": (doc_fav != "") & (doc_fav == cnpj_ente),
            "tipo_favorecido": "CNPJ", "favorecido": nome_fav,
            "valor": _num(lanc, "valor_lancamento_gestao_financeira").fillna(0),
            "data": datas, "mes": datas.fillna("").str.slice(0, 7),
            "doc_favorecido": doc_fav, "favorecido_publico": publico,
        })
        if len(prog_conta):
            fl["orgao"] = fl["id_agencia_conta"].astype(str).map(prog_conta["orgao"])
            fl["programa"] = fl["id_agencia_conta"].astype(str).map(prog_conta["programa"])
        fl["uf"] = fl["cnpj_ente"].map(instr.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["uf"])
        out["fluxo"] = fl

    if not sub.empty:
        sit = _str(sub, "descricao_situacao_pagamento_subtransacao_gestao_financeira").fillna("")
        s = sub[~sit.str.contains("Cancel", case=False)]
        # quem pagou: a subtransação aponta para o lançamento, que traz o CNPJ do ente (antes ficava vazio e
        # pagamentos de entes diferentes ao mesmo recebedor, no mesmo dia e valor, pareciam duplicados)
        quem = pd.DataFrame(columns=["id_lancamento_gestao_financeira", "_cnpj", "_nome"])
        lanc_all = L("gestao-financeira-lancamentos")
        if not lanc_all.empty and "id_lancamento_gestao_financeira" in lanc_all.columns:
            quem = pd.DataFrame({"id_lancamento_gestao_financeira": _str(lanc_all, "id_lancamento_gestao_financeira"),
                                 "_cnpj": doc(_str(lanc_all, "cnpj_ente_solicitante_gestao_financeira")),
                                 "_nome": _str(lanc_all, "nome_ente_solicitante_gestao_financeira")}
                                ).drop_duplicates("id_lancamento_gestao_financeira")
        idl = _str(s, "id_lancamento_gestao_financeira") if "id_lancamento_gestao_financeira" in s.columns \
            else pd.Series(None, index=s.index, dtype=object)
        lig = pd.DataFrame({"id_lancamento_gestao_financeira": idl.values}).merge(
            quem, on="id_lancamento_gestao_financeira", how="left")
        uf_ente = instr.drop_duplicates("cnpj_ente").set_index("cnpj_ente")["uf"] if not instr.empty else pd.Series(dtype=object)
        out["pagamentos"] = pd.DataFrame({
            "modulo": "Fundo a Fundo", "id_instrumento": None, "cnpj_ente": lig["_cnpj"].values,
            "nome_ente": lig["_nome"].values, "uf": lig["_cnpj"].map(uf_ente).values,
            "id_pagamento": _str(s, "id_subtransacao_gestao_financeira").values
            if "id_subtransacao_gestao_financeira" in s.columns else None,
            "doc_recebedor": _str(s, "doc_beneficiario_subtransacao_gestao_financeira_mask"),
            "nome_recebedor": _str(s, "nome_beneficiario_subtransacao_gestao_financeira"),
            "tipo_doc": _str(s, "descricao_tp_pessoa_beneficiario_subtransacao_gestao_financeira"),
            "natureza": None,
            "valor": _num(s, "valor_subtransacao_gestao_financeira").fillna(0),
            "data": _str(s, "data_pagamento_subtransacao_gestao_financeira")})
    return out


# ---------------------------------------------------------------- Discricionárias (CSV)
def discricionarias(bruto: Path) -> dict[str, pd.DataFrame]:
    conv = ultimo_bruto(bruto, "discricionarias_csv", "siconv_convenio")
    prop = ultimo_bruto(bruto, "discricionarias_csv", "siconv_proposta")
    em = ultimo_bruto(bruto, "discricionarias_csv", "siconv_emenda")
    if conv.empty or prop.empty or "id_proposta" not in conv.columns:
        return {}
    df = conv.merge(prop, on="id_proposta", how="left", suffixes=("", "_prop"))
    banco = serie_banco(col(df, ["cd_banco"]), col(df, ["nm_banco"]))
    datas = data(col(df, ["dia_assin_conv", "dia_publ_conv"]))
    # convênio ainda não assinado não tem ano: vale o ano da proposta, quando o ente já escolheu o banco
    # (conciliação 01/11: 49.500 instrumentos sem ano ficavam fora da escolha anual de banco; as duas equipes
    # independentes usaram o ano da proposta e acharam 825 saídas/554 entradas contra 806/481 do painel)
    ano = pd.to_numeric(col(df, ["ano", "ano_assinatura"]), errors="coerce").fillna(datas.dt.year).fillna(
        pd.to_numeric(col(df, ["ano_prop"]), errors="coerce"))
    nr = col(df, ["nr_convenio"]).astype(str)
    ag, ct = col(df, ["cd_agencia"]).fillna("").astype(str), col(df, ["cd_conta"]).fillna("").astype(str)
    orgao = col(df, ["desc_orgao_sup"])

    parlamentar = pd.Series([None] * len(df), index=df.index, dtype="object")
    emendas = _vazio(COLS_EMENDA)
    if not em.empty and "id_proposta" in em.columns:
        e = em[em["id_proposta"].fillna("") != ""].copy()
        e["valor"] = numero(col(e, ["valor_repasse_emenda", "valor_repasse_proposta_emenda"])).fillna(0)
        mapa_nr = df[["id_proposta"]].assign(id_instrumento=nr.values).drop_duplicates("id_proposta")
        e = e.merge(mapa_nr, on="id_proposta", how="inner")
        emendas = pd.DataFrame({"modulo": "Discricionárias", "id_instrumento": e["id_instrumento"],
                                "parlamentar": col(e, ["nome_parlamentar"]),
                                "tipo_parlamentar": col(e, ["tipo_parlamentar"]), "valor": e["valor"]})
        princ = emendas.sort_values("valor").drop_duplicates("id_instrumento", keep="last").set_index("id_instrumento")["parlamentar"]
        parlamentar = nr.map(princ)

    instr = pd.DataFrame({
        "modulo": "Discricionárias",
        "id_instrumento": nr, "codigo": nr, "ano": ano,
        "cnpj_ente": doc(col(df, ["identif_proponente"])),
        "nome_ente": col(df, ["nm_proponente"]),
        "uf": col(df, ["uf_proponente"]),
        "cod_ibge": col(df, ["cod_munic_ibge"]).astype("object"),
        "banco": banco, "grupo_banco": banco.map(grupo_banco),
        "agencia": ag, "conta": ct,
        "id_agencia_conta": np.where((ag != "") & (ct != ""), ag + "-" + ct, "conv-" + nr),
        "situacao": col(df, ["sit_convenio", "situacao_convenio"]),
        "situacao_conta": col(df, ["situacao_conta"]),
        "valor": numero(col(df, ["vl_repasse_conv", "vl_global_conv"])).fillna(0),
        "parlamentar": parlamentar,
        "objeto": col(df, ["objeto_proposta", "modalidade"]),
        "data_referencia": col(df, ["dia_assin_conv"]),
        "orgao": orgao, "programa": col(df, ["desc_orgao", "modalidade"]), "area": orgao,
    })
    instr["natureza_juridica"] = col(df, ["natureza_juridica"])
    instr["ativo"] = col(df, ["instrumento_ativo"]).fillna("").str.upper().str.startswith("SIM")
    instr["desembolsado"] = numero(col(df, ["vl_desembolsado_conv"])).fillna(0)
    instr["fim_vigencia"] = data(col(df, ["dia_fim_vigenc_conv"])).dt.strftime("%Y-%m-%d")

    saldo = numero(col(df, ["vl_saldo_conta"]))
    contas = pd.DataFrame({
        "modulo": "Discricionárias", "id_instrumento": nr, "cnpj_ente": instr["cnpj_ente"],
        "nome_ente": instr["nome_ente"], "uf": instr["uf"], "banco": banco, "grupo_banco": instr["grupo_banco"],
        "id_agencia_conta": instr["id_agencia_conta"], "situacao_conta": instr["situacao_conta"],
        "origem": "convênio", "saldo": saldo, "data_saldo": None,
        "rendimento": numero(col(df, ["vl_rendimento_aplicacao"]))})
    # só convênios ativos ou com saldo: os encerrados não têm custódia
    contas = contas[instr["ativo"].values | (saldo.fillna(0).values > 0)]
    return {"instrumentos": instr, "contas": contas, "emendas": emendas}


# ---------------------------------------------------------------- Consolidação
def completar_ibge(instr: pd.DataFrame, entes_ref: pd.DataFrame, mun_ref: pd.DataFrame | None) -> pd.DataFrame:
    """Garante código IBGE (7 dígitos para município, 2 para estado) em todo instrumento:
    1) o que o módulo traz; 2) CNPJ -> Siconfi; 3) nome 'MUNICIPIO DE X' + UF -> lista do IBGE;
    4) entes estaduais ('ESTADO DE', 'SECRETARIA DE ESTADO', 'GOVERNO DO') -> código da UF."""
    from .referencias import UF_COD, chave_nome_ente
    cod = instr["cod_ibge"].astype("object").where(instr["cod_ibge"].notna(), None)
    cod = cod.map(lambda v: str(v).replace(".0", "") if v not in (None, "", "None", "nan") else None)
    if not entes_ref.empty:
        falta = cod.isna()
        cod[falta] = instr.loc[falta, "cnpj_ente"].map(entes_ref.set_index("cnpj")["cod_ibge"])
    if mun_ref is not None and not mun_ref.empty:
        falta = cod.isna()
        chave = chave_nome_ente(instr.loc[falta, "nome_ente"], instr.loc[falta, "uf"])
        cod[falta] = chave.map(mun_ref.drop_duplicates("chave_nome").set_index("chave_nome")["cod_ibge"])
    estadual = instr["nome_ente"].fillna("").map(sem_acento).str.contains(
        r"^(?:estado d|governo d|secretaria de estado|secretaria estadual|fundo estadual)", regex=True)
    falta = cod.isna() & estadual
    cod[falta] = instr.loc[falta, "uf"].map(UF_COD)
    out = instr.copy()
    out["cod_ibge"] = cod
    out["esfera"] = np.where(cod.fillna("").str.len() == 7, "Municipal",
                             np.where(cod.fillna("").str.len() == 2, "Estadual", "Outro"))
    return out


TIPO_MUN, TIPO_EST = "Município e órgãos municipais", "Estado e órgãos estaduais"
TIPO_CONS, TIPO_OSC, TIPO_EMP = "Consórcio público", "Organização da sociedade civil", "Empresa pública / economia mista"
TIPOS_PUBLICOS = [TIPO_MUN, TIPO_EST, TIPO_CONS]


def tipo_ente(instr: pd.DataFrame) -> pd.Series:
    """Tipo do ente pela natureza jurídica (convênios) ou pelo nome/código (Especiais e Fundo a Fundo).
    Um município tem vários CNPJs (prefeitura, fundos, secretarias): todos ficam como 'Município e órgãos municipais'
    e se juntam pelo código IBGE."""
    nj = instr.get("natureza_juridica", pd.Series("", index=instr.index)).fillna("").map(sem_acento)
    nome = instr["nome_ente"].fillna("").map(sem_acento)
    cod = instr["cod_ibge"].fillna("").astype(str)
    estadual = nome.str.contains(r"^(?:estado d|governo d|secretaria de estado|secretaria estadual|fundo estadual|"
                                 r"policia (?:militar|civil)|corpo de bombeiros|tribunal|assembleia|universidade estadual)",
                                 regex=True)
    return pd.Series(np.select(
        [nj.str.contains("sociedade civil"), nj.str.contains("consorcio") | nome.str.contains(r"\bconsorcio\b", regex=True),
         nj.str.contains("empresa publica|economia mista"), nj.str.contains("estadual") | estadual | (cod.str.len() == 2)],
        [TIPO_OSC, TIPO_CONS, TIPO_EMP, TIPO_EST], TIPO_MUN), index=instr.index)


def _ano_faf(codigo: pd.Series, ano_vigencia: pd.Series) -> pd.Series:
    """Ano do plano Fundo a Fundo. O código traz o exercício (UG 6 dígitos + ANO 4 + sequência 4, ex.:
    30882120250004-028276 → 2025); a data de início de vigência tem erros na fonte (1987, 2029). Usa o código e,
    sem ele, a vigência — desde que plausível."""
    from datetime import date as _d
    lim = _d.today().year + 1
    cod = codigo.fillna("").astype(str).str.extract(r"^\d{6}(\d{4})\d{4}")[0]
    a_cod = pd.to_numeric(cod, errors="coerce")
    a_cod = a_cod.where((a_cod >= 2000) & (a_cod <= lim))
    a_vig = pd.to_numeric(ano_vigencia, errors="coerce")
    a_vig = a_vig.where((a_vig >= 2000) & (a_vig <= lim))
    return a_cod.fillna(a_vig).astype(float)   # mesmo tipo das outras modalidades


CONTRATADO, PREVISTO, IMPEDIDO, CANCELADO = "contratado", "previsto", "impedido", "cancelado"


def etapa_instrumento(instr: pd.DataFrame) -> pd.Series:
    """Separa o que é dinheiro contratado do que ainda não é (ou nunca será). Red team 02/11: o "valor transferido"
    somava convênios anulados, cancelados e rescindidos, propostas nunca assinadas e planos impedidos — R$ 64 bi
    sem nenhum pagamento. Evidência usada na regra (dados de 01/11/2026):
    - Especiais: só planos CIENTE receberam ordem bancária; IMPEDIDO = impedido (fora dos valores, mas pode ser
      destravado: continua nas janelas de escolha); rejeitado = cancelado; aguardando ciência e plano em
      elaboração = previsto (zero pago);
    - Discricionárias: anulado, cancelado e rescindido = cancelado (zero desembolso, salvo R$ 0,43 bi de
      cancelados já assinados); sem data de assinatura = previsto;
    - Fundo a Fundo: rejeitado = cancelado; em elaboração = previsto (sem saldo)."""
    sit = instr["situacao"].fillna("").astype(str).map(sem_acento).str.lower()
    mod = instr["modulo"]
    cancel = sit.str.contains(r"anulad|cancelad|rescindid|extint|rejeitad", regex=True) & \
        ~sit.str.contains("impedid")
    imped = sit.str.contains("impedid")          # pode ser destravado: fora dos valores, dentro das janelas
    ass = instr["data_referencia"].notna() & (instr["data_referencia"].astype(str).str.strip() != "")
    prev = (((mod == "Especiais") & sit.str.contains(r"aguardando_ciencia|aguardando ciencia|elaboracao", regex=True))
            | ((mod == "Discricionárias") & ~ass)
            | ((mod == "Fundo a Fundo") & (sit == "em_elaboracao")))
    return pd.Series(np.select([cancel, imped, prev], [CANCELADO, IMPEDIDO, PREVISTO], CONTRATADO), index=instr.index)


def saldo_uma_vez(contas: pd.DataFrame) -> pd.DataFrame:
    """Uma conta bancária pode servir a vários instrumentos (no Fundo a Fundo, a mesma conta aparece em vários
    planos com o MESMO saldo). O saldo — e o rendimento — são da conta: entram numa linha só; as demais ficam com
    zero e marcadas como compartilhadas. Vale para todas as modalidades (auditoria de 01/11: R$ 764,7 mi do
    Fundo a Fundo eram contados mais de uma vez em permanência, variação e defasagem)."""
    if contas is None or contas.empty or "id_agencia_conta" not in contas:
        return contas
    c = contas.copy()
    s = pd.to_numeric(c["saldo"], errors="coerce")
    c["_tem"] = s.fillna(0).ne(0).astype(int)
    c = c.sort_values(["modulo", "id_agencia_conta", "_tem"], ascending=[True, True, False], kind="stable")
    rep = c.duplicated(["modulo", "id_agencia_conta"], keep="first")
    c.loc[rep, "saldo"] = 0.0
    if "rendimento" in c:
        c.loc[rep, "rendimento"] = 0.0
    comp = c.duplicated(["modulo", "id_agencia_conta"], keep=False)
    c["conta_compartilhada"] = comp if "conta_compartilhada" not in c else (comp | c["conta_compartilhada"].fillna(False).astype(bool))
    return c.drop(columns="_tem").sort_index()


def construir(bruto: Path, entes_ref: pd.DataFrame, mun_ref: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    partes = [especiais(bruto), fundoafundo(bruto), discricionarias(bruto)]

    def junta(chave, cols):
        dfs = [p[chave] for p in partes if chave in p and not p[chave].empty]
        return pd.concat(dfs, ignore_index=True) if dfs else _vazio(cols)

    instr = junta("instrumentos", COLS_INSTR)
    for c in COLS_INSTR:
        if c not in instr.columns:
            instr[c] = None
    contas = junta("contas", ["modulo", "id_instrumento", "banco", "grupo_banco", "id_agencia_conta", "situacao_conta",
                              "origem", "saldo", "data_saldo", "cnpj_ente", "nome_ente", "uf"])
    pipeline = junta("pipeline", ["modulo", "id_empenho", "id_instrumento", "etapa", "valor_empenho", "valor_pago",
                                  "a_creditar", "valor_minuta",
                                  "data_empenho", "data_ob", "dias_ate_pagamento", "natureza", "cnpj_ente",
                                  "nome_ente", "uf", "banco", "grupo_banco", "area"])
    executores = junta("executores", ["id_executor", "id_instrumento", "grupo_banco", "grupo_banco_plano",
                                      "cnpj_executor", "nome_executor", "valor_executor", "cnpj_ente", "nome_ente", "uf"])
    destinacao = junta("destinacao", COLS_DEST)
    fluxo = junta("fluxo", COLS_FLUXO)
    pagamentos = junta("pagamentos", COLS_PAG)
    emendas = junta("emendas", COLS_EMENDA)
    creditos = junta("creditos", ["modulo", "id_instrumento", "id_agencia_conta", "grupo_banco", "cnpj_ente", "data",
                                  "valor"])

    instr = completar_ibge(instr, entes_ref, mun_ref)
    # o mesmo ente pode vir com código só em um módulo: propaga pelo CNPJ
    por_cnpj = instr.dropna(subset=["cod_ibge"]).drop_duplicates("cnpj_ente").set_index("cnpj_ente")["cod_ibge"]
    falta = instr["cod_ibge"].isna()
    instr.loc[falta, "cod_ibge"] = instr.loc[falta, "cnpj_ente"].map(por_cnpj)
    instr["tipo_ente"] = tipo_ente(instr)
    instr["esfera"] = instr["tipo_ente"].map({TIPO_MUN: "Municipal", TIPO_EST: "Estadual"}).fillna("Outro")

    instr["ano"] = pd.to_numeric(instr["ano"], errors="coerce").astype("Int64")
    dim_ente = (instr[instr["cnpj_ente"].fillna("") != ""]
                .sort_values("ano", na_position="first")
                .groupby("cnpj_ente", as_index=False)
                .agg(nome_ente=("nome_ente", "last"), uf=("uf", "last"), cod_ibge=("cod_ibge", "last"),
                     esfera=("esfera", "last"), tipo_ente=("tipo_ente", "last"),
                     modulos=("modulo", lambda s: ", ".join(sorted(set(s))))))
    if mun_ref is not None and not mun_ref.empty:
        dim_ente = dim_ente.merge(mun_ref[["cod_ibge", "municipio"]], on="cod_ibge", how="left")
    else:
        dim_ente["municipio"] = None
    if not entes_ref.empty and "populacao" in entes_ref.columns:
        dim_ente = dim_ente.merge(entes_ref[["cnpj", "populacao"]].rename(columns={"cnpj": "cnpj_ente"}),
                                  on="cnpj_ente", how="left")
    return {"fato_instrumento": instr, "fato_conta": contas, "fato_pipeline": pipeline,
            "fato_executor": executores, "fato_destinacao": destinacao, "fato_fluxo": fluxo,
            "fato_pagamento": pagamentos, "fato_emenda": emendas, "fato_credito": creditos, "dim_ente": dim_ente}
