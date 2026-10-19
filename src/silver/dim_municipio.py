"""
Silver: dim_municipio
Granularidade: uma linha por município do Pará.
Chave primária: cod_ibge.
Fonte (Bronze): ibge_municipios_pa.
"""
from __future__ import annotations

import json

import pandas as pd

from src import config
from src.common import checks, storage
from src.ingestion.ibge import DS_MUNICIPIOS
from src.silver.util import normalizar_texto, salvar

NOME = "dim_municipio"


def _regiao_intermediaria(regiao_imediata_json: str) -> str | None:
    try:
        return json.loads(regiao_imediata_json)["regiao-intermediaria"]["nome"]
    except (ValueError, KeyError, TypeError):
        return None


def construir() -> pd.DataFrame:
    bruto = storage.read_bronze(DS_MUNICIPIOS)
    if bruto.empty:
        raise RuntimeError("Bronze do IBGE vazia: rode python -m src.ingestion.run_bronze --fonte ibge antes")

    # Se a API foi carregada mais de uma vez, vale a versão mais recente
    bruto = bruto.sort_values("_ingested_at", kind="stable").drop_duplicates("id", keep="last")

    df = pd.DataFrame({
        "cod_ibge": bruto["id"].str.strip(),
        "nome": bruto["nome"].str.strip(),
        "nome_normalizado": normalizar_texto(bruto["nome"]),
        "regiao_intermediaria": bruto["regiao-imediata"].map(_regiao_intermediaria),
    }).sort_values("cod_ibge").reset_index(drop=True)

    invalidos = df.loc[~df["cod_ibge"].str.fullmatch(r"15\d{5}", na=False), "cod_ibge"].tolist()
    if invalidos:
        raise ValueError(f"Códigos fora do padrão do Pará: {invalidos}")
    if len(df) != config.IBGE_MUNICIPIOS_ESPERADOS:
        raise ValueError(f"Esperados {config.IBGE_MUNICIPIOS_ESPERADOS} municípios, vieram {len(df)}")

    checks.check_no_duplicates(df, ["cod_ibge"])
    # O join com o INPE é por nome, então o nome normalizado também precisa ser único
    checks.check_no_duplicates(df, ["nome_normalizado"])
    return df


def main() -> None:
    df = construir()
    path = salvar(df, NOME)
    print(f"[{NOME}] {len(df)} municípios, PK cod_ibge e nome_normalizado sem duplicatas")
    print(f"[{NOME}] regiões intermediárias: {df['regiao_intermediaria'].value_counts().to_dict()}")
    print(f"[{NOME}] salvo em {path}")


if __name__ == "__main__":
    main()
