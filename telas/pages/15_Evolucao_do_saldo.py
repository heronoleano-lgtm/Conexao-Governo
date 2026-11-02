import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.semantica import cor_banco, nome_modalidade  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao  # noqa: E402

ctx = pagina("Evolução do saldo",
             "Variação da custódia no dia, na semana, no mês e no ano, por banco, modalidade, UF e ente. "
             "A série é gravada a cada carga diária (repositório de dados).")
d = ctx.d
ev, vb = d["mart_evolucao_saldo"], d["mart_variacao_banco"]
dias = ev["dia"].nunique() if not ev.empty else 0
if dias < 2:
    st.info(f"A série diária começou a ser gravada: {dias} dia(s) até agora. As variações aparecem a partir da "
            "segunda carga; semana, mês e ano ficam completos conforme o histórico acumula.")

vb = q.filtrar(vb, ctx.modulos, None, None)
tot = vb.groupby("grupo_banco")[[c for c in vb.columns if c.startswith(("saldo", "var_")) and not c.endswith("_pct")]].sum()
cx = tot.loc["CAIXA"] if "CAIXA" in tot.index else pd.Series(dtype=float)


def _var(per):
    ant = cx.get(f"saldo_{per}_anterior")
    v = cx.get(f"var_{per}")
    if ant is None or pd.isna(ant) or not ant:
        return "—", "sem base de comparação"
    return f"{'+' if v >= 0 else ''}{q.brl(v)}", f"{v / ant:+.1%}".replace(".", ",")


_ct = ctx.f("fato_conta", anos=False)
cards = [ui.cartao_saldo_de("Custódia CAIXA hoje", _ct[_ct["grupo_banco"] == "CAIXA"] if not _ct.empty else _ct)]
for per, nome in (("dia", "no dia"), ("semana", "em 7 dias"), ("mes", "em 30 dias"), ("ano", "em 1 ano")):
    val, sub = _var(per)
    cards.append({"rotulo": f"Variação {nome}", "valor": val, "sub": sub,
                  "cor": "#00A19A" if (cx.get(f"var_{per}") or 0) >= 0 else "#D1495B"})
cartoes(cards)

sr = d.get("mart_saldo_reconstituido", pd.DataFrame())


def _teto(banco):
    rq = d.get("mart_reconstituicao_qualidade", pd.DataFrame())
    if rq is None or rq.empty:
        return None
    x = rq[rq["teste"].astype(str).str.startswith(f"Teto medido de {banco}")]
    return float(x["soma_reconstituida"].iloc[0]) if not x.empty else None
if sr is not None and not sr.empty and (not ctx.modulos or "Especiais" in ctx.modulos):
    secao("Transferências Especiais: saldo reconstituído mês a mês (regra SAL-01)",
          "Linha cheia: reconstituído com o extrato publicado (créditos − saídas + rendimento). Tracejada: estimado "
          "depois que o extrato parou, com a faixa de incerteza sombreada. Linha laranja: o último saldo publicado.")
    mc = d.get("mart_custodia", pd.DataFrame())
    par = {}
    if not mc.empty and "extrato_parado_em" in mc:
        for r in mc[(mc["modulo"] == "Especiais") & mc["extrato_parado_em"].notna() & (mc["saldo"] > 0)].itertuples():
            dt = pd.to_datetime(r.data_saldo_max, errors="coerce")
            par[r.grupo_banco] = (dt.strftime("%d/%m/%Y") if pd.notna(dt) else "?", r.saldo)
    g.saldo_reconstituido(sr, "evol_rec", cores={b: cor_banco(b) for b in sr["grupo_banco"].unique()}, paradas=par,
                          desde="2022-01")
    for b, (quando, valor) in par.items():
        x = sr[(sr["grupo_banco"] == b)].sort_values("mes").iloc[-1]
        leitura(f"{b}: parado × estimado", [
            f"<b>Parado:</b> {q.brl(valor)} é o último saldo publicado, de {quando}. Desde então o extrato não chega.",
            f"<b>Estimado hoje ({x['mes']}):</b> ≈ {q.brl(x['saldo_estimado'])}, faixa de {q.brl(x['saldo_est_min'])} a "
            f"{q.brl(x['saldo_est_max'])}. Entram os créditos publicados depois da parada (ordens bancárias) e saem as "
            "saídas estimadas pela curva de execução do próprio banco medida antes da parada.",
            (lambda t: f"<b>Teto medido:</b> {q.brl(t)} — o saldo parado mais tudo o que foi creditado depois, sem "
                       "nenhuma saída. O saldo real está abaixo disso." if t else "")(
                _teto(b)),
            "Como a estimativa foi testada: veja Qualidade e auditoria › Atualização das fontes."])

secao("Saldo ao longo do tempo")
c1, c2 = st.columns([1, 3])
freq = c1.radio("Período", ["Diário", "Semanal", "Mensal"], horizontal=False)
quebra = c1.radio("Separar por", ["Banco", "Modalidade"], horizontal=False)
e = q.filtrar(ev, ctx.modulos, None, None)
if not e.empty:
    e = e.assign(_p=pd.to_datetime(e["dia"]).dt.to_period({"Diário": "D", "Semanal": "W", "Mensal": "M"}[freq]).astype(str))
    ult = e.groupby("_p")["dia"].transform("max")
    e = e[e["dia"] == ult]
    cor = "grupo_banco" if quebra == "Banco" else "modulo"
    e = e.assign(modulo=e["modulo"].map(lambda m: nome_modalidade(m, True)))
    with c2:
        g.linha_tempo(e.groupby(["_p", cor], as_index=False)["saldo"].sum(), "_p", "saldo", chave="evol_linha",
                      cor_por=cor, cores={b: cor_banco(b) for b in e["grupo_banco"].unique()}, altura=380)

secao("Variação por UF", "Saldo CAIXA: comparação com 30 dias atrás.")
vu = d["mart_variacao_uf"]
vu = vu[vu["grupo_banco"] == "CAIXA"] if not vu.empty else vu
if ctx.ufs and not vu.empty:
    vu = vu[vu["uf"].isin(ctx.ufs)]
if not vu.empty and vu["var_mes"].notna().any():
    g.barras(vu.sort_values("var_mes"), "uf", {"var_mes": "Variação em 30 dias"}, chave="evol_uf", altura=340)
else:
    st.caption("Variação por UF aparece quando houver 30 dias de série.")

secao("Entes que mais ganharam e perderam saldo na CAIXA")
ve = d["mart_variacao_ente"]
ve = q.filtrar(ve[ve["grupo_banco"] == "CAIXA"], ctx.modulos, None, ctx.ufs) if not ve.empty else ve
per = st.radio("Comparar com", ["dia anterior", "7 dias", "30 dias", "1 ano"], horizontal=True, index=2)
col = {"dia anterior": "var_dia", "7 dias": "var_semana", "30 dias": "var_mes", "1 ano": "var_ano"}[per]
if ve.empty or ve[col].isna().all():
    st.caption("Ainda sem base de comparação para esse período.")
else:
    a, b = st.columns(2)
    cols = ["nome_ente", "uf", "modulo", "saldo", col, f"{col}_pct"]
    with a:
        st.markdown("**Maiores quedas**")
        g.grade(ve.nsmallest(50, col)[cols], chave="evol_quedas", altura=360)
    with b:
        st.markdown("**Maiores altas**")
        g.grade(ve.nlargest(50, col)[cols], chave="evol_altas", altura=360)
    quedas = ve[ve[col] < 0]
    leitura("Leitura", [f"{len(quedas):,} entes perderam saldo na CAIXA ({q.brl(-quedas[col].sum())}) na comparação com {per}.".replace(",", ".")])
baixar("evolucao_saldo", {"serie": ev, "variacao_banco": vb, "variacao_ente": ve})
