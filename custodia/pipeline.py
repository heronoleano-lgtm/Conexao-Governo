"""Orquestra a carga diária.

Uso:
    python -m custodia.pipeline                 # carga completa + transformação
    python -m custodia.pipeline --so-transformar  # refaz marts com os dados brutos já baixados
    python -m custodia.pipeline --sem-csv       # pula os CSVs de Discricionárias
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from . import config, historico, ingest_api, ingest_csv, marts, motores, qualidade, referencias, repositorio, storage
from . import motores_gestor as mg
from . import auditoria, auditoria_painel, ingest_outras, marts_crm, marts_outras, portal_api, regras, saldo_interno
from . import motores_fluxo as mf
from . import motores_territorio as mt
from .http import Cliente
from .ingest_api import ultimo_bruto

log = logging.getLogger("custodia")


def _configurar_log(pasta: Path, dia: date) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in raiz.handlers):
        fh = logging.FileHandler(pasta / f"carga_{dia.isoformat()}.log", encoding="utf-8")
        fh.setFormatter(fmt)
        raiz.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        raiz.addHandler(sh)


def _juntar_manifestos(cam: config.Caminhos, novos: list[dict]) -> list[dict]:
    """No modo --completar, mantém no manifesto as cargas anteriores que foram reaproveitadas."""
    anteriores = sorted(cam.estado.glob("manifesto_*.json"))
    if not anteriores:
        return novos
    velhos = {m.get("modulo"): m for m in json.loads(anteriores[-1].read_text("utf-8"))}
    saida = []
    for m in novos:
        v = velhos.pop(m.get("modulo"), None)
        if v and m.get("modulo") != "referencias":
            feitos = {c.get("endpoint") for c in m.get("cargas", [])}
            m["cargas"] = [c for c in v.get("cargas", []) if c.get("endpoint") not in feitos] + m.get("cargas", [])
        saida.append(m)
    return saida + list(velhos.values())


def baixar(cfg: dict, cam: config.Caminhos, dia: date, cli: Cliente, com_csv: bool = True,
           so_faltantes: bool = False) -> list[dict]:
    manifestos = []
    api = cfg["api"]
    for modulo, m in cfg["modulos"].items():
        if not m.get("ativo"):
            continue
        log.info("== Módulo %s", modulo)
        manifestos.append(ingest_api.carregar_modulo(cli, modulo, m.get("endpoints", []), cam.bruto, cam.estado,
                                                     dia, api["tamanho_pagina"], api["conexoes"],
                                                     so_faltantes=so_faltantes))
    if com_csv and cfg.get("csv_discricionarias", {}).get("ativo"):
        log.info("== CSVs de Discricionárias")
        manifestos.append(ingest_csv.carregar(cli, cfg["csv_discricionarias"], cam.bruto, cam.estado, dia))
    if cfg.get("outras_fontes", {}).get("ativo"):
        log.info("== Outras transferências (FUNDEB, Saúde, Educação, Assistência)")
        manifestos.append(ingest_outras.carregar(cfg["outras_fontes"], cfg["api"]["user_agent"], cam.bruto, cam.estado,
                                                 dia, sessao=cli.sessao))
    log.info("== Referências")
    manifestos.append({"modulo": "referencias", "cargas": [],
                       "status": referencias.atualizar(cli, cfg["referencias"], cam.referencias)})
    if (cfg.get("portal_api") or {}).get("ativo"):
        log.info("== API do Portal da Transparência (CRM)")
        try:
            muns = referencias.municipios(cam.referencias)["cod_ibge"].dropna().astype(str).tolist()
        except Exception:
            muns = []
        manifestos.append(portal_api.carregar(cfg["portal_api"], cfg["api"]["user_agent"], cam.bruto, cam.estado, dia,
                                              # sessão própria: a chave não pode ir junto nas chamadas a outros sites
                                              sessao=None if type(cli.sessao) is requests.Session else cli.sessao,
                                              municipios=muns))
    if so_faltantes:
        manifestos = _juntar_manifestos(cam, manifestos)
    (cam.estado / f"manifesto_{dia.isoformat()}.json").write_text(
        json.dumps(manifestos, ensure_ascii=False, indent=1, default=str), "utf-8")
    return manifestos


def _crm(cam, saida: dict, f: dict, fluxo: pd.DataFrame, dia: date, mun_ref: pd.DataFrame) -> dict:
    """CRM: Portal da Transparência (recebidos, emendas, sanções, presença CAIXA) + o que o painel já sabe."""
    c = marts_crm.consolidar(cam.bruto)
    cart = marts_crm.carteira(c["crm_recebido"], saida.get("fato_repasse_outros"), f["fato_pipeline"],
                              saida.get("mart_ente_resumo"), mun_ref, dia, c.get("crm_cobertura"))
    pres = marts_crm.presenca(c["crm_presenca_bruta"], cart, saida.get("mart_ente_resumo"), mun_ref)
    alertas = marts_crm.alertas_conformidade(c["crm_sancao"], fluxo, f.get("fato_pagamento"), c["crm_recebido"],
                                             saida.get("mart_potencial"), f["fato_conta"], dia)
    return {**c, "crm_carteira": cart, "crm_presenca": pres, "crm_alertas": alertas,
            "crm_rede": marts_crm.rede(c["crm_emenda_pagamento"], saida.get("mart_ente_resumo"), fluxo, alertas),
            "crm_prioridade": marts_crm.prioridade(cart, saida.get("mart_potencial"), pres, saida.get("mart_janela_escolha"),
                                                   alertas, c["crm_emenda_pagamento"], saida.get("mart_ente_resumo"))}


def _outras(cam, mun_ref) -> dict:
    o = marts_outras.construir(cam.bruto, mun_ref)
    return {**o, "mart_outras_municipio": marts_outras.por_municipio(o["fato_repasse_outros"], o["fato_conta_saude"]),
            "mart_oport_saude": marts_outras.oportunidades_saude(
                o["fato_conta_saude"], regras.param("SAU-01", "saldo_minimo", 100000))}


def transformar(cfg: dict, cam: config.Caminhos, dia: date, manifestos: list[dict] | None = None) -> Path:
    if manifestos is None:
        arq = cam.estado / f"manifesto_{dia.isoformat()}.json"
        anteriores = sorted(cam.estado.glob("manifesto_*.json"))
        arq = arq if arq.exists() else (anteriores[-1] if anteriores else None)
        manifestos = json.loads(arq.read_text("utf-8")) if arq else []

    # 1) histórico (SCD2) de TODAS as tabelas baixadas: guarda só o que muda e reconstrói qualquer dia sem perda
    mudancas, resumo_hist, verificacoes = {}, {}, []
    campos_alerta = {"especiais/planos-acao-especiais": ["codigo_banco_plano_acao", "situacao_plano_acao"],
                     "especiais/saldo-conta-gestao-financeira-especiais": ["saldo_final_gestao_financeira"]}
    explicitas = dict(cfg.get("historico") or {})
    arq_chaves = cam.estado / "chaves_historico.json"
    chaves = json.loads(arq_chaves.read_text("utf-8")) if arq_chaves.exists() else {}
    tabelas = sorted({f"{p.parent.name}/{p.name}" for p in cam.bruto.glob("*/*")
                      if p.is_dir() and not p.name.startswith("_")} | set(explicitas))
    for tabela in tabelas:
        modulo, endpoint = tabela.split("/")
        atual = ultimo_bruto(cam.bruto, modulo, endpoint)
        if atual.empty:
            continue
        anterior = chaves.get(tabela)
        chave = anterior or historico.escolher_chave(atual, explicitas.get(tabela))
        if chave != historico.CHAVE_LINHA and (chave not in atual.columns or atual[chave].duplicated().any()):
            log.warning("Histórico %s: chave %s deixou de ser única; passa a usar a linha inteira", tabela, chave)
            chave = historico.CHAVE_LINHA
        arq = cam.historico / tabela.replace("/", "__")
        if anterior and chave != anterior and storage.existe(arq):
            # troca de chave: o histórico antigo é arquivado inteiro (nada se perde) e um novo começa hoje
            antigo = storage.caminho(cam.historico, f"{tabela.replace('/', '__')}__ate_{dia.isoformat()}")
            storage.caminho(cam.historico, tabela.replace("/", "__")).rename(antigo)
        chaves[tabela] = chave
        resumo_hist[tabela] = historico.atualizar(atual, chave, arq, dia)
        arq_chaves.write_text(json.dumps(chaves, ensure_ascii=False, indent=1), "utf-8")   # salva a cada tabela
        v = historico.verificar(atual, chave, arq, dia)
        verificacoes.append({"tabela": tabela, "chave": chave, **v})
        if tabela in explicitas:
            mudancas[tabela] = historico.mudancas_do_dia(arq, chave, dia, campos_alerta.get(tabela, []))
        log.info("Histórico %s (%s): %s · sem perda=%s", tabela, chave, resumo_hist[tabela], v["ok"])
    arq_chaves.write_text(json.dumps(chaves, ensure_ascii=False, indent=1), "utf-8")

    # 2) fatos e dimensões
    entes_ref = referencias.entes_siconfi(cam.referencias)
    mun_ref = referencias.municipios(cam.referencias)
    f = marts.construir(cam.bruto, entes_ref, mun_ref)
    pasta_int = cam.dados / "internos"
    saldo_interno.exportar_contas(f["fato_conta"], pasta_int)
    f["fato_conta"], resumo_interno = saldo_interno.aplicar(f["fato_conta"], pasta_int)
    f["fato_conta"] = marts.saldo_uma_vez(f["fato_conta"])      # saldo de cada conta entra uma vez só
    # saldo estimado ao lado do publicado onde o extrato parou (regra SAL-01); o publicado não muda
    rec = {"contas": pd.DataFrame(), "serie": pd.DataFrame(), "qualidade": pd.DataFrame()}
    try:
        from . import reconstituicao
        paradas0 = mg.fontes_interrompidas(f["fato_fluxo"], f["fato_conta"], dia)
        rec = reconstituicao.reconstituir(f["fato_conta"], f.get("fato_credito"), f["fato_fluxo"], dia, paradas0)
        f["fato_conta"] = reconstituicao.aplicar(f["fato_conta"], rec["contas"])
    except Exception:
        log.exception("Reconstituição do saldo falhou (a carga segue só com o saldo publicado)")
    # só o CONTRATADO entra nos valores; o previsto (propostas, planos em elaboração) vale para a escolha de banco
    # e para o dinheiro previsto; cancelado/anulado/impedido fica fora e registrado (red team 02/11)
    todos = f["fato_instrumento"].assign(etapa_instrumento=lambda x: marts.etapa_instrumento(x))
    if "orgao" in todos:      # um nome por órgão em todas as modalidades (revisão de 03/11)
        from .analise_fluxo import nome_orgao
        todos["orgao"] = nome_orgao(todos["orgao"])
    f["fato_instrumento"] = todos[todos["etapa_instrumento"] == marts.CONTRATADO].reset_index(drop=True)
    instr_escolha = todos[todos["etapa_instrumento"] != marts.CANCELADO].reset_index(drop=True)
    f["fato_instrumento_fora"] = todos[todos["etapa_instrumento"] != marts.CONTRATADO].reset_index(drop=True)
    instr, contas = f["fato_instrumento"], f["fato_conta"]

    # 3) motores
    mc = cfg.get("motores", {})
    anos = mc.get("anos_recentes", 2)
    saldo_alto = mc.get("saldo_alto_concorrente", 1_000_000)
    disput = mc.get("modulos_disputaveis", ["Especiais", "Discricionárias"])
    instr_d = instr_escolha[instr_escolha["modulo"].isin(disput)]     # escolha de banco: inclui o previsto
    contas_d = contas[contas["modulo"].isin(disput)]
    perfil = motores.perfil_entes(instr_d, anos)
    vaz = motores.vazamento(f["fato_executor"])
    jan = motores.janelas(instr_d, contas_d, perfil, vaz, saldo_alto)
    sc = motores.score(perfil, contas_d, jan, vaz, instr_d, mc.get("pesos_score", {}), anos)
    cust = motores.custodia(contas)
    fluxo = f["fato_fluxo"]
    dest_ente = mf.destino_por_ente(fluxo)
    saida = {
        **f,
        "mart_saldo_reconstituido": rec["serie"],
        "mart_reconstituicao_qualidade": rec["qualidade"],
        "mart_participacao": motores.participacao(instr),
        "mart_custodia": cust,
        "mart_pipeline": motores.pipeline(f["fato_pipeline"]),
        "mart_vazamento": vaz,
        "mart_perfil_ente": perfil,
        "mart_janelas": jan,
        "mart_score": sc,
        "mart_alertas": motores.alertas(mudancas, saldo_alto),
        # origem -> caminho -> destino
        "mart_sankey": mf.sankey(instr, fluxo),
        "mart_matriz_destino": mf.matriz_destino(fluxo).reset_index(),
        "mart_parlamentares": mf.parlamentares(instr, f["fato_emenda"], perfil),
        "mart_rede_parlamentar": mf.rede_parlamentar_ente(instr, f["fato_emenda"]),
        "mart_orgaos": mf.orgaos(instr, contas),
        "mart_destinacao": mf.destinacao(f["fato_destinacao"], instr),
        "mart_destino_ente": dest_ente,
        "mart_fornecedores": mf.fornecedores(fluxo, f["fato_pagamento"]).head(20000),
        "mart_velocidade": mf.velocidade(f["fato_pipeline"]),
        "mart_potencial": mf.potencial(perfil, contas_d, f["fato_pipeline"], dest_ente, jan, sc, vaz, mc),
        "mart_conformidade": mf.conformidade(fluxo, mc.get("data_portaria_15_2025", "2025-07-28")),
        "mart_transferencia_secundaria": mf.transferencia_secundaria(fluxo, instr, contas),
    }
    saida["mart_ente_resumo"] = mt.ente_resumo(instr, contas, f["fato_pipeline"], f["dim_ente"],
                                               saida["mart_potencial"], saida["mart_transferencia_secundaria"], mun_ref)
    saida["mart_uf_modalidade"] = mt.uf_modalidade(instr, contas)

    # 3b) motores do gestor de custódia + série diária por ente (repositório)
    # cada bloco é independente: se um falhar, a falha vai para o log e para Qualidade, e o resto é publicado
    falhas: list[str] = []

    def seguro(nome, fn, padrao=None):
        try:
            return fn()
        except Exception:
            log.exception("Bloco %s falhou (a carga segue sem ele)", nome)
            falhas.append(nome)
            return pd.DataFrame() if padrao is None else padrao

    vazio = pd.DataFrame()
    pipe, er = f["fato_pipeline"], saida["mart_ente_resumo"]
    pasta_serie = cam.historico / "serie_ente"
    seguro("serie_ente", lambda: repositorio.gravar_serie_ente(pasta_serie, repositorio.linhas_do_dia(instr, contas, pipe), dia))
    serie_e = seguro("serie_ente_leitura", lambda: repositorio.ler_serie_ente(pasta_serie, desde=date(dia.year - 1, 1, 1)))
    nomes = f["dim_ente"][["cnpj_ente", "nome_ente"]].drop_duplicates("cnpj_ente")
    var_ente = seguro("mart_variacao_ente", lambda: repositorio.variacoes(
        serie_e, ["cnpj_ente", "uf", "modulo", "grupo_banco"], dia).merge(nomes, on="cnpj_ente", how="left"))
    paradas = seguro("fontes_interrompidas", lambda: mg.fontes_interrompidas(fluxo, contas, dia), set())
    if paradas:
        log.warning("Extrato interrompido na fonte: %s", sorted(paradas))
    esc = seguro("mart_escolha_ente", lambda: mg.escolhas(instr_escolha))
    perdidos = seguro("mart_entes_perdidos", lambda: mg.entes_perdidos(esc, contas, saida["mart_potencial"]))
    receber = seguro("mart_a_receber", lambda: mg.a_receber(pipe, instr_escolha, dia))
    transf = saida["mart_transferencia_secundaria"]
    janela = seguro("mart_janela_escolha", lambda: mg.janela_escolha(instr_escolha, esc))
    radar = seguro("mart_radar", lambda: mg.radar_risco(instr, contas, perdidos, dest_ente, saida["mart_rede_parlamentar"],
                                                       saida["mart_conformidade"], var_ente, dia))
    radar = pd.concat([radar, seguro("riscos_ampliados", lambda: mg.riscos_ampliados(esc, instr, janela, contas))],
                      ignore_index=True)
    vc = seguro("mart_venda_cruzada", lambda: mg.venda_cruzada(esc, transf, dest_ente, contas, fluxo, receber, anos, paradas))
    chance = seguro("chance_conversao", lambda: mg.chance_conversao(er, perfil, perdidos, vc, transf, esc))
    ve = var_ente if not var_ente.empty and "saldo" in var_ente else vazio
    saida.update(seguro("outras_fontes", lambda: _outras(cam, mun_ref), {}))
    saida.update({
        "mart_janela_escolha": janela,
        "mart_calendario_escolha": seguro("mart_calendario_escolha", lambda: mg.calendario_escolha(instr_escolha)),
        "mart_risco_agentes": seguro("mart_risco_agentes", lambda: mg.riscos_agentes(instr)),
        "mart_fora_caixa": seguro("mart_fora_caixa", lambda: mg.fora_da_caixa(er, esc, instr, dest_ente, perdidos)),
        "mart_fora_caixa_agentes": seguro("mart_fora_caixa_agentes", lambda: mg.fora_da_caixa_agentes(instr)),
        "mart_permanencia": seguro("mart_permanencia", lambda: mg.permanencia(contas, fluxo, mc, paradas)),
        "mart_concentracao": seguro("mart_concentracao", lambda: mg.concentracao(contas)),
        "mart_defasagem": seguro("mart_defasagem", lambda: mg.defasagem(contas, dia, fluxo)),
        "mart_a_receber": receber,
        "mart_sazonalidade": seguro("mart_sazonalidade", lambda: mg.sazonalidade(pipe)),
        "mart_escolha_ente": esc,
        "mart_transicoes": seguro("mart_transicoes", lambda: mg.transicoes(esc)),
        "mart_matriz_modalidades": seguro("mart_matriz_modalidades", lambda: mg.matriz_modalidades(esc)),
        "mart_entes_perdidos": perdidos,
        "mart_radar": radar,
        "mart_venda_cruzada": vc,
        "mart_priorizacao": seguro("mart_priorizacao", lambda: mg.priorizacao(er, chance)),
        "mart_ente_dimensoes": seguro("mart_ente_dimensoes", lambda: mg.dimensoes(er, receber, radar, vc, chance)),
        "mart_variacao_ente": ve[ve["saldo"].abs() > 0] if not ve.empty else vazio,
        "mart_variacao_banco": seguro("mart_variacao_banco", lambda: repositorio.variacoes(serie_e, ["modulo", "grupo_banco"], dia)),
        "mart_variacao_uf": seguro("mart_variacao_uf", lambda: repositorio.variacoes(serie_e, ["uf", "grupo_banco"], dia)),
        "mart_evolucao_saldo": seguro("mart_evolucao_saldo", lambda: repositorio.evolucao(serie_e, ["modulo", "grupo_banco"], "D")),
    })
    saida.update(seguro("crm", lambda: _crm(cam, saida, f, fluxo, dia, mun_ref), {}))
    # o fato de fluxo é grande; o painel usa os marts agregados (sem nomes e documentos de favorecidos)
    saida["fato_fluxo"] = fluxo.drop(columns=[c for c in ("favorecido", "doc_favorecido") if c in fluxo])

    # 4) série diária (base da tendência) e qualidade
    linhas = instr.groupby(["modulo", "grupo_banco"], as_index=False).agg(valor=("valor", "sum"),
                                                                          instrumentos=("id_instrumento", "count"))
    if not cust.empty:
        linhas = linhas.merge(cust[["modulo", "grupo_banco", "saldo", "contas", "cobertura"]],
                              on=["modulo", "grupo_banco"], how="left")
    serie = historico.serie_diaria(cam.historico / "serie_diaria", linhas, dia)
    saida["serie_diaria"] = serie
    saida["mart_qualidade"] = qualidade.checar(manifestos, cust, serie, cfg.get("qualidade", {}))
    ver = pd.DataFrame(verificacoes)
    if not ver.empty:
        ruins = ver[~ver["ok"]]
        saida["mart_qualidade"] = pd.concat([saida["mart_qualidade"], pd.DataFrame([{
            "status": "ok" if ruins.empty else "erro", "modulo": "repositório",
            "item": "Histórico sem perda (QLD-02)",
            "detalhe": (f"{len(ver)} tabelas: o dia reconstruído pelo histórico é idêntico à fonte"
                        if ruins.empty else "Diferença em: " + ", ".join(ruins["tabela"]))}])], ignore_index=True)
    saida["repo_verificacao"] = ver
    if falhas:
        saida["mart_qualidade"] = pd.concat([saida["mart_qualidade"], pd.DataFrame([{
            "status": "erro", "modulo": "painel", "item": "Blocos não calculados nesta carga",
            "detalhe": "Falharam (veja o log da carga): " + ", ".join(falhas)}])], ignore_index=True)
    coords = referencias.coordenadas(cam.referencias)
    saida["ref_coordenadas"] = coords
    pasta_repo = cam.dados / "repositorio"
    saida["repo_registro_cargas"] = repositorio.registrar_cargas(pasta_repo, manifestos, dia)
    # auditoria da carga bruta (completude, estrutura, chaves, domínios, integridade, coerência, frescor, reconciliação)
    reg = saida["repo_registro_cargas"]
    ant = reg[reg["dia"] < dia.isoformat()] if not reg.empty else reg
    ant = ant[ant["dia"] == ant["dia"].max()] if not ant.empty else ant
    aud = auditoria.auditar(cam.bruto, dia, manifestos, saida, ant,
                            int(mc.get("dias_limite_extrato", 60)))
    auditoria.gravar(aud, cam.dados)
    saida["mart_auditoria"] = aud
    hist_aud = storage.ler(cam.dados / "auditoria" / "historico_auditoria")
    saida["mart_auditoria_historico"] = (hist_aud.groupby(["dia", "status"], as_index=False).size()
                                         .rename(columns={"size": "checagens"}) if not hist_aud.empty else hist_aud)
    criticos = aud[aud["status"] == auditoria.CRITICO]
    log.info("Auditoria: %d checagens, %d críticas", len(aud), len(criticos))
    for r in criticos.head(10).itertuples():
        log.warning("Auditoria crítica · %s · %s: %s (%s)", r.familia, r.tabela, r.checagem, r.medido)
    # auditoria do que o painel mostra (percentuais, partes ≤ todo, coerência entre telas, território)
    try:
        aud_p, ex_p = auditoria_painel.auditar(saida, dia)
        auditoria_painel.gravar(aud_p, ex_p, cam.dados / "auditoria", dia.isoformat())
        saida["mart_auditoria_painel"], saida["mart_auditoria_painel_exemplos"] = aud_p, ex_p
        for r in aud_p[aud_p["status"] == auditoria.CRITICO].head(10).itertuples():
            log.warning("Auditoria do painel · %s · %s: %s", r.tabela, r.checagem, r.detalhe)
    except Exception:
        log.exception("Auditoria do painel falhou (a carga segue)")
    # auditoria profunda: refaz os números-chave em SQL, testes estatísticos e rede neural de anomalias
    try:
        from . import auditoria_profunda
        apf, anom, ext = auditoria_profunda.auditar(saida, rede=bool(cfg.get("auditoria", {}).get("rede_neural", True)))
        saida["mart_auditoria_profunda"], saida["mart_anomalias_entes"], saida["mart_extremos"] = apf, anom, ext
        pasta_a = cam.dados / "auditoria"
        pasta_a.mkdir(parents=True, exist_ok=True)
        apf.to_csv(pasta_a / f"profunda_{dia.isoformat()}.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
        if not anom.empty:
            anom.to_csv(pasta_a / f"anomalias_{dia.isoformat()}.csv", index=False, sep=";", decimal=",",
                        encoding="utf-8-sig")
        for r in apf[apf["status"] == auditoria.CRITICO].head(10).itertuples():
            log.warning("Auditoria profunda · %s · %s: %s", r.tabela, r.checagem, r.detalhe)
    except Exception:
        log.exception("Auditoria profunda falhou (a carga segue)")
    saida["repo_catalogo"] = repositorio.catalogo(cam.dados, saida)

    # 5) publica numa pasta nova e só então aponta ATUAL para ela (o painel nunca vê dados pela metade)
    execucao = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = cam.marts / execucao
    for nome, df in saida.items():
        storage.gravar(df.reset_index(drop=True), destino / nome)
    meta = {"execucao": execucao, "dia": dia.isoformat(),
            "data_atualizacao": {m["modulo"]: m.get("data_atualizacao") for m in manifestos if m.get("data_atualizacao")},
            "historico": resumo_hist, "saldo_interno": resumo_interno,
            "fontes_interrompidas": [{"modulo": m, "banco": b} for m, b in sorted(paradas)],
            "modulos": {k: {"nome": v.get("nome", k), "ativo": bool(v.get("ativo"))} for k, v in cfg["modulos"].items()},
            "linhas": {k: int(len(v)) for k, v in saida.items()}, "blocos_com_falha": falhas}
    (destino / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), "utf-8")
    tmp = cam.marts / "ATUAL.txt.tmp"
    tmp.write_text(execucao, "utf-8")
    tmp.replace(cam.marts / "ATUAL.txt")
    _limpar_marts(cam.marts, manter=3)
    log.info("Marts publicados em %s", destino)
    return destino


def _limpar_marts(pasta: Path, manter: int) -> None:
    execs = sorted(p for p in pasta.iterdir() if p.is_dir())
    for p in execs[:-manter]:
        shutil.rmtree(p, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Carga diária do Conexão Governo (painel de custódia)")
    ap.add_argument("--so-transformar", action="store_true")
    ap.add_argument("--sem-csv", action="store_true")
    ap.add_argument("--dia", help="AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--foto", action="store_true", help="guarda uma foto completa do bruto do dia no repositório")
    a = ap.parse_args(argv)
    cfg = config.carregar()
    cam = config.caminhos(cfg)
    cam.criar()
    dia = date.fromisoformat(a.dia) if a.dia else date.today()
    _configurar_log(cam.logs, dia)
    t0 = time.time()
    try:
        manifestos = None
        if not a.so_transformar:
            api = cfg["api"]
            cli = Cliente(api["base_url"], api["user_agent"], api["timeout_seg"], api["tentativas"])
            manifestos = baixar(cfg, cam, dia, cli, com_csv=not a.sem_csv)
            if repositorio.deve_fotografar(cfg.get("repositorio", {}), dia, a.foto, cam.dados):
                repositorio.foto_completa(cam.dados, dia)
            ingest_api.limpar_bruto(cam.bruto, cfg["dados"].get("manter_bruto_dias", 30))
        transformar(cfg, cam, dia, manifestos)
    except Exception:
        log.exception("Carga falhou")
        return 1
    log.info("Carga concluída em %.1f min", (time.time() - t0) / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
