"""TELA_INCORPORADA (v0.9.2): virou a visão "Assessor da visita" de pages/28_CRM_Visao_360.py. Mantida só para endereços antigos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ui.redirecionar("pages/28_CRM_Visao_360.py", ("ente_visao", "Assessor da visita"))
