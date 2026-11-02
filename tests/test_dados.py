"""Camada de dados do painel: leitura sob demanda, sem cópia a cada uso e sem uma tela alterar o dado de outra."""
import pandas as pd

from custodia import dados, storage


def _marts(tmp_path):
    storage.gravar(pd.DataFrame({"uf": ["MG", "SP", "MG"], "valor": [1.0, 2.0, 3.0], "modulo": ["A", "A", "B"]}),
                   tmp_path / "fato_x")
    storage.gravar(pd.DataFrame({"k": [1]}), tmp_path / "fato_y")
    (tmp_path / "meta.json").write_text('{"dia": "2026-11-01"}', "utf-8")
    return dados.Marts(tmp_path, ["fato_x", "fato_y"], "teste")


def test_leitura_sob_demanda_e_protegida(tmp_path):
    d = _marts(tmp_path)
    assert d.carregados() == []                          # nada lido antes de alguém pedir
    x = d["fato_x"]
    assert d.carregados() == ["fato_x"] and d["meta"]["dia"] == "2026-11-01"
    x.loc[0, "valor"] = 999.0                            # a tela altera a SUA cópia…
    x["nova"] = 1
    assert d["fato_x"]["valor"].iloc[0] == 1.0           # …e o dado guardado continua intacto
    assert "nova" not in d["fato_x"]
    assert "fato_y" in d and "nao_existe" not in d and d.get("nao_existe") is None
    assert set(dict(d.items())) == {"meta", "fato_x", "fato_y"}


def test_memo_reaproveita_e_nao_vaza(tmp_path):
    from custodia import consultas as q
    d = _marts(tmp_path)
    antes = dados.ESTATISTICA["calculos"]
    a = q.filtrada(d, "fato_x", None, None, ["MG"])
    b = q.filtrada(d, "fato_x", None, None, ["MG"])
    assert dados.ESTATISTICA["calculos"] == antes + 1     # o segundo pedido não recalculou
    assert len(a) == 2 and a["valor"].sum() == 4.0
    a.loc[a.index[0], "valor"] = -1.0
    assert q.filtrada(d, "fato_x", None, None, ["MG"])["valor"].sum() == 4.0
    assert b["valor"].sum() == 4.0
    c = q.filtrada(d, "fato_x", None, None, None, {"modulo": ["B"]})   # filtro de clique
    assert c["valor"].sum() == 3.0
    # tabela montada na hora não é memorizada por identidade (o id do objeto é reaproveitado pelo Python)
    assert dados._chave(pd.DataFrame({"a": [1]})) == [None]
