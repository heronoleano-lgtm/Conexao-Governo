"""Componentes visuais do painel: identidade, cabeçalhos, cartões de indicadores, tabelas rotuladas e gráficos.

Toda tela usa estas peças, então aparência e vocabulário são os mesmos em todo o painel.
Gráficos usam plotly; sem plotly instalado, cada componente cai para uma tabela ou gráfico simples.
"""
from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

from . import acesso, consultas, dados as _dados_mod, interacao
from .semantica import (BANCO_CORES, CAIXA_AZUL, CAIXA_LARANJA, EXTRA_CORES, MODALIDADES, SEGMENTO_CORES,
                        cor_banco, nome_modalidade, rotular)

FONTE = "Inter, 'Segoe UI', Roboto, sans-serif"
CSS = f"""
<style>
:root {{ --cx-azul: {CAIXA_AZUL}; --cx-laranja: {CAIXA_LARANJA}; --cx-marinho: #0B2E5C; --cx-borda: #E4E9F0;
  --cx-texto: #101828; --cx-suave: #667085; --cx-sombra: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06); }}
html, body, [class*="css"] {{ font-family: {FONTE}; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1560px; }}
h1, h2, h3 {{ letter-spacing: -0.015em; }}

/* cabeçalho da página */
.cx-cabecalho {{ position: relative; background: #fff; border: 1px solid var(--cx-borda); border-radius: 14px;
  padding: 18px 24px 18px 28px; margin-bottom: 18px; display: flex; justify-content: space-between; align-items: center;
  gap: 18px; box-shadow: var(--cx-sombra); overflow: hidden; }}
.cx-cabecalho::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px;
  background: linear-gradient(180deg, var(--cx-azul) 0%, var(--cx-azul) 70%, var(--cx-laranja) 70%, var(--cx-laranja) 100%); }}
.cx-cabecalho .cx-sobre {{ font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--cx-azul); margin-bottom: 2px; }}
.cx-cabecalho h1 {{ font-size: 1.6rem; margin: 0; color: var(--cx-marinho); font-weight: 750; line-height: 1.2; padding: 0; }}
.cx-cabecalho p {{ margin: 6px 0 0 0; color: #475467; font-size: .92rem; max-width: 1020px; line-height: 1.45; }}
.cx-cabecalho .cx-data {{ font-size: .78rem; color: var(--cx-suave); text-align: right; white-space: nowrap; line-height: 1.6; }}
.cx-cabecalho .cx-data b {{ color: var(--cx-texto); font-weight: 600; }}
.cx-faixa {{ display: none; }}
/* o X da CAIXA (arquivo da marca sobre o azul institucional) */
.cx-x {{ background: var(--cx-azul); border-radius: 12px; padding: 9px 11px; display: inline-flex; align-items: center;
  justify-content: center; box-shadow: 0 2px 6px rgba(0,92,169,.25); flex: none; }}
.cx-x img {{ display: block; }}
/* tela de entrada */
.cx-entrada {{ position: relative; border-radius: 18px; padding: 34px 36px 30px 36px; margin: 4vh 0 20px 0; overflow: hidden;
  background: linear-gradient(135deg, #003F7D 0%, var(--cx-azul) 58%, #1F7AC7 100%); color: #fff;
  box-shadow: 0 12px 32px rgba(0,63,125,.25); }}
.cx-entrada::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 6px; background: var(--cx-laranja); }}
.cx-entrada .topo {{ display: flex; align-items: center; gap: 18px; }}
.cx-entrada .cx-x {{ background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.25); box-shadow: none;
  padding: 14px 16px; border-radius: 16px; }}
.cx-entrada .sobre {{ font-size: .74rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; opacity: .85; }}
.cx-entrada h1 {{ color: #fff; font-size: 1.75rem; margin: 2px 0 0 0; padding: 0; font-weight: 750; line-height: 1.2; }}
.cx-entrada p {{ margin: 18px 0 0 0; font-size: .95rem; line-height: 1.5; opacity: .92; max-width: 560px; }}
.cx-entrada .pilares {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
.cx-entrada .pilares span {{ font-size: .76rem; font-weight: 600; padding: 4px 11px; border-radius: 999px;
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); }}
.cx-rodape-entrada {{ text-align: center; color: var(--cx-suave); font-size: .76rem; margin-top: 10px; }}
[data-testid="stForm"] {{ background: #fff; border: 1px solid var(--cx-borda); border-radius: 14px; box-shadow: var(--cx-sombra);
  padding: 18px 20px; }}

/* cartões de indicador */
.cx-cartoes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin: 4px 0 18px 0; }}
.cx-cartao {{ position: relative; background: #fff; border: 1px solid var(--cx-borda); border-radius: 12px;
  padding: 14px 16px 13px 16px; box-shadow: var(--cx-sombra); transition: box-shadow .15s ease, transform .15s ease; overflow: hidden; }}
.cx-cartao::before {{ content: ""; position: absolute; left: 0; right: 0; top: 0; height: 3px; background: var(--cor); }}
.cx-cartao:hover {{ box-shadow: 0 8px 20px rgba(16,24,40,.08); transform: translateY(-1px); }}
.cx-cartao .r {{ font-size: .72rem; color: var(--cx-suave); text-transform: uppercase; letter-spacing: .06em; font-weight: 650; }}
.cx-cartao .v {{ font-size: 1.62rem; font-weight: 750; color: var(--cx-marinho); margin-top: 6px; line-height: 1.15;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }}
.cx-cartao .s {{ font-size: .8rem; color: var(--cx-suave); margin-top: 4px; line-height: 1.35; }}
.cx-cartao .d {{ display: inline-block; font-size: .74rem; font-weight: 700; padding: 1px 7px; border-radius: 999px; margin-top: 6px; }}
.cx-cartao .d.sobe {{ background: #E7F6EE; color: #12733F; }} .cx-cartao .d.desce {{ background: #FDECEC; color: #A3222F; }}
.cx-cartao .d.neutro {{ background: #F2F4F7; color: #475467; }}
.cx-cartao .parado {{ display: block; margin-top: 7px; padding: 4px 8px; border-radius: 7px; font-size: .74rem; font-weight: 650;
  background: #FFF4E5; color: #8A4B00; border: 1px solid #F7C98B; line-height: 1.35; }}
.cx-cartao .est {{ display: inline-block; font-size: .64rem; font-weight: 750; letter-spacing: .05em; text-transform: uppercase;
  color: #6941C6; background: #F4F0FF; border-radius: 4px; padding: 1px 5px; margin-left: 6px; vertical-align: middle; }}

/* títulos de seção */
.cx-secao {{ margin: 26px 0 10px 0; }}
.cx-secao h3 {{ font-size: 1.08rem; margin: 0; color: var(--cx-texto); font-weight: 700; display: flex; align-items: center; gap: 10px; padding: 0; }}
.cx-secao h3::before {{ content: ""; width: 4px; height: 18px; border-radius: 2px; background: var(--cx-azul); display: inline-block; }}
.cx-secao p {{ margin: 4px 0 0 14px; color: var(--cx-suave); font-size: .86rem; }}

/* leitura automática (achados) */
.cx-leitura {{ background: linear-gradient(180deg, #F2F7FD 0%, #FFFFFF 100%); border: 1px solid #D6E4F5; border-radius: 12px;
  padding: 14px 18px; margin: 8px 0 16px 0; box-shadow: var(--cx-sombra); }}
.cx-leitura > b {{ display: block; font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: var(--cx-azul); }}
.cx-leitura ul {{ margin: 6px 0 0 18px; padding: 0; }} .cx-leitura li {{ margin: 4px 0; font-size: .92rem; color: #344054; line-height: 1.45; }}
.cx-leitura li b {{ color: var(--cx-marinho); }}

.cx-chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .76rem; margin: 0 6px 6px 0;
  background: var(--cor); color: #fff; font-weight: 600; }}
.cx-alerta {{ background: #FFF8EB; border: 1px solid #F7D08A; border-left: 5px solid var(--cx-laranja); border-radius: 12px;
  padding: 11px 16px; margin: 0 0 16px 0; font-size: .9rem; color: #5B3B00; }}
.cx-selo {{ display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: .75rem; font-weight: 700; }}

/* abas, tabelas, gráficos e mapa em "cartões" */
div[data-testid="stTabs"] button p {{ font-weight: 600; font-size: .92rem; }}
div[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 1px solid var(--cx-borda); }}
[data-testid="stDataFrame"], .ag-root-wrapper {{ border-radius: 12px !important; overflow: hidden; box-shadow: var(--cx-sombra); }}
[data-testid="stPlotlyChart"], .echarts-container {{ background: #fff; border: 1px solid var(--cx-borda); border-radius: 12px;
  box-shadow: var(--cx-sombra); }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: #fff; border-radius: 12px; }}
[data-testid="stDeckGlJsonChart"] {{ border: 1px solid var(--cx-borda); border-radius: 12px; overflow: hidden; background: #EEF2F7;
  box-shadow: var(--cx-sombra); }}

/* barra lateral */
[data-testid="stSidebarNav"] span {{ font-size: .9rem; }}
[data-testid="stSidebarNavSeparator"] {{ margin: 8px 0; }}
[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] header, [data-testid="stSidebar"] .st-emotion-cache-nav-header {{
  text-transform: uppercase; letter-spacing: .08em; font-size: .7rem; opacity: .75; }}

/* legenda do mapa */
.cx-leg {{ display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; font-size: .78rem; color: #344054; padding: 10px 4px 4px 4px; }}
.cx-leg-t {{ font-weight: 700; color: var(--cx-texto); margin-right: 2px; }}
.cx-leg-i {{ display: inline-flex; align-items: center; gap: 6px; }}
.cx-leg-i i {{ width: 14px; height: 14px; border-radius: 3px; display: inline-block; border: 1px solid rgba(16,24,40,.10); }}
.cx-leg-i i.o {{ border-radius: 50%; }}
.cx-leg-sep {{ width: 1px; height: 16px; background: #D0D5DD; }}
.cx-leg-dica {{ margin-left: auto; color: #98A2B3; font-size: .72rem; }}
.cx-filtros {{ font-size: .85rem; color: #344054; padding: 6px 0; }}
.cx-tab-info {{ font-size: .8rem; color: #667085; margin: 2px 0 6px; }}
</style>
"""


@dataclass
class Contexto:
    d: dict
    usuario: dict
    modulos: list[str]
    anos: list[int]
    ufs: list[str]
    extra: dict | None = None

    def f(self, df_ou_nome, modulos: bool = True, anos: bool = True, ufs: bool = True, extra: bool = True):
        """Aplica TODOS os filtros ativos (barra lateral + cliques) a um mart (pelo nome, memorizado) ou a uma tabela.
        Desligue um filtro passando False (ex.: anos=False em tabelas sem ano de origem)."""
        a = (self.modulos or None if modulos else None, self.anos or None if anos else None,
             self.ufs or None if ufs else None, (self.extra or None) if extra else None)
        if isinstance(df_ou_nome, str):
            return consultas.filtrada(self.d, df_ou_nome, *a)
        return consultas.filtrar(df_ou_nome, *a)


_cache_recurso = getattr(st, "cache_resource", None)
_ULTIMA = {"execucao": None}


def _abrir(execucao: str):
    if _ULTIMA["execucao"] not in (None, execucao):
        _dados_mod.limpar_memos()          # carga nova: cálculos da carga anterior saem da memória
    _ULTIMA["execucao"] = execucao
    return consultas.carregar(execucao)


# uma instância por execução, compartilhada e SEM cópia a cada clique (antes: cache_data copiava tudo)
_dados = _cache_recurso(max_entries=2, show_spinner="Abrindo os dados…")(_abrir) if _cache_recurso else _abrir


@(_cache_recurso(max_entries=4, show_spinner=False) if _cache_recurso else (lambda f: f))
def _opcoes_filtros(execucao: str) -> dict:
    instr = _dados(execucao)["fato_instrumento"]
    if instr.empty:
        return {"modulo": [], "ano": [], "uf": []}
    return {"modulo": sorted(instr["modulo"].dropna().unique()),
            "ano": sorted(int(a) for a in instr["ano"].dropna().unique()),
            "uf": sorted(instr["uf"].dropna().unique())}


def _login() -> dict | None:
    if st.session_state.get("usuario"):
        return st.session_state["usuario"]
    if not acesso.ler_usuarios():
        st.error("Nenhum usuário cadastrado. Rode novo_usuario.bat (perfil administrador) e recarregue.")
        st.stop()
    st.markdown(CSS, unsafe_allow_html=True)
    _, meio, _ = st.columns([1, 1.6, 1])
    with meio:
        x = selo_caixa(54)
        st.markdown(
            f'<div class="cx-entrada"><div class="topo">{x}<div><div class="sobre">CAIXA · Painel de Custódia</div>'
            '<h1>Transferências federais</h1></div></div>'
            '<p>Quanto do dinheiro transferido pela União a estados, municípios e entidades fica na CAIXA, '
            'para onde ele vai e onde estão as oportunidades.</p>'
            '<div class="pilares"><span>Especiais</span><span>Fundo a Fundo</span><span>Discricionárias</span>'
            '<span>Saúde e Tesouro</span><span>CRM</span></div></div>', unsafe_allow_html=True)
        with st.form("login"):
            login = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            ok = st.form_submit_button("Entrar", type="primary", use_container_width=True)
        st.markdown('<div class="cx-rodape-entrada">Fonte: Transferegov.br, Portal da Transparência, FNS e Tesouro · '
                    'uso interno</div>', unsafe_allow_html=True)
    if ok:
        u = acesso.autenticar(login, senha)
        if u:
            st.session_state["usuario"] = u
            st.rerun()
        st.error("Usuário ou senha inválidos.")
    st.stop()


# ------------------------------------------------------------------ marcas
LOGOS = Path(__file__).resolve().parent.parent / "assets" / "logos"
ARQ_LOGO = {"CAIXA": "caixa_branco", "CAIXA_COR": "caixa_cor", "BB": "bb", "BNB": "bnb", "GOV": "govbr"}


@lru_cache(maxsize=16)
def _logo_uri(nome: str) -> str | None:
    base = ARQ_LOGO.get(nome, nome)
    for ext, mime in ((".svg", "image/svg+xml"), (".png", "image/png"), (".webp", "image/webp")):
        arq = LOGOS / f"{base}{ext}"
        if arq.exists():
            return f"data:{mime};base64,{base64.b64encode(arq.read_bytes()).decode()}"
    return None


def marca(nome: str, altura: int = 22, texto: bool = True) -> str:
    """HTML com a logo da instituição (se o arquivo estiver em assets/logos) ou um selo com nome e cor."""
    uri = _logo_uri(nome)
    rot = {"GOV": "gov.br"}.get(nome, nome)
    if uri:
        return f'<img src="{uri}" alt="{rot}" style="height:{altura}px;vertical-align:middle">'
    if not texto:
        return ""
    return f'<span class="cx-chip" style="--cor:{cor_banco(rot)}">{html.escape(rot)}</span>'


def selo_caixa(altura: int = 30) -> str:
    """O X da CAIXA: o arquivo da marca (assets/logos/caixa_branco.png) sobre o azul institucional. Não redesenha
    a marca; sem o arquivo, não mostra nada."""
    uri = _logo_uri("CAIXA")
    return (f'<span class="cx-x"><img src="{uri}" alt="CAIXA" style="height:{altura}px"></span>' if uri else "")


def aviso_fonte(d: dict, modulos: list[str] | None = None) -> None:
    """Avisa quando o extrato de algum banco parou de chegar na fonte (regra QLD-01)."""
    paradas = d.get("meta", {}).get("fontes_interrompidas", [])
    dfa = d.get("mart_defasagem", pd.DataFrame())
    if modulos:
        paradas = [p for p in paradas if p["modulo"] in modulos]
    if not paradas:
        return
    frases = []
    for p in paradas:
        x = dfa[(dfa["modulo"] == p["modulo"]) & (dfa["grupo_banco"] == p["banco"])] if not dfa.empty else dfa
        quando = x["data_saldo_mediana"].iloc[0] if not x.empty else "?"
        frases.append(f"{p['banco']} em {nome_modalidade(p['modulo'])} (saldo típico de {quando})")
    st.markdown(f'<div class="cx-alerta"><b>Atenção à fonte:</b> o extrato de {"; ".join(frases)} parou de chegar ao '
                'Transferegov. Saldos e lançamentos desse banco nessa modalidade estão defasados; comparações de '
                'custódia ficam distorcidas. Veja Qualidade e atualização.</div>', unsafe_allow_html=True)


def exigir_login() -> dict:
    return _login()


# ------------------------------------------------------------------ telas com várias visões
# Telas que respondiam à mesma pergunta viraram VISÕES de uma tela só (v0.9.2): o conteúdo de cada uma fica em
# telas/visoes/ e roda dentro da tela-mãe, que já montou cabeçalho, filtros e login. Só a visão escolhida é
# calculada (nada pesa a mais), e cada visão continua podendo rodar sozinha.
VISOES = Path(__file__).resolve().parent.parent / "telas" / "visoes"
_EMBUTIDA: list = []


def visoes(ctx: "Contexto", opcoes: dict[str, str], chave: str) -> str:
    """Seletor de visões + execução da visão escolhida. `opcoes`: nome mostrado -> arquivo em telas/visoes."""
    import runpy
    nomes = list(opcoes)
    ss = st.session_state
    pedido = ss.pop(f"{chave}_pedido", None)          # vindo de um botão "abrir em…" de outra tela
    if pedido in nomes:
        ss[chave] = pedido
    if ss.get(chave) not in nomes:
        ss[chave] = nomes[0]
    seg = getattr(st, "segmented_control", None)
    if seg is not None:
        esc = seg("Visão", nomes, key=chave, label_visibility="collapsed")
    else:
        esc = st.radio("Visão", nomes, key=chave, horizontal=True, label_visibility="collapsed")
    esc = esc if esc in nomes else nomes[0]
    _EMBUTIDA.append(ctx)
    try:
        runpy.run_path(str(VISOES / opcoes[esc]), run_name="__main__")
    finally:
        _EMBUTIDA.pop()
    return esc


def abrir(rotulo: str, tela: str, visao: tuple[str, str] | None = None, estado: dict | None = None,
          chave: str | None = None, icone: str = ":material/arrow_forward:") -> None:
    """Botão que leva a outra tela já no ente/visão certos (o estado só muda quando a pessoa clica)."""
    if st.button(rotulo, key=chave or f"abrir_{tela}_{rotulo}", icon=icone):
        for k, v in (estado or {}).items():
            st.session_state[k] = v
        if visao:
            st.session_state[f"{visao[0]}_pedido"] = visao[1]
        st.switch_page(tela)


def redirecionar(tela: str, visao: tuple[str, str] | None = None) -> None:
    """Endereço antigo de uma tela que virou visão: leva para a tela-mãe."""
    if visao:
        st.session_state[f"{visao[0]}_pedido"] = visao[1]
    st.switch_page(tela)
    st.stop()


# a mesma escolha de ente vale em todas as telas (Visão 360, Assessor, Ficha, Mapa, Radar…)
ENTE = "ente_cnpj"
TELA_ENTE = "pages/28_CRM_Visao_360.py"


def pagina(titulo: str, legenda: str | None = None, filtros: bool = True) -> Contexto:
    if _EMBUTIDA:                                      # visão dentro de uma tela-mãe
        if legenda:
            st.caption(legenda)
        return _EMBUTIDA[-1]
    try:  # com o menu (app.py) a configuração já foi feita; sozinha, a tela configura
        st.set_page_config(page_title=f"{titulo} · Custódia", page_icon="🏦", layout="wide")
    except Exception:
        pass
    usuario = _login()
    st.markdown(CSS, unsafe_allow_html=True)
    execucao = consultas.execucao_atual()
    if not execucao:
        cabecalho(titulo, legenda)
        st.warning("Ainda não há dados carregados. Rode carga_diaria.bat e recarregue esta página.")
        st.stop()
    d = _dados(execucao)
    meta = d.get("meta", {})
    ops = _opcoes_filtros(execucao)
    interacao.aplicar_pendentes(ops)          # cliques em gráficos viram filtros da barra lateral
    ss = st.session_state

    with st.sidebar:
        c_u, c_s = st.columns([3, 1])
        c_u.markdown(f"<small><b>{html.escape(usuario['nome'])}</b> · {usuario['perfil']}</small>", unsafe_allow_html=True)
        if c_s.button("Sair", key="sair"):
            st.session_state.pop("usuario", None)
            st.rerun()
        modulos, anos, ufs = [], [], []
        if filtros and ops["modulo"]:
            st.divider()
            st.markdown("**Filtros** <small style='color:#98A2B3'>(valem para todas as telas)</small>",
                        unsafe_allow_html=True)
            modulos = st.multiselect("Modalidade", ops["modulo"], key="f_mod", format_func=nome_modalidade)
            anos = st.multiselect("Ano de origem", ops["ano"], key="f_ano")
            ufs = st.multiselect("UF", ops["uf"], key="f_uf", placeholder="Todas")
            # "todos marcados" = sem filtro (mais rápido e igual em resultado)
            modulos = [] if set(modulos) == set(ops["modulo"]) else modulos
            anos = [] if set(anos) == set(ops["ano"]) else anos
    cabecalho(titulo, legenda, f"Dados de {meta.get('dia', '?')}")
    extra = interacao.extras() if filtros else {}
    filtros_ativos(modulos, anos, ufs, extra)
    aviso_fonte(d, modulos or None)
    return Contexto(d, usuario, modulos, anos, ufs, extra)


def filtros_ativos(modulos, anos, ufs, extra) -> None:
    """Etiquetas dos filtros em uso (barra lateral e cliques nos gráficos); clique numa para retirar."""
    itens = [("modulo", m) for m in (modulos or [])] + [("ano", a) for a in (anos or [])] + \
        [("uf", u) for u in (ufs or [])] + [(k, v) for k, vs in (extra or {}).items() for v in vs]
    if not itens:
        return
    nomes = st.session_state.get("_f_nomes") or {}
    if len(itens) > 8:          # muitas modalidades/anos marcados: resume
        resumo = {}
        for k, v in itens:
            resumo.setdefault(k, []).append(v)
        texto = " · ".join(f"{interacao.DIMENSOES.get(k, k)}: {len(v)}" for k, v in resumo.items())
        c1, c2 = st.columns([6, 1])
        c1.markdown(f"<div class='cx-filtros'>Filtros ativos · {html.escape(texto)}</div>", unsafe_allow_html=True)
        if c2.button("Limpar filtros", key="f_limpar_tudo"):
            interacao.limpar()
            st.rerun()
        return
    cols = st.columns(len(itens) + 1)
    for i, (k, v) in enumerate(itens):
        rot = interacao.rotulo(k, nomes.get(f"{k}|{v}", v))
        if cols[i].button(f"✕ {rot}", key=f"f_x_{k}_{v}", help="Retirar este filtro"):
            interacao.remover(k, v)
            if k in interacao.BARRA:
                st.session_state[interacao.PENDENTE] = {
                    **(st.session_state.get(interacao.PENDENTE) or {}),
                    k: [x for x in (st.session_state.get(interacao.BARRA[k]) or []) if x != v] or None}
            st.rerun()
    if cols[-1].button("Limpar", key="f_limpar_tudo"):
        interacao.limpar()
        st.rerun()


# ------------------------------------------------------------------ blocos de texto
def cabecalho(titulo: str, legenda: str | None = None, data: str | None = None) -> None:
    logo = selo_caixa(30)
    direita = (f'<div class="cx-data">Fonte: <b>Transferegov.br</b>'
               f'{f"<br>{html.escape(data)}" if data else ""}</div>')
    st.markdown(
        f'<div class="cx-cabecalho"><div style="display:flex;gap:16px;align-items:center">'
        f'{logo}<div><div class="cx-sobre">CAIXA · Painel de Custódia</div>'
        f'<h1>{html.escape(titulo)}</h1>'
        f'{f"<p>{html.escape(legenda)}</p>" if legenda else ""}</div></div>{direita}</div>',
        unsafe_allow_html=True)


def secao(titulo: str, sub: str | None = None) -> None:
    st.markdown(f'<div class="cx-secao"><h3>{html.escape(titulo)}</h3>'
                f'{f"<p>{html.escape(sub)}</p>" if sub else ""}</div>', unsafe_allow_html=True)


def cartoes(itens: list[dict]) -> None:
    """Cartões de indicador. Cada item: rotulo, valor, sub, cor, ajuda e delta (opcionais).
    `delta` é um número (variação; positivo = bom) ou um texto já formatado."""
    partes = []
    for it in itens:
        d = it.get("delta")
        selo = ""
        if d is not None and d == d:
            if isinstance(d, (int, float)):
                cls = "sobe" if d > 0 else "desce" if d < 0 else "neutro"
                txt = ("▲ " if d > 0 else "▼ " if d < 0 else "") + consultas.pct(abs(d))
            else:
                cls, txt = "neutro", str(d)
            selo = f'<div class="d {cls}">{html.escape(txt)}</div>'
        est = '<span class="est">estimado</span>' if it.get("estimado") else ""
        par = f'<div class="parado">{html.escape(str(it["parado"]))}</div>' if it.get("parado") else ""
        partes.append(f'<div class="cx-cartao" style="--cor:{it.get("cor", CAIXA_AZUL)}" title="{html.escape(it.get("ajuda", ""))}">'
                      f'<div class="r">{html.escape(str(it["rotulo"]))}{est}</div>'
                      f'<div class="v">{html.escape(str(it["valor"]))}</div>'
                      f'{f"<div class=s>{html.escape(str(it["sub"]))}</div>" if it.get("sub") else ""}{selo}{par}</div>')
    st.markdown(f'<div class="cx-cartoes">{"".join(partes)}</div>', unsafe_allow_html=True)


def cartao_saldo(rotulo: str, publicado: float, estimado: float | None = None, minimo: float | None = None,
                 maximo: float | None = None, parado_em: str | None = None, cor: str | None = None,
                 sub: str | None = None, parado: float | None = None) -> dict:
    """Cartão de saldo com a regra SAL-01: onde o extrato parou, o valor principal é o saldo ESTIMADO de hoje (com a
    faixa) e o saldo PARADO (último publicado, com a data) aparece em destaque logo abaixo. Sem parada, é o cartão
    de sempre, com o saldo publicado."""
    it = {"rotulo": rotulo, "valor": consultas.brl(publicado), "sub": sub or "saldo publicado"}
    if cor:
        it["cor"] = cor
    if estimado is None or abs((estimado or 0) - publicado) <= 0.005 * max(abs(publicado), 1):
        return it
    if not parado_em:       # diferença só de contas sem saldo publicado (ex.: banco que nunca publicou extrato)
        it["sub"] = f"{sub or 'saldo publicado'} · ≈ {consultas.brl(estimado)} com as contas sem saldo publicado (SAL-01)"
        return it
    faixa = (f"faixa {consultas.brl(minimo)} a {consultas.brl(maximo)}" if minimo is not None and maximo is not None
             and abs(maximo - minimo) > 1 else "")
    it.update({"valor": "≈ " + consultas.brl(estimado), "estimado": True,
               "sub": "hoje, reconstituído (regra SAL-01)" + (f" · {faixa}" if faixa else "") + (f" · {sub}" if sub else ""),
               "parado": f"Parado: {consultas.brl(publicado)} — último saldo publicado, de {parado_em}"
                         + (f" (inclui {consultas.brl(parado)} de contas com extrato parado)"
                            if parado is not None and abs(parado - publicado) > 1 else ""),
               "ajuda": "O extrato desse banco parou de chegar ao Transferegov. O valor principal é a reconstituição de "
                        "hoje: créditos publicados (ordens bancárias) − saídas estimadas pela curva de execução do "
                        "próprio banco + rendimento calibrado nos bancos que publicam. A faixa vem dos testes "
                        "retroativos. O valor parado é o último publicado."})
    return it


def cartao_saldo_de(rotulo: str, contas: pd.DataFrame, cor: str | None = None, sub: str | None = None) -> dict:
    r = consultas.saldo_resumo(contas)
    return cartao_saldo(rotulo, r["publicado"], r["estimado"], r["minimo"], r["maximo"], r["parado_em"], cor, sub,
                        r["parado"])


def leitura(titulo: str, frases: list[str]) -> None:
    frases = [f for f in frases if f]
    if not frases:
        return
    itens = "".join(f"<li>{f}</li>" for f in frases)
    st.markdown(f'<div class="cx-leitura"><b>{html.escape(titulo)}</b><ul>{itens}</ul></div>', unsafe_allow_html=True)


def chips(rotulos: dict[str, str]) -> None:
    st.markdown("".join(f'<span class="cx-chip" style="--cor:{c}">{html.escape(r)}</span>' for r, c in rotulos.items()),
                unsafe_allow_html=True)


# ------------------------------------------------------------------ tabela
LIMITE_TABELA = 500        # acima disso a tabela pagina (todas as linhas continuam acessíveis e no download)


def _fragmento(fn):
    """Partes que mudam sozinhas (paginação, busca) redesenham só a si mesmas, não a tela inteira."""
    frag = getattr(st, "fragment", None)
    return frag(fn) if frag else fn


def tabela(df: pd.DataFrame, moedas: tuple[str, ...] = (), pcts: tuple[str, ...] = (), altura: int | None = None,
           chave: str | None = None, **kw) -> None:
    """Tabela com nomes de negócio e formatos do dicionário semântico (moedas/pcts mantidos por compatibilidade).
    Até 500 linhas: tudo de uma vez. Acima: busca, ordenação e páginas — nada é cortado, só não vai tudo ao
    navegador de uma vez (era isso que travava a página)."""
    if df is None or df.empty:
        st.info("Nada a mostrar com os filtros atuais.")
        return
    if len(df) <= LIMITE_TABELA:
        _tabela_simples(df, altura, **kw)
        return
    chave = chave or f"tab_{abs(hash((tuple(map(str, df.columns)), len(df)))) % 10**8}"
    _tabela_paginada(df, chave, altura, kw)


def _tabela_simples(df: pd.DataFrame, altura: int | None = None, **kw) -> None:
    if "modulo" in df.columns:
        df = df.assign(modulo=df["modulo"].map(lambda m: nome_modalidade(m)))
    out, cfg = rotular(df)
    if altura:
        kw["height"] = altura
    st.dataframe(out, use_container_width=True, hide_index=True, column_config=cfg, **kw)


@_fragmento
def _tabela_paginada(df: pd.DataFrame, chave: str, altura: int | None, kw: dict) -> None:
    from .semantica import ROTULOS, humanizar
    textos = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype).startswith(("string", "str"))]
    numeros = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
    busca = c1.text_input("Buscar na tabela", key=f"{chave}_busca", placeholder="nome, CNPJ, município…")
    rot = lambda c: ROTULOS.get(c, (humanizar(c),))[0]  # noqa: E731
    ordem = c2.selectbox("Ordenar por", ["(como veio)"] + numeros, key=f"{chave}_ordem",
                         format_func=lambda c: c if c == "(como veio)" else rot(c))
    tam = c3.selectbox("Linhas", [100, 250, 500], key=f"{chave}_tam")
    x = df
    if busca:
        b = busca.strip().lower()
        m = pd.Series(False, index=x.index)
        for c in textos:
            m |= x[c].astype(str).str.lower().str.contains(b, regex=False, na=False)
        x = x[m]
    if ordem != "(como veio)":
        x = x.sort_values(ordem, ascending=False)
    n = len(x)
    paginas = max(1, -(-n // tam))
    pag = c4.number_input("Página", min_value=1, max_value=paginas, value=1, step=1, key=f"{chave}_pag")
    pag = min(int(pag or 1), paginas)
    ini = (pag - 1) * tam
    st.markdown(f"<div class='cx-tab-info'>Linhas {ini + 1 if n else 0:,}–{min(ini + tam, n):,} de {n:,}"
                f"{f' (de {len(df):,} no total)' if n != len(df) else ''} · página {pag} de {paginas}"
                .replace(",", ".") + "</div>", unsafe_allow_html=True)
    _tabela_simples(x.iloc[ini:ini + tam], altura, **kw)
    if n:
        st.download_button("⬇ Baixar as linhas filtradas (CSV)", _so_rotulos(x).to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), f"{chave}.csv", "text/csv", key=f"{chave}_csv")


def escolher(rotulo: str, df: pd.DataFrame, coluna_id: str, coluna_rotulo: str, chave: str,
             pedido=None, limite: int = 300, container=None, ajuda: str | None = None):
    """Seletor com busca para listas grandes (milhares de entes, fornecedores…): o navegador recebe no máximo
    `limite` opções por vez — as primeiras da ordem dada (ex.: maior valor) ou as que casam com a busca.
    Nenhum item fica inacessível: todos podem ser encontrados pela busca."""
    from .normaliza import sem_acento
    alvo = container or st
    if df is None or df.empty:
        return None
    c1, c2 = alvo.columns([2, 3])
    busca = c1.text_input(f"Buscar {rotulo.lower()}", key=f"{chave}_busca", placeholder="nome, CNPJ, UF…",
                          help=ajuda or f"A lista mostra até {limite} itens; use a busca para achar qualquer outro.")
    x = df
    if busca and busca.strip():
        t = sem_acento(busca.strip()).lower()
        txt = (x[coluna_rotulo].astype(str) + " " + x[coluna_id].astype(str)).map(sem_acento).str.lower()
        dig = "".join(ch for ch in t if ch.isdigit())
        m = txt.str.contains(t, regex=False)
        if len(dig) >= 4:
            m |= x[coluna_id].astype(str).str.contains(dig, regex=False)
        x = x[m]
    x = x.head(limite)
    if pedido is not None and pedido not in set(x[coluna_id]) and pedido in set(df[coluna_id]):
        x = pd.concat([df[df[coluna_id] == pedido], x], ignore_index=True)
    if x.empty:
        c2.info("Nada encontrado com essa busca.")
        return None
    ids = x[coluna_id].tolist()
    rot = dict(zip(ids, x[coluna_rotulo].astype(str)))
    # o pedido (ex.: ente escolhido em outra tela) só manda quando mudou desde a última vez; assim a escolha
    # feita aqui não é desfeita na volta
    ss, k, ks = st.session_state, f"{chave}_sel", f"{chave}_sinc"
    if pedido in ids and ss.get(ks) != pedido:
        ss[k] = pedido
    if ss.get(k) not in ids:
        ss.pop(k, None)
    kw = {} if k in ss else {"index": ids.index(pedido) if pedido in ids else 0}
    sel = c2.selectbox(rotulo, ids, format_func=lambda i: rot.get(i, str(i)), key=k, **kw)
    ss[ks] = sel
    return sel


def resumo_detalhe(df: pd.DataFrame, grupo: str, chave: str, valor: str = "valor", titulo_detalhe: str = "",
                   colunas_resumo: dict | None = None, nomes: str | None = None) -> None:
    """Arquitetura resumo → detalhe: primeiro uma linha por grupo (somas), ao escolher um grupo aparecem as
    linhas dele. Mostra o essencial sem esconder nada (o detalhe e o download trazem tudo)."""
    if df is None or df.empty:
        st.info("Nada a mostrar com os filtros atuais.")
        return
    agg = {"linhas": (grupo, "size")}
    if valor in df:
        agg[valor] = (valor, "sum")
    for c, f in (colunas_resumo or {}).items():
        if c in df:
            agg[c] = (c, f)
    if nomes and nomes in df:
        agg[nomes] = (nomes, "first")
    r = df.groupby(grupo, dropna=False).agg(**agg).reset_index()
    if valor in r:
        r = r.sort_values(valor, ascending=False)
        tot = r[valor].sum()
        r["part_do_total"] = r[valor] / tot if tot else None
    opcoes = r[grupo].tolist()
    rot = (lambda v: f"{r.set_index(grupo).at[v, nomes]} · {consultas.brl(r.set_index(grupo).at[v, valor])}") \
        if nomes and nomes in r and valor in r else \
        (lambda v: f"{v} · {consultas.brl(r.set_index(grupo).at[v, valor])}" if valor in r else str(v))
    c1, c2 = st.columns([2, 3])
    with c1:
        tabela(r, chave=f"{chave}_r")
    with c2:
        alvo = st.selectbox(titulo_detalhe or "Ver o detalhe de", opcoes, key=f"{chave}_alvo", format_func=rot) \
            if opcoes else None
        if alvo is not None:
            tabela(df[df[grupo] == alvo], chave=f"{chave}_d")


def baixar(nome: str, tabelas: dict[str, pd.DataFrame]) -> None:
    """Download em Excel/CSV. O arquivo só é montado quando alguém pede (antes era gerado a cada abertura da tela:
    um Excel de 50 mil linhas custava até 30 s em toda visita, mesmo sem ninguém baixar)."""
    validas = {k: v for k, v in tabelas.items() if v is not None and not v.empty}
    if not validas:
        return
    chave = f"_dl_{nome}"
    linhas = sum(len(v) for v in validas.values())
    if not st.session_state.get(chave):
        if st.button(f"⬇ Preparar download ({linhas:,} linhas)".replace(",", "."), key=f"{chave}_btn"):
            st.session_state[chave] = True
            st.rerun()
        return
    rotuladas = {}
    for k, v in validas.items():
        v = v.assign(modulo=v["modulo"].map(nome_modalidade)) if "modulo" in v.columns else v
        rotuladas[k] = _so_rotulos(v)
    xlsx = consultas.para_excel(rotuladas)
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    if xlsx:
        c1.download_button("⬇ Excel", xlsx, f"{nome}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{chave}_x")
    primeira = next(iter(rotuladas.values()))
    c2.download_button("⬇ CSV", primeira.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       f"{nome}.csv", "text/csv", key=f"{chave}_c")
    if c3.button("Fechar", key=f"{chave}_f"):
        st.session_state[chave] = False
        st.rerun()


def _so_rotulos(df: pd.DataFrame) -> pd.DataFrame:
    from .semantica import ROTULOS, TECNICAS, humanizar
    cols = [c for c in df.columns if c not in TECNICAS]
    return df[cols].rename(columns={c: ROTULOS.get(c, (humanizar(c),))[0] for c in cols})


# ------------------------------------------------------------------ gráficos
def _plotly():
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        import plotly.io as pio
        if "caixa" not in pio.templates:
            t = go.layout.Template(pio.templates["plotly_white"])
            t.layout.font = dict(family=FONTE, size=13, color="#101828")
            t.layout.colorway = [CAIXA_AZUL, CAIXA_LARANJA, "#00A19A", "#F2C500", "#8C1D40", "#9AA4B1"]
            t.layout.hoverlabel = dict(font_family=FONTE, bgcolor="white")
            t.layout.legend = dict(orientation="h", yanchor="bottom", y=1.02, x=0)
            t.layout.margin = dict(l=8, r=8, t=36, b=8)
            pio.templates["caixa"] = t
        pio.templates.default = "caixa"
        return px, go
    except ImportError:
        return None, None


def _fmt(v, formato):
    try:
        if v is None or v != v:
            return "—"
    except Exception:
        pass
    if formato == "pct":
        return consultas.pct(v)
    if formato == "int":
        return f"{int(round(v)):,}".replace(",", ".") if v == v else "—"
    return consultas.brl(v)


def _mostrar(fig, chave=None, **kw):
    cfg = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"], "locale": "pt-BR"}
    return st.plotly_chart(fig, use_container_width=True, config=cfg, key=chave, **kw)


def _g():
    from . import graficos
    return graficos if graficos.st_echarts is not None else None


def sankey(arestas: pd.DataFrame, altura: int = 560, chave: str | None = None) -> None:
    """Diagrama de fluxo (origem -> destino)."""
    if arestas is None or arestas.empty:
        st.info("Sem fluxos para os filtros atuais.")
        return
    if _g():
        cores = {v["nome"]: v["cor"] for v in MODALIDADES.values()} | {v["curto"]: v["cor"] for v in MODALIDADES.values()}
        _g().sankey(arestas, chave, altura, cores)
        return
    px, go = _plotly()
    if go is None:
        tabela(arestas)
        return
    nos = list(dict.fromkeys(list(arestas["origem"]) + list(arestas["destino"])))
    pos = {n: i for i, n in enumerate(nos)}

    def cor(n):
        for chave, c in list(BANCO_CORES.items()) + [(v["nome"], v["cor"]) for v in MODALIDADES.values()]:
            if n.endswith(chave) or n == chave:
                return c
        return "#9AA4B1"
    cor_no = [cor(n) for n in nos]
    cor_lig = [cor(d).replace("#", "") for d in arestas["destino"]]
    cor_lig = [f"rgba({int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)},0.35)" for c in cor_lig]
    fig = go.Figure(go.Sankey(
        arrangement="snap", valueformat=",.0f",
        node=dict(label=nos, pad=16, thickness=16, color=cor_no, line=dict(width=0)),
        link=dict(source=arestas["origem"].map(pos), target=arestas["destino"].map(pos), value=arestas["valor"],
                  color=cor_lig, hovertemplate="%{source.label} → %{target.label}<br>R$ %{value:,.0f}<extra></extra>")))
    fig.update_layout(height=altura, margin=dict(l=8, r=8, t=8, b=8))
    _mostrar(fig)


def agregar_bolhas(b: pd.DataFrame, cor: str | None, tam: str = "valor") -> pd.DataFrame:
    """Uma bolha por município (vários CNPJs de um município viram um ponto), cor = categoria de maior valor."""
    b = b.dropna(subset=["lat", "lon"]).copy()
    if b.empty:
        return b
    b["_v"] = pd.to_numeric(b[tam], errors="coerce").fillna(0).clip(lower=0)
    b["_cx"] = b["_v"] * pd.to_numeric(b.get("part_caixa", 0), errors="coerce").fillna(0)
    chave = b["cod_ibge"].fillna(b["cnpj_ente"]) if "cod_ibge" in b else b["cnpj_ente"]
    b["_k"] = chave.astype(str)
    rot = (b["municipio"].fillna(b["nome_ente"]) if "municipio" in b else b["nome_ente"]).astype(str) + " · " + b["uf"].astype(str)
    b["_rot"] = rot
    cat = (b.sort_values("_v").groupby("_k")[cor].last() if cor and cor in b else None)
    g = b.groupby("_k").agg(lat=("lat", "first"), lon=("lon", "first"), valor=("_v", "sum"), cx=("_cx", "sum"),
                            entes=("cnpj_ente", "nunique"), rotulo=("_rot", "first")).reset_index()
    g["part_caixa"] = g["cx"] / g["valor"].replace(0, float("nan"))
    g["cod_ibge"] = g["_k"]
    g["_cor"] = g["_k"].map(cat) if cat is not None else "Entes"
    return g[g["valor"] > 0]


def _pydeck() -> bool:
    try:
        import pydeck  # noqa: F401  (vem com o Streamlit)
        return True
    except Exception:
        return False


def _rotulo_coluna(c: str) -> str:
    from .semantica import ROTULOS
    return ROTULOS.get(c, (c,))[0].replace(" (R$)", "")


def _mapa_deck(df, geojson, coluna, formato, escala, chave, altura, bolhas, cor_bolha, tam_bolha, titulo):
    """Mapa deck.gl: enquadra a área, faixas de cor com legenda, dica ao passar o mouse e clique para detalhar."""
    import inspect

    from . import config, mapa
    b = agregar_bolhas(bolhas, cor_bolha, tam_bolha) if bolhas is not None and not bolhas.empty else None
    cores_b = {**SEGMENTO_CORES, **BANCO_CORES, **EXTRA_CORES, **{k: v["cor"] for k, v in MODALIDADES.items()}}
    try:
        fundo = (config.carregar().get("painel") or {}).get("mapa_fundo") or None
    except Exception:
        fundo = None
    deck, leg = mapa.montar(df, geojson, coluna, formato, escala, b, cores_b, titulo, altura=altura, fundo=fundo)
    params = inspect.signature(st.pydeck_chart).parameters
    kw = {"key": chave}
    if "on_select" in params:
        kw.update(on_select="rerun", selection_mode="single-object")
    if "width" in params and "use_container_width" not in params or \
            "width" in params and params["width"].default == "stretch":
        kw.update(width="stretch", height=altura)
    else:
        kw.update(use_container_width=True)
        if "height" in params:
            kw["height"] = altura
    try:
        ev = st.pydeck_chart(deck, **kw)
    except TypeError:     # Streamlit antigo, sem seleção
        ev = st.pydeck_chart(deck, use_container_width=True)
    st.markdown(mapa.legenda_html(leg), unsafe_allow_html=True)
    return mapa.clicado(ev)


def mapa_coropletico(df: pd.DataFrame, geojson: dict | None, coluna: str, formato: str, escala: str,
                     chave: str, altura: int = 560, bolhas: pd.DataFrame | None = None,
                     cor_bolha: str = "segmento", tam_bolha: str = "valor") -> str | None:
    """Mapa colorido pela métrica, com camada opcional de bolhas (entes agregados por município).
    Devolve o codarea clicado (UF ou município) ou 'mun:<código>' ao clicar numa bolha."""
    px, go = _plotly()
    if df.empty and (bolhas is None or bolhas.empty):
        st.info("Sem dados para o mapa com os filtros atuais.")
        return None
    titulo = {"part_caixa": "Participação CAIXA", "valor": "Valor contratado", "saldo_concorrente": "Saldo no concorrente",
              "potencial": "Potencial de custódia", "valor_caixa": "Valor na CAIXA",
              "valor_concorrente": "Valor no concorrente"}.get(coluna) or _rotulo_coluna(coluna)
    if geojson is not None and hasattr(st, "pydeck_chart") and _pydeck():
        return _mapa_deck(df, geojson, coluna, formato, escala, chave, altura, bolhas, cor_bolha, tam_bolha, titulo)
    if _g() and _g().mapa_disponivel() and geojson is not None:
        feats = geojson.get("features", [])
        cod0 = str(feats[0]["properties"].get("codarea", "")) if feats else ""
        nome_mapa = "BR" if len(cod0) == 2 else f"UF_{cod0[:2]}"
        b = agregar_bolhas(bolhas, cor_bolha, tam_bolha) if bolhas is not None and not bolhas.empty else None
        cores_b = {**SEGMENTO_CORES, **BANCO_CORES, **EXTRA_CORES,
                   **{k: v["cor"] for k, v in MODALIDADES.items()}}
        titulo = {"part_caixa": "Participação CAIXA", "valor": "Valor contratado", "saldo_concorrente": "Saldo no concorrente",
                  "potencial": "Potencial de custódia", "valor_caixa": "Valor na CAIXA",
                  "valor_concorrente": "Valor no concorrente"}.get(coluna, coluna)
        base = df if not df.empty else pd.DataFrame(columns=["codarea", "nome", coluna])
        return _g().mapa_brasil(base, geojson, nome_mapa, coluna, formato, chave, altura, escala, b,
                                "_cor" if b is not None else None, cores_b, titulo)
    if px is None or geojson is None:
        if geojson is None:
            st.caption("Malha do IBGE ainda não baixada (rode a carga). Mostrando a tabela.")
        if not df.empty:
            tabela(df[["nome", coluna]].sort_values(coluna, ascending=False))
        return None
    fig = go.Figure()
    if not df.empty:
        def _dica(r):
            linhas = [f"<b>{r.get('nome', '')}</b>", f"Valor: {_fmt(r.get(coluna), formato)}"]
            for c, rot, f in (("valor", "Valor contratado", "brl"), ("part_caixa", "Participação CAIXA", "pct"),
                              ("saldo_concorrente", "Saldo no concorrente", "brl"), ("potencial", "Potencial", "brl")):
                if c != coluna and c in r.index:
                    linhas.append(f"{rot}: {_fmt(r[c], f)}")
            return "<br>".join(linhas)
        texto = df.apply(_dica, axis=1)
        kwargs = dict(zmin=0, zmax=1, zmid=0.5) if formato == "pct" else {}
        fig.add_trace(go.Choropleth(
            geojson=geojson, featureidkey="properties.codarea", locations=df["codarea"], z=df[coluna].astype(float),
            colorscale=escala, marker_line_color="white", marker_line_width=0.7, text=texto,
            hovertemplate="%{text}<extra></extra>", name="",
            colorbar=dict(title="", tickformat=".0%" if formato == "pct" else "~s", thickness=12, len=0.6, x=0.98),
            **kwargs))
    if bolhas is not None and not bolhas.empty:
        b = bolhas.dropna(subset=["lat", "lon"])
        maxv = max(float(b[tam_bolha].max()), 1.0)
        grupos = list(b.groupby(cor_bolha)) if cor_bolha and cor_bolha in b else [("Municípios", b)]
        for grupo, g in grupos:
            cor = (SEGMENTO_CORES.get(grupo) or BANCO_CORES.get(grupo) or MODALIDADES.get(grupo, {}).get("cor")
                   or EXTRA_CORES.get(grupo) or "#5B6573")
            fig.add_trace(go.Scattergeo(
                lon=g["lon"], lat=g["lat"], mode="markers", name=str(grupo),
                marker=dict(size=(g[tam_bolha].clip(lower=0) / maxv) ** 0.5 * 28 + 3, color=cor, opacity=0.78,
                            line=dict(width=0.6, color="white")),
                text=g.apply(lambda r: f"<b>{r.get('nome_ente', '')}</b> · {r.get('uf', '')}<br>Valor: {_fmt(r.get(tam_bolha), 'brl')}<br>"
                                       f"CAIXA: {_fmt(r.get('part_caixa'), 'pct')} · Banco principal: {r.get('banco_principal') or '-'}<br>"
                                       f"Potencial: {_fmt(r.get('potencial_custodia', 0), 'brl')}<br>"
                                       f"{r.get('acao_recomendada') or ''}", axis=1),
                hovertemplate="%{text}<extra></extra>"))
    fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator", bgcolor="rgba(0,0,0,0)")
    fig.update_layout(height=altura, margin=dict(l=0, r=0, t=0, b=0), dragmode=False,
                      legend=dict(orientation="h", y=-0.02, x=0, title=None))
    try:
        ev = _mostrar(fig, chave, on_select="rerun", selection_mode="points")
        pts = (ev or {}).get("selection", {}).get("points", []) if isinstance(ev, dict) else \
            getattr(getattr(ev, "selection", None), "points", []) or []
        for p in pts:
            if p.get("curve_number", 0) != 0 or df.empty:
                continue
            if p.get("location"):
                return str(p["location"])
            i = p.get("point_index", p.get("point_number"))
            if i is not None and 0 <= int(i) < len(df):
                return str(df["codarea"].iloc[int(i)])
    except TypeError:
        _mostrar(fig, chave)
    return None


def ranking(df: pd.DataFrame, coluna: str, formato: str, n: int = 15, titulo: str = "", rotulo: str = "nome",
            filtro=None, valores: str | None = None, chave: str | None = None, crescente: bool = False) -> None:
    """Ranking em barras horizontais (maiores primeiro; `crescente` = menores primeiro). Com `filtro`, clicar numa
    barra filtra por ela (valor bruto em `valores`); `filtro` pode ser uma função para ações da própria tela."""
    px, go = _plotly()
    if df.empty:
        return
    top = df.dropna(subset=[coluna]).sort_values(coluna, ascending=crescente).head(n).iloc[::-1]
    if _g():
        t2 = top.iloc[::-1].assign(**{rotulo: top.iloc[::-1][rotulo].astype(str).str.slice(0, 42)})
        _g().barras(t2, rotulo, {coluna: titulo or "Valor"}, chave, formato=formato, titulo=titulo, horizontal=True,
                    altura=max(260, 26 * len(t2) + 70), cores={titulo or "Valor": CAIXA_AZUL},
                    filtro=filtro, valores=valores)
        if isinstance(filtro, str):
            st.caption("Clique numa barra para filtrar.")
        return
    if px is None:
        st.bar_chart(top.set_index(rotulo)[coluna], horizontal=True)
        return
    cores = [CAIXA_AZUL if v >= 0.5 else "#D1495B" for v in top[coluna]] if formato == "pct" else [CAIXA_AZUL] * len(top)
    fig = go.Figure(go.Bar(x=top[coluna], y=top[rotulo], orientation="h", marker_color=cores,
                           text=[_fmt(v, formato) for v in top[coluna]], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_layout(height=max(300, 26 * len(top) + 70), title=dict(text=titulo, font=dict(size=14)),
                      xaxis=dict(visible=False), yaxis=dict(automargin=True), margin=dict(l=4, r=60, t=40, b=4))
    _mostrar(fig)


def treemap(df: pd.DataFrame, caminho: list[str], valor: str, cor: str, altura: int = 520,
            chave: str | None = None) -> None:
    px, go = _plotly()
    d = df[df[valor] > 0]
    if d.empty:
        return
    if _g():
        _g().treemap(d, caminho, valor, cor, chave, altura)
        return
    if px is None:
        tabela(d[caminho + [valor, cor]].sort_values(valor, ascending=False))
        return
    fig = px.treemap(d, path=[px.Constant("Total")] + caminho, values=valor, color=cor,
                     color_continuous_scale="RdBu", range_color=(0, 1), color_continuous_midpoint=0.5)
    fig.update_traces(hovertemplate="<b>%{label}</b><br>Valor: R$ %{value:,.0f}<br>CAIXA: %{color:.0%}<extra></extra>",
                      textinfo="label+value", texttemplate="<b>%{label}</b><br>R$ %{value:.3s}")
    fig.update_layout(height=altura, margin=dict(l=0, r=0, t=10, b=0), coloraxis_colorbar=dict(tickformat=".0%", title=""))
    _mostrar(fig)


def linha_participacao(serie: pd.DataFrame, altura: int = 380) -> None:
    """Valor por banco (barras empilhadas) e participação CAIXA (linha) por ano."""
    px, go = _plotly()
    if serie is None or serie.empty:
        st.info("Sem série anual.")
        return
    part = serie.get("CAIXA", 0) / serie.sum(axis=1)
    if _g():
        x = serie.reset_index()
        x.columns = ["ano"] + [str(c) for c in serie.columns]
        x["ano"] = x["ano"].astype(str)
        _g().barras(x, "ano", {str(c): str(c) for c in serie.columns}, None, titulo="Valor por banco e ano", altura=altura,
                    cores={str(c): cor_banco(c) for c in serie.columns})
        _g().linha_tempo(pd.DataFrame({"ano": x["ano"], "pct": part.values}), "ano", "pct", None, formato="pct",
                         titulo="Participação CAIXA no ano", area=True, altura=220, cores={None: "#0B3D91"})
        return
    if px is None:
        st.bar_chart(serie, stack=True)
        st.line_chart(part.rename("Participação CAIXA"))
        return
    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for b in serie.columns:
        fig.add_bar(x=serie.index, y=serie[b], name=b, marker_color=cor_banco(b), secondary_y=False,
                    hovertemplate=f"{b} · %{{x}}: R$ %{{y:,.0f}}<extra></extra>")
    fig.add_scatter(x=part.index, y=part, name="% CAIXA", mode="lines+markers+text",
                    line=dict(color="#0B3D91", width=3), text=[f"{v:.0%}" for v in part], textposition="top center",
                    secondary_y=True, hovertemplate="%{x}: %{y:.0%}<extra></extra>")
    fig.update_layout(barmode="stack", height=altura)
    fig.update_yaxes(title_text="R$", tickformat="~s", secondary_y=False)
    fig.update_yaxes(tickformat=".0%", range=[0, 1.08], secondary_y=True, showgrid=False)
    _mostrar(fig)


def barras_modalidade(df: pd.DataFrame, eixo: str, valor: str = "valor", altura: int = 420,
                      cor_por: str = "modulo", titulo: str = "", ordenar: bool = True,
                      filtro: str | bool | None = True) -> None:
    """Barras empilhadas por modalidade (ou banco) ao longo de um eixo (UF, ano...).
    Clicar numa barra filtra pelo eixo (UF, ano, modalidade…) quando ele é uma dimensão conhecida."""
    px, go = _plotly()
    if df.empty:
        return
    t = df.pivot_table(index=eixo, columns=cor_por, values=valor, aggfunc="sum", fill_value=0)
    t = t.loc[t.sum(axis=1).sort_values(ascending=False).index] if ordenar else t.sort_index()
    if _g():
        nomes = {c: (nome_modalidade(c, curto=True) if cor_por == "modulo" else str(c)) for c in t.columns}
        cores = {nomes[c]: (MODALIDADES.get(c, {}).get("cor") if cor_por == "modulo" else cor_banco(c)) for c in t.columns}
        x = t.reset_index()
        dim = (eixo if filtro is True and eixo in interacao.DIMENSOES else (filtro or None)) if filtro else None
        if dim:
            x["_bruto"] = x[eixo]
        x[eixo] = x[eixo].astype(str)
        _g().barras(x, eixo, {c: nomes[c] for c in t.columns}, f"bm_{eixo}_{cor_por}_{abs(hash(titulo)) % 10**6}",
                    titulo=titulo, altura=altura, cores=cores, filtro=dim, valores="_bruto" if dim else None)
        return
    if px is None:
        st.bar_chart(t, stack=True)
        return
    fig = go.Figure()
    for c in t.columns:
        nome = nome_modalidade(c, curto=True) if cor_por == "modulo" else c
        cor = MODALIDADES.get(c, {}).get("cor") if cor_por == "modulo" else cor_banco(c)
        fig.add_bar(x=t.index, y=t[c], name=nome, marker_color=cor,
                    hovertemplate=f"{nome} · %{{x}}: R$ %{{y:,.0f}}<extra></extra>")
    fig.update_layout(barmode="stack", height=altura, title=dict(text=titulo, font=dict(size=14)),
                      yaxis=dict(tickformat="~s", title="R$"))
    _mostrar(fig)


def rosca(valores: pd.Series, titulo: str = "", cores: dict | None = None, altura: int = 300,
          chave: str | None = None, filtro: str | None = None, nomes: dict | None = None) -> None:
    """Rosca de composição. Com `filtro`, clicar numa fatia filtra por ela."""
    px, go = _plotly()
    v = valores[valores > 0]
    if v.empty:
        return
    if _g():
        _g().rosca(v, chave, titulo, cores, altura, filtro=filtro, nomes=nomes)
        return
    if px is None:
        st.bar_chart(v)
        return
    cores = cores or {}
    fig = go.Figure(go.Pie(labels=v.index, values=v.values, hole=0.62, sort=False,
                           marker=dict(colors=[cores.get(k, "#9AA4B1") for k in v.index], line=dict(color="white", width=2)),
                           textinfo="percent", hovertemplate="%{label}: R$ %{value:,.0f} (%{percent})<extra></extra>"))
    fig.update_layout(height=altura, title=dict(text=titulo, font=dict(size=14)), showlegend=True,
                      legend=dict(orientation="v", x=1, y=0.5), margin=dict(l=4, r=4, t=40, b=4))
    _mostrar(fig)


def dispersao(df: pd.DataFrame, x: str, y: str, tamanho: str, rotulo: str, titulo: str = "",
              cor: str | None = None, linha_y: float | None = 0.5, altura: int = 460, formato_y: str = "pct") -> None:
    """Quadrante de prioridade: valor (x, escala log) × participação CAIXA (y). Canto inferior direito = agir."""
    px, go = _plotly()
    d = df[(df[x] > 0)].dropna(subset=[y])
    if d.empty:
        return
    if _g():
        d = d.assign(_faixa=[("CAIXA ≥ 50%" if v >= 0.5 else "CAIXA < 50%") for v in d[y]]) if cor is None else d
        _g().quadrante(d, x, y, tamanho, rotulo, None, cor_por=cor or "_faixa",
                       cores={"CAIXA ≥ 50%": CAIXA_AZUL, "CAIXA < 50%": "#D1495B"}, linha_y=linha_y,
                       titulo=titulo, altura=altura, nome_x="Valor", nome_y="Participação CAIXA", formato_y=formato_y)
        return
    if px is None:
        st.scatter_chart(d, x=x, y=y, size=tamanho) if hasattr(st, "scatter_chart") else tabela(d[[rotulo, x, y]])
        return
    maxs = max(float(d[tamanho].max()), 1.0)
    fig = go.Figure(go.Scatter(
        x=d[x], y=d[y], mode="markers", text=d[rotulo],
        marker=dict(size=(d[tamanho] / maxs) ** 0.5 * 34 + 5, opacity=0.75, line=dict(width=0.6, color="white"),
                    color=[CAIXA_AZUL if v >= 0.5 else "#D1495B" for v in d[y]] if cor is None else d[cor]),
        hovertemplate="<b>%{text}</b><br>Valor: R$ %{x:,.0f}<br>CAIXA: %{y:.0%}<extra></extra>"))
    if linha_y is not None:
        fig.add_hline(y=linha_y, line_dash="dot", line_color="#9AA4B1")
    fig.update_layout(height=altura, title=dict(text=titulo, font=dict(size=14)),
                      xaxis=dict(type="log", title="Valor (R$, escala log)", tickformat="~s"),
                      yaxis=dict(title="Participação CAIXA", tickformat=".0%", range=[-0.05, 1.05]))
    _mostrar(fig)
