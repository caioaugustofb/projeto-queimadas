# Ingestão — camada Bronze

## Como rodar
```bash
pip install -r requirements.txt
python -m src.ingestion.run_bronze                 # tudo
python -m src.ingestion.run_bronze --fonte ibge    # inpe_anual | inpe_2026 | ibge
python -m unittest discover -s tests -v            # testes offline (sem internet)
```
Rodar duas vezes seguidas não duplica dados: na segunda rodada tudo aparece como `skipped`.

## Fontes e formas de ingestão
| Dataset (Bronze) | Fonte | Forma |
|---|---|---|
| `inpe_focos_anual` | ZIPs 2013–2025 (`Brasil_sat_ref`) | arquivo |
| `inpe_focos_mensal` | CSVs mensais de 2026 já fechados (backfill) | arquivo |
| `inpe_focos_diario` | CSVs diários do mês corrente | incremental com checkpoint |
| `ibge_municipios_pa`, `ibge_populacao`, `ibge_rebanho_bovino`, `ibge_pib_municipal`, `ibge_periodos` | API do IBGE (Localidades, Agregados, SIDRA) | API REST (paginada por tabela × ano, retry com backoff) |

A pasta de diários do INPE guarda só ~30 dias; por isso os meses fechados vêm do mensal.
O arquivo diário do dia D só é ingerido depois de regravado em D+1 (regra: `Last-Modified` > D).

## Metadados em todo registro
`_ingested_at`, `_source_system`, `_source_object`, `_load_id`, `_record_hash` (SHA-256 das colunas da fonte).

## Idempotência (para a defesa)
1. HEAD igual ao do manifest → não baixa. 2. SHA-256 do arquivo igual → não ingere.
3. API: SHA-256 do corpo igual → não grava. Estado em `data/_state/bronze_state.json`.
Prova: `checks.summarize_bronze(storage.read_bronze("inpe_focos_diario"))` mantém `cargas == 1`
por objeto depois da segunda rodada (ver `test_idempotencia_rodar_duas_vezes`).
Se o manifest for apagado, a Silver deduplica por `_record_hash`.

## Quarentena
`data/quarantine/<dataset>/<load_id>.jsonl`: arquivo/ZIP corrompido, 404, arquivo vazio, encoding ilegível,
linhas malformadas (amostra + resumo), resposta de API inválida, período não publicado, dias ausentes na janela do INPE.

## Pendências conhecidas
- Códigos de variável do SIDRA em `config.IBGE_TABELAS` não foram conferidos contra a API.
- Esquema dos ZIPs anuais do INPE não verificado (pode não ter `municipio_id`).
- Licenças de uso do INPE e do IBGE ainda sem confirmação.
- Dados do INPE misturam satélite de referência (anual) e todos os satélites (mensal/diário): filtrar na Silver.
