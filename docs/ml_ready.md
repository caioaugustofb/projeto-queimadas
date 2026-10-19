# Base ML-Ready e anti-vazamento

Tabela: `data/gold/ml_base.parquet`, gerada por `src/gold/ml_base.py`.
Modelo e avaliação: `src/ml/modelo.py`. Métricas completas: `data/gold/modelo_metricas.json`.

## Definições

| Elemento | Definição |
|---|---|
| **Label** | `critico = 1` quando o município tem **39 focos ou mais no mês seguinte ao t0** (mês M+1). O evento só é conhecido no fim de M+1 |
| **Regra de rotulagem** | `critico = alvo_n_focos >= 39`, onde `alvo_n_focos` é a contagem de focos do satélite de referência (AQUA_M-T) no município em M+1, no horário de Belém. O 39 é o percentil 90 de `alvo_n_focos` **calculado só na partição de treino** e congelado como número |
| **Coorte** | Os 144 municípios do Pará em todo t0 que tenha 12 meses completos de histórico (o primeiro t0 é dez/2013). Nenhum município foi excluído: Mojuí dos Campos, o mais novo, foi instalado em 2013 e existe na série inteira |
| **Ponto de corte (t0)** | Último dia de cada mês M, 23:59 no horário de Belém. Tudo que o modelo sabe vem de antes desse instante |
| **Janela de observação** | De M-11 a M para os focos (mais a média do mesmo mês em todos os anos anteriores). Para o IBGE, o último ano **já publicado** no t0 |
| **Janela de predição** | O mês M+1 inteiro |
| **Split** | Temporal, pelo mês-alvo: treino = alvo até dez/2021; validação = alvo de jan/2022 a dez/2023; teste = alvo de jan/2024 a set/2026; previsão = t0 set/2026 (alvo out/2026, ainda sem label) |
| **Baseline** | Persistência sazonal: o score do município é o número de focos que ele teve **no mesmo mês do ano anterior**. Também reportamos a persistência simples (focos do mês atual) |
| **Métrica** | **Recall no top-15 por mês**: das situações críticas, quantas caíram entre os 15 municípios priorizados. Reportamos também PR-AUC, precisão no top-15 e a fração dos focos que caíram no top-15 |

### Por que essas escolhas

- **Split só temporal, não por grupo.** A decisão é sobre os mesmos 144 municípios no futuro: o que precisa generalizar é o tempo, não a entidade. Por isso cada município aparece em treino e teste, mas sempre em meses diferentes e com o teste depois do treino. Um split por grupo responderia "o modelo funciona em municípios que nunca viu?", pergunta que não existe aqui.
- **Split pelo mês-alvo, não pelo t0.** O label do último t0 do treino (nov/2021) é dez/2021. Nenhum label de treino cai dentro do período de validação ou de teste.
- **Recall no top-k em vez de acurácia.** Só 10% das linhas são positivas: um modelo que sempre diz "não crítico" teria 90% de acurácia e seria inútil. E a ação real é escolher k municípios por mês, então a métrica mede exatamente isso.
- **Limiar de 39 focos.** Fixado pelo percentil 90 do treino, o que dá cerca de 10% de positivos e marca os meses realmente fora do comum.

### Desbalanceamento

| Partição | t0 | Linhas | Positivos | Taxa |
|---|---|---|---|---|
| treino | dez/2013 a nov/2021 | 13.824 | 1.393 | 10,1% |
| validação | dez/2021 a nov/2023 | 3.456 | 392 | 11,3% |
| teste | dez/2023 a ago/2026 | 4.752 | 394 | 8,3% |
| previsão | set/2026 | 144 | — | — |

## Resultados

Modelo escolhido na validação pelo recall no top-15: **regressão logística** (o gradient boosting ficou logo atrás e é mais difícil de explicar).

### Validação (modelos treinados só no treino)

| Score | PR-AUC | Recall top-15 | Precisão top-15 |
|---|---|---|---|
| Baseline mesmo mês do ano anterior | 0,891 | 41,8% | 45,6% |
| Baseline último mês | 0,750 | 39,5% | 43,1% |
| Regressão logística | **0,926** | **42,9%** | **46,7%** |
| Gradient boosting | 0,914 | 42,4% | 46,1% |

### Teste (modelo retreinado com treino + validação, avaliado uma única vez)

| Score | PR-AUC | Recall top-15 | Teto do recall | Precisão top-15 | Focos no top-15 |
|---|---|---|---|---|---|
| Baseline mesmo mês do ano anterior | 0,760 | 44,4% | 52,0% | 35,4% | 57,8% |
| Baseline último mês | 0,637 | 41,4% | 52,0% | 32,9% | 57,1% |
| Regressão logística | **0,853** | **48,7%** | 52,0% | **38,8%** | **63,0%** |

Só a estiagem (meses-alvo de julho a novembro, 13 meses no teste):

| Score | Recall top-15 | Teto | Precisão top-15 | Falsos positivos por mês | Focos no top-15 |
|---|---|---|---|---|---|
| Baseline mesmo mês do ano anterior | 41,6% (138 de 332) | 49,1% | 70,8% | 4,4 | 59,6% |
| Regressão logística | **45,8% (152 de 332)** | 49,1% | **78,0%** | **3,3** | **65,1%** |

**Teto do recall:** mesmo um modelo perfeito só acerta até 15 por mês, e em setembro há bem mais de 15 municípios críticos. O modelo chega a 48,7% de um máximo possível de 52,0%. O limite principal é a capacidade de 15 equipes, não o modelo.

**Curva por k:** `docs/figuras/recall_top_k_teste.png`. O modelo fica acima dos dois baselines em todo k de 5 a 30.

### O que o modelo usa (importância por permutação no teste)

| Feature | Queda de PR-AUC ao embaralhar |
|---|---|
| `media_hist_mes_alvo` | 0,470 |
| `focos_m0` | 0,191 |
| `focos_mes_alvo_ano_anterior` | 0,027 |
| `focos_12m` | 0,025 |
| `mes_alvo_sin` | 0,023 |
| demais (incluindo todas do IBGE) | < 0,006 |

O risco do mês seguinte é explicado quase todo pelo histórico do próprio município naquele mês e pelo quanto ele já está queimando agora. As variáveis do IBGE quase não acrescentam.

## Checklist anti-vazamento

**1. Toda feature existia antes do t0?**
Sim.
- Os focos vêm de M e de meses anteriores. `focos_mes_alvo_ano_anterior` é M-11, e `media_hist_mes_alvo` é a média de M-11, M-23, e assim por diante.
- Os dados do IBGE entram com a defasagem de publicação: população do ano do t0 - 1, rebanho - 2 e PIB - 3. Exemplo: o PIB municipal de 2021 só foi publicado no fim de 2023, então só aparece em t0 de 2024 em diante.
- As colunas `dias_sem_chuva`, `precipitacao`, `risco_fogo` e `frp` **não** são features. Elas só existem nos arquivos de 2026, então o treino não teria esses valores.

**2. As agregações foram calculadas só com dados anteriores ao t0 de cada observação?**
Sim. As janelas (`rolling`, `shift`, média expandida) são calculadas por município em ordem de tempo, olhando só para trás. A única coluna que olha para frente é `alvo_n_focos` (shift de -1), e ela é a resposta: o código interrompe a execução se alguma coluna `alvo_*` ou `critico` estiver na lista de features. Conferência manual, São Félix do Xingu em t0 = ago/2020:

| Feature | Valor esperado | Bate |
|---|---|---|
| `focos_m0` | focos de ago/2020 | sim |
| `focos_m2` | focos de jun/2020 | sim |
| `focos_12m` | soma de set/2019 a ago/2020 | sim |
| `focos_mes_alvo_ano_anterior` | focos de set/2019 | sim |
| `media_hist_mes_alvo` | média dos setembros de 2013 a 2019 | sim |
| `alvo_n_focos` | focos de set/2020 | sim |

**3. O split respeita tempo e grupo? Nenhuma entidade aparece em treino e teste ao mesmo tempo?**
O split respeita o tempo: treino, validação e teste são blocos consecutivos pelo mês-alvo, sem sobreposição de labels. A mesma entidade (município) aparece em treino e em teste **de propósito**, em meses diferentes, porque a decisão é sobre esses mesmos municípios no futuro (ver "Por que essas escolhas").

**4. Scalers, encoders e imputadores foram ajustados (fit) somente no treino?**
Sim. O imputador de mediana, o `log1p` e o `StandardScaler` estão dentro do `Pipeline` do scikit-learn junto com o modelo. O `fit` é chamado só com o conjunto de treino de cada etapa:
- treino, na escolha do modelo;
- treino + validação, na avaliação no teste;
- tudo com label, no ranking final.

O limiar do label também foi calculado só no treino.

### Métrica alta: por que não é vazamento

A ROC-AUC fica em 0,98, o que à primeira vista parece alto demais. A explicação é a sazonalidade: de janeiro a maio quase nenhum município do Pará é crítico, e qualquer modelo acerta esses meses. Por isso as métricas que importam são as da estiagem e as do top-15, e nelas o ganho é modesto e realista: +4 pontos de recall e +7 de precisão sobre o baseline. Se houvesse vazamento, o modelo bateria o teto do recall, e não fica nem perto dele.

## Limitações

- **Foco de calor não é área queimada:** um incêndio grande pode gerar um foco ou centenas.
- **Nuvens escondem focos:** meses chuvosos podem estar subestimados.
- **Sem clima no histórico:** a chuva e os dias sem chuva só existem a partir de 2026. Com uma série histórica de clima (INMET), o modelo provavelmente melhoraria na virada da estação.
- **Associação, não causa:** o modelo indica onde o padrão histórico aponta risco; não diz por que o município queima.
- **Satélite de referência único:** usar só o AQUA_M-T mantém a série comparável entre os anos, mas subconta o total de focos. Se o INPE trocar o satélite de referência, a série e o limiar precisarão ser recalculados.
