"""Tela-mãe com visões (v0.9.2): o conteúdo de cada visão está em telas/visoes/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ctx = ui.pagina("Oportunidades e carteira",
               "Duas lentes complementares: o Potencial (quanto pode vir para a CAIXA e qual ação) e o Ranking de "
               "prospecção (score, janelas abertas, vazamentos e a carteira de abordagem).")
ui.visoes(ctx, {"Potencial e ações": "oport_potencial.py", "Ranking, janelas e carteira": "oport_ranking.py"},
          "oport_visao")
