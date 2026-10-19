"""
Gold: focos_municipio_mes
Granularidade: uma linha por município do Pará por mês, de jan/2013 até o último mês completo.
Chave primária: (cod_ibge, ano_mes).
Fontes (Silver): foco_calor, dim_municipio.
"""
from __future__ import annotations

import pandas as pd

from src import config
from src.common import checks
from src.gold.util import salvar
from src.silver import util as silver

NOME = "focos_municipio_mes"


def ultimo_mes_completo(datas: pd.Series) -> pd.Period:
    ultima = pd.Timestamp(datas.max())
    mes = ultima.to_period("M")
    return mes if ultima.day == ultima.days_in_month else mes - 1


def construir() -> tuple[pd.DataFrame, dict]:
    focos = silver.ler("foco_calor")[["cod_ibge", "ano_mes", "data_local"]]
    dim = silver.ler("dim_municipio")

    inicio = pd.Period(f"{config.INPE_ANUAL_ANOS.start}-01", freq="M")
    fim = ultimo_mes_completo(focos["data_local"])
    focos = focos.assign(mes=pd.PeriodIndex(focos["ano_mes"], freq="M"))
    no_periodo = focos["mes"].between(inicio, fim)

    contagem = (focos[no_periodo].groupby(["cod_ibge", "mes"]).size()
                .rename("n_focos").reset_index())

    # Grade completa município x mês: mês sem foco precisa existir com zero, senão o modelo nunca vê o negativo
    grade = dim[["cod_ibge"]].merge(pd.DataFrame({"mes": pd.period_range(inicio, fim, freq="M")}), how="cross")
    df = grade.merge(contagem, on=["cod_ibge", "mes"], how="left")
    df["n_focos"] = df["n_focos"].fillna(0).astype(int)

    df["ano_mes"] = df["mes"].astype(str)
    df["ano"] = df["mes"].dt.year
    df["mes_num"] = df["mes"].dt.month
    df = df.drop(columns="mes").sort_values(["cod_ibge", "ano_mes"]).reset_index(drop=True)

    if df["n_focos"].sum() != int(no_periodo.sum()):
        raise ValueError("A soma de n_focos não bate com o número de focos da Silver no período")
    checks.check_no_duplicates(df, ["cod_ibge", "ano_mes"])

    rel = {
        "periodo": f"{inicio} a {fim}",
        "linhas": len(df),
        "focos_no_periodo": int(no_periodo.sum()),
        "focos_fora_do_periodo (mês incompleto)": int((~no_periodo).sum()),
        "municipio_mes_com_zero_foco": int((df["n_focos"] == 0).sum()),
    }
    return df, rel


def main() -> None:
    df, rel = construir()
    path = salvar(df, NOME)
    for chave, valor in rel.items():
        print(f"[{NOME}] {chave}: {valor}")
    print(f"[{NOME}] PK (cod_ibge, ano_mes) verificada; salvo em {path}")


if __name__ == "__main__":
    main()
