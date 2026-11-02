"""TELA_INCORPORADA (v0.9.2): virou a visão "Potencial e ações" de pages/09_Oportunidades.py. Mantida só para endereços antigos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ui.redirecionar("pages/09_Oportunidades.py", ("oport_visao", "Potencial e ações"))
