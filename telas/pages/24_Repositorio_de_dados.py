import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from custodia import consultas as q  # noqa: E402
from custodia import graficos as g  # noqa: E402

from custodia.ui import baixar, cartoes, leitura, pagina, secao  # noqa: E402

ctx = pagina("Repositório de dados",
             "O que está guardado entre as cargas: carga bruta do dia, histórico só de mudanças (reconstrói qualquer "
             "dia), série diária de saldo por ente, registro das cargas e fotos completas quando pedidas.", filtros=False)
d = ctx.d
cat, reg, ver = d["repo_catalogo"], d["repo_registro_cargas"], d.get("repo_verificacao", pd.DataFrame())
serie = cat[cat["tabela"].astype(str).str.startswith("serie_ente")] if not cat.empty else cat
cartoes([
    {"rotulo": "Tabelas guardadas", "valor": len(cat)},
    {"rotulo": "Tamanho em disco", "valor": f"{cat['tamanho_mb'].fillna(0).sum():,.0f} MB".replace(",", ".")},
    {"rotulo": "Dias na série por ente", "valor": int(serie["cargas"].iloc[0]) if not serie.empty and pd.notna(serie["cargas"].iloc[0]) else 0,
     "sub": f"desde {serie['primeira_carga'].iloc[0]}" if not serie.empty else ""},
    {"rotulo": "Histórico sem perda", "valor": ("Sim" if ver["ok"].all() else "Não") if not ver.empty else "—",
     "cor": "#00A19A" if ver.empty or ver["ok"].all() else "#D1495B",
     "sub": f"{len(ver)} tabelas verificadas hoje" if not ver.empty else ""},
    {"rotulo": "Cargas registradas", "valor": reg["dia"].nunique() if not reg.empty else 0,
     "sub": f"{int((~reg['ok']).sum())} itens com erro" if not reg.empty else ""},
])
leitura("Como o repositório guarda tudo sem duplicar", [
    "Todas as tabelas baixadas entram no histórico de mudanças: uma versão nova só quando o registro muda. "
    "A cada carga o painel reconstrói o dia pelo histórico e compara com a fonte, linha a linha (regra QLD-02).",
    "Foto completa mensal, à parte: todas as colunas da API e os CSVs originais (zip). Foto avulsa: "
    "<code>carga_diaria.bat --foto</code>; todo dia: <code>foto_completa: diaria</code> no config.yaml.",
    "Reconstruir qualquer dia passado: <code>reconstruir_dia.bat AAAA-MM-DD</code>.",
    "Nova pergunta de negócio: endpoint ou arquivo novo no config.yaml → histórico, se precisar de passado → motor → "
    "tela, registrada em perguntas.yaml e regras.yaml."])
aba1, aba2, aba3 = st.tabs(["Catálogo", "Registro das cargas", "Verificação sem perda"])
with aba3:
    g.grade(ver, chave="repo_ver")
with aba1:
    camada = st.multiselect("Camada", sorted(cat["camada"].dropna().unique()) if not cat.empty else [], placeholder="Todas")
    g.grade(cat[cat["camada"].isin(camada)] if camada else cat, chave="repo_cat")
with aba2:
    if not reg.empty:
        por_dia = reg.groupby("dia", as_index=False).agg(linhas=("linhas", "sum"))
        g.barras(por_dia, "dia", {"linhas": "Linhas carregadas"}, chave="repo_reg", formato="int", altura=260)
    g.grade(reg.sort_values("dia", ascending=False) if not reg.empty else reg, chave="repo_reg_tab")
baixar("repositorio", {"catalogo": cat, "registro_cargas": reg})
