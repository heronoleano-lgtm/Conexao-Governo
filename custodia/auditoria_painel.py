"""Auditoria do que o painel MOSTRA (camada de entrega), sobre os marts prontos.

A auditoria da carga (auditoria.py) olha a carga bruta. Esta olha os números que chegam às telas:
  1. Percentuais: toda coluna marcada como % no dicionário semântico tem de estar entre 0% e 100%.
  2. Valores negativos e extremos: estornos/anulações e números mal lidos distorcem totais e participações.
  3. Unicidade: instrumento, ente e conta sem linhas repetidas (repetição = dupla contagem).
  4. Partes e todo: valor CAIXA ≤ valor total; soma das partes = total.
  5. Coerência entre telas: o mesmo total (valor, CAIXA, saldo) bate em todas as tabelas que o carregam.
  6. Território: municípios ≤ 5.570, UFs ≤ 27, códigos IBGE válidos.
  7. Datas e anos plausíveis.

Saída: data/auditoria/painel_AAAA-MM-DD.html (para ler) e .csv (checagens) + _exemplos.csv (linhas que falharam).
Uso avulso: python -m custodia.auditoria_painel   (ou auditar_painel.bat)
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .semantica import ROTULOS

from .auditoria import ATENCAO as ALERTA, CRITICO, OK  # mesmos status da auditoria da carga
ID_COLS = ["modulo", "id_instrumento", "codigo", "cnpj_ente", "nome_ente", "uf", "municipio", "orgao", "programa",
           "parlamentar", "agente", "grupo_banco", "banco_principal", "recebedor", "cnpj", "favorecido", "estagio"]
TOL = 1e-6


def _pcts() -> set[str]:
    return {c for c, v in ROTULOS.items() if len(v) > 1 and v[1] == "pct"}


def _linha(familia, tabela, checagem, status, valor=None, referencia=None, detalhe="", exemplos=None):
    return {"familia": familia, "tabela": tabela, "checagem": checagem, "status": status,
            "valor": valor, "referencia": referencia, "detalhe": detalhe,
            "_exemplos": exemplos if exemplos is not None else pd.DataFrame()}


def _ex(df: pd.DataFrame, cols_extra: list[str], n: int = 15, ordem: str | None = None, asc: bool = False) -> pd.DataFrame:
    cols = [c for c in ID_COLS if c in df.columns] + [c for c in cols_extra if c in df.columns]
    cols = list(dict.fromkeys(cols))
    x = df.sort_values(ordem, ascending=asc) if ordem and ordem in df.columns else df
    return x[cols].head(n)


# ------------------------------------------------------------------ 1. percentuais
def percentuais(d: dict) -> list[dict]:
    out = []
    pcts = _pcts()
    for nome, df in d.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for c in [c for c in df.columns if c in pcts]:
            v = pd.to_numeric(df[c], errors="coerce")
            ruins = (v < -TOL) | (v > 1 + TOL)
            n = int(ruins.sum())
            if n:
                ex = _ex(df[ruins].assign(**{c: v[ruins]}), [c, "valor", "valor_caixa", "saldo", "valor_total"],
                         ordem=c)
                out.append(_linha("Percentuais", nome, f"{c} entre 0% e 100%", CRITICO, n, int(v.notna().sum()),
                                  f"{n} linhas fora de 0–100%; máx {v.max():.4g}, mín {v.min():.4g}", ex))
            elif v.notna().any():
                out.append(_linha("Percentuais", nome, f"{c} entre 0% e 100%", OK, 0, int(v.notna().sum())))
    return out


# ------------------------------------------------------------------ 2. negativos e extremos
def negativos_extremos(d: dict) -> list[dict]:
    out = []
    alvos = [("fato_instrumento", "valor"), ("fato_conta", "saldo"), ("mart_ente_resumo", "valor"),
             ("mart_ente_resumo", "valor_caixa"), ("mart_ente_resumo", "saldo_caixa"),
             ("mart_ente_resumo", "saldo_concorrente"), ("fato_pagamento", "valor"), ("fato_fluxo", "valor"),
             ("fato_repasse_outros", "valor"), ("mart_orgaos", "valor"), ("mart_orgaos", "saldo")]
    for nome, c in alvos:
        df = d.get(nome)
        if not isinstance(df, pd.DataFrame) or df.empty or c not in df:
            continue
        v = pd.to_numeric(df[c], errors="coerce")
        neg = v < -0.005
        if nome == "fato_repasse_outros" and "detalhe" in df and neg.any():
            # ajustes do FUNDEB (Tesouro) são estornos legítimos: entram líquidos nos totais
            ajuste = neg & df["detalhe"].fillna("").astype(str).str.upper().str.contains("AJUSTE")
            if ajuste.any():
                out.append(_linha("Negativos", nome, "ajustes negativos legítimos (FUNDEB) somados líquidos", OK,
                                  int(ajuste.sum()), int(v.notna().sum()),
                                  f"{int(ajuste.sum())} ajustes somando {v[ajuste].sum():,.2f}"))
            neg = neg & ~ajuste
        if neg.any():
            # fluxo, pagamentos e repasses do Portal têm estornos/devoluções reais (valor negativo publicado na fonte):
            # entram líquidos e são sinalizados; em saldos e instrumentos, negativo é erro de leitura
            st = ALERTA if nome in ("fato_fluxo", "fato_pagamento", "fato_repasse_outros") else CRITICO
            expl = ("estornos/devoluções publicados pela fonte, somados líquidos; conferir se o volume é plausível"
                    if st == ALERTA else "distorcem totais e participações")
            out.append(_linha("Negativos", nome, f"{c} sem valores negativos", st, int(neg.sum()), int(v.notna().sum()),
                              f"{int(neg.sum())} negativos somando {v[neg].sum():,.2f}; {expl}",
                              _ex(df[neg].assign(**{c: v[neg]}), [c], ordem=c, asc=True)))
        else:
            out.append(_linha("Negativos", nome, f"{c} sem valores negativos", OK, 0, int(v.notna().sum())))
        pos = v[v > 0]
        if len(pos) > 50:
            p99 = float(pos.quantile(0.99))
            lim = max(p99 * 200, 5e9 if nome != "fato_conta" else 2e9)
            ext = v > lim
            if ext.any():
                out.append(_linha("Extremos", nome, f"{c} sem valores absurdos", ALERTA, int(ext.sum()), lim,
                                  f"{int(ext.sum())} acima de R$ {lim:,.0f} (200× o percentil 99): conferir leitura do número",
                                  _ex(df[ext].assign(**{c: v[ext]}), [c], ordem=c)))
    return out


# ------------------------------------------------------------------ 3. unicidade
def unicidade(d: dict) -> list[dict]:
    out = []
    for nome, chave in (("fato_instrumento", ["modulo", "id_instrumento"]), ("mart_ente_resumo", ["cnpj_ente"]),
                        ("dim_ente", ["cnpj_ente"]), ("mart_potencial", ["cnpj_ente"]),
                        ("mart_outras_municipio", ["cod_ibge"])):
        df = d.get(nome)
        if not isinstance(df, pd.DataFrame) or df.empty or not set(chave) <= set(df.columns):
            continue
        dup = df.duplicated(chave, keep=False)
        n = int(df.duplicated(chave).sum())
        out.append(_linha("Unicidade", nome, f"uma linha por {' + '.join(chave)}", CRITICO if n else OK, n, len(df),
                          f"{n} linhas repetidas: o que for somado por esta tabela conta em dobro" if n else "",
                          _ex(df[dup], chave + ["valor"], ordem=chave[-1]) if n else None))
    c = d.get("fato_conta")
    if isinstance(c, pd.DataFrame) and not c.empty and {"modulo", "id_agencia_conta", "saldo"} <= set(c.columns):
        s = pd.to_numeric(c["saldo"], errors="coerce").fillna(0)
        x = c.assign(_s=s)
        rep = x[x.duplicated(["modulo", "id_agencia_conta"], keep=False) & (x["_s"] != 0)]
        k = rep.groupby(["modulo", "id_agencia_conta"])["_s"].agg(["count", "nunique", "sum"])
        k = k[k["nunique"] == 1]
        n = int(len(k))
        tot = float((k["sum"] - k["sum"] / k["count"]).sum()) if n else 0.0
        out.append(_linha("Unicidade", "fato_conta", "saldo da mesma conta contado uma vez",
                          ALERTA if n else OK, n, int(c["id_agencia_conta"].nunique()),
                          f"{n} contas repetem o mesmo saldo em várias linhas (R$ {tot:,.0f} se somadas sem cuidado); "
                          "as telas devem deduplicar por conta" if n else ""))
    return out


# ------------------------------------------------------------------ 4. partes e todo
def partes_todo(d: dict) -> list[dict]:
    out = []
    for nome, df in d.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for parte, todo in (("valor_caixa", "valor"), ("valor_caixa", "valor_total"), ("saldo_caixa", "saldo"),
                            ("saude_caixa_12m", "saude_12m"), ("valor_em_disputa", "valor")):
            if parte in df and todo in df:
                p, t = pd.to_numeric(df[parte], errors="coerce"), pd.to_numeric(df[todo], errors="coerce")
                ruim = p > t * (1 + 1e-4) + 0.01
                n = int(ruim.sum())
                out.append(_linha("Partes e todo", nome, f"{parte} ≤ {todo}", CRITICO if n else OK, n, len(df),
                                  f"{n} linhas com a parte maior que o todo" if n else "",
                                  _ex(df[ruim], [parte, todo], ordem=parte) if n else None))
    return out


# ------------------------------------------------------------------ 5. coerência entre telas
def coerencia_telas(d: dict) -> list[dict]:
    out = []
    fi = d.get("fato_instrumento")
    if not isinstance(fi, pd.DataFrame) or fi.empty:
        return out
    v = pd.to_numeric(fi["valor"], errors="coerce").fillna(0)
    com = fi["grupo_banco"] != "(sem banco)"
    ref_tot, ref_cx = float(v[com].sum()), float(v[fi["grupo_banco"] == "CAIXA"].sum())

    def cmp(familia, tabela, checagem, valor, referencia, tol=0.005):
        dif = abs(valor - referencia) / max(abs(referencia), 1)
        st = OK if dif <= tol else (ALERTA if dif <= 0.03 else CRITICO)
        out.append(_linha(familia, tabela, checagem, st, round(valor, 2), round(referencia, 2),
                          f"diferença de {dif:.2%}" if st != OK else ""))

    er = d.get("mart_ente_resumo")
    if isinstance(er, pd.DataFrame) and not er.empty:
        if "valor_caixa" in er:
            cmp("Coerência entre telas", "mart_ente_resumo", "valor CAIXA = soma dos instrumentos na CAIXA",
                float(pd.to_numeric(er["valor_caixa"], errors="coerce").sum()),
                float(v[(fi["grupo_banco"] == "CAIXA") & fi["cnpj_ente"].fillna("").ne("")].sum()))
        if "valor_concorrente" in er and "valor_caixa" in er:
            cmp("Coerência entre telas", "mart_ente_resumo", "valor com banco = instrumentos com banco",
                float(pd.to_numeric(er["valor_caixa"], errors="coerce").sum() +
                      pd.to_numeric(er["valor_concorrente"], errors="coerce").sum()),
                float(v[com & fi["cnpj_ente"].fillna("").ne("")].sum()))
    mp = d.get("mart_participacao")
    if isinstance(mp, pd.DataFrame) and not mp.empty and {"grupo_banco", "valor"} <= set(mp.columns):
        x = mp[mp["grupo_banco"] != "(sem banco)"]
        cmp("Coerência entre telas", "mart_participacao", "total com banco = instrumentos",
            float(pd.to_numeric(x["valor"], errors="coerce").sum()), ref_tot)
    try:
        from . import consultas
        t = consultas.territorio(d, "UF")
        cmp("Coerência entre telas", "mapa (por UF)", "valor do mapa = instrumentos com banco e UF",
            float(t["valor"].sum()), float(v[com & fi["uf"].notna() & fi["cnpj_ente"].fillna("").ne("")].sum()), tol=0.02)
        part = t["valor_caixa"].sum() / t["valor"].sum() if t["valor"].sum() else np.nan
        cmp("Coerência entre telas", "mapa (por UF)", "participação CAIXA do mapa = do total",
            float(part * 100), float(ref_cx / ref_tot * 100) if ref_tot else 0.0, tol=0.03)
    except Exception as e:  # pragma: no cover
        out.append(_linha("Coerência entre telas", "mapa (por UF)", "cálculo do mapa", CRITICO, detalhe=str(e)[:200]))
    return out


# ------------------------------------------------------------------ 6. território
def territorio(d: dict) -> list[dict]:
    out = []
    er = d.get("mart_ente_resumo")
    if isinstance(er, pd.DataFrame) and not er.empty and "cod_ibge" in er:
        cod = er["cod_ibge"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
        m = cod[cod.str.len() == 7].nunique()
        out.append(_linha("Território", "mart_ente_resumo", "municípios distintos ≤ 5.570", CRITICO if m > 5571 else OK,
                          int(m), 5570))
        inval = cod[(cod != "") & ~cod.str.fullmatch(r"\d{2}|\d{7}")]
        out.append(_linha("Território", "mart_ente_resumo", "código IBGE com 2 ou 7 dígitos",
                          ALERTA if len(inval) else OK, int(len(inval)), len(cod)))
        u = er["uf"].dropna().nunique() if "uf" in er else 0
        out.append(_linha("Território", "mart_ente_resumo", "UFs ≤ 27", CRITICO if u > 27 else OK, int(u), 27))
        sem = int(cod.eq("").sum())
        out.append(_linha("Território", "mart_ente_resumo", "entes com município ou UF identificados",
                          ALERTA if sem > 0.05 * len(er) else OK, sem, len(er),
                          f"{sem} entes sem código IBGE ficam fora do mapa" if sem else ""))
    return out


# ------------------------------------------------------------------ 7. datas
def datas(d: dict, hoje: date) -> list[dict]:
    out = []
    fi = d.get("fato_instrumento")
    if isinstance(fi, pd.DataFrame) and not fi.empty and "ano" in fi:
        a = pd.to_numeric(fi["ano"], errors="coerce")
        ruim = (a < 2000) | (a > hoje.year + 1)
        out.append(_linha("Datas", "fato_instrumento", f"ano entre 2000 e {hoje.year + 1}", ALERTA if ruim.any() else OK,
                          int(ruim.sum()), int(a.notna().sum()), "",
                          _ex(fi[ruim], ["ano", "valor"]) if ruim.any() else None))
    c = d.get("fato_conta")
    if isinstance(c, pd.DataFrame) and not c.empty and "data_saldo" in c:
        dt = pd.to_datetime(c["data_saldo"], errors="coerce", format="mixed")
        fut = dt > pd.Timestamp(hoje) + pd.Timedelta(days=1)
        out.append(_linha("Datas", "fato_conta", "data do saldo não está no futuro", ALERTA if fut.any() else OK,
                          int(fut.sum()), int(dt.notna().sum())))
    return out



# ------------------------------------------------------------------ 8. CRM (Portal da Transparência)
def crm(d: dict) -> list[dict]:
    """Campos esperados, duplicidades, contas reversas, coerência das emendas, carteira (parte ≤ todo),
    reconciliação Portal × Transferegov/FNS e contradições de conformidade."""
    out = []
    F = "CRM"
    campos = d.get("crm_campos")
    if isinstance(campos, pd.DataFrame) and not campos.empty:
        falta = campos[campos["obrigatorio"] & ~campos["encontrado"] & (campos["linhas"] > 0)]
        out.append(_linha(F, "crm_campos", "campos obrigatórios recebidos da API", CRITICO if len(falta) else OK,
                          int(len(falta)), int(campos["obrigatorio"].sum()),
                          ("faltam: " + ", ".join(falta["conjunto"] + "." + falta["campo"])) if len(falta) else "",
                          falta if len(falta) else None))
    q = d.get("crm_qualidade")
    if isinstance(q, pd.DataFrame) and not q.empty:
        for r in q.itertuples():
            if r.duplicadas_identicas:
                out.append(_linha(F, r.conjunto, "linhas repetidas removidas", ALERTA, int(r.duplicadas_identicas),
                                  int(r.linhas), "a mesma linha veio mais de uma vez da API; contada uma vez só"))
            out.append(_linha(F, r.conjunto, "chave sem versões conflitantes", ALERTA if r.chaves_conflitantes else OK,
                              int(r.chaves_conflitantes), int(r.linhas),
                              "mesma chave com valores diferentes; ficou a versão mais recente" if r.chaves_conflitantes else ""))
            ag = getattr(r, "linhas_agregadas", 0)
            if ag == ag and ag:
                out.append(_linha(F, r.conjunto, "lançamentos do mesmo órgão no mês somados (não descartados)", OK, int(ag),
                                  int(r.linhas), f"{int(ag)} linhas com a mesma chave e valores diferentes na mesma "
                                                 "consulta: são lançamentos distintos e foram somados"))
            bx = getattr(r, "linhas_de_bancos_excluidas", 0)
            if bx == bx and bx:
                out.append(_linha(F, r.conjunto, "bancos fora da carteira de entes", OK, int(bx), None,
                                  f"{int(bx)} linhas de bancos como favorecidos (R$ {r.valor_de_bancos_excluido:,.2f}) "
                                  "não entram como recebimento de ente"))
            lg = getattr(r, "linhas_unidades_legadas", 0)
            if lg == lg and lg:
                out.append(_linha(F, r.conjunto, "consultas antigas (sem tipo de favorecido) ignoradas", OK, int(lg), None,
                                  f"{int(lg)} linhas da fila anterior sobrepunham as novas consultas; não entram nas somas"))
    integ = d.get("crm_integridade")
    if isinstance(integ, pd.DataFrame) and not integ.empty:
        perd = integ[integ["sem_arquivo"] > 0]
        out.append(_linha(F, "crm_integridade", "toda consulta baixada tem o arquivo no cache", CRITICO if len(perd) else OK,
                          int(integ["sem_arquivo"].sum()), int(integ["baixadas"].sum()),
                          ("arquivos de consultas sumiram do cache (" + ", ".join(f"{r.conjunto}: {r.sem_arquivo}"
                                                                                  for r in perd.itertuples())
                           + "); os números desses conjuntos estão incompletos até a próxima carga, que baixa de novo")
                          if len(perd) else "", perd if len(perd) else None))
    cob = d.get("crm_cobertura")
    if isinstance(cob, pd.DataFrame) and not cob.empty:
        ok = cob["ok"].astype(bool)
        falhas = cob[~ok]
        out.append(_linha(F, "crm_cobertura", "consultas de recursos baixadas por inteiro", ALERTA if len(falhas) else OK,
                          int(len(falhas)), int(len(cob)),
                          (f"{len(falhas)} consultas (UF × mês × tipo) falharam ou foram cortadas; esses meses ficam fora "
                           "do 'banco conhecido' e entram de novo na próxima carga") if len(falhas) else
                          f"{int(cob['mes'].nunique())} meses × {int(cob['uf'].nunique())} UFs completos",
                          falhas.head(30) if len(falhas) else None))

    rec, cart = d.get("crm_recebido"), d.get("crm_carteira")
    if isinstance(rec, pd.DataFrame) and not rec.empty:
        v = pd.to_numeric(rec["valor"], errors="coerce")
        tot = float(v.sum())
        por_mes = float(v.groupby(rec["mes"]).sum().sum())
        por_ente = float(v.groupby(rec["cnpj"]).sum().sum())
        por_uf = float(v.groupby(rec["uf"].fillna("?")).sum().sum())
        ok = all(abs(x - tot) <= 0.01 for x in (por_mes, por_ente, por_uf))
        out.append(_linha(F, "crm_recebido", "Σ por mês = Σ por ente = Σ por UF = total", OK if ok else CRITICO,
                          round(tot, 2), round(por_mes, 2), "" if ok else f"ente {por_ente:,.2f} · UF {por_uf:,.2f}"))
        nan = int(v.isna().sum())
        out.append(_linha(F, "crm_recebido", "valores legíveis (sem vazio virando zero)", ALERTA if nan else OK, nan,
                          len(v), f"{nan} valores ilegíveis ficaram vazios" if nan else ""))
        pf = int(rec["cnpj"].astype(str).str.len().ne(14).sum())
        out.append(_linha(F, "crm_recebido", "só pessoas jurídicas (nenhum CPF)", CRITICO if pf else OK, pf, len(rec)))
        if isinstance(cart, pd.DataFrame) and not cart.empty:
            fim = rec["mes"].max()
            ini = (pd.Period(fim, "M") - 11).strftime("%Y-%m")
            ref = float(v[(rec["mes"] >= ini) & (rec["mes"] <= fim)].sum())
            soma = float(cart["recebido_12m"].sum())
            out.append(_linha(F, "crm_carteira", "Σ carteira 12m = Σ recebidos dos 12 meses (conta reversa)",
                              OK if abs(soma - ref) <= 0.01 else CRITICO, round(soma, 2), round(ref, 2)))
    if isinstance(cart, pd.DataFrame) and not cart.empty:
        partes = cart["caixa_conhecido_12m"] + cart["concorrente_conhecido_12m"] + cart["sem_banco_12m"]
        exc = cart["conhecido_excede"].fillna(False).astype(bool)
        bate = (abs(partes - cart["recebido_12m"]) <= 0.01) | exc | (cart["recebido_12m"] <= 0)
        out.append(_linha(F, "crm_carteira", "recebido = CAIXA + concorrente + sem banco", OK if bate.all() else CRITICO,
                          int((~bate).sum()), len(cart)))
        out.append(_linha(F, "crm_carteira", "banco conhecido ≤ recebido (sem dupla contagem)", ALERTA if exc.any() else OK,
                          int(exc.sum()), len(cart),
                          f"{int(exc.sum())} entes com mais dinheiro de banco conhecido (FNS/Especiais) do que o Portal "
                          "registra como recebido: datas de competência diferentes ou dado faltando numa fonte" if exc.any() else "",
                          _ex(cart[exc].rename(columns={"cnpj": "cnpj_ente", "nome": "nome_ente"}),
                              ["recebido_12m", "caixa_conhecido_12m", "concorrente_conhecido_12m"], ordem="recebido_12m")
                          if exc.any() else None))
        neg = int((cart["recebido_12m"] < -0.005).sum())
        out.append(_linha(F, "crm_carteira", "recebido_12m sem negativos", ALERTA if neg else OK, neg, len(cart),
                          f"{neg} favorecidos com saldo líquido negativo em 12 meses (devoluções maiores que os repasses "
                          "no período carregado); não entram como potencial" if neg else "",
                          _ex(cart[cart["recebido_12m"] < -0.005].rename(columns={"cnpj": "cnpj_ente", "nome": "nome_ente"}),
                              ["recebido_12m"], ordem="recebido_12m", asc=True) if neg else None))
        neg = int((cart["sem_banco_12m"] < -0.005).sum())
        out.append(_linha(F, "crm_carteira", "sem_banco_12m sem negativos", CRITICO if neg else OK, neg, len(cart)))
        dup = int(cart["cnpj"].duplicated().sum())
        out.append(_linha(F, "crm_carteira", "uma linha por CNPJ", CRITICO if dup else OK, dup, len(cart)))

    em, pag = d.get("crm_emenda"), d.get("crm_emenda_pagamento")
    if isinstance(em, pd.DataFrame) and not em.empty:
        e = em.copy()
        for c in ("empenhado", "liquidado", "pago"):
            e[c] = pd.to_numeric(e[c], errors="coerce")
        r1 = e["liquidado"] > e["empenhado"] + 0.01
        r2 = e["pago"] > e["liquidado"] + 0.01
        ruim = r1 | r2
        out.append(_linha(F, "crm_emenda", "empenhado ≥ liquidado ≥ pago", ALERTA if ruim.any() else OK, int(ruim.sum()),
                          len(e), "inconsistência na fonte (ou restos a pagar de anos anteriores)" if ruim.any() else "",
                          _ex(e[ruim].rename(columns={"autor": "parlamentar"}), ["codigo", "empenhado", "liquidado", "pago"])
                          if ruim.any() else None))
        dup = int(e["codigo"].duplicated().sum())
        out.append(_linha(F, "crm_emenda", "uma linha por código de emenda", CRITICO if dup else OK, dup, len(e)))
        if isinstance(pag, pd.DataFrame) and not pag.empty:
            sp = pag.groupby("codigo_emenda")["valor_pago_doc"].sum()
            ref = e.set_index("codigo")["pago"].fillna(0) + pd.to_numeric(e.set_index("codigo").get("resto_pago"),
                                                                             errors="coerce").fillna(0)
            com = sp.index.intersection(ref.index)
            exced = sp[com] > ref[com] * 1.01 + 1
            out.append(_linha(F, "crm_emenda_pagamento", "Σ pagamentos dos documentos ≤ valor pago da emenda",
                              CRITICO if exced.any() else OK, int(exced.sum()), int(len(com)),
                              f"{int(exced.sum())} emendas com documentos somando mais que o pago" if exced.any() else ""))
            dif = pag.dropna(subset=["valor", "valor_detalhe"])
            div = (dif["valor"] - dif["valor_detalhe"]).abs() > 0.01
            out.append(_linha(F, "crm_emenda_pagamento", "valor do documento = valor do detalhe", ALERTA if div.any() else OK,
                              int(div.sum()), len(dif)))
            sem = int(pag["doc_favorecido"].fillna("").astype(str).eq("").sum())
            out.append(_linha(F, "crm_emenda_pagamento", "pagamentos com favorecido identificado",
                              ALERTA if sem else OK, sem, len(pag),
                              f"{sem} pagamentos ainda sem detalhe (entram nas próximas cargas)" if sem else ""))
            if "compartilhado" in pag:
                sh = pag[pag["compartilhado"].fillna(False).astype(bool) & pag["valor_detalhe"].notna()]
                if not sh.empty:
                    soma = sh.groupby("codigo_documento")["valor_pago_doc"].sum()
                    ordem = sh.groupby("codigo_documento")["valor_detalhe"].first()
                    ruim = (soma - ordem).abs() > 0.01
                    out.append(_linha(F, "crm_emenda_pagamento", "ordem paga a várias emendas: Σ rateio = valor da ordem",
                                      CRITICO if ruim.any() else OK, int(ruim.sum()), int(len(soma)),
                                      f"{int(len(soma))} ordens bancárias rateadas entre emendas" if not ruim.any() else ""))
            dupd = int(pag.duplicated(["codigo_emenda", "codigo_documento"]).sum())
            out.append(_linha(F, "crm_emenda_pagamento", "documento contado uma vez por emenda", CRITICO if dupd else OK,
                              dupd, len(pag)))

    # reconciliação: o que tem banco conhecido não pode ser maior do que o Portal registra (por fonte)
    if isinstance(rec, pd.DataFrame) and not rec.empty:
        out_ = d.get("fato_repasse_outros")
        if isinstance(out_, pd.DataFrame) and not out_.empty and "cnpj" in out_:
            fns = out_[out_["fonte"] == "FNS"].assign(
                mes=lambda x: x["ano"].astype(int).astype(str) + "-" + x["mes"].astype(int).astype(str).str.zfill(2))
            meses = set(rec["mes"].dropna())
            fns = fns[fns["mes"].isin(meses)]
            if not fns.empty:
                saude = rec[rec["orgao_superior"].fillna("").str.contains("Saúde|Saude", regex=True)]
                a = fns.groupby(["cnpj", "mes"])["valor"].sum()
                b = saude.groupby(["cnpj", "mes"])["valor"].sum()
                k = a.index.intersection(b.index)
                dif = (a[k] - b[k]).abs() > (b[k].abs() * 0.02 + 1)
                out.append(_linha(F, "reconciliação", "FNS (com banco) = Portal Saúde, por ente e mês",
                                  ALERTA if dif.any() else OK, int(dif.sum()), int(len(k)),
                                  f"{int(dif.sum())} pares ente-mês divergem mais de 2%" if dif.any() else
                                  ("sem pares em comum para comparar" if not len(k) else "")))

    pres = d.get("crm_presenca")
    if isinstance(pres, pd.DataFrame) and not pres.empty:
        dup = int(pres["cod_ibge"].duplicated().sum())
        out.append(_linha(F, "crm_presenca", "uma linha por município", CRITICO if dup else OK, dup, len(pres)))
        vb = pd.to_numeric(pres["valor_por_beneficiario"], errors="coerce")
        fora = vb.notna() & ((vb < 50) | (vb > 3000))
        out.append(_linha(F, "crm_presenca", "valor por beneficiário plausível (R$ 50 a R$ 3.000)", ALERTA if fora.any() else OK,
                          int(fora.sum()), int(vb.notna().sum())))
    al = d.get("crm_alertas")
    if isinstance(al, pd.DataFrame) and not al.empty:
        for regra, nome in (("CON-01", "fornecedor sancionado pago durante a sanção"),
                            ("CON-02", "entidade no CEPIM recebendo recursos"),
                            ("CON-03", "ente da prospecção com sanção vigente")):
            x = al[al["regra"] == regra]
            chave = ["cnpj", "cnpj_ente", "banco_conta"] if regra == "CON-01" else ["cnpj"]
            dup = int(x.duplicated([c for c in chave if c in x], keep="first").sum())
            out.append(_linha(F, "crm_alertas", f"{regra}: um alerta por {' + '.join(chave)} (valor contado uma vez)",
                              CRITICO if dup else OK, dup, int(len(x))))
            if not x.empty:
                out.append(_linha("Conformidade", "crm_alertas", nome, ALERTA, int(len(x)), None,
                                  f"R$ {pd.to_numeric(x['valor'], errors='coerce').sum():,.2f} envolvidos",
                                  _ex(x, ["cadastro", "valor", "data", "banco_conta"], ordem="valor")))
    return out

# ------------------------------------------------------------------ execução
# ------------------------------------------------------------------ 9. premissas que viram número
def premissas(d: dict) -> list[dict]:
    """Onde o painel mostra um valor que é premissa (prazo padrão), e não medição."""
    out = []
    pm = d.get("mart_permanencia")
    if isinstance(pm, pd.DataFrame) and not pm.empty and {"base_permanencia", "saldo"} <= set(pm.columns):
        s = pd.to_numeric(pm["saldo"], errors="coerce").fillna(0)
        med = pm["base_permanencia"].astype(str).str.startswith("medido")
        pct_padrao = float(s[~med].sum() / s.sum()) if s.sum() else 0.0
        grupos = pm.assign(_m=med).groupby(["modulo", "grupo_banco"])["_m"].any()
        sem = [f"{m} · {b}" for (m, b), v in grupos.items() if not v]
        out.append(_linha("Premissas", "mart_permanencia", "permanência medida (não prazo padrão)",
                          ALERTA if pct_padrao > 0.5 else OK, round(pct_padrao, 4), 0.5,
                          f"{pct_padrao:.0%} do saldo usa o prazo padrão; grupos sem medição: {', '.join(sem) or 'nenhum'}. "
                          "A tela mostra esses grupos como não medidos (sem média)"))
    # cobertura do Portal ("recursos recebidos") frente às transferências conhecidas aos municípios
    rec, out_ = d.get("crm_recebido"), d.get("fato_repasse_outros")
    if isinstance(rec, pd.DataFrame) and not rec.empty and isinstance(out_, pd.DataFrame) and not out_.empty \
            and {"tipo", "mes", "valor"} <= set(rec.columns):
        mun = rec[rec["tipo"].fillna("").astype(str).str.contains("Municipal")]
        o = out_[out_["fonte"].isin(["FPM", "FUNDEB", "FNS"])].assign(
            m=lambda x: x["ano"].astype(int).astype(str) + "-" + x["mes"].astype(int).astype(str).str.zfill(2))
        meses = sorted(set(mun["mes"].dropna()) & set(o["m"]))
        if meses:
            a = float(pd.to_numeric(mun[mun["mes"].isin(meses)]["valor"], errors="coerce").sum())
            b = float(pd.to_numeric(o[o["m"].isin(meses)]["valor"], errors="coerce").sum())
            out.append(_linha("Premissas", "crm_recebido", "Portal × transferências conhecidas aos municípios",
                              ALERTA if b and a / b < 0.5 else OK, round(a, 2), round(b, 2),
                              f"nos meses {', '.join(meses)}, o Portal registra {a / b:.0%} do que FPM + FUNDEB + FNS "
                              "transferiram aos municípios: o 'recebido no Portal' é parcial (despesas com o CNPJ como "
                              "favorecido) e não deve ser lido como tudo o que o ente recebe" if b else ""))
    paradas = (d.get("meta") or {}).get("fontes_interrompidas", []) if hasattr(d, "get") else []
    if paradas:
        out.append(_linha("Premissas", "meta", "fontes com extrato parado", ALERTA, len(paradas), None,
                          "; ".join(f"{p['modulo']} · {p['banco']}" for p in paradas) +
                          " — conferir com a auditoria da carga (QLD-01)"))
    return out


def auditar(d: dict, hoje: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    hoje = hoje or date.today()
    d = {k: v for k, v in d.items() if not str(k).startswith("mart_auditoria")}   # não audita o próprio relatório
    linhas = []
    for f in (percentuais, negativos_extremos, unicidade, partes_todo, coerencia_telas, territorio, crm, premissas):
        try:
            linhas += f(d)
        except Exception as e:  # uma família com erro não derruba as outras
            linhas.append(_linha(f.__name__, "-", "execução da checagem", CRITICO, detalhe=f"{type(e).__name__}: {e}"[:300]))
    linhas += datas(d, hoje)
    ex = []
    for i, l in enumerate(linhas):
        e = l.pop("_exemplos")
        if e is not None and not e.empty:
            ex.append(e.assign(_checagem=f"{l['tabela']} · {l['checagem']}"))
    aud = pd.DataFrame(linhas)
    aud["dia"] = hoje.isoformat()
    for c in ("valor", "referencia"):
        aud[c] = pd.to_numeric(aud[c], errors="coerce")
    exemplos = pd.concat(ex, ignore_index=True) if ex else pd.DataFrame()
    if not exemplos.empty:     # tipos misturados: guarda como texto (é só para leitura)
        exemplos = exemplos.astype(object).where(exemplos.notna(), None).astype(str).replace("None", "")
    return aud, exemplos


def gravar(aud: pd.DataFrame, exemplos: pd.DataFrame, pasta: Path, dia: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    aud.to_csv(pasta / f"painel_{dia}.csv", index=False, sep=";", encoding="utf-8-sig")
    if not exemplos.empty:
        exemplos.to_csv(pasta / f"painel_{dia}_exemplos.csv", index=False, sep=";", encoding="utf-8-sig")
    cor = {OK: "#12733F", ALERTA: "#B54708", CRITICO: "#A3222F"}
    resumo = aud["status"].value_counts().to_dict()
    linhas = "".join(
        f"<tr><td>{html.escape(str(r.familia))}</td><td>{html.escape(str(r.tabela))}</td><td>{html.escape(str(r.checagem))}</td>"
        f"<td style='color:{cor.get(r.status, '#333')};font-weight:700'>{r.status}</td><td>{'' if pd.isna(r.valor) else r.valor}</td>"
        f"<td>{'' if pd.isna(r.referencia) else r.referencia}</td><td>{html.escape(str(r.detalhe or ''))}</td></tr>"
        for r in aud.sort_values("status", key=lambda s: s.map({CRITICO: 0, ALERTA: 1, OK: 2})).itertuples())
    ex_html = ""
    if not exemplos.empty:
        for chk, g in exemplos.groupby("_checagem"):
            ex_html += f"<h3>{html.escape(chk)}</h3>" + g.drop(columns="_checagem").dropna(axis=1, how="all").to_html(index=False)
    arq = pasta / f"painel_{dia}.html"
    arq.write_text(f"""<!doctype html><meta charset="utf-8"><title>Auditoria do painel {dia}</title>
<style>body{{font-family:Segoe UI,Arial;margin:24px;color:#101828}}table{{border-collapse:collapse;font-size:13px;margin:8px 0 18px}}
td,th{{border:1px solid #E4E9F0;padding:4px 8px;text-align:left}}th{{background:#F7F9FC}}</style>
<h1>Auditoria do painel · {dia}</h1><p>{resumo.get(CRITICO, 0)} críticos · {resumo.get(ALERTA, 0)} alertas · {resumo.get(OK, 0)} ok</p>
<table><tr><th>Família</th><th>Tabela</th><th>Checagem</th><th>Status</th><th>Valor</th><th>Referência</th><th>Detalhe</th></tr>{linhas}</table>
<h2>Exemplos das linhas que falharam</h2>{ex_html}""", "utf-8")
    return arq


def main() -> int:
    from . import config, consultas
    cam = config.caminhos()
    ex = consultas.execucao_atual(cam)
    if not ex:
        print("Sem carga. Rode carga_diaria.bat.")
        return 1
    d = consultas.carregar(ex, cam)
    aud, exemplos = auditar(d)
    arq = gravar(aud, exemplos, cam.dados / "auditoria", date.today().isoformat())
    r = aud["status"].value_counts().to_dict()
    print(f"Carga {ex}: {r.get(CRITICO, 0)} críticos, {r.get(ALERTA, 0)} alertas, {r.get(OK, 0)} ok")
    for l in aud[aud["status"] != OK].itertuples():
        print(f"  [{l.status}] {l.tabela} · {l.checagem}: {l.detalhe}")
    print(f"Relatório: {arq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
