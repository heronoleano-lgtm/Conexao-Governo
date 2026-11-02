"""Filtros por clique (filtro cruzado) e medição de desempenho das telas.

Clique num gráfico → o valor vira um filtro ativo, visível como etiqueta no topo da tela e válido em todas as
telas da sessão (até ser removido). Modalidade, ano e UF vão para a própria barra lateral; as demais dimensões
(banco, segmento, porte, órgão, parlamentar, município…) ficam como filtros extras.

O Streamlit é importado dentro das funções: o módulo funciona com o simulador dos testes.
"""
from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

DIMENSOES = {
    "modulo": "Modalidade", "ano": "Ano", "uf": "UF", "grupo_banco": "Banco", "banco_principal": "Banco principal",
    "segmento": "Segmento", "porte": "Porte", "esfera": "Esfera", "tipo_ente": "Tipo de ente", "regiao": "Região",
    "cod_ibge": "Município", "orgao": "Órgão", "orgao_superior": "Órgão superior", "parlamentar": "Parlamentar",
    "acao_recomendada": "Ação recomendada", "faixa_caixa": "Faixa CAIXA", "status": "Etapa", "area": "Área",
    "fonte": "Fonte", "classe_saldo": "Classe do saldo", "cnpj_ente": "Ente", "programa": "Programa",
}
BARRA = {"modulo": "f_mod", "ano": "f_ano", "uf": "f_uf"}      # dimensões que vivem na barra lateral
EXTRA = "f_extra"
PENDENTE = "_f_pendente"


def _ss():
    import streamlit as st
    return st.session_state


def extras() -> dict[str, list]:
    return dict(_ss().get(EXTRA) or {})


def rotulo(dim: str, valor, nomes: dict | None = None) -> str:
    v = (nomes or {}).get(valor, valor)
    if dim == "modulo":
        from .semantica import nome_modalidade
        v = nome_modalidade(valor)
    return f"{DIMENSOES.get(dim, dim)}: {v}"


def clicar(dim: str, valor, nome: str | None = None) -> None:
    """Aplica (ou retira, se já estiver ativo) o filtro e redesenha a tela."""
    import streamlit as st
    if valor is None or (isinstance(valor, float) and valor != valor):
        return
    ss = _ss()
    if dim in BARRA:
        pend = dict(ss.get(PENDENTE) or {})
        atual = list(ss.get(BARRA[dim]) or [])
        so_ele = atual == [valor]
        pend[dim] = None if so_ele else [valor]          # None = volta a "todos"
        ss[PENDENTE] = pend
    else:
        ex = extras()
        vals = list(ex.get(dim) or [])
        if valor in vals:
            vals.remove(valor)
        else:
            vals = [valor]                                # clique troca o filtro da dimensão
        if vals:
            ex[dim] = vals
        else:
            ex.pop(dim, None)
        ss[EXTRA] = ex
        if nome:
            nomes = dict(ss.get("_f_nomes") or {})
            nomes[f"{dim}|{valor}"] = nome
            ss["_f_nomes"] = nomes
    st.rerun()


def evento_novo(chave: str, bruto) -> tuple[int | None, str | None]:
    """O componente de gráfico devolve o último clique em toda nova execução; só um clique NOVO conta.
    O JavaScript devolve 'índice|nome|carimbo'."""
    if not bruto or not isinstance(bruto, str) or bruto.count("|") < 2:
        return None, None
    ss = _ss()
    k = f"_ev_{chave}"
    if ss.get(k) == bruto:
        return None, None
    ss[k] = bruto
    i, nome, _ = bruto.split("|", 2)
    try:
        return int(i), nome
    except ValueError:
        return None, nome


JS_CLIQUE = "function(p){ return String(p.dataIndex) + '|' + String(p.name) + '|' + Date.now(); }"


def remover(dim: str, valor=None) -> None:
    ss = _ss()
    if dim in BARRA:
        pend = dict(ss.get(PENDENTE) or {})
        pend[dim] = None
        ss[PENDENTE] = pend
    else:
        ex = extras()
        if valor is None or valor in (ex.get(dim) or []):
            vals = [v for v in (ex.get(dim) or []) if valor is not None and v != valor]
            if vals:
                ex[dim] = vals
            else:
                ex.pop(dim, None)
        ss[EXTRA] = ex


def limpar() -> None:
    ss = _ss()
    ss[EXTRA] = {}
    ss[PENDENTE] = {d: None for d in BARRA}


def aplicar_pendentes(opcoes: dict[str, list]) -> None:
    """Antes de desenhar a barra lateral: leva os cliques para os filtros da barra (o Streamlit não deixa mudar
    um filtro depois que ele foi desenhado na execução)."""
    ss = _ss()
    pend = ss.pop(PENDENTE, None) or {}
    for dim, chave in BARRA.items():
        ops = opcoes.get(dim) or []
        if dim in pend:
            ss[chave] = list(ops) if pend[dim] is None and dim != "uf" else (pend[dim] or [])
        atual = ss.get(chave)
        if atual is None:
            ss[chave] = [] if dim == "uf" else list(ops)
        else:   # valores que não existem nesta carga quebrariam o filtro
            ss[chave] = [v for v in atual if v in ops]


# ------------------------------------------------------------------ desempenho
class Cronometro:
    """Mede o tempo de montagem de cada tela; grava em logs/telas.csv para diagnóstico no computador do usuário."""

    def __init__(self, tela: str):
        self.tela, self.t0 = tela, time.perf_counter()

    def fim(self, pasta_logs: Path | None, extra: dict | None = None) -> float:
        dt = time.perf_counter() - self.t0
        if pasta_logs is not None:
            try:
                pasta_logs.mkdir(parents=True, exist_ok=True)
                arq = pasta_logs / "telas.csv"
                novo = not arq.exists()
                with arq.open("a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f, delimiter=";")
                    if novo:
                        w.writerow(["quando", "tela", "segundos", "tabelas_em_memoria", "memoria_mb", "calculos",
                                    "reaproveitados"])
                    e = extra or {}
                    w.writerow([datetime.now().isoformat(timespec="seconds"), self.tela, f"{dt:.2f}",
                                e.get("tabelas", ""), e.get("memoria_mb", ""), e.get("calculos", ""),
                                e.get("acertos", "")])
            except Exception:
                pass
        return dt
