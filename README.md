# Painel de Custódia · Transferegov

Painel interno para acompanhar a custódia de recursos de transferências federais (CAIXA × concorrência)
e priorizar a prospecção de entes públicos. Fases 0 e 1 do roteiro: carga diária com histórico, motores de
custódia e painel executivo com login.

## O que está pronto

| Parte | Conteúdo |
| --- | --- |
| Ingestão | Transferências Especiais e Fundo a Fundo pela API (paginação em paralelo, novas tentativas, conferência de contagem, alerta de mudança de esquema); Discricionárias pelos CSVs (baixa só o que mudou, pelo ETag); Siconfi (CNPJ ↔ IBGE, população) e coordenadas dos municípios |
| Histórico | Foto diária das tabelas-chave (planos, executores, saldos, contas FaF) gravando só o que mudou (SCD2), e série diária de participação e saldo por banco |
| Motores | Participação, custódia com cobertura, fluxo a creditar, vazamento, perfil e rotação de banco por ente, janelas de oportunidade, score de prospecção 0–100, alertas do dia, qualidade |
| Painel | 14 telas na ordem do dinheiro: Cockpit executivo (filtros de entes por modalidade, banco, segmento, UF, esfera, porte e ação; mapa do Brasil com estados coloridos e uma bolha por ente; fluxo modalidade → banco → destino; roscas e rankings; leituras automáticas) · Fluxo do dinheiro · Transferência secundária FaF · Mapa e território (Brasil → UF → município → ente, mapa coroplético IBGE, treemap, evolução, fluxo por nível) · Concorrência · Parlamentares · Ministérios e programas · Destinação · Fornecedores e pagamentos · Potencial e ações · Oportunidades (carteira) · Ficha do ente · Conformidade · Qualidade; login com perfis; exportação Excel/CSV |
| Fluxo do dinheiro | Origem (órgão, programa, parlamentar) → destinação (área, natureza) → banco da conta → banco de quem recebe; fornecedores; velocidade empenho → pagamento; potencial por ente e ação recomendada |
| Visual | Identidade CAIXA (azul/laranja), cartões de indicador, gráficos Plotly (mapa, Sankey, treemap, roscas, barras empilhadas, quadrante valor × participação). Toda tabela passa pela camada semântica: nome de negócio, formato R$/%/número e explicação em cada coluna; colunas técnicas não aparecem (um teste garante isso) |
| Gestor de custódia (v0.4) | Menu por seções; 12 telas novas: Radar de risco, Permanência e rentabilidade, Evolução do saldo (dia/semana/mês/ano), Dinheiro a receber, Matriz de escolhas, Entes perdidos, Venda cruzada, Priorização e cenários, Assessor do ente, Perguntas de negócio, Regras e premissas, Repositório de dados. Gráficos ECharts (velocímetro, radar, matriz de calor, funil, quadrante) e tabelas AgGrid (filtro e ordenação por coluna) |
| Regras de negócio | `config/regras.yaml`: cada regra com código, parâmetros e base; as telas citam o código. Perguntas de negócio em `config/perguntas.yaml` |
| Repositório | Todas as tabelas baixadas no histórico de mudanças, com verificação diária de que o dia reconstruído é idêntico à fonte (QLD-02); série diária de saldo por ente (variações dia/semana/mês/ano); foto completa mensal (API com todas as colunas + CSVs originais); `reconstruir_dia.bat AAAA-MM-DD` recria qualquer dia; registro de cargas e catálogo |
| Saldo interno CAIXA | Desde 30/04/2025 a API não traz extrato das contas CAIXA das Transferências Especiais. O painel grava `data/internos/contas_caixa_para_consulta.csv`; um `saldos_caixa*.csv` (agencia;conta;saldo;data_saldo) na mesma pasta substitui o saldo público |
| Janela de escolha e relacionamento (v0.5) | Repasses no momento de escolha do banco (5 estágios), tendência pelo histórico do ente e do parlamentar, matriz estágio × tendência, calendário das escolhas; radar com troca de banco, queda de participação, parlamentares e órgãos migrando, e entes/agentes que não direcionam à CAIXA com motivos prováveis; mapa ECharts (zoom, legenda deslizante, clique para detalhar; bolhas por município); contagem por município (código IBGE) e tipo de ente |
| Auditoria diária | A cada carga, 8 famílias de checagem sobre a carga bruta (completude, estrutura, chaves, domínios, integridade, coerência, frescor, reconciliação com o painel); tela Auditoria da carga e relatório em `data/auditoria/relatorio_AAAA-MM-DD.html`. Avulso: `auditar_carga.bat` |
| Outros repasses (v0.6) | Tela "FUNDEB, saúde, educação e assistência". FUNDEB e FPM pela API do Tesouro (diária); saúde pela Consulta FNS com banco, conta e último saldo de cada fundo (semanal, pode levar 15–30 min); educação (FNDE) e assistência social (FNAS) pelo arquivo mensal do Portal da Transparência (semanal; meses fechados baixam uma vez). Só a saúde publica o banco: as demais entram como volume por município. Regra SAU-01: fundos de saúde com saldo no concorrente. Liga e desliga no bloco `outras_fontes` de `config/config.yaml`; se uma fonte falhar, a carga segue |
| Visual (v0.7) | Mapa novo em deck.gl (pydeck, já vem com o Streamlit): enquadra o Brasil ou a UF automaticamente, cores por faixas (quantis; participação CAIXA em vermelho → azul), siglas das UFs, bolhas por município, dica ao passar o mouse, clique para descer Brasil → UF → município, legenda abaixo, sem mapa de ruas da internet (opcional: `painel.mapa_fundo: light` no config.yaml). Tema novo (`.streamlit/config.toml`): barra lateral azul-marinho, fundo cinza-azulado com cartões brancos; cabeçalho, cartões com variação, seções, tabelas e gráficos com o mesmo acabamento |
| CRM (v0.8) | Seção CRM: Funil e agenda (etapas da carteira, agenda da equipe, lista pela prioridade CRM-01), Visão 360 do ente (recebido da União em 12 meses pelo Portal da Transparência, partes com banco conhecido, emendas e parlamentares, Bolsa Família pago pela CAIXA no município, fornecedores, conformidade, atividades), Rede de relacionamento (parlamentar → ente → banco → fornecedor → sanção) e Conformidade (CEIS, CNEP, CEPIM). Dados pela API do Portal (chave pessoal em `config/segredos.yaml`, linha `portal_api_chave: ...`); a fila baixa cada consulta uma vez, respeita o limite da API e retoma na noite seguinte. `sondar_portal.bat` testa a API e mostra os campos reais. Atividades ficam no banco da carteira (histórico nunca sobrescrito) |
| CRM (v0.8.3) | Correções da 1ª carga real: recursos pedidos por tipo de favorecido (prefeituras/estados/entidades; pessoas físicas e empresas não são baixadas), 4 consultas em paralelo dentro do limite, consulta cortada vira falha (não grava pela metade), lançamentos do mesmo órgão no mês somados pelos códigos, bancos fora da carteira, "banco conhecido" só nos meses completos (coluna Meses completos), alertas CON-01/02/03 sem dupla contagem (um pagamento conta uma vez mesmo com várias sanções ou nas duas fontes), datas ISO × brasileiras lidas sem trocar dia e mês (inclusive no calendário de escolha do banco) |
| Desempenho e interação (v0.9) | Dados abertos sob demanda e sem cópia a cada clique (antes o cache copiava todos os marts e travava a página); cálculos memorizados; tabelas grandes com busca, ordenação e páginas (todas as linhas acessíveis e no download); seletores de ente com busca; tempo de cada tela em `data/logs/telas.csv`. Filtro por clique: clicar numa barra ou fatia filtra todas as telas (etiquetas no topo, clique para retirar). Mapa: faixas de participação CAIXA (forte/fraca), valor mínimo, filtros de ente e de CRM aplicados juntos, camada de oportunidades CRM, rankings clicáveis (mais/menos CAIXA, oportunidades, sem banco) e "Indicações para o CRM" (abrir Visão 360 ou incluir na carteira). Rede: nomes no lugar de CNPJ, resumo 80/20 e rede completa. Fluxo do dinheiro: leituras automáticas e conferência das somas em cada etapa, vazamento e entrada na CAIXA, recebedores fora da CAIXA. Permanência: média só com o que foi medido (corrigido BB/BNB marcados como extrato parado) |
| Auditoria profunda (v0.9.1) | Motor `auditoria_profunda` na carga e tela própria: totais refeitos em SQL (SQLite) e comparados ao painel, Benford (transacional × por fórmula), extremos robustos, duplicidades pelo identificador da fonte e rede neural (autoencoder em numpy) de entes atípicos, validada a cada carga com anomalias plantadas e 5 inicializações. Correções da auditoria de 01/11 sobre os dados reais: saldo do Fundo a Fundo contado em dobro em permanência/variação/defasagem (R$ 764,7 mi), BB das Especiais marcado como extrato parado, vazamento das contas CAIXA (R$ 15,0 bi → R$ 5,9 bi comprovados), comparação entre bancos na mesma janela, prioridade CRM-01 (percentil inflado, presença sem diferenciar, emendas fora dos 12 meses), Portal tratado como tudo o que o ente recebe (cobre ~6% das transferências aos municípios), pagamentos do FaF sem ente pagador, transferência secundária de 335 fundos fora do mapa, downloads montados a cada abertura de tela |
| Conciliação entre equipes e visual (v0.9.2) | Duas equipes de análise independentes (uma em pandas, outra em SQL) responderam às mesmas 15 perguntas sem ver o painel nem uma à outra; as diferenças viraram correções: aplicações "APL AUTOM"/"APL FUNDO" (R$ 8,6 bi) e emissão de ordem bancária (R$ 1,06 bi) classificadas errado; retenção no próprio banco (BB ~46% × CAIXA ~16% do pago a terceiros) na comparação justa; minutas de empenho (R$ 3,9 bi) e propostas sem convênio assinado (R$ 9,3 bi) separadas do dinheiro firme a receber (regra REC-04); conta sem número que casava saldo com o ente errado (R$ 118,7 mi) e saldo sem vínculo que sumia (R$ 81 mi); permanência do banco que parou medida na própria janela, conta sem saída em 12 meses como dinheiro parado e média por estoque ÷ fluxo; saldo do FNS identificado como das contas dos blocos antigos; 276 pagamentos do FNS repetidos; BNB das Especiais deixou de aparecer como fonte interrompida. Visual: o X da CAIXA na entrada, no cabeçalho e na barra lateral; tabelas com barra no valor principal, nome fixo e banco com marca de cor. Telas que respondiam à mesma pergunta viraram visões de uma tela só (Visão 360 + Assessor + Ficha; Conformidade; Oportunidades; Qualidade e auditoria): menu de 33 para 28 itens (34 para 28 no perfil gestão), nada removido |
| Saldo reconstituído e veracidade (v0.9.3) | Regra SAL-01: onde o extrato parou (CAIXA nas Especiais), cada saldo aparece duas vezes, o ESTIMADO de hoje (com faixa) e o PARADO (último publicado, com a data, em destaque). A reconstituição usa créditos publicados (ordens bancárias, que batem ao centavo com o "pago" no Portal da Transparência), saídas pela curva de execução do próprio banco e rendimento calibrado nos bancos que publicam; é testada a cada carga (calibração, validação fora da amostra e testes retroativos) e o teste fica em Qualidade e auditoria. Correções do red team de veracidade: só o valor CONTRATADO entra nos valores (anulados, cancelados, rescindidos, propostas sem assinatura e planos impedidos ficam fora, em fato_instrumento_fora); um lançamento isolado não reabre banco parado; FPM sem banco inventado; fonte ausente não vira zero; banco inferido e estimativas com rótulo; potencial documentado (POT-01); textos sem datas fixas |
| Em desenvolvimento | Gestão de Parcerias, TED e a API de Discricionárias aparecem no painel com esse aviso |

## Instalação (Windows, uma vez)

1. Instale o **Python 3.12** em python.org, marcando **Add python.exe to PATH**.
2. O código fica em `OneDrive\DASH TRANSFEREGOV` (só arquivos pequenos). O ambiente Python vai para
   `%LOCALAPPDATA%\PainelCustodia\venv` e os dados para `C:\PainelCustodia\data`, fora do OneDrive,
   para não sincronizar gigabytes. Para mudar o local dos dados, edite `dados.pasta` em `config/config.yaml`.
3. Dê dois cliques em **`instalar.bat`**. Ele cria o ambiente, instala as bibliotecas, roda os testes,
   testa a conexão com as fontes e pede o login e a senha do primeiro administrador.

## Uso diário

| Arquivo | Para quê |
| --- | --- |
| `carga_diaria.bat` | Baixa tudo e recalcula os indicadores. A primeira carga leva de 20 a 60 minutos. |
| `agendar_carga.bat` | Agenda a carga para 13h05, todos os dias (as fontes atualizam entre 0h e 12h). |
| `iniciar_painel.bat` | Abre o painel em http://localhost:8501 |
| `novo_usuario.bat` | Cadastra alguém da equipe (perfis: gestao, comercial, administrador) |
| `diagnostico.bat` | Testa a conexão com cada fonte |

O histórico começa no dia da primeira carga. Quanto antes a carga diária estiver agendada, mais
tendência o painel terá para mostrar.

## Acesso da equipe

O painel roda no seu computador e fica disponível enquanto ele estiver ligado.

1. Instale o **Tailscale** (ou Cloudflare Tunnel) no seu computador e no de cada pessoa da equipe.
2. Em `.streamlit/config.toml`, troque `address = "localhost"` por `address = "0.0.0.0"`.
3. A equipe acessa `http://<nome-do-seu-computador>:8501` e entra com o próprio login.

Antes disso, confirme com a área de TI e de conformidade da CAIXA se o uso do Tailscale e de dados
públicos para prospecção está de acordo com as normas internas.

## Como os números são calculados

- **Participação**: valor dos planos e convênios cuja conta está na CAIXA ÷ valor de todos os que já têm banco.
- **Saldo publicado**: último saldo informado pela API para cada conta. A coluna **cobertura** mostra
  quantas contas daquele banco têm saldo publicado; abaixo de 50%, leia o número como estimativa.
  Hoje a API publica saldo de 93% das contas do BB e de 30% das contas da CAIXA nas Especiais.
- **A creditar**: valor empenhado que ainda não virou ordem bancária (Especiais).
- **Vazamento**: plano com conta na CAIXA cujo executor recebe em outro banco.
- **Para onde vai**: débitos das contas das Especiais (`gestao-financeira-lancamentos-especiais`), separados em
  aplicação/resgate, tributos e pagamentos; o banco de quem recebe vem do lançamento. Transferência para o próprio
  ente é identificada pelo nome (o documento vem mascarado).
- **Potencial**: saldo hoje no concorrente + metade do que ainda vai ser creditado lá + janelas abertas.
  Resultado estimado = potencial × `taxa_referencia_aa` × `fracao_resultado` (config.yaml). Ordem de grandeza, não cálculo oficial.
- **Discricionárias**: o CSV de propostas traz só o NOME do banco; linhas com `;` dentro do endereço/objeto são
  reparadas na leitura (contagem na tela Qualidade).
- **Score**: soma ponderada (pesos em `config/config.yaml`) de emendas recentes no concorrente, saldo no
  concorrente, janelas abertas, ente multibanco e vazamento. O Fundo a Fundo fica fora do score e das
  janelas, porque a conta é sempre do BB.

## Estrutura

```
telas/                telas Streamlit (Inicio.py + pages/)
custodia/
  ingest_api.py       conector genérico das APIs (mesmo contrato nos 5 módulos)
  ingest_csv.py       CSVs de Discricionárias por ETag
  historico.py        SCD2 e série diária
  marts.py            fatos e dimensões (ente = CNPJ)
  motores.py          inteligência de custódia
  motores_fluxo.py    fluxo do dinheiro, parlamentares, órgãos, potencial, transferência secundária FaF
  motores_territorio.py resumo por ente (mapa) e UF × modalidade
  semantica.py        nomes, formatos e cores de cada coluna, modalidade e banco
  ui.py               identidade visual, cartões e gráficos
  consultas.py        consultas das telas
  qualidade.py        checagens da carga
  pipeline.py         orquestração (python -m custodia.pipeline)
  acesso.py           usuários e carteira da equipe (SQLite)
config/config.yaml    endpoints, pesos do score, limites
data/                 bruto (Parquet), histórico, marts publicados, logs  (criada na carga)
tests/                API simulada e testes de ponta a ponta
```

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Diagnóstico diz "Resposta não é JSON" ou HTTP 403 | O Cloudflare da API pode estar bloqueando o acesso a partir da rede corporativa. Teste fora da rede da CAIXA; se funcionar, peça à TI liberação para `api-publica.transferegov.gestao.gov.br`. |
| Erro de certificado (SSL) na rede corporativa | O proxy da empresa inspeciona HTTPS. Peça à TI o certificado raiz e defina `REQUESTS_CA_BUNDLE` apontando para ele. |
| Carga demorou demais ou caiu no meio | Rode de novo: os dados já baixados no dia são reaproveitados no `--so-transformar`. Reduza `conexoes` no `config.yaml` se houver muitos HTTP 429. |
| Painel diz "Ainda não há dados" | Rode `carga_diaria.bat` e recarregue. |
| Erro `format="localized"` ou tabela sem formato | Atualize o Streamlit: rode `instalar.bat` de novo (precisa da versão 1.42 ou mais nova). |
| Gráficos não aparecem, só tabelas | Falta o Plotly: rode `instalar.bat` de novo. |
| Telas aparecem duplicadas no menu | Apague a pasta antiga `app` e abra pelo `iniciar_painel.bat` (que usa `telas\app.py`). |
| Gráficos simples em vez dos novos / tabela sem filtros por coluna | Faltam `streamlit-echarts` ou `streamlit-aggrid`: rode `instalar.bat` de novo. O painel funciona sem eles, com gráficos mais simples. |

## Testes

`%LOCALAPPDATA%\PainelCustodia\venv\Scripts\python -m pytest -q` roda a carga completa duas vezes contra uma API simulada e executa
todas as telas.
