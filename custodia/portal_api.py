"""API de dados do Portal da Transparência (CGU) — ingestão para o CRM.

Conjuntos usados (todos públicos; nada por CPF):
  recursos     /despesas/recursos-recebidos       tudo o que cada favorecido recebeu da União, por mês
  emendas      /emendas                           emendas de todos os tipos (individual, bancada, comissão...)
  emenda_docs  /emendas/documentos/{codigo}       empenhos, liquidações e pagamentos de cada emenda
  documento    /despesas/documentos/{codigo}      detalhe do pagamento (quem recebeu)
  ceis/cnep/cepim                                 cadastros de sanções (empresas e entidades impedidas)
  presenca     /novo-bolsa-familia-por-municipio  benefício pago pela CAIXA, total por município

Como funciona (para não perder nada e não duplicar nada):
  * cada consulta é uma UNIDADE (conjunto + parâmetros) gravada num arquivo próprio em bruto/portal_api/<conjunto>/;
  * unidades de períodos fechados não são baixadas de novo; as abertas são renovadas na periodicidade do config;
  * cada execução respeita um orçamento de chamadas e de tempo e retoma de onde parou na noite seguinte;
  * o limite da API (400/min das 6h às 24h; 700/min das 0h às 6h) é respeitado com folga;
  * os campos que a API realmente devolveu ficam registrados (estado/portal_api_esquema.json) e a auditoria
    acusa quando falta um campo esperado — nada de "zero silencioso".
A chave (pessoal) fica em config/segredos.yaml (portal_api_chave: ...) ou na variável PORTAL_API_CHAVE.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import storage
from .http import Cliente, ErroAPI

log = logging.getLogger(__name__)
BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
       "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
SANCOES = {"ceis": "/ceis", "cnep": "/cnep", "cepim": "/cepim"}


class ErroChave(RuntimeError):
    """Chave ausente, inválida ou suspensa: para tudo (insistir suspende a chave por horas)."""


class ErroIncompleto(RuntimeError):
    """A unidade passou do teto de páginas: não é gravada (dado cortado não pode parecer completo)."""


TIPOS_FAVORECIDO = ["Administração Pública Municipal", "Administração Pública Estadual ou do Distrito Federal",
                    "Entidades Sem Fins Lucrativos"]


# ------------------------------------------------------------------ chave
def ler_chave(raiz: Path | None = None) -> str | None:
    if os.environ.get("PORTAL_API_CHAVE"):
        return os.environ["PORTAL_API_CHAVE"].strip()
    from . import config
    arq = (raiz or config.RAIZ) / "config" / "segredos.yaml"
    if arq.exists():
        import yaml
        v = (yaml.safe_load(arq.read_text("utf-8")) or {}).get("portal_api_chave")
        return str(v).strip() if v else None
    return None


# ------------------------------------------------------------------ números e campos
_NUM = re.compile(r"[^\d,.\-]")


def num_br(v) -> float:
    """'1.234,56' → 1234.56; '- 26.002,00' → -26002.0; número → número; vazio/ilegível → NaN (nunca 0)."""
    if v is None:
        return math.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return math.nan
    neg = s.startswith("-") or s.startswith("(") or s.replace(" ", "").startswith("R$-")
    s = _NUM.sub("", s).replace("-", "")
    if not s:
        return math.nan
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        x = float(s)
    except ValueError:
        return math.nan
    return -x if neg else x


def achatar(registros) -> pd.DataFrame:
    if not registros:
        return pd.DataFrame()
    if isinstance(registros, dict):
        registros = [registros]
    return pd.json_normalize(registros, sep=".")


def campo(df: pd.DataFrame, *candidatos: str) -> str | None:
    """Primeira coluna que casa com um candidato: nome exato, depois o último trecho (ex.: 'sancionado.codigoFormatado'
    casa com 'codigoFormatado'), sem diferenciar maiúsculas."""
    cols = list(df.columns)
    baixa = {c.lower(): c for c in cols}
    for cand in candidatos:
        if cand.lower() in baixa:
            return baixa[cand.lower()]
    for cand in candidatos:
        alvo = cand.lower().split(".")[-1]
        for c in cols:
            if c.lower().split(".")[-1] == alvo:
                return c
    return None


def doc_limpo(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.replace(r"\D", "", regex=True)


# ------------------------------------------------------------------ cliente com limite
class Limitador:
    """Ritmo global de chamadas, compartilhado entre as conexões paralelas (seguro entre threads)."""

    def __init__(self, dia: int = 350, noite: int = 650, intervalo: float | None = None):
        self.dia, self.noite, self.fixo, self.proximo = dia, noite, intervalo, 0.0
        self._trava = threading.Lock()

    def esperar(self):
        if self.fixo == 0:
            return
        h = datetime.now().hour
        intervalo = self.fixo if self.fixo is not None else 60.0 / (self.noite if h < 6 else self.dia)
        with self._trava:
            agora = time.monotonic()
            vez = max(agora, self.proximo)
            self.proximo = vez + intervalo
        if vez > agora:
            time.sleep(vez - agora)


_TRAVA_CONTADOR = threading.Lock()
CONTADOR = {"chamadas": 0}


class ClientePortal:
    def __init__(self, chave: str, user_agent: str, sessao=None, limitador: Limitador | None = None,
                 timeout: float = 60, tentativas: int = 4):
        self.cli = Cliente(BASE, user_agent, timeout, tentativas, sessao=sessao)
        self.cli.sessao.headers.update({"chave-api-dados": chave})
        self.lim = limitador or Limitador()
        self.chamadas = 0

    def get(self, caminho: str, params: dict | None = None):
        self.lim.esperar()
        with _TRAVA_CONTADOR:
            self.chamadas += 1
            CONTADOR["chamadas"] += 1
        try:
            r = self.cli.get(caminho, params)
        except ErroAPI as e:
            if "HTTP 401" in str(e) or "HTTP 403" in str(e):
                raise ErroChave(f"A API recusou a chave ({str(e)[:120]}). Confira config/segredos.yaml.") from e
            raise
        if not r.content:
            return []
        return r.json()

    def paginas(self, caminho: str, params: dict | None = None, max_paginas: int = 20000) -> list:
        out, p = [], 1
        while True:
            if p > max_paginas:
                raise ErroIncompleto(f"{caminho} {params}: mais de {max_paginas} páginas; unidade não gravada")
            lote = self.get(caminho, {**(params or {}), "pagina": p})
            if isinstance(lote, dict):          # endpoints de registro único
                out.append(lote)
                break
            if not lote:
                break
            out.extend(lote)
            p += 1
        return out


# ------------------------------------------------------------------ unidades (fila com cache)
def _id(conjunto: str, params: dict) -> str:
    return hashlib.sha1(f"{conjunto}|{json.dumps(params, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()[:16]


class Repositorio:
    """Índice e arquivos das unidades de um conjunto: bruto/portal_api/<conjunto>/<id>.<ext> + _indice.json."""

    def __init__(self, bruto: Path, conjunto: str):
        self.pasta = bruto / "portal_api" / conjunto
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arq_indice = self.pasta / "_indice.json"
        self.indice = json.loads(self.arq_indice.read_text("utf-8")) if self.arq_indice.exists() else {}

    def precisa(self, params: dict, fechado: bool, a_cada_dias: int, dia: date) -> bool:
        i = _id(self.conjunto_nome(), params)
        reg = self.indice.get(i)
        if not reg or not reg.get("ok"):
            return True
        if not storage.existe(self.pasta / i):      # índice diz ok mas o arquivo sumiu: baixa de novo
            return True
        if reg.get("fechado") and fechado:
            return False
        return (dia - date.fromisoformat(reg["baixado_em"])).days >= a_cada_dias

    def conjunto_nome(self) -> str:
        return self.pasta.name

    _trava = threading.Lock()

    def gravar(self, params: dict, df: pd.DataFrame, fechado: bool, dia: date, chamadas: int) -> None:
        with Repositorio._trava:
            self._gravar(params, df, fechado, dia, chamadas)

    def _gravar(self, params: dict, df: pd.DataFrame, fechado: bool, dia: date, chamadas: int) -> None:
        i = _id(self.conjunto_nome(), params)
        df = df.astype(object).where(df.notna(), None)
        df = df.assign(**{c: df[c].astype(str) for c in df.columns if df[c].map(lambda v: isinstance(v, (list, dict))).any()})
        storage.gravar(df.assign(_unidade=i), self.pasta / i)
        self.indice[i] = {"params": params, "linhas": int(len(df)), "baixado_em": dia.isoformat(), "fechado": fechado,
                          "ok": True, "chamadas": chamadas}
        self.salvar_indice()

    def falhou(self, params: dict, erro: str, dia: date) -> None:
        with Repositorio._trava:
            self._falhou(params, erro, dia)

    def _falhou(self, params: dict, erro: str, dia: date) -> None:
        i = _id(self.conjunto_nome(), params)
        reg = self.indice.get(i, {})
        if reg.get("ok"):          # já havia versão boa: mantém e só anota o erro
            reg["ultimo_erro"] = erro[:200]
        else:
            reg = {"params": params, "ok": False, "erro": erro[:200], "baixado_em": dia.isoformat()}
        self.indice[i] = reg
        self.salvar_indice()

    def salvar_indice(self) -> None:
        tmp = self.arq_indice.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.indice, ensure_ascii=False, indent=0), "utf-8")
        tmp.replace(self.arq_indice)

    def ler(self) -> pd.DataFrame:
        partes = []
        for i, reg in self.indice.items():
            if reg.get("ok") and storage.existe(self.pasta / i):
                partes.append(storage.ler(self.pasta / i))
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

    def sem_arquivo(self) -> list[str]:
        """Unidades marcadas como baixadas cujo arquivo não existe (dado perdido até a próxima carga)."""
        return [i for i, reg in self.indice.items() if reg.get("ok") and not storage.existe(self.pasta / i)]


def obsoleta(conjunto: str, params: dict) -> bool:
    """Consulta da fila antiga que a fila atual não pede mais (recursos sem tipo de favorecido): não entra nas somas
    nem é baixada de novo; se o arquivo sumir, não é perda."""
    return conjunto == "recursos" and "tipoFavorecido" not in params


def integridade(bruto: Path) -> pd.DataFrame:
    """Por conjunto: unidades no índice, baixadas, com falha e baixadas sem arquivo."""
    base = bruto / "portal_api"
    linhas = []
    if base.exists():
        for p in sorted(x for x in base.iterdir() if x.is_dir()):
            r = Repositorio(bruto, p.name)
            obsoletas = {i for i, v in r.indice.items() if obsoleta(p.name, v.get("params", {}))}
            vivas = {i: v for i, v in r.indice.items() if i not in obsoletas}
            ok = sum(1 for v in vivas.values() if v.get("ok"))
            linhas.append({"conjunto": p.name, "unidades": len(vivas), "baixadas": ok, "com_falha": len(vivas) - ok,
                           "sem_arquivo": len([i for i in r.sem_arquivo() if i not in obsoletas]),
                           "obsoletas": len(obsoletas)})
    return pd.DataFrame(linhas, columns=["conjunto", "unidades", "baixadas", "com_falha", "sem_arquivo", "obsoletas"])


def ler_conjunto(bruto: Path, conjunto: str) -> pd.DataFrame:
    p = bruto / "portal_api" / conjunto
    return Repositorio(bruto, conjunto).ler() if p.exists() else pd.DataFrame()


def indice(bruto: Path, conjunto: str) -> dict:
    a = bruto / "portal_api" / conjunto / "_indice.json"
    return json.loads(a.read_text("utf-8")) if a.exists() else {}


# ------------------------------------------------------------------ plano de unidades
def _meses(dia: date, n: int, atraso: int = 1) -> list[pd.Period]:
    fim = pd.Period(dia, "M") - atraso
    return [fim - k for k in range(n)]


def planejar(cfg: dict, bruto: Path, dia: date, municipios: list[str]) -> list[tuple]:
    """Lista ordenada de (conjunto, caminho, params, fechado, a_cada_dias). Prioridade: sanções e emendas (leves e
    usadas em todo o CRM), presença CAIXA, recursos dos 3 meses mais recentes, documentos das emendas e, por último,
    o histórico de recursos. Recursos vêm por TIPO de favorecido: pessoas físicas (≈ 80% das linhas) e empresas
    privadas não são nem baixadas."""
    plano, recentes, antigos = [], [], []
    s = cfg.get("sancoes", {})
    if s.get("ativo", True):
        for nome, caminho in SANCOES.items():
            plano.append((nome, caminho, {}, False, s.get("a_cada_dias", 7)))
    e = cfg.get("emendas", {})
    if e.get("ativo", True):
        for k in range(int(e.get("anos", 3))):
            ano = dia.year - k
            plano.append(("emendas", "/emendas", {"ano": ano}, k >= 2, e.get("a_cada_dias", 7)))
    p = cfg.get("presenca", {})
    if p.get("ativo", True) and municipios:
        for m in _meses(dia, int(p.get("meses", 1)), int(p.get("atraso_meses", 2))):
            for cod in municipios:
                plano.append(("presenca", "/novo-bolsa-familia-por-municipio",
                              {"mesAno": m.strftime("%Y%m"), "codigoIbge": cod}, True, 3650))
    r = cfg.get("recursos", {})
    if r.get("ativo", True):
        tipos = r.get("tipos_favorecido", TIPOS_FAVORECIDO)
        for k, m in enumerate(_meses(dia, int(r.get("meses", 13)), int(r.get("atraso_meses", 1)))):
            fechado = m < pd.Period(dia, "M") - 3
            for uf in UFS:
                for tipo in tipos:
                    u = ("recursos", "/despesas/recursos-recebidos",
                         {"mesAnoInicio": m.strftime("%m/%Y"), "mesAnoFim": m.strftime("%m/%Y"), "uf": uf,
                          "tipoFavorecido": tipo}, fechado, r.get("a_cada_dias", 7))
                    (recentes if k < 3 else antigos).append(u)
    plano += recentes
    d = cfg.get("documentos_emendas", {})
    if d.get("ativo", True):
        em = ler_conjunto(bruto, "emendas")
        if not em.empty:
            cod, pago = campo(em, "codigoEmenda"), campo(em, "valorPago")
            if cod and pago:
                x = em.assign(_pago=em[pago].map(num_br)).sort_values("_pago", ascending=False)
                x = x[x["_pago"] > 0].drop_duplicates(cod)
                for _, row in x.head(int(d.get("max_emendas", 3000))).iterrows():
                    # o valor pago entra nos parâmetros: se mudar, é outra unidade (a anterior fica no cache)
                    plano.append(("emenda_docs", f"/emendas/documentos/{row[cod]}",
                                  {"codigoEmenda": str(row[cod]), "pago": round(float(row["_pago"]), 2)}, True, 3650))
        docs = ler_conjunto(bruto, "emenda_docs")
        if not docs.empty and d.get("detalhar_pagamentos", True):
            cdoc, fase = campo(docs, "codigoDocumento"), campo(docs, "fase")
            if cdoc:
                x = docs
                if fase:
                    x = x[x[fase].fillna("").astype(str).str.lower().str.contains("pagamento")]
                for c in x[cdoc].dropna().astype(str).unique()[: int(d.get("max_detalhes", 5000))]:
                    plano.append(("documento", f"/despesas/documentos/{c}", {"codigoDocumento": c}, True, 3650))
    plano += antigos
    return plano


def _sem_parametros_de_caminho(conjunto: str, params: dict) -> dict:
    """Parâmetros que só identificam a unidade (código no caminho, valor pago) não vão para a API."""
    if conjunto in ("emenda_docs", "documento"):
        return {}
    return params


# ------------------------------------------------------------------ execução
def carregar(cfg: dict, user_agent: str, bruto: Path, estado: Path, dia: date, sessao=None,
             municipios: list[str] | None = None, raiz: Path | None = None) -> dict:
    man = {"modulo": "portal_api", "cargas": []}
    if not cfg.get("ativo", False):
        man["cargas"].append({"endpoint": "portal_api", "ok": True, "carregado": 0, "nota": "desligado no config"})
        return man
    chave = ler_chave(raiz)
    if not chave:
        man["cargas"].append({"endpoint": "portal_api", "ok": False, "erro": "sem chave (config/segredos.yaml)"})
        log.warning("API do Portal: sem chave em config/segredos.yaml — CRM sem dados do Portal")
        return man
    lim = Limitador(cfg.get("limite_dia", 350), cfg.get("limite_noite", 650), cfg.get("intervalo_fixo"))
    conexoes = max(1, int(cfg.get("conexoes", 4)))
    local = threading.local()

    def cliente() -> ClientePortal:          # uma sessão HTTP por conexão (a de teste é compartilhada)
        if not hasattr(local, "cli"):
            local.cli = ClientePortal(chave, user_agent, sessao=sessao, limitador=lim)
        return local.cli

    orc_chamadas, orc_min = int(cfg.get("max_chamadas", 20000)), float(cfg.get("max_minutos", 90))
    max_pag = int(cfg.get("max_paginas", 20000))
    CONTADOR["chamadas"] = 0
    t0 = time.monotonic()
    repos: dict[str, Repositorio] = {}
    esquema_arq = estado / "portal_api_esquema.json"
    esquema = json.loads(esquema_arq.read_text("utf-8")) if esquema_arq.exists() else {}
    feitos, pulados, falhas, parou = {}, 0, {}, None
    trava = threading.Lock()
    ok_alguma = [False]     # a 1ª unidade vai sozinha: chave recusada custa uma chamada só

    def baixar(u):
        conjunto, caminho, params, fechado, _ = u
        c = cliente()
        antes = c.chamadas
        regs = c.paginas(caminho, _sem_parametros_de_caminho(conjunto, params), max_pag)
        df = achatar(regs)
        if conjunto == "recursos" and not df.empty:
            df = _so_pessoas_juridicas(df)
        repos[conjunto].gravar(params, df, fechado, dia, c.chamadas - antes)
        return df

    for etapa in (0, 1, 2):       # dependências: emendas → documentos das emendas → detalhe dos pagamentos
        plano = planejar(cfg, bruto, dia, municipios or [])
        if etapa > 0:
            plano = [u for u in plano if u[0] in ("emenda_docs", "documento")]
        baixados_antes = sum(feitos.values())
        fila = []
        for u in plano:
            repo = repos.setdefault(u[0], Repositorio(bruto, u[0]))
            if repo.precisa(u[2], u[3], u[4], dia):
                fila.append(u)
            else:
                pulados += 1
        with ThreadPoolExecutor(max_workers=conexoes) as ex:
            andamento = {}
            pos = 0
            while pos < len(fila) or andamento:
                while pos < len(fila) and len(andamento) < (conexoes if ok_alguma[0] else 1) and not parou:
                    if CONTADOR["chamadas"] >= orc_chamadas or (time.monotonic() - t0) / 60 > orc_min:
                        parou = "orçamento da execução atingido; continua na próxima carga"
                        break
                    andamento[ex.submit(baixar, fila[pos])] = fila[pos]
                    pos += 1
                if not andamento:
                    break
                prontos, _ = wait(andamento, return_when=FIRST_COMPLETED)
                for fut in prontos:
                    conjunto, _, params, _, _ = andamento.pop(fut)
                    try:
                        df = fut.result()
                        ok_alguma[0] = True
                        with trava:
                            feitos[conjunto] = feitos.get(conjunto, 0) + 1
                            if not df.empty:
                                esquema[conjunto] = sorted(set(esquema.get(conjunto, [])) |
                                                           {c for c in df.columns if c != "_unidade"})
                    except ErroChave as e:
                        if not parou or "orçamento" in parou:
                            parou = str(e)
                            man["cargas"].append({"endpoint": "portal_api", "ok": False, "erro": parou})
                            log.error(parou)
                    except Exception as e:  # uma unidade com erro não para as outras
                        ok_alguma[0] = True
                        repos[conjunto].falhou(params, f"{type(e).__name__}: {e}", dia)
                        falhas[conjunto] = falhas.get(conjunto, 0) + 1
                        log.warning("Portal API %s %s: %s", conjunto, params, str(e)[:160])
                if parou and "chave" in parou.lower():
                    pos = len(fila)          # chave recusada: não envia mais nada
        if parou or (etapa > 0 and sum(feitos.values()) == baixados_antes):
            break
    esquema_arq.write_text(json.dumps(esquema, ensure_ascii=False, indent=1), "utf-8")
    for conj in sorted(set(feitos) | set(falhas)):
        man["cargas"].append({"endpoint": f"portal_api/{conj}", "ok": not falhas.get(conj), "carregado": feitos.get(conj, 0),
                              "falhas": falhas.get(conj, 0)})
    man["resumo"] = {"chamadas": CONTADOR["chamadas"], "unidades_baixadas": sum(feitos.values()), "puladas_em_cache": pulados,
                     "falhas": sum(falhas.values()), "parou": parou, "minutos": round((time.monotonic() - t0) / 60, 1)}
    log.info("API do Portal: %s", man["resumo"])
    return man


def _so_pessoas_juridicas(df: pd.DataFrame) -> pd.DataFrame:
    """Recursos recebidos podem incluir pessoas físicas: ficam de fora (o CRM trata de entes e entidades)."""
    c = campo(df, "codigoPessoa", "codigoFavorecido", "cpfCnpj", "cnpj")
    if not c:
        return df
    d = doc_limpo(df[c])
    tipo = campo(df, "tipoPessoa", "tipoFavorecido")
    pf = d.str.len().eq(11) | df[c].fillna("").astype(str).str.contains(r"\*")
    if tipo:
        pf |= df[tipo].fillna("").astype(str).str.lower().str.contains("física|fisica")
    return df[~pf]


def sondar(user_agent: str, raiz: Path | None = None, sessao=None, ano: int | None = None) -> dict:
    """Uma chamada por conjunto, para ver os campos reais (usado por sondar_portal.bat)."""
    chave = ler_chave(raiz)
    if not chave:
        raise ErroChave("sem chave em config/segredos.yaml")
    cli = ClientePortal(chave, user_agent, sessao=sessao, limitador=Limitador(intervalo=0.3))
    ano = ano or date.today().year
    m = (pd.Period(date.today(), "M") - 2).strftime("%m/%Y")
    alvos = {"emendas": ("/emendas", {"ano": ano, "pagina": 1}),
             "recursos": ("/despesas/recursos-recebidos", {"mesAnoInicio": m, "mesAnoFim": m, "uf": "DF", "pagina": 1}),
             "ceis": ("/ceis", {"pagina": 1}), "cnep": ("/cnep", {"pagina": 1}), "cepim": ("/cepim", {"pagina": 1}),
             "presenca": ("/novo-bolsa-familia-por-municipio",
                          {"mesAno": (pd.Period(date.today(), "M") - 2).strftime("%Y%m"), "codigoIbge": "5300108",
                           "pagina": 1})}
    out = {}
    for nome, (caminho, params) in alvos.items():
        try:
            j = cli.get(caminho, params)
            df = achatar(j if isinstance(j, list) else [j])
            out[nome] = {"linhas": int(len(df)), "campos": list(df.columns),
                         "exemplo": {k: str(v)[:60] for k, v in (df.iloc[0].to_dict().items() if len(df) else [])}}
        except Exception as e:
            out[nome] = {"erro": f"{type(e).__name__}: {str(e)[:200]}"}
    em = out.get("emendas", {})
    if em.get("exemplo", {}).get("codigoEmenda"):
        cod = em["exemplo"]["codigoEmenda"]
        try:
            docs = achatar(cli.get(f"/emendas/documentos/{cod}", {"pagina": 1}))
            out["emenda_docs"] = {"linhas": int(len(docs)), "campos": list(docs.columns),
                                  "exemplo": {k: str(v)[:60] for k, v in (docs.iloc[0].to_dict().items() if len(docs) else [])}}
            cdoc = campo(docs, "codigoDocumento") if not docs.empty else None
            if cdoc:
                det = achatar(cli.get(f"/despesas/documentos/{docs.iloc[0][cdoc]}"))
                out["documento"] = {"campos": list(det.columns),
                                    "exemplo": {k: str(v)[:60] for k, v in (det.iloc[0].to_dict().items() if len(det) else [])}}
        except Exception as e:
            out["emenda_docs"] = {"erro": f"{type(e).__name__}: {str(e)[:200]}"}
    return out


if __name__ == "__main__":   # python -m custodia.portal_api  → sonda e grava data/estado/portal_api_sonda.json
    import sys
    from . import config
    cfg = config.carregar()
    cam = config.caminhos(cfg)
    r = sondar(cfg["api"]["user_agent"])
    (cam.estado / "portal_api_sonda.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), "utf-8")
    for k, v in r.items():
        print(k, "→", v.get("erro") or f"{v.get('linhas', '?')} linhas · campos: {', '.join(v['campos'][:14])}")
    print(f"Sonda gravada em {cam.estado / 'portal_api_sonda.json'}")
    sys.exit(0)
