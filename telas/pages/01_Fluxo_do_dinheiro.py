import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import analise_fluxo as af  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.semantica import CAIXA_AZUL, cor_banco, nome_modalidade  # noqa: E402
from custodia.ui import (baixar, barras_modalidade, cartoes, leitura, pagina, ranking, resumo_detalhe,  # noqa: E402
                         sankey, secao, tabela)

ctx = pagina("Fluxo do dinheiro",
             "O caminho do dinheiro em três etapas: de onde vem, em que banco fica guardado e para onde vai quando sai "
             "da conta. Cada etapa explica os números e confere as somas (nada é perdido nem contado duas vezes). "
             "Clique nas barras para filtrar.")
d = ctx.d
F = af.filtros_ctx(ctx)
etapa = st.radio("Etapa", ["1 · De onde vem", "2 · Onde fica (custódia)", "3 · Para onde vai"], horizontal=True,
                 label_visibility="collapsed", key="fluxo_etapa")


def conferencia(ok: bool, texto: str) -> None:
    st.markdown(f"<div class='cx-tab-info'>{'✔' if ok else '⚠'} Conferência: {texto}</div>", unsafe_allow_html=True)


# ================================================================ 1 · de onde vem
if etapa.startswith("1"):
    o = af.origem(d, F)
    if not o:
        st.info("Sem instrumentos com os filtros atuais.")
        st.stop()
    t = o["tabela"]
    cartoes([{"rotulo": "Valor contratado", "valor": q.brl(o["total"])},
             {"rotulo": "Órgãos de origem", "valor": len(t)},
             {"rotulo": "Maior origem", "valor": str(t.iloc[0]["orgao"])[:28], "sub": q.brl(t.iloc[0]["valor"])},
             {"rotulo": "3 maiores órgãos", "valor": q.pct(o["top3"]), "sub": "do valor total",
              "ajuda": "Concentração: quanto do dinheiro vem dos três maiores órgãos"},
             {"rotulo": "Com emenda parlamentar", "valor": q.pct(o["com_emenda"]), "sub": "dos instrumentos"},
             {"rotulo": "Vai para conta do concorrente", "valor": q.brl(t["valor_concorrente"].sum()), "cor": "#F39200",
              "sub": "dinheiro com banco definido fora da CAIXA"}])
    leitura("O que os números dizem", af.leitura_origem(o, q.brl, q.pct))
    conferencia(o["confere"], "Σ por órgão = Σ por modalidade = valor transferido.")

    secao("Do órgão à modalidade", "Largura = valor. Os 12 maiores órgãos aparecem; o resto fica em 'Demais órgãos'.")
    instr = ctx.f("fato_instrumento")
    top = set(t["orgao"].head(12))
    e = instr.assign(origem=np.where(instr["orgao"].isin(top), instr["orgao"], "Demais órgãos"),
                     destino=instr["modulo"].map(lambda m: nome_modalidade(m, True))) \
        .groupby(["origem", "destino"], as_index=False)["valor"].sum()
    sankey(e, altura=520, chave="fluxo_1")

    c1, c2 = st.columns(2)
    with c1:
        ranking(t, "valor", "brl", n=15, titulo="Órgãos por valor transferido (clique para filtrar)", rotulo="orgao",
                filtro="orgao", valores="orgao", chave="fluxo_org")
    with c2:
        ranking(t, "valor_concorrente", "brl", n=15, titulo="Órgãos que mais levam dinheiro ao concorrente",
                rotulo="orgao", filtro="orgao", valores="orgao", chave="fluxo_org_conc")
    secao("Ao longo dos anos", "Valor por ano de origem e modalidade. Clique num ano para filtrar.")
    pa = o["por_ano"].stack().rename("valor").reset_index()
    barras_modalidade(pa, "ano", titulo="Valor por ano e modalidade", ordenar=False)
    secao("Órgãos e programas", "À esquerda, um órgão por linha; escolha um órgão para ver os programas dele.")
    resumo_detalhe(o["programas"], "orgao", "fluxo_orgprog", titulo_detalhe="Programas do órgão")
    with st.expander("Tabela completa por órgão (banco, CAIXA, concorrente, emendas)"):
        tabela(t[["orgao", "valor", "part_do_total", "valor_caixa", "valor_concorrente", "part_caixa", "instrumentos",
                  "entes", "com_emenda"]], chave="fluxo_org_tab")
    baixar("fluxo_origem", {"orgaos": t, "programas": o["programas"]})

# ================================================================ 2 · onde fica
elif etapa.startswith("2"):
    cu = af.custodia(d, F)
    if not cu:
        st.info("Sem instrumentos com os filtros atuais.")
        st.stop()
    b = cu["bancos"].set_index("grupo_banco")
    cx = b.loc["CAIXA"] if "CAIXA" in b.index else pd.Series({"valor": 0, "saldo": 0, "part_valor": np.nan,
                                                               "part_saldo": np.nan})
    cartoes([{"rotulo": "Valor nas contas CAIXA", "valor": q.brl(cx["valor"]), "sub": q.pct(cx["part_valor"]),
              "cor": CAIXA_AZUL},
             {"rotulo": "Valor no concorrente", "valor": q.brl(b["valor"].sum() - cx["valor"]), "cor": "#D1495B"},
             ui.cartao_saldo("Saldo hoje na CAIXA", cx["saldo"], cx.get("saldo_estimado"), parado_em=q.parada_saldo(d),
                             sub=f"{q.pct(cx['part_saldo'])} do saldo publicado"),
             ui.cartao_saldo("Saldo hoje no concorrente", b["saldo"].sum() - cx["saldo"],
                             (b["saldo_estimado"].sum() - cx.get("saldo_estimado", 0)) if "saldo_estimado" in b else None,
                             cor="#F39200"),
             {"rotulo": "Sem banco definido", "valor": q.brl(cu["sem_banco"]), "sub": "custódia em aberto", "cor": "#00A19A"}])
    leitura("O que os números dizem", af.leitura_custodia(cu, q.brl, q.pct))
    conferencia(True, f"saldo contado uma vez por conta ({cu['contas_repetidas']:,} linhas repetidas não somadas)."
                .replace(",", "."))

    secao("Da modalidade ao banco da conta", "Em que banco cada modalidade guarda o dinheiro.")
    mb = cu["modalidade_banco"].stack().rename("valor").reset_index()
    e = mb.assign(origem=mb["modulo"].map(lambda m: nome_modalidade(m, True)), destino="Conta " + mb["grupo_banco"])
    c1, c2 = st.columns([3, 2])
    with c1:
        sankey(e[["origem", "destino", "valor"]], altura=420, chave="fluxo_2")
    with c2:
        g.rosca(b["saldo"], "fluxo_2_saldo", "Saldo hoje por banco (clique para filtrar)",
                {x: cor_banco(x) for x in b.index}, altura=380, filtro="grupo_banco")
    secao("Valor × saldo por banco", "Quanto do que foi transferido ainda está na conta (saldo ÷ valor) e há quanto "
                                     "tempo (idade mediana do saldo). Saldo alto e antigo = dinheiro parado.")
    tabela(cu["bancos"], chave="fluxo_bancos")
    secao("Por estado", "Onde a CAIXA guarda e onde o concorrente lidera. Clique numa barra para filtrar o estado.")
    c1, c2 = st.columns(2)
    with c1:
        ranking(cu["uf"], "valor_concorrente", "brl", n=15, titulo="Valor no concorrente por UF", rotulo="uf",
                filtro="uf", valores="uf", chave="fluxo_uf_conc")
    with c2:
        ranking(cu["uf"][cu["uf"]["valor"] > 0], "part_caixa", "pct", n=15, titulo="Menor participação CAIXA",
                rotulo="uf", filtro="uf", valores="uf", chave="fluxo_uf_part", crescente=True)
    secao("Entes com mais dinheiro parado no concorrente", "Saldo de hoje fora da CAIXA, por ente e banco: lista de ação.")
    tabela(cu["entes_concorrente"], chave="fluxo_ent_conc")
    leitura("Contexto", ["O Fundo a Fundo é operado pelo BB por regra: a disputa de custódia está nas Transferências "
                         "Especiais e nos convênios — e na transferência secundária do Fundo a Fundo."])
    baixar("fluxo_custodia", {"bancos": cu["bancos"], "uf": cu["uf"], "entes_concorrente": cu["entes_concorrente"]})

# ================================================================ 3 · para onde vai
else:
    de = af.destino(d, F)
    if not de:
        st.info("Sem lançamentos bancários para os filtros atuais.")
        st.stop()
    pdst = de["por_destino"]
    terc = pdst[[i for i in pdst.index if i.startswith("Recebedor")]].sum()
    v_cx = pdst.get("Recebedor na CAIXA", 0)
    ini, fim = de["periodo"]
    cartoes([{"rotulo": "Saiu das contas", "valor": q.brl(de["total"]), "sub": f"{ini} a {fim}" if ini else ""},
             {"rotulo": "Pago a terceiros com banco conhecido", "valor": q.brl(terc)},
             {"rotulo": "Recebedores na CAIXA", "valor": q.pct(v_cx / terc) if terc else "—", "sub": q.brl(v_cx),
              "cor": CAIXA_AZUL},
             {"rotulo": "Vazamento das contas CAIXA", "valor": q.brl(de["vazamento"]), "cor": "#D1495B",
              "sub": f"+ {q.brl(de['sem_info_caixa'])} sem banco informado",
              "ajuda": "Saiu de conta CAIXA para recebedor com conta comprovadamente em outro banco. Pagamentos sem o "
                       "banco do recebedor informado ficam à parte (não são vazamento comprovado)"},
             {"rotulo": "Entrada na CAIXA", "valor": q.brl(de["entrada"]), "cor": "#00A19A",
              "sub": "de conta do concorrente para recebedor CAIXA"},
             {"rotulo": "Para conta do próprio ente", "valor": q.brl(pdst.get("Conta do próprio ente", 0))}])
    leitura("O que os números dizem", af.leitura_destino(de, q.brl, q.pct))
    conferencia(de["confere"], "Σ dos destinos = Σ das saídas das contas.")
    cp = de.get("comparavel")
    if cp is not None and not cp.empty and len(cp) > 1:
        secao("CAIXA × BB na mesma janela", f"Pago a terceiros com banco conhecido, {cp['periodo'].iloc[0]} (os 12 meses "
                                            "antes de o extrato CAIXA parar). Retenção = o que fica no banco da conta.")
        tabela(cp.rename(columns={"grupo_origem": "grupo_banco"})[["grupo_banco", "pago_terceiros", "pct_fica_no_banco",
                                                                   "pct_recebedor_caixa"]], chave="fluxo_justo")

    secao("Do banco da conta a quem recebe", "Lançamentos de débito das contas (Transferências Especiais e Fundo a Fundo).")
    sankey(de["tabela"], altura=460, chave="fluxo_3")
    _par = q.paradas_texto(d)
    st.caption((f"Atenção: extrato parado na fonte ({_par}); as saídas dessas contas depois disso não aparecem e "
                "ficam sub-representadas. " if _par else "") + "No Fundo a Fundo a API não informa o banco de quem recebe.")
    secao("Para onde vai, por banco de origem", "Em cada linha, a parte de cada destino (soma 100% por linha).")
    tabela(de["matriz_pct"].reset_index().rename(columns={"origem": "conta"}).rename(
        columns={c: c for c in de["matriz_pct"].columns}), chave="fluxo_matriz")
    secao("Mês a mês", "Saídas por destino ao longo do tempo.")
    pm = de["por_mes"].stack().rename("valor").reset_index().rename(columns={"_m": "mes"})
    if not pm.empty:
        piv = pm.pivot_table(index="mes", columns="destino", values="valor", aggfunc="sum", fill_value=0).reset_index()
        g.barras(piv, "mes", {c: c for c in piv.columns if c != "mes"}, chave="fluxo_mes", titulo="Saídas por mês e destino",
                 altura=380)
    secao("Quem recebe fora da CAIXA", "Recebedores pagos com dinheiro das contas e que têm conta em outro banco "
                                       "(ou banco não informado): relacionamento a construir (domicílio bancário).")
    tabela(de["recebedores_fora"].assign(doc_favorecido=lambda x: x["doc_favorecido"].map(q.cnpj_fmt)),
           chave="fluxo_rec_fora")
    vel = d["mart_velocidade"]
    if not vel.empty:
        with st.expander("Velocidade do pagamento (dias entre empenho e ordem bancária)"):
            tabela(vel)
            st.caption("Dias entre a emissão do empenho e a PRIMEIRA ordem bancária de cada empenho. Contando cada "
                       "ordem bancária (pagamentos parcelados), a mediana fica alguns dias maior. Os empenhos "
                       "saem em poucos lotes por ano, por isso os percentis repetem valores; o prazo depende do lote, "
                       "não do banco.")
    baixar("fluxo_destino", {"origem_destino": de["tabela"], "recebedores": de["recebedores"]})
