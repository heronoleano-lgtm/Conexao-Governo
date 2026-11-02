"""Simulador mínimo do Streamlit: executa as telas e registra o que seria desenhado.

Valida tipos dos argumentos principais para pegar erros que só apareceriam no navegador.
"""
from __future__ import annotations

import types

import pandas as pd


class Parar(Exception):
    pass


class _Bloco:
    def __init__(self, reg):
        self._reg = reg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, nome):
        return getattr(_api(self._reg), nome)


_estado: dict = {}


def _api(reg):
    ns = types.SimpleNamespace()

    def anota(nome, *a, **k):
        reg.append((nome, a, k))

    def _df_ok(df):
        if hasattr(df, "data") and hasattr(df, "format"):  # pandas Styler
            df = df.data
        assert isinstance(df, (pd.DataFrame, pd.Series)), f"dataframe recebeu {type(df)}"

    ns.title = ns.subheader = ns.caption = ns.info = ns.warning = ns.error = ns.success = \
        lambda *a, **k: anota("texto", *a, **k)

    def markdown(txt, *a, **k):
        # cartões de indicador (HTML) contam como métrica; o texto vai para o registro para inspeção
        anota("metric" if 'class="cx-cartao"' in str(txt) else "texto", txt)
    ns.markdown = markdown
    ns.divider = lambda *a, **k: anota("divider")
    ns.json = lambda *a, **k: anota("json", *a)

    def metric(label, value, *a, **k):
        assert isinstance(label, str)
        assert isinstance(value, (str, int, float)) or value is None, f"metric {label}: {type(value)}"
        anota("metric", label, value)
    ns.metric = metric

    def dataframe(df, *a, **k):
        _df_ok(df)
        cfg = k.get("column_config") or {}
        for nome in cfg:
            assert nome in df.columns, f"column_config para coluna inexistente: {nome}"
        anota("dataframe", df)
    ns.dataframe = dataframe

    def chart(df, *a, **k):
        _df_ok(df)
        assert not df.empty, "gráfico vazio"
        anota("chart", df, **k)
    ns.bar_chart = ns.line_chart = chart

    def mapa(df, latitude, longitude, size=None, color=None, **k):
        for c in (latitude, longitude, size, color):
            assert c is None or c in df.columns, c
        anota("map", df)
    ns.map = mapa

    def multiselect(label, options, default=None, key=None, **k):
        ops = list(options)
        if key is not None and key in _estado:
            v = list(_estado[key])
            assert all(x in ops for x in v), f"multiselect {label}: valor fora das opções {v}"
            assert default is None, f"multiselect {label}: key com default (o Streamlit avisa)"
            return v
        return list(default) if default is not None else []
    ns.multiselect = multiselect

    def selectbox(label, options, index=0, format_func=str, key=None, **k):
        opts = list(options)
        if not opts:
            return None
        v = _estado[key] if key is not None and _estado.get(key) in opts else opts[index or 0]
        format_func(v)
        return v
    ns.selectbox = selectbox
    ns.slider = lambda label, a=None, b=None, value=None, *r, **k: value if value is not None else a
    ns.select_slider = lambda label, options=(), value=None, **k: value if value is not None else list(options)[0]
    ns.number_input = lambda label, min_value=None, value=0.0, **k: value
    ns.text_input = lambda label, value="", **k: value
    ns.text_area = lambda label, value="", **k: value
    ns.button = lambda *a, **k: False
    ns.checkbox = lambda label, value=False, **k: value
    def radio(label, options, index=0, key=None, **k):
        ops = list(options) or [None]
        if key is not None and key in _estado and _estado[key] in ops:
            return _estado[key]
        return ops[index if index is not None and index < len(ops) else 0]
    ns.radio = radio

    def page_link(pagina, *a, **k):
        from pathlib import Path as _P
        alvo = _P(__file__).resolve().parents[1] / "telas" / str(pagina)
        assert alvo.exists(), f"page_link para tela inexistente: {pagina}"
        anota("link", str(pagina))
    ns.page_link = page_link
    ns.logo = lambda *a, **k: anota("logo")

    class _Pagina:
        def __init__(self, arquivo, title=None, icon=None, default=False, **k):
            self.arquivo, self.title = arquivo, title
    ns.Page = _Pagina

    class _Nav:
        def __init__(self, menu):
            self.menu = menu
        def run(self):
            anota("navigation", self.menu)
    ns.navigation = lambda menu, **k: _Nav(menu)
    ns.container = lambda *a, **k: _Bloco(reg)
    ns.switch_page = lambda *a, **k: None
    ns.plotly_chart = lambda fig, **k: anota("chart", fig)
    ns.toggle = lambda label, value=False, **k: value
    ns.date_input = lambda label, value=None, **k: value

    def pydeck_chart(pydeck_obj=None, *, use_container_width=None, width="stretch", height=500,
                     selection_mode="single-object", on_select="ignore", key=None):
        import json as _json
        j = _json.loads(pydeck_obj.to_json())          # mapa inválido quebra o teste
        anota("mapa", j)
        clique = (getattr(ns, "_cliques", None) or {}).get(key)
        objs = {"areas": [{"codarea": clique, "properties": {"codarea": clique}}]} if clique else {}
        return {"selection": {"indices": {}, "objects": objs}}
    ns.pydeck_chart = pydeck_chart
    ns.form_submit_button = lambda *a, **k: False
    ns.download_button = lambda label, data, *a, **k: anota("download", label, len(data))
    ns.columns = lambda spec, **k: [_Bloco(reg) for _ in range(spec if isinstance(spec, int) else len(spec))]
    ns.tabs = lambda nomes: [_Bloco(reg) for _ in nomes]
    ns.form = lambda *a, **k: _Bloco(reg)
    ns.expander = lambda *a, **k: _Bloco(reg)
    return ns


def criar(sessao: dict | None = None):
    reg: list = []
    st = types.ModuleType("streamlit")
    for k, v in vars(_api(reg)).items():
        setattr(st, k, v)
    st.registro = reg
    st.session_state = dict(sessao or {})
    global _estado
    _estado = st.session_state
    st.query_params = {}
    st.sidebar = _Bloco(reg)
    st.set_page_config = lambda **k: None

    def cache_data(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f
    st.cache_data = cache_data

    def cache_resource(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f
    st.cache_resource = cache_resource

    def fragment(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f
    st.fragment = fragment

    def stop():
        raise Parar()
    st.stop = stop
    st.rerun = stop
    def coluna(tipo):
        def f(label=None, *a, help=None, format=None, **k):
            return (tipo, label, format)
        return f
    cc = types.SimpleNamespace(NumberColumn=coluna("num"), ProgressColumn=coluna("prog"),
                               TextColumn=coluna("txt"), CheckboxColumn=coluna("chk"))
    st.column_config = cc
    return st
