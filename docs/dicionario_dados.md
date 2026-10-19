# Dicionário de dados

Tabelas das camadas Silver (`data/silver/`) e Gold (`data/gold/`), em Parquet.
Fontes, URLs, licenças e data de coleta estão no [README](../README.md#fontes).

Convenções:
- `cod_ibge` é sempre o código de município do IBGE com 7 dígitos, como texto (`1500107`).
- Mês é escrito como texto `AAAA-MM`, no horário de Belém (America/Belem, UTC-3).
- Colunas que começam com `_` são metadados técnicos herdados da Bronze.

---

## Silver

### dim_municipio

Uma linha por município do Pará. PK: `cod_ibge`. 144 linhas.
Origem: API de Localidades do IBGE (Bronze `ibge_municipios_pa`).

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `cod_ibge` | texto | 7 dígitos começando com `15`; 144 valores únicos | campo `id` | Código IBGE do município |
| `nome` | texto | 144 valores únicos | campo `nome` | Nome oficial, com acentos |
| `nome_normalizado` | texto | maiúsculas, sem acento e sem pontuação; 144 valores únicos | derivado de `nome` | Chave do join com o INPE nos anos em que o INPE não traz código |
| `regiao_intermediaria` | texto | 7 regiões (Belém, Castanhal, Marabá, Redenção, Santarém, Altamira, Breves) | campo `regiao-imediata` | Região geográfica intermediária do IBGE (divisão de 2017) |

### ibge_indicador_anual

Uma linha por município por ano, de 2013 a 2025. PK: (`cod_ibge`, `ano`). 1.872 linhas.
Origem: API do SIDRA (Bronze `ibge_populacao`, `ibge_rebanho_bovino`, `ibge_pib_municipal`).

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `cod_ibge` | texto | presente em `dim_municipio` | SIDRA `D1C` | Município |
| `ano` | inteiro | 2013 a 2025 | SIDRA `D3C` | Ano de referência do dado (não é o ano de publicação) |
| `populacao` | decimal | > 0 (3.200 a 1.506.420) | tabela 6579, variável 9324 | População residente estimada |
| `rebanho_bovino` | inteiro | ≥ 0 | tabela 3939, variável 105, classificação 79/2670 | Efetivo de bovinos (cabeças). O símbolo `-` do SIDRA (zero absoluto) vira 0 |
| `pib_mil_reais` | decimal | > 0; vazio em 2024 e 2025 | tabela 5938, variável 37 | PIB a preços correntes, em mil reais. Vazio onde o IBGE ainda não publicou |
| `populacao_imputada` | booleano | `True` em 2022 e 2023 (288 linhas) | derivado | A tabela 6579 não tem 2022 e 2023; o valor repete o último ano conhecido (2021) |

Por que repetir 2021 e não interpolar: interpolar 2022 usaria a estimativa de 2024, que ainda não existia em 2022.

### foco_calor

Uma linha por foco de calor detectado no Pará pelo satélite de referência (AQUA_M-T). PK: `id_foco`. 472.088 linhas.
Origem: INPE Programa Queimadas (Bronze `inpe_focos_anual`, `inpe_focos_mensal`, `inpe_focos_diario`).

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `id_foco` | texto | 16 caracteres hexadecimais, único | hash de satélite + data/hora UTC + lat + lon | Identificador do foco. Não usa o id do INPE porque ele pode mudar entre o arquivo diário e o mensal |
| `id_inpe` | texto | — | `foco_id` (anual) ou `id` (mensal/diário) | Identificador original do INPE, mantido para rastreio |
| `lat` | decimal | -9,95 a 2,70 | `lat` | Latitude do foco |
| `lon` | decimal | -59,00 a -45,95 | `lon` | Longitude do foco |
| `data_hora_utc` | data/hora UTC | 2013-01-01 em diante | `data_pas` (anual) ou `data_hora_gmt` | Momento da passagem do satélite |
| `data_hora_local` | data/hora America/Belem | — | derivado | Mesmo momento no horário de Belém |
| `data_local` | data | — | derivado | Dia no horário de Belém |
| `ano_mes` | texto `AAAA-MM` | — | derivado | Mês no horário de Belém. Um foco às 01h UTC do dia 1º pertence ao mês anterior |
| `ano` | inteiro | 2013 a 2026 | derivado | Ano no horário de Belém |
| `municipio` | texto | 144 valores | `municipio` | Nome do município como veio do INPE |
| `cod_ibge` | texto | presente em `dim_municipio` | `municipio_id` (2026) ou join por nome (2013-2025) | Município do foco |
| `estado` | texto | `PARÁ` | `estado` | UF do foco |
| `satelite` | texto | `AQUA_M-T` ou vazio | `satelite` | Vazio em 2013-2025: os arquivos anuais já são só do satélite de referência e não trazem a coluna |
| `bioma` | texto | — | `bioma` | Bioma do foco |
| `dias_sem_chuva` | decimal | ≥ 0; vazio em 2013-2025 | `numero_dias_sem_chuva` | Só existe nos arquivos de 2026. -999 da fonte vira vazio |
| `precipitacao` | decimal | ≥ 0; vazio em 2013-2025 | `precipitacao` | Só existe em 2026 |
| `risco_fogo` | decimal | 0 a 1; vazio em 2013-2025 | `risco_fogo` | Só existe em 2026 |
| `frp` | decimal | ≥ 0; vazio em 2013-2025 | `frp` | Potência radiativa do fogo (MW). Só existe em 2026 |
| `origem` | texto | `inpe_focos_anual`, `inpe_focos_mensal`, `inpe_focos_diario` | derivado | Dataset da Bronze de onde veio a linha |
| `_ingested_at`, `_source_system`, `_source_object`, `_load_id`, `_record_hash` | texto | — | Bronze | Metadados técnicos; `_record_hash` liga a linha à linha bruta da Bronze |

---

## Gold

### focos_municipio_mes

Uma linha por município por mês, de 2013-01 até o último mês completo (2026-09). PK: (`cod_ibge`, `ano_mes`). 23.760 linhas.
Origem: Silver `foco_calor` e `dim_municipio`.

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `cod_ibge` | texto | presente em `dim_municipio` | `dim_municipio` | Município |
| `ano_mes` | texto `AAAA-MM` | 2013-01 a 2026-09 | grade de meses | Mês |
| `ano` | inteiro | 2013 a 2026 | derivado | Ano |
| `mes_num` | inteiro | 1 a 12 | derivado | Mês do calendário |
| `n_focos` | inteiro | ≥ 0 (10.618 linhas com zero) | contagem em `foco_calor` | Focos do satélite de referência no município e mês |

### ml_base

Uma linha por município por t0 (último dia de cada mês M). PK: (`cod_ibge`, `t0_ano_mes`). 22.176 linhas.
Origem: Gold `focos_municipio_mes` e Silver `ibge_indicador_anual`. Definições em [ml_ready.md](ml_ready.md).

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `cod_ibge` | texto | presente em `dim_municipio` | — | Município |
| `t0_ano_mes` | texto `AAAA-MM` | 2013-12 a 2026-09 | — | Mês M do ponto de corte |
| `t0_data` | data | último dia de M | derivado | Instante em que o conhecimento é congelado |
| `mes_alvo` | texto `AAAA-MM` | M+1 | derivado | Mês que está sendo previsto |
| `particao` | texto | `treino`, `validacao`, `teste`, `previsao` | regra de split | Partição temporal, definida pelo mês-alvo |
| `focos_m0` | inteiro | ≥ 0 | `n_focos` em M | Focos no mês do t0 |
| `focos_m1`, `focos_m2` | decimal | ≥ 0 | `n_focos` em M-1 e M-2 | Focos nos dois meses anteriores |
| `focos_3m` | decimal | ≥ 0 | soma de M-2 a M | Focos nos últimos 3 meses |
| `focos_12m` | decimal | ≥ 0 | soma de M-11 a M | Focos nos últimos 12 meses |
| `focos_mes_alvo_ano_anterior` | decimal | ≥ 0 | `n_focos` em M-11 | Focos no mesmo mês do calendário que o mês-alvo, um ano antes |
| `media_hist_mes_alvo` | decimal | ≥ 0 | média de M-11, M-23, ... | Média do mês-alvo em todos os anos anteriores |
| `mes_alvo_sin`, `mes_alvo_cos` | decimal | -1 a 1 | mês de M+1 | Sazonalidade em forma circular (dezembro fica perto de janeiro) |
| `populacao` | decimal | > 0; vazio em t0 de 2013 | `ibge_indicador_anual`, ano do t0 - 1 | População, com 1 ano de defasagem de publicação |
| `rebanho_bovino` | decimal | ≥ 0; vazio em t0 até 2014 | ano do t0 - 2 | Bovinos, com 2 anos de defasagem |
| `bovinos_por_habitante` | decimal | ≥ 0 | ano do t0 - 2 | Rebanho / população do mesmo ano |
| `pib_per_capita` | decimal | > 0; vazio em t0 até 2015 | ano do t0 - 3 | PIB × 1000 / população do mesmo ano, com 3 anos de defasagem |
| `alvo_n_focos` | decimal | ≥ 0; vazio na partição `previsao` | `n_focos` em M+1 | **Futuro.** Fonte do label; nunca é feature |
| `critico` | inteiro 0/1 | vazio na partição `previsao` | `alvo_n_focos >= 39` | **Label.** 1 = mês seguinte crítico |

Metadados da tabela (limiar, split, defasagens, lista de features) em `data/gold/ml_base_meta.json`.

### ranking_prioridade

Uma linha por município para o t0 mais recente (2026-09, prevendo 2026-10). PK: `cod_ibge`. 144 linhas.
Origem: modelo em `src/ml/modelo.py` aplicado à partição `previsao` da `ml_base`.

| Coluna | Tipo | Domínio válido | Origem | Significado |
|---|---|---|---|---|
| `posicao` | inteiro | 1 a 144 | ordenação por `score` | Prioridade do município |
| `cod_ibge`, `nome`, `regiao_intermediaria` | texto | — | `dim_municipio` | Município |
| `t0_ano_mes` | texto | 2026-09 | `ml_base` | Ponto de corte usado |
| `mes_alvo` | texto | 2026-10 | `ml_base` | Mês previsto |
| `score` | decimal | 0 a 1 | modelo | Probabilidade estimada de mês crítico |
| `top_15` | booleano | 15 linhas `True` | `posicao <= 15` | Recebe equipe no mês-alvo |
| `focos_m0`, `focos_mes_alvo_ano_anterior`, `media_hist_mes_alvo` | decimal | ≥ 0 | `ml_base` | Features principais, para explicar o ranking |
