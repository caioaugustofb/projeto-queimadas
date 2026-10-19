"""
Silver: ibge_indicador_anual
Granularidade: uma linha por município do Pará por ano (2013 a 2025).
Chave primária: (cod_ibge, ano).
Fontes (Bronze): ibge_populacao, ibge_rebanho_bovino, ibge_pib_municipal.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from src import config
from src.common import checks, metadata, quarantine, storage
from src.silver.util import ler, salvar

NOME = "ibge_indicador_anual"
DATASET = f"silver_{NOME}"

# Coluna da Silver -> dataset da Bronze
INDICADORES = {
    "populacao": "ibge_populacao",
    "rebanho_bovino": "ibge_rebanho_bovino",
    "pib_mil_reais": "ibge_pib_municipal",
}
# Símbolos do SIDRA no lugar de número. "-" é zero absoluto; os outros são ausência de dado.
SIMBOLOS_SIDRA = {"-": 0, "..": None, "...": None, "X": None}


def ler_indicador(coluna: str, dataset: str, codigos_validos: set[str],
                  run_id: str, rel: Counter) -> pd.DataFrame:
    bruto = storage.read_bronze(dataset)
    if bruto.empty:
        raise RuntimeError(f"Bronze {dataset} vazia: rode python -m src.ingestion.run_bronze --fonte ibge antes")

    # Colunas do SIDRA: D1C = código do município, D3C = ano, V = valor.
    # Se o IBGE revisou um ano e ele foi carregado de novo, vale a versão mais recente.
    bruto = bruto.sort_values("_ingested_at", kind="stable").drop_duplicates(["D1C", "D3C"], keep="last")

    texto = bruto["V"].str.strip()
    for simbolo, n in texto[texto.isin(list(SIMBOLOS_SIDRA))].value_counts().items():
        rel[f"{coluna}_simbolo_{simbolo}"] += int(n)

    df = pd.DataFrame({
        "cod_ibge": bruto["D1C"].str.strip(),
        "ano": pd.to_numeric(bruto["D3C"], errors="coerce"),
        coluna: pd.to_numeric(texto.replace("-", "0"), errors="coerce"),
        "_source_object": bruto["_source_object"],
    })

    orfaos = ~df["cod_ibge"].isin(codigos_validos) | df["ano"].isna()
    if orfaos.any():
        quarantine.quarantine_rows(DATASET, dataset, run_id, "municipio_ou_ano_invalido",
                                   df[orfaos].to_dict(orient="records"))
        rel[f"{coluna}_quarentena"] += int(orfaos.sum())

    df = df[~orfaos].drop(columns="_source_object")
    df["ano"] = df["ano"].astype(int)
    return df


def construir() -> tuple[pd.DataFrame, Counter]:
    run_id = metadata.new_load_id(DATASET)
    rel: Counter = Counter()
    dim = ler("dim_municipio")
    codigos = set(dim["cod_ibge"])

    # Grade completa município x ano: ano sem publicação aparece como vazio, não some
    anos = pd.DataFrame({"ano": list(config.INPE_ANUAL_ANOS)})
    df = dim[["cod_ibge"]].merge(anos, how="cross")

    for coluna, dataset in INDICADORES.items():
        df = df.merge(ler_indicador(coluna, dataset, codigos, run_id, rel), on=["cod_ibge", "ano"], how="left")

    df = df.sort_values(["cod_ibge", "ano"]).reset_index(drop=True)

    # A tabela de estimativas não tem 2022 e 2023. Repete o último valor conhecido em vez de
    # interpolar: interpolar 2022 usaria a estimativa de 2024, que ainda não existia (vazamento).
    faltava = df["populacao"].isna()
    df["populacao"] = df.groupby("cod_ibge")["populacao"].ffill()
    df["populacao_imputada"] = faltava & df["populacao"].notna()

    for coluna in INDICADORES:
        rel[f"{coluna}_vazios"] = int(df[coluna].isna().sum())
    rel["populacao_imputada"] = int(df["populacao_imputada"].sum())
    rel["final"] = len(df)

    checks.check_no_duplicates(df, ["cod_ibge", "ano"])
    return df, rel


def main() -> None:
    df, rel = construir()
    path = salvar(df, NOME)
    for chave, valor in rel.items():
        print(f"[{NOME}] {chave}: {valor}")
    anos_vazios = df.groupby("ano")[list(INDICADORES)].apply(lambda g: g.isna().all())
    for coluna in INDICADORES:
        print(f"[{NOME}] anos sem nenhum dado de {coluna}: {anos_vazios.index[anos_vazios[coluna]].tolist()}")
    print(f"[{NOME}] PK (cod_ibge, ano) verificada; salvo em {path}")


if __name__ == "__main__":
    main()
