from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src import config

GOLD_DIR = Path(config.DATA_DIR) / "gold"


def salvar(df: pd.DataFrame, nome: str, meta: dict[str, Any] | None = None) -> Path:
    path = GOLD_DIR / f"{nome}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    if meta is not None:
        (GOLD_DIR / f"{nome}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def ler(nome: str) -> pd.DataFrame:
    path = GOLD_DIR / f"{nome}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe: rode python -m src.gold.{nome} antes")
    return pd.read_parquet(path)


def ler_meta(nome: str) -> dict[str, Any]:
    return json.loads((GOLD_DIR / f"{nome}_meta.json").read_text(encoding="utf-8"))
