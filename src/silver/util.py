from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config

SILVER_DIR = Path(config.DATA_DIR) / "silver"
TZ_LOCAL = "America/Belem"


def normalizar_texto(s: pd.Series) -> pd.Series:
    # "Santa Izabel do Pará" e "SANTA IZABEL DO PARA" viram a mesma chave
    return (s.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
             .str.upper().str.replace(r"[^A-Z ]", " ", regex=True)
             .str.split().str.join(" "))


def salvar(df: pd.DataFrame, nome: str) -> Path:
    # Cada tabela é reconstruída inteira a partir da Bronze: rodar 2x dá o mesmo resultado
    path = SILVER_DIR / f"{nome}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def ler(nome: str) -> pd.DataFrame:
    path = SILVER_DIR / f"{nome}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} não existe: rode python -m src.silver.{nome} antes")
    return pd.read_parquet(path)
