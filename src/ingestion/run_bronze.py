"""Executa a ingestão da camada Bronze.

Uso (na raiz do repositório):
    python -m src.ingestion.run_bronze                    # tudo
    python -m src.ingestion.run_bronze --fonte ibge       # só IBGE
    python -m src.ingestion.run_bronze --fonte inpe_anual
    python -m src.ingestion.run_bronze --fonte inpe_2026  # mensal + diário (incremental)

Rodar duas vezes seguidas não duplica nada: na segunda, tudo aparece como "skipped".
Um erro em uma fonte não derruba as outras; o código de saída é 2 se algo inesperado ocorreu.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date
from typing import Any, Callable

from src.common import metadata
from src.common.state import StateStore
from src.ingestion import ibge, inpe

log = logging.getLogger("bronze")


def _run(name: str, fn: Callable[[], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], bool]:
    try:
        return fn(), True
    except Exception:  # noqa: BLE001 - uma fonte nunca derruba as outras
        log.exception("Falha inesperada na fonte %s", name)
        return [{"dataset": name, "source_object": "-", "status": "error", "rows": 0}], False


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonte", choices=["todas", "inpe_anual", "inpe_2026", "ibge"], default="todas")
    parser.add_argument("--hoje", type=date.fromisoformat, default=today,
                        help="AAAA-MM-DD; só para reprocessar/testar (padrão: hoje em UTC)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    state = StateStore()
    ok_all, results = True, []
    plan = {
        "inpe_anual": lambda: inpe.ingest_annual(state, metadata.new_load_id("inpe_anual")),
        "inpe_2026": lambda: (inpe.ingest_monthly(state, metadata.new_load_id("inpe_mensal"), args.hoje)
                              + inpe.ingest_daily(state, metadata.new_load_id("inpe_diario"), args.hoje)),
        "ibge": lambda: ibge.ingest_all(state, metadata.new_load_id("ibge")),
    }
    for name, fn in plan.items():
        if args.fonte in ("todas", name):
            res, ok = _run(name, fn)
            results += res
            ok_all &= ok

    by_status = Counter(r["status"] for r in results)
    rows = sum(r.get("rows", 0) for r in results)
    log.info("Resumo: %s | linhas gravadas nesta rodada: %d", dict(by_status), rows)
    for r in results:
        if r["status"] in ("quarantined", "error"):
            log.info("  ! %s %s -> %s", r["dataset"], r["source_object"], r.get("detail", ""))
    return 0 if ok_all else 2


if __name__ == "__main__":
    sys.exit(main())
