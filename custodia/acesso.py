"""Usuários do painel (senha com PBKDF2, sem dependências externas) e carteira da equipe (SQLite).

Criar usuário:  python -m custodia.acesso adicionar <login> "<Nome>" <perfil>
Perfis: gestao, comercial, administrador
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from . import config

PERFIS = ("gestao", "comercial", "administrador")
STATUS_CARTEIRA = ("não abordado", "abordado", "proposta enviada", "conquistado", "perdido")


# ------------------------------------------------------------------ usuários
def _hash(senha: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), 200_000).hex()


def ler_usuarios(arquivo: Path | None = None) -> dict:
    arquivo = arquivo or config.caminhos().usuarios
    if not arquivo.exists():
        return {}
    return (yaml.safe_load(arquivo.read_text("utf-8")) or {}).get("usuarios", {})


def gravar_usuario(login: str, nome: str, perfil: str, senha: str, arquivo: Path | None = None) -> None:
    if perfil not in PERFIS:
        raise ValueError(f"Perfil deve ser um de {PERFIS}")
    arquivo = arquivo or config.caminhos().usuarios
    usuarios = ler_usuarios(arquivo)
    sal = secrets.token_hex(16)
    usuarios[login] = {"nome": nome, "perfil": perfil, "sal": sal, "senha": _hash(senha, sal)}
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(yaml.safe_dump({"usuarios": usuarios}, allow_unicode=True), "utf-8")


def autenticar(login: str, senha: str, arquivo: Path | None = None) -> dict | None:
    u = ler_usuarios(arquivo).get((login or "").strip())
    if not u:
        return None
    if hmac.compare_digest(_hash(senha or "", u["sal"]), u["senha"]):
        return {"login": login, "nome": u["nome"], "perfil": u["perfil"]}
    return None


# ------------------------------------------------------------------ carteira
def _con(db: Path | None = None) -> sqlite3.Connection:
    db = db or config.caminhos().carteira_db
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS carteira (
        cnpj_ente TEXT PRIMARY KEY, status TEXT, responsavel TEXT, observacao TEXT,
        atualizado_em TEXT, atualizado_por TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS carteira_log (
        cnpj_ente TEXT, status TEXT, responsavel TEXT, observacao TEXT, atualizado_em TEXT, atualizado_por TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS crm_atividade (
        id INTEGER PRIMARY KEY AUTOINCREMENT, cnpj_ente TEXT NOT NULL, atividade TEXT NOT NULL, data_atividade TEXT NOT NULL,
        resultado TEXT, proxima_acao TEXT, data_proxima TEXT, responsavel TEXT, registrado_por TEXT NOT NULL,
        registrado_em TEXT NOT NULL)""")
    return con


def carteira(db: Path | None = None) -> pd.DataFrame:
    with _con(db) as con:
        return pd.read_sql_query("SELECT * FROM carteira", con)


def historico_carteira(cnpj: str, db: Path | None = None) -> pd.DataFrame:
    with _con(db) as con:
        return pd.read_sql_query("SELECT * FROM carteira_log WHERE cnpj_ente=? ORDER BY atualizado_em DESC",
                                 con, params=(cnpj,))


def salvar_carteira(cnpj: str, status: str, responsavel: str, observacao: str, usuario: str,
                    db: Path | None = None) -> None:
    if status not in STATUS_CARTEIRA:
        raise ValueError("status inválido")
    agora = datetime.now().isoformat(timespec="seconds")
    linha = (cnpj, status, responsavel, observacao, agora, usuario)
    with _con(db) as con:
        con.execute("INSERT OR REPLACE INTO carteira VALUES (?,?,?,?,?,?)", linha)
        con.execute("INSERT INTO carteira_log VALUES (?,?,?,?,?,?)", linha)


# ------------------------------------------------------------------ CRM: atividades
TIPOS_ATIVIDADE = ("Visita", "Reunião", "Ligação", "E-mail", "Proposta", "Análise interna", "Outro")


def registrar_atividade(cnpj: str, atividade: str, data_atividade: str, resultado: str, proxima_acao: str,
                        data_proxima: str | None, responsavel: str, usuario: str, db: Path | None = None) -> int:
    """Grava uma atividade (nunca sobrescreve: o histórico do relacionamento fica inteiro)."""
    if atividade not in TIPOS_ATIVIDADE:
        raise ValueError("tipo de atividade inválido")
    datetime.fromisoformat(data_atividade)            # valida a data
    if data_proxima:
        datetime.fromisoformat(data_proxima)
    if not str(cnpj).isdigit() or len(str(cnpj)) != 14:
        raise ValueError("CNPJ do ente deve ter 14 dígitos")
    agora = datetime.now().isoformat(timespec="seconds")
    with _con(db) as con:
        cur = con.execute("""INSERT INTO crm_atividade (cnpj_ente, atividade, data_atividade, resultado, proxima_acao,
            data_proxima, responsavel, registrado_por, registrado_em) VALUES (?,?,?,?,?,?,?,?,?)""",
                          (cnpj, atividade, data_atividade, resultado, proxima_acao, data_proxima or None, responsavel,
                           usuario, agora))
        return int(cur.lastrowid)


def atividades(cnpj: str | None = None, db: Path | None = None) -> pd.DataFrame:
    with _con(db) as con:
        sql, par = "SELECT * FROM crm_atividade", ()
        if cnpj:
            sql, par = sql + " WHERE cnpj_ente=?", (cnpj,)
        return pd.read_sql_query(sql + " ORDER BY data_atividade DESC, id DESC", con, params=par)


def agenda(db: Path | None = None) -> pd.DataFrame:
    """Próxima ação vigente de cada ente: a da atividade mais recente (atividades novas substituem a agenda antiga)."""
    a = atividades(db=db)
    if a.empty:
        return a
    ult = a.sort_values(["data_atividade", "id"]).drop_duplicates("cnpj_ente", keep="last")
    return ult[ult["data_proxima"].notna() & (ult["data_proxima"] != "")].sort_values("data_proxima")


def _cli(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "adicionar":
        print(__doc__)
        return 1
    _, login, nome, perfil = argv
    senha = getpass.getpass(f"Senha para {login}: ")
    if len(senha) < 8 or senha != getpass.getpass("Repita a senha: "):
        print("Senha precisa ter 8+ caracteres e as duas digitações devem ser iguais.")
        return 1
    gravar_usuario(login, nome, perfil, senha)
    print(f"Usuário {login} ({perfil}) gravado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
