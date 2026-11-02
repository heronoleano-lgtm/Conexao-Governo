"""Cliente HTTP com novas tentativas e espera progressiva."""
from __future__ import annotations

import logging
import random
import time

import requests

log = logging.getLogger(__name__)

REPETIR_STATUS = {429, 500, 502, 503, 504, 520, 522, 524}


class ErroAPI(RuntimeError):
    pass


class Cliente:
    def __init__(self, base_url: str, user_agent: str, timeout: float = 90, tentativas: int = 5,
                 sessao: requests.Session | None = None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.tentativas = tentativas
        self.sessao = sessao or requests.Session()
        self.sessao.headers.update({"User-Agent": user_agent, "Accept": "application/json"})

    def url(self, caminho: str) -> str:
        if caminho.startswith("http"):
            return caminho
        return f"{self.base}/{caminho.lstrip('/')}"

    def get(self, caminho: str, params: dict | None = None, stream: bool = False) -> requests.Response:
        ultimo = None
        for t in range(1, self.tentativas + 1):
            try:
                r = self.sessao.get(self.url(caminho), params=params, timeout=self.timeout, stream=stream)
                if r.status_code in REPETIR_STATUS:
                    ultimo = f"HTTP {r.status_code}"
                    espera = float(r.headers.get("Retry-After", 0)) or min(60, 2 ** t) + random.random()
                    log.warning("%s em %s (tentativa %d); aguardando %.0fs", ultimo, caminho, t, espera)
                    time.sleep(espera)
                    continue
                if r.status_code >= 400:
                    raise ErroAPI(f"HTTP {r.status_code} em {caminho}: {r.text[:300]}")
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                ultimo = repr(e)
                espera = min(60, 2 ** t) + random.random()
                log.warning("Falha de conexão em %s (tentativa %d): %s", caminho, t, e)
                time.sleep(espera)
        raise ErroAPI(f"Desisti de {caminho} após {self.tentativas} tentativas: {ultimo}")

    def json(self, caminho: str, params: dict | None = None):
        r = self.get(caminho, params)
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            raise ErroAPI(
                f"Resposta não é JSON em {caminho} (content-type={ctype}). "
                "Pode ser bloqueio do Cloudflare; veja o README, seção 'Problemas comuns'.")
        return r.json()
