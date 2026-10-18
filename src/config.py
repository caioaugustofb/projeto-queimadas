"""Configuração central do pipeline (camada Bronze).

Tudo que muda entre máquinas ou entre fontes fica aqui. Os módulos leem os
valores via `config.NOME` (e não `from config import NOME`) para que os testes
consigam trocar URLs e pastas em tempo de execução.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Pastas (todas dentro de data/, que está no .gitignore)
# --------------------------------------------------------------------------- #
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("QUEIMADAS_DATA_DIR", ROOT_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"                # arquivos baixados, como vieram
BRONZE_DIR = DATA_DIR / "bronze"          # dado + metadados técnicos
QUARANTINE_DIR = DATA_DIR / "quarantine"  # arquivos/linhas problemáticos + motivo
STATE_FILE = DATA_DIR / "_state" / "bronze_state.json"  # manifest + checkpoints

BRONZE_FORMAT = "parquet"  # "parquet" (padrão) ou "csv" (usado nos testes)

# Toda operação aleatória usa esta semente (exigência do projeto).
SEED = 42

# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
HTTP_TIMEOUT = (10, 120)      # (conexão, leitura) em segundos
HTTP_MAX_ATTEMPTS = 5
HTTP_BACKOFF_BASE = 1.0       # 1s, 2s, 4s, 8s... (com jitter), até o teto abaixo
HTTP_BACKOFF_MAX = 30.0
USER_AGENT = "projeto-queimadas-bronze/1.0 (projeto academico)"

# --------------------------------------------------------------------------- #
# Leitura de CSV
# --------------------------------------------------------------------------- #
CSV_CHUNK_ROWS = 200_000
CSV_DELIMITER_CANDIDATES = [",", ";", "|", "\t"]
CSV_MAX_BAD_LINES_SAMPLE = 1000  # linhas malformadas guardadas na quarentena

# --------------------------------------------------------------------------- #
# INPE - Programa Queimadas
# --------------------------------------------------------------------------- #
INPE_SOURCE_SYSTEM = "INPE - Programa Queimadas (dataserver-coids)"
INPE_BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv"
INPE_ANUAL_ANOS = range(2013, 2026)          # 2013..2025
INPE_ANUAL_PATH = "/anual/Brasil_sat_ref/focos_br_ref_{ano}.zip"
INPE_MENSAL_PATH = "/mensal/Brasil/focos_mensal_br_{ano}{mes:02d}.csv"
INPE_DIARIO_DIR_PATH = "/diario/Brasil/"
INPE_DIARIO_FILE_PATH = "/diario/Brasil/focos_diario_br_{data}.csv"
INPE_DIARIO_REGEX = r"focos_diario_br_(\d{8})\.csv"
INPE_INCREMENTAL_ANO = 2026
# Colunas que esperamos ver nos arquivos mensais/diários (só gera aviso se faltar).
INPE_COLUNAS_ESPERADAS = [
    "id", "lat", "lon", "data_hora_gmt", "satelite", "municipio", "estado",
    "municipio_id", "bioma", "frp",
]

# --------------------------------------------------------------------------- #
# IBGE
# --------------------------------------------------------------------------- #
IBGE_SOURCE_SYSTEM = "IBGE - SIDRA / API de Dados Agregados e Localidades"
IBGE_LOCALIDADES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades"
IBGE_AGREGADOS_URL = "https://servicodados.ibge.gov.br/api/v3/agregados"
IBGE_SIDRA_URL = "https://apisidra.ibge.gov.br/values"
IBGE_UF_PARA = 15
IBGE_MUNICIPIOS_ESPERADOS = 144
IBGE_PAUSA_SEGUNDOS = 0.3  # educação com a API entre requisições

# ATENÇÃO: os códigos de variável/classificação abaixo vieram de memória e NÃO
# foram conferidos contra a API. Confirme em
#   https://servicodados.ibge.gov.br/api/v3/agregados/<tabela>/metadados
# antes da primeira carga completa.
IBGE_TABELAS = {
    "populacao": {
        "tabela": 6579, "variavel": "9324", "classificacao": None,
        "anos": range(2013, 2026),
    },
    "rebanho_bovino": {
        "tabela": 3939, "variavel": "105", "classificacao": "c79/2670",
        "anos": range(2013, 2026),
    },
    "pib_municipal": {
        "tabela": 5938, "variavel": "37", "classificacao": None,
        "anos": range(2013, 2024),  # 2023 é o último ano divulgado (dez/2025)
    },
}
