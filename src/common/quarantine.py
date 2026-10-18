"""Quarentena: nada problemático some sem rastro, e o job não quebra por dado sujo.

Cada ocorrência vira uma linha JSON em
  data/quarantine/<dataset>/<load_id>.jsonl
com: quando, dataset, objeto de origem, carga, motivo, detalhe e (para linhas) o conteúdo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Sequence

from src import config
from src.common.metadata import utc_now_iso

log = logging.getLogger(__name__)
_MAX_PAYLOAD_CHARS = 2000


def _path(dataset: str, load_id: str) -> Path:
    path = Path(config.QUARANTINE_DIR) / dataset / f"{load_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append(dataset: str, load_id: str, records: Sequence[dict[str, Any]]) -> Path:
    path = _path(dataset, load_id)
    with open(path, "a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return path


def quarantine_file(dataset: str, source_object: str, load_id: str, reason: str, detail: str = "") -> Path:
    """Arquivo ou resposta inteira que não pôde ser processada."""
    log.warning("QUARENTENA [%s] %s -> %s %s", dataset, source_object, reason, detail[:200])
    return _append(dataset, load_id, [{
        "quarantined_at": utc_now_iso(), "dataset": dataset, "source_object": source_object,
        "load_id": load_id, "level": "file", "reason": reason, "detail": detail[:_MAX_PAYLOAD_CHARS],
    }])


def quarantine_rows(dataset: str, source_object: str, load_id: str, reason: str,
                    rows: Sequence[Any], total: int | None = None, detail: str = "") -> Path:
    """Linhas descartadas do parse. Guarda uma amostra e, se houver mais, um registro-resumo."""
    log.warning("QUARENTENA [%s] %s -> %d linha(s): %s", dataset, source_object, total or len(rows), reason)
    records = [{
        "quarantined_at": utc_now_iso(), "dataset": dataset, "source_object": source_object,
        "load_id": load_id, "level": "row", "reason": reason, "detail": detail,
        "payload": json.dumps(row, ensure_ascii=False, default=str)[:_MAX_PAYLOAD_CHARS],
    } for row in rows]
    if total is not None and total > len(rows):
        records.append({
            "quarantined_at": utc_now_iso(), "dataset": dataset, "source_object": source_object,
            "load_id": load_id, "level": "summary", "reason": f"{reason}_resumo",
            "detail": f"{total} linhas no total; {len(rows)} guardadas como amostra",
        })
    return _append(dataset, load_id, records)
