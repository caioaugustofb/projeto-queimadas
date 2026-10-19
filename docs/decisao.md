# Decisão

## A frase do projeto

> Cruzando os **focos de calor do INPE (2013 a 2026)** com **população, rebanho bovino e PIB dos municípios (IBGE)**, identificamos que **15 municípios concentram cerca de 65% dos focos de cada mês da estiagem**, e que o histórico do próprio município naquele mês é o melhor sinal do que vem a seguir. Recomendamos que a **SEMAS-PA, junto com o Corpo de Bombeiros Militar do Pará (CBMPA)**, **posicione brigadas de prevenção e fiscalização** nos **próximos 30 dias**, priorizando **os 15 municípios do topo do ranking mensal**. Se agir, o ganho esperado é **cobrir 65% dos focos da estiagem com 78% das equipes no lugar certo**, contra 60% e 71% escolhendo pelo mesmo mês do ano anterior. Se errarmos, o custo é **cerca de 3 equipes por mês em municípios que não ficaram críticos** e **municípios críticos sem equipe**, que já são inevitáveis com só 15 equipes.

## A frase, parte por parte

| Trecho | Valor | De onde vem |
|---|---|---|
| Bases cruzadas | INPE Queimadas (focos) × IBGE (Localidades e SIDRA) | `README.md`, seção Fontes |
| Chave do cruzamento | código IBGE do município + mês | `foco_calor.cod_ibge`, `focos_municipio_mes` |
| Registros casados no join | 472.088 focos do Pará, 144 de 144 municípios, 0 órfãos | relatório de `python -m src.silver.run_silver` |
| "15 municípios concentram cerca de 65% dos focos" | 65,1% dos focos dos meses de estiagem do teste caíram nos 15 priorizados pelo modelo | `modelo_metricas.json` → `teste.regressao_logistica.top_k_temporada.cobertura_focos` |
| "78% das equipes no lugar certo" | precisão no top-15 na estiagem: 152 acertos em 195 escolhas | `top_k_temporada.precisao` |
| "contra 60% e 71%" | baseline mesmo mês do ano anterior: cobertura 59,6%, precisão 70,8% | `teste.baseline_mesmo_mes_ano_anterior.top_k_temporada` |
| "cerca de 3 equipes por mês" | 3,3 falsos positivos por mês de estiagem (baseline: 4,4) | `falsos_positivos_por_mes` |
| "municípios críticos sem equipe" | 180 de 332 situações críticas da estiagem ficaram fora do top-15. Mesmo um modelo perfeito deixaria 169 de fora (teto de 49,1%) | `nao_capturados`, `recall_maximo_possivel` |
| Prazo | 30 dias, decisão renovada todo mês | o modelo prevê só o mês M+1 |

Números do período de teste (meses-alvo de jan/2024 a set/2026), que o modelo não viu no treino. Estiagem = meses-alvo de julho a novembro.

## Quem decide e o que faz

- **Decisor:** Secretaria de Estado de Meio Ambiente e Sustentabilidade do Pará (SEMAS-PA), junto com o CBMPA, que operam as brigadas e a fiscalização ambiental.
- **Quando:** no último dia útil de cada mês, assim que o pipeline roda com os dados do mês que fechou.
- **Ação:** deslocar as equipes de prevenção e combate inicial para os 15 municípios de maior score, durante o mês seguinte.
- **Entrega do pipeline:** a tabela `data/gold/ranking_prioridade.csv`, com os 144 municípios ordenados, o score e as features que explicam a posição.

## Custos de errar

| Erro | O que acontece | Custo |
|---|---|---|
| **Falso positivo** (equipe enviada a um município que não fica crítico) | A equipe passa o mês num lugar com pouco fogo | Diárias, combustível e deslocamento, e principalmente uma equipe a menos onde ela seria necessária |
| **Falso negativo** (município crítico sem equipe) | O fogo não é combatido no início | Mais área queimada, perda de vegetação e de produção, fumaça e doenças respiratórias, mais custo de combate depois |

O falso negativo custa mais que o falso positivo. Por isso a métrica principal é o recall, e por isso o modelo prioriza pegar os municípios críticos, mesmo que isso traga alguns alarmes falsos.

## Limiar adotado

O modelo produz uma probabilidade, mas **o corte não é 0,5**. O corte é a **capacidade operacional**: os 15 municípios de maior score recebem equipe, seja qual for a probabilidade deles.

- 15 é uma **premissa** do projeto para o número de equipes disponíveis por mês. Com outra capacidade, basta mudar `K` em `src/ml/modelo.py`.
- A curva em `docs/figuras/recall_top_k_teste.png` mostra o efeito de ter mais ou menos equipes:

| Equipes por mês (k) | 5 | 10 | 15 | 20 | 25 | 30 |
|---|---|---|---|---|---|---|
| Situações críticas cobertas (teste) | 19,5% | 33,8% | 48,7% | 60,2% | 70,1% | 78,4% |

Isso liga a métrica técnica à decisão: cada 5 equipes a mais cobrem cerca de 10 pontos percentuais a mais das situações críticas.

## Ranking para outubro de 2026

Gerado com t0 = 30/09/2026.

| Posição | Município | Região intermediária | Focos em set/2026 | Focos em out/2025 |
|---|---|---|---|---|
| 1 | Portel | Breves | 244 | 162 |
| 2 | São Félix do Xingu | Redenção | 426 | 165 |
| 3 | Pacajá | Marabá | 107 | 167 |
| 4 | Altamira | Altamira | 524 | 144 |
| 5 | Óbidos | Santarém | 111 | 168 |
| 6 | Moju | Belém | 70 | 112 |
| 7 | Uruará | Altamira | 91 | 72 |
| 8 | Anapu | Altamira | 87 | 116 |
| 9 | Itaituba | Santarém | 317 | 45 |
| 10 | Novo Repartimento | Marabá | 42 | 178 |
| 11 | Marabá | Marabá | 113 | 131 |
| 12 | Rurópolis | Santarém | 178 | 48 |
| 13 | Santarém | Santarém | 82 | 63 |
| 14 | Oriximiná | Santarém | 84 | 115 |
| 15 | Aveiro | Santarém | 103 | 64 |

**Conferência com o mês em curso.** Isso não é avaliação do modelo, porque outubro ainda não terminou e esses dados não entram no modelo. Com os focos observados de 1º a 18 de outubro:
- os 15 municípios do ranking concentram **4.289 dos 6.844 focos** (63%);
- **11 dos 15** também estão entre os 15 que mais queimaram até agora.

## Limitações

- **O que os dados não permitem afirmar:**
  - Que mandar a equipe *reduz* o fogo. O modelo prevê risco, não mede o efeito da ação. Para afirmar isso seria preciso comparar municípios com e sem equipe ao longo do tempo.
  - Quantos hectares vão queimar. Foco de calor não é área queimada; para isso seria preciso a área queimada do INPE (AQ1km) ou do MapBiomas Fogo.
- **O que melhoraria a previsão:**
  - Uma série histórica de chuva e umidade (INMET ou reanálise) para todos os anos. Hoje só existe em 2026.
  - O número real de brigadas disponíveis por mês. Os 15 são uma premissa.
- **Riscos de uso:**
  - O ranking só vale para o mês seguinte e precisa ser recalculado todo mês.
  - Anos extremos fora do padrão histórico, como a seca de 2024, reduzem a precisão: o teste foi pior que a validação justamente nesse período.
