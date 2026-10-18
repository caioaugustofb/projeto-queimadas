"""Verificações da Bronze usadas na defesa (idempotência e metadados)."""
from __future__ import annotations

import pandas as pd

from src.common.metadata import META_COLUMNS


def check_bronze_metadata(df: pd.DataFrame) -> None:
    """Toda linha da Bronze precisa ter os 5 metadados preenchidos."""
    missing = [c for c in META_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas de metadados ausentes: {missing}")
    empty = {c: int((df[c].astype(str) == "").sum()) for c in META_COLUMNS}
    empty = {c: n for c, n in empty.items() if n}
    if empty:
        raise ValueError(f"Metadados vazios: {empty}")


def check_no_duplicates(df: pd.DataFrame, key: list[str]) -> None:
    """Prova de unicidade da chave: levanta ValueError se houver duplicata."""
    dups = int(df.duplicated(subset=key).sum())
    if dups:
        raise ValueError(f"{dups} linha(s) duplicada(s) na chave {key}")


def summarize_bronze(df: pd.DataFrame) -> pd.DataFrame:
    """Por objeto de origem: nº de cargas, linhas e hashes distintos.

    Se rodar a ingestão duas vezes e o resultado não mudar (mesmo nº de cargas e
    linhas), a ingestão é idempotente.
    """
    if df.empty:
        return pd.DataFrame(columns=["_source_object", "cargas", "linhas", "hashes_distintos"])
    return (df.groupby("_source_object")
              .agg(cargas=("_load_id", "nunique"), linhas=("_record_hash", "size"),
                   hashes_distintos=("_record_hash", "nunique"))
              .reset_index())
