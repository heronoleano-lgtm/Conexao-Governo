"""Camada semântica: como cada dado aparece para quem usa o painel.

Uma única fonte para:
  - nome de negócio de cada coluna, formato (R$, %, número, data, texto) e explicação (tooltip);
  - colunas técnicas que nunca aparecem (ids, códigos internos);
  - nomes e cores das modalidades de transferência e dos bancos.
Qualquer tabela mostrada passa por `rotular()`; coluna sem rótulo aparece com o nome "humanizado" e é
apontada pelo teste de rótulos, para que nenhum "n" ou "hhi_entes" chegue à tela.
"""
from __future__ import annotations

import pandas as pd

# ------------------------------------------------------------------ modalidades e bancos
MODALIDADES = {
    "Especiais": {"nome": "Transferências Especiais", "curto": "Especiais", "cor": "#005CA9",
                  "descricao": "Emendas individuais transferidas direto ao ente (\"emendas Pix\")."},
    "Fundo a Fundo": {"nome": "Fundo a Fundo", "curto": "Fundo a Fundo", "cor": "#00A19A",
                      "descricao": "Repasse de fundos federais a fundos estaduais e municipais (conta no BB)."},
    "Discricionárias": {"nome": "Convênios e Contratos de Repasse", "curto": "Convênios", "cor": "#F39200",
                        "descricao": "Transferências discricionárias e legais: convênios, contratos de repasse e termos."},
}
BANCO_CORES = {"CAIXA": "#005CA9", "BB": "#F2C500", "BNB": "#8C1D40", "(sem banco)": "#C7CDD6",
               "Bradesco": "#CC092F", "Itaú": "#EC7000", "Santander": "#EA1D25", "Sicoob": "#003641",
               "Sicredi": "#3FA110", "outros bancos": "#9AA4B1"}
SEGMENTO_CORES = {"Território CAIXA": "#005CA9", "Disputado": "#F39200", "Território concorrente": "#D1495B",
                  "Sem banco definido": "#9AA4B1", "Só Fundo a Fundo": "#00A19A"}
CAIXA_AZUL, CAIXA_LARANJA = "#005CA9", "#F39200"
SEVERIDADE_CORES = {"Crítico": "#D1495B", "Atenção": "#F39200"}
QUADRANTE_CORES = {"Atacar já": "#005CA9", "Construir relação": "#8C1D40", "Ganho rápido": "#00A19A",
                   "Monitorar": "#9AA4B1"}
CLASSE_CORES = {"Estável": "#005CA9", "Médio": "#00A19A", "Passagem": "#F39200"}
EXTRA_CORES = {**SEVERIDADE_CORES, **QUADRANTE_CORES, **CLASSE_CORES}


def nome_modalidade(m: str, curto: bool = False) -> str:
    info = MODALIDADES.get(m)
    return (info["curto"] if curto else info["nome"]) if info else m


def cor_banco(b: str) -> str:
    return BANCO_CORES.get(b, BANCO_CORES["outros bancos"])


# ------------------------------------------------------------------ dicionário de colunas
# coluna: (rótulo, tipo, ajuda)   tipos: brl, pct, int, num, dias, data, texto, bool, score
R, P, I, D, T, B = "brl", "pct", "int", "data", "texto", "bool"
ROTULOS: dict[str, tuple[str, str, str]] = {
    # identificação
    "modulo": ("Modalidade", T, "Tipo de transferência federal"),
    "modulos": ("Modalidades", T, ""),
    "nome_ente": ("Ente", T, "Município, estado ou órgão que recebe o recurso"),
    "nome": ("Local", T, ""),
    "cnpj_ente": ("CNPJ do ente", T, ""),
    "uf": ("UF", T, ""), "uf_principal": ("UF principal", T, "UF que concentra o maior valor"),
    "ufs": ("UFs", T, ""), "municipio": ("Município", T, ""), "esfera": ("Esfera", T, "Municipal ou estadual"),
    "populacao": ("População", I, "Siconfi"), "regiao": ("Região", T, ""),
    "codigo": ("Código do instrumento", T, ""), "objeto": ("Objeto", T, ""), "ano": ("Ano", T, ""),
    "situacao": ("Situação", T, ""), "situacao_conta": ("Situação da conta", T, ""),
    "orgao": ("Órgão / ministério", T, ""), "orgaos": ("Órgãos", T, ""), "programa": ("Programa", T, ""),
    "programas": ("Programas", T, ""), "area": ("Área de política", T, ""),
    "area_principal": ("Área principal", T, ""), "parlamentar": ("Parlamentar", T, ""),
    "tipo_parlamentar": ("Tipo de emenda", T, ""), "natureza_juridica": ("Natureza jurídica", T, ""),
    "agencia": ("Agência", T, ""), "conta": ("Conta", T, ""), "origem": ("Origem da conta", T, ""),
    "data_referencia": ("Data de referência", D, ""), "fim_vigencia": ("Fim da vigência", D, ""),
    "ativo": ("Ativo", B, ""),
    # bancos
    "grupo_banco": ("Banco", T, "Banco da conta do instrumento"), "banco": ("Código do banco", T, ""),
    "grupo_banco_plano": ("Banco do plano", T, ""), "grupo_origem": ("Banco de origem", T, "Banco da conta que pagou"),
    "grupo_destino": ("Banco de destino", T, "Banco de quem recebeu"), "bancos": ("Bancos usados", T, ""),
    "banco_principal": ("Banco principal", T, "Banco que recebe a maior parte"),
    "banco_ano_anterior": ("Banco no ano anterior", T, ""), "banco_ano_atual": ("Banco no ano atual", T, ""),
    "pct_no_banco_principal": ("% no banco principal", P, ""),
    # valores
    "valor": ("Valor (R$)", R, "Valor do repasse"), "valor_total": ("Valor total (R$)", R, ""),
    "valor_caixa": ("Valor na CAIXA (R$)", R, ""), "valor_concorrente": ("Valor no concorrente (R$)", R, ""),
    "valor_concorrente_recente": ("No concorrente, anos recentes (R$)", R, "Últimos 2 anos com dados"),
    "valor_em_entes_so_concorrente": ("Em entes só do concorrente (R$)", R, ""),
    "part_caixa": ("Participação CAIXA", P, "Valor na CAIXA ÷ valor com banco definido"),
    "saldo": ("Saldo (R$)", R, "Último saldo publicado"), "saldo_caixa": ("Saldo na CAIXA (R$)", R, ""),
    "saldo_concorrente": ("Saldo no concorrente (R$)", R, ""), "saldo_faf_hoje": ("Saldo Fundo a Fundo hoje (R$)", R, ""),
    "data_saldo": ("Data do saldo", D, ""), "data_saldo_max": ("Saldo mais recente", D, ""),
    "contas": ("Contas", I, ""), "contas_com_saldo": ("Contas com saldo publicado", I, ""),
    "cobertura": ("Cobertura do saldo", P, "Contas com saldo publicado ÷ contas"),
    "saldo_x_repasse": ("Saldo ÷ repasse (vezes)", "vezes", "Saldo em conta dividido pelo valor repassado no período. Pode passar de 1×: a conta do Fundo a Fundo acumula repasses de anos anteriores e rendimentos"),
    "desembolsado": ("Desembolsado (R$)", R, ""),
    "instrumentos": ("Instrumentos", I, "Planos de ação ou convênios"), "entes": ("Entes", I, ""),
    "empenhos": ("Empenhos", I, ""), "a_creditar": ("A creditar (R$)", R, "Empenhado e ainda sem ordem bancária"),
    "a_creditar_concorrente": ("A creditar no concorrente (R$)", R, ""),
    "valor_empenho": ("Empenhado (R$)", R, ""), "valor_pago": ("Pago (R$)", R, ""),
    "data_empenho": ("Data do empenho", D, ""), "data_ob": ("Data da ordem bancária", D, ""),
    "dias_ate_pagamento": ("Dias até o pagamento", I, ""),
    "natureza": ("Natureza da despesa", T, ""),
    # velocidade
    "recorte": ("Recorte", T, ""), "n": ("Pagamentos analisados", I, ""),
    "dias_p25": ("Dias (25% mais rápidos)", I, "Um quarto dos pagamentos sai até aqui"),
    "dias_mediana": ("Dias (mediana)", I, "Metade dos pagamentos sai até aqui"),
    "dias_p75": ("Dias (75%)", I, "Três quartos dos pagamentos saem até aqui"),
    # fluxo e pagamentos
    "tipo_movimento": ("Tipo de movimento", T, ""), "proprio_ente": ("Para o próprio ente", B, ""),
    "tipo_favorecido": ("Tipo de favorecido", T, ""), "data": ("Data", D, ""), "mes": ("Mês", T, ""),
    "pago_terceiros": ("Pago a terceiros (R$)", R, "Pagamentos com banco de destino identificado"),
    "pago_terceiros_caixa": ("Pago a recebedores CAIXA (R$)", R, ""),
    "pago_terceiros_fora": ("Pago fora da CAIXA (R$)", R, ""),
    "part_caixa_pagamentos": ("% dos pagamentos na CAIXA", P, ""),
    "para_conta_propria": ("Para conta do próprio ente (R$)", R, ""), "aplicacoes": ("Aplicações e resgates (R$)", R, ""),
    "recebedor": ("Recebedor", T, ""), "documento": ("CNPJ do recebedor", T, ""), "tipo_doc": ("Tipo", T, ""),
    "valor_recebido": ("Recebido (R$)", R, ""), "entes_pagadores": ("Entes que pagaram", I, ""),
    "recebe_na_caixa": ("% recebido na CAIXA", P, ""), "fonte": ("Fonte do dado", T, ""),
    "pct_fica_no_banco": ("Fica no próprio banco", P, "Parte do pago a terceiros que vai para recebedor no mesmo banco da conta"),
    "etapa": ("Etapa", T, ""), "destino": ("Destino", T, ""),
    # parlamentares
    "hhi_entes": ("Concentração nos entes", P, "0% = espalhado; 100% = um único ente (índice HHI)"),
    "pct_uf_principal": ("% na UF principal", P, ""), "entes_so_concorrente": ("Entes só do concorrente", I, ""),
    "leitura": ("Leitura", T, "Interpretação sugerida pelo motor"),
    # perfil, oportunidades e potencial
    "perfil": ("Perfil bancário", T, ""), "rotacao": ("Mudança de banco", T, "Entre os dois últimos anos"),
    "segmento": ("Segmento", T, ""), "score": ("Score de prospecção", I, "0 a 100"),
    "motivo_principal": ("Motivo da nota", T, ""), "motivo": ("Motivo", T, ""),
    "multibanco": ("Multibanco", B, ""), "valor_janelas": ("Em janelas abertas (R$)", R, ""),
    "janelas": ("Janelas abertas (R$)", R, ""), "valor_vazamento": ("Vazamento (R$)", R, ""),
    "referencia": ("Referência", T, ""), "detalhe": ("Detalhe", T, ""),
    "potencial": ("Potencial de custódia (R$)", R, ""),
    "potencial_custodia": ("Potencial de custódia (R$)", R, "Saldo no concorrente + metade do a creditar + janelas"),
    "resultado_estimado_ano": ("Resultado estimado/ano (R$)", R, "Ordem de grandeza; premissas no config.yaml"),
    "pagamentos_fora_caixa": ("Pagamentos fora da CAIXA (R$)", R, ""),
    "acao_recomendada": ("Ação recomendada", T, ""),
    "status": ("Status", T, ""), "responsavel": ("Responsável", T, ""), "observacao": ("Observação", T, ""),
    "atualizado_em": ("Atualizado em", T, ""), "atualizado_por": ("Atualizado por", T, ""),
    # vazamento e executores
    "nome_executor": ("Executor", T, ""), "cnpj_executor": ("CNPJ do executor", T, ""),
    "valor_executor": ("Valor do executor (R$)", R, ""), "direcao": ("Direção", T, ""),
    # transferência secundária e conformidade
    "lancamentos": ("Lançamentos", I, ""), "valor_transferido": ("Transferido (R$)", R, ""),
    "valor_12_meses": ("Transferido em 12 meses (R$)", R, ""), "primeira": ("Primeira", D, ""),
    "ultima": ("Última", D, ""), "tem_conta_caixa_outro_modulo": ("Já é cliente CAIXA", B,
                                                                 "Tem conta CAIXA em outra modalidade"),
    "para_outro_orgao_publico": ("Para outro órgão público (R$)", R, ""),
    "transf_secundaria": ("Transferência secundária FaF 12m (R$)", R, ""),
    # destinação e órgãos
    "tipo": ("Tipo", T, ""), "destinacao": ("Destinação", T, ""),
    # qualidade
    "item": ("Item", T, ""),
    "data_atualizacao": ("Atualizado na origem em", T, "Data informada pelo governo"),
    "tabela_publicada": ("Tabela", T, ""), "linhas": ("Linhas", I, ""),
    # resumo por ente e por UF/modalidade
    "valor_especiais": ("Transferências Especiais (R$)", R, ""), "valor_fundo_a_fundo": ("Fundo a Fundo (R$)", R, ""),
    "valor_convenios": ("Convênios (R$)", R, ""), "valor_filtro": ("Valor no recorte (R$)", R, ""),
    "porte": ("Porte", T, "Faixa de população"), "pagamentos": ("Pagamentos analisados", I, ""),
    "cod_uf": ("Código da UF", T, ""),
    # colunas de banco em tabelas cruzadas
    "CAIXA": ("CAIXA (R$)", R, ""), "BB": ("BB (R$)", R, ""), "BNB": ("BNB (R$)", R, ""),
    "(sem banco)": ("Sem banco (R$)", R, ""), "outros bancos": ("Outros bancos (R$)", R, ""),
    "Total": ("Total (R$)", R, ""), "% CAIXA": ("Participação CAIXA", P, ""), "Concorrência": ("No concorrente (R$)", R, ""),
}
# nunca exibidas
TECNICAS = {"cod_uf", "id_instrumento", "id_empenho", "id_agencia_conta", "id_executor", "codarea", "cod_ibge", "lat", "lon",
            "favorecido_publico", "doc_favorecido", "chave", "dia", "descricao", "_cx", "_com"}


# ------------------------------------------------------------------ gestor de custódia
V = "var"   # variação percentual com sinal
ROTULOS.update({
    "rendimento": ("Rendimento de aplicação (R$)", R, "Rendimento acumulado informado no convênio"),
    "saidas_12m": ("Saídas em 12 meses (R$)", R, "Pagamentos, transferências, tributos e devoluções da conta"),
    "dias_permanencia": ("Permanência (dias)", I, "Saldo ÷ média diária de saídas (regra PERM-01)"),
    "base_permanencia": ("Base do cálculo", T, ""),
    "classe_saldo": ("Classe do saldo", T, "Estável, médio ou de passagem (regra PERM-02)"),
    "valor_economico_ano": ("Valor econômico / ano (R$)", R, "Saldo × taxa × fração (regra PERM-03)"),
    "posicao": ("Posição", I, ""), "pct_do_saldo": ("% do saldo", P, ""),
    "pct_acumulado": ("% acumulado", P, "Participação somada até esta posição"),
    "valor_a_receber": ("A receber (R$)", R, "Empenhado e não pago, repasse de convênio assinado ainda não liberado, "
                                            "ou previsto (minuta de empenho / proposta aprovada: ver a coluna Etapa)"),
    "saldo_estimado": ("Saldo estimado hoje (R$)", R, "Regra SAL-01: igual ao publicado onde o extrato chega; onde parou, "
                       "reconstituído com os créditos publicados, a curva de execução do banco e o rendimento"),
    "saldo_est_min": ("Estimado · mínimo (R$)", R, "Limite inferior pela faixa dos testes retroativos"),
    "saldo_est_max": ("Estimado · máximo (R$)", R, "Limite superior pela faixa dos testes retroativos"),
    "saldo_publicado": ("Saldo publicado (R$)", R, "Último saldo publicado na fonte (parado, se o extrato parou)"),
    "base_saldo": ("Base do saldo", T, "Publicado, reconstituído ou estimado (regra SAL-01)"),
    "extrato_parado_em": ("Extrato parado em", T, "Último lançamento publicado do banco desta conta"),
    "saldo_caixa_estimado": ("Saldo CAIXA estimado hoje (R$)", R, "Regra SAL-01"),
    "saldo_concorrente_estimado": ("Saldo no concorrente estimado (R$)", R, "Regra SAL-01"),
    "creditos_apos_parada": ("Créditos depois da parada (R$)", R, "Ordens bancárias publicadas depois que o extrato parou"),
    "teste": ("Teste", T, ""), "parametro": ("Parâmetro", T, ""),
    "erro_total": ("Erro do total", V, "Estimado ÷ publicado − 1"),
    "soma_publicada": ("Soma publicada (R$)", R, ""), "soma_reconstituida": ("Soma reconstituída (R$)", R, ""),
    "contas_ate_5pct": ("Contas a até 5%", P, "Erro de até 5% do crédito da conta"),
    "contas_ate_10pct": ("Contas a até 10%", P, "Erro de até 10% do crédito da conta"),
    "pct_fica_no_banco": ("Fica no próprio banco", P, "Parte do pago a terceiros que vai para recebedor no mesmo banco da conta"),
    "etapa": ("Etapa", T, "Em que ponto está o dinheiro: empenho emitido, minuta, convênio assinado ou proposta"),
    "firme": ("Firme", B, "Empenho emitido ou convênio assinado (o previsto pode não se confirmar)"),
    "valor_minuta": ("Minuta de empenho (R$)", R, "Empenho previsto, ainda não emitido"),
    "data_prevista": ("Previsão do crédito", T, "Regra REC-01"),
    "dias_para_credito": ("Dias até o crédito", I, ""), "faixa_prazo": ("Prazo", T, ""),
    "regra": ("Regra", T, "Código em Regras e premissas"),
    "mes_nome": ("Mês", T, ""), "pct_do_total": ("% do total", P, ""),
    "banco_de": ("Banco antes", T, ""), "banco_para": ("Banco depois", T, ""),
    "banco_especiais": ("Banco nas Transferências Especiais", T, ""),
    "banco_convenios": ("Banco nos convênios", T, ""),
    "ultimo_ano_caixa": ("Último ano na CAIXA", T, ""), "ultimo_ano": ("Último ano com instrumentos", T, ""),
    "anos_sem_caixa": ("Anos fora da CAIXA", I, ""), "banco_atual": ("Banco atual", T, ""),
    "valor_caixa_historico": ("Já teve na CAIXA (R$)", R, ""),
    "valor_concorrente_depois": ("Foi para o concorrente desde então (R$)", R, ""),
    "risco": ("Risco", T, ""), "severidade": ("Severidade", T, ""), "valor_em_risco": ("Valor em risco (R$)", R, ""),
    "oferta": ("Oferta", T, ""), "valor_oportunidade": ("Oportunidade (R$)", R, ""), "argumento": ("Argumento", T, ""),
    "chance_conversao": ("Chance de conversão", I, "0 a 100 (regra PRI-01)"), "quadrante": ("Prioridade", T, "Regra PRI-02"),
    "dim_tamanho": ("Tamanho", I, "0 a 100"), "dim_disputa": ("Disputa", I, "0 a 100"),
    "dim_potencial": ("Potencial", I, "0 a 100"), "dim_credito": ("Crédito a receber", I, "0 a 100"),
    "dim_risco": ("Risco", I, "0 a 100"), "dim_venda": ("Venda cruzada", I, "0 a 100"),
    "dim_chance": ("Chance", I, "0 a 100"),
    "a_receber_total": ("A receber (R$)", R, ""), "riscos": ("Riscos", I, ""), "ofertas": ("Ofertas", I, ""),
    "valor_venda_cruzada": ("Venda cruzada (R$)", R, ""),
    "camada": ("Camada", T, ""), "tabela": ("Tabela", T, ""), "primeira_carga": ("Desde", T, ""),
    "ultima_carga": ("Até", T, ""), "cargas": ("Dias com carga", I, ""), "tamanho_mb": ("Tamanho (MB)", I, ""),
    "registros": ("Registros", I, ""), "colunas": ("Colunas", I, ""), "tabela_origem": ("Tabela de origem", T, ""),
    "esperado": ("Esperado", I, "Total informado pela API"), "ok": ("Ok", B, ""), "segundos": ("Segundos", I, ""),
    "erro": ("Erro", T, ""), "chave": ("Chave do histórico", T, "_chave_linha = a própria linha (tabela sem identificador)"),
    "linhas_fonte": ("Linhas na fonte", I, ""), "linhas_reconstruidas": ("Linhas reconstruídas", I, "Pelo histórico, para o dia"),
    "diferencas": ("Diferenças", I, "0 = nada perdido"),
    "estagio": ("Estágio da janela", T, "Momento da escolha do banco (regra JAN-01)"),
    "banco_indicado": ("Banco indicado", T, ""), "part_caixa_ente_hist": ("CAIXA no histórico do ente", P, ""),
    "part_caixa_parlamentar": ("CAIXA no histórico do parlamentar", P, ""),
    "prob_caixa": ("Probabilidade CAIXA", P, "60% histórico do ente + 40% do parlamentar"),
    "tendencia": ("Tendência", T, ""), "valor_em_disputa": ("Valor em disputa (R$)", R, "Valor × (1 − probabilidade CAIXA)"),
    "acao": ("Ação", T, ""), "tipo_agente": ("Tipo", T, ""), "agente": ("Agente", T, "Parlamentar ou órgão concedente"),
    "valor_recente": ("Valor nos últimos 3 anos (R$)", R, ""), "part_caixa_recente": ("CAIXA nos últimos 3 anos", P, ""),
    "motivos": ("Motivos prováveis", T, "Sinais tirados dos dados (regra FOR-01)"),
    "uf_principal": ("UF principal", T, ""), "instrumentos_janela": ("Instrumentos na janela", I, ""),
    "tipo_ente": ("Tipo de ente", T, "Município e órgãos municipais, estado, consórcio, OSC ou empresa pública"),
    "municipios": ("Municípios", I, "Códigos IBGE distintos (o Brasil tem 5.570)"),
    "conta_compartilhada": ("Conta compartilhada", B, "A mesma conta serve a mais de um plano ou executor; o saldo entra uma vez"),
    "familia": ("Família", T, "Tipo de checagem"), "checagem": ("Checagem", T, ""),
    "medido": ("Medido", T, "O que a auditoria encontrou"), "referencia": ("Esperado / referência", T, ""),
    "impacto": ("Impacto no painel", T, ""), "checagens": ("Checagens", I, ""), "nome_regra": ("Regra", T, ""), "frente": ("Frente de negócio", T, ""),
    "descricao_regra": ("O que faz", T, ""), "parametros": ("Parâmetros", T, "Ajuste em config/regras.yaml"),
    "base": ("Base", T, ""), "status_regra": ("Status", T, "validar = premissa a confirmar"),
    "pergunta": ("Pergunta de negócio", T, ""), "tela": ("Tela", T, ""), "regras": ("Regras", T, ""),
    "situacao": ("Situação", T, ""),
    "ganho_valor": ("Ganho em valor transferido (R$)", R, ""),
    "ganho_custodia": ("Ganho de custódia (R$)", R, "Saldo que viria para a CAIXA na meta"),
    "ganho_resultado_ano": ("Resultado estimado / ano (R$)", R, ""),
    "part_saldo_caixa": ("% do saldo na CAIXA", P, ""),
    "data_saldo_recente": ("Saldo mais recente em", T, ""), "data_saldo_mediana": ("Data típica do saldo", T, "Mediana das datas de saldo"),
    "dias_desde_saldo": ("Idade do saldo (dias)", I, ""), "pct_saldo_atualizado": ("% do saldo atualizado", P, "Saldo com data nos últimos 60 dias"),
    "saldo_desatualizado": ("Saldo desatualizado", B, "Regra QLD-01"),
    "ultimo_lancamento": ("Último lançamento no extrato", T, "Data do lançamento bancário mais recente publicado"),
})
for _ano in range(2008, 2036):
    ROTULOS[f"ano_{_ano}"] = (str(_ano), T, "Banco escolhido no ano")
# outros repasses (FUNDEB, FPM, FNS, FNDE, FNAS)
ROTULOS.update({
    "cnpj": ("CNPJ", T, "CNPJ do favorecido"),
    "favorecido": ("Favorecido", T, "Quem recebeu o repasse (fundo, prefeitura, secretaria)"),
    "fundeb_12m": ("FUNDEB 12 meses (R$)", R, "Repasses do FUNDEB (Tesouro) nos últimos 12 meses"),
    "fpm_12m": ("FPM 12 meses (R$)", R, "Fundo de Participação dos Municípios nos últimos 12 meses"),
    "saude_12m": ("Saúde 12 meses (R$)", R, "Repasses do Fundo Nacional de Saúde nos últimos 12 meses"),
    "saude_caixa_12m": ("Saúde na CAIXA 12 meses (R$)", R, "Parte dos repasses do FNS creditada em conta CAIXA"),
    "educacao_12m": ("Educação 12 meses (R$)", R, "Repasses do FNDE (PNAE, PDDE, PNATE…) nos últimos 12 meses"),
    "assistencia_12m": ("Assistência 12 meses (R$)", R, "Repasses do Fundo Nacional de Assistência Social nos últimos 12 meses"),
    "saldo_saude_caixa": ("Saldo saúde na CAIXA (R$)", R, "Último saldo das contas do FNS na CAIXA"),
    "saldo_saude_concorrente": ("Saldo saúde no concorrente (R$)", R, "Último saldo das contas do FNS em outro banco"),
    "part_caixa_saude": ("% saúde na CAIXA", P, "Repasses do FNS creditados na CAIXA ÷ total do FNS"),
    "bloco": ("Bloco do SUS", T, "Bloco de financiamento (custeio, investimento)"),
    "saldo_concorrente": ("Saldo no concorrente (R$)", R, ""),
    "outros_12m": ("Repasses 12 meses (R$)", R, ""),
})

# CRM (Portal da Transparência)
ROTULOS.update({
    "cadastro": ("Cadastro", T, "CEIS, CNEP ou CEPIM"), "tipo_sancao": ("Tipo de sanção", T, ""),
    "inicio": ("Início", T, ""), "fim": ("Fim", T, ""), "regra": ("Regra", T, ""), "gravidade": ("Gravidade", T, ""),
    "banco_conta": ("Banco da conta", T, "Banco da conta de onde saiu o pagamento"),
    "recebido_12m": ("Recebido da União em 12 meses (R$)", R, "Tudo o que o CNPJ recebeu (Portal da Transparência)"),
    "saude_12m": ("Saúde 12 meses (R$)", R, ""), "educacao_12m": ("Educação 12 meses (R$)", R, ""),
    "assistencia_12m": ("Assistência 12 meses (R$)", R, ""),
    "constitucionais_12m": ("Constitucionais 12 meses (R$)", R, "FPM, FPE e outras transferências da Fazenda"),
    "outros_12m": ("Outros 12 meses (R$)", R, ""),
    "caixa_conhecido_12m": ("Na CAIXA (banco conhecido) 12m (R$)", R, "FNS e ordens bancárias das Especiais com conta CAIXA"),
    "concorrente_conhecido_12m": ("No concorrente (banco conhecido) 12m (R$)", R, ""),
    "sem_banco_12m": ("Sem banco conhecido 12m (R$)", R, "Recebido cujo banco a fonte aberta não informa"),
    "crm_priorizados": ("Entes priorizados no CRM", I, "Entes com prioridade CRM-01 de 70 ou mais"),
    "crm_prioridade_max": ("Maior prioridade CRM", I, "Nota CRM-01 (0 a 100) do ente mais prioritário da área"),
    "crm_potencial": ("Potencial dos priorizados (R$)", R, "Potencial de custódia dos entes com prioridade ≥ 70"),
    "crm_sem_banco": ("Recebido sem banco conhecido 12m (R$)", R, "Portal da Transparência: recebido pela administração "
                      "pública da área sem banco identificado nas fontes abertas"),
    "crm_recebido": ("Recebido da União 12m (R$)", R, "Portal da Transparência, administração pública da área"),
    "crm_bolsa_familia": ("Bolsa Família no mês (R$)", R, "Pago pela CAIXA na área (presença CAIXA)"),
    "crm_alertas": ("Entes com alerta de conformidade", I, ""),
    "faixa_caixa": ("Faixa de participação CAIXA", T, ""),
    **{k: (k, P, "Parte das saídas desta conta") for k in (
        "Recebedor na CAIXA", "Recebedor no BB", "Recebedor em outro banco", "Banco do recebedor não informado",
        "Conta do próprio ente", "Aplicação financeira", "Tributos e tarifas", "Devolução")},
    "conta": ("Conta", T, ""),
    "cnpj_plano": ("CNPJ do ente do plano", T, "Dono da conta Fundo a Fundo quando quem movimenta é um fundo do ente"),
    "metodo": ("Método", T, "Como o número foi conferido"), "escore_anomalia": ("Escore de anomalia", I, ""),
    "percentil": ("Percentil", P, ""), "explicacao": ("O que é atípico", T, "Variáveis que a rede não reconstruiu"),
    "extremo_isolado": ("Extremo numa variável", B, ""), "z": ("z robusto", I, "Distância do típico em desvios robustos"),
    "id_pagamento": ("Identificador do pagamento", T, ""), "nome_fonte": ("Fonte", T, ""),
    "valor_12m": ("Valor 12 meses (R$)", R, ""), "valor_outro_banco": ("Em outro banco (R$)", R, ""),
    "banco_publicado": ("Banco publicado", B, ""), "pago_terceiros": ("Pago a terceiros (R$)", R, ""),
    "pct_recebedor_caixa": ("% para recebedor CAIXA", P, ""),
    "com_emenda": ("% com emenda", P, "Parte dos instrumentos que vêm de emenda parlamentar"),
    "idade_saldo_dias": ("Idade mediana do saldo (dias)", I, "Dias entre a data do saldo e o saldo mais recente"),
    "part_valor": ("% do valor", P, ""), "part_saldo": ("% do saldo", P, ""),
    "entes_pagadores": ("Entes que pagaram", I, ""),
    "saldo_medido_pct": ("% do saldo medido", P, "Parte do saldo com lançamentos de 12 meses (base da média)"),
    "part_do_total": ("% do total", P, ""), "sancionado": ("Com sanção", B, "Aparece no CEIS/CNEP"),
    "relacao": ("Tipo de relação", T, ""), "relacoes": ("Relações", I, ""),
    "relacoes_no_corte": ("Relações que somam 80%", I, "Quantas das maiores relações somam 80% do valor"),
    "pct_relacoes_no_corte": ("% das relações", P, "Parte das relações que concentra 80% do valor"),
    "valor_no_corte": ("Valor dessas relações (R$)", R, ""), "pct_valor_no_corte": ("% do valor", P, ""),
    "meses_cobertos": ("Meses completos no Portal", I, "Meses dos 12 em que o recebido do ente foi baixado por inteiro; "
                       "o banco conhecido só é comparado nesses meses"),
    "sancoes": ("Registros de sanção", I, ""), "unidades": ("Consultas", I, ""), "baixadas": ("Baixadas", I, ""),
    "com_falha": ("Com falha", I, ""), "sem_arquivo": ("Baixadas sem arquivo", I, ""),
    "obsoletas": ("Consultas da fila antiga", I, "Não entram nas somas"), "tipo_consulta": ("Tipo de favorecido (consulta)", T, ""),
    "cod_orgao_superior": ("Código do órgão superior", T, ""), "cod_orgao": ("Código do órgão", T, ""),
    "cod_ug": ("Código da UG", T, ""), "linhas_agregadas": ("Linhas somadas", I, ""),
    "linhas_unidades_legadas": ("Linhas de consultas antigas", I, ""),
    "linhas_de_bancos_excluidas": ("Linhas de bancos excluídas", I, ""),
    "valor_de_bancos_excluido": ("Valor de bancos excluído (R$)", R, ""),
    "pct_banco_conhecido": ("% com banco conhecido", P, "Parte do recebido com banco identificado"),
    "part_caixa_conhecido": ("% CAIXA no banco conhecido", P, ""),
    "conhecido_excede": ("Banco conhecido maior que recebido", B, "Contradição entre fontes: investigar"),
    "custodia_caixa": ("Custódia CAIXA (saldo) (R$)", R, ""), "part_caixa_painel": ("Participação CAIXA (instrumentos)", P, ""),
    "bolsa_familia_mes": ("Bolsa Família no mês (R$)", R, "Pago pela CAIXA no município (Portal da Transparência)"),
    "beneficiarios": ("Famílias beneficiárias", I, ""), "valor_por_beneficiario": ("Valor por família (R$)", R, ""),
    "recebido_12m_municipio": ("Recebido pelo município em 12 meses (R$)", R, "Soma dos CNPJs do município"),
    "valor_instrumentos": ("Valor em instrumentos (R$)", R, ""),
    "part_caixa_instrumentos": ("Participação CAIXA nos instrumentos", P, ""), "classe": ("Situação", T, ""),
    "prioridade": ("Prioridade CRM (0–100)", I, "Regra CRM-01"), "emendas_12m": ("Emendas pagas ao ente (R$)", R, ""),
    "alerta_conformidade": ("Alerta de conformidade", B, ""), "proxima_acao": ("Próxima ação sugerida", T, ""),
    "codigo_emenda": ("Emenda", T, ""), "codigo_documento": ("Documento", T, ""), "fase": ("Fase", T, ""),
    "doc_favorecido": ("CNPJ do favorecido", T, ""), "valor_detalhe": ("Valor no detalhe (R$)", R, ""),
    "valor_pago_doc": ("Valor pago (R$)", R, ""), "autor": ("Autor da emenda", T, ""), "tipo": ("Tipo", T, ""),
    "empenhado": ("Empenhado (R$)", R, ""), "liquidado": ("Liquidado (R$)", R, ""), "pago": ("Pago (R$)", R, ""),
    "resto_pago": ("Restos a pagar pagos (R$)", R, ""), "localidade": ("Localidade do gasto", T, ""),
    "numero": ("Número", T, ""), "funcao": ("Função", T, ""), "codigo": ("Código", T, ""),
    "orgao_superior": ("Órgão superior", T, ""), "ug": ("Unidade gestora", T, ""),
    "origem_tipo": ("Tipo de origem", T, ""), "origem": ("Origem", T, ""), "destino_tipo": ("Tipo de destino", T, ""),
    "destino": ("Destino", T, ""), "banco": ("Banco", T, ""),
    "tipo_pessoa": ("Tipo de favorecido", T, "Como o Portal classifica o CNPJ"),
    "compartilhado": ("Ordem paga a várias emendas", B, "Valor rateado entre as emendas"),
    "origem_id": ("Código de origem", T, "CNPJ ou nome"), "destino_id": ("Código de destino", T, "CNPJ ou nome"),
    "part_caixa_ente": ("CAIXA nos instrumentos do ente", P, ""), "ente_caixa": ("Ente da CAIXA", B, ""),
    "conjunto": ("Conjunto da API", T, ""), "campo": ("Campo", T, ""), "coluna_api": ("Coluna na API", T, ""),
    "obrigatorio": ("Obrigatório", B, ""), "encontrado": ("Encontrado", B, ""), "linhas": ("Linhas", I, ""),
    "duplicadas_identicas": ("Linhas repetidas removidas", I, ""), "chaves_conflitantes": ("Chaves com versões diferentes", I, ""),
    "data": ("Data", D, ""), "valor": ("Valor (R$)", R, ""), "cnpj": ("CNPJ", T, ""),
    "atividade": ("Atividade", T, ""), "resultado": ("Resultado", T, ""), "data_atividade": ("Data", D, ""),
    "data_proxima": ("Data da próxima ação", D, ""), "registrado_por": ("Registrado por", T, ""),
    "registrado_em": ("Registrado em", T, ""), "status": ("Status", T, ""), "responsavel": ("Responsável", T, ""),
    "observacao": ("Observação", T, ""),
})

for _per, _nome in (("dia", "dia anterior"), ("semana", "7 dias"), ("mes", "30 dias"), ("ano", "1 ano")):
    ROTULOS[f"saldo_{_per}_anterior"] = (f"Saldo há {_nome} (R$)", R, "")
    ROTULOS[f"var_{_per}"] = (f"Variação {_nome} (R$)", R, "")
    ROTULOS[f"var_{_per}_pct"] = (f"Variação {_nome} (%)", V, "")
    ROTULOS[f"ref_{_per}"] = (f"Data de comparação ({_nome})", T, "Dia com dado mais próximo")


def humanizar(col: str) -> str:
    c = str(col).replace("_", " ").strip()
    return c if c.isupper() else c[:1].upper() + c[1:]


# realces visuais das tabelas
MARCA_BANCO = {"CAIXA": "🟦", "BB": "🟨", "BNB": "🟥", "BASA": "🟩"}
TEXTO_BANCO = {"CAIXA": ("#005CA9", "#E8F1FA"), "BB": ("#7A6200", "#FFF6CC"), "BNB": ("#8C1D40", "#F8E9EF"),
               "BASA": ("#0B6E4F", "#E6F4EE")}
NOMES_FIXOS = ("nome_ente", "nome", "municipio", "recebedor", "nome_recebedor", "favorecido", "parlamentar", "orgao",
               "programa", "oferta", "risco", "destino")
VALOR_PRINCIPAL = ("saldo", "valor", "saldo_caixa", "potencial", "valor_12m", "recebido", "a_receber", "custodia")


def colunas_banco(df: pd.DataFrame) -> list[str]:
    """Colunas de texto que guardam o grupo do banco (CAIXA, BB…): ganham marca de cor nas tabelas."""
    out = []
    for c in df.columns:
        if "banco" not in str(c) or ROTULOS.get(str(c), ("", "texto"))[1] not in ("texto", T) \
                or df[c].dtype != object:
            continue
        v = df[c].dropna().astype(str)
        if len(v) and v.isin(list(MARCA_BANCO) + ["Outros", "outros", "Outros bancos", "(sem banco)"]).mean() >= .6:
            out.append(c)
    return out


def coluna_principal(df: pd.DataFrame) -> str | None:
    """A coluna de valor (R$) que vira barra dentro da célula: a de negócio mais importante, sem negativos."""
    brl = [c for c in df.columns if ROTULOS.get(str(c), ("", ""))[1] == "brl"
           and pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    ok = [c for c in brl if df[c].notna().any() and (df[c].dropna() >= 0).all() and df[c].max() > 0]
    if not ok:
        return None
    pref = [c for c in VALOR_PRINCIPAL if c in ok]
    return pref[0] if pref else max(ok, key=lambda c: df[c].max())


def rotular(df: pd.DataFrame, manter_cnpj: bool = True, realce: bool = True) -> tuple[pd.DataFrame, dict]:
    """Esconde colunas técnicas, renomeia para o nome de negócio e devolve a configuração de formato.
    Percentuais (0–1) viram barras 0–100%; valores em R$ ficam com separador brasileiro.
    Com `realce`: a coluna de valor principal vira barra na célula (com o número), a coluna de nome fica fixa à
    esquerda e o banco ganha uma marca de cor (🟦 CAIXA, 🟨 BB…)."""
    import streamlit as st  # import tardio: o resto do módulo não depende do Streamlit
    cols = [c for c in df.columns if c not in TECNICAS and (manter_cnpj or not str(c).startswith("cnpj"))]
    out = df[cols].copy()
    cfg, novos = {}, {}
    principal = coluna_principal(out) if realce and len(out) >= 3 else None
    fixa = next((c for c in NOMES_FIXOS if c in cols and out[c].dtype == object), None) if realce else None
    bancos = colunas_banco(out) if realce else []
    for c in bancos:
        out[c] = out[c].map(lambda v: f"{MARCA_BANCO[v]} {v}" if isinstance(v, str) and v in MARCA_BANCO else v)
    # rótulos repetidos (ex.: potencial e potencial_custodia) ganham sufixo
    vistos = {}
    for c in cols:
        r = ROTULOS.get(str(c), (humanizar(str(c)), "texto", ""))[0]
        novos[c] = f"{r} ({c})" if r in vistos else r
        vistos[r] = True
    for c in cols:
        _, tipo, ajuda = ROTULOS.get(str(c), (humanizar(str(c)), "texto", ""))
        rot = novos[c]
        ajuda = ajuda or None
        if tipo == "pct":
            out[c] = pd.to_numeric(out[c], errors="coerce") * 100
            cfg[rot] = st.column_config.ProgressColumn(rot, help=ajuda, format="%.0f%%", min_value=0, max_value=100)
        elif tipo == "var":
            out[c] = pd.to_numeric(out[c], errors="coerce") * 100
            cfg[rot] = st.column_config.NumberColumn(rot, help=ajuda, format="%+.1f%%")
        elif tipo == "vezes":
            out[c] = pd.to_numeric(out[c], errors="coerce")
            cfg[rot] = st.column_config.NumberColumn(rot, help=ajuda, format="%.1f×")
        elif tipo == "brl" and c == principal:
            try:
                cfg[rot] = st.column_config.ProgressColumn(rot, help=ajuda, format="localized", min_value=0,
                                                           max_value=float(out[c].max()))
            except Exception:                       # versão sem formatos prontos na barra
                cfg[rot] = st.column_config.NumberColumn(rot, help=ajuda, format="localized", step=1)
        elif tipo in ("brl", "int"):
            cfg[rot] = st.column_config.NumberColumn(rot, help=ajuda, format="localized", step=1)
        elif tipo == "bool":
            cfg[rot] = st.column_config.CheckboxColumn(rot, help=ajuda)
        elif c == fixa:
            try:
                cfg[rot] = st.column_config.TextColumn(rot, help=ajuda, pinned=True)
            except TypeError:
                cfg[rot] = st.column_config.TextColumn(rot, help=ajuda)
        elif ajuda:
            cfg[rot] = st.column_config.TextColumn(rot, help=ajuda)
    return out.rename(columns=novos), cfg


def sem_rotulo(colunas) -> list[str]:
    return [c for c in colunas if str(c) not in ROTULOS and str(c) not in TECNICAS]
