"""TELA_INCORPORADA (v0.9.2): virou a visão "Portaria 15/2025 · conta própria" de pages/31_CRM_Conformidade.py. Mantida só para endereços antigos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ui.redirecionar("pages/31_CRM_Conformidade.py", ("conf_visao", "Portaria 15/2025 · conta própria"))
