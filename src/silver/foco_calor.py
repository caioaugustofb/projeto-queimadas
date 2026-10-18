"""
Silver: foco_calor
Granularidade: uma linha por foco de calor detectado no Pará pelo satélite de referência.
Chave primária: id_foco (hash de satélite + data/hora UTC + lat + lon).
Fontes (Bronze): inpe_focos_anual, inpe_focos_mensal, inpe_focos_diario.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter
from pathlib import Path

import pandas as pd

from src import config
from src.common import checks, metadata, quarantine, storage
from src.ingestion.inpe import DS_ANUAL, DS_DIARIO, DS_MENSAL

log = logging.getLogger(__name__)

DATASET = "silver_foco_calor"
SILVER_DIR = Path(config.DATA_DIR) / "silver"
TZ_LOCAL = "America/Belem"
SATELITE_REFERENCIA_PADRAO = "AQUA_M-T"

# Nome na Silver -> nomes possíveis na fonte (o anual e o mensal/diário podem diferir)
ALIASES = {
    "id_inpe": ["id", "foco_id", "id_bdq"],
    "lat": ["lat", "latitude"],
    "lon": ["lon", "longitude"],
    "data_hora_utc": ["data_hora_gmt", "data_pas", "datahora"],
    "satelite": ["satelite"],
    "municipio": ["municipio"],
    "estado": ["estado"],
    "cod_ibge": ["municipio_id", "id_municipio", "cod_municipio"],
    "dias_sem_chuva": ["numero_dias_sem_chuva", "diasemchuva"],
    "precipitacao": ["precipitacao"],
    "risco_fogo": ["risco_fogo", "riscofogo"],
    "bioma": ["bioma"],
    "frp": ["frp"],
}
OBRIGATORIAS = ["lat", "lon", "data_hora_utc", "estado"]
NUMERICAS = ["dias_sem_chuva", "precipitacao", "risco_fogo", "frp"]

# Retângulo que contém o Pará, com folga de ~0.1 grau
LAT_MIN, LAT_MAX = -9.95, 2.70
LON_MIN, LON_MAX = -59.00, -45.95


def sem_acento(s: pd.Series) -> pd.Series:
    return (s.str.normalize("NFKD").str.encode("ascii", "ignore")
             .str.decode("ascii").str.upper().str.strip())


def _arquivos(dataset: str) -> list[Path]:
    padrao = "part-*.parquet" if config.BRONZE_FORMAT == "parquet" else "part-*.csv"
    return sorted(storage.dataset_dir(dataset).glob(f"ingest_date=*/*/{padrao}"))


def _ler_parte(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def padronizar_colunas(df: pd.DataFrame, origem: str) -> pd.DataFrame:
    renomear = {}
    for destino, candidatas in ALIASES.items():
        achada = next((c for c in candidatas if c in df.columns), None)
        if achada:
            renomear[achada] = destino

    faltando = [c for c in OBRIGATORIAS if c not in renomear.values()]
    faltando += [c for c in metadata.META_COLUMNS if c not in df.columns]
    if faltando:
        raise ValueError(f"faltam as colunas {faltando}; colunas do arquivo: {list(df.columns)}")

    out = df[list(renomear) + metadata.META_COLUMNS].rename(columns=renomear)
    out["origem"] = origem
    return out


def filtrar_para(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    mask = sem_acento(df["estado"]) == "PARA"
    return df[mask].copy(), int((~mask).sum())


def ler_bronze_para(dataset: str, run_id: str, rel: Counter) -> list[pd.DataFrame]:
    # Filtra o Pará arquivo por arquivo: o Brasil inteiro de uma vez não cabe na memória
    partes = []
    for path in _arquivos(dataset):
        bruto = _ler_parte(path)
        rel[f"lidos_{dataset}"] += len(bruto)
        try:
            df = padronizar_colunas(bruto, dataset)
        except ValueError as exc:
            objeto = bruto["_source_object"].iloc[0] if "_source_object" in bruto and len(bruto) else str(path)
            quarantine.quarantine_file(DATASET, objeto, run_id, "contrato_quebrado", str(exc))
            rel["arquivos_contrato_quebrado"] += 1
            continue
        df, fora = filtrar_para(df)
        rel["fora_do_para"] += fora
        partes.append(df)
    return partes


def _parse_datas(df: pd.DataFrame) -> pd.Series:
    # Converte arquivo por arquivo: o formato da data pode mudar entre anual e mensal
    partes = [pd.to_datetime(s, errors="coerce", utc=True)
              for _, s in df.groupby("_source_object", dropna=False)["data_hora_utc"]]
    return pd.concat(partes).reindex(df.index)


def tipar(df: pd.DataFrame) -> pd.DataFrame:
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["data_hora_utc"] = _parse_datas(df)

    for col in NUMERICAS:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            # INPE usa negativos (ex.: -999) como "sem medição"
            df[col] = df[col].mask(df[col] < 0)
    if "risco_fogo" in df:
        df["risco_fogo"] = df["risco_fogo"].mask(df["risco_fogo"] > 1)

    for col in ["satelite", "municipio", "bioma"]:
        if col in df:
            df[col] = df[col].str.strip().str.upper().replace("", pd.NA)
    if "cod_ibge" in df:
        df["cod_ibge"] = df["cod_ibge"].str.strip().str.replace(r"\.0$", "", regex=True)
    return df


def filtrar_satelite_referencia(df: pd.DataFrame) -> tuple[pd.DataFrame, set[str], int]:
    # O anual já vem só do satélite de referência; mensal e diário trazem todos.
    # Sem o filtro, 2026 teria muito mais focos só por contar mais satélites.
    if "satelite" not in df:
        raise ValueError("Nenhum arquivo do INPE trouxe a coluna de satélite: impossível filtrar mensal/diário")

    anual = df["origem"] == DS_ANUAL
    if df.loc[anual, "satelite"].notna().any():
        ultimo_ano = df.loc[anual, "data_hora_utc"].dt.year.max()
        ref = set(df.loc[anual & (df["data_hora_utc"].dt.year == ultimo_ano), "satelite"].dropna())
    else:
        ref = {SATELITE_REFERENCIA_PADRAO}

    manter = anual | df["satelite"].isin(ref)
    return df[manter].copy(), ref, int((~manter).sum())


def separar_invalidos(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    motivos = pd.Series(pd.NA, index=df.index, dtype="object")

    def marcar(mask: pd.Series, motivo: str) -> None:
        motivos[mask & motivos.isna()] = motivo

    marcar(df[["lat", "lon", "data_hora_utc"]].isna().any(axis=1), "campo_obrigatorio_invalido")
    marcar(~df["lat"].between(LAT_MIN, LAT_MAX) | ~df["lon"].between(LON_MIN, LON_MAX),
           "coordenada_fora_do_para")
    if "cod_ibge" in df:
        marcar(~df["cod_ibge"].str.fullmatch(r"15\d{5}", na=False), "cod_ibge_fora_do_padrao")

    validos = df[motivos.isna()].copy()
    invalidos = df[motivos.notna()].copy()
    invalidos["_motivo"] = motivos[motivos.notna()]
    return validos, invalidos


def adicionar_tempo_local(df: pd.DataFrame) -> pd.DataFrame:
    # 01h UTC do dia 1º ainda é o mês anterior em Belém
    df["data_hora_local"] = df["data_hora_utc"].dt.tz_convert(TZ_LOCAL)
    df["data_local"] = df["data_hora_local"].dt.date
    df["ano_mes"] = df["data_hora_local"].dt.strftime("%Y-%m")
    df["ano"] = df["data_hora_local"].dt.year
    return df


def criar_id_foco(df: pd.DataFrame) -> pd.DataFrame:
    # Não usa o id do INPE: ele pode mudar entre o diário e o mensal do mesmo mês
    chave = (df["satelite"].fillna("") + "|"
             + df["data_hora_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S") + "|"
             + df["lat"].round(5).astype(str) + "|"
             + df["lon"].round(5).astype(str))
    df["id_foco"] = chave.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()[:16])
    return df


def deduplicar(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    antes = len(df)
    df = (df.sort_values("_ingested_at", kind="stable")
            .drop_duplicates(subset=["id_foco"], keep="last"))
    return df, antes - len(df)


def construir() -> tuple[pd.DataFrame, Counter, set[str]]:
    run_id = metadata.new_load_id(DATASET)
    rel: Counter = Counter()

    partes = []
    for ds in (DS_ANUAL, DS_MENSAL, DS_DIARIO):
        partes += ler_bronze_para(ds, run_id, rel)
    if not partes:
        raise RuntimeError("Bronze do INPE vazia: rode python -m src.ingestion.run_bronze antes")

    df = pd.concat(partes, ignore_index=True)
    df = tipar(df)
    df, ref, rel["fora_satelite_referencia"] = filtrar_satelite_referencia(df)

    df, invalidos = separar_invalidos(df)
    for (motivo, objeto), grupo in invalidos.groupby(["_motivo", "_source_object"], dropna=False):
        linhas = grupo.drop(columns="_motivo").to_dict(orient="records")
        quarantine.quarantine_rows(DATASET, objeto, run_id, motivo, linhas)
        rel[f"quarentena_{motivo}"] += len(linhas)

    df = adicionar_tempo_local(df)
    df = criar_id_foco(df)
    df, rel["duplicatas_removidas"] = deduplicar(df)
    rel["final"] = len(df)

    checks.check_no_duplicates(df, ["id_foco"])
    return df, rel, ref


def salvar(df: pd.DataFrame) -> Path:
    # Reconstruída inteira a partir da Bronze a cada execução: rodar 2x dá o mesmo resultado
    path = SILVER_DIR / "foco_calor.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    df, rel, ref = construir()
    path = salvar(df)
    print(f"Satélite(s) de referência: {sorted(ref)}")
    for chave, valor in rel.items():
        print(f"{chave}: {valor}")
    print(f"PK id_foco verificada: {df['id_foco'].nunique()} valores únicos em {len(df)} linhas")
    print(f"Salvo em {path}")


if __name__ == "__main__":
    main()
