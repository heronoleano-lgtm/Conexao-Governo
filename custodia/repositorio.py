"""Repositório de dados do painel: o que fica guardado entre as cargas e como consultar o passado.

Desenho (sem foto completa diária, que ocuparia ~100 GB/ano):
  1. bruto/            carga do dia por endpoint, mantida por N dias (config dados.manter_bruto_dias);
  2. historico/        tabelas-chave em SCD2 (uma versão nova só quando o registro muda) — reconstrói qualquer dia;
  3. historico/serie_ente/AAAA-MM   saldo, valor e crédito a receber por ente × modalidade × banco, um ponto por dia
                       — base das variações do dia, da semana, do mês e do ano;
  4. repositorio/registro_cargas    o que cada carga trouxe (linhas, tempo, erros), para auditoria;
  5. repositorio/catalogo.json      inventário de tudo o que existe, com período coberto e tamanho;
  6. repositorio/fotos/AAAA-MM-DD   foto completa do bruto, só quando pedida (--foto) ou se ativada no config.
Novas perguntas de negócio entram como: endpoint/arquivo novo no config.yaml (bruto) → histórico se precisar
de passado → motor → mart → tela, e ficam registradas em config/perguntas.yaml e config/regras.yaml.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import storage

log = logging.getLogger(__name__)

CHAVE_SERIE = ["modulo", "cnpj_ente", "uf", "grupo_banco"]
REFERENCIAS = {"dia": 1, "semana": 7, "mes": 30, "ano": 365}


# ------------------------------------------------------------------ série diária por ente
def linhas_do_dia(instr: pd.DataFrame, contas: pd.DataFrame, pipe: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ente × modalidade × banco com saldo, valor dos instrumentos e crédito a receber."""
    partes = []
    if not contas.empty:
        partes.append(contas.groupby(CHAVE_SERIE, dropna=False, as_index=False)["saldo"].sum())
    if not instr.empty:
        partes.append(instr.groupby(CHAVE_SERIE, dropna=False, as_index=False)["valor"].sum())
    if not pipe.empty:
        p = pipe.assign(modulo=pipe.get("modulo", "Especiais"))
        partes.append(p.groupby(CHAVE_SERIE, dropna=False, as_index=False)["a_creditar"].sum())
    if not partes:
        return pd.DataFrame(columns=CHAVE_SERIE + ["saldo", "valor", "a_creditar"])
    out = partes[0]
    for p in partes[1:]:
        out = out.merge(p, on=CHAVE_SERIE, how="outer")
    for c in ("saldo", "valor", "a_creditar"):
        out[c] = out[c].fillna(0.0) if c in out else 0.0
    out = out[(out["saldo"] != 0) | (out["a_creditar"] != 0) | (out["valor"] != 0)]
    return out[CHAVE_SERIE + ["saldo", "valor", "a_creditar"]]


def gravar_serie_ente(pasta: Path, linhas: pd.DataFrame, dia: date) -> None:
    """Acrescenta o dia no arquivo do mês (rodar de novo no mesmo dia substitui)."""
    arq = pasta / dia.strftime("%Y-%m")
    hist = storage.ler(arq)
    if not hist.empty:
        hist = hist[hist["dia"] != dia.isoformat()]
    storage.gravar(pd.concat([hist, linhas.assign(dia=dia.isoformat())], ignore_index=True), arq)


def ler_serie_ente(pasta: Path, desde: date | None = None) -> pd.DataFrame:
    if not pasta.exists():
        return pd.DataFrame(columns=CHAVE_SERIE + ["saldo", "valor", "a_creditar", "dia"])
    arqs = sorted(p for p in pasta.iterdir() if p.suffix == storage.EXT)
    if desde:
        arqs = [p for p in arqs if p.stem >= desde.strftime("%Y-%m")]
    if not arqs:
        return pd.DataFrame(columns=CHAVE_SERIE + ["saldo", "valor", "a_creditar", "dia"])
    return pd.concat([storage.ler(p.with_suffix("")) for p in arqs], ignore_index=True)


def _dia_ref(dias: list[str], hoje: str, deslocamento: int) -> str | None:
    """Último dia com dado até (hoje - deslocamento). Para o 'dia', o último anterior a hoje."""
    limite = (date.fromisoformat(hoje) - timedelta(days=deslocamento)).isoformat()
    candidatos = [d for d in dias if d <= limite and d < hoje]
    return max(candidatos) if candidatos else None


def variacoes(serie: pd.DataFrame, por: list[str], dia: date | None = None) -> pd.DataFrame:
    """Saldo de hoje e variação contra o dia anterior, 7, 30 e 365 dias atrás (o ponto mais próximo disponível)."""
    if serie.empty:
        return pd.DataFrame(columns=por + ["saldo"])
    dias = sorted(serie["dia"].unique())
    hoje = dia.isoformat() if dia else dias[-1]
    if hoje not in dias:
        hoje = dias[-1]
    base = serie[serie["dia"] == hoje].groupby(por, dropna=False)["saldo"].sum().rename("saldo")
    out = base.to_frame()
    for nome, desl in REFERENCIAS.items():
        ref = _dia_ref(dias, hoje, desl)
        col = f"saldo_{nome}_anterior"
        if ref is None:
            out[col] = float("nan")
        else:
            out[col] = serie[serie["dia"] == ref].groupby(por, dropna=False)["saldo"].sum().reindex(out.index)
            # quem não existia no dia de referência tinha saldo zero
            out[col] = out[col].fillna(0.0)
        out[f"var_{nome}"] = out["saldo"] - out[col]
        out[f"var_{nome}_pct"] = out[f"var_{nome}"] / out[col].where(out[col] > 0)
        out[f"ref_{nome}"] = ref
    return out.reset_index()


def evolucao(serie: pd.DataFrame, por: list[str], frequencia: str = "D") -> pd.DataFrame:
    """Saldo ao longo do tempo (D = diário, W = semanal, M = mensal: último ponto de cada período)."""
    if serie.empty:
        return pd.DataFrame(columns=["dia"] + por + ["saldo"])
    s = serie.groupby(["dia"] + por, dropna=False, as_index=False)["saldo"].sum()
    if frequencia == "D":
        return s
    s["_p"] = pd.to_datetime(s["dia"]).dt.to_period(frequencia).astype(str)
    ult = s.groupby("_p")["dia"].transform("max")
    return s[s["dia"] == ult].drop(columns="_p")


# ------------------------------------------------------------------ reconstrução do passado (SCD2)
def como_era(arquivo_hist: Path, dia: date) -> pd.DataFrame:
    """Estado de uma tabela histórica num dia passado."""
    h = storage.ler(arquivo_hist)
    if h.empty:
        return h
    d = dia.isoformat()
    vale = (h["valido_de"] <= d) & (h["valido_ate"].isna() | (h["valido_ate"] > d))
    return h[vale].drop(columns=[c for c in ("_hash", "valido_de", "valido_ate") if c in h])


# ------------------------------------------------------------------ registro e catálogo
def registrar_cargas(pasta_repo: Path, manifestos: list[dict], dia: date) -> pd.DataFrame:
    linhas = []
    for m in manifestos or []:
        for c in m.get("cargas", []):
            linhas.append({"dia": dia.isoformat(), "modulo": m.get("modulo"),
                           "tabela_origem": c.get("endpoint") or c.get("arquivo"),
                           "linhas": c.get("carregado", c.get("linhas")), "esperado": c.get("esperado"),
                           "ok": bool(c.get("ok", not c.get("erro"))), "segundos": c.get("segundos"),
                           "erro": (c.get("erro") or "")[:300]})
    arq = pasta_repo / "registro_cargas"
    reg = storage.ler(arq)
    if not reg.empty:
        reg = reg[reg["dia"] != dia.isoformat()]
    reg = pd.concat([reg, pd.DataFrame(linhas)], ignore_index=True)
    storage.gravar(reg, arq)
    return reg


def _tam_mb(p: Path) -> float:
    if p.is_file():
        return p.stat().st_size / 1e6
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def catalogo(dados: Path, marts_publicados: dict[str, pd.DataFrame]) -> pd.DataFrame:
    linhas = []
    bruto = dados / "bruto"
    for pasta in sorted(bruto.glob("*/*")):
        if not pasta.is_dir():
            continue
        dias = sorted(p.stem for p in pasta.iterdir() if p.suffix == storage.EXT)
        if dias:
            linhas.append({"camada": "Bruto (carga do dia)", "tabela": f"{pasta.parent.name}/{pasta.name}",
                           "primeira_carga": dias[0], "ultima_carga": dias[-1], "cargas": len(dias),
                           "tamanho_mb": round(_tam_mb(pasta), 1)})
    hist = dados / "historico"
    for p in sorted(hist.glob(f"*{storage.EXT}")):
        df = storage.ler(p.with_suffix(""))
        prim = df["valido_de"].min() if "valido_de" in df else (df["dia"].min() if "dia" in df else None)
        ult = df["valido_de"].max() if "valido_de" in df else (df["dia"].max() if "dia" in df else None)
        linhas.append({"camada": "Histórico (só mudanças)", "tabela": p.stem, "primeira_carga": prim,
                       "ultima_carga": ult, "registros": len(df), "tamanho_mb": round(_tam_mb(p), 1)})
    se = hist / "serie_ente"
    if se.exists():
        s = ler_serie_ente(se)
        linhas.append({"camada": "Histórico (só mudanças)", "tabela": "serie_ente (saldo diário por ente)",
                       "primeira_carga": s["dia"].min() if not s.empty else None,
                       "ultima_carga": s["dia"].max() if not s.empty else None,
                       "cargas": s["dia"].nunique() if not s.empty else 0, "registros": len(s),
                       "tamanho_mb": round(_tam_mb(se), 1)})
    for nome, df in sorted(marts_publicados.items()):
        if isinstance(df, pd.DataFrame):
            linhas.append({"camada": "Painel (tabelas publicadas)", "tabela": nome, "registros": len(df),
                           "colunas": len(df.columns)})
    fotos = dados / "repositorio" / "fotos"
    if fotos.exists():
        for f in sorted(p for p in fotos.iterdir() if p.is_dir()):
            linhas.append({"camada": "Foto completa", "tabela": f.name, "primeira_carga": f.name,
                           "ultima_carga": f.name, "tamanho_mb": round(_tam_mb(f), 1)})
    cat = pd.DataFrame(linhas)
    (dados / "repositorio").mkdir(parents=True, exist_ok=True)
    (dados / "repositorio" / "catalogo.json").write_text(
        cat.to_json(orient="records", force_ascii=False, indent=1), "utf-8")
    return cat


def foto_completa(dados: Path, dia: date) -> Path:
    """Foto completa e independente do histórico: a carga bruta mais recente de cada tabela (API, todas as
    colunas) e os arquivos CSV originais (zip, todas as colunas). Não é apagada pela limpeza do bruto."""
    destino = dados / "repositorio" / "fotos" / dia.isoformat()
    for pasta in (dados / "bruto").glob("*/*"):
        if not pasta.is_dir() or pasta.name.startswith("_"):
            continue
        arqs = sorted(p for p in pasta.iterdir() if p.suffix == storage.EXT)
        if arqs:
            alvo = destino / pasta.parent.name / f"{pasta.name}{storage.EXT}"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arqs[-1], alvo)
    originais = dados / "bruto" / "_originais_csv"
    if originais.exists():
        for z in originais.glob("*.zip"):
            alvo = destino / "csv_originais" / z.name
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(z, alvo)
    log.info("Foto completa gravada em %s", destino)
    return destino


def deve_fotografar(cfg_repo: dict, dia: date, pedido: bool, dados: Path | None = None) -> bool:
    """Mensal por padrão: na primeira carga de cada mês (ou se ainda não houver foto do mês)."""
    if pedido:
        return True
    modo = (cfg_repo or {}).get("foto_completa", "mensal")
    if modo == "diaria":
        return True
    if modo != "mensal":
        return False
    fotos = (dados / "repositorio" / "fotos") if dados else None
    if fotos is None or not fotos.exists():
        return True
    return not any(p.name.startswith(dia.strftime("%Y-%m")) for p in fotos.iterdir() if p.is_dir())


def reconstruir(dados: Path, dia: date, destino: Path | None = None) -> Path:
    """Grava em repositorio/reconstrucao/AAAA-MM-DD todas as tabelas como estavam no dia (a partir do histórico)."""
    from . import historico
    destino = destino or dados / "repositorio" / "reconstrucao" / dia.isoformat()
    destino.mkdir(parents=True, exist_ok=True)
    arqs = sorted((dados / "historico").glob(f"*{storage.EXT}"))
    ativos = {}
    for arq in arqs:      # para cada tabela, o arquivo que cobre o dia: arquivados (__ate_D) valem antes de D
        nome = arq.stem
        if historico.ARQUIVO_ATE in nome:
            base, ate = nome.split(historico.ARQUIVO_ATE, 1)
            ate = ate.split("_")[0]
            if dia.isoformat() < ate and (base not in ativos or ativos[base][0] > ate):
                ativos[base] = (ate, arq)
        else:
            ativos.setdefault(nome, ("9999", arq))
    for nome, (_, arq) in sorted(ativos.items()):
        h = storage.ler(arq.with_suffix(""))
        if "valido_de" not in h:
            continue
        r = historico.como_era(h, dia)
        if historico.REPETICOES in r:
            r = r.loc[r.index.repeat(r[historico.REPETICOES].astype(int))]
        r = r.drop(columns=[c for c in ("_hash", "valido_de", "valido_ate", historico.REPETICOES,
                                        historico.CHAVE_LINHA) if c in r])
        storage.gravar(r.reset_index(drop=True), destino / nome)
    log.info("Tabelas de %s reconstruídas em %s", dia, destino)
    return destino


if __name__ == "__main__":  # python -m custodia.repositorio AAAA-MM-DD
    import sys
    from . import config
    cam = config.caminhos(config.carregar())
    alvo = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(reconstruir(cam.dados, alvo))


def resumo_json(cat: pd.DataFrame) -> str:
    return json.dumps({"tabelas": len(cat), "tamanho_mb": float(cat.get("tamanho_mb", pd.Series(dtype=float)).sum())})
