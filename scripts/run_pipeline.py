"""
Executa o pipeline inteiro, na ordem: Bronze, Silver, Gold e modelo.

Uso (na raiz do repositório):
    python -m scripts.run_pipeline
"""
from __future__ import annotations

import sys

from src.gold import run_gold
from src.ingestion import run_bronze
from src.ml import modelo
from src.silver import run_silver


def etapa(nome: str) -> None:
    print(f"\n{'=' * 25} {nome} {'=' * 25}", flush=True)


def main() -> int:
    etapa("BRONZE")
    # Arquivo com problema vai para a quarentena e não para o pipeline; só uma falha inesperada para
    if run_bronze.main([]) != 0:
        print("Falha inesperada na ingestão (ver log acima). Pipeline interrompido.")
        return 1

    etapa("SILVER")
    run_silver.main()

    etapa("GOLD")
    run_gold.main()

    etapa("MODELO")
    modelo.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
