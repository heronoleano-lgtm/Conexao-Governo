"""Auditoria profunda: cada número-chave recalculado por um caminho independente, testes estatísticos e uma rede
neural de anomalias. Roda na carga e grava mart_auditoria_profunda (checagens) e mart_anomalias_entes.

1. Conferência independente — os totais publicados são refeitos em SQL (SQLite, motor diferente do pandas) a
   partir dos fatos: participação CAIXA, saldo por banco (uma vez por conta), somas por ente e por UF.
2. Lei de Benford — distribuição do 1º dígito dos valores. Desvio forte indica arredondamento, valores de
   referência, lançamentos manuais repetidos ou erro de leitura. É um SINAL para olhar, não prova de nada.
3. Extremos robustos — por modalidade, valores com z robusto (mediana/MAD, em log) acima de 6.
4. Possíveis duplicidades — mesmo pagador, recebedor, valor e data em pagamentos distintos.
5. Rede neural (autoencoder) — aprende o "perfil normal" dos entes a partir de 10 indicadores e aponta os que ela
   não consegue reconstruir (combinações raras, ex.: saldo muito alto para o que recebe). Validação embutida:
   anomalias plantadas têm de aparecer no topo (recall) e o resultado tem de ser estável entre 5 inicializações
   (Jaccard). Um segundo detector (z robusto) serve de comparação. Só numpy: nada a instalar.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

OK, ALERTA, CRITICO, NV = "ok", "atenção", "crítico", "não verificável"


def _linha(familia, tabela, checagem, status, valor=None, referencia=None, detalhe="", metodo=""):
    return {"familia": familia, "tabela": tabela, "checagem": checagem, "status": status, "valor": valor,
            "referencia": referencia, "metodo": metodo, "detalhe": detalhe}


def _cmp(familia, tabela, checagem, a, b, metodo, tol=0.001):
    if a is None or b is None or (isinstance(a, float) and np.isnan(a)) or (isinstance(b, float) and np.isnan(b)):
        return _linha(familia, tabela, checagem, NV, a, b, "sem dado para comparar", metodo)
    dif = abs(a - b) / max(abs(b), 1.0)
    st = OK if dif <= tol else (ALERTA if dif <= 0.02 else CRITICO)
    return _linha(familia, tabela, checagem, st, round(float(a), 2), round(float(b), 2),
                  "" if st == OK else f"diferença de {dif:.2%} entre os dois caminhos", metodo)


# ------------------------------------------------------------------ 1. conferência independente (SQL)
def _sql(d) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    cols = {"fato_instrumento": ["modulo", "cnpj_ente", "uf", "grupo_banco", "valor"],
            "fato_conta": ["modulo", "id_agencia_conta", "cnpj_ente", "grupo_banco", "saldo"],
            "mart_ente_resumo": ["cnpj_ente", "valor", "valor_caixa", "saldo_caixa", "saldo_concorrente"],
            "mart_custodia": ["modulo", "grupo_banco", "saldo"]}
    for t, cs in cols.items():
        df = d.get(t)
        if df is None or df.empty:
            continue
        x = df[[c for c in cs if c in df.columns]].copy()
        for c in x.columns:
            if not pd.api.types.is_numeric_dtype(x[c]):
                x[c] = x[c].astype(object).where(x[c].notna(), None).map(lambda v: None if v is None else str(v))
        x.to_sql(t, con, index=False)
    return con


def conferencia_independente(d) -> list[dict]:
    out = []
    fi, fc, er = d.get("fato_instrumento"), d.get("fato_conta"), d.get("mart_ente_resumo")
    if fi is None or fi.empty:
        return out
    con = _sql(d)
    q = lambda s: pd.read_sql(s, con)  # noqa: E731
    M = "pandas × SQL"
    com = fi[fi["grupo_banco"] != "(sem banco)"]
    a = float(com.loc[com["grupo_banco"] == "CAIXA", "valor"].sum() / com["valor"].sum()) if com["valor"].sum() else None
    b = q("select sum(case when grupo_banco='CAIXA' then valor end)*1.0/sum(valor) p from fato_instrumento "
          "where grupo_banco<>'(sem banco)'").p[0]
    out.append(_cmp("Conferência independente", "fato_instrumento", "participação CAIXA total", a, b, M, 1e-9))
    s1 = com.groupby("uf")["valor"].sum()
    s2 = q("select uf, sum(valor) v from fato_instrumento where grupo_banco<>'(sem banco)' and uf is not null "
           "group by uf").set_index("uf")["v"]
    pior = float((s1 - s2.reindex(s1.index)).abs().max()) if len(s1) else 0.0
    out.append(_linha("Conferência independente", "fato_instrumento", "valor por UF (pior UF)",
                      OK if pior < 1 else CRITICO, round(pior, 2), 0, "" if pior < 1 else "UF com soma diferente", M))
    if fc is not None and not fc.empty:
        sal = pd.to_numeric(fc["saldo"], errors="coerce")
        a = float(fc.assign(s=sal).groupby(["modulo", "id_agencia_conta"])["s"].max().sum())
        b = q("select sum(s) s from (select modulo, id_agencia_conta, max(saldo) s from fato_conta group by 1,2)").s[0]
        out.append(_cmp("Conferência independente", "fato_conta", "saldo total, uma vez por conta", a, b, M))
        soma_linhas = float(sal.sum())
        out.append(_cmp("Conferência independente", "fato_conta", "saldo somando linhas = saldo uma vez por conta",
                        soma_linhas, b, "linhas × contas distintas",
                        0.0001))   # se a mesma conta repetir saldo em várias linhas, a soma de linhas infla
        mc = d.get("mart_custodia")
        if mc is not None and not mc.empty:
            out.append(_cmp("Conferência independente", "mart_custodia", "custódia publicada = contas distintas",
                            float(mc["saldo"].sum()), b, "mart × SQL"))
        for t in ("mart_permanencia", "mart_variacao_banco", "mart_defasagem"):
            x = d.get(t)
            if x is not None and not x.empty and "saldo" in x:
                out.append(_cmp("Conferência independente", t, f"{t}: Σ saldo = contas distintas",
                                float(pd.to_numeric(x["saldo"], errors="coerce").sum()), b, "mart × SQL"))
    if er is not None and not er.empty:
        b = q("select sum(valor) v from fato_instrumento where grupo_banco='CAIXA' and cnpj_ente is not null").v[0]
        out.append(_cmp("Conferência independente", "mart_ente_resumo", "Σ valor CAIXA dos entes",
                        float(er["valor_caixa"].sum()), b, "mart × SQL"))
    con.close()
    return out


# ------------------------------------------------------------------ 2. Benford
BENFORD = np.log10(1 + 1 / np.arange(1, 10))


def benford(valores: pd.Series) -> dict:
    v = pd.to_numeric(valores, errors="coerce").abs()
    v = v[v >= 10]
    if len(v) < 1000:
        return {"n": int(len(v)), "mad": None, "classe": "amostra pequena"}
    dig = (v / 10 ** np.floor(np.log10(v))).astype(int).clip(1, 9)
    obs = np.bincount(dig, minlength=10)[1:] / len(dig)
    mad = float(np.mean(np.abs(obs - BENFORD)))
    classe = ("conformidade próxima" if mad <= 0.006 else "conformidade aceitável" if mad <= 0.012
              else "conformidade marginal" if mad <= 0.015 else "não conforme")
    excesso = int(np.argmax(obs - BENFORD)) + 1
    return {"n": int(len(v)), "mad": mad, "classe": classe, "digito_excesso": excesso,
            "obs": obs.round(4).tolist(), "esperado": BENFORD.round(4).tolist()}


# valores definidos por fórmula, teto ou arredondamento (coeficientes do FPM, emendas em múltiplos de mil, repasses
# per capita): Benford NÃO se aplica — o teste fica informativo. Em pagamentos e lançamentos (transacionais) o desvio
# merece olhar.
TRANSACIONAIS = {"fato_pagamento", "fato_fluxo"}


def _redondos(v: pd.Series) -> float:
    v = pd.to_numeric(v, errors="coerce").abs()
    v = v[v >= 1000]
    return float(((v % 1000) == 0).mean()) if len(v) else float("nan")


def testes_benford(d) -> list[dict]:
    out = []
    for t, col, grupo in (("fato_instrumento", "valor", "modulo"), ("fato_pagamento", "valor", "modulo"),
                          ("fato_fluxo", "valor", "modulo"), ("crm_recebido", "valor", None),
                          ("fato_repasse_outros", "valor", "fonte")):
        df = d.get(t)
        if df is None or df.empty or col not in df:
            continue
        grupos = [(None, df)] if not grupo or grupo not in df else list(df.groupby(grupo))
        for g, x in grupos:
            b = benford(x[col])
            if b["mad"] is None:
                continue
            trans = t in TRANSACIONAIS
            st = OK if b["mad"] <= 0.012 or not trans else ALERTA
            red = _redondos(x[col])
            top = pd.to_numeric(x[col], errors="coerce").round(2).value_counts().head(3)
            out.append(_linha("Benford (1º dígito)", t, f"{t}{' · ' + str(g) if g else ''}", st, round(b["mad"], 4),
                              0.012, (f"{b['classe']} · {b['n']:,} valores · dígito {b['digito_excesso']} acima do "
                                      f"esperado · {red:.0%} são múltiplos de R$ 1 mil · valores mais repetidos: "
                                      + ", ".join(f"R$ {v:,.0f} ({n}×)" for v, n in top.items())).replace(",", "X")
                              .replace(".", ",").replace("X", ".")
                              + ("" if trans else " · valores por fórmula/arredondados: desvio esperado, só informativo"),
                              "Nigrini: MAD ≤ 0,012 aceitável"))
    return out


# ------------------------------------------------------------------ 3. extremos e 4. duplicidades
def extremos(d, z_lim: float = 6.0) -> tuple[list[dict], pd.DataFrame]:
    out, ex = [], []
    fi = d.get("fato_instrumento")
    if fi is not None and not fi.empty:
        for m, x in fi.groupby("modulo"):
            v = pd.to_numeric(x["valor"], errors="coerce")
            lv = np.log10(v[v > 0])
            if len(lv) < 100:
                continue
            med, mad = lv.median(), (lv - lv.median()).abs().median() * 1.4826
            z = (lv - med) / mad if mad else lv * 0
            alto = z[z > z_lim].index
            out.append(_linha("Extremos robustos", "fato_instrumento", f"valores extremos · {m}",
                              OK if len(alto) == 0 else ALERTA, int(len(alto)), int(len(lv)),
                              f"{len(alto)} instrumentos com valor muito acima do típico (z robusto > {z_lim:g}); "
                              f"maior: R$ {v.loc[alto].max():,.0f}".replace(",", ".") if len(alto) else "",
                              "z robusto em log10 (mediana/MAD)"))
            if len(alto):
                ex.append(x.loc[alto, [c for c in ("modulo", "id_instrumento", "cnpj_ente", "nome_ente", "uf",
                                                   "grupo_banco", "valor", "objeto") if c in x]].assign(z=z.loc[alto]))
    return out, (pd.concat(ex, ignore_index=True).sort_values("z", ascending=False) if ex else pd.DataFrame())


def duplicidades(d) -> list[dict]:
    out = []
    p = d.get("fato_pagamento")
    if p is not None and not p.empty and {"cnpj_ente", "doc_recebedor", "valor", "data"} <= set(p.columns):
        if "id_pagamento" in p and p["id_pagamento"].notna().any():     # identificador da fonte: duplicata exata
            com_id = p[p["id_pagamento"].notna()]
            n = int(com_id.duplicated(["modulo", "id_pagamento"]).sum())
            out.append(_linha("Possíveis duplicidades", "fato_pagamento", "identificador do pagamento único",
                              OK if n == 0 else CRITICO, n, int(len(com_id)),
                              f"{n} pagamentos com o mesmo identificador da fonte" if n else "", "id da fonte"))
            p = p[p["id_pagamento"].isna()]
        sem_ente = int(p["cnpj_ente"].isna().sum())
        p = p[p["cnpj_ente"].notna()]
        k = ["cnpj_ente", "doc_recebedor", "valor", "data"] + (["id_instrumento"] if "id_instrumento" in p else [])
        dup = p[p.duplicated(k, keep=False)]
        extra = float(dup["valor"].sum() - dup.drop_duplicates(k)["valor"].sum()) if len(dup) else 0.0
        out.append(_linha("Possíveis duplicidades", "fato_pagamento", "mesmo pagador, recebedor, valor, data e instrumento",
                          OK if extra == 0 else ALERTA, int(len(dup)), int(len(p)),
                          (f"R$ {extra:,.0f} se as repetições forem contadas mais de uma vez; podem ser parcelas "
                           "legítimas (a fonte não traz identificador) — conferir na fonte").replace(",", ".")
                          + (f" · {sem_ente} pagamentos sem ente pagador ficaram fora" if sem_ente else "")
                          if extra or sem_ente else "", "chave composta (sem identificador da fonte)"))
    return out


# ------------------------------------------------------------------ 5. rede neural (autoencoder)
VARS = ["valor", "valor_caixa", "valor_concorrente", "saldo_caixa", "saldo_concorrente", "a_creditar",
        "potencial_custodia", "pagamentos_fora_caixa", "transf_secundaria", "populacao"]


RAZOES = ["valor_caixa", "saldo_caixa", "saldo_concorrente", "a_creditar", "potencial_custodia",
          "pagamentos_fora_caixa", "transf_secundaria"]


def _matriz(er: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Tamanho do ente (valor e população, em log) + cada indicador como PROPORÇÃO do valor recebido: assim a rede
    procura combinações atípicas (ex.: saldo 50× o recebido) e não só entes grandes."""
    x = er.reindex(columns=VARS).apply(pd.to_numeric, errors="coerce").fillna(0).clip(lower=0)
    base = x["valor"] + 1.0
    cols = {"tamanho (valor)": np.log1p(x["valor"]), "tamanho (população)": np.log1p(x["populacao"])}
    for c in RAZOES:
        cols[f"{c} ÷ valor"] = np.log1p(x[c] / base)
    m = pd.DataFrame(cols)
    vs = list(m.columns)
    X = m.to_numpy(float)
    med = np.median(X, axis=0)
    iqr = np.subtract(*np.percentile(X, [75, 25], axis=0))
    iqr[iqr == 0] = X.std(axis=0)[iqr == 0] + 1e-9
    return (X - med) / iqr, vs


class Autoencoder:
    """MLP n→16→4→16→n (tanh), Adam, erro quadrático. Só numpy."""

    def __init__(self, n: int, semente: int = 0, ocultas=(16, 4)):
        r = np.random.default_rng(semente)
        dims = [n, ocultas[0], ocultas[1], ocultas[0], n]
        self.W = [r.normal(0, np.sqrt(1 / a), (a, b)) for a, b in zip(dims[:-1], dims[1:])]
        self.b = [np.zeros(b) for b in dims[1:]]
        self.m = [np.zeros_like(w) for w in self.W + self.b]
        self.v = [np.zeros_like(w) for w in self.W + self.b]
        self.t = 0

    def _fwd(self, X):
        hs = [X]
        for i, (w, b) in enumerate(zip(self.W, self.b)):
            z = hs[-1] @ w + b
            hs.append(z if i == len(self.W) - 1 else np.tanh(z))
        return hs

    def reconstruir(self, X):
        return self._fwd(X)[-1]

    def treinar(self, X, epocas=60, lote=256, lr=3e-3, semente=0):
        r = np.random.default_rng(semente)
        n = len(X)
        for _ in range(epocas):
            idx = r.permutation(n)
            for i in range(0, n, lote):
                xb = X[idx[i:i + lote]]
                hs = self._fwd(xb)
                g = 2 * (hs[-1] - xb) / len(xb)
                gW, gb = [None] * len(self.W), [None] * len(self.b)
                for j in range(len(self.W) - 1, -1, -1):
                    gW[j] = hs[j].T @ g
                    gb[j] = g.sum(axis=0)
                    if j:
                        g = (g @ self.W[j].T) * (1 - hs[j] ** 2)
                self.t += 1
                for k, (p, gr) in enumerate(zip(self.W + self.b, gW + gb)):
                    self.m[k] = 0.9 * self.m[k] + 0.1 * gr
                    self.v[k] = 0.999 * self.v[k] + 0.001 * gr ** 2
                    mh, vh = self.m[k] / (1 - 0.9 ** self.t), self.v[k] / (1 - 0.999 ** self.t)
                    p -= lr * mh / (np.sqrt(vh) + 1e-8)
        return self


def anomalias_entes(er: pd.DataFrame, sementes=(0, 1, 2, 3, 4), topo: float = 0.01, epocas: int = 80,
                    validar: bool = True) -> tuple[pd.DataFrame, list[dict]]:
    out = []
    if er is None or len(er) < 200:
        return pd.DataFrame(), [_linha("Rede neural", "mart_ente_resumo", "anomalias de entes", NV,
                                       detalhe="poucos entes para treinar")]
    X, vs = _matriz(er)
    erros, tops = [], []
    k = max(10, int(len(X) * topo))
    for s in sementes:
        ae = Autoencoder(X.shape[1], s).treinar(X, epocas=epocas, semente=s)
        e = (ae.reconstruir(X) - X) ** 2
        erros.append(e)
        tops.append(set(np.argsort(-e.sum(axis=1))[:k]))
    E = np.mean(erros, axis=0)
    score = E.sum(axis=1)
    jac = np.mean([len(a & b) / len(a | b) for i, a in enumerate(tops) for b in tops[i + 1:]]) if len(tops) > 1 else 1.0
    out.append(_linha("Rede neural", "mart_ente_resumo", "estabilidade entre inicializações (Jaccard do topo)",
                      OK if jac >= 0.6 else ALERTA, round(float(jac), 3), 0.6,
                      f"{len(sementes)} redes treinadas com sementes diferentes; o topo {topo:.0%} se repete em média "
                      f"{jac:.0%}", f"autoencoder {X.shape[1]}→16→4→16→{X.shape[1]}"))
    # segundo detector, independente: maior |z| robusto entre as variáveis
    zr = np.abs(X).max(axis=1)
    top_ae = set(np.argsort(-score)[:k])
    top_z = set(np.argsort(-zr)[:k])
    concord = len(top_ae & top_z) / k
    out.append(_linha("Rede neural", "mart_ente_resumo", "concordância com detector simples (z robusto)", OK,
                      round(concord, 3), None,
                      f"{concord:.0%} do topo da rede também é extremo numa variável isolada; o resto são combinações "
                      "raras que só a rede enxerga", "autoencoder × z robusto"))
    if validar:   # anomalias plantadas: cópias de entes com UMA combinação impossível
        r = np.random.default_rng(42)
        n_pl = 30
        base = er.sample(n_pl, random_state=42).copy()
        if {"saldo_concorrente", "valor"} <= set(base.columns):
            base["saldo_concorrente"] = pd.to_numeric(base["valor"], errors="coerce").fillna(0) * 50 + 5e7
        Xp, _ = _matriz(pd.concat([er, base], ignore_index=True))
        ae = Autoencoder(Xp.shape[1], 0).treinar(Xp[:len(er)], epocas=epocas, semente=0)
        sp = ((ae.reconstruir(Xp) - Xp) ** 2).sum(axis=1)
        lim = np.sort(sp[:len(er)])[-int(len(er) * 0.02)]
        recall = float((sp[len(er):] >= lim).mean())
        out.append(_linha("Rede neural", "mart_ente_resumo", "validação com anomalias plantadas (recall no topo 2%)",
                           OK if recall >= 0.8 else ALERTA, round(recall, 3), 0.8,
                           f"{n_pl} entes falsos com saldo no concorrente 50× o valor recebido; a rede pôs "
                           f"{recall:.0%} deles entre os 2% mais anômalos", "teste de sanidade do detector"))
        del r
    # explicação: variáveis que a rede menos conseguiu reconstruir em cada ente anômalo
    idx = np.argsort(-score)[:k]
    linhas = []
    for i in idx:
        cont = E[i] / E[i].sum() if E[i].sum() else E[i]
        ordem = np.argsort(-cont)[:3]
        r_ = er.iloc[i]
        linhas.append({"cnpj_ente": r_.get("cnpj_ente"), "nome_ente": r_.get("nome_ente"), "uf": r_.get("uf"),
                       "escore_anomalia": float(score[i]), "percentil": float((score < score[i]).mean()),
                       "explicacao": "; ".join(f"{vs[j]} ({cont[j]:.0%})" for j in ordem),
                       "extremo_isolado": i in top_z,
                       **{v: r_.get(v) for v in VARS if v in er}})
    an = pd.DataFrame(linhas)
    out.append(_linha("Rede neural", "mart_ente_resumo", "entes com perfil atípico", ALERTA if len(an) else OK,
                      int(len(an)), int(len(er)), f"{len(an)} entes (1% mais anômalos) para conferência manual: podem "
                      "ser erro de dado (ex.: conta atribuída ao ente errado) ou oportunidade real", "autoencoder"))
    return an, out


# ------------------------------------------------------------------ tudo
def auditar(d, rede: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    linhas = []
    for f in (conferencia_independente, testes_benford, duplicidades):
        try:
            linhas += f(d)
        except Exception as e:  # pragma: no cover
            linhas.append(_linha(f.__name__, "-", "execução", CRITICO, detalhe=str(e)[:200]))
    try:
        l2, ext = extremos(d)
        linhas += l2
    except Exception as e:  # pragma: no cover
        ext = pd.DataFrame()
        linhas.append(_linha("extremos", "-", "execução", CRITICO, detalhe=str(e)[:200]))
    an = pd.DataFrame()
    if rede:
        try:
            an, l3 = anomalias_entes(d.get("mart_ente_resumo"))
            linhas += l3
        except Exception as e:  # pragma: no cover
            linhas.append(_linha("Rede neural", "-", "execução", CRITICO, detalhe=str(e)[:200]))
    return pd.DataFrame(linhas), an, ext
