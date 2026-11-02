import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import auditoria_profunda as apf  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, pagina, secao, tabela  # noqa: E402

ctx = pagina("Auditoria profunda",
             "Cada número-chave refeito por um caminho independente (SQL), testes estatísticos (Benford, extremos, "
             "duplicidades) e uma rede neural que aponta entes com combinação atípica de números. Roda em toda carga.",
             filtros=False)
d = ctx.d
aud = d.get("mart_auditoria_profunda", pd.DataFrame())
if aud is None or aud.empty:
    st.info("A auditoria profunda roda na carga diária. Rode carga_diaria.bat para gerar a primeira.")
    st.stop()

cont = aud["status"].value_counts()
cartoes([{"rotulo": "Checagens", "valor": len(aud)},
         {"rotulo": "OK", "valor": int(cont.get("ok", 0)), "cor": "#00A19A"},
         {"rotulo": "Atenção", "valor": int(cont.get("atenção", 0)), "cor": "#F39200"},
         {"rotulo": "Críticas", "valor": int(cont.get("crítico", 0)), "cor": "#D1495B"}])
crit = aud[aud["status"] == "crítico"]
leitura("Como ler", [
    "<b>Conferência independente</b>: o mesmo número calculado em pandas (o painel) e em SQL (outro motor). Se diferem, "
    "um dos dois está errado e a tela que usa esse número fica sob suspeita.",
    "<b>Benford</b>: em pagamentos e lançamentos, um 1º dígito fora do padrão pede olhar (valores repetidos, "
    "lançamentos manuais). Em valores por fórmula (FPM, emendas redondas) o desvio é esperado e só informativo.",
    "<b>Rede neural</b>: é validada a cada carga com anomalias plantadas e com 5 inicializações diferentes; a lista de "
    "entes atípicos é para conferência humana — pode ser erro de dado ou oportunidade real.",
    f"<b>{len(crit)} checagem(ns) crítica(s)</b>: " + "; ".join(crit["checagem"].head(5)) if len(crit) else ""])

for fam in ["Conferência independente", "Possíveis duplicidades", "Extremos robustos", "Benford (1º dígito)", "Rede neural"]:
    x = aud[aud["familia"] == fam]
    if x.empty:
        continue
    secao(fam)
    tabela(x.drop(columns=["familia"]), chave=f"apf_{fam}")

secao("Benford: observado × esperado", "Proporção de valores por 1º dígito numa tabela escolhida.")
op = {"Pagamentos (Especiais)": ("fato_pagamento", "Especiais"), "Pagamentos (Fundo a Fundo)": ("fato_pagamento", "Fundo a Fundo"),
      "Lançamentos (Especiais)": ("fato_fluxo", "Especiais"), "Instrumentos (Discricionárias)": ("fato_instrumento", "Discricionárias")}
esc = st.selectbox("Tabela", list(op), key="apf_benford")
t, m = op[esc]
df = d.get(t, pd.DataFrame())
if df is not None and not df.empty:
    b = apf.benford(df.loc[df["modulo"] == m, "valor"] if "modulo" in df else df["valor"])
    if b.get("obs"):
        bd = pd.DataFrame({"digito": [str(i) for i in range(1, 10)], "observado": b["obs"], "esperado": b["esperado"]})
        g.barras(bd, "digito", {"observado": "Observado", "esperado": "Benford"}, chave="apf_bd", formato="pct",
                 empilhado=False, altura=320)
        st.caption(f"{b['classe']} · desvio médio (MAD) {b['mad']:.4f} · {b['n']:,} valores".replace(",", "."))

an = d.get("mart_anomalias_entes", pd.DataFrame())
if an is not None and not an.empty:
    secao("Entes com perfil atípico (rede neural)", "Ordenados pelo escore de anomalia. 'Explicação' mostra o que a rede "
                                                    "menos conseguiu reconstruir. Selecione para abrir a Visão 360.")
    sel = g.grade(an, chave="apf_anom", selecao=True, altura=460)
    if sel and sel.get("cnpj_ente"):
        ui.abrir("Abrir na Visão 360", ui.TELA_ENTE, ("ente_visao", "360 · CRM"), {ui.ENTE: sel["cnpj_ente"]},
                 chave="apf_v360")
ext = d.get("mart_extremos", pd.DataFrame())
if ext is not None and not ext.empty:
    secao("Instrumentos de valor extremo", "Valor muito acima do típico da modalidade (z robusto > 6): conferir se é "
                                           "obra grande legítima ou erro de digitação na fonte.")
    tabela(ext, chave="apf_ext")
baixar("auditoria_profunda", {"checagens": aud, "anomalias": an, "extremos": ext})
