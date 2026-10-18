"""Metadados técnicos obrigatórios em todo registro da Bronze.

Colunas adicionadas:
  _ingested_at   horário (UTC, ISO-8601) em que o arquivo/resposta foi ingerido
  _source_system sistema de origem (ex.: "INPE - Programa Queimadas")
  _source_object objeto de origem (URL do arquivo, com "#membro.csv" se vier de ZIP)
  _load_id       identificador da carga (uma por execução e por fonte)
  _record_hash   SHA-256 do conteúdo do registro (só as colunas da fonte)

O hash NÃO inclui os metadados, então o mesmo registro lido em duas execuções
tem o mesmo hash. É isso que permite provar a ausência de duplicatas na Silver.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

META_COLUMNS = ["_ingested_at", "_source_system", "_source_object", "_load_id", "_record_hash"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_load_id(dataset: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{dataset}-{stamp}-{uuid.uuid4().hex[:8]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(block):
            h.update(chunk)
    return h.hexdigest()


def compute_record_hashes(df: pd.DataFrame) -> list[str]:
    """SHA-256 por linha. Colunas em ordem alfabética (reordenar colunas não muda o hash)."""
    cols = sorted(df.columns)
    prefix = "\x1e".join(cols) + "\x1d"
    arrays = [df[c].astype(str).tolist() for c in cols]
    return [
        hashlib.sha256((prefix + "\x1f".join(values)).encode("utf-8", "surrogatepass")).hexdigest()
        for values in zip(*arrays)
    ]


def add_metadata(df: pd.DataFrame, *, source_system: str, source_object: str,
                 load_id: str, ingested_at: str | None = None) -> pd.DataFrame:
    """Devolve o DataFrame com as 5 colunas de metadados (hash calculado antes)."""
    out = df.copy()
    hashes = compute_record_hashes(df)
    out["_ingested_at"] = ingested_at or utc_now_iso()
    out["_source_system"] = source_system
    out["_source_object"] = source_object
    out["_load_id"] = load_id
    out["_record_hash"] = hashes
    return out
