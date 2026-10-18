"""Baixa um arquivo remoto e ingere na Bronze, de forma idempotente.

Ordem das decisões (da mais barata para a mais cara):
  1. HEAD: se ETag/Last-Modified/tamanho são iguais aos do manifest -> pula sem baixar.
  2. Baixa e calcula SHA-256: se igual ao do manifest -> pula (só atualiza o manifest).
  3. Só então lê o CSV e grava na Bronze, com carga nova.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src import config
from src.common import http, metadata, quarantine
from src.common.state import StateStore
from src.ingestion import csv_loader

log = logging.getLogger(__name__)
_DONE = ("ok", "empty")


def _same_head(entry: dict[str, Any], head: dict[str, Any]) -> bool:
    known = {k: v for k, v in (entry.get("head") or {}).items() if v}
    return bool(known) and all(head.get(k) == v for k, v in known.items())


def ingest_remote_file(state: StateStore, load_id: str, *, dataset: str, url: str,
                       source_system: str, expected_columns: list[str] | None = None,
                       head: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {"dataset": dataset, "source_object": url}
    entry = state.get_manifest(url)
    try:
        head = head if head is not None else http.head_info(url)
    except http.HttpError as exc:
        quarantine.quarantine_file(dataset, url, load_id, "http_error", str(exc))
        return {**out, "status": "quarantined", "rows": 0, "detail": str(exc)}

    if entry and entry.get("status") in _DONE and _same_head(entry, head):
        return {**out, "status": "skipped", "rows": 0, "detail": "inalterado (HEAD igual ao manifest)"}

    dest = Path(config.RAW_DIR) / dataset / f"{load_id}__{url.rsplit('/', 1)[-1]}"
    try:
        dl = http.download_file(url, dest)
    except http.HttpError as exc:
        quarantine.quarantine_file(dataset, url, load_id, "http_error", str(exc))
        return {**out, "status": "quarantined", "rows": 0, "detail": str(exc)}

    if entry and entry.get("status") in _DONE and entry.get("sha256") == dl["sha256"]:
        state.set_manifest(url, {**entry, "head": head})
        dest.unlink(missing_ok=True)  # conteúdo idêntico ao já ingerido
        return {**out, "status": "skipped", "rows": 0, "detail": "inalterado (mesmo SHA-256)"}

    results = csv_loader.ingest_local_file(dest, dataset=dataset, source_system=source_system,
                                           source_url=url, load_id=load_id,
                                           expected_columns=expected_columns)
    statuses = {r["status"] for r in results}
    status = "quarantined" if "quarantined" in statuses else ("ok" if "ok" in statuses else "empty")
    rows = sum(r["rows"] for r in results)
    state.set_manifest(url, {
        "status": status, "sha256": dl["sha256"], "bytes": dl["bytes"], "head": head,
        "rows": rows, "load_id": load_id, "ingested_at": metadata.utc_now_iso(),
        "raw_file": str(dest), "members": [
            {k: r.get(k) for k in ("source_object", "status", "rows", "columns", "encoding",
                                   "delimiter", "bad_lines")} for r in results],
    })
    return {**out, "status": status, "rows": rows,
            "detail": "; ".join(str(r.get("detail", "")) for r in results if r.get("detail"))}
