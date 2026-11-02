"""TELA_INCORPORADA (v0.9.2): virou a visão "Auditoria da carga" de pages/12_Qualidade_dos_dados.py. Mantida só para endereços antigos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ui.redirecionar("pages/12_Qualidade_dos_dados.py", ("qual_visao", "Auditoria da carga"))
