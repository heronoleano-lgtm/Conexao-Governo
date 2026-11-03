import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # telas/visoes -> raiz

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import ui  # noqa: E402
from custodia import acesso  # noqa: E402
from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402
from custodia.ui import cartoes, leitura, pagina, rosca, secao, tabela  # noqa: E402
from custodia.ui import AUREA_INV  # noqa: E402  (ESTET-01: divisão φ : 1)

ctx = pagina("CRM · Visão 360 do ente",
             "Tudo sobre um ente num lugar: quanto recebe da União (Portal da Transparência), em que banco o dinheiro "
             "fica, quem manda (emendas), a presença da CAIXA no município, fornecedores, conformidade e o histórico "
             "de relacionamento.", filtros=False)
d = ctx.d
cart = d.get("crm_carteira", pd.DataFrame())
pr = d.get("crm_prioridade", pd.DataFrame())
er = d.get("mart_ente_resumo", pd.DataFrame())
if (cart is None or cart.empty) and (er is None or er.empty):
    st.info("O CRM usa a API do Portal da Transparência. Coloque a chave em config/segredos.yaml e rode a carga.")
    st.stop()

# ---------------------------------------------------------------- escolha do ente
pedido = st.session_state.get("ente_cnpj") or st.query_params.get("cnpj")
c0, c1, c2 = st.columns([2, 3, 1])
busca = c0.text_input("Buscar ente", key="v360_busca", placeholder="nome, município, UF ou CNPJ",
                      help="A lista mostra até 300 entes (os de maior prioridade CRM, ou os que casam com a busca). "
                           "Todos os entes do painel e do Portal podem ser encontrados pela busca.")
opc = q.buscar_entes(d, busca, 300, pedido)
if opc.empty:
    st.info("Nenhum ente encontrado com essa busca.")
    st.stop()
lista = opc["cnpj_ente"].tolist()
rot = dict(zip(opc["cnpj_ente"], opc["rotulo"]))
cnpj = c1.selectbox("Ente", lista, index=lista.index(pedido) if pedido in lista else 0,
                    format_func=lambda c: rot.get(c, c))
st.session_state["ente_cnpj"] = cnpj
linha = cart[cart["cnpj"] == cnpj].iloc[0] if not cart.empty and (cart["cnpj"] == cnpj).any() else None
ente = er[er["cnpj_ente"] == cnpj].iloc[0] if not er.empty and (er["cnpj_ente"] == cnpj).any() else None
cod = (linha["cod_ibge"] if linha is not None else None) or (ente["cod_ibge"] if ente is not None else None)
cod = str(cod).replace(".0", "") if cod is not None and cod == cod else None
municipio_todo = c2.toggle("Somar o município inteiro", value=False, disabled=not cod or len(cod) != 7,
                           help="Prefeitura, fundos e secretarias do município (todos os CNPJs com o mesmo código IBGE)")
if municipio_todo and cod:
    cnpjs = set(cart.loc[cart["cod_ibge"].astype(str) == cod, "cnpj"]) | \
        (set(er.loc[er["cod_ibge"].astype(str) == cod, "cnpj_ente"]) if not er.empty else set()) | {cnpj}
else:
    cnpjs = {cnpj}
c_sel = cart[cart["cnpj"].isin(cnpjs)] if not cart.empty else cart

# ---------------------------------------------------------------- indicadores (com a conta reversa visível)
rec = float(c_sel["recebido_12m"].sum()) if not c_sel.empty else 0.0
cx = float(c_sel["caixa_conhecido_12m"].sum()) if not c_sel.empty else 0.0
co = float(c_sel["concorrente_conhecido_12m"].sum()) if not c_sel.empty else 0.0
sb = float(c_sel["sem_banco_12m"].sum()) if not c_sel.empty else 0.0
pri = pr.loc[pr["cnpj_ente"] == cnpj, "prioridade"] if not pr.empty else pd.Series(dtype=float)
carteira = acesso.carteira()
st_cart = carteira.loc[carteira["cnpj_ente"] == cnpj, "status"] if not carteira.empty else pd.Series(dtype=str)
cartoes([
    {"rotulo": "Prioridade CRM", "valor": f"{int(pri.iloc[0])}/100" if len(pri) and pri.iloc[0] == pri.iloc[0] else "—",
     "sub": "regra CRM-01", "cor": "#7E5BB5"},
    {"rotulo": "Recebido no Portal (12 meses)", "valor": q.brl(rec), "sub": f"{len(cnpjs)} CNPJ(s) · despesas com o CNPJ favorecido",
     "ajuda": "Portal da Transparência, recursos recebidos: despesas federais em que o CNPJ é o favorecido. NÃO inclui "
              "FPM, FUNDEB nem os repasses fundo a fundo (FNS, FNAS, FNDE), que aparecem em 'Transferências ao município'"},
    {"rotulo": "Na CAIXA (banco conhecido)", "valor": q.brl(cx), "cor": "#005CA9"},
    {"rotulo": "No concorrente (banco conhecido)", "valor": q.brl(co), "cor": "#D1495B"},
    {"rotulo": "Sem banco conhecido", "valor": q.brl(sb), "cor": "#F39200",
     "sub": "a fonte aberta não informa o banco"},
    (ui.cartao_saldo("Custódia CAIXA (saldo)", ente["saldo_caixa"], ente.get("saldo_caixa_estimado"),
                     parado_em=q.parada_saldo(d))
     if ente is not None and "saldo_caixa" in ente else {"rotulo": "Custódia CAIXA (saldo)", "valor": "—"}),
    {"rotulo": "Status na carteira", "valor": st_cart.iloc[0] if len(st_cart) else "não abordado", "cor": "#00A19A"},
])
if rec:
    st.caption(f"Conferência: {q.brl(rec)} recebidos = {q.brl(cx)} na CAIXA + {q.brl(co)} no concorrente + "
               f"{q.brl(sb)} sem banco conhecido.")
if not c_sel.empty and c_sel["conhecido_excede"].fillna(False).astype(bool).any():
    st.warning("Contradição entre fontes: o dinheiro com banco conhecido (FNS/Especiais) passa do que o Portal registra "
               "como recebido. Pode ser diferença de mês de competência ou dado faltando; está na Auditoria da carga.")
tm = q.transferencias_municipio(d, cod) if cod and len(cod) == 7 else pd.DataFrame()
if not tm.empty:
    tot_tm = float(tm["valor_12m"].sum())
    cx_tm, ob_tm = float(tm["valor_caixa"].sum()), float(tm["valor_outro_banco"].sum())
    cartoes([{"rotulo": "Transferências ao município (12 meses)", "valor": q.brl(tot_tm),
              "sub": " · ".join(f"{r.fonte} {q.brl(r.valor_12m)}" for r in tm.head(4).itertuples()), "cor": "#0B2E5C",
              "ajuda": "FPM e FUNDEB (Tesouro), saúde (FNS), educação (FNDE), assistência (FNAS) e royalties, somados por "
                       "município (prefeitura e fundos). Só o FNS publica o banco da conta"},
             {"rotulo": "… com banco publicado na CAIXA", "valor": q.brl(cx_tm), "cor": "#005CA9",
              "sub": f"{q.pct(cx_tm / (cx_tm + ob_tm)) if cx_tm + ob_tm else '—'} do que tem banco publicado"},
             {"rotulo": "… sem banco publicado", "valor": q.brl(tot_tm - cx_tm - ob_tm), "cor": "#F39200",
              "sub": "FPM, FUNDEB, FNDE, FNAS: a fonte não publica o banco"}])
    st.caption("O Portal e as transferências ao município são bases diferentes e NÃO são somadas: o Portal traz despesas "
               "com o CNPJ como favorecido; as transferências constitucionais e fundo a fundo vêm do Tesouro, do FNS, do "
               "FNDE e do FNAS.")
acao = pr.loc[pr["cnpj_ente"] == cnpj, "proxima_acao"] if not pr.empty else pd.Series(dtype=str)
if len(acao):
    leitura("Próxima ação sugerida", [acao.iloc[0]])

aba1, aba2, aba3, aba4, aba5 = st.tabs(["De onde vem o dinheiro", "Emendas e parlamentares", "Município e presença CAIXA",
                                        "Fornecedores e conformidade", "Relacionamento"])
with aba1:
    if c_sel.empty:
        st.info("Sem recebimentos no Portal para este recorte (ou a carga do Portal ainda não chegou neste ente).")
    else:
        comp = pd.Series({"Saúde": c_sel["saude_12m"].sum(), "Educação": c_sel["educacao_12m"].sum(),
                          "Assistência": c_sel["assistencia_12m"].sum(),
                          "Constitucionais": c_sel["constitucionais_12m"].sum(), "Outros": c_sel["outros_12m"].sum()})
        a, b = st.columns(AUREA_INV)
        with a:
            rosca(comp, "Recebido por área (12 meses)", altura=300, chave="crm360_area")
            rosca(pd.Series({"CAIXA": cx, "Concorrente": co, "Sem banco conhecido": sb}), "Em que banco fica",
                  {"CAIXA": "#005CA9", "Concorrente": "#D1495B", "Sem banco conhecido": "#F39200"}, altura=300,
                  chave="crm360_banco")
        with b:
            r = d.get("crm_recebido", pd.DataFrame())
            r = r[r["cnpj"].isin(cnpjs)] if not r.empty else r
            if not r.empty:
                m = r.groupby(["mes", "orgao_superior"], as_index=False)["valor"].sum()
                piv = m.pivot_table(index="mes", columns="orgao_superior", values="valor", aggfunc="sum").fillna(0)
                top = piv.sum().sort_values(ascending=False).index[:6]
                piv = piv[top].reset_index()
                g.barras(piv, "mes", {c: str(c)[:30] for c in top}, chave="crm360_mes", altura=360,
                         titulo="Recebido por mês e órgão")
            tabela(c_sel.drop(columns=["conhecido_excede"], errors="ignore"))
with aba2:
    pg = d.get("crm_emenda_pagamento", pd.DataFrame())
    pg = pg[pg["doc_favorecido"].isin(cnpjs)] if not pg.empty else pg
    if pg.empty:
        st.info("Nenhum pagamento de emenda identificado para este recorte.")
    else:
        por = pg.groupby("autor", as_index=False)["valor_pago_doc"].sum().sort_values("valor_pago_doc", ascending=False)
        g.barras(por.head(15), "autor", {"valor_pago_doc": "Emendas pagas"}, chave="crm360_emendas", horizontal=True,
                 altura=360)
        tabela(pg[["autor", "tipo", "ano", "codigo_emenda", "codigo_documento", "data", "valor_pago_doc", "favorecido"]])
with aba3:
    pres = d.get("crm_presenca", pd.DataFrame())
    p = pres[pres["cod_ibge"].astype(str) == str(cod)] if cod and not pres.empty else pd.DataFrame()
    if p.empty:
        st.info("Sem dado de Bolsa Família para o município (ou ente estadual).")
    else:
        p = p.iloc[0]
        cartoes([{"rotulo": "Bolsa Família pago pela CAIXA (mês)", "valor": q.brl(p["bolsa_familia_mes"]),
                  "sub": f"{int(p['beneficiarios'] or 0):,} famílias · {p['mes']}".replace(",", ".")},
                 {"rotulo": "Participação CAIXA nos instrumentos", "valor": q.pct(p["part_caixa_instrumentos"]),
                  "cor": "#005CA9"},
                 {"rotulo": "Situação", "valor": p["classe"], "cor": "#F39200"}])
    if cod and not er.empty:
        tabela(er[er["cod_ibge"].astype(str) == str(cod)][["nome_ente", "tipo_ente", "valor", "part_caixa",
                                                            "banco_principal", "saldo_caixa", "saldo_concorrente",
                                                            "cnpj_ente"]])
with aba4:
    al = d.get("crm_alertas", pd.DataFrame())
    al = al[al["cnpj_ente"].isin(cnpjs) | al["cnpj"].isin(cnpjs)] if not al.empty else al
    if al.empty:
        st.success("Nenhum alerta de conformidade para este recorte.")
    else:
        st.warning("Alertas de conformidade: a leitura jurídica cabe à Conformidade da CAIXA.")
        tabela(al)
    rd = d.get("crm_rede", pd.DataFrame())
    forn = rd[(rd["origem_tipo"] == "ente") & (rd["destino_tipo"] == "fornecedor") & rd["origem_id"].isin(cnpjs)] \
        if not rd.empty else rd
    if not forn.empty:
        secao("Principais fornecedores pagos", "Pelos extratos das contas de transferência (Transferegov).")
        tabela(forn[["destino", "destino_id", "valor"]].rename(columns={"destino": "nome", "destino_id": "cnpj"}))
with aba5:
    hist = acesso.atividades(cnpj)
    if hist.empty:
        st.caption("Nenhuma atividade registrada para este ente.")
    else:
        tabela(hist[["data_atividade", "atividade", "resultado", "proxima_acao", "data_proxima", "responsavel",
                     "registrado_por"]])
    if ctx.usuario["perfil"] in ("comercial", "gestao", "administrador"):
        with st.form("crm_atividade"):
            a1, a2, a3 = st.columns(3)
            tipo = a1.selectbox("Atividade", acesso.TIPOS_ATIVIDADE)
            quando = a2.date_input("Data", value=date.today())
            resp = a3.text_input("Responsável", ctx.usuario["nome"])
            resultado = st.text_area("Resultado", placeholder="O que foi tratado, decisões, objeções")
            b1, b2, b3 = st.columns([3, 1, 2])
            prox = b1.text_input("Próxima ação")
            dprox = b2.date_input("Data da próxima ação", value=None)
            novo_status = b3.selectbox("Status na carteira", acesso.STATUS_CARTEIRA,
                                       index=acesso.STATUS_CARTEIRA.index(st_cart.iloc[0]) if len(st_cart) else 0)
            if st.form_submit_button("Registrar"):
                acesso.registrar_atividade(cnpj, tipo, str(quando), resultado, prox, str(dprox) if dprox else None, resp,
                                           ctx.usuario["login"])
                if not len(st_cart) or novo_status != st_cart.iloc[0]:
                    acesso.salvar_carteira(cnpj, novo_status, resp, resultado[:500], ctx.usuario["login"])
                st.success("Atividade registrada.")
                st.rerun()
