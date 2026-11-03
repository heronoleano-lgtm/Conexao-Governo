"""Regras de proporção ESTET-01 a ESTET-06 (custodia/ui.py). Uma mudança visual fora das escalas quebra este teste."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

if importlib.util.find_spec("streamlit") is None:            # fora do Windows do usuário: simulador dos testes
    from tests import st_stub
    sys.modules.setdefault("streamlit", st_stub.criar({}))
from custodia import ui  # noqa: E402

RAIZ = Path(ui.__file__).resolve().parents[1]


def _px(prop: str) -> list[float]:
    """Valores em px usados em `prop` no CSS do painel (variáveis resolvidas)."""
    css = ui.CSS
    tokens = dict(re.findall(r"(--[er]\d):\s*(\d+)px", css))
    vals = []
    for bloco in re.findall(rf"(?<![-\w]){prop}(?:-[a-z]+)?:\s*([^;}}]+)", css):
        for v in re.findall(r"var\((--[er]\d)\)|(\d+(?:\.\d+)?)px", bloco):
            vals.append(float(tokens[v[0]]) if v[0] else float(v[1]))
    return vals


@pytest.mark.parametrize("prop", ["margin", "padding", "gap", "border-radius"])
def test_espacos_so_da_escala_de_fibonacci(prop):            # ESTET-02
    fora = sorted({v for v in _px(prop) if v not in ui.FIB and v != 999})   # 999 = pílula
    assert not fora, f"{prop} fora da escala {ui.FIB}: {fora}"


def test_escala_tipografica_raiz_de_phi():                   # ESTET-03
    passos = [float(ui._t(n).removesuffix("rem")) for n in range(-1, 5)]
    for a, b in zip(passos, passos[1:]):
        assert b / a == pytest.approx(ui.PHI ** .5, rel=2e-3)
    assert float(ui._t(2).removesuffix("rem")) == pytest.approx(ui.PHI, rel=1e-3)


def test_selo_da_caixa_na_proporcao_aurea():                 # ESTET-04
    w0, h0 = ui.tamanho_logo("CAIXA")
    for alvo in (ui.LOGO_ENTRADA, ui.LOGO_CABECALHO):
        m = ui.medidas_selo(alvo)
        assert m["x_altura"] <= h0                            # nunca amplia o arquivo da marca
        assert m["selo_altura"] / m["x_altura"] == pytest.approx(ui.PHI, rel=5e-3)
        assert m["x_largura"] / m["x_altura"] == pytest.approx(w0 / h0, rel=2e-2)   # sem distorcer
        assert m["canto"] in ui.FIB
    assert ui.medidas_selo(ui.LOGO_CABECALHO)["selo_altura"] == pytest.approx(55, abs=.1)


def test_divisoes_de_tela_em_phi():                          # ESTET-01
    assert ui.AUREA[0] / ui.AUREA[1] == pytest.approx(1.618, abs=1e-3)
    assert "61.8%" in ui.CSS                                  # faixa azul/laranja do cabeçalho
    quase = re.compile(r"st\.columns\(\[(3, 2|2, 3|1, 1\.6, 1)\]\)")
    restos = [str(p.relative_to(RAIZ)) for p in (RAIZ / "telas").rglob("*.py") if quase.search(p.read_text("utf-8"))]
    restos += ["custodia/ui.py"] if quase.search((RAIZ / "custodia" / "ui.py").read_text("utf-8")) else []
    assert not restos, f"divisões 3:2 aproximadas em vez de φ:1 em {restos}"


def test_entrada_na_linha_aurea():                           # ESTET-05 e ESTET-06
    assert "* 0.382" in ui.CSS and "--cx-selo" in ui.CSS


# ---------------------------------------------------------------- mapa: nomes e rolagem (02/11)
def test_mapa_mostra_nome_e_resume_nome_longo():
    from custodia import mapa
    assert mapa.resumir("MUNICIPIO DE NOVA OLINDA") == "Nova Olinda"
    curto = mapa.resumir("INSTITUTO CULTURAL CENTRO DE MEMORIA QUEIXADAS")
    assert len(curto) <= mapa.LIMITE_NOME and curto.endswith("…") and not curto.endswith(" de…")
    assert mapa.nome_area("35") == "São Paulo (SP)"
    assert mapa.nome_area("3550308", "3550308", {"3550308": "São Paulo"}) == "São Paulo"   # nunca só o código


def test_roda_do_mouse_rola_a_pagina_e_pontos_tem_nome():
    import pandas as pd
    from custodia import mapa
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"codarea": "3550308"},
         "geometry": {"type": "Polygon", "coordinates": [[[-46.8, -23.4], [-46.4, -23.4], [-46.4, -23.8], [-46.8, -23.4]]]}}]}
    b = pd.DataFrame({"lat": [-23.55], "lon": [-46.63], "valor": [10.0], "rotulo": ["São Paulo · SP"],
                      "rotulo_curto": ["INSTITUTO CULTURAL CENTRO DE MEMORIA QUEIXADAS"], "entes": [1],
                      "entes_nomes": [["Inst. Cultural Centro de Memoria Queixadas"]], "cod_ibge": ["3550308"]})
    deck, _ = mapa.montar(pd.DataFrame(), geo, "valor", bolhas=b, nomes={"3550308": "São Paulo"})
    spec = deck.to_json()
    assert '"scrollZoom": false' in spec
    assert '"dt": "S' in spec and "Paulo" in spec and '"dt": "3550308"' not in spec   # área sem dados mostra o nome
    import json
    dados = json.dumps([l for l in json.loads(spec)["layers"] if l["id"] in ("areas", "bolhas")])
    assert "<div" not in dados and "<b>" not in dados        # dados só em texto: o pydeck escapa HTML dos dados
    assert "Inst. Cultural Centro" in spec and '"id": "nomes_bolhas"' in spec
