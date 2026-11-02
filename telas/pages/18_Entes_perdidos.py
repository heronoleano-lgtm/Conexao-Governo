import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.semantica import cor_banco  # noqa: E402
from custodia.ui import baixar, cartoes, leitura, mapa_coropletico, pagina, secao  # noqa: E402

ctx = pagina("Entes perdidos",
             "Entes que já escolheram a CAIXA e, no último ano com instrumentos, não colocaram nada na CAIXA "
             "(regra PER-01, olhando até 5 anos). Para quem foram, desde quando, quanto e quanto daria para reconquistar. "
             "É mais amplo que a 'troca da CAIXA' da tela Concorrência, que compara só os dois últimos anos.")
d = ctx.d
pd_ = d["mart_entes_perdidos"].copy()
if ctx.ufs and not pd_.empty:
    pd_ = pd_[pd_["uf"].isin(ctx.ufs)]
if pd_.empty:
    st.success("Nenhum ente perdido pelas regras com os filtros atuais.")
    st.stop()
rec = pd_[pd_["anos_sem_caixa"] <= 2]
cartoes([
    {"rotulo": "Entes perdidos", "valor": f"{len(pd_):,}".replace(",", "."), "cor": "#D1495B"},
    {"rotulo": "Foi para o concorrente desde então", "valor": q.brl(pd_["valor_concorrente_depois"].sum())},
    {"rotulo": "Saldo hoje no concorrente", "valor": q.brl(pd_["saldo_concorrente"].sum()), "cor": "#F39200"},
    {"rotulo": "Potencial de reconquista", "valor": q.brl(pd_["potencial_custodia"].sum()), "cor": "#00A19A"},
    {"rotulo": "Perdidos há até 2 anos", "valor": f"{len(rec):,}".replace(",", "."), "sub": "relação ainda recente",
     "cor": "#005CA9"},
])
c1, c2 = st.columns([3, 2])
with c1:
    secao("Onde estão", "Bolhas = entes perdidos (tamanho = valor no concorrente; cor = banco atual).")
    er = d["mart_ente_resumo"]
    b = pd_.merge(er[["cnpj_ente", "lat", "lon", "part_caixa", "banco_principal"]], on="cnpj_ente", how="left")
    b = b.assign(valor=b["valor_concorrente_depois"], acao_recomendada="Reconquista")
    uf = q.territorio(d, "UF", None, None, None, set(pd_["cnpj_ente"]))
    mapa_coropletico(uf, q.malha("BR"), "valor_concorrente", "brl", "Reds", chave="perd_mapa", altura=500,
                     bolhas=b, cor_bolha="banco_atual", tam_bolha="valor")
with c2:
    secao("Para quem foram")
    pb = pd_.groupby("banco_atual", as_index=False).agg(entes=("cnpj_ente", "count"),
                                                        valor_concorrente_depois=("valor_concorrente_depois", "sum"))
    g.barras(pb, "banco_atual", {"entes": "Entes"}, chave="perd_banco", formato="int", altura=220,
             cores={"Entes": "#D1495B"})
    secao("Desde quando")
    pa = pd_.groupby("ultimo_ano_caixa", as_index=False).agg(entes=("cnpj_ente", "count"),
                                                             valor=("valor_concorrente_depois", "sum"))
    g.barras(pa.assign(ultimo_ano_caixa=pa["ultimo_ano_caixa"].astype(str)), "ultimo_ano_caixa",
             {"valor": "Valor no concorrente depois"}, chave="perd_ano", altura=220, cores={"Valor no concorrente depois": "#8C1D40"})

leitura("Por onde começar", [
    f"<b>{len(rec):,}</b> entes saíram há até 2 anos: a relação com a agência ainda é recente.".replace(",", "."),
    "Cruze com o Assessor do ente para ver o que mudou (parlamentar, área, pagamentos) e o argumento de retorno."])
secao("Lista de reconquista", "Clique numa linha para abrir o ente no Assessor.")
sel = g.grade(pd_.sort_values("potencial_custodia", ascending=False), chave="perd_lista", selecao=True)
if sel and sel.get("cnpj_ente"):
    ui.abrir(f"Abrir {sel.get('nome_ente', 'ente')} no Assessor", ui.TELA_ENTE, ("ente_visao", "Assessor da visita"),
            {ui.ENTE: sel["cnpj_ente"]}, chave="perd_abrir")
baixar("entes_perdidos", {"perdidos": pd_})
