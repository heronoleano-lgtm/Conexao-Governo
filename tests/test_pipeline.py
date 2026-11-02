"""Teste de ponta a ponta: duas cargas diárias contra a API falsa."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from custodia import config, ingest_api, pipeline, storage
from custodia.http import Cliente
from custodia.normaliza import codigo_banco, grupo_banco, numero
from tests.fake_api import BASE, SessaoFalsa, dados_base


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIA_DADOS", str(tmp_path / "data"))
    config.carregar.cache_clear()
    cfg = config.carregar()
    cfg = json.loads(json.dumps(cfg))
    cfg["api"]["tamanho_pagina"] = 7   # força várias páginas
    cfg["api"]["conexoes"] = 3
    cfg["motores"]["saldo_alto_concorrente"] = 500_000
    cfg["portal_api"].update({"intervalo_fixo": 0})       # simulador: sem espera entre chamadas
    cfg["portal_api"]["recursos"]["meses"] = 2
    cam = config.caminhos(cfg)
    cam.criar()
    return cfg, cam


def _ler_mart(cam, nome):
    atual = (cam.marts / "ATUAL.txt").read_text()
    return storage.ler(cam.marts / atual / nome)


def test_normalizacao():
    assert codigo_banco("001") == "1" and codigo_banco(104.0) == "104"
    assert codigo_banco(None, "Caixa Econômica Federal") == "104"
    assert grupo_banco("104") == "CAIXA" and grupo_banco("") == "(sem banco)"
    assert numero(pd.Series(["1.250.000,50", "300000.25", ""])).tolist()[:2] == [1250000.5, 300000.25]


def test_novas_tentativas():
    s = SessaoFalsa(falhas=2)
    cli = Cliente(BASE, "teste", tentativas=4, sessao=s)
    import custodia.http as h
    h.time.sleep = lambda *_: None
    df, res = ingest_api.baixar_endpoint(cli, "especiais", "beneficiarios-especiais", 2, 2)
    assert res.ok and len(df) == 5


def test_ponta_a_ponta(ambiente):
    cfg, cam = ambiente
    dados = dados_base()
    cli = Cliente(BASE, "teste", sessao=SessaoFalsa(dados))

    # ---- dia 1
    d1 = date(2026, 11, 3)
    man = pipeline.baixar(cfg, cam, d1, cli)
    cargas = [c for m in man for c in m.get("cargas", []) if "esperado" in c]
    assert cargas and all(c["ok"] for c in cargas), [c for c in cargas if not c["ok"]]
    pipeline.transformar(cfg, cam, d1, man)

    instr = _ler_mart(cam, "fato_instrumento")
    assert set(instr["modulo"]) == {"Especiais", "Fundo a Fundo", "Discricionárias"}
    disc = instr[instr["modulo"] == "Discricionárias"].set_index("id_instrumento")
    assert disc.loc["900001", "valor"] == pytest.approx(1250000.5)
    assert disc.loc["900001", "grupo_banco"] == "CAIXA" and int(disc.loc["900002", "ano"]) == 2025

    esp = instr[instr["modulo"] == "Especiais"]
    # só o contratado entra nos valores; os 2 planos impedidos/em elaboração do simulador ficam em fato_instrumento_fora
    fora = _ler_mart(cam, "fato_instrumento_fora")
    assert len(fora[fora["modulo"] == "Especiais"]) == 2 and set(fora["etapa_instrumento"]) <= {"previsto", "impedido", "cancelado"}
    assert len(esp) == 28 and esp["cnpj_ente"].str.len().eq(14).all()
    assert (esp["grupo_banco"] == "(sem banco)").sum() == 0      # os 2 sem banco são impedido/aguardando ciência (fora)
    assert (fora.loc[fora["modulo"] == "Especiais", "grupo_banco"] == "(sem banco)").sum() == 2

    cust = _ler_mart(cam, "mart_custodia").set_index(["modulo", "grupo_banco"])
    assert cust.loc[("Fundo a Fundo", "BB"), "saldo"] == pytest.approx(4_500_000)
    assert cust.loc[("Especiais", "CAIXA"), "cobertura"] > 0

    perfil = _ler_mart(cam, "mart_perfil_ente").set_index("cnpj_ente")
    assert perfil.loc["22222222000102", "perfil"] == "multibanco"
    assert perfil.loc["11111111000101", "perfil"] == "só CAIXA"

    vaz = _ler_mart(cam, "mart_vazamento")
    assert (vaz["direcao"] == "saída da CAIXA").sum() == 2

    jan = _ler_mart(cam, "mart_janelas")
    motivos = set(jan["motivo"])
    assert {"Plano sem banco definido", "Plano impedido e sem banco", "Saldo alto parado no concorrente",
            "Ente multibanco com plano novo no concorrente", "Executor recebe em outro banco"} <= motivos

    sc = _ler_mart(cam, "mart_score")
    assert sc["score"].between(0, 100).all()
    assert sc.iloc[0]["cnpj_ente"] != "11111111000101"   # ente só-CAIXA não lidera a prospecção

    pipe = _ler_mart(cam, "mart_pipeline")
    assert pipe["a_creditar"].sum() == pytest.approx(90000 * 18)  # k=1 e k=2 sem OB

    q = _ler_mart(cam, "mart_qualidade")
    assert not (q["status"] == "erro").any(), q[q["status"] == "erro"]
    assert _ler_mart(cam, "ref_coordenadas").shape[0] == 4
    dim = _ler_mart(cam, "dim_ente").set_index("cnpj_ente")
    assert dim.loc["11111111000101", "cod_ibge"] == "3100104"

    # ---- novos motores: origem -> caminho -> destino
    assert disc.loc["900002", "grupo_banco"] == "BB"            # banco vem do NOME no CSV real
    assert disc.loc["900001", "orgao"] == "MINISTÉRIO DAS CIDADES" and disc.loc["900001", "parlamentar"] == "FULANO"
    contas_disc = _ler_mart(cam, "fato_conta").query("modulo == 'Discricionárias'")
    assert set(contas_disc["id_instrumento"]) == {"900001", "900002"}   # encerrado sem saldo fica fora
    assert contas_disc["saldo"].sum() == pytest.approx(700000)
    assert esp["area"].notna().all() or (esp["grupo_banco"] == "(sem banco)").any()
    sk = _ler_mart(cam, "mart_sankey")
    assert {"1 · origem → área", "2 · área → banco da conta", "3 · conta → quem recebe"} <= set(sk["etapa"])
    assert sk.loc[sk["etapa"] == "2 · área → banco da conta", "valor"].sum() == pytest.approx(instr["valor"].sum())
    fl = _ler_mart(cam, "fato_fluxo")
    assert set(fl["tipo_movimento"]) == {"pagamento/transferência", "aplicação/resgate"}  # créditos fora (filtro D)
    assert fl["proprio_ente"].sum() > 0
    parl = _ler_mart(cam, "mart_parlamentares").set_index("parlamentar")
    assert {"Fulano", "Beltrana", "Sicrano", "FULANO", "BELTRANA"} <= set(parl.index)
    assert parl.loc["BELTRANA", "part_caixa"] == 0
    org = _ler_mart(cam, "mart_orgaos")
    assert {"MinC", "MINISTÉRIO DAS CIDADES", "MINISTÉRIO DA SAÚDE"} <= set(org["orgao"])
    assert org.loc[org["orgao"] == "MinC", "saldo"].sum() == pytest.approx(4_500_000)
    dest = _ler_mart(cam, "mart_destinacao")
    assert {"Urbanismo", "Saúde", "CUSTEIO"} <= set(dest["tipo"])
    forn = _ler_mart(cam, "mart_fornecedores")
    assert "CONSTRUTORA EXEMPLO LTDA" in set(forn["recebedor"]) and "PESSOA FISICA" not in set(forn["recebedor"])
    assert forn.loc[forn["fonte"].str.startswith("lançamentos"), "banco_principal"].iloc[0] == "BB"
    pot = _ler_mart(cam, "mart_potencial")
    assert pot["acao_recomendada"].notna().all() and (pot["potencial_custodia"] >= 0).all()
    assert pot.set_index("cnpj_ente").loc["44444444000104", "acao_recomendada"].startswith("Contatar")
    conf = _ler_mart(cam, "mart_conformidade")
    assert not conf.empty and (conf["grupo_origem"] == "BB").all() and (conf["primeira"] >= "2025-07-28").all()
    ts = _ler_mart(cam, "mart_transferencia_secundaria").set_index("cnpj_ente")
    assert set(ts.index) == {"11111111000101", "33333333000103"}          # só CNPJ do favorecido = CNPJ do ente
    assert ts.loc["11111111000101", "valor_transferido"] == pytest.approx(120000)
    assert bool(ts.loc["11111111000101", "tem_conta_caixa_outro_modulo"])  # Alfa tem planos CAIXA nas Especiais
    assert ts.loc["11111111000101", "saldo_faf_hoje"] == pytest.approx(1_500_000)
    assert ts.loc["33333333000103", "valor_12_meses"] == 0                  # transferência de 2024
    assert not set(conf["cnpj_ente"]) & {"33333333000103"}                 # FaF não entra na conformidade
    # território: todo ente com código IBGE; agregação por UF e por município
    assert (cam.referencias / "malhas" / "BR.json").exists() and (cam.referencias / "malhas" / "MG.json").exists()
    dim = _ler_mart(cam, "dim_ente").set_index("cnpj_ente")
    assert dim.loc["22222222000102", "cod_ibge"] == "3100203"             # via Siconfi (CNPJ)
    assert dim.loc["44444444000104", "cod_ibge"] == "2900108"             # via nome 'MUNICIPIO DE DELTA' + BA
    assert dim.loc["55555555000105", "cod_ibge"] == "29" and dim.loc["55555555000105", "esfera"] == "Estadual"
    from custodia import consultas
    dd = consultas.carregar((cam.marts / "ATUAL.txt").read_text())
    uf = consultas.territorio(dd, "UF").set_index("codarea")
    assert {"31", "43", "29"} <= set(uf.index)
    assert uf["valor"].sum() == pytest.approx(dd["fato_instrumento"].query("grupo_banco != '(sem banco)'")["valor"].sum())
    mun = consultas.territorio(dd, "Município", "MG").set_index("codarea")
    assert set(mun.index) == {"3100104", "3100203"} and mun.loc["3100104", "nome"] == "Alfa"
    assert mun.loc["3100104", "transf_secundaria"] == pytest.approx(120000)
    assert not consultas.entes_da_area(dd, "29").empty                    # governo do estado da BA
    # pagamentos do Fundo a Fundo ligados ao ente pagador pelo lançamento, com identificador único
    pg = dd["fato_pagamento"]
    faf = pg[pg["modulo"] == "Fundo a Fundo"]
    assert len(faf) == 2 and (faf["cnpj_ente"] == "33333333000103").all() and faf["id_pagamento"].is_unique
    # saldo de cada conta entra uma vez em todas as tabelas (auditoria de 01/11: Fundo a Fundo contado em dobro)
    unicas = dd["fato_conta"].assign(s=pd.to_numeric(dd["fato_conta"]["saldo"], errors="coerce")).groupby(
        ["modulo", "id_agencia_conta"])["s"].max().sum()
    assert pd.to_numeric(dd["fato_conta"]["saldo"], errors="coerce").sum() == pytest.approx(unicas)
    for t in ("mart_permanencia", "mart_variacao_banco", "mart_defasagem", "mart_custodia"):
        assert dd[t]["saldo"].sum() == pytest.approx(unicas), t
    vel = _ler_mart(cam, "mart_velocidade")
    assert not vel.empty

    # ---- dia 2: um plano troca de banco e surge um plano novo
    pa = dados["especiais"]["planos-acao-especiais"]
    pa[0]["codigo_banco_plano_acao"] = "001"
    novo = dict(pa[-1], id_plano_acao=999, codigo_plano_acao="09032026-000999", ano_plano_acao=2026)
    pa.append(novo)
    d2 = date(2026, 11, 4)
    man2 = pipeline.baixar(cfg, cam, d2, Cliente(BASE, "teste", sessao=SessaoFalsa(dados)))
    pipeline.transformar(cfg, cam, d2, man2)
    al = _ler_mart(cam, "mart_alertas")
    assert {"Troca de banco", "Plano novo"} <= set(al["tipo"])
    serie = _ler_mart(cam, "serie_diaria")
    assert serie["dia"].nunique() == 2

    # rodar de novo no mesmo dia não duplica o histórico
    hist1 = storage.ler(cam.historico / "especiais__planos-acao-especiais")
    pipeline.transformar(cfg, cam, d2, man2)
    hist2 = storage.ler(cam.historico / "especiais__planos-acao-especiais")
    assert len(hist1) == len(hist2) == 31 + 1   # 31 vigentes + 1 versão antiga do plano que trocou de banco

    # CSV sem mudança de ETag não é baixado de novo
    csvm = next(m for m in man2 if m["modulo"] == "discricionarias_csv")
    assert all(c.get("motivo") == "sem mudança (ETag igual)" for c in csvm["cargas"])


def test_csv_em_blocos_latin1():
    import io
    import zipfile
    from custodia.ingest_csv import ler_csv_zip
    txt = 'ID_PROPOSTA;NM_PROPONENTE;VL_REPASSE_PROP;IGNORAR\n"1";"MUNICÍPIO DE SÃO JOSÉ";"1.000,00";"x"\n"2";"AÇAÍLÂNDIA";"5,5";"y"\n'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.csv", txt.encode("latin-1"))
    df = ler_csv_zip(buf.getvalue(), ["id_proposta", "nm_proponente", "vl_repasse_prop"], bloco=1)
    assert list(df.columns) == ["id_proposta", "nm_proponente", "vl_repasse_prop"]
    assert df["nm_proponente"].tolist() == ["MUNICÍPIO DE SÃO JOSÉ", "AÇAÍLÂNDIA"]


def test_csv_proposta_com_ponto_e_virgula_no_endereco():
    import io
    from custodia.ingest_csv import ler_linhas
    cab = ("ID_PROPOSTA;UF_PROPONENTE;MUNIC_PROPONENTE;COD_MUNIC_IBGE;COD_ORGAO_SUP;DESC_ORGAO_SUP;NATUREZA_JURIDICA;"
           "NR_PROPOSTA;DIA_PROP;MES_PROP;ANO_PROP;DIA_PROPOSTA;COD_ORGAO;DESC_ORGAO;MODALIDADE;IDENTIF_PROPONENTE;"
           "NM_PROPONENTE;CEP_PROPONENTE;ENDERECO_PROPONENTE;BAIRRO_PROPONENTE;NM_BANCO;SITUACAO_CONTA;"
           "SITUACAO_PROJETO_BASICO;SIT_PROPOSTA;DIA_INIC_VIGENCIA_PROPOSTA;DIA_FIM_VIGENCIA_PROPOSTA;OBJETO_PROPOSTA;"
           "ITEM_INVESTIMENTO;ENVIADA_MANDATARIA;NOME_SUBTIPO_PROPOSTA;DESCRICAO_SUBTIPO_PROPOSTA;VL_GLOBAL_PROP;"
           "VL_REPASSE_PROP;VL_CONTRAPARTIDA_PROP;CD_AGENCIA;CD_CONTA")
    inicio = "1;MG;ALFA;3100104;56000;MIN CIDADES;Adm Municipal;1/2020;1;2;2020;01/02/2020;56000;MIN CIDADES;CONTRATO DE REPASSE;11111111000101;MUNICIPIO DE ALFA;30000000"
    fim = "SIM;NÃO;;;100;90;10;1234;5678"
    ok = f"{inicio};RUA A, 1;CENTRO;CAIXA ECONOMICA FEDERAL;Registrada;Aprovado;Aprovada;01/03/2020;01/03/2022;PAVIMENTACAO;{fim}"
    ruim = (f"{inicio};RUA B; SALA 2;CENTRO;BANCO DO BRASIL SA;Registrada;Aprovado;Aprovada;01/03/2020;01/03/2022;"
            f"OBRA; FASE 1;{fim}").replace("1;MG", "2;MG", 1)
    quebrada = ok.replace("1;MG", "3;MG", 1).replace("PAVIMENTACAO", "LINHA\nQUEBRADA")
    df, st = ler_linhas(io.StringIO("\n".join([cab, ok, ruim, quebrada]) + "\n"),
                        ["id_proposta", "nm_banco", "bairro_proponente", "objeto_proposta", "cd_conta"])
    assert st["reparadas"] == 1 and st["descartadas"] == 0
    r = df.set_index("id_proposta")
    assert r.loc["2", "nm_banco"] == "BANCO DO BRASIL SA" and r.loc["2", "objeto_proposta"] == "OBRA; FASE 1"
    assert r.loc["2", "cd_conta"] == "5678" and r.loc["3", "nm_banco"] == "CAIXA ECONOMICA FEDERAL"


def test_saldo_interno_e_fonte_interrompida(tmp_path):
    from datetime import date as _d
    from custodia import motores_gestor as mg, saldo_interno
    contas = pd.DataFrame({"modulo": ["Especiais", "Especiais", "Especiais"], "id_instrumento": ["1", "2", "3"],
                           "cnpj_ente": ["a", "b", "c"], "nome_ente": ["A", "B", "C"], "uf": ["MG"] * 3,
                           "grupo_banco": ["CAIXA", "CAIXA", "BB"],
                           "id_agencia_conta": ["4626-574881331", "56-575993745", "4626-16137"],
                           "saldo": [100.0, 200.0, 300.0], "data_saldo": ["2025-04-30", "2025-04-30", "2026-10-20"]})
    pasta = tmp_path / "internos"
    assert saldo_interno.exportar_contas(contas, pasta).exists()
    (pasta / "saldos_caixa_2026-10.csv").write_text(
        "agencia;conta;saldo;data_saldo\n4626;5748813315;1.234,56;30/10/2026\n", "utf-8")
    novo, resumo = saldo_interno.aplicar(contas, pasta)
    assert resumo["contas_substituidas"] == 1
    linha = novo[novo["id_agencia_conta"] == "4626-574881331"].iloc[0]
    assert linha["saldo"] == 1234.56 and linha["data_saldo"] == "2026-10-30" and linha["fonte_saldo"] == "Base interna CAIXA"
    fluxo = pd.DataFrame({"modulo": ["Especiais", "Especiais"], "grupo_origem": ["CAIXA", "BB"],
                          "data": ["2025-04-28", "2026-10-29"], "tipo_movimento": ["pagamento/transferência"] * 2,
                          "cnpj_ente": ["a", "c"], "valor": [10.0, 10.0], "id_agencia_conta": ["x", "y"]})
    paradas = mg.fontes_interrompidas(fluxo, contas, _d(2026, 10, 31))
    assert ("Especiais", "CAIXA") in paradas and ("Especiais", "BB") not in paradas
    # caso real de 01/11: BB publica lançamentos, mas a maioria das contas BB tem saldo com data antiga.
    # A mediana antiga NÃO pode marcar o BB como parado (antes marcava, e a permanência virava 180 dias para todos)
    antigas = pd.DataFrame({"modulo": "Especiais", "id_instrumento": ["9", "10"], "cnpj_ente": ["d", "e"],
                            "nome_ente": ["D", "E"], "uf": "MG", "grupo_banco": "BB",
                            "id_agencia_conta": ["1-1", "1-2"], "saldo": [50.0, 60.0],
                            "data_saldo": ["2024-01-31", "2024-02-29"]})
    paradas2 = mg.fontes_interrompidas(fluxo, pd.concat([contas, antigas], ignore_index=True), _d(2026, 10, 31))
    assert ("Especiais", "BB") not in paradas2 and ("Especiais", "CAIXA") in paradas2
    # banco que NUNCA publicou extrato (contas sem saldo e sem lançamento) não "parou" (BNB nas Especiais, 01/11)
    bnb = pd.DataFrame({"modulo": "Especiais", "id_instrumento": ["11"], "cnpj_ente": ["f"], "nome_ente": ["F"],
                        "uf": "CE", "grupo_banco": "BNB", "id_agencia_conta": ["9-9"], "saldo": [0.0],
                        "data_saldo": [None]})
    assert ("Especiais", "BNB") not in mg.fontes_interrompidas(fluxo, pd.concat([contas, bnb]), _d(2026, 10, 31))
    perm = mg.permanencia(contas, fluxo, {}, paradas)
    assert perm.loc[perm["grupo_banco"] == "CAIXA", "base_permanencia"].str.contains("parou").all()


def test_historico_sem_perda_e_reconstrucao(tmp_path):
    """Três dias com inclusão, alteração, exclusão e linhas idênticas: cada dia reconstruído = fonte do dia."""
    from datetime import date as _d
    from custodia import historico, repositorio
    dias = [_d(2026, 11, 1), _d(2026, 11, 2), _d(2026, 11, 3)]
    fontes = [
        pd.DataFrame({"id_x": [1, 2, 3], "v": [10.0, 20.0, None], "t": ["a", "b", "c"]}),
        pd.DataFrame({"id_x": [1, 2, 4], "v": [10.0, 25.0, 40.0], "t": ["a", "b", "d"]}),       # muda 2, sai 3, entra 4
        pd.DataFrame({"id_x": [1, 4], "v": [10.0, 40.0], "t": ["a", "d"]}),
    ]
    sem_id = [pd.DataFrame({"conta": ["x", "x", "y"], "valor": [1.0, 1.0, 2.0]}),            # linhas idênticas
              pd.DataFrame({"conta": ["x", "y", "y"], "valor": [1.0, 2.0, 2.0]}),
              pd.DataFrame({"conta": ["z"], "valor": [9.0]})]
    dados = tmp_path / "data"
    for dia, f, s in zip(dias, fontes, sem_id):
        ch = historico.escolher_chave(f)
        assert ch == "id_x"
        historico.atualizar(f, ch, dados / "historico" / "t__com_id", dia)
        assert historico.verificar(f, ch, dados / "historico" / "t__com_id", dia)["ok"]
        ch2 = historico.escolher_chave(s)
        assert ch2 == historico.CHAVE_LINHA
        historico.atualizar(s, ch2, dados / "historico" / "t__sem_id", dia)
        assert historico.verificar(s, ch2, dados / "historico" / "t__sem_id", dia)["ok"]
    for dia, f, s in zip(dias, fontes, sem_id):
        pasta = repositorio.reconstruir(dados, dia, tmp_path / f"rec_{dia}")
        r = storage.ler(pasta / "t__com_id").sort_values("id_x").reset_index(drop=True)
        assert r["id_x"].astype(int).tolist() == f["id_x"].tolist()
        assert r["v"].fillna(-1).tolist() == f["v"].fillna(-1).tolist()
        r2 = storage.ler(pasta / "t__sem_id").sort_values(["conta", "valor"]).reset_index(drop=True)
        assert r2.values.tolist() == s.sort_values(["conta", "valor"]).reset_index(drop=True).values.tolist()
    # foto completa mensal: só uma por mês
    (dados / "repositorio" / "fotos" / "2026-11-01").mkdir(parents=True)
    assert not repositorio.deve_fotografar({"foto_completa": "mensal"}, dias[1], False, dados)
    assert repositorio.deve_fotografar({"foto_completa": "mensal"}, _d(2026, 12, 2), False, dados)


def test_auditoria_da_carga(ambiente):
    from custodia import auditoria as au
    assert au.cnpj_valido(pd.Series(["00.000.000/0001-91", "11111111000101", "00000000000191"])).tolist() == [True, False, True]
    cfg, cam = ambiente
    dados = dados_base()
    dia = date(2026, 11, 3)
    man = pipeline.baixar(cfg, cam, dia, Cliente(BASE, "teste", sessao=SessaoFalsa(dados)))
    pipeline.transformar(cfg, cam, dia, man)
    aud = _ler_mart(cam, "mart_auditoria")
    assert set(aud["familia"]) >= {"Completude", "Identificadores", "Integridade", "Frescor", "Reconciliação", "Coerência"}
    rec = aud[(aud["familia"] == "Reconciliação") & aud["checagem"].str.startswith("Instrumentos")]
    assert (rec["status"] == "ok").all(), rec
    assert (aud[aud["familia"] == "Completude"]["status"] != "crítico").all()
    assert (cam.dados / "auditoria" / f"relatorio_{dia}.html").exists()
    # perda de registros na fonte vira alerta no dia seguinte
    dados["especiais"]["planos-acao-especiais"] = dados["especiais"]["planos-acao-especiais"][:20]
    d2 = date(2026, 11, 4)
    man2 = pipeline.baixar(cfg, cam, d2, Cliente(BASE, "teste", sessao=SessaoFalsa(dados)))
    pipeline.transformar(cfg, cam, d2, man2)
    aud2 = _ler_mart(cam, "mart_auditoria")
    queda = aud2[aud2["checagem"] == "Variação contra a carga anterior"]
    assert not queda.empty and (queda["status"] == "crítico").any()


def test_conta_compartilhada_e_zeros_a_esquerda(tmp_path):
    """Saldo da conta entra uma vez (mesmo servindo ao plano e a executores) e casa com agência '0095' = '95'."""
    from custodia import marts
    b = tmp_path / "bruto" / "especiais"
    def grava(ep, linhas):
        storage.gravar(pd.DataFrame(linhas), b / ep / "2026-10-31")
    grava("beneficiarios-especiais", [{"id_beneficiario": 1, "cnpj_beneficiario": "18116137000171",
                                       "nome_beneficiario": "MUNICIPIO X", "uf_beneficiario": "MG"}])
    grava("planos-acao-especiais", [
        {"id_plano_acao": 1, "id_beneficiario": 1, "codigo_banco_plano_acao": "104", "id_agencia_conta": "95-576017788",
         "ano_plano_acao": 2025, "valor_custeio_plano_acao": 0, "valor_investimento_plano_acao": 100.0},
        {"id_plano_acao": 2, "id_beneficiario": 1, "codigo_banco_plano_acao": "104", "id_agencia_conta": "95-576017788",
         "ano_plano_acao": 2025, "valor_custeio_plano_acao": 0, "valor_investimento_plano_acao": 50.0}])
    grava("executores-especiais", [
        {"id_executor": 10, "id_plano_acao": 1, "codigo_banco_executor": "104", "numero_agencia_executor": "95",
         "numero_conta_executor": "576017788", "cnpj_executor": "18116137000171", "nome_executor": "MUNICIPIO X"},
        {"id_executor": 10, "id_plano_acao": 1, "codigo_banco_executor": "104", "numero_agencia_executor": "95",
         "numero_conta_executor": "576017788", "cnpj_executor": "18116137000171", "nome_executor": "MUNICIPIO X"},
        {"id_executor": 11, "id_plano_acao": 2, "codigo_banco_executor": "104", "numero_agencia_executor": "330",
         "numero_conta_executor": "575865224", "cnpj_executor": "18116137000171", "nome_executor": "MUNICIPIO X"}])
    grava("saldo-conta-gestao-financeira-especiais", [
        {"id_agencia_conta": "0095-576017788", "data_saldo_conta": "2025-04-30", "saldo_final_gestao_financeira": 1000.0},
        {"id_agencia_conta": "0330-575865224", "data_saldo_conta": "2025-04-30", "saldo_final_gestao_financeira": 500.0}])
    grava("gestao-financeira-lancamentos-especiais", [
        {"id_lancamento_gestao_financeira": 1, "id_agencia_conta": "0095-576017788", "codigo_banco_gestao_financeira": "104",
         "cnpj_ente_solicitante_gestao_financeira": "18116137000171", "nome_ente_solicitante_gestao_financeira": "MUNICIPIO X",
         "doc_favorecido_gestao_financeira": "18116137000171.0", "nome_favorecido_gestao_financeira": "PREFEITURA",
         "tipo_operacao_gestao_financeira": "D", "valor_gestao_financeira": 10.0,
         "descricao_gestao_financeira": "TED", "data_lancamento_gestao_financeira": "2025-04-01"}])
    out = marts.especiais(tmp_path / "bruto")
    c = out["contas"]
    assert c["saldo"].sum() == pytest.approx(1500.0)                     # nem dobrado, nem perdido
    assert c.loc[c["id_agencia_conta"] == "95-576017788", "saldo"].fillna(0).sum() == pytest.approx(1000.0)
    assert len(out["executores"]) == 2                                   # executor repetido na fonte entra uma vez
    assert bool(out["fluxo"]["proprio_ente"].iloc[0])                   # CNPJ '...171.0' = CNPJ do ente


def test_outras_fontes(ambiente):
    """FUNDEB/FPM (Tesouro), FNS (banco + saldo) e Portal (Educação/Assistência) entram nos marts."""
    cfg, cam = ambiente
    cli = Cliente(BASE, "teste", sessao=SessaoFalsa(dados_base()))
    d1 = date(2026, 11, 3)
    man = pipeline.baixar(cfg, cam, d1, cli)
    pipeline.transformar(cfg, cam, d1, man)
    rep = _ler_mart(cam, "fato_repasse_outros")
    assert {"FUNDEB", "FPM", "FNS", "FNDE", "FNAS"} <= set(rep["fonte"]), rep["fonte"].unique()
    # Saúde vem só do FNS (com banco); o Portal não duplica
    assert rep.loc[rep["fonte"] == "FNS", "valor"].sum() == pytest.approx(1_200_000)
    # Portal: só Educação/Assistência a entes; sem FUNDEB (já vem do Tesouro), sem pagamento a pessoas, sem Saúde
    meses = rep.loc[rep["fonte"] == "FNDE", "mes"].nunique() * rep.loc[rep["fonte"] == "FNDE", "ano"].nunique()
    fnde = rep[rep["fonte"] == "FNDE"]
    assert set(fnde["valor"].round(2)) == {120000.0}, fnde[["detalhe", "valor"]].drop_duplicates()
    assert set(rep.loc[rep["fonte"] == "FNAS", "valor"].round(2)) == {80000.0}
    portal = rep[rep["fonte"].isin(["FNDE", "FNAS"])]
    assert not portal["detalhe"].fillna("").str.contains("FUNDEB|Pé-de-Meia|Bolsa", regex=True).any()
    assert rep["cod_ibge"].astype(str).str.len().eq(7).all()
    contas = _ler_mart(cam, "fato_conta_saude")
    assert set(contas["grupo_banco"]) == {"CAIXA", "BB"}
    assert contas["saldo"].sum() == pytest.approx(3_300_000)
    op = _ler_mart(cam, "mart_oport_saude")
    assert len(op) == 1 and op.iloc[0]["saldo_concorrente"] == pytest.approx(2_500_000)
    mun = _ler_mart(cam, "mart_outras_municipio")
    assert {"fundeb_12m", "saude_12m"} <= set(mun.columns)


def test_auditoria_do_painel(ambiente):
    """Auditoria da camada de entrega: percentuais 0–100%, partes ≤ todo, coerência entre telas, território."""
    from custodia import auditoria_painel as ap, consultas
    cfg, cam = ambiente
    cli = Cliente(BASE, "teste", sessao=SessaoFalsa(dados_base()))
    d1 = date(2026, 11, 3)
    pipeline.transformar(cfg, cam, d1, pipeline.baixar(cfg, cam, d1, cli))
    d = consultas.carregar(consultas.execucao_atual(cam), cam)
    assert not d["mart_auditoria_painel"].empty          # roda dentro da carga
    aud, ex = ap.auditar(d, d1)
    assert (aud["status"] != ap.CRITICO).all(), aud[aud["status"] == ap.CRITICO].to_string()
    print(aud[aud["status"] != ap.OK][["tabela", "checagem", "status", "detalhe"]].to_string())
    assert {"Percentuais", "Partes e todo", "Coerência entre telas", "Território", "Unicidade"} <= set(aud["familia"])
    assert not (aud["checagem"] == "execução da checagem").any()
    # um percentual impossível plantado tem de ser pego
    er = d["mart_ente_resumo"]
    er.loc[er.index[0], "part_caixa"] = 116.48
    # e a alteração NÃO vaza para o dado guardado (cada tela recebe cópia protegida)
    assert d["mart_ente_resumo"]["part_caixa"].max() <= 1
    aud2, ex2 = ap.auditar({**dict(d.items()), "mart_ente_resumo": er}, d1)
    ruim = aud2[(aud2["tabela"] == "mart_ente_resumo") & aud2["checagem"].str.startswith("part_caixa")]
    assert ruim["status"].iloc[0] == ap.CRITICO and not ex2.empty
    arq = ap.gravar(aud2, ex2, cam.dados / "auditoria", "2026-11-03")
    assert arq.exists() and "116.48" in arq.read_text("utf-8")


def test_historico_troca_de_chave_sem_derrubar_carga(tmp_path):
    """Reproduz a falha real de 31/10: histórico gravado com id_executor; a fonte passa a repetir o id e a chave
    vira a linha inteira. Antes: KeyError '_chave_linha' derrubava a carga. Agora: arquiva e segue, sem perda."""
    from custodia import historico, repositorio, storage
    pasta = tmp_path / "historico"
    pasta.mkdir()
    arq = pasta / "especiais__executores-especiais"
    d1, d2 = date(2026, 10, 30), date(2026, 10, 31)
    v1 = pd.DataFrame({"id_executor": [1, 2, 3], "valor": [10.0, 20.0, 30.0]})
    historico.atualizar(v1, "id_executor", arq, d1)
    v2 = pd.DataFrame({"id_executor": [1, 2, 2, 3], "valor": [10.0, 20.0, 25.0, 30.0]})   # id 2 repetido
    r = historico.atualizar(v2, historico.CHAVE_LINHA, arq, d2)
    assert r["novos"] == 4
    assert historico.verificar(v2, historico.CHAVE_LINHA, arq, d2)["ok"]
    arquivados = list(pasta.glob(f"*{historico.ARQUIVO_ATE}*"))
    assert len(arquivados) == 1
    # reconstrução: o dia antigo vem do arquivo arquivado, o novo do histórico atual
    rec1 = storage.ler(repositorio.reconstruir(tmp_path, d1) / "especiais__executores-especiais")
    rec2 = storage.ler(repositorio.reconstruir(tmp_path, d2) / "especiais__executores-especiais")
    assert len(rec1) == 3 and len(rec2) == 4 and rec2["valor"].sum() == 85.0


def test_bloco_com_falha_nao_derruba_a_carga(ambiente, monkeypatch):
    from custodia import motores_gestor
    cfg, cam = ambiente

    def quebra(*a, **k):
        raise ValueError("simulada")
    monkeypatch.setattr(motores_gestor, "janela_escolha", quebra)
    cli = Cliente(BASE, "teste", sessao=SessaoFalsa(dados_base()))
    d1 = date(2026, 11, 3)
    destino = pipeline.transformar(cfg, cam, d1, pipeline.baixar(cfg, cam, d1, cli))
    assert destino.exists() and not _ler_mart(cam, "mart_ente_resumo").empty
    q = _ler_mart(cam, "mart_qualidade")
    assert q["detalhe"].str.contains("mart_janela_escolha").any()


def test_crm_portal_contas_reversas_e_armadilhas(ambiente):
    """CRM com a API do Portal (simulada): confere cada número à mão e as armadilhas plantadas."""
    from custodia import auditoria_painel as ap, consultas, portal_api
    cfg, cam = ambiente
    cli = Cliente(BASE, "teste", sessao=SessaoFalsa(dados_base()))
    d1 = date(2026, 11, 3)
    man = pipeline.baixar(cfg, cam, d1, cli)
    pm = next(m for m in man if m["modulo"] == "portal_api")
    assert pm["resumo"]["falhas"] == 0 and pm["resumo"]["parou"] is None, pm
    pipeline.transformar(cfg, cam, d1, man)
    d = consultas.carregar(consultas.execucao_atual(cam), cam)

    # recebidos: 2 meses × 5 pessoas jurídicas de MG (a pessoa física fica de fora)
    rec = d["crm_recebido"]
    assert len(rec) == 10 and rec["cnpj"].str.len().eq(14).all()
    assert rec["valor"].sum() == pytest.approx(2 * 1_700_000)        # 2º lançamento do FNDE somado; banco fora
    assert not rec["cnpj"].str.startswith("00360305").any()
    qr = d["crm_qualidade"].set_index("conjunto").loc["recursos"]
    assert qr["linhas_agregadas"] == 4 and qr["linhas_de_bancos_excluidas"] == 2 and qr["chaves_conflitantes"] == 0
    cob = d["crm_cobertura"]
    assert cob["ok"].all() and len(cob) == 2 * 27 * 3                 # 2 meses × 27 UFs × 3 tipos
    assert set(rec["mes"]) == {"2026-09", "2026-10"}

    # carteira: recebido = CAIXA conhecido + concorrente conhecido + sem banco (conta reversa)
    cart = d["crm_carteira"].set_index("cnpj")
    assert cart.loc["11111111000101", "recebido_12m"] == pytest.approx(2_100_000)
    assert cart.loc["11111111000101", "educacao_12m"] == pytest.approx(300_000)
    assert (cart["meses_cobertos"] == 2).all()
    assert cart.loc["11111111000101", "constitucionais_12m"] == pytest.approx(1_800_000)
    alfa_fms, beta_fms = cart.loc["11111111000283"], cart.loc["22222222000294"]
    # FNS pagou em 08 e 09; o Portal só tem 09 e 10 carregados: agosto NÃO entra no conhecido (cobertura)
    assert alfa_fms["concorrente_conhecido_12m"] == pytest.approx(300_000)   # FNS na conta BB (só setembro)
    assert beta_fms["caixa_conhecido_12m"] == pytest.approx(300_000)         # FNS na conta CAIXA (só setembro)
    assert beta_fms["sem_banco_12m"] == pytest.approx(300_000)               # outubro: banco desconhecido
    assert not cart["conhecido_excede"].any()
    partes = cart["caixa_conhecido_12m"] + cart["concorrente_conhecido_12m"] + cart["sem_banco_12m"]
    assert (abs(partes - cart["recebido_12m"]) < 0.01).all()
    assert cart["recebido_12m"].sum() == pytest.approx(rec["valor"].sum())

    # emendas: "- 26.002,00" vira -26002 (não zero); documentos ligam parlamentar → ente
    em = d["crm_emenda"]
    assert len(em) == 3 and em["codigo"].is_unique
    pag = d["crm_emenda_pagamento"]
    assert set(pag["codigo_documento"]) == {"OB1", "OB2", "OB3", "OB4"}
    assert pag["doc_favorecido"].str.len().eq(14).all()          # CNPJ formatado da API vira 14 dígitos
    s = pag.groupby("autor")["valor_pago_doc"].sum()
    assert s["DEP FULANO"] == pytest.approx(300_000) and s["BANCADA DE MG"] == pytest.approx(100_000)
    assert portal_api.num_br("- 26.002,00") == -26002.0
    # OB2 paga duas emendas: rateio pelo que falta pagar em cada uma; a soma do documento = valor da ordem
    ob2 = pag[pag["codigo_documento"] == "OB2"]
    assert len(ob2) == 2 and ob2["compartilhado"].all()
    assert ob2["valor_pago_doc"].sum() == pytest.approx(100_000)
    assert pag.groupby("codigo_emenda")["valor_pago_doc"].sum().max() <= 300_000 + 0.01
    # nenhum CPF entra nas sanções (o campo 'sancionado' da API traz CPF completo)
    sanc = d["crm_sancao"]
    assert sanc["cnpj"].str.len().eq(14).all() and "FULANO DE TAL" not in set(sanc["nome"])
    rede = d["crm_rede"]
    assert {"parlamentar", "ente", "fornecedor"} <= set(rede["origem_tipo"])

    # presença CAIXA: Alfa com Bolsa Família (R$ 150 mil, 220 famílias)
    pres = d["crm_presenca"].set_index("cod_ibge")
    assert pres.loc["3100104", "bolsa_familia_mes"] == pytest.approx(150_000)

    # conformidade: construtora sancionada paga durante a sanção; associação no CEPIM recebendo
    al = d["crm_alertas"]
    assert "88888888000188" in set(al.loc[al["regra"] == "CON-01", "cnpj"])
    assert "55555555000155" in set(al.loc[al["regra"] == "CON-02", "cnpj"])

    # auditoria: aponta a emenda com pago > liquidado e não acusa contas reversas
    aud, ex = ap.auditar(d, d1)
    crm = aud[aud["familia"] == "CRM"]
    assert crm.loc[crm["checagem"] == "empenhado ≥ liquidado ≥ pago", "valor"].iloc[0] == 1
    for chk in ("Σ por mês = Σ por ente = Σ por UF = total", "Σ carteira 12m = Σ recebidos dos 12 meses (conta reversa)",
                "recebido = CAIXA + concorrente + sem banco", "só pessoas jurídicas (nenhum CPF)",
                "campos obrigatórios recebidos da API", "Σ pagamentos dos documentos ≤ valor pago da emenda",
                "ordem paga a várias emendas: Σ rateio = valor da ordem"):
        assert crm.loc[crm["checagem"] == chk, "status"].iloc[0] == ap.OK, (chk, crm[crm["checagem"] == chk].to_dict("records"))
    assert (aud["familia"] == "Conformidade").sum() >= 2

    # segunda carga no mesmo dia: nada é baixado de novo, nada duplica
    man2 = pipeline.baixar(cfg, cam, d1, cli)
    pm2 = next(m for m in man2 if m["modulo"] == "portal_api")
    assert pm2["resumo"]["unidades_baixadas"] == 0
    pipeline.transformar(cfg, cam, d1, man2)
    d2 = consultas.carregar(consultas.execucao_atual(cam), cam)
    assert len(d2["crm_recebido"]) == 10 and d2["crm_recebido"]["valor"].sum() == pytest.approx(rec["valor"].sum())


def test_portal_api_chave_recusada_para_tudo(tmp_path, monkeypatch):
    """Chave recusada (401): para na hora, sem insistir (insistir suspende a chave)."""
    from custodia import portal_api
    monkeypatch.setenv("PORTAL_API_CHAVE", "errada")
    sess = SessaoFalsa(dados_base())
    cfg = {"ativo": True, "intervalo_fixo": 0, "recursos": {"meses": 1}}
    man = portal_api.carregar(cfg, "t", tmp_path / "bruto", tmp_path, date(2026, 11, 3), sessao=sess, municipios=[])
    assert man["resumo"]["parou"] and "chave" in man["resumo"]["parou"].lower()
    assert man["resumo"]["chamadas"] == 1


def test_crm_atividades_e_agenda(tmp_path):
    from custodia import acesso
    db = tmp_path / "carteira.db"
    acesso.registrar_atividade("11111111000101", "Visita", "2026-10-01", "Apresentação", "Enviar proposta",
                               "2026-10-10", "Ana", "ana", db)
    acesso.registrar_atividade("11111111000101", "Proposta", "2026-10-09", "Proposta enviada", "Cobrar retorno",
                               "2026-10-20", "Ana", "ana", db)
    acesso.registrar_atividade("22222222000294", "Ligação", "2026-10-05", "Sem interesse agora", "", None, "Bia", "bia", db)
    at = acesso.atividades(db=db)
    assert len(at) == 3                                       # nada é sobrescrito
    ag = acesso.agenda(db)
    assert ag["cnpj_ente"].tolist() == ["11111111000101"]     # um compromisso vigente por ente: o da última atividade
    assert ag.iloc[0]["proxima_acao"] == "Cobrar retorno"
    with pytest.raises(ValueError):
        acesso.registrar_atividade("123", "Visita", "2026-10-01", "", "", None, "Ana", "ana", db)
    with pytest.raises(ValueError):
        acesso.registrar_atividade("11111111000101", "Festa", "2026-10-01", "", "", None, "Ana", "ana", db)
    with pytest.raises(ValueError):
        acesso.registrar_atividade("11111111000101", "Visita", "31/10/2026", "", "", None, "Ana", "ana", db)
