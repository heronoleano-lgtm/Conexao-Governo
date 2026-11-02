"""Ingestão das APIs do Transferegov (qualquer módulo com o mesmo contrato).

Para cada endpoint: lê a página 1 (descobre total_pages), baixa o resto em paralelo,
achata campos aninhados, confere a contagem com total_items e grava em Parquet.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import storage
from .http import Cliente

log = logging.getLogger(__name__)


@dataclass
class ResultadoCarga:
    modulo: str
    endpoint: str
    esperado: int = 0
    carregado: int = 0
    paginas: int = 0
    segundos: float = 0.0
    erro: str | None = None
    colunas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.erro is None and self.esperado == self.carregado


def achatar(registro: dict, prefixo: str = "") -> dict:
    out = {}
    for k, v in registro.items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            out.update(achatar(v, f"{chave}__"))
        elif isinstance(v, list):
            out[chave] = json.dumps(v, ensure_ascii=False)
        else:
            out[chave] = v
    return out


def baixar_endpoint(cli: Cliente, modulo: str, endpoint: str, tamanho: int = 200,
                    conexoes: int = 6, params_extra: dict | None = None) -> tuple[pd.DataFrame, ResultadoCarga]:
    import time
    t0 = time.time()
    res = ResultadoCarga(modulo, endpoint)
    caminho = f"/{modulo}/{endpoint}"
    base = dict(params_extra or {}, tamanho_da_pagina=tamanho)
    primeira = cli.json(caminho, dict(base, pagina=1))
    res.esperado = int(primeira.get("total_items", 0))
    res.paginas = int(primeira.get("total_pages", 0))
    paginas: dict[int, list] = {1: primeira.get("data", [])}

    if res.paginas > 1:
        with ThreadPoolExecutor(max_workers=conexoes) as ex:
            futuros = {ex.submit(cli.json, caminho, dict(base, pagina=p)): p for p in range(2, res.paginas + 1)}
            for i, f in enumerate(as_completed(futuros), 1):
                p = futuros[f]
                paginas[p] = f.result().get("data", [])
                if i % 200 == 0:
                    log.info("%s: %d/%d páginas", caminho, i + 1, res.paginas)

    registros = [achatar(r) for p in sorted(paginas) for r in paginas[p]]
    df = pd.DataFrame.from_records(registros)
    res.carregado = len(df)
    res.colunas = list(df.columns)
    res.segundos = round(time.time() - t0, 1)
    if res.carregado != res.esperado:
        log.warning("%s: esperado %d, carregado %d", caminho, res.esperado, res.carregado)
    return df, res


def data_atualizacao(cli: Cliente, modulo: str) -> str | None:
    try:
        return cli.json(f"/{modulo}/data-atualizacao").get("data_ultima_atualizacao")
    except Exception as e:  # não bloqueia a carga
        log.warning("Sem data de atualização para %s: %s", modulo, e)
        return None


def esquema(cli: Cliente, modulo: str) -> dict:
    """Mapa endpoint -> lista de parâmetros (= colunas) a partir do openapi.json."""
    spec = cli.json(f"/{modulo}/openapi.json")
    out = {}
    for path, ops in spec.get("paths", {}).items():
        op = ops.get("get") or {}
        nomes = [p["name"] for p in op.get("parameters", []) if p.get("name") not in ("pagina", "tamanho_da_pagina")]
        out[path.strip("/")] = sorted(nomes)
    return out


def comparar_esquemas(antigo: dict, novo: dict) -> list[dict]:
    mudancas = []
    for ep in sorted(set(antigo) | set(novo)):
        a, n = set(antigo.get(ep, [])), set(novo.get(ep, []))
        if ep not in antigo:
            mudancas.append({"endpoint": ep, "tipo": "endpoint novo", "colunas": ""})
        elif ep not in novo:
            mudancas.append({"endpoint": ep, "tipo": "endpoint removido", "colunas": ""})
        else:
            if n - a:
                mudancas.append({"endpoint": ep, "tipo": "colunas novas", "colunas": ", ".join(sorted(n - a))})
            if a - n:
                mudancas.append({"endpoint": ep, "tipo": "colunas removidas", "colunas": ", ".join(sorted(a - n))})
    return mudancas


def carregar_modulo(cli: Cliente, modulo: str, endpoints: list[str], pasta_bruto: Path, pasta_estado: Path,
                    dia: date, tamanho: int, conexoes: int, so_faltantes: bool = False) -> dict:
    """Baixa os endpoints de um módulo e devolve o manifesto da carga.

    so_faltantes=True baixa só os endpoints que ainda não têm nenhuma carga bruta gravada
    (aproveita o que já foi baixado e completa o que entrou de novo no config.yaml)."""
    manifesto = {"modulo": modulo, "dia": dia.isoformat(), "data_atualizacao": data_atualizacao(cli, modulo),
                 "cargas": [], "mudancas_esquema": []}

    arq_esquema = pasta_estado / f"esquema_{modulo}.json"
    try:
        novo = esquema(cli, modulo)
        if arq_esquema.exists():
            manifesto["mudancas_esquema"] = comparar_esquemas(json.loads(arq_esquema.read_text("utf-8")), novo)
        arq_esquema.write_text(json.dumps(novo, ensure_ascii=False, indent=1), "utf-8")
    except Exception as e:
        log.warning("Não consegui ler o openapi.json de %s: %s", modulo, e)

    for item in endpoints:
        ep, params = (item["nome"], item.get("params")) if isinstance(item, dict) else (item, None)
        if so_faltantes and tem_bruto(pasta_bruto, modulo, ep):
            log.info("%s/%s: já baixado, reaproveitado", modulo, ep)
            continue
        try:
            df, res = baixar_endpoint(cli, modulo, ep, tamanho, conexoes, params)
            storage.gravar(df, pasta_bruto / modulo / ep / dia.isoformat())
            log.info("%s/%s: %d linhas em %.0fs", modulo, ep, res.carregado, res.segundos)
        except Exception as e:
            log.exception("Falha em %s/%s", modulo, ep)
            res = ResultadoCarga(modulo, ep, erro=str(e)[:500])
        manifesto["cargas"].append(asdict(res) | {"ok": res.ok})
    return manifesto


def tem_bruto(pasta_bruto: Path, modulo: str, endpoint: str) -> bool:
    pasta = pasta_bruto / modulo / endpoint
    return pasta.exists() and any(p.suffix == storage.EXT for p in pasta.iterdir())


def ultimo_bruto(pasta_bruto: Path, modulo: str, endpoint: str) -> pd.DataFrame:
    """Lê a carga bruta mais recente de um endpoint (vazio se nunca carregado)."""
    pasta = pasta_bruto / modulo / endpoint
    if not pasta.exists():
        return pd.DataFrame()
    arquivos = sorted(p for p in pasta.iterdir() if p.suffix == storage.EXT)
    return storage.ler(arquivos[-1]) if arquivos else pd.DataFrame()


# pastas que são CACHE (uma unidade por arquivo, nome = id da consulta), não fotos diárias: nunca podam
CACHE_SEM_PODA = {"portal_api"}


def limpar_bruto(pasta_bruto: Path, manter_dias: int) -> None:
    """Mantém as últimas N fotos diárias de cada endpoint. A API do Portal guarda uma unidade por arquivo com nome
    em hexadecimal: podar por ordem de nome apagava unidades válidas (v0.8.3 manteve só 30 por conjunto)."""
    for pasta in pasta_bruto.glob("*/*"):
        if not pasta.is_dir() or pasta.parent.name in CACHE_SEM_PODA:
            continue
        arquivos = sorted(p for p in pasta.iterdir() if p.suffix == storage.EXT)
        for p in arquivos[:-manter_dias] if manter_dias > 0 else []:
            p.unlink(missing_ok=True)
