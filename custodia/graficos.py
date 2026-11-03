"""Gráficos executivos com ECharts (streamlit-echarts) e tabelas profissionais com AgGrid (streamlit-aggrid).

Cada componente tenta, nesta ordem: ECharts/AgGrid → Plotly → gráfico/tabela nativos do Streamlit.
Assim o painel continua funcionando se algum pacote não estiver instalado.
Valores em R$ chegam em reais; a formatação (mil, mi, bi) é feita no navegador.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import streamlit as st

from .semantica import (BANCO_CORES, CAIXA_AZUL, CAIXA_LARANJA, ROTULOS, TECNICAS, cor_banco, humanizar)

try:  # gráficos
    from streamlit_echarts import JsCode, st_echarts
except Exception:  # pragma: no cover - depende do ambiente
    st_echarts, JsCode = None, None
try:
    from streamlit_echarts import Map as EMap
except Exception:  # pragma: no cover
    EMap = None
try:  # tabelas
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
    from st_aggrid import JsCode as AgJs
except Exception:  # pragma: no cover
    AgGrid = None

FONTE = "Inter, 'Segoe UI', Roboto, sans-serif"
PALETA = [CAIXA_AZUL, CAIXA_LARANJA, "#00A19A", "#F2C500", "#8C1D40", "#6C7A89", "#3FA110", "#EC7000"]

_JS_NUM = """
function __f(v, t){ if(v===null||v===undefined||isNaN(v)) return '—'; var a=Math.abs(v);
  if(t==='pct') return (v*100).toFixed(1).replace('.',',')+'%';
  if(t==='int') return Math.round(v).toLocaleString('pt-BR');
  if(a>=1e9) return 'R$ '+(v/1e9).toFixed(1).replace('.',',')+' bi';
  if(a>=1e6) return 'R$ '+(v/1e6).toFixed(1).replace('.',',')+' mi';
  if(a>=1e3) return 'R$ '+(v/1e3).toFixed(0)+' mil';
  return 'R$ '+v.toFixed(0); }
"""


def disponivel() -> dict:
    return {"echarts": st_echarts is not None, "aggrid": AgGrid is not None}


def _js(corpo: str):
    return JsCode(corpo).js_code if JsCode else None


def _fmt_eixo(formato: str):
    return _js(f"function(v){{{_JS_NUM} return __f(v,'{formato}');}}")


def _fmt_tooltip(formato: str):
    return _js(f"""function(ps){{{_JS_NUM} ps=[].concat(ps); var s='<b>'+(ps[0].axisValueLabel||ps[0].name)+'</b>';
      ps.forEach(function(p){{ var v=Array.isArray(p.value)?p.value[p.value.length-1]:p.value;
        s+='<br/>'+p.marker+(p.seriesName||'')+': '+__f(v,'{formato}'); }}); return s; }}""")


def _base(titulo: str = "") -> dict:
    return {"textStyle": {"fontFamily": FONTE}, "color": PALETA,
            "title": {"text": titulo, "left": 0, "textStyle": {"fontSize": 14, "fontWeight": 600, "color": "#101828"}},
            "grid": {"left": 8, "right": 16, "top": 44 if titulo else 24, "bottom": 8, "containLabel": True},
            "animationDuration": 700}


def _evento(res):
    """Valor devolvido pelo clique. Até a 0.6 o st_echarts devolvia o valor direto; a partir da 0.7 devolve
    um objeto de resultado com o valor em `chart_event`."""
    if res is None or isinstance(res, (str, int, float)):
        return res
    try:
        v = res.get("chart_event") if isinstance(res, dict) else getattr(res, "chart_event", None)
    except Exception:
        v = None
    if v is None and hasattr(res, "__getitem__") and not isinstance(res, dict):
        try:
            v = res["chart_event"]
        except Exception:
            v = None
    return v


_EIXO = {"axisLine": {"lineStyle": {"color": "#D0D5DD"}}, "axisTick": {"show": False},
         "axisLabel": {"color": "#475467", "fontSize": 11, "hideOverlap": True},
         "splitLine": {"lineStyle": {"color": "#EEF1F5", "type": "dashed"}},
         "nameTextStyle": {"color": "#667085", "fontSize": 11}}
_DICA = {"backgroundColor": "rgba(255,255,255,0.98)", "borderColor": "#E4E9F0", "borderWidth": 1,
         "padding": [8, 12], "textStyle": {"color": "#101828", "fontSize": 12, "fontFamily": FONTE},
         "extraCssText": "border-radius:8px; box-shadow:0 8px 24px rgba(16,24,40,.14);"}


def _junta(base: dict, extra: dict) -> dict:
    """Aplica `base` por baixo de `extra` (o que o gráfico definiu prevalece)."""
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _junta(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _polir(op: dict) -> dict:
    """Acabamento único para todos os gráficos: dicas brancas com sombra, eixos discretos, legenda
    com marcadores redondos, títulos e animação suaves."""
    op = dict(op)
    for eixo in ("xAxis", "yAxis"):
        if eixo in op:
            v = op[eixo]
            op[eixo] = [_junta(_EIXO, e) for e in v] if isinstance(v, list) else _junta(_EIXO, v)
    if "tooltip" in op:
        op["tooltip"] = _junta(_DICA, op["tooltip"])
    leg = op.get("legend")
    if isinstance(leg, dict) and leg.get("show", True):
        op["legend"] = _junta({"itemWidth": 10, "itemHeight": 10, "itemGap": 14, "icon": "circle",
                               "textStyle": {"color": "#344054", "fontSize": 12}}, leg)
    if isinstance(op.get("title"), dict):
        op["title"] = _junta({"textStyle": {"fontSize": 14, "fontWeight": 650, "color": "#101828"},
                              "subtextStyle": {"color": "#667085", "fontSize": 12}}, op["title"])
    op.setdefault("animationEasing", "cubicOut")
    op.setdefault("backgroundColor", "transparent")
    return op


def _mostrar(op: dict, altura: int, chave: str | None, eventos: dict | None = None, mapa=None):
    op = _polir(op)
    kw = {"map": mapa} if mapa is not None else {}
    return _evento(st_echarts(options=op, height=f"{altura}px", key=chave, events=eventos or {}, **kw))


def _com_filtro(op: dict, altura: int, chave: str | None, filtro, valores: list | None,
                nomes: list | None = None):
    """Mostra o gráfico; com `filtro`, o clique numa barra/fatia vira filtro ativo (dimensão `filtro`,
    valor bruto `valores[i]`). `filtro` também pode ser uma função (valor, nome) para ações próprias da tela
    (ex.: descer do Brasil para o estado no mapa)."""
    from . import interacao
    if not filtro or valores is None:
        return _mostrar(op, altura, chave)
    if callable(filtro):
        acao, filtro_nome = filtro, "acao"
    else:
        acao, filtro_nome = None, filtro
    chave = chave or f"g_{filtro_nome}_{abs(hash(tuple(map(str, valores[:30])))) % 10**8}"
    op.setdefault("title", {})
    res = _mostrar(op, altura, chave, {"click": interacao.JS_CLIQUE})
    i, nome = interacao.evento_novo(chave, res)
    if i is not None and 0 <= i < len(valores):
        rot = (nomes[i] if nomes and i < len(nomes) else nome)
        if acao:
            acao(valores[i], str(rot) if rot is not None else None)
        else:
            interacao.clicar(filtro_nome, valores[i], str(rot) if rot is not None else None)
    return None


DICA_FILTRO = "Clique para filtrar"


def _plotly():
    try:
        import plotly.graph_objects as go
        return go
    except Exception:
        return None


# ------------------------------------------------------------------ indicadores
def gauge(valor: float | None, titulo: str, chave: str, meta: float | None = None, cor: str = CAIXA_AZUL,
          altura: int = 220) -> None:
    """Velocímetro de 0 a 100% (ex.: participação CAIXA)."""
    v = 0.0 if valor is None or valor != valor else float(valor)
    if st_echarts:
        op = {"textStyle": {"fontFamily": FONTE}, "series": [{
            "type": "gauge", "startAngle": 200, "endAngle": -20, "min": 0, "max": 100, "radius": "95%",
            "progress": {"show": True, "width": 16, "itemStyle": {"color": cor}},
            "axisLine": {"lineStyle": {"width": 16, "color": [[1, "#E8EDF4"]]}},
            "axisTick": {"show": False}, "splitLine": {"show": False},
            "axisLabel": {"distance": -38, "fontSize": 10, "color": "#8A94A6"},
            "pointer": {"show": False}, "anchor": {"show": False},
            "title": {"show": True, "offsetCenter": [0, "62%"], "fontSize": 12, "color": "#5B6573"},
            "detail": {"valueAnimation": True, "offsetCenter": [0, "10%"], "fontSize": 28, "fontWeight": 700,
                       "formatter": "{value}%", "color": "#101828"},
            "data": [{"value": round(v * 100, 1), "name": titulo}]}]}
        if meta is not None:
            op["series"].append({"type": "gauge", "startAngle": 200, "endAngle": -20, "min": 0, "max": 100,
                                 "radius": "95%", "axisLine": {"show": False}, "axisTick": {"show": False},
                                 "splitLine": {"show": False}, "axisLabel": {"show": False},
                                 "pointer": {"show": True, "length": "18%", "width": 4, "offsetCenter": [0, "-78%"],
                                             "itemStyle": {"color": CAIXA_LARANJA}},
                                 "detail": {"show": False}, "title": {"show": False},
                                 "data": [{"value": round(meta * 100, 1)}]})
        _mostrar(op, altura, chave)
        return
    go = _plotly()
    if go:
        fig = go.Figure(go.Indicator(mode="gauge+number", value=v * 100, number={"suffix": "%"},
                                     title={"text": titulo}, gauge={"axis": {"range": [0, 100]},
                                                                    "bar": {"color": cor}}))
        fig.update_layout(height=altura, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True, key=chave)
    else:
        st.metric(titulo, f"{v:.0%}")


def radar(indicadores: list[str], series: dict[str, list[float]], chave: str, altura: int = 380,
          cores: dict | None = None, titulo: str = "") -> None:
    """Radar de 0 a 100 (ex.: dimensões do ente contra a média dos pares)."""
    cores = cores or {}
    if st_echarts:
        op = _base(titulo)
        op.update({"legend": {"bottom": 0, "icon": "circle"}, "tooltip": {},
                   "radar": {"indicator": [{"name": n, "max": 100} for n in indicadores], "radius": "64%",
                             "splitArea": {"areaStyle": {"color": ["#F8FAFD", "#FFFFFF"]}},
                             "axisName": {"color": "#344054", "fontSize": 11}},
                   "series": [{"type": "radar", "data": [
                       {"name": n, "value": [round(float(x), 0) for x in v], "areaStyle": {"opacity": 0.18},
                        "lineStyle": {"width": 2, "color": cores.get(n)}, "itemStyle": {"color": cores.get(n)}}
                       for n, v in series.items()]}]})
        _mostrar(op, altura, chave)
        return
    go = _plotly()
    if go:
        fig = go.Figure([go.Scatterpolar(r=list(v) + [v[0]], theta=indicadores + [indicadores[0]], fill="toself",
                                         name=n, line=dict(color=cores.get(n))) for n, v in series.items()])
        fig.update_layout(height=altura, polar=dict(radialaxis=dict(range=[0, 100])), margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True, key=chave)
    else:
        st.dataframe(pd.DataFrame(series, index=indicadores))


def heatmap(df: pd.DataFrame, x: str, y: str, valor: str, chave: str, formato: str = "int", titulo: str = "",
            altura: int = 420, ordem_x: list | None = None, ordem_y: list | None = None) -> None:
    """Matriz colorida (ex.: banco antes × banco depois)."""
    if df.empty:
        st.info("Sem dados para a matriz.")
        return
    xs = ordem_x or sorted(df[x].astype(str).unique())
    ys = ordem_y or sorted(df[y].astype(str).unique())
    if st_echarts:
        dados = [[xs.index(str(a)), ys.index(str(b)), float(v)] for a, b, v in zip(df[x], df[y], df[valor])
                 if str(a) in xs and str(b) in ys]
        op = _base(titulo)
        op["grid"].update({"bottom": 60})
        op.update({
            "tooltip": {"position": "top", "formatter": _js(
                f"function(p){{{_JS_NUM} return '<b>'+p.name+' → '+{json.dumps(ys)}[p.value[1]]+'</b><br/>'+__f(p.value[2],'{formato}');}}")},
            "xAxis": {"type": "category", "data": xs, "splitArea": {"show": True}, "axisLabel": {"interval": 0, "rotate": 20}},
            "yAxis": {"type": "category", "data": ys, "splitArea": {"show": True}},
            "visualMap": {"min": 0, "max": max(v[2] for v in dados) if dados else 1, "calculable": True,
                          "orient": "horizontal", "left": "center", "bottom": 0,
                          "inRange": {"color": ["#EEF4FB", "#8DB6E4", CAIXA_AZUL]}, "show": False},
            "series": [{"type": "heatmap", "data": dados,
                        "label": {"show": True, "formatter": _js(f"function(p){{{_JS_NUM} return __f(p.value[2],'{formato}');}}"),
                                  "fontSize": 11},
                        "emphasis": {"itemStyle": {"shadowBlur": 8, "shadowColor": "rgba(0,0,0,.3)"}}}]})
        _mostrar(op, altura, chave)
        return
    go = _plotly()
    piv = df.pivot_table(index=y, columns=x, values=valor, aggfunc="sum").reindex(index=ys, columns=xs)
    if go:
        fig = go.Figure(go.Heatmap(z=piv.values, x=xs, y=ys, colorscale="Blues", text=piv.values,
                                   texttemplate="%{text:,.0f}"))
        fig.update_layout(height=altura, title=titulo, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True, key=chave)
    else:
        st.dataframe(piv)


def funil(etapas: list[tuple[str, float]], chave: str, titulo: str = "", altura: int = 320,
          formato: str = "brl", filtro: str | None = None, valores: list | None = None) -> None:
    if not etapas:
        return
    if st_echarts:
        op = _base(titulo)
        op.update({"tooltip": {"formatter": _js(f"function(p){{{_JS_NUM} return '<b>'+p.name+'</b><br/>'+__f(p.value,'{formato}');}}")},
                   "series": [{"type": "funnel", "left": "8%", "width": "84%", "top": 40, "bottom": 10,
                               "sort": "none", "gap": 3, "minSize": "18%",
                               "label": {"show": True, "position": "inside", "color": "#fff", "fontWeight": 600,
                                         "formatter": _js(f"function(p){{{_JS_NUM} return p.name+'\\n'+__f(p.value,'{formato}');}}")},
                               "data": [{"name": n, "value": float(v), "itemStyle": {"color": PALETA[i % len(PALETA)]}}
                                        for i, (n, v) in enumerate(etapas)]}]})
        _com_filtro(op, altura, chave, filtro, valores, [n for n, _ in etapas])
        return
    go = _plotly()
    if go:
        fig = go.Figure(go.Funnel(y=[n for n, _ in etapas], x=[v for _, v in etapas]))
        fig.update_layout(height=altura, title=titulo)
        st.plotly_chart(fig, use_container_width=True, key=chave)
    else:
        st.dataframe(pd.DataFrame(etapas, columns=["Etapa", "Valor"]))


def barras(df: pd.DataFrame, categoria: str, series: dict[str, str], chave: str, formato: str = "brl",
           titulo: str = "", empilhado: bool = True, horizontal: bool = False, altura: int = 380,
           cores: dict | None = None, filtro: str | None = None, valores: str | None = None) -> None:
    """Barras com várias séries. `series` = {coluna: nome exibido}."""
    if df.empty:
        st.info("Sem dados.")
        return
    cores = cores or {}
    cats = df[categoria].astype(str).tolist()
    if st_echarts:
        eixo_cat = {"type": "category", "data": cats, "axisLabel": {"interval": 0, "fontSize": 11}}
        eixo_val = {"type": "value", "axisLabel": {"formatter": _fmt_eixo(formato)}, "splitLine": {"lineStyle": {"color": "#EEF1F5"}}}
        if horizontal:
            eixo_cat["inverse"] = True
        op = _base(titulo)
        op.update({"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "formatter": _fmt_tooltip(formato)},
                   "legend": {"top": 0 if not titulo else 22, "right": 0, "icon": "roundRect"} if len(series) > 1 else {"show": False},
                   "xAxis": eixo_val if horizontal else eixo_cat, "yAxis": eixo_cat if horizontal else eixo_val,
                   "series": [{"name": nome, "type": "bar", "stack": "t" if empilhado else None,
                               "data": [None if pd.isna(v) else float(v) for v in df[col]],
                               "itemStyle": {"color": cores.get(nome) or cores.get(col), "borderRadius": 3},
                               "emphasis": {"focus": "series"}, "barMaxWidth": 46}
                              for col, nome in series.items()]})
        if len(series) > 1:
            op["grid"]["top"] = 56
        if filtro:
            op["series"] = [{**se, "cursor": "pointer"} for se in op["series"]]
        _com_filtro(op, altura, chave, filtro, df[valores or categoria].tolist() if filtro else None, cats)
        return
    tab = df.set_index(categoria)[list(series)].rename(columns=series)
    try:
        st.bar_chart(tab, horizontal=horizontal)
    except TypeError:
        st.bar_chart(tab)


def linha_tempo(df: pd.DataFrame, x: str, y: str, chave: str, cor_por: str | None = None, formato: str = "brl",
                titulo: str = "", area: bool = True, altura: int = 360, cores: dict | None = None) -> None:
    if df.empty:
        st.info("Sem dados para a série.")
        return
    cores = cores or {}
    xs = sorted(df[x].astype(str).unique())
    grupos = [(None, df)] if not cor_por else list(df.groupby(cor_por))
    if st_echarts:
        op = _base(titulo)
        op.update({"tooltip": {"trigger": "axis", "formatter": _fmt_tooltip(formato)},
                   "legend": {"top": 0 if not titulo else 22, "right": 0} if cor_por else {"show": False},
                   "xAxis": {"type": "category", "data": xs, "boundaryGap": False},
                   "yAxis": {"type": "value", "axisLabel": {"formatter": _fmt_eixo(formato)},
                             "splitLine": {"lineStyle": {"color": "#EEF1F5"}}},
                   "dataZoom": [{"type": "inside"}] if len(xs) > 30 else [],
                   "series": []})
        for nome, g in grupos:
            serie = g.groupby(g[x].astype(str))[y].sum().reindex(xs)
            op["series"].append({"name": str(nome or y), "type": "line", "smooth": True, "symbol": "circle",
                                 "symbolSize": 5 if len(xs) < 60 else 0,
                                 "areaStyle": {"opacity": 0.12} if area else None,
                                 "lineStyle": {"width": 2.5, "color": cores.get(nome)},
                                 "itemStyle": {"color": cores.get(nome)},
                                 "data": [None if pd.isna(v) else float(v) for v in serie]})
        if cor_por:
            op["grid"]["top"] = 56
        _mostrar(op, altura, chave)
        return
    tab = df.pivot_table(index=x, columns=cor_por, values=y, aggfunc="sum") if cor_por else df.set_index(x)[[y]]
    st.line_chart(tab)


def saldo_reconstituido(serie: pd.DataFrame, chave: str, cores: dict | None = None, paradas: dict | None = None,
                        altura: int = 400, desde: str | None = None) -> None:
    """Saldo mês a mês por banco (regra SAL-01): linha cheia onde é reconstituído com o extrato publicado, tracejada
    onde é projetado (extrato parado), com a faixa de incerteza sombreada e uma linha laranja no último saldo
    publicado do banco que parou (`paradas`: banco -> (data dd/mm/aaaa, valor))."""
    if serie is None or serie.empty:
        st.info("Sem série reconstituída.")
        return
    s = serie if not desde else serie[serie["mes"] >= desde]
    cores = cores or {}
    xs = sorted(s["mes"].astype(str).unique())
    if not st_echarts:
        st.line_chart(s.pivot_table(index="mes", columns="grupo_banco", values="saldo_estimado", aggfunc="sum"))
        return
    op = _base("")
    op.update({"tooltip": {"trigger": "axis", "formatter": _fmt_tooltip("brl")},
               "legend": {"top": 0, "right": 0},
               "xAxis": {"type": "category", "data": xs, "boundaryGap": False},
               "yAxis": {"type": "value", "axisLabel": {"formatter": _fmt_eixo("brl")}},
               "series": []})
    op["grid"]["top"] = 48
    for b, g in s.groupby("grupo_banco"):
        g = g.set_index(g["mes"].astype(str)).reindex(xs)
        cor = cores.get(b)
        proj = g["tipo"].astype(str).str.startswith("projetado")
        real = [None if (pd.isna(v) or p) else float(v) for v, p in zip(g["saldo_estimado"], proj)]
        # liga o último ponto reconstituído ao primeiro projetado
        pr = [float(v) if (p and pd.notna(v)) else None for v, p in zip(g["saldo_estimado"], proj)]
        if proj.any():
            i0 = int(np.argmax(proj.values))
            if i0 > 0 and pd.notna(g["saldo_estimado"].iloc[i0 - 1]):
                pr[i0 - 1] = float(g["saldo_estimado"].iloc[i0 - 1])
        op["series"].append({"name": f"{b}", "type": "line", "smooth": True, "symbol": "none", "data": real,
                             "lineStyle": {"width": 2.5, "color": cor}, "itemStyle": {"color": cor}})
        if proj.any():
            lo = [float(v) if p else None for v, p in zip(g["saldo_est_min"], proj)]
            hi = [float(h - l) if p else None for h, l, p in zip(g["saldo_est_max"], g["saldo_est_min"], proj)]
            op["series"].append({"name": f"{b} · faixa", "type": "line", "stack": f"faixa_{b}", "symbol": "none",
                                 "lineStyle": {"opacity": 0}, "data": lo, "tooltip": {"show": False}})
            op["series"].append({"name": f"{b} · faixa", "type": "line", "stack": f"faixa_{b}", "symbol": "none",
                                 "lineStyle": {"opacity": 0}, "areaStyle": {"color": cor, "opacity": 0.12},
                                 "data": hi, "tooltip": {"show": False}})
            serie_p = {"name": f"{b} · estimado (extrato parado)", "type": "line", "smooth": True, "symbol": "none",
                       "data": pr, "lineStyle": {"width": 2.5, "type": "dashed", "color": cor},
                       "itemStyle": {"color": cor}}
            if paradas and b in paradas:
                quando, valor = paradas[b]
                serie_p["markLine"] = {"symbol": "none", "silent": True,
                                       "lineStyle": {"color": "#E07B00", "type": "dashed", "width": 1.5},
                                       "label": {"formatter": f"Parado: último saldo publicado ({quando})",
                                                 "color": "#8A4B00", "position": "insideEndTop"},
                                       "data": [{"yAxis": float(valor)}]}
            op["series"].append(serie_p)
    op["legend"]["data"] = [x["name"] for x in op["series"] if not x["name"].endswith("faixa")]
    _mostrar(op, altura, chave)


def quadrante(df: pd.DataFrame, x: str, y: str, tamanho: str, rotulo: str, chave: str, cor_por: str | None = None,
              cores: dict | None = None, linha_x: float | None = None, linha_y: float | None = None,
              titulo: str = "", altura: int = 480, log_x: bool = True, nome_x: str = "", nome_y: str = "",
              formato_x: str = "brl", formato_y: str = "int", max_pontos: int = 1500):
    """Dispersão com quadrantes. Devolve o rótulo do ponto clicado (quando o ECharts está disponível)."""
    d = df[df[x] > 0].dropna(subset=[y]).nlargest(max_pontos, tamanho) if not df.empty else df
    if d.empty:
        st.info("Sem pontos para mostrar.")
        return None
    cores = cores or {}
    mx = max(float(d[tamanho].max()), 1.0)
    grupos = [(None, d)] if not cor_por else list(d.groupby(cor_por))
    if st_echarts:
        op = _base(titulo)
        op["grid"].update({"top": 56, "right": 24, "bottom": 30})
        op.update({
            "legend": {"top": 0 if not titulo else 22, "right": 0} if cor_por else {"show": False},
            "tooltip": {"formatter": _js(f"""function(p){{{_JS_NUM} return '<b>'+p.value[3]+'</b><br/>{nome_x or x}: '
                +__f(p.value[0],'{formato_x}')+'<br/>{nome_y or y}: '+__f(p.value[1],'{formato_y}');}}""")},
            "xAxis": {"type": "log" if log_x else "value", "name": nome_x, "nameLocation": "middle", "nameGap": 26,
                      "axisLabel": {"formatter": _fmt_eixo(formato_x)}, "splitLine": {"lineStyle": {"color": "#EEF1F5"}}},
            "yAxis": {"type": "value", "name": nome_y, "axisLabel": {"formatter": _fmt_eixo(formato_y)},
                      "splitLine": {"lineStyle": {"color": "#EEF1F5"}}},
            "series": []})
        for i, (nome, g) in enumerate(grupos):
            serie = {"name": str(nome or ""), "type": "scatter",
                     "data": [[float(a), float(b), float(c), str(r)] for a, b, c, r in zip(g[x], g[y], g[tamanho], g[rotulo])],
                     "symbolSize": _js(f"function(v){{return Math.sqrt(v[2]/{mx})*36+5;}}"),
                     "itemStyle": {"color": cores.get(nome, PALETA[i % len(PALETA)]), "opacity": 0.72,
                                   "borderColor": "#fff", "borderWidth": 0.6},
                     "emphasis": {"focus": "series", "label": {"show": True, "formatter": "{@[3]}", "position": "top"}}}
            if i == 0 and (linha_x is not None or linha_y is not None):
                ml = []
                if linha_x is not None:
                    ml.append({"xAxis": float(linha_x)})
                if linha_y is not None:
                    ml.append({"yAxis": float(linha_y)})
                serie["markLine"] = {"silent": True, "symbol": "none", "label": {"show": False},
                                     "lineStyle": {"type": "dashed", "color": "#9AA4B1"}, "data": ml}
            op["series"].append(serie)
        ev = _mostrar(op, altura, chave, {"click": "function(p){return p.value[3];}"})
        return ev
    from .ui import dispersao
    dispersao(d, x, y, tamanho, rotulo, titulo, linha_y=None, altura=altura)
    return None


# ------------------------------------------------------------------ tabela profissional
def _tipo(c: str) -> str:
    return ROTULOS.get(c, ("", "texto", ""))[1]


_CSS_GRADE = {
    ".ag-root-wrapper": {"border": "1px solid #E4E9F0 !important", "border-radius": "12px !important",
                         "font-family": "Inter, 'Segoe UI', Roboto, sans-serif !important"},
    ".ag-header": {"background-color": "#F7F9FC !important", "border-bottom": "1px solid #E4E9F0 !important"},
    ".ag-header-cell-text": {"color": "#344054 !important", "font-weight": "650 !important", "font-size": "12px !important"},
    ".ag-row": {"font-size": "13px !important", "color": "#101828 !important", "border-color": "#F0F2F5 !important"},
    ".ag-row-hover": {"background-color": "#F2F7FD !important"},
    ".ag-row-selected": {"background-color": "#E3EEFA !important"},
    ".ag-paging-panel": {"color": "#667085 !important", "border-top": "1px solid #E4E9F0 !important"},
    ".ag-cell-focus": {"border-color": "#005CA9 !important"},
    ".ag-row-odd": {"background-color": "#FAFBFD !important"},
    ".ag-header-cell": {"border-right": "1px solid #EEF1F5 !important"},
    ".ag-pinned-left-cols-container": {"box-shadow": "2px 0 4px rgba(16,24,40,.06)"},
    ".ag-cell": {"line-height": "32px !important"},
}


LIMITE_GRADE = 2500


def grade(df: pd.DataFrame, chave: str, altura: int = 440, selecao: bool = False, pagina: int = 25,
          fixar: str | None = None) -> dict | None:
    """Tabela AgGrid (filtro e ordenação por coluna, busca, colunas redimensionáveis, seleção de linha).
    Devolve a linha selecionada com os nomes originais das colunas. Sem AgGrid, usa a tabela padrão."""
    from .ui import tabela
    if df is None or df.empty:
        st.info("Nada para mostrar com estes filtros.")
        return None
    if AgGrid is None or (len(df) > LIMITE_GRADE and not selecao):
        # a grade manda todas as linhas ao navegador: acima do limite usa a tabela paginada no servidor
        # (busca, ordenação e páginas; nada é cortado)
        tabela(df, altura=altura, chave=f"{chave}_pag")
        return None
    if len(df) > LIMITE_GRADE:
        st.caption(f"Mostrando as {LIMITE_GRADE:,} primeiras de {len(df):,} linhas para seleção; o download traz todas."
                   .replace(",", "."))
        df = df.head(LIMITE_GRADE)
    cols = [c for c in df.columns if c not in TECNICAS]
    rot = {c: ROTULOS.get(c, (humanizar(c), "texto", ""))[0] for c in cols}
    vistos = {}
    for c, r in list(rot.items()):
        if r in vistos:
            rot[c] = f"{r} ({c})"
        vistos[r] = True
    v = df[cols].rename(columns=rot)
    gb = GridOptionsBuilder.from_dataframe(v)
    gb.configure_default_column(sortable=True, filter=True, resizable=True, wrapHeaderText=True,
                                autoHeaderHeight=True, minWidth=110)
    fmt = {"brl": "v.toLocaleString('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0})",
           "pct": "(v*100).toFixed(1).replace('.',',')+'%'",
           "var": "(v>0?'+':'')+(v*100).toFixed(1).replace('.',',')+'%'",
           "int": "Math.round(v).toLocaleString('pt-BR')",
           "vezes": "v.toFixed(1).replace('.',',')+'×'"}
    from .semantica import TEXTO_BANCO, coluna_principal, colunas_banco
    principal = coluna_principal(df[cols]) if len(df) >= 3 else None
    bancos = set(colunas_banco(df[cols]))
    barra = ("function(p){{var v=p.value;if(v==null||isNaN(v)||v<=0)return {{textAlign:'right'}};"
             "var w=Math.max(0,Math.min(100,100*v/{m}));return {{textAlign:'right',backgroundImage:"
             "'linear-gradient(90deg, rgba({cor},.16) '+w+'%, transparent '+w+'%)'}};}}")
    for c in cols:
        t = _tipo(c)
        ajuda = ROTULOS.get(c, ("", "", ""))[2] or None
        if t in fmt:
            estilo = None
            if t == "var":
                estilo = AgJs("function(p){if(p.value==null)return null;return {color:p.value<0?'#D1495B':'#027A48',fontWeight:600};}")
            elif t == "pct":          # barra 0–100% atrás do número
                estilo = AgJs(barra.format(m=1, cor="243,146,0"))
            elif c == principal:      # barra proporcional ao maior valor da coluna
                estilo = AgJs(barra.format(m=float(df[c].max()), cor="0,92,169"))
            elif t == "brl":          # negativo em vermelho
                estilo = AgJs("function(p){return (p.value!=null&&p.value<0)?{color:'#B42318'}:null;}")
            gb.configure_column(rot[c], type=["numericColumn"], headerTooltip=ajuda, cellStyle=estilo,
                                valueFormatter=AgJs(f"function(p){{var v=p.value;if(v===null||v===undefined||isNaN(v))return '';return {fmt[t]};}}"))
        elif c in bancos:             # banco como etiqueta colorida
            cores = ",".join(f"'{b}':['{tx}','{bg}']" for b, (tx, bg) in TEXTO_BANCO.items())
            gb.configure_column(rot[c], headerTooltip=ajuda, cellStyle=AgJs(
                f"function(p){{var m={{{cores}}};var c=m[p.value];if(!c)return {{color:'#475467'}};"
                "return {color:c[0],backgroundColor:c[1],fontWeight:650};}"))
        else:
            gb.configure_column(rot[c], headerTooltip=ajuda)
    if not fixar:
        fixar = next((c for c in ("nome_ente", "recebedor", "parlamentar", "oferta", "risco") if c in cols), None)
    primeira = rot.get(fixar) if fixar else next((rot[c] for c in cols if _tipo(c) == "texto"
                                                   and not c.startswith("cnpj")), None)
    if primeira:
        gb.configure_column(primeira, pinned="left", minWidth=200)
    if selecao:
        gb.configure_selection("single", use_checkbox=False)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=pagina)
    gb.configure_grid_options(enableCellTextSelection=True, rowHeight=34, headerHeight=40, animateRows=True)
    kw = dict(gridOptions=gb.build(), height=altura, allow_unsafe_jscode=True, key=chave,
              update_mode=GridUpdateMode.SELECTION_CHANGED if selecao else GridUpdateMode.NO_UPDATE,
              fit_columns_on_grid_load=len(cols) <= 7)
    try:
        resp = AgGrid(v, theme="alpine", custom_css=_CSS_GRADE, **kw)
    except TypeError:            # versões antigas sem custom_css
        resp = AgGrid(v, theme="balham", **kw)
    if not selecao:
        return None
    sel = resp.get("selected_rows") if isinstance(resp, dict) else getattr(resp, "selected_rows", None)
    if sel is None or (hasattr(sel, "empty") and sel.empty) or (isinstance(sel, list) and not sel):
        return None
    linha = sel.iloc[0].to_dict() if hasattr(sel, "iloc") else sel[0]
    inv = {r: c for c, r in rot.items()}
    return {inv.get(k, k): val for k, val in linha.items()}


def cores_bancos(nomes) -> dict:
    return {b: cor_banco(b) for b in nomes} | {k: v for k, v in BANCO_CORES.items()}


# ------------------------------------------------------------------ mapa do Brasil (ECharts + malha IBGE)
ESCALAS = {"pct": ["#D1495B", "#F7D8A8", "#C9DCF2", CAIXA_AZUL], "Blues": ["#EEF4FB", "#8DB6E4", CAIXA_AZUL],
           "Reds": ["#FDECEC", "#F29A9F", "#B42318"], "Greens": ["#ECFDF3", "#7AD3A8", "#027A48"],
           "Oranges": ["#FFF4E5", "#F8B76B", "#C25E00"]}


def mapa_disponivel() -> bool:
    return st_echarts is not None and EMap is not None


def mapa_brasil(df: pd.DataFrame, geojson: dict, nome_mapa: str, coluna: str, formato: str, chave: str,
                altura: int = 560, escala: str = "Blues", bolhas: pd.DataFrame | None = None,
                cor_bolha: str | None = None, cores_bolha: dict | None = None, titulo_valor: str = ""):
    """Mapa interativo: arrastar e dar zoom, legenda deslizante (filtra faixas), dica ao passar o mouse,
    clique numa área devolve o código IBGE (codarea); clique numa bolha devolve 'mun:<código>'.
    df: codarea, nome, coluna da métrica + valor, part_caixa, saldo_concorrente, potencial (opcionais)."""
    dados = []
    for r in df.itertuples(index=False):
        v = getattr(r, coluna)
        dados.append({"name": str(r.codarea), "value": None if pd.isna(v) else float(v), "rotulo": str(r.nome),
                      "valor": float(getattr(r, "valor", 0) or 0), "part": float(getattr(r, "part_caixa", 0) or 0),
                      "conc": float(getattr(r, "saldo_concorrente", 0) or 0), "pot": float(getattr(r, "potencial", 0) or 0)})
    vals = [x["value"] for x in dados if x["value"] is not None]
    mn, mx = (0.0, 1.0) if formato == "pct" else ((min(vals) if vals else 0.0), (max(vals) if vals else 1.0))
    cores = ESCALAS["pct"] if formato == "pct" else ESCALAS.get(escala, ESCALAS["Blues"])
    tip = _js(f"""function(p){{{_JS_NUM}
        if(p.seriesType==='scatter'){{var d=p.data; return '<b>'+d.rotulo+'</b><br>'+d.entes+' ente(s)'+
            '<br>Valor: '+__f(d.valor,'brl')+'<br>CAIXA: '+__f(d.part,'pct')+(d.extra?'<br>'+d.extra:'');}}
        var d=p.data||{{}}; if(!d.rotulo) return p.name;
        return '<b>'+d.rotulo+'</b><br>{titulo_valor or 'Métrica'}: '+__f(d.value,'{formato}')+
            '<br>Valor contratado: '+__f(d.valor,'brl')+'<br>Participação CAIXA: '+__f(d.part,'pct')+
            '<br>Saldo no concorrente: '+__f(d.conc,'brl')+'<br>Potencial: '+__f(d.pot,'brl')+
            '<br><i>clique para detalhar</i>'; }}""")
    op = {"textStyle": {"fontFamily": FONTE}, "tooltip": {"trigger": "item", "formatter": tip,
                                                          "backgroundColor": "rgba(255,255,255,.97)"},
          "visualMap": {"type": "continuous", "min": mn, "max": mx if mx > mn else mn + 1, "calculable": True,
                        "seriesIndex": 0, "orient": "vertical", "left": 8, "bottom": 16, "itemHeight": 120,
                        "inRange": {"color": cores}, "text": ["mais", "menos"],
                        "formatter": _js(f"function(v){{{_JS_NUM} return __f(v,'{formato}');}}")},
          "geo": {"map": nome_mapa, "roam": "move", "nameProperty": "codarea", "scaleLimit": {"min": 0.8, "max": 14},
                  "itemStyle": {"areaColor": "#EEF2F7", "borderColor": "#FFFFFF", "borderWidth": 0.6},
                  "emphasis": {"label": {"show": False}, "itemStyle": {"areaColor": CAIXA_LARANJA}},
                  "select": {"disabled": True}, "layoutCenter": ["50%", "52%"], "layoutSize": "95%"},
          "toolbox": {"right": 8, "top": 8, "feature": {"restore": {"title": "Voltar ao enquadramento"},
                                                       "saveAsImage": {"title": "Salvar imagem"}}},
          "series": [{"type": "map", "geoIndex": 0, "name": titulo_valor or coluna, "data": dados}]}
    if bolhas is not None and not bolhas.empty:
        b = bolhas.dropna(subset=["lat", "lon"])
        mxb = max(float(b["valor"].max()), 1.0)
        grupos = [(None, b)] if not cor_bolha else list(b.groupby(cor_bolha))
        for i, (nome, gb) in enumerate(grupos):
            op["series"].append({
                "type": "scatter", "coordinateSystem": "geo", "name": str(nome or "Entes"),
                "data": [{"value": [float(r.lon), float(r.lat), float(r.valor)], "rotulo": str(r.rotulo),
                          "entes": int(getattr(r, "entes", 1)), "valor": float(r.valor),
                          "part": float(getattr(r, "part_caixa", 0) or 0), "cod": str(getattr(r, "cod_ibge", "")),
                          "extra": str(getattr(r, "extra", "") or "")} for r in gb.itertuples(index=False)],
                "symbolSize": _js(f"function(v){{return Math.sqrt(v[2]/{mxb})*26+3;}}"),
                "itemStyle": {"color": (cores_bolha or {}).get(nome, PALETA[i % len(PALETA)]), "opacity": 0.78,
                              "borderColor": "#fff", "borderWidth": 0.5},
                "emphasis": {"scale": 1.4}, "zlevel": 2})
        if cor_bolha:
            op["legend"] = {"top": 8, "left": "center", "icon": "circle",
                            "data": [str(n) for n, _ in grupos]}
    ev = _mostrar(op, altura, chave, {"click": "function(p){ if(p.seriesType==='scatter'){return 'mun:'+p.data.cod;} return p.name; }"},
                  mapa=EMap(nome_mapa, geojson))
    return ev


# ------------------------------------------------------------------ composição e fluxo
def rosca(valores: pd.Series, chave: str, titulo: str = "", cores: dict | None = None, altura: int = 300,
          formato: str = "brl", filtro: str | None = None, nomes: dict | None = None) -> None:
    v = valores[valores > 0].sort_values(ascending=False) if not valores.empty else valores
    if v.empty:
        return
    if not st_echarts:
        st.bar_chart(v)
        return
    op = _base(titulo)
    op.update({"tooltip": {"trigger": "item", "formatter": _js(
        f"function(p){{{_JS_NUM} return '<b>'+p.name+'</b><br>'+__f(p.value,'{formato}')+' ('+p.percent+'%)';}}")},
        "legend": {"bottom": 0, "icon": "circle", "type": "scroll"},
        "series": [{"type": "pie", "radius": ["48%", "72%"], "center": ["50%", "48%"], "avoidLabelOverlap": True,
                    "itemStyle": {"borderColor": "#fff", "borderWidth": 2, "borderRadius": 4},
                    "label": {"show": True, "formatter": "{d}%", "fontWeight": 600},
                    "data": [{"name": str((nomes or {}).get(k, k)), "value": float(x),
                              "itemStyle": {"color": (cores or {}).get(k)}} for k, x in v.items()]}]})
    _com_filtro(op, altura, chave, filtro, list(v.index) if filtro else None,
                [str((nomes or {}).get(k, k)) for k in v.index])


def sankey(arestas: pd.DataFrame, chave: str, altura: int = 520, cores: dict | None = None, titulo: str = "") -> None:
    """Fluxo em colunas da esquerda para a direita (origem → destino). Arestas: origem, destino, valor."""
    if arestas.empty:
        st.info("Sem fluxo para mostrar.")
        return
    nos = list(dict.fromkeys(list(arestas["origem"]) + list(arestas["destino"])))
    cores = cores or {}

    def cor(n):
        for b, c in BANCO_CORES.items():
            if str(n).startswith(b) or f"· {b}" in str(n) or str(n).endswith(b):
                return c
        return cores.get(n, "#9AA4B1")
    op = _base(titulo)
    op.update({"tooltip": {"trigger": "item", "formatter": _js(
        f"function(p){{{_JS_NUM} if(p.dataType==='edge') return p.data.source+' → '+p.data.target+'<br><b>'+__f(p.data.value,'brl')+'</b>';"
        f" return '<b>'+p.name+'</b>';}}")},
        "series": [{"type": "sankey", "left": 8, "right": 160, "top": 36 if titulo else 12, "bottom": 12,
                    "nodeAlign": "justify", "nodeGap": 10, "nodeWidth": 16, "draggable": True,
                    "emphasis": {"focus": "adjacency"},
                    "lineStyle": {"color": "gradient", "curveness": 0.5, "opacity": 0.35},
                    "label": {"fontSize": 11, "color": "#344054"},
                    "data": [{"name": str(n), "itemStyle": {"color": cor(n)}} for n in nos],
                    "links": [{"source": str(a.origem), "target": str(a.destino), "value": float(a.valor)}
                              for a in arestas.itertuples() if a.valor > 0 and a.origem != a.destino]}]})
    _mostrar(op, altura, chave)


def treemap(df: pd.DataFrame, caminho: list[str], valor: str, cor: str, chave: str, altura: int = 520) -> None:
    """Treemap navegável (clique para entrar no nível). Cor = participação CAIXA (vermelho → azul)."""
    if df.empty:
        return

    def nos(d, nivel):
        col = caminho[nivel]
        out = []
        for nome, g in d.groupby(col, dropna=False):
            v = float(g[valor].sum())
            if v <= 0:
                continue
            pc = float((g[valor] * g[cor].fillna(0)).sum() / v) if v else 0
            item = {"name": str(nome) if pd.notna(nome) else "—", "value": v, "part": round(pc, 4),
                    "itemStyle": {"color": _cor_pct(pc)}}
            if nivel + 1 < len(caminho):
                item["children"] = nos(g, nivel + 1)
            out.append(item)
        return sorted(out, key=lambda x: -x["value"])
    op = {"textStyle": {"fontFamily": FONTE},
          "tooltip": {"formatter": _js(f"function(p){{{_JS_NUM} return '<b>'+p.name+'</b><br>'+__f(p.value,'brl')+"
                                       "'<br>CAIXA: '+__f(p.data.part,'pct');}")},
          "series": [{"type": "treemap", "data": nos(df, 0), "leafDepth": 1, "roam": False, "width": "100%",
                      "height": "88%", "breadcrumb": {"show": True, "bottom": 0},
                      "label": {"show": True, "formatter": "{b}", "fontSize": 12},
                      "upperLabel": {"show": True, "height": 22, "color": "#fff"},
                      "levels": [{"itemStyle": {"borderColor": "#fff", "borderWidth": 2, "gapWidth": 2}},
                                 {"itemStyle": {"borderColor": "#fff", "borderWidth": 1, "gapWidth": 1}}]}]}
    _mostrar(op, altura, chave)


def _cor_pct(p: float) -> str:
    """Vermelho (0%) → bege (50%) → azul CAIXA (100%)."""
    a, b, c = (209, 73, 91), (247, 233, 208), (0, 92, 169)
    p = max(0.0, min(1.0, p))
    x, y, t = (a, b, p / 0.5) if p < 0.5 else (b, c, (p - 0.5) / 0.5)
    return "#%02x%02x%02x" % tuple(int(x[i] + (y[i] - x[i]) * t) for i in range(3))


# ------------------------------------------------------------------ rede de relacionamento
CORES_REDE = {"parlamentar": "#7E5BB5", "ente": "#0B3D91", "banco": "#F2C500", "fornecedor": "#00A19A",
              "sanção": "#D1495B", "CAIXA": CAIXA_AZUL, "concorrente": "#F2C500"}


def rede(arestas: pd.DataFrame, chave: str, altura: int = 620, foco: str | None = None, rotulos_todos: bool = False):
    """Grafo de força: nós = parlamentares, entes, bancos, fornecedores, sanções; espessura = valor.
    `arestas`: origem_tipo, origem, origem_id, destino_tipo, destino, destino_id, valor. Devolve o id clicado."""
    if arestas is None or arestas.empty:
        st.info("Sem relações para mostrar com este recorte.")
        return None
    a = arestas.copy()
    a["valor"] = pd.to_numeric(a["valor"], errors="coerce").fillna(0)
    nos = {}
    for lado in ("origem", "destino"):
        for r in a[[f"{lado}_tipo", lado, f"{lado}_id", "valor"]].itertuples(index=False):
            tipo, nome, nid, v = r
            tipo = "CAIXA" if (tipo == "banco" and nome == "CAIXA") else ("concorrente" if tipo == "banco" else tipo)
            k = str(nid)
            n = nos.setdefault(k, {"id": k, "name": str(nome)[:46], "tipo": tipo, "valor": 0.0})
            n["valor"] += float(v)
    mx = max((n["valor"] for n in nos.values()), default=1) or 1
    cats = sorted({n["tipo"] for n in nos.values()})
    if not st_echarts:
        from .ui import tabela
        tabela(a)
        return None
    dados = [{"id": n["id"], "name": n["name"], "value": round(n["valor"], 2), "category": cats.index(n["tipo"]),
              "symbolSize": 8 + 34 * (n["valor"] / mx) ** 0.5,
              "itemStyle": {"color": CORES_REDE.get(n["tipo"], "#5B6573"),
                            "borderColor": "#101828" if foco and n["id"] == foco else "#fff",
                            "borderWidth": 3 if foco and n["id"] == foco else 1},
              "label": {"show": bool(rotulos_todos) or n["valor"] >= mx * 0.08 or (foco and n["id"] == foco)}}
             for n in nos.values()]
    mv = max(a["valor"].max(), 1)
    nome = {k: n["name"] for k, n in nos.items()}
    links = [{"source": str(r.origem_id), "target": str(r.destino_id), "value": float(r.valor),
              "sn": nome.get(str(r.origem_id), ""), "tn": nome.get(str(r.destino_id), ""),
              "lineStyle": {"width": 0.6 + 5 * (float(r.valor) / mv) ** 0.5, "opacity": 0.55, "curveness": 0.08}}
             for r in a.itertuples(index=False)]
    op = _base()
    op.update({
        "tooltip": {"formatter": _js(f"function(p){{{_JS_NUM} if(p.dataType==='edge') return '<b>'+p.data.sn+'</b> → <b>'+p.data.tn+'</b><br>'+__f(p.data.value,'brl'); return '<b>'+p.name+'</b><br>'+__f(p.value,'brl');}}")},
        "legend": {"data": cats, "top": 4, "left": "center"},
        "series": [{"type": "graph", "layout": "force", "roam": "move", "draggable": True, "data": dados, "links": links,
                    "categories": [{"name": c, "itemStyle": {"color": CORES_REDE.get(c, "#5B6573")}} for c in cats],
                    "force": {"repulsion": 160, "edgeLength": [40, 160], "gravity": 0.08},
                    "label": {"position": "right", "fontSize": 11, "color": "#344054"},
                    "emphasis": {"focus": "adjacency", "lineStyle": {"width": 4}},
                    "lineStyle": {"color": "source"}}]})
    return _mostrar(op, altura, chave, {"click": "function(p){ if(p.dataType==='node') return p.data.id; }"})
