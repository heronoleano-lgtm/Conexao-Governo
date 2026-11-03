"""Ponto de entrada do painel: login e menu por seções. Rode com: streamlit run telas/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from custodia import config, dados, interacao, ui  # noqa: E402

st.set_page_config(page_title="Conexão Governo · CAIXA", page_icon="🏦", layout="wide",
                   initial_sidebar_state="expanded")
usuario = ui.exigir_login()
logo = ui.LOGOS / "caixa_selo.png"          # o X da CAIXA sobre o azul (o branco some na barra lateral clara)
if logo.exists() and hasattr(st, "logo"):
    try:
        st.logo(str(logo), size="large")
    except TypeError:
        st.logo(str(logo))

P = st.Page
MENU = {
    "Visão executiva": [
        P("Inicio.py", title="Cockpit", icon=":material/dashboard:", default=True),
        P("pages/26_Janela_de_escolha.py", title="Janela de escolha do banco", icon=":material/how_to_reg:"),
        P("pages/13_Radar_de_risco.py", title="Radar de risco e relacionamento", icon=":material/radar:"),
        P("pages/02_Mapa_da_custodia.py", title="Mapa e território", icon=":material/map:"),
    ],
    "CRM": [
        P("pages/29_CRM_Funil_e_agenda.py", title="Funil e agenda", icon=":material/filter_alt:"),
        P("pages/28_CRM_Visao_360.py", title="Visão 360 do ente", icon=":material/account_circle:"),
        P("pages/30_CRM_Rede_de_relacionamento.py", title="Rede de relacionamento", icon=":material/hub:"),
        P("pages/31_CRM_Conformidade.py", title="Conformidade", icon=":material/gpp_maybe:"),
    ],
    "Custódia": [
        P("pages/14_Permanencia_e_rentabilidade.py", title="Permanência e rentabilidade", icon=":material/savings:"),
        P("pages/15_Evolucao_do_saldo.py", title="Evolução do saldo", icon=":material/show_chart:"),
        P("pages/16_Dinheiro_a_receber.py", title="Dinheiro a receber", icon=":material/event_upcoming:"),
        P("pages/27_Outros_repasses.py", title="FUNDEB, saúde, educação e assistência", icon=":material/health_and_safety:"),
    ],
    "Mercado": [
        P("pages/03_Concorrencia.py", title="Concorrência", icon=":material/leaderboard:"),
        P("pages/17_Matriz_de_escolhas.py", title="Matriz de escolhas", icon=":material/grid_on:"),
        P("pages/18_Entes_perdidos.py", title="Entes perdidos", icon=":material/person_remove:"),
    ],
    "Fluxo do dinheiro": [
        P("pages/01_Fluxo_do_dinheiro.py", title="Fluxo do dinheiro", icon=":material/account_tree:"),
        P("pages/01_Transferencia_secundaria_FaF.py", title="Transferência secundária FaF", icon=":material/swap_horiz:"),
        P("pages/05_Ministerios_e_programas.py", title="Ministérios e programas", icon=":material/account_balance:"),
        P("pages/06_Destinacao.py", title="Destinação", icon=":material/category:"),
        P("pages/04_Parlamentares.py", title="Parlamentares", icon=":material/how_to_vote:"),
        P("pages/07_Fornecedores_e_pagamentos.py", title="Fornecedores e pagamentos", icon=":material/storefront:"),
    ],
    "Ação comercial": [
        P("pages/20_Priorizacao_e_cenarios.py", title="Priorização e cenários", icon=":material/target:"),
        P("pages/19_Venda_cruzada.py", title="Venda cruzada", icon=":material/handshake:"),
        P("pages/09_Oportunidades.py", title="Oportunidades e carteira", icon=":material/work:"),
    ],
    "Governança": [
        P("pages/22_Perguntas_de_negocio.py", title="Perguntas de negócio", icon=":material/quiz:"),
        P("pages/23_Regras_e_premissas.py", title="Regras e premissas", icon=":material/rule:"),
        P("pages/24_Repositorio_de_dados.py", title="Repositório de dados", icon=":material/database:"),
        P("pages/12_Qualidade_dos_dados.py", title="Qualidade e auditoria", icon=":material/verified:"),
    ],
}
# telas que viraram visões de outra (v0.9.2) ficam fora do menu e só redirecionam endereços antigos

try:
    nav = st.navigation(MENU, position="sidebar", expanded=True)
except TypeError:
    nav = st.navigation(MENU, position="sidebar")
relogio = interacao.Cronometro(getattr(nav, "title", "") or "tela")
try:
    nav.run()
finally:
    # tempo de cada tela, para diagnóstico no computador (data/logs/telas.csv) e aviso discreto na barra lateral
    try:
        execucao = ui.consultas.execucao_atual()
        m = ui._dados(execucao) if execucao else None
        info = {"tabelas": len(m.carregados()) if m is not None else "", "memoria_mb": round(m.memoria_mb())
                if m is not None else "", "calculos": dados.ESTATISTICA["calculos"], "acertos": dados.ESTATISTICA["acertos"]}
        seg = relogio.fim(config.caminhos().dados / "logs", info)
        st.sidebar.caption(f"Tela montada em {seg:.1f} s")
    except Exception:
        pass
