"""Tela-mãe com visões (v0.9.2): o conteúdo de cada visão está em telas/visoes/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ctx = ui.pagina("Qualidade e auditoria",
               "A confiança nos números: atualização das fontes, auditoria da carga (completude, chaves, frescor, "
               "reconciliação) e auditoria profunda (recontas independentes, Benford, extremos e rede neural de "
               "anomalias).", filtros=False)
ui.visoes(ctx, {"Atualização das fontes": "qualidade_atualizacao.py", "Auditoria da carga": "qualidade_carga.py",
                "Auditoria profunda": "qualidade_profunda.py"}, "qual_visao")
