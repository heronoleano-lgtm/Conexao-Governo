"""Outras transferências federais custodiadas em bancos oficiais.

  FUNDEB e transferências constitucionais (FPM, royalties...) — API do Tesouro Transparente, por município e mês.
  Saúde (Fundo Nacional de Saúde)  — consulta pública do FNS: fundos de saúde, contas por bloco com BANCO,
                                       pagamentos e saldo mensal da conta.
  Educação (FNDE) e Assistência social (FNAS) — arquivo mensal "Transferências" do Portal da Transparência
                                       (valores por município e programa; o banco da conta não é publicado).
O que não está nas fontes abertas fica dito na tela: banco da conta do FUNDEB, do FNDE e do FNAS.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from . import storage
from .http import Cliente
from .normaliza import sem_acento

log = logging.getLogger(__name__)

TESOURO = "https://apiapex.tesouro.gov.br/aria/v1/transferencias_constitucionais/custom"
FNS = "https://consultafns.saude.gov.br/recursos/consulta-detalhada"
PORTAL = "https://portaldatransparencia.gov.br/download-de-dados/transferencias"
UFS = "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()


def _grava(df: pd.DataFrame, bruto: Path, nome: str, dia: date) -> int:
    storage.gravar(df, bruto / "outras" / nome / dia.isoformat())
    return len(df)


# ------------------------------------------------------------------ Tesouro: FUNDEB e constitucionais
def tesouro(cli: Cliente, anos: list[int], codigos: list[int], tamanho: int = 1000) -> pd.DataFrame:
    est = cli.json(f"{TESOURO}/estados").get("registros", [])
    linhas = []
    for e in est:
        for ano in anos:
            pagina = 1
            while True:
                j = cli.json(f"{TESOURO}/por_estado_municipio", {
                    "p_ano": ano, "p_estado": e["codigo"], "p_transferencia": ":".join(map(str, codigos)),
                    "p_mes": ":".join(str(m) for m in range(1, 13)), "pageSize": tamanho, "page": pagina})
                reg = j.get("registros", [])
                linhas += reg
                if len(reg) < tamanho:
                    break
                pagina += 1
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df.columns = [c.lower() for c in df.columns]
    return df.rename(columns={"co_ibge": "cod_ibge"})


# ------------------------------------------------------------------ FNS: saúde, com banco e saldo
def _paginas(cli: Cliente, recurso: str, params: dict, tamanho: int = 500) -> list[dict]:
    out, pagina = [], 1
    while True:
        j = cli.json(f"{FNS}/{recurso}", {**params, "count": tamanho, "page": pagina})
        r = j.get("resultado", {}) or {}
        dados = r.get("dados", []) or []
        out += dados
        total = r.get("total") or 0
        if not dados or len(out) >= total or len(dados) < tamanho:
            return out
        pagina += 1


def fns(cli: Cliente, ano: int, conexoes: int = 6, com_saldo: bool = True, pausa: float = 0.05,
        ufs: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Fundos de saúde públicos (municipais e estaduais): contas por bloco, pagamentos do ano e último saldo."""
    ents = []
    for uf in ufs or UFS:
        ents += [e for e in _paginas(cli, "entidades", {"ano": ano, "estado": uf}, 5000)
                 if e.get("esferaAdministrativa") in ("MUNICIPAL", "ESTADUAL")]
    entidades = pd.DataFrame(ents)
    log.info("FNS %s: %d fundos públicos", ano, len(entidades))

    def por_entidade(e):
        p = {"ano": ano, "estado": e["uf"], "municipio": e.get("codigoMunicipioIBGE") or "", "cpfCnpjUg": e["cpfCnpj"]}
        try:
            contas = _paginas(cli, "detalhe-conta", p, 200)
            pags = _paginas(cli, "detalhe-pagamento", p, 500)
        except Exception as ex:  # um fundo com erro não derruba a coleta
            log.warning("FNS %s: %s", e.get("cpfCnpj"), ex)
            return [], []
        time.sleep(pausa)
        for c in contas:
            c["cpfCnpj"] = e["cpfCnpj"]
        for g in pags:
            g["cpfCnpj"] = e["cpfCnpj"]
        return contas, pags

    contas, pagamentos = [], []
    with ThreadPoolExecutor(max_workers=conexoes) as ex:
        for c, g in ex.map(por_entidade, ents):
            contas += c
            pagamentos += g
    ct = pd.json_normalize(contas) if contas else pd.DataFrame()
    pg = pd.json_normalize(pagamentos) if pagamentos else pd.DataFrame()
    if not ct.empty:
        ct = ct[ct["contaCorrente"].fillna("").astype(str).str.strip() != ""]
        ct = ct.drop_duplicates(["cpfCnpj", "codigoBanco", "codigoAgencia", "contaCorrente", "codigoBloco"])
    saldos = pd.DataFrame()
    if com_saldo and not ct.empty:
        unicas = ct.drop_duplicates(["codigoBanco", "codigoAgencia", "contaCorrente"])[
            ["codigoBanco", "codigoAgencia", "contaCorrente"]].to_dict("records")

        def saldo(c):
            try:
                j = cli.json(f"{FNS}/ultimo-saldo", {"banco": c["codigoBanco"], "agencia": c["codigoAgencia"],
                                                      "conta": c["contaCorrente"]})
                d = ((j.get("resultado") or {}).get("dados") or [{}])[0]
                return {**c, "saldo": d.get("valorTotal"), "data_saldo": d.get("dataSaldoFormatada")}
            except Exception:
                return {**c, "saldo": None, "data_saldo": None}
        with ThreadPoolExecutor(max_workers=conexoes) as ex:
            saldos = pd.DataFrame(list(ex.map(saldo, unicas)))
    return {"fns_entidades": entidades, "fns_contas": ct, "fns_pagamentos": pg, "fns_saldos": saldos}


# ------------------------------------------------------------------ Portal da Transparência: Educação e Assistência
# Colunas do arquivo "Recursos Transferidos" segundo o dicionário oficial do Portal da Transparência
# (portaldatransparencia.gov.br/dicionario-de-dados/recursos-transferidos). Não existe "órgão superior":
# a área vem da FUNÇÃO orçamentária.
AREAS_PORTAL = {"Educação": "educacao", "Assistência social": "assistencia social"}
COLS_PORTAL = {"ano / mes": "ano_mes", "tipo transferencia": "tipo_transferencia", "tipo favorecido": "tipo_favorecido",
               "uf": "uf", "codigo municipio siafi": "codigo_siafi", "nome municipio": "municipio",
               "nome orgao": "orgao", "nome funcao": "funcao", "nome programa": "programa", "nome acao": "acao",
               "linguagem cidada": "linguagem_cidada", "codigo favorecido": "doc_favorecido",
               "nome favorecido": "favorecido", "valor transferido": "valor"}
# fora do escopo: pagamento direto a pessoas (Bolsa Família, Pé-de-Meia...) e a complementação da União ao FUNDEB,
# que já vem do Tesouro (contaria duas vezes)
EXCLUIR_ACAO = r"fundeb|complementacao da uniao ao fundo de manutencao"


def _norm(c) -> str:
    return " ".join(sem_acento(str(c)).lower().replace("\ufeff", "").split())


def _col(df: pd.DataFrame, *partes: str) -> str | None:
    for c in df.columns:
        n = _norm(c)
        if all(p in n for p in partes):
            return c
    return None


def ler_portal(f) -> pd.DataFrame:
    """Lê o CSV do Portal (latin-1, ';') e devolve só Educação e Assistência social repassadas a entes e entidades,
    agregado por favorecido e ação."""
    df = pd.read_csv(f, sep=";", encoding="latin-1", dtype=str, low_memory=False)
    df = df.rename(columns={c: COLS_PORTAL[_norm(c)] for c in df.columns if _norm(c) in COLS_PORTAL})
    falta = {"funcao", "valor"} - set(df.columns)
    if falta:
        raise ValueError(f"Arquivo do Portal sem as colunas {sorted(falta)}; colunas recebidas: {list(df.columns)[:12]}")
    fun = df["funcao"].fillna("").map(_norm)
    area = pd.Series(None, index=df.index, dtype="object")
    for nome_area, alvo in AREAS_PORTAL.items():
        area[fun == alvo] = nome_area
    m = area.notna()
    if "tipo_transferencia" in df:
        m &= ~df["tipo_transferencia"].fillna("").map(_norm).str.contains("direta ao cidadao")
    if "tipo_favorecido" in df:
        m &= ~df["tipo_favorecido"].fillna("").map(_norm).str.contains("pessoa fisica")
    if "acao" in df:
        m &= ~df["acao"].fillna("").map(_norm).str.contains(EXCLUIR_ACAO, regex=True)
    df = df[m].assign(area=area[m])
    if df.empty:
        return pd.DataFrame(columns=["area", "orgao", "programa", "acao", "uf", "municipio", "codigo_siafi",
                                     "favorecido", "doc_favorecido", "valor"])
    df["valor"] = pd.to_numeric(df["valor"].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                                errors="coerce").fillna(0.0)
    cols = [c for c in ("area", "orgao", "programa", "acao", "uf", "municipio", "codigo_siafi", "favorecido",
                        "doc_favorecido") if c in df.columns]
    return df[cols + ["valor"]].fillna({c: "" for c in cols}).groupby(cols, as_index=False)["valor"].sum()


def portal_mes(cli: Cliente, anomes: str) -> pd.DataFrame:
    """Baixa o arquivo do mês (zip) e aplica ler_portal."""
    r = cli.get(f"{PORTAL}/{anomes}", stream=True)
    buf = io.BytesIO()
    for pedaco in r.iter_content(1 << 20):
        buf.write(pedaco)
    with zipfile.ZipFile(buf) as z:
        nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome) as f:
            out = ler_portal(f)
    log.info("Portal %s: %d linhas de Educação/Assistência (%s)", anomes, len(out),
             brl_txt(out["valor"].sum()) if not out.empty else "R$ 0")
    return out.assign(anomes=anomes)


def brl_txt(v: float) -> str:
    return f"R$ {v / 1e6:,.1f} mi".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ orquestração
def _ultima(estado: Path, nome: str) -> str | None:
    arq = estado / f"outras_{nome}.txt"
    return arq.read_text().strip() if arq.exists() else None


def _marca(estado: Path, nome: str, dia: date) -> None:
    (estado / f"outras_{nome}.txt").write_text(dia.isoformat())


def carregar(cfg_o: dict, user_agent: str, bruto: Path, estado: Path, dia: date, sessao=None) -> dict:
    """Roda cada fonte na sua periodicidade (config outras_fontes) e grava no bruto/outras."""
    man = {"modulo": "outras", "cargas": []}
    cli = Cliente("https://apiapex.tesouro.gov.br", user_agent, cfg_o.get("timeout_seg", 120), cfg_o.get("tentativas", 5),
                  sessao=sessao)
    anos = [dia.year - i for i in range(int(cfg_o.get("anos", 2)))]

    def vencida(nome, dias):
        u = _ultima(estado, nome)
        return u is None or (dia - date.fromisoformat(u)).days >= dias

    def item(nome, func):
        t0 = time.time()
        try:
            n = func()
            man["cargas"].append({"endpoint": nome, "carregado": n, "ok": True, "segundos": round(time.time() - t0)})
            _marca(estado, nome, dia)
        except Exception as e:
            log.exception("Falha em %s", nome)
            man["cargas"].append({"endpoint": nome, "erro": str(e)[:300], "ok": False})

    t = cfg_o.get("tesouro", {})
    if t.get("ativo", True) and vencida("tesouro_transferencias", t.get("a_cada_dias", 1)):
        item("tesouro_transferencias", lambda: _grava(tesouro(cli, anos, t.get("codigos", [10, 14, 3, 7, 12])),
                                                     bruto, "tesouro_transferencias", dia))
    f = cfg_o.get("fns", {})
    if f.get("ativo", True) and vencida("fns", f.get("a_cada_dias", 7)):
        def _fns():
            n = 0
            partes: dict[str, list] = {}
            for ano in anos[: int(f.get("anos", 1))]:
                for k, v in fns(cli, ano, f.get("conexoes", 6), f.get("saldo", True)).items():
                    partes.setdefault(k, []).append(v.assign(ano_consulta=ano))
            for k, v in partes.items():
                n += _grava(pd.concat(v, ignore_index=True), bruto, k, dia)
            return n
        item("fns", _fns)
    p = cfg_o.get("portal", {})
    if p.get("ativo", True) and vencida("portal_v2", p.get("a_cada_dias", 7)):   # v2: leitura pelo dicionário oficial
        def _portal():
            pasta = bruto / "outras" / "_portal_meses"
            pasta.mkdir(parents=True, exist_ok=True)
            meses = pd.period_range(end=pd.Period(dia, "M") - 1, periods=int(p.get("meses", 13)), freq="M")
            for m in meses:
                am = m.strftime("%Y%m")
                arq = pasta / am
                if storage.existe(arq) and am < (pd.Period(dia, "M") - 2).strftime("%Y%m") \
                        and not storage.ler(arq).empty and "area" in storage.ler(arq).columns:
                    continue    # meses fechados não mudam: baixa uma vez (os 2 últimos são renovados); vazio = baixar de novo
                try:
                    storage.gravar(portal_mes(cli, am), arq)
                except Exception as e:
                    log.warning("Portal %s indisponível: %s", am, e)
            todos = [storage.ler(x.with_suffix("")) for x in sorted(pasta.glob(f"*{storage.EXT}"))]
            return _grava(pd.concat(todos, ignore_index=True) if todos else pd.DataFrame(), bruto,
                          "portal_educacao_assistencia", dia)
        item("portal_educacao_assistencia", _portal)
        if man["cargas"] and man["cargas"][-1].get("ok"):
            _marca(estado, "portal_v2", dia)
    return man
