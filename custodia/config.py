"""Leitura da configuração e caminhos do projeto."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(os.environ.get("CUSTODIA_RAIZ", Path(__file__).resolve().parent.parent))


@dataclass(frozen=True)
class Caminhos:
    raiz: Path
    dados: Path

    @property
    def bruto(self) -> Path:
        return self.dados / "bruto"

    @property
    def historico(self) -> Path:
        return self.dados / "historico"

    @property
    def marts(self) -> Path:
        return self.dados / "marts"

    @property
    def referencias(self) -> Path:
        return self.dados / "referencias"

    @property
    def estado(self) -> Path:
        return self.dados / "estado"

    @property
    def logs(self) -> Path:
        return self.dados / "logs"

    @property
    def carteira_db(self) -> Path:
        return self.dados / "carteira" / "carteira.sqlite"

    @property
    def usuarios(self) -> Path:
        return self.raiz / "config" / "usuarios.yaml"

    def criar(self) -> None:
        for p in (self.bruto, self.historico, self.marts, self.referencias, self.estado, self.logs,
                  self.carteira_db.parent):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=4)
def carregar(caminho: str | None = None) -> dict:
    arq = Path(caminho) if caminho else RAIZ / "config" / "config.yaml"
    with open(arq, encoding="utf-8") as f:
        return yaml.safe_load(f)


def caminhos(cfg: dict | None = None) -> Caminhos:
    cfg = cfg or carregar()
    pasta = Path(os.environ.get("CUSTODIA_DADOS", cfg["dados"]["pasta"]))
    if not pasta.is_absolute():
        pasta = RAIZ / pasta
    return Caminhos(raiz=RAIZ, dados=pasta)
