"""Exercita os caminhos ECharts e AgGrid com simuladores (os pacotes não estão no ambiente de teste)."""
from __future__ import annotations

import importlib
import json
import sys

import pandas as pd

from tests import st_stub


class _Js:
    def __init__(self, code):
        assert code.strip().startswith("function"), code[:40]
        self.js_code = f"--x_x--0_0--{code}--x_x--0_0--"


def _carregar(monkeypatch):
    st = st_stub.criar({})
    sys.modules["streamlit"] = st
    import custodia.graficos as g
    importlib.reload(g)
    chamadas = []

    def fake_echarts(options, height, key=None, events=None, **k):
        json.dumps(options)  # tem de ser serializável
        assert height.endswith("px")
        chamadas.append(options)
        return None
    monkeypatch.setattr(g, "st_echarts", fake_echarts)
    monkeypatch.setattr(g, "JsCode", _Js)
    return g, chamadas


def test_echarts_componentes(monkeypatch):
    g, ch = _carregar(monkeypatch)
    g.gauge(0.42, "Participação", "k1", meta=0.6)
    g.radar(["A", "B", "C"], {"Ente": [10, 50, 90], "Pares": [30, 30, 30]}, "k2")
    df = pd.DataFrame({"x": ["CAIXA", "BB", "CAIXA"], "y": ["BB", "CAIXA", "CAIXA"], "v": [3, 4, 5]})
    g.heatmap(df, "x", "y", "v", "k3", formato="int")
    g.funil([("Total", 100.0), ("CAIXA", 40.0)], "k4")
    g.barras(pd.DataFrame({"c": ["a", "b"], "s1": [1.0, None], "s2": [3.0, 4.0]}), "c", {"s1": "S1", "s2": "S2"}, "k5",
             horizontal=True)
    g.linha_tempo(pd.DataFrame({"d": ["2026-10-01", "2026-10-02", "2026-10-01"], "v": [1.0, 2.0, 3.0],
                                "b": ["CAIXA", "CAIXA", "BB"]}), "d", "v", "k6", cor_por="b")
    g.quadrante(pd.DataFrame({"p": [1e6, 5e6, 2e5], "c": [80, 20, 60], "n": ["A", "B", "C"], "q": ["x", "y", "x"]}),
                "p", "c", "p", "n", "k7", cor_por="q", linha_x=1e6, linha_y=50)
    assert len(ch) == 7
    assert ch[0]["series"][0]["type"] == "gauge" and len(ch[0]["series"]) == 2
    assert ch[2]["series"][0]["type"] == "heatmap" and len(ch[2]["series"][0]["data"]) == 3
    assert ch[4]["series"][0]["data"] == [1.0, None]
    assert ch[6]["series"][0]["markLine"]["data"] == [{"xAxis": 1e6}, {"yAxis": 50.0}]


def test_aggrid_grade(monkeypatch):
    g, _ = _carregar(monkeypatch)
    conf = {}

    class GOB:
        @staticmethod
        def from_dataframe(df):
            conf["cols"] = list(df.columns)
            return GOB()

        def configure_default_column(self, **k):
            pass

        def configure_column(self, nome, **k):
            assert nome in conf["cols"], nome
            conf.setdefault("cfg", {}).setdefault(nome, {}).update(k)

        def configure_selection(self, *a, **k):
            pass

        def configure_pagination(self, **k):
            pass

        def configure_grid_options(self, **k):
            pass

        def build(self):
            return {"ok": True}

    class Modo:
        SELECTION_CHANGED, NO_UPDATE = "sel", "none"

    def fake_aggrid(df, gridOptions, **k):
        return {"selected_rows": pd.DataFrame([df.iloc[0].to_dict()])}
    monkeypatch.setattr(g, "AgGrid", fake_aggrid)
    monkeypatch.setattr(g, "GridOptionsBuilder", GOB, raising=False)
    monkeypatch.setattr(g, "GridUpdateMode", Modo, raising=False)
    monkeypatch.setattr(g, "AgJs", _Js, raising=False)
    df = pd.DataFrame({"cnpj_ente": ["1"], "nome_ente": ["A"], "valor_em_risco": [10.0], "var_mes_pct": [-0.2],
                       "part_caixa": [0.4]})
    sel = g.grade(df, "kg", selecao=True)
    assert sel == {"cnpj_ente": "1", "nome_ente": "A", "valor_em_risco": 10.0, "var_mes_pct": -0.2, "part_caixa": 0.4}
    assert "Ente" in conf["cols"] and conf["cfg"]["Ente"].get("pinned") == "left"
    assert "valueFormatter" in conf["cfg"]["Valor em risco (R$)"]


def test_mapa_e_composicao_echarts(monkeypatch):
    g, ch = _carregar(monkeypatch)
    monkeypatch.setattr(g, "EMap", lambda nome, geo: ("mapa", nome))
    import custodia.ui as ui
    geo = {"type": "FeatureCollection", "features": [{"properties": {"codarea": "31"}}, {"properties": {"codarea": "35"}}]}
    uf = pd.DataFrame({"codarea": ["31", "35"], "nome": ["MG", "SP"], "valor": [10.0, 20.0], "part_caixa": [0.4, 0.7],
                       "saldo_concorrente": [1.0, 2.0], "potencial": [3.0, 4.0]})
    entes = pd.DataFrame({"cnpj_ente": ["a", "b", "c"], "nome_ente": ["P1", "F1", "P2"], "uf": ["MG", "MG", "SP"],
                          "cod_ibge": ["3100104", "3100104", "3550308"], "municipio": ["ALFA", "ALFA", "SAO PAULO"],
                          "lat": [-19.0, -19.0, -23.5], "lon": [-44.0, -44.0, -46.6], "valor": [5.0, 7.0, 9.0],
                          "part_caixa": [1.0, 0.0, 0.5], "segmento": ["Disputado", "Território CAIXA", "Disputado"]})
    b = ui.agregar_bolhas(entes, "segmento")
    assert len(b) == 2 and b.loc[b["cod_ibge"] == "3100104", "entes"].iloc[0] == 2   # 2 CNPJs, 1 município
    assert abs(b.loc[b["cod_ibge"] == "3100104", "part_caixa"].iloc[0] - 5 / 12) < 1e-9
    g.mapa_brasil(uf, geo, "BR", "part_caixa", "pct", "km", bolhas=b, cor_bolha="_cor")
    op = ch[-1]
    assert op["geo"]["nameProperty"] == "codarea" and op["series"][0]["type"] == "map"
    assert {s["type"] for s in op["series"][1:]} == {"scatter"}
    g.rosca(pd.Series({"CAIXA": 3.0, "BB": 1.0}), "kr")
    g.sankey(pd.DataFrame({"origem": ["A", "A"], "destino": ["Conta CAIXA", "Conta BB"], "valor": [1.0, 2.0]}), "ks")
    g.treemap(pd.DataFrame({"m": ["x", "x", "y"], "o": ["a", "b", "c"], "v": [1.0, 2.0, 3.0], "p": [0.1, 0.9, 0.5]}),
              ["m", "o"], "v", "p", "kt")
    tipos = [o["series"][0]["type"] for o in ch[-3:]]
    assert tipos == ["pie", "sankey", "treemap"]


def test_clique_no_grafico_vira_filtro_uma_vez(monkeypatch):
    """Clicar numa barra aplica o filtro (com o valor bruto, não o rótulo); o mesmo clique devolvido de novo pelo
    componente na execução seguinte NÃO reaplica (senão o filtro ligaria e desligaria sozinho)."""
    g, ch = _carregar(monkeypatch)
    from custodia import interacao
    resposta = {"v": "1|SP|1730000000000"}
    monkeypatch.setattr(g, "st_echarts", lambda options, height, key=None, events=None, **k:
                        (ch.append((options, events)), resposta["v"])[1])
    rerun = []
    monkeypatch.setattr(g.st if hasattr(g, "st") else None, "rerun", lambda: rerun.append(1), raising=False)
    import streamlit as st_mod
    monkeypatch.setattr(st_mod, "rerun", lambda: rerun.append(1))
    df = pd.DataFrame({"nome": ["Minas", "São Paulo"], "uf": ["MG", "SP"], "v": [1.0, 2.0]})
    g.barras(df, "nome", {"v": "Valor"}, "rk", filtro="uf", valores="uf")
    assert "click" in (ch[-1][1] or {})
    assert st_mod.session_state[interacao.PENDENTE]["uf"] == ["SP"] and rerun == [1]
    g.barras(df, "nome", {"v": "Valor"}, "rk", filtro="uf", valores="uf")      # mesmo evento: ignora
    assert rerun == [1]
    resposta["v"] = "0|MG|1730000000999"                                         # clique novo em outra barra
    g.barras(df, "nome", {"v": "Valor"}, "rk", filtro="banco_principal", valores="nome")
    assert st_mod.session_state[interacao.EXTRA] == {"banco_principal": ["Minas"]} and rerun == [1, 1]
    # ação própria da tela (ex.: descer no mapa) em vez de filtro
    alvo = []
    resposta["v"] = "1|SP|1730000001000"
    g.barras(df, "nome", {"v": "Valor"}, "rk2", filtro=lambda v, n: alvo.append((v, n)), valores="uf")
    assert alvo == [("SP", "São Paulo")]


def test_aplicar_pendentes_sincroniza_barra_lateral(monkeypatch):
    _carregar(monkeypatch)
    import streamlit as st_mod
    from custodia import interacao
    ss = st_mod.session_state
    ss.clear()
    ops = {"modulo": ["Especiais", "Fundo a Fundo"], "ano": [2024, 2025], "uf": ["MG", "SP"]}
    interacao.aplicar_pendentes(ops)
    assert ss["f_mod"] == ops["modulo"] and ss["f_uf"] == []
    ss[interacao.PENDENTE] = {"uf": ["SP"], "modulo": ["Especiais"]}
    interacao.aplicar_pendentes(ops)
    assert ss["f_uf"] == ["SP"] and ss["f_mod"] == ["Especiais"]
    ss["f_uf"] = ["XX"]                      # valor de outra carga: não pode quebrar o filtro
    interacao.aplicar_pendentes(ops)
    assert ss["f_uf"] == []
