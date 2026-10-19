# Queimadas no Pará: da ingestão à decisão

Pipeline de dados (Bronze, Silver e Gold) que cruza os focos de calor do INPE com indicadores municipais do IBGE para responder uma pergunta operacional: **quais municípios do Pará devem receber brigadas de prevenção no mês que vem?**

Todo mês, o pipeline gera um ranking dos 144 municípios pelo risco de terem um mês crítico (39 focos ou mais) no mês seguinte. Os 15 primeiros são a recomendação de onde posicionar as equipes. A decisão, os números e as limitações estão em [docs/decisao.md](docs/decisao.md).

Projeto Integrador da disciplina de Ciência de Dados, Ciência da Computação, CESUPA.

## Integrantes

- Caio Augusto (GitHub: caioaugustofb)
- Pedro Augusto (GitHub: callilpedro)

## Como executar do zero

Requer Python 3.11 ou mais novo (testado no 3.13) e conexão com a internet. Os dados não ficam no Git: o pipeline baixa tudo.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Depois, na raiz do repositório, rode o pipeline inteiro com um comando:

```bash
python -m scripts.run_pipeline
```

Ou cada etapa separada, na mesma ordem:

```bash
python -m src.ingestion.run_bronze   # baixa INPE e IBGE para data/bronze (alguns minutos)
python -m src.silver.run_silver      # limpa, tipa e cruza (data/silver)
python -m src.gold.run_gold          # tabelas da decisão e base do modelo (data/gold)
python -m src.ml.modelo              # treina, avalia e gera o ranking do próximo mês
```

Testes offline da ingestão (sem internet, com um servidor HTTP falso):

```bash
python -m unittest discover -s tests -v
```

**Idempotência:** rodar `run_bronze` duas vezes seguidas não duplica nada. Na segunda vez tudo aparece como `skipped`, porque o manifesto em `data/_state/` reconhece os arquivos e respostas já carregados. A Silver e a Gold são reconstruídas inteiras a partir da camada anterior, então rodar de novo produz o mesmo resultado.

## Estrutura

```
src/
  common/      funções da Bronze: metadados, retry, quarentena, manifesto e checkpoint
  ingestion/   ingestão do INPE (anual, mensal, diário) e do IBGE (API)
  silver/      dim_municipio, ibge_indicador_anual, foco_calor
  gold/        focos_municipio_mes, ml_base
  ml/          modelo, avaliação e ranking
scripts/       run_pipeline.py: executa Bronze, Silver, Gold e modelo em ordem
notebooks/     exploração e resultados (só lê as tabelas geradas)
tests/         testes offline da Bronze
docs/          dicionário de dados, ML-Ready, decisão, ingestão, figuras
data/          gerado pelo pipeline, fora do Git (bronze, silver, gold, quarantine, _state, raw)
```

## Camadas e tabelas

| Camada | Tabela | Granularidade | Chave |
|---|---|---|---|
| Bronze | `inpe_focos_anual`, `inpe_focos_mensal`, `inpe_focos_diario` | uma linha por linha do CSV de origem | `_record_hash` |
| Bronze | `ibge_municipios_pa`, `ibge_populacao`, `ibge_rebanho_bovino`, `ibge_pib_municipal` | uma linha por registro da resposta da API | `_record_hash` |
| Silver | `dim_municipio` | uma linha por município do Pará | `cod_ibge` |
| Silver | `ibge_indicador_anual` | uma linha por município por ano | `cod_ibge`, `ano` |
| Silver | `foco_calor` | uma linha por foco no Pará (satélite de referência) | `id_foco` |
| Gold | `focos_municipio_mes` | uma linha por município por mês | `cod_ibge`, `ano_mes` |
| Gold | `ml_base` | uma linha por município por t0 (fim de mês) | `cod_ibge`, `t0_ano_mes` |
| Gold | `ranking_prioridade` | uma linha por município para o próximo mês | `cod_ibge` |

Toda tabela da Silver e da Gold tem a PK verificada por código (`checks.check_no_duplicates`) a cada execução. Colunas, tipos e domínios: [docs/dicionario_dados.md](docs/dicionario_dados.md).

## Fontes

Dados coletados em **19/10/2026**.

| Fonte | Instituição | O que usamos | Formato | Forma de ingestão | URL |
|---|---|---|---|---|---|
| Focos de calor, satélite de referência, 2013 a 2025 | INPE, Programa Queimadas | focos anuais do Brasil | CSV dentro de ZIP | arquivo | https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/ |
| Focos de calor, 2026 (meses fechados) | INPE, Programa Queimadas | focos mensais, todos os satélites | CSV | arquivo | https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/ |
| Focos de calor, mês corrente | INPE, Programa Queimadas | focos diários, todos os satélites | CSV | incremental com checkpoint | https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/Brasil/ |
| Municípios do Pará | IBGE, API de Localidades | código, nome e região | JSON | API REST | https://servicodados.ibge.gov.br/api/v1/localidades/estados/15/municipios |
| População residente estimada | IBGE, SIDRA tabela 6579 | variável 9324 | JSON | API REST, um pedido por ano | https://apisidra.ibge.gov.br/values/t/6579 |
| Efetivo de bovinos (PPM) | IBGE, SIDRA tabela 3939 | variável 105, classificação 79/2670 | JSON | API REST, um pedido por ano | https://apisidra.ibge.gov.br/values/t/3939 |
| PIB dos municípios | IBGE, SIDRA tabela 5938 | variável 37 | JSON | API REST, um pedido por ano | https://apisidra.ibge.gov.br/values/t/5938 |

**Licenças.** As duas fontes são dados públicos do governo federal, de acesso aberto e sem cadastro. Os portais permitem o uso desde que a fonte seja citada (Fonte: INPE, Programa Queimadas; Fonte: IBGE). Não encontramos um termo de licença formal (como Creative Commons) publicado nos portais do INPE Queimadas e da API do SIDRA.

**Chave de cruzamento:** código IBGE do município (7 dígitos) e mês. Os arquivos anuais do INPE (2013 a 2025) não trazem o código, só o nome do município. Nesses anos o cruzamento é feito pelo nome normalizado (sem acento, em maiúsculas). Resultado do join:
- **144 de 144** municípios do INPE casaram com o IBGE, **0 órfãos**;
- **472.088 focos** do Pará com município atribuído e **0 focos na quarentena**;
- nos dados de 2026, que trazem os dois campos, o código obtido pelo nome bate com o código do INPE em 100% dos casos (0 divergências).

## Números do pipeline

| Etapa | Resultado |
|---|---|
| Bronze | 2.455.276 linhas anuais, 2.007.259 mensais e 625.516 diárias do INPE (Brasil inteiro); 144 municípios e 5.040 registros do SIDRA |
| Silver `foco_calor` | 4.064.460 focos fora do Pará e 551.502 de satélites que não são o de referência saem da tabela; 1 duplicata removida; 472.088 focos finais |
| Silver `ibge_indicador_anual` | população de 2022 e 2023 imputada com o valor de 2021 (a tabela não tem esses anos); PIB de 2024 e 2025 ainda não publicado |
| Gold `focos_municipio_mes` | 23.760 linhas (144 municípios × 165 meses), 10.618 com zero foco; 6.844 focos de out/2026 fora, porque o mês ainda não fechou |
| Gold `ml_base` | 22.176 linhas; label com 10% de positivos no treino |
| Modelo | regressão logística: no teste, cobre 48,7% das situações críticas com 15 equipes, contra 44,4% do baseline (o máximo possível é 52,0%) |

## Documentação

- [docs/decisao.md](docs/decisao.md): a frase da decisão, custos de erro, limiar, ranking de outubro e limitações
- [docs/ml_ready.md](docs/ml_ready.md): label, coorte, t0, janelas, split, baseline, métricas e checklist anti-vazamento
- [docs/dicionario_dados.md](docs/dicionario_dados.md): colunas de todas as tabelas da Silver e da Gold
- [docs/ingestao_bronze.md](docs/ingestao_bronze.md): detalhes da ingestão, idempotência e quarentena

## Uso de IA

Usamos ferramentas de IA generativa como apoio, e os dois integrantes revisaram e conseguem explicar todo o código entregue.

| Ferramenta | Onde | Para quê |
|---|---|---|
| Claude (Anthropic), via Claude Code | desenho do projeto, `src/silver/`, `src/gold/`, `src/ml/`, `docs/` | propor o cruzamento e a decisão, escrever e revisar o código da Silver, da Gold e do modelo, revisar a Bronze e redigir a documentação |

Os números deste README e dos documentos vêm das execuções do próprio pipeline.
