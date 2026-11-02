"""Acesso aos marts publicados, pensado para o painel ficar leve sem perder nenhum dado.

Antes: cada clique copiava TODOS os ~85 marts (centenas de MB) do cache do Streamlit, que serializa e
desserializa o que guarda. Isso travava o navegador ("página não respondendo") nas telas pesadas.

Agora:
  * `Marts` lê cada tabela do disco só quando uma tela pede, uma vez por execução, e guarda na memória do
    processo (compartilhada entre usuários; nada é copiado a cada clique);
  * quem recebe a tabela ganha uma cópia rasa (custo zero). Com copy-on-write do pandas, alterar a cópia
    nunca altera o original guardado: uma tela não consegue "estragar" o dado de outra;
  * `memo` guarda o resultado de cálculos (filtros, agregações por território, etc.) por argumentos, também sem
    copiar a cada uso, com limite de entradas para não crescer sem fim.
Nenhuma linha é descartada: as telas continuam recebendo as tabelas completas.
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from functools import wraps
from pathlib import Path

import pandas as pd

from . import storage

# copy-on-write: padrão no pandas 3; no 2.x é ligado aqui (cópias rasas passam a ser seguras)
try:
    if int(pd.__version__.split(".")[0]) < 3:
        pd.set_option("mode.copy_on_write", True)
except Exception:  # pragma: no cover
    pass


def _raso(v):
    """Cópia rasa: protege o objeto guardado sem duplicar memória."""
    if isinstance(v, (pd.DataFrame, pd.Series)):
        return v.copy(deep=False)
    if isinstance(v, dict):
        return {k: _raso(x) for k, x in v.items()}
    if isinstance(v, tuple):
        return tuple(_raso(x) for x in v)
    if isinstance(v, list):
        return [_raso(x) for x in v]
    return v


class Marts(Mapping):
    """Dicionário preguiçoso dos marts de uma execução: d["fato_instrumento"], d.get(...), "x" in d."""

    def __init__(self, pasta: Path, nomes: list[str], execucao: str = ""):
        self.pasta, self.nomes, self.execucao = Path(pasta), list(nomes), execucao
        self._cache: dict[str, object] = {}
        self._trava = threading.Lock()
        self.tempos: dict[str, float] = {}

    def _ler(self, nome: str):
        if nome == "meta":
            arq = self.pasta / "meta.json"
            return json.loads(arq.read_text("utf-8")) if arq.exists() else {}
        t0 = time.perf_counter()
        df = storage.ler(self.pasta / nome)
        self.tempos[nome] = time.perf_counter() - t0
        return df

    def bruto(self, nome: str):
        """O objeto guardado (sem cópia) — uso interno de cálculos memorizados."""
        if nome not in self._cache:
            if nome != "meta" and nome not in self.nomes:
                raise KeyError(nome)
            with self._trava:
                if nome not in self._cache:
                    self._cache[nome] = self._ler(nome)
        return self._cache[nome]

    def __getitem__(self, nome: str):
        return _raso(self.bruto(nome))

    def __iter__(self):
        return iter(["meta", *self.nomes])

    def __len__(self) -> int:
        return len(self.nomes) + 1

    def __contains__(self, nome) -> bool:
        return nome == "meta" or nome in self.nomes

    def carregados(self) -> list[str]:
        return [n for n in self._cache if n != "meta"]

    def memoria_mb(self) -> float:
        tot = 0
        for v in self._cache.values():
            if isinstance(v, pd.DataFrame):
                tot += int(v.memory_usage(deep=False).sum())
        return tot / 1e6


# ------------------------------------------------------------------ memória de cálculos
def _chave(v):
    """Chave estável e barata para os argumentos de um cálculo."""
    if isinstance(v, Marts):
        return ("marts", str(v.pasta))
    if isinstance(v, (list, tuple)):
        return tuple(_chave(x) for x in v)
    if isinstance(v, (set, frozenset)):
        return ("set", tuple(sorted(map(str, v))))
    if isinstance(v, dict):
        return tuple(sorted((str(k), _chave(x)) for k, x in v.items()))
    if isinstance(v, (pd.DataFrame, pd.Series)):
        # tabela montada na hora não tem identidade estável (o id é reaproveitado): não memoriza
        return [None]
    return v


class _LRU:
    def __init__(self, maximo: int):
        self.maximo, self.itens, self.trava = maximo, OrderedDict(), threading.Lock()

    def get(self, k):
        with self.trava:
            if k in self.itens:
                self.itens.move_to_end(k)
                return True, self.itens[k]
        return False, None

    def put(self, k, v):
        with self.trava:
            self.itens[k] = v
            self.itens.move_to_end(k)
            while len(self.itens) > self.maximo:
                self.itens.popitem(last=False)

    def limpar(self):
        with self.trava:
            self.itens.clear()


_MEMOS: list[_LRU] = []
ESTATISTICA = {"acertos": 0, "calculos": 0, "segundos_calculando": 0.0}


def memo(maximo: int = 48):
    """Memoriza o resultado por argumentos (a execução dos dados entra na chave via `Marts`)."""
    def deco(fn):
        lru = _LRU(maximo)
        _MEMOS.append(lru)

        @wraps(fn)
        def w(*a, **k):
            chave = (_chave(a), _chave(k))
            try:
                hash(chave)
            except TypeError:
                return fn(*a, **k)
            ok, v = lru.get(chave)
            if ok:
                ESTATISTICA["acertos"] += 1
                return _raso(v)
            t0 = time.perf_counter()
            v = fn(*a, **k)
            ESTATISTICA["calculos"] += 1
            ESTATISTICA["segundos_calculando"] += time.perf_counter() - t0
            lru.put(chave, v)
            return _raso(v)
        w.limpar = lru.limpar
        return w
    return deco


def limpar_memos() -> None:
    for m in _MEMOS:
        m.limpar()
