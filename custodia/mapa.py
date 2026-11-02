"""Mapa territorial com deck.gl (pydeck, que já vem com o Streamlit).

Por que deck.gl: desenha os 5.570 municípios com fluidez, enquadra o Brasil ou a UF automaticamente,
não depende de mapa de ruas da internet (rede corporativa), tem dica ao passar o mouse e clique nativo
do Streamlit (st.pydeck_chart com seleção) para descer de Brasil → UF → município.

Este módulo só monta o mapa (sem Streamlit), para poder ser testado e pré-visualizado fora do painel.
"""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd

from .consultas import brl, pct

# paletas sequenciais claras → escuras (7 tons), legíveis em tela e impressão
PALETAS = {
    "Blues": ["#EEF4FB", "#D0E1F5", "#A6C8EC", "#6FA6DD", "#3B82C8", "#0F5FAE", "#073F7A"],
    "Oranges": ["#FEF4E8", "#FDDDB8", "#FBC17F", "#F8A14A", "#F07F1D", "#C9620A", "#8E4306"],
    "Reds": ["#FDF0F0", "#F8D2D3", "#F0A7AA", "#E3787E", "#D1495B", "#A92F42", "#76202E"],
    "Greens": ["#EEF8F2", "#CDEBD8", "#9ED6B4", "#66BC8C", "#2F9D66", "#16784A", "#0B5232"],
    "Purples": ["#F4F1FA", "#E0D7F0", "#C3B1E1", "#A085CC", "#7E5BB5", "#5F3F93", "#40296A"],
}
# participação CAIXA: vermelho (concorrente domina) → cinza (empate) → azul CAIXA
DIVERGENTE = ["#B4232F", "#E1706A", "#F2B8A8", "#CDD4DF", "#A9C8EA", "#4F8FD6", "#005CA9"]
SEM_DADO = "#F3F4F6"
CONTORNO = [255, 255, 255, 255]


def _rgba(cor: str, alfa: int = 235) -> list[int]:
    c = cor.lstrip("#")
    return [int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alfa]


def _fmt(v, formato: str) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if formato == "pct":
        return pct(v)
    if formato == "int":
        return f"{int(round(v)):,}".replace(",", ".")
    return brl(v)


# ------------------------------------------------------------------ classes da legenda
def classes(valores: pd.Series, formato: str, n: int = 5) -> list[float]:
    """Limites das faixas. Percentual: faixas fixas de 20 p.p.; valores: quantis (o Brasil é muito
    concentrado — com escala contínua, SP pinta tudo de claro)."""
    if formato == "pct":
        return [0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001]
    v = pd.to_numeric(valores, errors="coerce").dropna()
    v = v[v > 0]
    if v.empty:
        return []
    q = np.unique(np.quantile(v, np.linspace(0, 1, n + 1)))
    if len(q) < 2:
        q = np.array([0.0, float(v.max())])
    q[0] = min(q[0], float(v.min()))
    q[-1] = float(v.max()) * 1.0000001
    return [float(x) for x in q]


def _cores_classes(escala: str, formato: str, n: int) -> list[str]:
    pal = DIVERGENTE if formato == "pct" else PALETAS.get(escala, PALETAS["Blues"])
    if n <= 0:
        return []
    idx = np.linspace(0, len(pal) - 1, n) if formato == "pct" else np.linspace(1, len(pal) - 1, n)
    return [pal[int(round(i))] for i in idx]


def _classe(v, limites: list[float]) -> int | None:
    if v is None or (isinstance(v, float) and math.isnan(v)) or not limites:
        return None
    for i in range(len(limites) - 1):
        if v < limites[i + 1]:
            return i
    return len(limites) - 2


# ------------------------------------------------------------------ geometria
def _aneis(geom: dict):
    if not geom:
        return
    if geom["type"] == "Polygon":
        yield geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        for p in geom["coordinates"]:
            yield p[0]


def _area_centro(anel) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(anel, anel[1:] + anel[:1]):
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-12:
        xs, ys = zip(*anel)
        return 0.0, sum(xs) / len(xs), sum(ys) / len(ys)
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def _arredondar(geom: dict | None, casas: int = 4) -> dict | None:
    """Coordenadas com 4 casas (~11 m): o mapa fica 2–3x mais leve sem diferença visível."""
    if not geom:
        return geom

    def r(c):
        return [round(c[0], casas), round(c[1], casas)] if c and isinstance(c[0], (int, float)) else [r(x) for x in c]
    return {"type": geom["type"], "coordinates": r(geom["coordinates"])}


def centro(geom: dict) -> tuple[float, float]:
    """Centro do maior polígono (o rótulo da UF não cai no mar nem numa ilha)."""
    melhor = max((_area_centro([tuple(p[:2]) for p in an]) for an in _aneis(geom)), default=(0, 0.0, 0.0))
    return melhor[1], melhor[2]


def caixa(features: list[dict]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for f in features:
        for an in _aneis(f.get("geometry")):
            for p in an:
                xs.append(p[0])
                ys.append(p[1])
    if not xs:
        return -74.0, -34.0, -34.0, 5.5
    return min(xs), min(ys), max(xs), max(ys)


def _merc(lat: float) -> float:
    lat = max(min(lat, 85.0), -85.0)
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def enquadrar(bbox, largura: int = 1000, altura: int = 560, folga: float = 0.90) -> tuple[float, float, float]:
    """Centro e zoom que fazem a área caber inteira no quadro (projeção Web Mercator do deck.gl)."""
    x0, y0, x1, y1 = bbox
    dx = max((x1 - x0) / 360.0, 1e-6)
    m0, m1 = _merc(y0), _merc(y1)
    dy = max((m1 - m0) / (2 * math.pi), 1e-6)
    zoom = math.log2(min(largura * folga / (512 * dx), altura * folga / (512 * dy)))
    lat_c = math.degrees(2 * math.atan(math.exp((m0 + m1) / 2)) - math.pi / 2)
    return (x0 + x1) / 2, lat_c, max(min(zoom, 12.0), 1.0)


# ------------------------------------------------------------------ dicas
def _dica_area(r: dict, coluna: str, formato: str, titulo: str) -> str:
    linhas = [f"<div style='font-weight:700;font-size:13px;margin-bottom:4px'>{html.escape(str(r.get('nome', '')))}</div>",
              f"<div>{html.escape(titulo)}: <b>{_fmt(r.get(coluna), formato)}</b></div>"]
    for c, rot, f in (("valor", "Valor contratado", "brl"), ("part_caixa", "Participação CAIXA", "pct"),
                      ("saldo_concorrente", "Saldo no concorrente", "brl"), ("potencial", "Potencial de custódia", "brl"),
                      ("entes", "Entes", "int")):
        if c != coluna and c in r and r[c] is not None and not (isinstance(r[c], float) and math.isnan(r[c])):
            linhas.append(f"<div style='color:#5B6573'>{rot}: {_fmt(r[c], f)}</div>")
    return "".join(linhas)


def _dica_bolha(r: dict, rotulo_cor: str | None) -> str:
    linhas = [f"<div style='font-weight:700;font-size:13px;margin-bottom:4px'>{html.escape(str(r.get('rotulo', '')))}</div>",
              f"<div>Valor: <b>{_fmt(r.get('valor'), 'brl')}</b></div>"]
    if r.get("part_caixa") is not None and not (isinstance(r["part_caixa"], float) and math.isnan(r["part_caixa"])):
        linhas.append(f"<div style='color:#5B6573'>Participação CAIXA: {_fmt(r['part_caixa'], 'pct')}</div>")
    if r.get("entes"):
        linhas.append(f"<div style='color:#5B6573'>Entes: {int(r['entes'])}</div>")
    if rotulo_cor and r.get("_cor"):
        linhas.append(f"<div style='color:#5B6573'>{html.escape(str(r['_cor']))}</div>")
    return "".join(linhas)


# ------------------------------------------------------------------ montagem
def montar(df: pd.DataFrame, geojson: dict, coluna: str, formato: str = "brl", escala: str = "Blues",
           bolhas: pd.DataFrame | None = None, cores_bolha: dict | None = None, titulo: str = "",
           altura: int = 560, largura: int = 820, fundo: str | None = None, rotulos: bool | None = None):
    """Devolve (deck, legenda) — `deck` é um pydeck.Deck pronto para st.pydeck_chart; `legenda` é um dict
    com as faixas e cores, para desenhar a legenda em HTML abaixo do mapa."""
    import pydeck as pdk
    from pydeck.types import String as Literal   # sem isto o pydeck trata "pixels" como expressão JS

    titulo = titulo or coluna
    feats_in = (geojson or {}).get("features", [])
    base = df.copy() if df is not None and not df.empty else pd.DataFrame(columns=["codarea", "nome", coluna])
    base["codarea"] = base["codarea"].astype(str)
    por_cod = {r["codarea"]: r for r in base.to_dict("records")}
    limites = classes(base[coluna] if coluna in base else pd.Series(dtype=float), formato)
    cores = _cores_classes(escala, formato, max(len(limites) - 1, 0))

    feats = []
    for f in feats_in:
        cod = str(f.get("properties", {}).get("codarea", ""))
        r = por_cod.get(cod, {"codarea": cod, "nome": cod})
        v = r.get(coluna)
        k = _classe(float(v) if v is not None and v == v else None, limites)
        cor = cores[k] if k is not None and cores else SEM_DADO
        dica = _dica_area(r, coluna, formato, titulo) if cod in por_cod else \
            f"<div style='font-weight:700'>{html.escape(str(r.get('nome', cod)))}</div><div style='color:#5B6573'>Sem dados</div>"
        props = {"codarea": cod, "nome": str(r.get("nome", cod)), "cor": _rgba(cor), "dica": dica, "tipo": "area"}
        feats.append({"type": "Feature", "geometry": _arredondar(f.get("geometry")), "properties": props,
                      "codarea": cod, "dica": dica, "tipo": "area"})

    bbox = caixa(feats)
    lon, lat, zoom = enquadrar(bbox, largura, altura)
    camadas = [pdk.Layer(
        "GeoJsonLayer", {"type": "FeatureCollection", "features": feats}, id="areas", pickable=True,
        stroked=True, filled=True, get_fill_color="properties.cor", get_line_color=CONTORNO,
        line_width_units=Literal("pixels"), get_line_width=1 if len(feats) < 100 else 0.5, line_width_min_pixels=0.5,
        auto_highlight=True, highlight_color=[16, 24, 40, 70])]

    # siglas das UFs no mapa do Brasil
    if rotulos is None:
        rotulos = len(feats) <= 30
    if rotulos and feats:
        txt = []
        for f in feats:
            x, y = centro(f["geometry"])
            txt.append({"p": [x, y], "t": f["properties"]["nome"]})
        camadas.append(pdk.Layer("TextLayer", txt, id="siglas", get_position="p", get_text="t", get_size=12,
                                 size_units=Literal("pixels"), get_color=[16, 24, 40, 225], font_weight=700,
                                 font_family=Literal("Inter, 'Segoe UI', Arial, sans-serif"),
                                 outline_width=3, outline_color=[255, 255, 255, 230], font_settings={"sdf": True},
                                 get_text_anchor=Literal("middle"), get_alignment_baseline=Literal("center"), pickable=False))

    leg_bolhas = []
    if bolhas is not None and not bolhas.empty:
        b = bolhas.dropna(subset=["lat", "lon"]).copy()
        b = b[pd.to_numeric(b["valor"], errors="coerce").fillna(0) > 0]
        if not b.empty:
            mx = float(b["valor"].max())
            b["raio"] = 3 + 21 * np.sqrt(b["valor"].astype(float) / mx)
            cats = b["_cor"].astype(str) if "_cor" in b else pd.Series("Entes", index=b.index)
            paleta = ["#005CA9", "#F39200", "#00A19A", "#D1495B", "#7E5BB5", "#5B6573"]
            mapa_cor = {}
            for i, c in enumerate(pd.unique(cats)):
                mapa_cor[c] = (cores_bolha or {}).get(c) or paleta[i % len(paleta)]
            b["cor"] = cats.map(lambda c: _rgba(mapa_cor[c], 205))
            b = b.sort_values("valor", ascending=False)       # pequenas por cima
            dados = []
            for r in b.to_dict("records"):
                dados.append({"p": [float(r["lon"]), float(r["lat"])], "raio": float(r["raio"]), "cor": r["cor"],
                              "dica": _dica_bolha(r, "_cor" in b), "codarea": f"mun:{r.get('cod_ibge', '')}",
                              "tipo": "bolha"})
            camadas.append(pdk.Layer(
                "ScatterplotLayer", dados, id="bolhas", pickable=True, get_position="p", get_radius="raio",
                radius_units=Literal("pixels"), get_fill_color="cor", stroked=True, get_line_color=[255, 255, 255, 230],
                line_width_min_pixels=1, auto_highlight=True, highlight_color=[255, 194, 14, 220]))
            if "_cor" in b and len(mapa_cor) > 1 or "_cor" in b and list(mapa_cor) != ["Entes"]:
                leg_bolhas = [(c, mapa_cor[c]) for c in mapa_cor]

    estilo_dica = {"backgroundColor": "#FFFFFF", "color": "#101828", "fontFamily": "Inter, 'Segoe UI', sans-serif",
                   "fontSize": "12px", "padding": "10px 12px", "borderRadius": "8px",
                   "boxShadow": "0 6px 18px rgba(16,24,40,.18)", "border": "1px solid #E3E8EF", "maxWidth": "300px"}
    kw = {}
    if fundo:
        kw.update(map_provider="carto", map_style=fundo)
    else:
        kw.update(map_provider=None, map_style=None)
    deck = pdk.Deck(layers=camadas, initial_view_state=pdk.ViewState(longitude=lon, latitude=lat, zoom=zoom,
                                                                      min_zoom=max(zoom - 1.5, 1), max_zoom=13,
                                                                      pitch=0, bearing=0),
                    views=[pdk.View(type="MapView", controller={"dragRotate": False, "touchRotate": False,
                                                                "doubleClickZoom": True, "scrollZoom": True})],
                    tooltip={"html": "{dica}", "style": estilo_dica}, height=altura, **kw)
    faixas = []
    for i, c in enumerate(cores):
        a, z = limites[i], limites[i + 1]
        if formato == "pct":
            faixas.append((f"{round(a * 100):.0f}–{min(round(z * 100), 100):.0f}%", c))
        else:
            faixas.append((f"{_curto(a)} – {_curto(z)}", c))
    legenda = {"titulo": titulo, "faixas": faixas, "sem_dado": SEM_DADO, "bolhas": leg_bolhas}
    return deck, legenda


def _curto(v: float) -> str:
    a = abs(v)
    for lim, suf in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if a >= lim:
            return f"R$ {v / lim:,.1f}{suf}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v:,.0f}".replace(",", ".")


def legenda_html(leg: dict) -> str:
    itens = "".join(f"<span class='cx-leg-i'><i style='background:{c}'></i>{html.escape(t)}</span>"
                    for t, c in leg["faixas"])
    itens += f"<span class='cx-leg-i'><i style='background:{leg['sem_dado']}'></i>Sem dados</span>"
    bol = ""
    if leg.get("bolhas"):
        bol = "<span class='cx-leg-sep'></span>" + "".join(
            f"<span class='cx-leg-i'><i class='o' style='background:{c}'></i>{html.escape(str(t))}</span>"
            for t, c in leg["bolhas"])
    return (f"<div class='cx-leg'><span class='cx-leg-t'>{html.escape(leg['titulo'])}</span>{itens}{bol}"
            f"<span class='cx-leg-dica'>Arraste para mover · role para aproximar · clique para detalhar</span></div>")


def clicado(evento) -> str | None:
    """Código da área clicada (UF ou município) ou 'mun:<código>' da bolha, a partir do retorno do
    st.pydeck_chart com seleção."""
    if evento is None:
        return None
    sel = evento.get("selection") if isinstance(evento, dict) else getattr(evento, "selection", None)
    if sel is None:
        return None
    objs = sel.get("objects") if isinstance(sel, dict) else getattr(sel, "objects", None)
    for camada in ("bolhas", "areas"):
        for o in (objs or {}).get(camada, []) or []:
            if not isinstance(o, dict):
                continue
            cod = o.get("codarea") or (o.get("properties") or {}).get("codarea")
            if cod:
                return str(cod)
    return None
