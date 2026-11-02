import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia import normaliza  # noqa: E402
from custodia.marts_outras import doze_meses  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, mapa_coropletico, pagina, rosca, secao  # noqa: E402

FONTES = {
    "FUNDEB": ("Educação · FUNDEB", "#7A4EAB", "Tesouro Nacional", False),
    "FPM": ("FPM", "#5B6573", "Tesouro Nacional", False),
    "FNS": ("Saúde · FNS", "#0F9D8A", "Fundo Nacional de Saúde", True),
    "FNDE": ("Educação · FNDE", "#F39200", "Portal da Transparência", False),
    "FNAS": ("Assistência social · FNAS", "#D1495B", "Portal da Transparência", False),
}
BANCO = {"CAIXA": "#005CA9", "BB": "#F2C500"}

ctx = pagina("Outros repasses federais",
             "FUNDEB, FPM, saúde (FNS), educação (FNDE) e assistência social (FNAS) por município. Só a saúde publica "
             "o banco e o saldo da conta; as demais fontes mostram o volume (regras OUT-01, OUT-02 e SAU-01).")
d = ctx.d
fato = q.filtrada(d, "fato_repasse_outros", None, None, ctx.ufs or None)
if (fato is None or fato.empty) and not ctx.ufs:
    st.info("Os outros repasses ainda não foram carregados. Eles entram na próxima carga diária "
            "(bloco outras_fontes em config/config.yaml).")
    st.stop()
f12 = q.outros_doze_meses(d, ctx.ufs or None)
contas = d.get("fato_conta_saude", pd.DataFrame())
if ctx.ufs and not contas.empty:
    contas = contas[contas["uf"].isin(ctx.ufs)]

# ---------------------------------------------------------------- cartões por fonte
itens = []
for fonte, (nome, cor, origem, tem_banco) in FONTES.items():
    x = f12[f12["fonte"] == fonte]
    if x.empty:
        continue
    per = (x["ano"] * 100 + x["mes"]).astype(int)
    n_mun = x["cod_ibge"].dropna().nunique()
    sub = ((f"{n_mun:,} municípios".replace(",", ".") if n_mun else "município não identificado na fonte")
           + f" · até {per.max() % 100:02d}/{per.max() // 100}")
    if tem_banco:
        cx = x.loc[x["grupo_banco"] == "CAIXA", "valor"].sum()
        sub = f"{q.pct(cx / x['valor'].sum())} na CAIXA · " + sub
    n_meses = int(per.nunique())        # a fonte pode ter menos de 12 meses (FNS: só o ano corrente)
    itens.append({"rotulo": f"{nome} · {'12 meses' if n_meses >= 12 else f'{n_meses} meses'}",
                  "valor": q.brl(x["valor"].sum()), "cor": cor, "sub": sub})
cartoes(itens)
st.caption("FUNDEB e FPM: Tesouro Nacional. Saúde: Consulta FNS (com banco e saldo). Educação e assistência: Portal da "
           "Transparência. O banco das contas do FUNDEB, FNDE e FNAS não é publicado em fonte aberta.")

# ---------------------------------------------------------------- saúde: CAIXA x BB
secao("Saúde: em que banco cai o dinheiro", "Repasses do FNS em 12 meses e o último saldo publicado de cada conta.")
s12 = f12[f12["fonte"] == "FNS"]
if s12.empty:
    st.info("Sem repasses do FNS com os filtros atuais.")
else:
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        rosca(s12.groupby("grupo_banco")["valor"].sum(), chave="out_saude_rep", titulo="Repasses 12 meses",
                cores=BANCO, altura=280)
    with c2:
        if not contas.empty and "saldo" in contas:
            rosca(contas.groupby("grupo_banco")["saldo"].sum(), chave="out_saude_saldo", titulo="Saldo em conta",
                    cores=BANCO, altura=280)
        else:
            st.caption("Saldo das contas ainda não consultado (outras_fontes.fns.saldo em config.yaml).")
    with c3:
        pu = s12.groupby(["uf", "grupo_banco"])["valor"].sum().unstack(fill_value=0)
        pu = pu.assign(total=pu.sum(axis=1)).sort_values("total", ascending=False).head(15).reset_index()
        series = {b: b for b in ("CAIXA", "BB") if b in pu}
        if series:
            g.barras(pu, "uf", series, chave="out_saude_uf", altura=300, cores=BANCO)
    tot = s12["valor"].sum()
    cx = s12.loc[s12["grupo_banco"] == "CAIXA", "valor"].sum()
    n_s = int((s12["ano"] * 100 + s12["mes"]).nunique())
    janela = "Nos últimos 12 meses" if n_s >= 12 else f"Nos {n_s} meses publicados (a fonte só traz o ano corrente)"
    linhas = [f"{janela} o FNS repassou <b>{q.brl(tot)}</b>; <b>{q.pct(cx / tot if tot else 0)}</b> "
              "foram creditados em conta CAIXA."]
    if not contas.empty and "saldo" in contas:
        sc = contas.loc[contas["grupo_banco"] != "CAIXA", "saldo"].sum()
        sx = contas.loc[contas["grupo_banco"] == "CAIXA", "saldo"].sum()
        dts = normaliza.data(contas["data_saldo"]) if "data_saldo" in contas else pd.Series(pd.NaT, index=contas.index)
        dt = dts.max()
        # conciliação 01/11: parte das contas tem saldo de anos atrás (ex.: 29/10/2021); a data mais recente
        # não vale para todas
        antigas = contas[dts < dt - pd.Timedelta(days=62)] if pd.notna(dt) else contas.iloc[0:0]
        quando = f" (saldo mais recente de {dt:%d/%m/%Y})" if pd.notna(dt) else ""
        linhas.append(f"Saldo parado nas contas de saúde: <b>{q.brl(sx)}</b> na CAIXA e <b>{q.brl(sc)}</b> no "
                      f"concorrente{quando}.")
        if len(antigas):
            n_ant = f"{len(antigas):,}".replace(",", ".")
            linhas.append(f"{n_ant} contas têm saldo de data antiga (somam {q.brl(antigas['saldo'].sum())}): "
                          "a fonte não atualizou essas contas.")
        if "bloco" in contas and pd.to_numeric(contas["bloco"], errors="coerce").max() < 10:
            linhas.append("<b>O saldo publicado é de contas antigas:</b> a lista de contas e saldos do FNS traz só os "
                          "blocos de financiamento anteriores a 2018 (códigos 1 a 8), enquanto os repasses de hoje caem "
                          "nas contas dos blocos de Manutenção e de Estruturação (10 e 11) — as duas listas têm "
                          "pouquíssimas contas em comum. O saldo mostrado é o que sobrou nas contas antigas, não a "
                          "custódia do dinheiro que entra agora; por isso a participação CAIXA no saldo (quase zero) não "
                          "mede a custódia da saúde. A participação nos repasses é a medida confiável.")
    linhas.append("O FNS abre a conta no BB ou na CAIXA. A possibilidade de o ente pedir a conta na CAIXA deve ser "
                  "validada com o jurídico e a conformidade (premissa da regra SAU-01).")
    leitura("Leitura", linhas)

# ---------------------------------------------------------------- mapa
secao("Onde está o dinheiro", "Escolha a métrica. O mapa soma os 12 últimos meses por UF; as bolhas são municípios.")
mun = d.get("mart_outras_municipio", pd.DataFrame())
if ctx.ufs and not mun.empty:
    mun = mun[mun["uf"].isin(ctx.ufs)]
metricas = {"Todos os repasses": None, "FUNDEB": "fundeb_12m", "FPM": "fpm_12m", "Saúde": "saude_12m",
            "Educação (FNDE)": "educacao_12m", "Assistência social": "assistencia_12m",
            "Saldo saúde no concorrente": "saldo_saude_concorrente"}
# só métricas com dado: fonte ausente ou sem município não vira mapa de zeros (red team 02/11)
metricas = {k: v for k, v in metricas.items() if v is None or (not mun.empty and v in mun and mun[v].notna().any())}
fora = [n for n, c in {"FUNDEB": "fundeb_12m", "FPM": "fpm_12m", "Saúde": "saude_12m", "Educação (FNDE)": "educacao_12m",
                       "Assistência social": "assistencia_12m"}.items() if c not in mun or not mun[c].notna().any()] \
    if not mun.empty else []
if fora:
    st.caption("Sem dado por município nesta carga: " + ", ".join(fora) + " (fonte não carregada ou sem município "
               "identificado). Não aparecem como zero.")
esc = st.radio("Métrica", list(metricas), horizontal=True, key="out_metrica")
if not mun.empty:
    m = mun.copy()
    soma = [c for c in ("fundeb_12m", "fpm_12m", "saude_12m", "educacao_12m", "assistencia_12m") if c in m]
    m["valor"] = m[soma].sum(axis=1, min_count=1) if metricas[esc] is None else m[metricas[esc]]
    m["cod_ibge"] = m["cod_ibge"].astype(str)
    uf = m.assign(codarea=m["cod_ibge"].str[:2]).groupby("codarea", as_index=False).agg(nome=("uf", "first"),
                                                                                        valor=("valor", "sum"))
    er = d.get("mart_ente_resumo", pd.DataFrame())
    bolhas = None
    if not er.empty and {"cod_ibge", "lat", "lon"} <= set(er.columns):
        geo = er.dropna(subset=["lat", "lon"]).assign(cod_ibge=lambda x: x["cod_ibge"].astype(str)) \
                .drop_duplicates("cod_ibge")[["cod_ibge", "lat", "lon"]]
        bolhas = m.merge(geo, on="cod_ibge", how="inner").assign(cnpj_ente=lambda x: x["cod_ibge"],
                                                                 nome_ente=lambda x: x["municipio"],
                                                                 part_caixa=lambda x: x["part_caixa_saude"])
        bolhas = bolhas.nlargest(800, "valor")
    mapa_coropletico(uf, q.malha("BR"), "valor", "brl", "Purples", chave="out_mapa", altura=520, bolhas=bolhas,
                     cor_bolha=None)

# ---------------------------------------------------------------- oportunidades
secao("Fundos de saúde com saldo no concorrente", "Regra SAU-01: saldo acima do mínimo em conta do FNS fora da CAIXA. "
                                                   "É saldo remanescente das contas dos blocos antigos (ver acima).")
op = d.get("mart_oport_saude", pd.DataFrame())
if ctx.ufs and not op.empty:
    op = op[op["uf"].isin(ctx.ufs)]
if op.empty:
    st.info("Nenhum fundo de saúde acima do mínimo com os filtros atuais.")
else:
    cartoes([{"rotulo": "Fundos com saldo no concorrente", "valor": f"{len(op):,}".replace(",", "."),
              "sub": f"{op['uf'].nunique()} UFs"},
             {"rotulo": "Saldo no concorrente", "valor": q.brl(op["saldo_concorrente"].sum()), "cor": "#D1495B"},
             {"rotulo": "Desses, já têm conta CAIXA", "valor": f"{(op['saldo_caixa'] > 0).sum():,}".replace(",", "."),
              "sub": "relacionamento já existe", "cor": "#005CA9"}])
    g.grade(op.rename(columns={"favorecido": "nome_ente"}), chave="out_oport", altura=420)

# ---------------------------------------------------------------- ranking por município
secao("Municípios", "Repasses de 12 meses por área e a custódia da saúde.")
if not mun.empty:
    g.grade(mun.sort_values("saude_12m", ascending=False).rename(columns={"municipio": "nome_ente"}),
            chave="out_mun", altura=440)

secao("Evolução mensal", "Valor repassado por mês e por fonte.")
ev = q.outros_por_mes(d, ctx.ufs or None)
series = {f: FONTES[f][0] for f in FONTES if f in ev}
if series:
    g.barras(ev, "periodo", series, chave="out_evol", altura=340,
             cores={FONTES[f][0]: FONTES[f][1] for f in series})
    tot = ev[list(series)].sum(axis=1)
    if len(tot) >= 4 and tot.iloc[-1] < .7 * tot.iloc[-4:-1].median():
        st.caption(f"O último mês ({ev['periodo'].iloc[-1]}) parece incompleto: soma {q.pct(tot.iloc[-1] / tot.iloc[-4:-1].median())} "
                   "da média dos três anteriores. Os repasses do Tesouro saem em parcelas (decêndios) e o mês só fecha "
                   "no fim: a queda no último ponto não é queda de repasse.")
baixar("outros_repasses", {"municipios": mun, "oportunidades_saude": op, "contas_saude": contas, "repasses": f12})
