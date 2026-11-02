"""Ingestão dos CSVs de Discricionárias e Legais (repositório público em Azure Blob).

A listagem XML traz ETag de cada arquivo: só baixamos o que mudou desde a última carga.
"""
from __future__ import annotations

import io
import json
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from . import storage
from .http import Cliente

log = logging.getLogger(__name__)


def listar(cli: Cliente, caminho_listagem: str) -> pd.DataFrame:
    r = cli.get(caminho_listagem)
    raiz = ET.fromstring(r.content)
    linhas = []
    for b in raiz.iter("Blob"):
        props = b.find("Properties")
        linhas.append({
            "nome": b.findtext("Name"),
            "url": b.findtext("Url"),
            "etag": props.findtext("Etag") if props is not None else None,
            "tamanho": int(props.findtext("Content-Length") or 0) if props is not None else 0,
            "modificado": props.findtext("Last-Modified") if props is not None else None,
        })
    return pd.DataFrame(linhas)


def ler_csv_zip(origem, colunas: list[str] | None = None, bloco: int = 200_000) -> pd.DataFrame:
    """Lê o CSV de dentro do zip em blocos (arquivos de centenas de MB cabem em PC comum)."""
    if isinstance(origem, (bytes, bytearray)):
        origem = io.BytesIO(origem)
    with zipfile.ZipFile(origem) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome) as f:
            amostra = f.read(1 << 20)
        corte = amostra.rfind(b"\n")
        try:
            amostra[:corte if corte > 0 else len(amostra)].decode("utf-8")
            enc = "utf-8-sig"
        except UnicodeDecodeError:
            enc = "latin-1"
        with z.open(nome) as f:
            texto = io.TextIOWrapper(f, encoding=enc, errors="replace", newline="")
            df, stats = ler_linhas(texto, colunas)
    df.attrs["linhas_reparadas"] = stats["reparadas"]
    df.attrs["linhas_descartadas"] = stats["descartadas"]
    if stats["reparadas"] or stats["descartadas"]:
        log.info("%s: %d linhas reparadas, %d descartadas", nome, stats["reparadas"], stats["descartadas"])
    return df


BANCO_RE = None


def _limpa(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def _reparar_proposta(campos: list[str], cab: list[str]) -> list[str] | None:
    """O CSV de propostas não usa aspas, e endereço/bairro/objeto às vezes contêm ';'.
    Âncoras: os campos até CEP_PROPONENTE e os 9 últimos são confiáveis; o banco é achado pelo nome."""
    import re
    global BANCO_RE
    BANCO_RE = BANCO_RE or re.compile(r"^(CAIXA ECON|BANCO |BCO )", re.I)
    n = len(cab)
    try:
        i_cep, i_end, i_banco, i_obj = (cab.index(c) for c in
                                        ("cep_proponente", "endereco_proponente", "nm_banco", "objeto_proposta"))
    except ValueError:
        return None
    cauda = n - i_obj - 1
    inicio, fim = campos[:i_end], campos[len(campos) - cauda:]
    meio = campos[i_end:len(campos) - cauda]
    pos = next((k for k, v in enumerate(meio) if BANCO_RE.match(v.strip())), None)
    entre = i_obj - i_banco - 1          # campos entre o banco e o objeto
    if pos is None or pos < 2 or pos + entre >= len(meio):
        return None
    endereco = ";".join(meio[:pos - 1])
    bairro = meio[pos - 1]
    depois = meio[pos:pos + 1 + entre]
    objeto = ";".join(meio[pos + 1 + entre:])
    fixo = inicio + [endereco, bairro] + depois + [objeto] + fim
    return fixo if len(fixo) == n else None


REPARADORES = {"nm_banco": _reparar_proposta}


def ler_linhas(texto, colunas: list[str] | None) -> tuple[pd.DataFrame, dict]:
    """Leitor tolerante para CSV ';' sem aspas: repara linhas com ';' dentro de campos de texto e
    junta registros quebrados em duas linhas. Guarda só as colunas pedidas (pouca memória)."""
    stats = {"reparadas": 0, "descartadas": 0}
    cab = [_limpa(c).lower() for c in texto.readline().rstrip("\r\n").split(";")]
    n = len(cab)
    alvo = [c.lower() for c in colunas] if colunas else cab
    idx = [(c, cab.index(c)) for c in alvo if c in cab]
    reparador = next((f for chave, f in REPARADORES.items() if chave in cab and "objeto_proposta" in cab), None)
    dados = {c: [] for c, _ in idx}
    pendente, juncoes = None, 0
    for linha in texto:
        linha = linha.rstrip("\r\n")
        if pendente is not None:
            linha, pendente = pendente + " " + linha, None
        if not linha:
            continue
        campos = linha.split(";")
        if len(campos) < n:
            juncoes += 1
            if juncoes > 5:               # não é quebra de linha: descarta e segue
                stats["descartadas"] += 1
                juncoes = 0
                continue
            pendente = linha              # registro continua na próxima linha
            continue
        juncoes = 0
        if len(campos) > n:
            fixo = reparador(campos, cab) if reparador else None
            if fixo is None:
                stats["descartadas"] += 1
                continue
            campos = fixo
            stats["reparadas"] += 1
        for c, i in idx:
            dados[c].append(_limpa(campos[i]) or None)
    if pendente:
        stats["descartadas"] += 1
    return pd.DataFrame(dados, dtype="object"), stats


def carregar(cli: Cliente, cfg_csv: dict, pasta_bruto: Path, pasta_estado: Path, dia: date) -> dict:
    manifesto = {"modulo": "discricionarias_csv", "dia": dia.isoformat(), "cargas": []}
    arq_estado = pasta_estado / "etags_csv.json"
    etags = json.loads(arq_estado.read_text("utf-8")) if arq_estado.exists() else {}
    try:
        lista = listar(cli, cfg_csv["listagem"])
    except Exception as e:
        log.exception("Falha ao listar CSVs")
        manifesto["erro"] = str(e)[:500]
        return manifesto

    for nome in cfg_csv.get("arquivos", []):
        arquivo = f"{nome}.zip"
        linha = lista[lista["nome"] == arquivo]
        item = {"arquivo": arquivo, "baixado": False, "linhas": None, "erro": None, "ok": True}
        if linha.empty:
            item.update(erro="arquivo não está na listagem", ok=False)
            manifesto["cargas"].append(item)
            continue
        etag = linha.iloc[0]["etag"]
        destino = pasta_bruto / "discricionarias_csv" / nome / dia.isoformat()
        if etags.get(arquivo) == etag and any((pasta_bruto / "discricionarias_csv" / nome).glob(f"*{storage.EXT}")):
            item["motivo"] = "sem mudança (ETag igual)"
            manifesto["cargas"].append(item)
            continue
        try:
            tmp = pasta_estado / f"_{arquivo}.parcial"
            r = cli.get(cfg_csv["download"] + arquivo, stream=True)
            with open(tmp, "wb") as out:
                for pedaco in r.iter_content(1 << 20):
                    out.write(pedaco)
            df = ler_csv_zip(tmp, (cfg_csv.get("colunas") or {}).get(nome))
            # guarda o arquivo original completo (todas as colunas) da última versão: a foto completa o copia
            originais = pasta_bruto / "_originais_csv"
            originais.mkdir(parents=True, exist_ok=True)
            tmp.replace(originais / arquivo)
            storage.gravar(df, destino)
            etags[arquivo] = etag
            item.update(baixado=True, linhas=len(df), tamanho=int(linha.iloc[0]["tamanho"]))
            log.info("CSV %s: %d linhas", arquivo, len(df))
        except Exception as e:
            log.exception("Falha no CSV %s", arquivo)
            item.update(erro=str(e)[:500], ok=False)
        manifesto["cargas"].append(item)

    arq_estado.write_text(json.dumps(etags, indent=1), "utf-8")
    return manifesto
