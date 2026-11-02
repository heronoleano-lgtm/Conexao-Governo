"""Reconstituição do saldo das contas das Transferências Especiais (regra SAL-01).

Por que existe: a CAIXA parou de publicar extrato e saldo das Especiais em 30/05/2025 (saldo congelado em
30/04/2025), mas as ordens bancárias continuam sendo publicadas. Desde a parada, R$ 6,4 bi foram creditados em contas
CAIXA, a maioria em contas novas que nunca tiveram saldo publicado. Mostrar só o saldo parado esconde esse dinheiro;
inventar um saldo seria pior. Este módulo reconstitui o saldo mês a mês com o que é publicado e mede o próprio erro.

Modelo, por conta e por mês:
    saldo(m) = saldo(m−1) × (1 + r) + créditos(m) − saídas(m)
- créditos = ordens bancárias do plano da conta (medido: publicado para todos os bancos);
- saídas = débitos do extrato, sem as aplicações financeiras (o saldo publicado INCLUI o aplicado: com as
  aplicações tratadas como saída, o erro passava de bilhões);
- r = rendimento mensal da aplicação, que não é publicado. É calibrado nos bancos que publicam: o r que faz a soma
  reconstituída bater com a soma publicada. Em 01/11/2026: 1,0% ao mês (≈ 12,7% ao ano, ordem do CDI); a mesma
  taxa, aplicada à CAIXA até abr/2025 (fora da calibração), errou o total em +4,3%, com 73% das contas a até 5%.
- Depois da parada de um banco, as saídas dele não são conhecidas. Usa-se a CURVA DE EXECUÇÃO do próprio banco,
  medida antes da parada: que fração de um crédito ainda está na conta k meses depois (contas de um só crédito). O
  dinheiro que estava na conta na parada decai pela curva, conforme a idade de cada crédito; os créditos novos
  (ordens bancárias, que continuam publicadas) entram e decaem pela mesma curva. Um ritmo único de saída sobre o
  estoque foi testado e descartado (erro de −30% a +36% no teste retroativo).
- Faixa de incerteza: a cada carga, o painel finge que os bancos que publicam pararam em várias datas passadas,
  projeta com a mesma técnica e mede o erro contra o saldo reconstituído com as saídas reais. A faixa usa os erros
  observados em horizontes parecidos (01/11/2026: de −11% a +52%; paradas recentes, de −11% a +2%).
- Conta de banco parado COM saldo publicado parte do valor publicado na data dele (âncora); conta sem saldo
  publicado parte de zero no primeiro crédito.
- Conta sem crédito publicado (conta de executor, saldo sem vínculo) não tem como ser reconstituída: fica com o
  valor publicado, marcada como "parado — sem como reconstituir".
Nada aqui substitui o saldo publicado: as colunas novas ficam ao lado (saldo_estimado, faixa e base).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import normaliza
from .regras import param as _p

ANO0 = 2018
APLICACAO = "aplicação/resgate"
BASE_PUBLICADO = "publicado"
BASE_RECONST = "reconstituído (créditos − débitos publicados + rendimento estimado)"
BASE_PARADO_ANCORA = "estimado: extrato parado; parte do último saldo publicado"
BASE_PARADO_NOVA = "estimado: conta creditada depois que o extrato parou (sem saldo publicado)"
BASE_SEM_COMO = "parado — sem como reconstituir (sem créditos publicados)"
BASE_NUNCA = "estimado: banco nunca publicou extrato (curva média dos bancos que publicam)"


def _mes(d: pd.Series) -> pd.Series:
    return ((d.dt.year - ANO0) * 12 + d.dt.month - 1).clip(lower=0)


def _ultimo_dia(m: int) -> str:
    a, mm = ANO0 + m // 12, m % 12 + 1
    return (pd.Timestamp(a, mm, 1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")


def _simular(C, D, r, real_ate, h, fim, ancora_mes=None, ancora_val=None):
    """Roda o modelo. real_ate: último mês com saídas reais (por linha); depois, saídas = h × disponível.
    Devolve o saldo no mês `fim` de cada linha e a série mensal da soma."""
    n, M = C.shape
    S = np.zeros(n)
    out = np.zeros(n)
    serie = np.zeros(M)
    for m in range(M):
        disp = S * (1 + r) + C[:, m]
        S = np.where(m <= real_ate, np.maximum(disp - D[:, m], 0.0), disp * (1 - h))
        if ancora_mes is not None:
            a = ancora_mes == m
            S = np.where(a, ancora_val, S)
        out = np.where(fim == m, S, out)
        serie[m] = S.sum()
    return out, serie


def _ritmo(C, D, r, ate, meses):
    """Saída efetiva mensal ÷ dinheiro disponível, nos `meses` antes de `ate` (com as saídas reais)."""
    S = np.zeros(C.shape[0])
    num = den = 0.0
    for m in range(min(ate + 1, C.shape[1])):
        disp = S * (1 + r) + C[:, m]
        if m > ate - meses:
            num += D[:, m].sum()
            den += disp.sum()
        S = np.maximum(disp - D[:, m], 0.0)
    return num / den if den > 0 else np.nan


def _aval(est, obs, cred):
    e = obs - est
    tot = obs.sum()
    return {"contas": int(len(obs)), "soma_publicada": float(tot), "soma_reconstituida": float(est.sum()),
            "erro_total": float((est.sum() - tot) / tot) if tot else np.nan,
            "contas_ate_5pct": float((np.abs(e) <= .05 * np.maximum(cred, 1)).mean()) if len(e) else np.nan,
            "contas_ate_10pct": float((np.abs(e) <= .10 * np.maximum(cred, 1)).mean()) if len(e) else np.nan}


def reconstituir(contas: pd.DataFrame, creditos: pd.DataFrame, fluxo: pd.DataFrame, hoje: date,
                 paradas: set | None = None) -> dict[str, pd.DataFrame]:
    vazio = {"contas": pd.DataFrame(), "serie": pd.DataFrame(), "qualidade": pd.DataFrame()}
    if contas is None or contas.empty or creditos is None or creditos.empty:
        return vazio
    ct = contas[contas["modulo"] == "Especiais"].copy()
    cr = creditos[creditos["modulo"] == "Especiais"].copy()
    fl = fluxo[(fluxo["modulo"] == "Especiais")].copy() if fluxo is not None and not fluxo.empty else pd.DataFrame()
    if ct.empty or cr.empty:
        return vazio
    # uma linha por conta: banco, saldo publicado e data (o saldo já entra uma vez só por conta)
    ct["_s"] = pd.to_numeric(ct["saldo"], errors="coerce")
    ct["_d"] = normaliza.data(ct["data_saldo"]) if "data_saldo" in ct else pd.NaT
    contas_u = ct.groupby("id_agencia_conta").agg(grupo_banco=("grupo_banco", "first"),
                                                 saldo_publicado=("_s", lambda s: s.sum(min_count=1)),
                                                 data_saldo=("_d", "max"))
    cr["_d"] = normaliza.data(cr["data"])
    cr = cr[cr["_d"].notna() & cr["id_agencia_conta"].notna()]
    sem_conta = float(creditos.loc[creditos["id_agencia_conta"].isna(), "valor"].sum())
    fl["_d"] = normaliza.data(fl["data"]) if not fl.empty else pd.Series(dtype="datetime64[ns]")
    efetivo = fl[fl["tipo_movimento"] != APLICACAO] if not fl.empty else fl
    # último extrato EFETIVO de cada banco (lançamento isolado depois da parada não conta)
    ult_banco = (normaliza.ultimo_extrato_efetivo(fl, ("grupo_origem",)) if not fl.empty
                 else pd.Series(dtype="datetime64[ns]"))
    if not fl.empty:
        fl = fl[fl["_d"] <= fl["grupo_origem"].map(ult_banco)]
        efetivo = fl[fl["tipo_movimento"] != APLICACAO]
    paradas_b = {b for (m, b) in (paradas or set()) if m == "Especiais"}
    frescos = [b for b in ult_banco.index if b not in paradas_b]
    ref = ult_banco[frescos].max() if frescos else pd.Timestamp(hoje)
    ref = min(ref, pd.Timestamp(hoje))
    M = int(_mes(pd.Series([ref])).iloc[0]) + 1

    keys = contas_u.index.tolist()
    idx = pd.Series(np.arange(len(keys)), index=keys)
    C = np.zeros((len(keys), M))
    D = np.zeros((len(keys), M))
    c_in = cr[cr["id_agencia_conta"].isin(idx.index)]
    np.add.at(C, (idx[c_in["id_agencia_conta"]].values, np.minimum(_mes(c_in["_d"]).values, M - 1)),
              c_in["valor"].astype(float).values)
    if not efetivo.empty:
        d_in = efetivo[efetivo["id_agencia_conta"].isin(idx.index)]
        np.add.at(D, (idx[d_in["id_agencia_conta"]].values, np.minimum(_mes(d_in["_d"]).values, M - 1)),
                  d_in["valor"].astype(float).values)
    banco = contas_u["grupo_banco"].fillna("(sem banco)").values
    tem_cred = C.sum(axis=1) > 0
    pub = contas_u["saldo_publicado"].values
    m_saldo = _mes(contas_u["data_saldo"]).fillna(-1).astype(int).values
    tem_pub = ~np.isnan(pub) & (m_saldo >= 0)
    ult_m = {b: int(_mes(pd.Series([d])).iloc[0]) for b, d in ult_banco.items() if pd.notna(d)}
    q = []

    # 1) calibração do rendimento nos bancos que publicam
    cal = tem_cred & tem_pub & np.isin(banco, frescos)
    r = float(_p("SAL-01", "rendimento_mensal_padrao", 0.008))
    if cal.sum() >= 50:
        melhor = None
        for rr in np.arange(0, 0.0201, 0.0005):
            est, _ = _simular(C[cal], D[cal], rr, np.full(cal.sum(), M), 0.0, m_saldo[cal])
            a = _aval(est, pub[cal], C[cal].sum(1))
            if melhor is None or abs(a["erro_total"]) < abs(melhor[1]["erro_total"]):
                melhor = (rr, a)
        r = float(melhor[0])
        q.append({"teste": "Calibração do rendimento (bancos que publicam)", "parametro": f"r = {r:.2%} ao mês "
                  f"({(1 + r) ** 12 - 1:.1%} ao ano)", **melhor[1]})
    # 2) validação fora da amostra: banco parado, até a data do último saldo dele
    for b in paradas_b:
        v = tem_cred & tem_pub & (banco == b)
        if v.sum() >= 20:
            est, _ = _simular(C[v], D[v], r, np.full(v.sum(), M), 0.0, m_saldo[v])
            q.append({"teste": f"Validação fora da calibração: {b} até o último saldo publicado",
                      "parametro": f"mesmo r = {r:.2%} ao mês", **_aval(est, pub[v], C[v].sum(1))})
    # 3) curva de execução e testes retroativos (faixa de incerteza), nos bancos que publicam
    def historico(sel, ate):
        """Saldo mês a mês com as saídas reais até `ate` (depois, sem saídas)."""
        S = np.zeros(sel.sum())
        H = np.zeros((sel.sum(), M))
        for m in range(M):
            S = np.maximum(S * (1 + r) + C[sel, m] - (D[sel, m] if m <= ate else 0.0), 0.0)
            H[:, m] = S
        return H

    def curva(sel, H, ate, K=48):
        Cs = C[sel]
        um = (Cs > 0).sum(1) == 1
        Hs, Cs = H[um], Cs[um]
        m0, c0 = Cs.argmax(1), Cs.max(1)
        R = np.full(K, np.nan)
        for k in range(K):
            ok = (m0 + k) <= ate
            if c0[ok].sum() > 0:
                R[k] = Hs[ok, (m0 + k)[ok]].sum() / c0[ok].sum()
        conhecidos = np.where(~np.isnan(R))[0]
        if len(conhecidos) == 0:
            return None
        u = conhecidos.max()
        taxa = R[u] / R[u - 1] if u > 0 and R[u - 1] > 0 else 1.0
        for k in range(u + 1, K):
            R[k] = R[k - 1] * min(taxa, 1.0)
        return R

    def projetar(sel, R, ate, alvo, base_ate):
        """Saldo em `alvo` projetado a partir do saldo em `ate` (base_ate) + créditos posteriores, pela curva R."""
        Cs = C[sel]
        K = len(R)
        Rf = lambda k: R[np.clip(k, 0, K - 1)]  # noqa: E731
        novo = sum(Cs[:, m] * Rf(alvo - m) for m in range(ate + 1, alvo + 1)) if alvo > ate else 0.0
        w = np.zeros(sel.sum())
        tot = np.zeros(sel.sum())
        for m in range(ate + 1):
            a = Cs[:, m] * Rf(ate - m)
            w += a * np.where(Rf(ate - m) > 0, Rf(alvo - m) / np.maximum(Rf(ate - m), 1e-9), 0.0)
            tot += a
        fator = np.where(tot > 0, w / np.maximum(tot, 1e-9), 1.0)
        return base_ate * fator + novo

    erros = []
    for f in frescos:
        t = tem_cred & (banco == f)
        if t.sum() < 200 or f not in ult_m:
            continue
        Hf = historico(t, M)
        for st in range(ult_m[f] - 36, ult_m[f] - 5, 6):
            if st <= 0:
                continue
            Rb = curva(t, Hf, st)
            if Rb is None:
                continue
            for hz in (6, 12, 18, 24):
                alvo = st + hz
                if alvo > ult_m[f]:
                    continue
                verdade = Hf[:, alvo].sum()
                if verdade > 0:
                    e = projetar(t, Rb, st, alvo, Hf[:, st]).sum() / verdade - 1
                    erros.append({"banco": f, "parada": _ultimo_dia(st)[:7], "horizonte": hz, "erro": e})
    erros = pd.DataFrame(erros)
    for x in erros.itertuples():
        q.append({"teste": f"Teste retroativo: {x.banco} como se tivesse parado em {x.parada}, {x.horizonte} meses depois",
                  "parametro": "curva de execução do próprio banco", "erro_total": x.erro})

    def faixa(horizonte):
        if erros.empty:
            return (-0.5, 0.5)
        e = erros.loc[(erros["horizonte"] - horizonte).abs() <= 6, "erro"]
        e = e if len(e) else erros["erro"]
        return (float(e.min()), float(e.max()))

    # 4) estimativa de hoje, por conta
    fim = np.full(len(keys), M - 1)
    est = np.where(tem_pub, np.nan_to_num(pub), 0.0)
    est_min, est_max = est.copy(), est.copy()
    base = np.where(tem_pub, BASE_PUBLICADO, "sem saldo publicado").astype(object)   # texto sem largura fixa
    parada = np.full(len(keys), None, dtype=object)
    series = []
    for b in sorted(set(banco)):
        sel = banco == b
        if b in paradas_b and b in ult_m:
            s_cred = sel & tem_cred
            st = ult_m[b]
            if s_cred.any():
                Hb = historico(s_cred, st)
                Rb = curva(s_cred, Hb, st)
                # âncora: o saldo publicado na data dele substitui o reconstituído (é o dado real)
                base_st = Hb[:, st].copy()
                ancora = tem_pub[s_cred] & (m_saldo[s_cred] >= st - 1)
                base_st[ancora] = np.nan_to_num(pub[s_cred][ancora])
                if Rb is not None:
                    hz = M - 1 - st
                    lo, hi = faixa(hz)
                    v = projetar(s_cred, Rb, st, M - 1, base_st)
                    est[s_cred], est_min[s_cred], est_max[s_cred] = v, v / (1 + hi), v / (1 + lo)
                    teto = float(np.nansum(pub[sel & tem_pub])) + float(C[sel][:, st + 1:].sum())
                    q.append({"teste": f"Teto medido de {b} hoje (sem saídas nem rendimento)", "parametro":
                              "último saldo publicado + ordens bancárias creditadas depois da parada",
                              "soma_publicada": float(np.nansum(pub[sel & tem_pub])), "soma_reconstituida": teto})
                    q.append({"teste": f"Estimativa de {b} hoje ({hz} meses depois da parada)", "parametro":
                              f"faixa pelos testes retroativos: erro de {lo:+.0%} a {hi:+.0%}",
                              "soma_publicada": float(np.nansum(pub[s_cred])), "soma_reconstituida": float(v.sum())})
                    congelado = float(np.nansum(pub[sel & ~tem_cred & tem_pub]))
                    for m in range(M):
                        if m <= st:
                            tot = base_st.sum() + congelado if m == st else Hb[:, m].sum()
                            series.append({"modulo": "Especiais", "grupo_banco": b, "mes": _ultimo_dia(m)[:7],
                                           "saldo_estimado": tot, "saldo_est_min": tot, "saldo_est_max": tot,
                                           "tipo": "reconstituído"})
                        else:
                            tot = projetar(s_cred, Rb, st, m, base_st).sum() + congelado
                            lo_m, hi_m = faixa(m - st)
                            series.append({"modulo": "Especiais", "grupo_banco": b, "mes": _ultimo_dia(m)[:7],
                                           "saldo_estimado": tot, "saldo_est_min": tot / (1 + hi_m),
                                           "saldo_est_max": tot / (1 + lo_m), "tipo": "projetado (extrato parado)"})
                base[s_cred] = np.where(tem_pub[s_cred], BASE_PARADO_ANCORA, BASE_PARADO_NOVA)
            parada[sel] = ult_banco[b].strftime("%Y-%m-%d")
            s_sem = sel & ~tem_cred
            base[s_sem] = np.where(tem_pub[s_sem], BASE_SEM_COMO, "sem saldo publicado")
        elif b not in ult_m and (sel & tem_cred).any() and frescos:
            # banco que nunca publicou extrato (sem nenhum débito conhecido): débito zero NÃO é "não gastou".
            # Projeta os créditos pela curva média dos bancos que publicam, com a faixa geral dos testes.
            s_cred = sel & tem_cred
            pool = tem_cred & np.isin(banco, frescos)
            Hp = historico(pool, M)
            Rp = curva(pool, Hp, M - 1)
            if Rp is not None:
                v = projetar(s_cred, Rp, 0, M - 1, np.zeros(s_cred.sum()))
                lo, hi = faixa(12)
                est[s_cred], est_min[s_cred], est_max[s_cred] = v, v / (1 + hi), v / (1 + lo)
                base[s_cred] = BASE_NUNCA
                q.append({"teste": f"Estimativa de {b} (nunca publicou extrato)", "parametro":
                          "curva média dos bancos que publicam", "soma_reconstituida": float(v.sum())})
        else:
            # banco que publica: o saldo é o publicado; conta com crédito e sem saldo publicado é reconstituída
            s_rec = sel & tem_cred & ~tem_pub
            if s_rec.any():
                v, _ = _simular(C[s_rec], D[s_rec], r, np.full(s_rec.sum(), M), 0.0, fim[s_rec])
                est[s_rec] = est_min[s_rec] = est_max[s_rec] = v
                base[s_rec] = BASE_RECONST
            s_cred = sel & tem_cred
            if s_cred.any() and b in ult_m:
                _, ser = _simular(C[s_cred], D[s_cred], r, np.full(s_cred.sum(), M), 0.0, fim[s_cred])
                for m in range(M):
                    series.append({"modulo": "Especiais", "grupo_banco": b, "mes": _ultimo_dia(m)[:7],
                                   "saldo_estimado": ser[m], "saldo_est_min": ser[m], "saldo_est_max": ser[m],
                                   "tipo": "reconstituído"})
    out = pd.DataFrame({"id_agencia_conta": keys, "grupo_banco": banco, "saldo_publicado": pub,
                        "data_saldo": contas_u["data_saldo"].dt.strftime("%Y-%m-%d").values,
                        "saldo_estimado": est, "saldo_est_min": est_min, "saldo_est_max": est_max,
                        "base_saldo": base, "extrato_parado_em": parada,
                        "creditos_apos_parada": [C[i, ult_m.get(b, M) + 1:].sum() if b in paradas_b else 0.0
                                                 for i, b in enumerate(banco)]})
    if sem_conta:
        q.append({"teste": "Ordens bancárias sem conta identificada (fora da reconstituição)",
                  "parametro": f"R$ {sem_conta:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")})
    q.append({"teste": "Mês de referência da estimativa", "parametro": ref.strftime("%m/%Y")})
    return {"contas": out, "serie": pd.DataFrame(series), "qualidade": pd.DataFrame(q)}


def aplicar(fato_conta: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    """Leva as colunas estimadas para o fato de contas, na mesma linha que guarda o saldo da conta (as linhas
    repetidas da conta ficam com zero, como o saldo). Contas fora das Especiais: estimado = publicado."""
    fc = fato_conta.copy()
    s = pd.to_numeric(fc["saldo"], errors="coerce").fillna(0.0)
    fc["saldo_estimado"], fc["saldo_est_min"], fc["saldo_est_max"] = s, s, s
    fc["base_saldo"] = np.where(s != 0, BASE_PUBLICADO, None)
    fc["extrato_parado_em"] = None
    if rec is None or rec.empty:
        return fc
    esp = fc["modulo"] == "Especiais"
    prim = esp & ~fc.duplicated(["modulo", "id_agencia_conta"])
    r = rec.set_index("id_agencia_conta")
    k = fc.loc[prim, "id_agencia_conta"]
    for col in ("saldo_estimado", "saldo_est_min", "saldo_est_max"):
        fc.loc[prim, col] = k.map(r[col]).fillna(s[prim]).values
        fc.loc[esp & ~prim, col] = 0.0
    fc.loc[esp, "base_saldo"] = fc.loc[esp, "id_agencia_conta"].map(r["base_saldo"]).values
    fc.loc[esp, "extrato_parado_em"] = fc.loc[esp, "id_agencia_conta"].map(r["extrato_parado_em"]).values
    return fc
