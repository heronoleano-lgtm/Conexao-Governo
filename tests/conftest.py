import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
# sem pyarrow no ambiente de teste, grava em pickle; em produção é Parquet
try:
    import pyarrow  # noqa: F401
except ImportError:
    os.environ.setdefault("CUSTODIA_STORAGE", "pickle")

# a chave real (config/segredos.yaml) nunca é usada nos testes
os.environ["PORTAL_API_CHAVE"] = "chave-de-teste"
