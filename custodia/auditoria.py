"""Auditoria diária da carga bruta: confere, interpreta e valida o que foi entregue antes de virar informação.

Roda dentro da carga diária (depois da transformação, antes de publicar) e também sozinha:
    python -m custodia.auditoria            (ou auditar_carga.bat)

Oito famílias de checagem, cada uma com status ok / atenção / crítico / não verificável e o impacto no painel:
  1. Completude      — a API informou N registros e chegaram N? tabela vazia? queda brusca contra o dia anterior?
  2. Estrutura       — colunas novas, removidas ou que ficaram totalmente vazias
  3. Identificadores — chaves duplicadas ou vazias
  4. Domínios        — CNPJ com dígito válido, UF existente, código de banco conhecido, datas possíveis, valores negativos
  5. Integridade     — ligações entre tabelas (plano → beneficiário, empenho → plano, OB → documento, convênio → proposta...)
  6. Coerência       — regras de negócio da fonte (pago ≤ empenhado, desembolsado ≤ repasse, empenho ≤ valor do plano)
  7. Frescor         — data de atualização do governo e último extrato publicado por banco
  8. Reconciliação   — o que entrou no bruto aparece igual nas tabelas do painel (contagem, valor e saldo)
O resultado vai para a tela "Auditoria da carga", para o histórico de auditorias e para um relatório HTML do dia.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import storage
from .ingest_api import ultimo_bruto

log = logging.getLogger(__name__)

OK, ATENCAO, CRITICO, NV = "ok", "atenção", "crítico", "não verificável"
ORDEM = {CRITICO: 0, ATENCAO: 1, NV: 2, OK: 3}
UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BANCOS_CONHECIDOS = {"1", "104", "4", "3", "37", "33", "237", "341", "756", "748", "41", "47", "21", "70", "85", "136"}

# ligações entre tabelas: (filho, coluna do filho, pai, coluna do pai, tolerância de órfãos, impacto)
RELACOES = [
    ("especiais/planos-acao-especiais", "id_beneficiario", "especiais/beneficiarios-especiais", "id_beneficiario", 0.001,
     "plano sem beneficiário fica sem ente (CNPJ, UF) e sai do mapa"),
    ("especiais/executores-especiais", "id_plano_acao", "especiais/planos-acao-especiais", "id_plano_acao", 0.001,
     "executor sem plano não entra no vazamento"),
    ("especiais/empenhos-especiais", "id_plano_acao", "especiais/planos-acao-especiais", "id_plano_acao", 0.001,
     "empenho sem plano não entra no dinheiro a receber"),
    ("especiais/documentos-habeis-especiais", "id_empenho", "especiais/empenhos-especiais", "id_empenho", 0.005,
     "pagamento sem empenho não é contado como pago"),
    ("especiais/ordens-pagamentos-ordens-bancarias-especiais", "id_dh", "especiais/documentos-habeis-especiais", "id_dh",
     0.005, "ordem bancária sem documento não marca o empenho como pago"),
    ("especiais/gestao-financeira-lancamentos-especiais", "id_agencia_conta",
     "_contas_especiais", "id_agencia_conta", 0.01,
     "lançamento de conta que não é de nenhum plano nem executor: some do fluxo por banco"),
    ("especiais/saldo-conta-gestao-financeira-especiais", "id_agencia_conta",
     "_contas_especiais", "id_agencia_conta", 0.01,
     "saldo de conta que não é de nenhum plano nem executor: fica fora da custódia"),
    ("fundoafundo/planos-acao-dados-bancarios", "id_plano_acao", "fundoafundo/planos-acao", "id_plano_acao", 0.001,
     "conta do Fundo a Fundo sem plano fica sem órgão e ente"),
    ("fundoafundo/gestao-financeira-lancamentos", "id_agencia_conta", "fundoafundo/planos-acao-dados-bancarios",
     "id_agencia_conta", 0.02, "transferência secundária sem conta conhecida"),
    ("discricionarias_csv/siconv_convenio", "id_proposta", "discricionarias_csv/siconv_proposta", "id_proposta", 0.001,
     "convênio sem proposta fica sem banco, ente e UF"),
    ("discricionarias_csv/siconv_emenda", "id_proposta", "discricionarias_csv/siconv_proposta", "id_proposta", 0.01,
     "emenda sem proposta não liga parlamentar ao convênio"),
    ("discricionarias_csv/siconv_desembolso", "nr_convenio", "discricionarias_csv/siconv_convenio", "nr_convenio", 0.01,
     "desembolso sem convênio"),
]
CHAVES = {
    "especiais/planos-acao-especiais": "id_plano_acao", "especiais/beneficiarios-especiais": "id_beneficiario",
    "especiais/executores-especiais": "id_executor", "especiais/empenhos-especiais": "id_empenho",
    "especiais/documentos-habeis-especiais": "id_dh", "especiais/saldo-conta-gestao-financeira-especiais": "id_agencia_conta",
    "especiais/gestao-financeira-lancamentos-especiais": "id_lancamento_gestao_financeira",
    "fundoafundo/planos-acao": "id_plano_acao", "fundoafundo/planos-acao-dados-bancarios": "id_plano_acao_dado_bancario",
    "fundoafundo/gestao-financeira-lancamentos": "id_lancamento_gestao_financeira",
    "discricionarias_csv/siconv_convenio": "nr_convenio", "discricionarias_csv/siconv_proposta": "id_proposta",
}


def _linha(familia, tabela, checagem, status, valor=None, referencia=None, detalhe="", impacto=""):
    return {"familia": familia, "tabela": tabela, "checagem": checagem, "status": status,
            "medido": None if valor is None else str(valor), "referencia": None if referencia is None else str(referencia),
            "detalhe": detalhe, "impacto": impacto}


def _digitos(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\D", "", regex=True)


def cnpj_valido(s: pd.Series) -> pd.Series:
    """Dígitos verificadores do CNPJ, vetorizado."""
    d = _digitos(s).str.zfill(14)
    ok_tam = d.str.len() == 14
    m = np.array([list(x) if len(x) == 14 and x.isdigit() else ["0"] * 14 for x in d], dtype=int)
    p1 = np.array([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    p2 = np.array([6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    r1 = (m[:, :12] * p1).sum(1) % 11
    d1 = np.where(r1 < 2, 0, 11 - r1)
    r2 = (np.c_[m[:, :12], d1] * p2).sum(1) % 11
    d2 = np.where(r2 < 2, 0, 11 - r2)
    repetido = d.str.match(r"^(\d)\1{13}$")
    return pd.Series(ok_tam.values & (m[:, 12] == d1) & (m[:, 13] == d2) & ~repetido.values, index=s.index)


# ------------------------------------------------------------------ famílias de checagem
def completude(manifestos: list[dict], anterior: pd.DataFrame) -> list[dict]:
    out = []
    ant = anterior.set_index("tabela_origem")["linhas"] if not anterior.empty else pd.Series(dtype=float)
    for m in manifestos or []:
        for c in m.get("cargas", []):
            tab = f"{m.get('modulo')}/{c.get('endpoint') or c.get('arquivo', '').replace('.zip', '')}"
            esp, car = c.get("esperado"), c.get("carregado", c.get("linhas"))
            if c.get("erro"):
                out.append(_linha("Completude", tab, "Download", CRITICO, detalhe=str(c["erro"])[:200],
                                  impacto="tabela do dia não entrou; o painel usa a última carga boa"))
                continue
            if c.get("motivo"):
                out.append(_linha("Completude", tab, "Download", OK, detalhe=c["motivo"]))
                continue
            if esp is not None and car is not None and int(esp) != int(car):
                out.append(_linha("Completude", tab, "Registros informados × recebidos", CRITICO, car, esp,
                                  f"faltaram {int(esp) - int(car):,} registros".replace(",", "."),
                                  "números da tabela incompletos"))
            elif car == 0:
                out.append(_linha("Completude", tab, "Tabela vazia", ATENCAO, 0, detalhe="a fonte não trouxe registros"))
            else:
                out.append(_linha("Completude", tab, "Registros informados × recebidos", OK, car, esp))
            nome = c.get("endpoint") or c.get("arquivo")
            if car is not None and nome in ant.index and pd.notna(ant[nome]) and ant[nome] > 0:
                var = (car - ant[nome]) / ant[nome]
                if var < -0.02:
                    out.append(_linha("Completude", tab, "Variação contra a carga anterior", CRITICO if var < -0.10 else ATENCAO,
                                      car, int(ant[nome]), f"{var:+.1%} de registros",
                                      "registros sumiram da fonte; confira se foi exclusão legítima"))
    return out


def estrutura(manifestos: list[dict], brutos: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for m in manifestos or []:
        for mud in m.get("mudancas_esquema", []) or []:
            out.append(_linha("Estrutura", f"{m.get('modulo')}/{mud.get('endpoint', '?')}", "Esquema da API mudou", ATENCAO,
                              detalhe=json.dumps(mud, ensure_ascii=False)[:250],
                              impacto="coluna nova pode trazer informação; removida pode quebrar cálculo"))
    for tab, df in brutos.items():
        if df.empty:
            continue
        vazias = [c for c in df.columns if df[c].isna().all()]
        if vazias and len(vazias) < len(df.columns):
            out.append(_linha("Estrutura", tab, "Colunas totalmente vazias", NV if len(vazias) < 3 else ATENCAO,
                              len(vazias), detalhe=", ".join(vazias[:8])))
    return out


def identificadores(brutos: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    for tab, chave in CHAVES.items():
        df = brutos.get(tab, pd.DataFrame())
        if df.empty or chave not in df.columns:
            out.append(_linha("Identificadores", tab, f"Chave {chave}", NV, detalhe="tabela ou coluna ausente"))
            continue
        nulos, dup = int(df[chave].isna().sum()), int(df[chave].dropna().duplicated().sum())
        st = OK if not nulos and not dup else (CRITICO if dup > len(df) * 0.01 else ATENCAO)
        out.append(_linha("Identificadores", tab, f"Chave {chave} única e preenchida", st, f"{dup} duplicadas, {nulos} vazias",
                          detalhe="" if st == OK else "registros repetidos podem dobrar valores",
                          impacto="" if st == OK else "somas podem estar infladas"))
    return out


def dominios(brutos: dict[str, pd.DataFrame], hoje: date) -> list[dict]:
    out = []
    lim_fut = pd.Timestamp(hoje) + pd.Timedelta(days=1)
    for tab, df in brutos.items():
        if df.empty:
            continue
        for c in df.columns:
            nome = str(c).lower()
            s = df[c].dropna()
            if s.empty:
                continue
            if nome.startswith(("cnpj", "identif_proponente")) or nome in ("doc_favorecido_gestao_financeira",):
                from .normaliza import doc
                x = s.astype(str)
                x = x[~x.str.contains(r"\*") & (x.str.strip() != "")]
                x = doc(x)                                  # tira '.0' e completa zeros, como o painel faz
                x = x[x.str.len() == 14]                    # só CNPJ (CPF fica de fora)
                if len(x):
                    inval = int((~cnpj_valido(x)).sum())
                    out.append(_linha("Domínios", tab, f"CNPJ válido em {c}", OK if inval == 0 else
                                      (ATENCAO if inval / len(x) < 0.01 else CRITICO), f"{inval} inválidos de {len(x)}",
                                      impacto="" if inval == 0 else "ente pode não casar com IBGE/Siconfi"))
            elif nome.startswith("uf") or nome.endswith("_uf") or nome.startswith("uf_"):
                inval = int((~s.astype(str).str.upper().isin(UFS)).sum())
                if inval:
                    out.append(_linha("Domínios", tab, f"UF existente em {c}", ATENCAO, f"{inval} fora das 27 UFs"))
            elif "codigo_banco" in nome or nome == "cd_banco":
                b = s.astype(str).str.replace(r"\.0$", "", regex=True).str.strip().str.lstrip("0")
                b = b[(b != "") & (b.str.lower() != "nan")]
                desc = b[~b.str.fullmatch(r"\d{1,3}")]     # código de banco é numérico de 1 a 3 dígitos
                if len(desc):
                    out.append(_linha("Domínios", tab, f"Código de banco válido em {c}", ATENCAO,
                                      f"{len(desc)} registros", detalhe=", ".join(desc.value_counts().head(5).index)))
            elif nome.startswith(("data_", "dia_", "dt_")):
                txt = s.astype(str)
                iso = txt.str.match(r"^\d{4}-\d{2}-\d{2}")
                d = pd.Series(pd.NaT, index=txt.index)
                d[iso] = pd.to_datetime(txt[iso], errors="coerce", format="ISO8601")   # com ou sem hora/microssegundos
                d[~iso] = pd.to_datetime(txt[~iso], errors="coerce", dayfirst=True, format="mixed")
                ruins = int(d.isna().sum())
                planejada = any(k in nome for k in ("fim", "vigenc", "prev", "vencimento", "inicio"))
                fut = 0 if planejada else int((d > lim_fut).sum())
                antigas = int((d < pd.Timestamp("1990-01-01")).sum())
                ruim = ruins + fut + antigas
                if ruim:
                    st = OK if ruim <= max(len(s) * 0.001, 0) else ATENCAO   # casos isolados não mudam números
                    out.append(_linha("Domínios", tab, f"Datas válidas em {c}", st,
                                      f"{ruins} ilegíveis, {fut} no futuro, {antigas} antes de 1990",
                                      f"{len(s):,} datas".replace(",", "."),
                                      "casos isolados de digitação na fonte" if st == OK else ""))
            elif nome.startswith(("valor", "vl_")) and "saldo" not in nome:
                v = pd.to_numeric(s, errors="coerce")
                neg = int((v < 0).sum())
                if neg:
                    out.append(_linha("Domínios", tab, f"Valores negativos em {c}", ATENCAO, f"{neg} registros",
                                      impacto="estornos ou erro de sinal na fonte"))
    return out


def _contas_especiais(brutos: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pa = brutos.get("especiais/planos-acao-especiais", pd.DataFrame())
    ex = brutos.get("especiais/executores-especiais", pd.DataFrame())
    partes = []
    if "id_agencia_conta" in pa:
        partes.append(pa["id_agencia_conta"])
    if {"numero_agencia_executor", "numero_conta_executor"} <= set(ex.columns):
        partes.append(ex["numero_agencia_executor"].astype(str) + "-" + ex["numero_conta_executor"].astype(str))
    return pd.DataFrame({"id_agencia_conta": pd.concat(partes, ignore_index=True)}) if partes else pd.DataFrame()


def integridade(brutos: dict[str, pd.DataFrame]) -> list[dict]:
    from .normaliza import chave_conta
    out = []
    brutos = {**brutos, "_contas_especiais": _contas_especiais(brutos)}
    for filho, cf, pai, cp, tol, impacto in RELACOES:
        f, p = brutos.get(filho, pd.DataFrame()), brutos.get(pai, pd.DataFrame())
        if f.empty or p.empty or cf not in f.columns or cp not in p.columns:
            out.append(_linha("Integridade", filho, f"{cf} existe em {pai.split('/')[-1].lstrip('_')}", NV,
                              detalhe="tabela ou coluna ausente"))
            continue
        norm = chave_conta if cf == "id_agencia_conta" else (lambda z: z.astype(str).str.replace(r"\.0$", "", regex=True))
        chaves_pai = set(norm(p[cp].dropna()))
        x = norm(f[cf].dropna())
        orf = int((~x.isin(chaves_pai)).sum())
        pct = orf / max(len(x), 1)
        st = OK if pct <= tol else (ATENCAO if pct <= tol * 10 else CRITICO)
        out.append(_linha("Integridade", filho, f"{cf} existe em {pai.split('/')[-1].lstrip('_').replace('_', ' ')}", st,
                          f"{orf:,} órfãos ({pct:.2%})".replace(",", "."),
                          f"tolerância {tol:.1%}", impacto="" if st == OK else impacto))
    return out


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce") if c in df else pd.Series(dtype=float)


def coerencia(brutos: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    emp = brutos.get("especiais/empenhos-especiais", pd.DataFrame())
    dh = brutos.get("especiais/documentos-habeis-especiais", pd.DataFrame())
    pa = brutos.get("especiais/planos-acao-especiais", pd.DataFrame())
    if not emp.empty and not dh.empty and {"id_empenho", "valor_dh"} <= set(dh.columns) and "valor_empenho" in emp:
        pago = dh.groupby(dh["id_empenho"].astype(str))["valor_dh"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
        e = emp.assign(_id=emp["id_empenho"].astype(str), _v=_num(emp, "valor_empenho"))
        e["_p"] = e["_id"].map(pago).fillna(0)
        acima = e[e["_p"] > e["_v"] * 1.001 + 1]
        out.append(_linha("Coerência", "especiais/documentos-habeis-especiais", "Pago ≤ empenhado",
                          OK if acima.empty else ATENCAO, f"{len(acima)} empenhos pagos acima do valor",
                          detalhe="" if acima.empty else f"excesso {acima['_p'].sub(acima['_v']).sum():,.0f}",
                          impacto="" if acima.empty else "dinheiro a receber pode ficar negativo (o painel corta em zero)"))
    if not emp.empty and not pa.empty and "id_plano_acao" in emp and "id_plano_acao" in pa:
        val = _num(pa, "valor_custeio_plano_acao").fillna(0) + _num(pa, "valor_investimento_plano_acao").fillna(0)
        vp = pd.Series(val.values, index=pa["id_plano_acao"].astype(str))
        ep = emp.groupby(emp["id_plano_acao"].astype(str))["valor_empenho"].apply(lambda s: pd.to_numeric(s, errors="coerce").sum())
        j = pd.concat([vp.rename("plano"), ep.rename("emp")], axis=1).dropna()
        acima = j[j["emp"] > j["plano"] * 1.01 + 1]
        out.append(_linha("Coerência", "especiais/empenhos-especiais", "Empenhado ≤ valor do plano",
                          OK if len(acima) <= len(j) * 0.01 else ATENCAO, f"{len(acima)} planos com empenho acima do valor"))
    conv = brutos.get("discricionarias_csv/siconv_convenio", pd.DataFrame())
    if not conv.empty and {"vl_desembolsado_conv", "vl_repasse_conv"} <= set(conv.columns):
        from .normaliza import numero
        d, r = numero(conv["vl_desembolsado_conv"]).fillna(0), numero(conv["vl_repasse_conv"]).fillna(0)
        acima = int((d > r * 1.001 + 1).sum())
        out.append(_linha("Coerência", "discricionarias_csv/siconv_convenio", "Desembolsado ≤ repasse",
                          OK if acima <= len(conv) * 0.005 else ATENCAO, f"{acima} convênios",
                          impacto="" if not acima else "repasse a liberar desses convênios fica zerado"))
        if "vl_saldo_conta" in conv:
            s = numero(conv["vl_saldo_conta"]).fillna(0)
            neg = int((s < 0).sum())
            if neg:
                out.append(_linha("Coerência", "discricionarias_csv/siconv_convenio", "Saldo de conta negativo", ATENCAO,
                                  f"{neg} convênios"))
    return out


def frescor(manifestos: list[dict], brutos: dict[str, pd.DataFrame], hoje: date, limite: int = 60) -> list[dict]:
    out = []
    for m in manifestos or []:
        d = m.get("data_atualizacao")
        if d:
            idade = (pd.Timestamp(hoje) - pd.to_datetime(d, errors="coerce").normalize()).days
            out.append(_linha("Frescor", m.get("modulo"), "Atualização informada pelo governo",
                              OK if idade <= 2 else (ATENCAO if idade <= 7 else CRITICO), str(d)[:10], f"até 2 dias",
                              impacto="" if idade <= 2 else "dados do módulo podem estar atrasados"))
    nomes = {"1": "BB", "104": "CAIXA", "4": "BNB"}
    for tab in ("especiais/gestao-financeira-lancamentos-especiais", "fundoafundo/gestao-financeira-lancamentos"):
        df = brutos.get(tab, pd.DataFrame())
        if df.empty or "codigo_banco_gestao_financeira" not in df or "data_lancamento_gestao_financeira" not in df:
            continue
        x = df.assign(_b=df["codigo_banco_gestao_financeira"].astype(str).str.lstrip("0"),
                      _d=pd.to_datetime(df["data_lancamento_gestao_financeira"], errors="coerce"))
        for b, g in x.groupby("_b"):
            ult = g["_d"].max()
            idade = (pd.Timestamp(hoje) - ult).days if pd.notna(ult) else None
            st = OK if idade is not None and idade <= limite else CRITICO
            out.append(_linha("Frescor", tab, f"Último extrato publicado · {nomes.get(b, 'banco ' + b)}", st,
                              ult.strftime("%Y-%m-%d") if pd.notna(ult) else "—", f"até {limite} dias",
                              f"{idade} dias sem lançamentos" if st != OK else "",
                              "" if st == OK else "saldo e movimentação desse banco estão defasados na fonte (regra QLD-01)"))
    sal = brutos.get("especiais/saldo-conta-gestao-financeira-especiais", pd.DataFrame())
    if not sal.empty and "data_saldo_conta" in sal:
        d = pd.to_datetime(sal["data_saldo_conta"], errors="coerce")
        recente = float((d >= pd.Timestamp(hoje) - pd.Timedelta(days=limite)).mean())
        out.append(_linha("Frescor", "especiais/saldo-conta-gestao-financeira-especiais", "Saldos com data recente",
                          OK, f"{recente:.0%} das contas", f"últimos {limite} dias",
                          detalhe="informativo: o saldo publicado tem a data do último extrato com movimento; conta "
                                  "parada mantém a data antiga. A defasagem por banco é medida no último extrato."))
    return out


def reconciliacao(brutos: dict[str, pd.DataFrame], saida: dict[str, pd.DataFrame]) -> list[dict]:
    """O que entrou no bruto aparece no painel com a mesma contagem, valor e saldo."""
    out = []
    # contratados + os que ficaram fora dos valores (previsto, impedido, cancelado): nada pode sumir
    instr = pd.concat([x for x in (saida.get("fato_instrumento"), saida.get("fato_instrumento_fora"))
                       if x is not None and not x.empty], ignore_index=True) \
        if saida.get("fato_instrumento") is not None else pd.DataFrame()
    contas = saida.get("fato_conta", pd.DataFrame())
    pares = [("especiais/planos-acao-especiais", "Especiais", "id_plano_acao",
              lambda df: _num(df, "valor_custeio_plano_acao").fillna(0) + _num(df, "valor_investimento_plano_acao").fillna(0)),
             ("fundoafundo/planos-acao", "Fundo a Fundo", "id_plano_acao", None),
             ("discricionarias_csv/siconv_convenio", "Discricionárias", "nr_convenio", None)]
    for tab, mod, chave, valor in pares:
        b = brutos.get(tab, pd.DataFrame())
        if b.empty or instr.empty:
            out.append(_linha("Reconciliação", tab, "Bruto × painel", NV))
            continue
        i = instr[instr["modulo"] == mod]
        nb, ni = b[chave].nunique() if chave in b else len(b), i["id_instrumento"].nunique()
        st = OK if nb == ni else (ATENCAO if abs(nb - ni) <= nb * 0.001 else CRITICO)
        out.append(_linha("Reconciliação", tab, f"Instrumentos: bruto × painel ({mod})", st, ni, nb,
                          impacto="" if st == OK else "instrumentos perdidos ou duplicados na transformação"))
        if valor is not None:
            vb, vi = float(valor(b).sum()), float(i["valor"].sum())
            st = OK if abs(vb - vi) <= max(vb, 1) * 0.0001 else CRITICO
            out.append(_linha("Reconciliação", tab, f"Valor: bruto × painel ({mod})", st, f"{vi:,.0f}", f"{vb:,.0f}"))
    sal = brutos.get("especiais/saldo-conta-gestao-financeira-especiais", pd.DataFrame())
    if not sal.empty and not contas.empty and "saldo_final_gestao_financeira" in sal:
        from .normaliza import chave_conta
        sal = sal.assign(id_agencia_conta=chave_conta(sal["id_agencia_conta"]))
        tot = float(_num(sal, "saldo_final_gestao_financeira").sum())
        publico = contas["fonte_saldo"].eq("Transferegov") if "fonte_saldo" in contas else pd.Series(True, index=contas.index)
        no_painel = float(contas.loc[(contas["modulo"] == "Especiais") & publico, "saldo"].sum())
        contas_sal = set(sal["id_agencia_conta"].dropna().astype(str)) if "id_agencia_conta" in sal else set()
        contas_painel = set(contas.loc[contas["modulo"] == "Especiais", "id_agencia_conta"].dropna().astype(str))
        sem = contas_sal - contas_painel
        saldo_sem = float(_num(sal[sal["id_agencia_conta"].astype(str).isin(sem)], "saldo_final_gestao_financeira").sum())
        pct = saldo_sem / max(tot, 1)
        excesso = no_painel - tot
        out.append(_linha("Reconciliação", "especiais/saldo-conta-gestao-financeira-especiais",
                          "Saldo do painel ≤ saldo publicado (sem dupla contagem)",
                          OK if excesso <= max(tot, 1) * 0.0001 else CRITICO, f"{no_painel:,.0f}", f"{tot:,.0f}",
                          impacto="" if excesso <= max(tot, 1) * 0.0001 else "custódia inflada: conta somada mais de uma vez"))
        out.append(_linha("Reconciliação", "especiais/saldo-conta-gestao-financeira-especiais",
                          "Saldo publicado ligado a uma conta do painel", OK if pct < 0.01 else (ATENCAO if pct < 0.05 else CRITICO),
                          f"{1 - pct:.1%} do saldo", f"{len(sem):,} contas sem plano/executor".replace(",", "."),
                          detalhe=f"saldo bruto {tot:,.0f} · no painel {no_painel:,.0f}",
                          impacto="" if pct < 0.01 else "parte do saldo publicado não entra na custódia por banco"))
    return out


# ------------------------------------------------------------------ orquestração e relatório
def auditar(bruto: Path, dia: date, manifestos: list[dict], saida: dict[str, pd.DataFrame],
            registro_anterior: pd.DataFrame | None = None, limite_dias: int = 60) -> pd.DataFrame:
    tabelas = sorted({f"{p.parent.name}/{p.name}" for p in bruto.glob("*/*") if p.is_dir() and not p.name.startswith("_")})
    brutos = {t: ultimo_bruto(bruto, *t.split("/")) for t in tabelas}
    linhas = []
    for nome, f in (("completude", lambda: completude(manifestos, registro_anterior if registro_anterior is not None else pd.DataFrame())),
                    ("estrutura", lambda: estrutura(manifestos, brutos)),
                    ("identificadores", lambda: identificadores(brutos)),
                    ("dominios", lambda: dominios(brutos, dia)),
                    ("integridade", lambda: integridade(brutos)),
                    ("coerencia", lambda: coerencia(brutos)),
                    ("frescor", lambda: frescor(manifestos, brutos, dia, limite_dias)),
                    ("reconciliacao", lambda: reconciliacao(brutos, saida))):
        try:
            linhas += f()
        except Exception as e:  # uma checagem com defeito não derruba a carga
            log.exception("Auditoria %s falhou", nome)
            linhas.append(_linha(nome.capitalize(), "—", "Execução da checagem", NV, detalhe=str(e)[:200]))
    df = pd.DataFrame(linhas)
    df.insert(0, "dia", dia.isoformat())
    return df.sort_values("status", key=lambda s: s.map(ORDEM)).reset_index(drop=True)


def interpretar(aud: pd.DataFrame) -> list[str]:
    """Leitura em linguagem de negócio do que a auditoria encontrou."""
    if aud.empty:
        return ["Auditoria sem resultados."]
    cont = aud["status"].value_counts()
    frases = [f"{int(cont.get(OK, 0))} checagens ok, {int(cont.get(ATENCAO, 0))} de atenção, "
              f"{int(cont.get(CRITICO, 0))} críticas e {int(cont.get(NV, 0))} não verificáveis."]
    crit = aud[aud["status"] == CRITICO]
    for r in crit.head(8).itertuples():
        frases.append(f"Crítico · {r.familia} · {r.tabela}: {r.checagem} ({r.medido}). {r.impacto or r.detalhe}")
    if crit.empty:
        frases.append("Nenhum problema crítico: os números do painel refletem a fonte do dia.")
    return frases


def gravar(aud: pd.DataFrame, dados: Path) -> Path:
    pasta = dados / "auditoria"
    pasta.mkdir(parents=True, exist_ok=True)
    dia = aud["dia"].iloc[0] if not aud.empty else date.today().isoformat()
    hist = storage.ler(pasta / "historico_auditoria")
    if not hist.empty:
        hist = hist[hist["dia"] != dia]
    storage.gravar(pd.concat([hist, aud], ignore_index=True), pasta / "historico_auditoria")
    cor = {OK: "#027A48", ATENCAO: "#B54708", CRITICO: "#B42318", NV: "#667085"}
    cont = aud["status"].value_counts()
    linhas = "".join(
        f"<tr><td><span style='color:{cor[r.status]};font-weight:700'>{html.escape(r.status)}</span></td>"
        f"<td>{html.escape(r.familia)}</td><td>{html.escape(str(r.tabela))}</td><td>{html.escape(r.checagem)}</td>"
        f"<td>{html.escape(str(r.medido or ''))}</td><td>{html.escape(str(r.referencia or ''))}</td>"
        f"<td>{html.escape(r.detalhe or '')}</td><td>{html.escape(r.impacto or '')}</td></tr>" for r in aud.itertuples())
    resumo = "".join(f"<li>{html.escape(f)}</li>" for f in interpretar(aud))
    cartoes = "".join(f"<div class=c style='border-color:{cor[s]}'><b>{int(cont.get(s, 0))}</b><span>{s}</span></div>"
                      for s in (CRITICO, ATENCAO, OK, NV))
    doc = f"""<!doctype html><html lang=pt-BR><meta charset=utf-8><title>Auditoria da carga {dia}</title>
<style>body{{font-family:Segoe UI,Roboto,sans-serif;margin:24px;color:#101828}}h1{{color:#005CA9;margin:0}}
.cs{{display:flex;gap:12px;margin:16px 0}}.c{{border-left:6px solid;padding:8px 14px;background:#F8FAFD;border-radius:8px}}
.c b{{font-size:1.6rem;display:block}}table{{border-collapse:collapse;width:100%;font-size:.86rem}}
td,th{{border-bottom:1px solid #E3E8EF;padding:6px 8px;text-align:left;vertical-align:top}}th{{background:#F4F7FB}}</style>
<h1>Auditoria da carga · {dia}</h1><p>Conexão Governo · CAIXA · fonte Transferegov.br</p><div class=cs>{cartoes}</div>
<h3>Leitura</h3><ul>{resumo}</ul><h3>Checagens</h3><table><tr><th>Status</th><th>Família</th><th>Tabela</th>
<th>Checagem</th><th>Medido</th><th>Referência</th><th>Detalhe</th><th>Impacto no painel</th></tr>{linhas}</table></html>"""
    arq = pasta / f"relatorio_{dia}.html"
    arq.write_text(doc, "utf-8")
    return arq


def main() -> int:
    """Audita a última carga bruta contra as tabelas publicadas, sem baixar nada."""
    from . import config, consultas
    cfg = config.carregar()
    cam = config.caminhos(cfg)
    exe = consultas.execucao_atual(cam)
    saida = consultas.carregar(exe, cam) if exe else {}
    man = sorted(cam.estado.glob("manifesto_*.json"))
    manifestos = json.loads(man[-1].read_text("utf-8")) if man else []
    dia = date.fromisoformat(man[-1].stem.split("_")[-1]) if man else date.today()
    reg = storage.ler(cam.dados / "repositorio" / "registro_cargas")
    ant = reg[reg["dia"] < dia.isoformat()] if not reg.empty else reg
    ant = ant[ant["dia"] == ant["dia"].max()] if not ant.empty else ant
    aud = auditar(cam.bruto, dia, manifestos, saida, ant)
    arq = gravar(aud, cam.dados)
    for f in interpretar(aud):
        print("-", f)
    print(f"Relatório: {arq}")
    return 1 if (aud["status"] == CRITICO).any() else 0


if __name__ == "__main__":
    raise SystemExit(main())
