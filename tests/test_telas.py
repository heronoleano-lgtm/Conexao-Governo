"""Executa todas as telas com o simulador do Streamlit sobre uma carga de teste."""
from __future__ import annotations

import importlib
import json
import runpy
import sys
from datetime import date
from pathlib import Path

import pytest

from custodia import acesso, config, pipeline
from custodia.http import Cliente
from tests import st_stub
from tests.fake_api import BASE, SessaoFalsa

APP = Path(__file__).resolve().parents[1] / "telas"
INCORPORADAS = {f"pages/{t.name}" for t in (APP / "pages").glob("*.py") if "TELA_INCORPORADA" in t.read_text("utf-8")}
TELAS = [APP / "Inicio.py"] + sorted(t for t in (APP / "pages").glob("*.py") if f"pages/{t.name}" not in INCORPORADAS) \
    + sorted((APP / "visoes").glob("*.py"))


@pytest.fixture(scope="module")
def carga(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dados")
    mp = pytest.MonkeyPatch()
    mp.setenv("CUSTODIA_DADOS", str(tmp / "data"))
    config.carregar.cache_clear()
    cfg = json.loads(json.dumps(config.carregar()))
    cfg["motores"]["saldo_alto_concorrente"] = 500_000
    cfg["portal_api"].update({"intervalo_fixo": 0})       # simulador: sem espera entre chamadas
    cfg["portal_api"]["recursos"]["meses"] = 2
    cam = config.caminhos(cfg)
    cam.criar()
    dados = SessaoFalsa().dados
    for dia in (date(2026, 11, 3), date(2026, 11, 4)):
        if dia.day == 4:
            dados["especiais"]["planos-acao-especiais"][0]["codigo_banco_plano_acao"] = "001"
        m = pipeline.baixar(cfg, cam, dia, Cliente(BASE, "t", sessao=SessaoFalsa(dados)))
        pipeline.transformar(cfg, cam, dia, m)
    usuarios = tmp / "usuarios.yaml"
    acesso.gravar_usuario("ana", "Ana", "comercial", "senha-segura", usuarios)
    mp.setattr(acesso, "ler_usuarios", lambda arquivo=None, _u=usuarios: acesso.yaml.safe_load(
        _u.read_text("utf-8"))["usuarios"])
    yield cam
    mp.undo()


def _rodar(tela: Path, sessao: dict):
    st = st_stub.criar(sessao)
    sys.modules["streamlit"] = st
    import custodia.ui as ui
    importlib.reload(ui)
    try:
        runpy.run_path(str(tela), run_name="__main__")
    except st_stub.Parar:
        pass
    return st.registro


def test_login_obrigatorio(carga):
    reg = _rodar(TELAS[0], {})
    assert not any(n == "metric" for n, *_ in reg), "mostrou dados sem login"


def test_autenticacao(carga):
    assert acesso.autenticar("ana", "senha-segura")["perfil"] == "comercial"
    assert acesso.autenticar("ana", "errada") is None


@pytest.mark.parametrize("tela", TELAS, ids=lambda p: p.stem)
def test_tela_renderiza(carga, tela):
    perfil = "gestao" if "onformidade" in tela.stem else "comercial"
    reg = _rodar(tela, {"usuario": {"login": "ana", "nome": "Ana", "perfil": perfil}})
    tipos = {n for n, *_ in reg}
    assert "metric" in tipos or "dataframe" in tipos, f"{tela.stem} não desenhou nada: {tipos}"


def test_carteira(carga):
    acesso.salvar_carteira("44444444000104", "abordado", "Ana", "Visita marcada", "ana")
    acesso.salvar_carteira("44444444000104", "proposta enviada", "Ana", "Proposta de conta", "ana")
    assert acesso.carteira().set_index("cnpj_ente").at["44444444000104", "status"] == "proposta enviada"
    assert len(acesso.historico_carteira("44444444000104")) == 2


def test_conformidade_restrita(carga):
    """A visão da Portaria 15/2025 só aparece para gestão e administrador (nem roda para o comercial)."""
    reg = _rodar(APP / "visoes" / "conformidade_portaria.py", {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}})
    assert not any(n in ("metric", "dataframe") for n, *_ in reg)
    hub = _rodar(APP / "pages" / "31_CRM_Conformidade.py",
                 {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}})
    assert not any("Portaria" in str(a) for n, a, k in hub if n == "texto" and "15/2025 ·" in str(a))


def test_visoes_compartilham_o_ente(carga):
    """Telas que viraram visões: a tela-mãe roda a visão pedida e o ente escolhido vale em todas."""
    sess = {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}, "ente_visao_pedido": "Ficha técnica"}
    reg = _rodar(APP / "pages" / "28_CRM_Visao_360.py", sess)
    assert any(n == "dataframe" for n, *_ in reg)
    for stub in INCORPORADAS:
        assert (APP / stub).exists()
    assert len(INCORPORADAS) == 6


def test_mapa_drill_uf_e_municipio(carga):
    tela = next(t for t in TELAS if "Mapa" in t.stem)
    reg = _rodar(tela, {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"},
                        "terr_uf": "MG", "terr_mun": "3100104"})
    tabelas = [a[0] for n, a, k in reg if n == "dataframe"]
    assert any("Ente" in t.columns and "MUNICIPIO DE ALFA" in set(t["Ente"]) for t in tabelas
               if hasattr(t, "columns"))


@pytest.mark.parametrize("tela", TELAS, ids=lambda p: p.stem)
def test_sem_coluna_tecnica_na_tela(carga, tela):
    """Toda tabela exibida usa só nomes de negócio do dicionário semântico (nada de 'n', 'hhi_entes'...)."""
    from custodia.semantica import ROTULOS
    validos = {v[0] for v in ROTULOS.values()}
    perfil = "gestao" if "onformidade" in tela.stem else "comercial"
    reg = _rodar(tela, {"usuario": {"login": "ana", "nome": "Ana", "perfil": perfil}})
    ruins = set()
    for n, a, k in reg:
        if n != "dataframe":
            continue
        df = a[0].data if hasattr(a[0], "format") else a[0]
        nomes = list(df.columns) if hasattr(df, "columns") else [df.name]
        for c in nomes:
            if not any(str(c) == v or str(c).startswith(v + " (") for v in validos):
                ruins.add(str(c))
    assert not ruins, f"{tela.stem} mostra colunas sem rótulo de negócio: {sorted(ruins)}"


def test_menu_registra_todas_as_telas(carga):
    """O menu (app.py) registra todas as telas existentes, e cada tela registrada existe."""
    for perfil in ("comercial", "gestao"):
        reg = _rodar(APP / "app.py", {"usuario": {"login": "ana", "nome": "Ana", "perfil": perfil}})
        menu = next(a[0] for n, a, k in reg if n == "navigation")
        arquivos = {p.arquivo for paginas in menu.values() for p in paginas}
        for arq in arquivos:
            assert (APP / arq).exists(), arq
        esperado = ({"Inicio.py"} | {f"pages/{t.name}" for t in (APP / "pages").glob("*.py")}) - INCORPORADAS
        assert arquivos == esperado, esperado ^ arquivos


@pytest.fixture()
def plotly_falso(monkeypatch):
    """Reproduz o Windows nos testes: Plotly instalado e ECharts indisponível no simulador (a 0.7 do
    streamlit-echarts se registra no Streamlit ao ser importada, o que o simulador não suporta)."""
    from unittest.mock import MagicMock
    import types
    pl = types.ModuleType("plotly")
    for sub in ("express", "graph_objects", "io", "subplots"):
        m = MagicMock(name=f"plotly.{sub}")
        setattr(pl, sub, m)
        monkeypatch.setitem(sys.modules, f"plotly.{sub}", m)
    monkeypatch.setitem(sys.modules, "plotly", pl)
    if "streamlit" not in sys.modules:
        monkeypatch.setitem(sys.modules, "streamlit", st_stub.criar({}))
    from custodia import graficos
    monkeypatch.setattr(graficos, "st_echarts", None)
    monkeypatch.setattr(graficos, "mapa_disponivel", lambda: False)
    yield


@pytest.mark.parametrize("tela", TELAS, ids=lambda p: p.stem)
def test_tela_renderiza_com_plotly(carga, plotly_falso, tela):
    perfil = "gestao" if "onformidade" in tela.stem else "comercial"
    reg = _rodar(tela, {"usuario": {"login": "ana", "nome": "Ana", "perfil": perfil}})
    assert not any(n == "error" for n, *_ in reg), [r for r in reg if r[0] == "error"]


def test_clique_echarts_07():
    """A 0.7 do streamlit-echarts devolve o clique em `chart_event`; versões antigas devolvem o valor direto."""
    from custodia.graficos import _evento

    class Res(dict):
        def __getattr__(self, k):
            return self.get(k)
    assert _evento("31") == "31"
    assert _evento(Res(chart_event="mun:3100104")) == "mun:3100104"
    assert _evento(Res()) is None and _evento(None) is None


def test_mapa_deck_e_clique(carga):
    """O mapa usa deck.gl (pydeck): enquadra o Brasil, pinta por faixas e o clique na UF abre os municípios."""
    tela = next(t for t in TELAS if "Mapa" in t.stem)
    reg = _rodar(tela, {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}})
    mapas = [a[0] for n, a, k in reg if n == "mapa"]
    assert mapas, "a tela não desenhou o mapa deck.gl"
    j = mapas[0]
    camadas = {c["id"]: c for c in j["layers"]}
    assert "areas" in camadas and camadas["areas"]["lineWidthUnits"] == "pixels"
    assert 1 <= j["initialViewState"]["zoom"] <= 12
    assert not j.get("mapStyle") and not j.get("mapProvider")   # sem mapa de ruas (rede corporativa)
    assert any("cx-leg" in str(a[0]) for n, a, k in reg if n == "texto" and a)


def test_clicado():
    from custodia.mapa import clicado
    assert clicado({"selection": {"objects": {"areas": [{"properties": {"codarea": "31"}}]}}}) == "31"
    assert clicado({"selection": {"objects": {"bolhas": [{"codarea": "mun:3100104"}],
                                              "areas": [{"codarea": "31"}]}}}) == "mun:3100104"
    assert clicado({"selection": {"objects": {}}}) is None and clicado(None) is None


@pytest.mark.parametrize("etapa", ["1 · De onde vem", "2 · Onde fica (custódia)", "3 · Para onde vai"])
def test_fluxo_tres_etapas(carga, etapa):
    reg = _rodar(APP / "pages" / "01_Fluxo_do_dinheiro.py",
                 {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}, "fluxo_etapa": etapa})
    textos = " ".join(str(a[0]) for n, a, _ in reg if n == "texto" and a)
    assert "Conferência" in textos and "⚠" not in textos, "conta reversa do fluxo não fechou"


@pytest.mark.parametrize("modo", ["Principais relações (80/20)", "Rede completa"])
def test_rede_dois_modos_sem_cnpj_como_nome(carga, modo):
    reg = _rodar(APP / "pages" / "30_CRM_Rede_de_relacionamento.py",
                 {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}, "rede_modo": modo})
    assert any(n in ("metric", "dataframe") for n, *_ in reg)


def test_mapa_com_filtros_e_oportunidades(carga):
    sess = {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"},
            "mapa_f": {"faixas": ["Concorrente lidera (menos de 30%)", "Sem CAIXA (0%)"], "camada": "Áreas + oportunidades CRM",
                       "prio_min": 0, "valor_min": 0.0}, "mapa_rank": "Menor participação CAIXA"}
    reg = _rodar(APP / "pages" / "02_Mapa_da_custodia.py", sess)
    assert any(n == "metric" for n, *_ in reg)
    sess["terr_uf"] = "MG"
    reg = _rodar(APP / "pages" / "02_Mapa_da_custodia.py", sess)
    assert any(n == "mapa" for n, *_ in reg)


def test_download_so_quando_pedido(carga):
    sess = {"usuario": {"login": "ana", "nome": "Ana", "perfil": "comercial"}}
    reg = _rodar(TELAS[0], sess)
    assert not any(n == "download" for n, *_ in reg)               # abrir a tela não monta arquivo
    reg = _rodar(TELAS[0], {**sess, "_dl_entes_do_recorte": True})
    assert any(n == "download" for n, *_ in reg)                   # pedido: Excel/CSV prontos
