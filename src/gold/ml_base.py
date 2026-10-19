"""
Gold: ml_base
Granularidade: uma linha por município do Pará por t0 (último dia de cada mês M).
Chave primária: (cod_ibge, t0_ano_mes).
Label: critico = 1 se o município tiver n_focos >= limiar no mês seguinte (M+1).
Fontes: Gold focos_municipio_mes e Silver ibge_indicador_anual.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.common import checks
from src.gold.util import ler, salvar
from src.silver import util as silver

NOME = "ml_base"
PERCENTIL_LIMIAR = 0.90

# Split pelo mês-alvo (M+1): nenhum label do treino cai no período de validação ou de teste
TREINO_ATE = pd.Period("2021-12", freq="M")
VALIDACAO_ATE = pd.Period("2023-12", freq="M")

# Anos entre o dado do IBGE e a sua publicação. Em um t0 do ano Y só entra o dado do ano Y - defasagem.
DEFASAGEM_PUBLICACAO = {
    "populacao": 1,
    "rebanho_bovino": 2,
    "bovinos_por_habitante": 2,
    "pib_per_capita": 3,
}

FEATURES = [
    "focos_m0", "focos_m1", "focos_m2", "focos_3m", "focos_12m",
    "focos_mes_alvo_ano_anterior", "media_hist_mes_alvo",
    "mes_alvo_sin", "mes_alvo_cos",
    *DEFASAGEM_PUBLICACAO,
]


def features_de_focos(m: pd.DataFrame) -> pd.DataFrame:
    m = m.sort_values(["cod_ibge", "ano_mes"]).reset_index(drop=True)
    g = m.groupby("cod_ibge")["n_focos"]

    m["focos_m0"] = m["n_focos"]
    m["focos_m1"] = g.shift(1)
    m["focos_m2"] = g.shift(2)
    m["focos_3m"] = g.transform(lambda s: s.rolling(3).sum())
    m["focos_12m"] = g.transform(lambda s: s.rolling(12).sum())

    # M-11 é o mesmo mês do calendário que o mês-alvo (M+1), um ano antes
    m["focos_mes_alvo_ano_anterior"] = g.shift(11)
    m["mes_alvo_num"] = m["mes_num"] % 12 + 1
    # Média do mês-alvo nos anos anteriores: só usa M-11, M-23, ..., todos antes do t0
    m["media_hist_mes_alvo"] = (m.groupby(["cod_ibge", "mes_alvo_num"])["focos_mes_alvo_ano_anterior"]
                                  .transform(lambda s: s.expanding().mean()))
    m["mes_alvo_sin"] = np.sin(2 * np.pi * m["mes_alvo_num"] / 12)
    m["mes_alvo_cos"] = np.cos(2 * np.pi * m["mes_alvo_num"] / 12)

    # Único valor do futuro na tabela: é a resposta, nunca uma feature
    m["alvo_n_focos"] = g.shift(-1)
    return m


def features_do_ibge(m: pd.DataFrame) -> pd.DataFrame:
    ind = silver.ler("ibge_indicador_anual")
    # Razões calculadas no mesmo ano do dado, antes de aplicar a defasagem
    ind["bovinos_por_habitante"] = ind["rebanho_bovino"] / ind["populacao"]
    ind["pib_per_capita"] = ind["pib_mil_reais"] * 1000 / ind["populacao"]

    for coluna, defasagem in DEFASAGEM_PUBLICACAO.items():
        atrasado = ind[["cod_ibge", "ano", coluna]].assign(ano=ind["ano"] + defasagem)
        m = m.merge(atrasado, on=["cod_ibge", "ano"], how="left")
    return m


def construir() -> tuple[pd.DataFrame, dict]:
    m = features_do_ibge(features_de_focos(ler("focos_municipio_mes")))

    # Coorte: t0 com 12 meses completos de histórico (o primeiro é dez/2013)
    m = m[m["focos_12m"].notna()].copy()

    t0 = pd.PeriodIndex(m["ano_mes"], freq="M")
    alvo = t0 + 1
    m["particao"] = np.select(
        [alvo <= TREINO_ATE, alvo <= VALIDACAO_ATE, m["alvo_n_focos"].notna()],
        ["treino", "validacao", "teste"], default="previsao")

    # Limiar calculado só com o treino e congelado como número
    treino = m["particao"] == "treino"
    limiar = max(1.0, float(m.loc[treino, "alvo_n_focos"].quantile(PERCENTIL_LIMIAR)))
    m["critico"] = (m["alvo_n_focos"] >= limiar).astype("Int8").where(m["alvo_n_focos"].notna())

    m["t0_ano_mes"] = m["ano_mes"]
    m["t0_data"] = t0.to_timestamp(how="end").normalize()
    m["mes_alvo"] = alvo.astype(str)
    colunas = ["cod_ibge", "t0_ano_mes", "t0_data", "mes_alvo", "particao", *FEATURES, "alvo_n_focos", "critico"]
    m = m[colunas].reset_index(drop=True)

    if any(c.startswith("alvo_") or c == "critico" for c in FEATURES):
        raise ValueError("Coluna do futuro na lista de features")
    checks.check_no_duplicates(m, ["cod_ibge", "t0_ano_mes"])

    por_particao = m.groupby("particao").agg(
        linhas=("critico", "size"), positivos=("critico", "sum"),
        t0_inicio=("t0_ano_mes", "min"), t0_fim=("t0_ano_mes", "max"))
    por_particao["taxa_positivos"] = (por_particao["positivos"] / por_particao["linhas"]).round(4)

    meta = {
        "label": f"critico = alvo_n_focos (focos no mês M+1) >= {limiar:g}",
        "limiar_focos": limiar,
        "percentil_limiar_no_treino": PERCENTIL_LIMIAR,
        "split_por_mes_alvo": {"treino_ate": str(TREINO_ATE), "validacao_ate": str(VALIDACAO_ATE)},
        "defasagem_publicacao_ibge_anos": DEFASAGEM_PUBLICACAO,
        "features": FEATURES,
        "particoes": por_particao.reset_index().astype({"positivos": int}).to_dict(orient="records"),
    }
    return m, meta


def main() -> None:
    df, meta = construir()
    path = salvar(df, NOME, meta)
    print(f"[{NOME}] {meta['label']}")
    print(pd.DataFrame(meta["particoes"]).to_string(index=False))
    vazios = df[df["particao"] == "treino"][FEATURES].isna().mean().round(3)
    print(f"[{NOME}] fração de vazios por feature no treino:\n{vazios[vazios > 0].to_string()}")
    print(f"[{NOME}] PK (cod_ibge, t0_ano_mes) verificada; salvo em {path}")


if __name__ == "__main__":
    main()
