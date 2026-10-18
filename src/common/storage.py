"""Gravação da Bronze: imutável, particionada por data de ingestão.

Layout:
  data/bronze/<dataset>/ingest_date=AAAA-MM-DD/<objeto>__<load_id>/part-00000.parquet
                                                              └── _header.json (opcional)

- Nunca sobrescreve: cada carga tem um load_id novo, logo um diretório novo.
- Gravação atômica: escreve em "<dir>.tmp" e renomeia no final. Se der erro no
  meio, o .tmp é apagado e nada parcial fica na Bronze.
- Todas as colunas são texto ("como veio da fonte"). A tipagem forte é da Silver.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src import config


def slugify(text: str, max_len: int = 120) -> str:
    text = re.sub(r"^[a-z]+://", "", text)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[-max_len:]


def dataset_dir(dataset: str) -> Path:
    return Path(config.BRONZE_DIR) / dataset


def _write_part(df: pd.DataFrame, directory: Path, index: int) -> None:
    if config.BRONZE_FORMAT == "parquet":
        df.to_parquet(directory / f"part-{index:05d}.parquet", index=False)
    elif config.BRONZE_FORMAT == "csv":
        df.to_csv(directory / f"part-{index:05d}.csv", index=False)
    else:
        raise ValueError(f"BRONZE_FORMAT inválido: {config.BRONZE_FORMAT!r}")


def write_bronze_chunks(dataset: str, source_object: str, load_id: str,
                        chunks: Iterable[pd.DataFrame],
                        sidecars: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grava os chunks e devolve {"rows", "parts", "path"}. Sem linhas => nada é criado."""
    ingest_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final = (dataset_dir(dataset) / f"ingest_date={ingest_date}"
             / f"{slugify(source_object)}__{load_id}")
    tmp = final.with_name(final.name + ".tmp")
    if final.exists():
        raise FileExistsError(f"Bronze é imutável; já existe: {final}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    rows = parts = 0
    try:
        for chunk in chunks:
            if len(chunk) == 0:
                continue
            _write_part(chunk, tmp, parts)
            rows += len(chunk)
            parts += 1
        if rows == 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return {"rows": 0, "parts": 0, "path": None}
        for name, payload in (sidecars or {}).items():
            (tmp / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"rows": rows, "parts": parts, "path": str(final)}


def read_bronze(dataset: str) -> pd.DataFrame:
    """Lê toda a Bronze de um dataset (para checagens e testes)."""
    base = dataset_dir(dataset)
    pattern = "part-*.parquet" if config.BRONZE_FORMAT == "parquet" else "part-*.csv"
    files = sorted(base.glob(f"ingest_date=*/*/{pattern}"))
    if not files:
        return pd.DataFrame()
    if config.BRONZE_FORMAT == "parquet":
        frames = [pd.read_parquet(f) for f in files]
    else:
        frames = [pd.read_csv(f, dtype=str, keep_default_na=False) for f in files]
    return pd.concat(frames, ignore_index=True)
