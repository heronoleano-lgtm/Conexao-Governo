"""Tela-mãe com visões (v0.9.2): o conteúdo de cada visão está em telas/visoes/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ctx = ui.pagina("Visão 360 do ente",
               "Um ente, três leituras: o 360 do CRM (quanto recebe, onde fica, quem manda, conformidade), o roteiro "
               "do Assessor (diagnóstico, recomendações e argumentos) e a Ficha técnica (instrumentos, contas, "
               "janelas, a creditar e simulador). A escolha do ente vale nas três.", filtros=False)
ui.visoes(ctx, {"360 · CRM": "ente_360.py", "Assessor da visita": "ente_assessor.py",
                "Ficha técnica": "ente_ficha.py"}, "ente_visao")
