"""API falsa com o mesmo contrato do Transferegov (paginação, envelope, openapi, CSV em zip)."""
from __future__ import annotations

import copy
import io
import json
from datetime import date
import math
import zipfile
from urllib.parse import parse_qs, urlparse

import requests

BASE = "https://api-publica.transferegov.gestao.gov.br"


def dados_base():
    ben = [
        {"id_beneficiario": 1, "uf_beneficiario": "MG", "nome_beneficiario": "MUNICIPIO DE ALFA", "cnpj_beneficiario": "11111111000101", "id_ente": 10},
        {"id_beneficiario": 2, "uf_beneficiario": "MG", "nome_beneficiario": "MUNICIPIO DE BETA", "cnpj_beneficiario": "22222222000102", "id_ente": 20},
        {"id_beneficiario": 3, "uf_beneficiario": "RS", "nome_beneficiario": "MUNICIPIO DE GAMA", "cnpj_beneficiario": "33333333000103", "id_ente": 30},
        {"id_beneficiario": 4, "uf_beneficiario": "BA", "nome_beneficiario": "MUNICIPIO DE DELTA", "cnpj_beneficiario": "44444444000104", "id_ente": 40},
        {"id_beneficiario": 5, "uf_beneficiario": "BA", "nome_beneficiario": "ESTADO DA BAHIA", "cnpj_beneficiario": "55555555000105", "id_ente": 50},
    ]
    planos, execs, saldos, emps, dhs, obs = [], [], [], [], [], []
    bancos = {1: "104", 2: "001", 3: "104", 4: "001", 5: "004"}
    pid = 100
    for ano in (2024, 2025):
        for b in ben:
            for k in range(3):
                pid += 1
                banco = bancos[b["id_beneficiario"]]
                if b["id_beneficiario"] == 2 and ano == 2025 and k == 0:
                    banco = "104"  # Beta vira multibanco
                if b["id_beneficiario"] == 5 and ano == 2024:
                    banco = "104"  # Estado da Bahia: CAIXA em 2024, BNB em 2025 (ente perdido)
                sit = "CIENTE"
                if k == 2 and ano == 2025 and b["id_beneficiario"] in (3, 4):
                    banco, sit = None, ("IMPEDIDO" if b["id_beneficiario"] == 3 else "AGUARDANDO_CIENCIA")
                ag, ct = 1000 + pid, 500000 + pid
                planos.append({
                    "id_plano_acao": pid, "codigo_plano_acao": f"0903{ano}-{pid:06d}", "ano_plano_acao": ano,
                    "modalidade_plano_acao": "Especial", "situacao_plano_acao": sit,
                    "data_aceite_plano_acao": f"{ano}-08-07" if banco else None,
                    "codigo_banco_plano_acao": banco,
                    "nome_banco_plano_acao": {"104": "Caixa Econômica Federal", "001": "Banco do Brasil", "004": "Banco do Nordeste"}.get(banco),
                    "descricao_situacao_dado_bancario_plano_acao": "Conta Ativa" if banco else None,
                    "numero_agencia_plano_acao": str(ag) if banco else None,
                    "numero_conta_plano_acao": str(ct) if banco else None,
                    "id_agencia_conta": f"{ag}-{ct}" if banco else None,
                    "nome_parlamentar_emenda_plano_acao": ["Fulano", "Beltrana", "Sicrano"][k],
                    "valor_custeio_plano_acao": 0.0, "valor_investimento_plano_acao": 100000.0 * (k + 1) * b["id_beneficiario"],
                    "id_beneficiario": b["id_beneficiario"], "nome_objeto": "Pavimentação", "id_programa": ano - 2000,
                })
                if banco:
                    saldos.append({"id_agencia_conta": f"{ag}-{ct}", "agencia_batch": ag, "conta_batch": ct,
                                   "data_saldo_conta": "2026-10-20",
                                   "saldo_final_gestao_financeira": 50000.0 * (k + 1) * b["id_beneficiario"]})
                    eb = banco
                    if b["id_beneficiario"] == 1 and k == 1:
                        eb = "001"  # vazamento: plano CAIXA, executor BB
                    execs.append({"id_executor": pid * 10, "cnpj_executor": b["cnpj_beneficiario"],
                                  "nome_executor": b["nome_beneficiario"], "codigo_banco_executor": eb.lstrip("0"),
                                  "nome_banco_executor": "x", "numero_agencia_executor": str(2000 + pid),
                                  "numero_conta_executor": str(700000 + pid),
                                  "descricao_situacao_dado_bancario_executor": "Conta Ativa",
                                  "ind_recursos_gerenciados_conta_especifica_executor": "Não",
                                  "vl_custeio_executor": 0.0, "vl_investimento_executor": 100000.0 * (k + 1),
                                  "id_plano_acao": pid})
                    emps.append({"id_empenho": pid * 7, "valor_empenho": 90000.0, "data_emissao_empenho": f"{ano}-09-01",
                                 "id_plano_acao": pid, "descricao_situacao_empenho": "Enviado"})
                    if k == 0:
                        dhs.append({"id_dh": pid * 3, "valor_dh": 90000.0, "id_empenho": pid * 7})
                        obs.append({"id_op_ob": pid * 5, "numero_ordem_bancaria": f"2025OB{pid}", "id_dh": pid * 3, "data_emissao_ob": f"{ano}-10-16"})
    fin, rgn, dls, lancs = [], [], [], []
    nomes = {b["id_beneficiario"]: (b["nome_beneficiario"], b["cnpj_beneficiario"]) for b in ben}
    for i, p in enumerate(planos):
        if not p["codigo_banco_plano_acao"]:
            continue
        fin.append({"id_executor": p["id_plano_acao"] * 10, "cd_area_politica_publica_tipo_pt": 15,
                    "area_politica_publica_tipo_pt": "Urbanismo" if i % 2 else "Saúde",
                    "cd_area_politica_publica_pt": 451, "area_politica_publica_pt": "Infraestrutura Urbana"})
        rgn.append({"id_relatorio_gestao_novo": p["id_plano_acao"], "id_plano_acao": p["id_plano_acao"],
                    "id_executor": p["id_plano_acao"] * 10})
        dls.append({"id_relatorio_gestao_dl": p["id_plano_acao"], "id_relatorio_gestao_novo": p["id_plano_acao"],
                    "tp_doc_recebedor_relatorio_gestao_dl": "CNPJ",
                    "tx_identificacao_recebedor_mascarado_relatorio_gestao_dl": "88888888000188",
                    "tx_nome_recebedor_relatorio_gestao_dl": "CONSTRUTORA EXEMPLO LTDA",
                    "tx_natureza_relatorio_gestao_dl": "INVESTIMENTO", "vl_pagamento_relatorio_gestao_dl": 50000.0,
                    "dt_pagamento_relatorio_gestao_dl": "2025-09-10"})
        nome, cnpj = nomes[p["id_beneficiario"]]
        orig = int(p["codigo_banco_plano_acao"])
        base = {"id_agencia_conta": p["id_agencia_conta"], "codigo_banco_gestao_financeira": orig,
                "cnpj_ente_solicitante_gestao_financeira": cnpj, "nome_ente_solicitante_gestao_financeira": nome,
                "tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 2}
        lancs.append(dict(base, id_lancamento_gestao_financeira=f"{orig}-{i}a", descricao_gestao_financeira="TED Transf.Eletr.Disponivel",
                          codigo_banco_favorecido_gestao_financeira=1, nome_favorecido_gestao_financeira="CONSTRUTORA EXEMPLO LTDA",
                          doc_favorecido_gestao_financeira="88888888000188",
                          valor_gestao_financeira=40000.0, data_lancamento_gestao_financeira="2025-09-10"))
        lancs.append(dict(base, id_lancamento_gestao_financeira=f"{orig}-{i}b", descricao_gestao_financeira="BB-APLIC C.PRZ-APL.AUT",
                          codigo_banco_favorecido_gestao_financeira=0, nome_favorecido_gestao_financeira="",
                          valor_gestao_financeira=10000.0, data_lancamento_gestao_financeira="2025-09-11"))
        if orig == 1 and i % 3 == 0:  # saída da conta BB para conta do próprio ente na CAIXA, após a portaria
            lancs.append(dict(base, id_lancamento_gestao_financeira=f"{orig}-{i}c", descricao_gestao_financeira="Transferência enviada",
                              codigo_banco_favorecido_gestao_financeira=104, nome_favorecido_gestao_financeira=nome,
                              valor_gestao_financeira=5000.0, data_lancamento_gestao_financeira="2025-10-01"))
        lancs.append(dict(base, id_lancamento_gestao_financeira=f"{orig}-{i}d", tipo_operacao_gestao_financeira="C",
                          descricao_gestao_financeira="Crédito", codigo_banco_favorecido_gestao_financeira=0,
                          nome_favorecido_gestao_financeira="", valor_gestao_financeira=99.0,
                          data_lancamento_gestao_financeira="2025-09-01"))
    faf_pa, faf_db = [], []
    for i, (cnpj, nome, uf, ibge) in enumerate([("11111111000101", "MUNICIPIO DE ALFA", "MG", 3100104),
                                                 ("33333333000103", "MUNICIPIO DE GAMA", "RS", 4300034)], 1):
        faf_pa.append({"id_plano_acao": i, "codigo_plano_acao": f"FAF-{i}", "data_inicio_vigencia_plano_acao": "2025-03-01",
                       "situacao_plano_acao": "EM_EXECUCAO", "valor_total_repasse_plano_acao": 250000.0 * i,
                       "cnpj_ente_recebedor_plano_acao": cnpj, "nome_ente_recebedor_plano_acao": nome,
                       "uf_ente_recebedor_plano_acao": uf, "codigo_ibge_municipio_ente_recebedor_plano_acao": ibge,
                       "id_programa": 7})
        faf_db.append({"id_plano_acao_dado_bancario": i, "id_agencia_conta": f"{4200 + i}-{7000 + i}",
                       "codigo_banco_plano_acao_dado_bancario": "001", "nome_banco_plano_acao_dado_bancario": "Banco do Brasil",
                       "numero_agencia_plano_acao_dado_bancario": str(4200 + i), "numero_conta_plano_acao_dado_bancario": str(7000 + i),
                       "situacao_conta_plano_acao_dado_bancario": "Conta Ativa",
                       "data_abertura_conta_plano_acao_dado_bancario": "2025-03-02",
                       "saldo_final_dado_bancario": {"saldo_final_gestao_financeira": 1500000.0 * i},
                       "id_plano_acao": i})
    return {
        "especiais": {
            "programas-especiais": [{"id_programa": 24, "ano_programa": 2024}, {"id_programa": 25, "ano_programa": 2025}],
            "beneficiarios-especiais": ben,
            "planos-acao-especiais": planos,
            "executores-especiais": execs,
            "saldo-conta-gestao-financeira-especiais": saldos,
            "empenhos-especiais": emps,
            "documentos-habeis-especiais": dhs,
            "ordens-pagamentos-ordens-bancarias-especiais": obs,
            "planos-trabalho-especiais": [],
            "devolucao-especiais": [],
            "gestao-financeira-subtransacoes-especiais": [],
            "finalidade-especiais": fin,
            "relatorios-gestao-novos-especiais": rgn,
            "relatorios-gestao-documento-liquidacao-especiais": dls,
            "gestao-financeira-lancamentos-especiais": lancs,
        },
        "fundoafundo": {
            "programas": [{"id_programa": 7, "nome_programa": "PNAB", "ano_programa": 2025,
                           "sigla_orgao_superior_programa": "MinC", "nome_orgao_superior_programa": "Ministério da Cultura"}],
            "planos-acao": faf_pa,
            "planos-acao-dados-bancarios": faf_db,
            "empenhos": [], "termos-adesao": [], "programas-beneficiarios": [],
            "gestao-financeira-lancamentos": [
                {"id_lancamento_gestao_financeira": 9001, "id_agencia_conta": "4201-7001", "codigo_banco_gestao_financeira": "001",
                 "cnpj_ente_solicitante_gestao_financeira": "11111111000101", "nome_ente_solicitante_gestao_financeira": "MUNICIPIO DE ALFA",
                 "tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 2, "descricao_gestao_financeira": "Transferência enviada",
                 "doc_favorecido_gestao_financeira_mask": "11111111000101", "nome_favorecido_gestao_financeira": "MUNICIPIO DE ALFA",
                 "valor_lancamento_gestao_financeira": 120000.0, "data_lancamento_gestao_financeira": "2026-03-10"},
                {"id_lancamento_gestao_financeira": 9002, "id_agencia_conta": "4202-7002", "codigo_banco_gestao_financeira": "001",
                 "cnpj_ente_solicitante_gestao_financeira": "33333333000103", "nome_ente_solicitante_gestao_financeira": "MUNICIPIO DE GAMA",
                 "tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 2, "descricao_gestao_financeira": "TED",
                 "doc_favorecido_gestao_financeira_mask": "33333333000103", "nome_favorecido_gestao_financeira": "MUNICIPIO DE GAMA",
                 "valor_lancamento_gestao_financeira": 80000.0, "data_lancamento_gestao_financeira": "2024-01-05"},
                {"id_lancamento_gestao_financeira": 9003, "id_agencia_conta": "4202-7002", "codigo_banco_gestao_financeira": "001",
                 "cnpj_ente_solicitante_gestao_financeira": "33333333000103", "nome_ente_solicitante_gestao_financeira": "MUNICIPIO DE GAMA",
                 "tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 2, "descricao_gestao_financeira": "TED",
                 "doc_favorecido_gestao_financeira_mask": "77777777000177", "nome_favorecido_gestao_financeira": "PRODUTORA CULTURAL LTDA",
                 "valor_lancamento_gestao_financeira": 30000.0, "data_lancamento_gestao_financeira": "2026-02-01"},
                {"id_lancamento_gestao_financeira": 9004, "id_agencia_conta": "4202-7002", "codigo_banco_gestao_financeira": "001",
                 "cnpj_ente_solicitante_gestao_financeira": "33333333000103", "nome_ente_solicitante_gestao_financeira": "MUNICIPIO DE GAMA",
                 "tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 1, "descricao_gestao_financeira": "TED",
                 "doc_favorecido_gestao_financeira_mask": "***123***", "nome_favorecido_gestao_financeira": "PESSOA FISICA",
                 "valor_lancamento_gestao_financeira": 999.0, "data_lancamento_gestao_financeira": "2026-02-01"}],
            "planos-acao-destinacao-recursos": [
                {"id_destinacao_recursos_plano_acao": 1, "id_plano_acao": 1, "tipo_despesa_destinacao_recursos_plano_acao": "CUSTEIO",
                 "descricao_natureza_despesa_destinacao_recursos_plano_acao": "PREMIAÇÕES CULTURAIS", "valor_destinacao_recursos_plano_acao": 250000.0}],
            "gestao-financeira-subtransacoes": [
                {"id_subtransacao_gestao_financeira": "1-1", "id_lancamento_gestao_financeira": 9003,
                 "descricao_situacao_pagamento_subtransacao_gestao_financeira": "Pago",
                 "descricao_tp_pessoa_beneficiario_subtransacao_gestao_financeira": "CNPJ",
                 "doc_beneficiario_subtransacao_gestao_financeira_mask": "77777777000177",
                 "nome_beneficiario_subtransacao_gestao_financeira": "PRODUTORA CULTURAL LTDA",
                 "valor_subtransacao_gestao_financeira": 80000.0, "data_pagamento_subtransacao_gestao_financeira": "2025-05-02"},
                {"id_subtransacao_gestao_financeira": "1-2", "id_lancamento_gestao_financeira": 9003,
                 "descricao_situacao_pagamento_subtransacao_gestao_financeira": "Pago",
                 "descricao_tp_pessoa_beneficiario_subtransacao_gestao_financeira": "CPF",
                 "doc_beneficiario_subtransacao_gestao_financeira_mask": "***123***",
                 "nome_beneficiario_subtransacao_gestao_financeira": "PESSOA FISICA", "valor_subtransacao_gestao_financeira": 5000.0,
                 "data_pagamento_subtransacao_gestao_financeira": "2025-05-02"}],
        },
    }


def _zip_csv(linhas: list[dict]) -> bytes:
    cab = list(linhas[0].keys())
    txt = ";".join(c.upper() for c in cab) + "\n" + "\n".join(";".join(f'"{r[c]}"' for c in cab) for r in linhas)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dados.csv", txt.encode("utf-8"))
    return buf.getvalue()


CSVS = {
    # mesmas colunas dos arquivos reais (verificadas em 31/10/2026); proposta NÃO tem CD_BANCO
    "siconv_convenio.zip": _zip_csv([
        {"nr_convenio": "900001", "id_proposta": "1", "ano": "2024", "dia_assin_conv": "15/03/2024", "sit_convenio": "Em execução",
         "instrumento_ativo": "SIM", "dia_fim_vigenc_conv": "15/03/2027", "vl_global_conv": "1.300.000,00",
         "vl_repasse_conv": "1.250.000,50", "vl_desembolsado_conv": "600000", "vl_saldo_conta": "450.000,00", "vl_rendimento_aplicacao": "1200,5"},
        {"nr_convenio": "900002", "id_proposta": "2", "ano": "2025", "dia_assin_conv": "20/06/2025", "sit_convenio": "Em execução",
         "instrumento_ativo": "SIM", "dia_fim_vigenc_conv": "20/06/2027", "vl_global_conv": "320000",
         "vl_repasse_conv": "300000,00", "vl_desembolsado_conv": "300000", "vl_saldo_conta": "250000", "vl_rendimento_aplicacao": ""},
        {"nr_convenio": "700003", "id_proposta": "3", "ano": "2012", "dia_assin_conv": "01/02/2012", "sit_convenio": "Prestação de Contas Aprovada",
         "instrumento_ativo": "NÃO", "dia_fim_vigenc_conv": "01/02/2014", "vl_global_conv": "100000",
         "vl_repasse_conv": "90000", "vl_desembolsado_conv": "90000", "vl_saldo_conta": "0", "vl_rendimento_aplicacao": ""},
    ]),
    "siconv_proposta.zip": _zip_csv([
        {"id_proposta": "1", "uf_proponente": "MG", "cod_munic_ibge": "3100104", "cod_orgao_sup": "56000", "desc_orgao_sup": "MINISTÉRIO DAS CIDADES",
         "desc_orgao": "MINISTERIO DAS CIDADES", "identif_proponente": "11111111000101", "nm_proponente": "MUNICIPIO DE ALFA",
         "nm_banco": "CAIXA ECONOMICA FEDERAL", "natureza_juridica": "Administração Pública Municipal", "modalidade": "CONTRATO DE REPASSE"},
        {"id_proposta": "2", "uf_proponente": "BA", "cod_munic_ibge": "2900108", "cod_orgao_sup": "36000", "desc_orgao_sup": "MINISTÉRIO DA SAÚDE",
         "desc_orgao": "FUNDO NACIONAL DE SAUDE", "identif_proponente": "44444444000104", "nm_proponente": "MUNICIPIO DE DELTA",
         "nm_banco": "BANCO DO BRASIL SA", "natureza_juridica": "Administração Pública Municipal", "modalidade": "CONVENIO"},
        {"id_proposta": "3", "uf_proponente": "MG", "cod_munic_ibge": "3100203", "cod_orgao_sup": "56000", "desc_orgao_sup": "MINISTÉRIO DAS CIDADES",
         "desc_orgao": "MINISTERIO DAS CIDADES", "identif_proponente": "22222222000102", "nm_proponente": "MUNICIPIO DE BETA",
         "nm_banco": "CAIXA ECONOMICA FEDERAL", "natureza_juridica": "Administração Pública Municipal", "modalidade": "CONTRATO DE REPASSE"},
    ]),
    "siconv_emenda.zip": _zip_csv([
        {"id_proposta": "1", "nr_emenda": "202400010001", "nome_parlamentar": "FULANO", "tipo_parlamentar": "INDIVIDUAL",
         "ind_impositivo": "SIM", "valor_repasse_emenda": "1250000,50", "beneficiario_emenda": "11111111000101"},
        {"id_proposta": "2", "nr_emenda": "202500020001", "nome_parlamentar": "BELTRANA", "tipo_parlamentar": "INDIVIDUAL",
         "ind_impositivo": "SIM", "valor_repasse_emenda": "300000", "beneficiario_emenda": "44444444000104"},
        {"id_proposta": "", "nr_emenda": "201000030001", "nome_parlamentar": "SEM PROPOSTA", "tipo_parlamentar": "BANCADA",
         "ind_impositivo": "NÃO", "valor_repasse_emenda": "", "beneficiario_emenda": ""},
    ]),
    "siconv_desembolso.zip": _zip_csv([{"nr_convenio": "900001", "vl_desembolsado": "1000,00"}]),
}


class Resp:
    def __init__(self, status=200, corpo=b"", ctype="application/json"):
        self.status_code = status
        self.content = corpo
        self.headers = {"content-type": ctype}

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)

    def iter_content(self, tamanho):
        for i in range(0, len(self.content), tamanho):
            yield self.content[i:i + tamanho]


class SessaoFalsa(requests.Session):
    def __init__(self, dados=None, falhas: int = 0):
        super().__init__()
        self.dados = dados or dados_base()
        self.falhas = falhas  # primeiras N chamadas devolvem 503 (testa novas tentativas)
        self.chamadas = 0

    def get(self, url, params=None, timeout=None, stream=False, **kw):
        self.chamadas += 1
        if self.falhas > 0:
            self.falhas -= 1
            return Resp(503, b"{}")
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        q.update({k: str(v) for k, v in (params or {}).items()})
        partes = u.path.strip("/").split("/")
        if "apiapex.tesouro.gov.br" in url:
            if url.endswith("/estados"):
                return Resp(200, json.dumps({"registros": [{"codigo": 11, "nome": "Minas Gerais"}]}).encode())
            if int(q.get("page", 1)) > 1:
                return Resp(200, json.dumps({"registros": []}).encode())
            reg = []
            for mes in (8, 9):
                for cod, nome, siafi, v in ((3100104, "Alfa", 4001, 900000.0), (3100203, "Beta", 4003, 1500000.0)):
                    reg += [{"UF": "MG", "ANO": str(q.get("p_ano")), "TRANSFERENCIA": "FUNDEB", "codigo_siafi": siafi,
                             "CO_IBGE": cod, "MES": f"{mes:02d}", "MUNICIPIO": nome, "VALOR": v},
                            {"UF": "MG", "ANO": str(q.get("p_ano")), "TRANSFERENCIA": "FPM", "codigo_siafi": siafi,
                             "CO_IBGE": cod, "MES": f"{mes:02d}", "MUNICIPIO": nome, "VALOR": v * 2}]
            return Resp(200, json.dumps({"registros": reg, "next": "x"}).encode())
        if "consultafns.saude.gov.br" in url:
            vazio = {"resultado": {"dados": [], "total": 0}}
            rec = partes[-1]
            if rec == "entidades":
                dados = [] if q.get("estado") != "MG" else [
                    {"uf": "MG", "municipio": "ALFA", "cpfCnpj": "11111111000283", "razaoSocial": "FUNDO MUNICIPAL DE SAUDE",
                     "codigoMunicipioIBGE": "310010", "esferaAdministrativa": "MUNICIPAL"},
                    {"uf": "MG", "municipio": "BETA", "cpfCnpj": "22222222000294", "razaoSocial": "FUNDO MUNICIPAL DE SAUDE",
                     "codigoMunicipioIBGE": "310020", "esferaAdministrativa": "MUNICIPAL"},
                    {"uf": "MG", "municipio": "ALFA", "cpfCnpj": "99999999000199", "razaoSocial": "CLINICA X",
                     "codigoMunicipioIBGE": "310010", "esferaAdministrativa": "PRIVADA"}]
                return Resp(200, json.dumps({"resultado": {"dados": dados, "total": len(dados)}}).encode())
            if rec == "detalhe-conta":
                b = "001" if q.get("cpfCnpjUg") == "11111111000283" else "104"
                d = [{"anoPagamento": "2026", "codigoBanco": b, "codigoAgencia": "001234", "codigoBloco": 10,
                      "contaCorrente": f"00009{q.get('cpfCnpjUg')[:4]}"},
                     {"anoPagamento": "2026", "codigoBanco": b, "codigoAgencia": "001234", "codigoBloco": 8,
                      "contaCorrente": ""}]
                return Resp(200, json.dumps({"resultado": {"dados": d, "total": 2}}).encode())
            if rec == "detalhe-pagamento":
                b = "001" if q.get("cpfCnpjUg") == "11111111000283" else "104"
                d = [{"anoPagamento": "2026", "mesPagamento": m, "uf": "MG", "codigoBanco": b, "codigoAgencia": "001234",
                      "contaCorrente": f"00009{q.get('cpfCnpjUg')[:4]}", "valorLiquido": 300000.0, "valorTotal": 300000.0,
                      "nomeBloco": "Manutenção das Ações e Serviços Públicos de Saúde"} for m in ("08", "09")]
                return Resp(200, json.dumps({"resultado": {"dados": d, "total": 2}}).encode())
            if rec == "ultimo-saldo":
                v = 2500000.0 if q.get("banco") == "001" else 800000.0
                return Resp(200, json.dumps({"resultado": {"dados": [{"valorTotal": v, "dataSaldoFormatada": "31/08/2026"}],
                                                           "total": 1}}).encode())
            return Resp(200, json.dumps(vazio).encode())
        if "api.portaldatransparencia.gov.br" in url:
            return self._portal_api(u.path, q)
        if "portaldatransparencia.gov.br" in url:
            import io as _io
            import zipfile as _zip
            # layout do dicionário oficial (portaldatransparencia.gov.br/dicionario-de-dados/recursos-transferidos)
            cab = ["ANO / MÊS", "TIPO TRANSFERÊNCIA", "TIPO FAVORECIDO", "UF", "CÓDIGO MUNICÍPIO SIAFI", "NOME MUNICÍPIO",
                   "CÓDIGO ÓRGÃO SIAFI", "NOME ÓRGÃO", "CÓDIGO UNIDADE GESTORA", "NOME UNIDADE GESTORA", "CÓDIGO FUNÇÃO",
                   "NOME FUNÇÃO", "CÓDIGO SUBFUNÇÃO", "NOME SUBFUNÇÃO", "CÓDIGO PROGRAMA", "NOME PROGRAMA", "CÓDIGO AÇÃO",
                   "NOME AÇÃO", "LINGUAGEM CIDADÃ", "CÓDIGO FAVORECIDO", "NOME FAVORECIDO", "VALOR TRANSFERIDO"]

            def lin(tipo, fav, uf, siafi, mun, orgao, funcao, acao, doc, nome, valor):
                d = dict.fromkeys(cab, "")
                d.update({"ANO / MÊS": partes[-1], "TIPO TRANSFERÊNCIA": tipo, "TIPO FAVORECIDO": fav, "UF": uf,
                          "CÓDIGO MUNICÍPIO SIAFI": siafi, "NOME MUNICÍPIO": mun, "NOME ÓRGÃO": orgao,
                          "NOME FUNÇÃO": funcao, "NOME AÇÃO": acao, "CÓDIGO FAVORECIDO": doc, "NOME FAVORECIDO": nome,
                          "VALOR TRANSFERIDO": valor})
                return ";".join(d[c] for c in cab)
            linhas = [
                lin("Legais", "Administração Pública", "MG", "4001", "ALFA", "Fundo Nacional de Desenvolvimento da Educação",
                    "Educação", "Apoio à Alimentação Escolar na Educação Básica (PNAE)", "11111111000101", "MUNICIPIO DE ALFA", "120.000,00"),
                lin("Legais", "Administração Pública", "MG", "4003", "BETA", "Fundo Nacional de Assistência Social",
                    "Assistência social", "Proteção Social Básica", "22222222000102", "MUNICIPIO DE BETA", "80.000,00"),
                lin("Legais", "Administração Pública", "MG", "4001", "ALFA", "Fundo Nacional de Saúde", "Saúde", "MAC",
                    "11111111000283", "FMS ALFA", "999,00"),
                # devem ficar de fora: complementação do FUNDEB (já vem do Tesouro) e pagamento direto a pessoas
                lin("Constitucionais e Royalties", "Administração Pública", "MG", "4001", "ALFA", "Ministério da Educação",
                    "Educação", "Complementação da União ao Fundo de Manutenção e Desenvolvimento da Educação Básica (FUNDEB)",
                    "11111111000101", "MUNICIPIO DE ALFA", "5.000.000,00"),
                lin("Direta ao Cidadão", "Pessoa Física", "MG", "4001", "ALFA", "Ministério da Educação", "Educação",
                    "Pé-de-Meia", "***.123.456-**", "ESTUDANTE", "1.000,00"),
                lin("Direta ao Cidadão", "Pessoa Física", "MG", "4003", "BETA", "Ministério do Desenvolvimento Social",
                    "Assistência social", "Bolsa Família", "***.654.321-**", "BENEFICIARIO", "600,00"),
            ]
            csv = ";".join(f'"{c}"' for c in cab) + "\n" + "\n".join(linhas) + "\n"
            buf = _io.BytesIO()
            with _zip.ZipFile(buf, "w") as z:
                z.writestr(f"{partes[-1]}_Transferencias.csv", csv.encode("latin-1", errors="replace"))
            return Resp(200, buf.getvalue(), "application/zip")
        if "siconfi" in url:
            return Resp(200, json.dumps({"items": [
                {"cod_ibge": 3100104, "ente": "Alfa", "uf": "MG", "esfera": "M", "populacao": 12000, "cnpj": "11111111000101"},
                {"cod_ibge": 3100203, "ente": "Beta", "uf": "MG", "esfera": "M", "populacao": 34000, "cnpj": "22222222000102"},
            ]}).encode())
        if "municipios.csv" in url:
            return Resp(200, ("codigo_ibge,nome,latitude,longitude,codigo_uf\n3100104,Alfa,-18.5,-46.5,31\n"
                              "3100203,Beta,-19.9,-43.9,31\n4300034,Gama,-30.0,-51.2,43\n"
                              "2900108,Delta,-12.0,-38.5,29\n").encode(), "text/csv")
        if "servicodados.ibge.gov.br" in url:
            def feat(c):
                return {"type": "Feature", "properties": {"codarea": c},
                        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
            if "/paises/BR" in url:
                corpo = {"type": "FeatureCollection", "features": [feat(c) for c in ("31", "43", "29", "53")]}
            else:
                corpo = {"type": "FeatureCollection", "features": [feat("3100104"), feat("3100203")]}
            return Resp(200, json.dumps(corpo).encode())
        if partes[0] == "downloads":
            if q.get("comp") == "list":
                blobs = "".join(f"<Blob><Name>{n}</Name><Url>x</Url><Properties><Etag>0x{abs(hash(c)) % 10**8}</Etag>"
                                f"<Content-Length>{len(c)}</Content-Length></Properties></Blob>" for n, c in CSVS.items())
                return Resp(200, f"<EnumerationResults><Blobs>{blobs}</Blobs></EnumerationResults>".encode(), "application/xml")
            return Resp(200, CSVS[partes[-1]], "application/octet-stream")
        mod, ep = partes[0], partes[1]
        if ep == "openapi.json":
            paths = {f"/{e}": {"get": {"parameters": [{"name": c} for c in (rows[0].keys() if rows else [])]
                                       + [{"name": "pagina"}, {"name": "tamanho_da_pagina"}]}}
                     for e, rows in self.dados[mod].items()}
            return Resp(200, json.dumps({"openapi": "3.1.0", "paths": paths}).encode())
        if ep == "data-atualizacao":
            return Resp(200, b'{"data_ultima_atualizacao":"2026-10-31T06:00:00"}')
        rows = self.dados[mod][ep]
        filtros = {k: v for k, v in q.items() if k not in ("pagina", "tamanho_da_pagina")}
        if filtros:
            rows = [r for r in rows if all(str(r.get(k)) == v for k, v in filtros.items())]
        tam, pag = int(q.get("tamanho_da_pagina", 50)), int(q.get("pagina", 1))
        if tam > 200:
            return Resp(422, b'{"detail":"max 200"}')
        fatia = rows[(pag - 1) * tam: pag * tam]
        corpo = {"data": copy.deepcopy(fatia), "total_items": len(rows), "total_pages": math.ceil(len(rows) / tam),
                 "page_number": pag, "page_size": len(fatia)}
        return Resp(200, json.dumps(corpo).encode())


    # ------------------------------------------------------------------ API de dados do Portal da Transparência
    def _portal_api(self, caminho, q):
        def j(x):
            return Resp(200, json.dumps(x).encode())
        if self.headers.get("chave-api-dados") != "chave-de-teste":
            return Resp(401, b'{"Erro": "chave"}')
        pag = int(q.get("pagina", 1))
        if pag > 1 and not caminho.startswith("/api-de-dados/despesas/documentos/"):
            return j([])
        c = caminho.replace("/api-de-dados", "")
        if c == "/despesas/recursos-recebidos":
            if q.get("uf") != "MG":
                return j([])
            mes = str(q.get("mesAnoInicio"))
            anomes = mes[3:] + mes[:2]

            def fmt(d):          # a API devolve o CNPJ formatado (00.000.000/0000-00)
                return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if d.isdigit() and len(d) == 14 else d

            codigos = {}

            def cod(nome):         # códigos estáveis por nome (como na API)
                return codigos.setdefault(nome, str(10000 + len(codigos)))

            def r(doc, nome, mun, sup, orgao, ug, valor, tipo="Administração Pública Municipal"):
                valor = float(valor.replace(".", "").replace(",", "."))   # a API devolve número aqui
                return {"anoMes": int(anomes), "codigoPessoa": fmt(doc), "nomePessoa": nome, "tipoPessoa": tipo,
                        "municipioPessoa": mun, "siglaUFPessoa": "MG", "codigoOrgaoSuperior": cod(sup),
                        "nomeOrgaoSuperior": sup, "codigoOrgao": cod(orgao), "nomeOrgao": orgao, "codigoUG": cod("UG " + ug),
                        "nomeUG": ug, "valor": valor}
            # o filtro tipoFavorecido usa o rótulo da consulta; a linha traz o rótulo do cadastro
            consulta = {"Administração Pública Municipal": {"Administração Pública Municipal"},
                        "Entidades Sem Fins Lucrativos": {"Entidade sem fins lucrativos"},
                        "Pessoa Física": {"Pessoa Física"}}
            pedido = q.get("tipoFavorecido")
            linhas = [
                r("11111111000101", "MUNICIPIO DE ALFA", "ALFA", "Ministério da Fazenda", "Secretaria do Tesouro",
                  "STN", "900.000,00"),
                r("11111111000101", "MUNICIPIO DE ALFA", "ALFA", "Ministério da Educação", "FNDE", "FNDE", "120.000,00"),
                r("11111111000283", "FUNDO MUNICIPAL DE SAUDE", "ALFA", "Ministério da Saúde", "Fundo Nacional de Saúde",
                  "FNS", "300.000,00"),
                r("22222222000294", "FUNDO MUNICIPAL DE SAUDE", "BETA", "Ministério da Saúde", "Fundo Nacional de Saúde",
                  "FNS", "300.000,00"),
                r("55555555000155", "ASSOCIACAO X", "ALFA", "Ministério da Cultura", "MinC", "MinC", "50.000,00",
                  "Entidade sem fins lucrativos"),
                r("***.123.456-**", "PESSOA FISICA", "ALFA", "Ministério da Cultura", "MinC", "MinC", "1.000,00",
                  "Pessoa Física"),
                # armadilha: segundo lançamento do mesmo órgão/UG no mês (legítimo: soma, não é duplicação)
                r("11111111000101", "MUNICIPIO DE ALFA", "ALFA", "Ministério da Educação", "FNDE", "FNDE", "30.000,00"),
                # armadilha: banco listado como favorecido (não é ente; fica fora da carteira)
                r("00360305000104", "CAIXA ECONOMICA FEDERAL", "BRASILIA", "Ministério da Fazenda",
                  "Secretaria do Tesouro", "STN", "999.000,00"),
            ]
            if pedido:
                linhas = [x for x in linhas if x["tipoPessoa"] in consulta.get(pedido, set())]
            return j(linhas)
        if c == "/emendas":
            ano = int(q.get("ano"))
            if ano != date.today().year:
                return j([])
            return j([
                {"codigoEmenda": f"{ano}10010001", "ano": ano, "tipoEmenda": "Emenda Individual - Transferências com "
                 "Finalidade Definida", "autor": "1001", "nomeAutor": "DEP FULANO", "numeroEmenda": "0001",
                 "localidadeDoGasto": "ALFA - MG", "funcao": "Saúde", "subfuncao": "Atenção Básica",
                 "valorEmpenhado": "500.000,00", "valorLiquidado": "400.000,00", "valorPago": "300.000,00",
                 "valorRestoInscrito": "0,00", "valorRestoCancelado": "- 26.002,00", "valorRestoPago": "0,00"},
                {"codigoEmenda": f"{ano}10020001", "ano": ano, "tipoEmenda": "Emenda de Bancada", "autor": "1002",
                 "nomeAutor": "BANCADA DE MG", "numeroEmenda": "0001", "localidadeDoGasto": "MINAS GERAIS (UF)",
                 "funcao": "Saúde", "subfuncao": "Assistência Hospitalar", "valorEmpenhado": "200.000,00",
                 "valorLiquidado": "100.000,00", "valorPago": "100.000,00", "valorRestoInscrito": "0,00",
                 "valorRestoCancelado": "0,00", "valorRestoPago": "0,00"},
                # inconsistente de propósito: pago maior que liquidado (a auditoria tem de apontar)
                {"codigoEmenda": f"{ano}10030001", "ano": ano, "tipoEmenda": "Emenda de Comissão", "autor": "1003",
                 "nomeAutor": "COMISSAO DE SAUDE", "numeroEmenda": "0001", "localidadeDoGasto": "Nacional",
                 "funcao": "Saúde", "subfuncao": "", "valorEmpenhado": "50.000,00", "valorLiquidado": "10.000,00",
                 "valorPago": "20.000,00", "valorRestoInscrito": "0,00", "valorRestoCancelado": "0,00",
                 "valorRestoPago": "0,00"},
            ])
        if c.startswith("/emendas/documentos/"):
            cod = c.rsplit("/", 1)[-1]
            # como na API real: sem valor (o valor vem do detalhe do documento). OB2 paga duas emendas.
            docs = {"10010001": [("Empenho", "EMP1"), ("Pagamento", "OB1"), ("Pagamento", "OB2")],
                    "10020001": [("Empenho", "EMP2"), ("Pagamento", "OB3"), ("Pagamento", "OB2")],
                    "10030001": [("Pagamento", "OB4")]}
            lst = docs.get(cod[-8:], [])
            return j([{"id": i, "data": "10/08/2026", "fase": f, "codigoDocumento": d, "codigoDocumentoResumido": d,
                       "especieTipo": "Original", "tipoEmenda": ""} for i, (f, d) in enumerate(lst)])
        if c.startswith("/despesas/documentos/"):
            cod = c.rsplit("/", 1)[-1]
            fav = {"OB1": ("11111111000101", "MUNICIPIO DE ALFA", "200.000,00"),
                   "OB2": ("11111111000283", "FUNDO MUNICIPAL DE SAUDE DE ALFA", "100.000,00"),
                   "OB3": ("22222222000294", "FUNDO MUNICIPAL DE SAUDE DE BETA", "100.000,00"),
                   "OB4": ("22222222000294", "FUNDO MUNICIPAL DE SAUDE DE BETA", "20.000,00")}.get(cod)
            if not fav:
                return Resp(404, b"{}")
            d = fav[0]
            return j({"documento": cod, "data": "15/08/2026", "favorecido": f"{d} - {fav[1]}",
                      "codigoFavorecido": f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}", "nomeFavorecido": fav[1],
                      "ufFavorecido": "MG", "valor": fav[2], "fase": "Pagamento", "orgaoSuperior": "Ministério da Saúde"})
        if c == "/ceis":
            return j([{"id": 1, "dataReferencia": "30/10/2026", "dataInicioSancao": "01/01/2025",
                       "dataFimSancao": "31/12/2027", "tipoSancao": {"descricaoResumida": "Impedimento/proibição de contratar"},
                       "orgaoSancionador": {"nome": "CGU", "siglaUf": "DF"},
                       "sancionado": {"nome": "CONSTRUTORA EXEMPLO LTDA", "codigoFormatado": "88.888.888/0001-88"},
                       "pessoa": {"cpfFormatado": "", "cnpjFormatado": "88.888.888/0001-88",
                                  "nome": "CONSTRUTORA EXEMPLO LTDA", "tipo": "Entidades Empresariais Privadas"}},
                      # pessoa física com CPF completo no campo 'sancionado' (como na API real): não pode entrar
                      {"id": 2, "dataReferencia": "30/10/2026", "dataInicioSancao": "22/04/2025",
                       "dataFimSancao": "22/04/2035", "tipoSancao": {"descricaoResumida": "Impedimento"},
                       "orgaoSancionador": {"nome": "TRF1"},
                       "sancionado": {"nome": "FULANO DE TAL", "codigoFormatado": "038.945.501-63"},
                       "pessoa": {"cpfFormatado": "***.945.501-**", "cnpjFormatado": "", "nome": "FULANO DE TAL",
                                  "tipo": "Pessoa Física"}}])
        if c == "/cnep":
            return j([])
        if c == "/cepim":
            return j([{"id": 9, "dataReferencia": "28/10/2026", "motivo": "Omissão no dever de prestar contas",
                       "orgaoSuperior": {"nome": "Ministério da Cultura"},
                       "pessoaJuridica": {"cnpjFormatado": "55.555.555/0001-55", "nome": "ASSOCIACAO X"}}])
        if c == "/novo-bolsa-familia-por-municipio":
            if str(q.get("codigoIbge")) != "3100104":
                return j([])
            return j([{"id": 1, "dataReferencia": str(q.get("mesAno"))[:4] + "-" + str(q.get("mesAno"))[4:] + "-01",
                       "municipio": {"codigoIBGE": "3100104", "nomeIBGE": "ALFA", "uf": {"sigla": "MG"}},
                       "tipo": {"id": 8, "descricao": "Novo Bolsa Família"}, "valor": 150000.0,
                       "quantidadeBeneficiados": 220}])
        return Resp(404, b"{}")