"""Teste rápido de conexão com as fontes: rode antes da primeira carga.

    python -m custodia.diagnostico
"""
from __future__ import annotations

import sys
import time

from . import config
from .http import Cliente


def main() -> int:
    cfg = config.carregar()
    api = cfg["api"]
    cli = Cliente(api["base_url"], api["user_agent"], timeout=30, tentativas=2)
    testes = []
    for modulo, m in cfg["modulos"].items():
        if m.get("ativo"):
            testes.append((f"{m['nome']}: data de atualização", f"/{modulo}/data-atualizacao", None))
            ep = m["endpoints"][0] if isinstance(m["endpoints"][0], str) else m["endpoints"][0]["nome"]
            testes.append((f"{m['nome']}: {ep}", f"/{modulo}/{ep}", {"tamanho_da_pagina": 1}))
    if cfg.get("csv_discricionarias", {}).get("ativo"):
        testes.append(("CSVs de Discricionárias: listagem", cfg["csv_discricionarias"]["listagem"], "xml"))
    testes.append(("Siconfi (entes)", cfg["referencias"]["siconfi_entes"], "raw"))
    testes.append(("Coordenadas dos municípios", cfg["referencias"]["municipios_coordenadas"], "raw"))

    falhas = 0
    for nome, caminho, params in testes:
        t0 = time.time()
        try:
            if params in ("xml", "raw"):
                r = cli.get(caminho)
                info = f"{len(r.content):,} bytes".replace(",", ".")
            else:
                j = cli.json(caminho, params)
                info = f"{j.get('total_items'):,} registros".replace(",", ".") if "total_items" in j else str(j)[:60]
            print(f"[OK]    {nome}: {info} ({time.time() - t0:.1f}s)")
        except Exception as e:
            falhas += 1
            print(f"[FALHA] {nome}: {e}")
    print()
    print("Tudo certo. Pode rodar a carga." if not falhas else
          f"{falhas} teste(s) falharam. Veja 'Problemas comuns' no README.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
