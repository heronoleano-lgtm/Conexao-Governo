"""Tela-mãe com visões (v0.9.2): o conteúdo de cada visão está em telas/visoes/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodia import ui  # noqa: E402

ctx = ui.pagina("Conformidade",
               "Pontos de atenção para a Conformidade da CAIXA: cadastros de sanções (CEIS, CNEP, CEPIM) cruzados com "
               "recebedores e fornecedores, e — para gestão — saídas para conta própria depois da Portaria Conjunta "
               "MF/MGI 15/2025. A leitura jurídica e a decisão cabem à Conformidade.", filtros=False)
op = {"Sanções (CEIS, CNEP, CEPIM)": "conformidade_sancoes.py"}
if ctx.usuario.get("perfil") in ("gestao", "administrador"):
    op["Portaria 15/2025 · conta própria"] = "conformidade_portaria.py"
ui.visoes(ctx, op, "conf_visao")
