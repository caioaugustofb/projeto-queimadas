"""
Modelo de priorização: quais municípios do Pará têm maior risco de mês crítico de queimadas no mês seguinte.

1. Treina na partição treino e escolhe o modelo pela validação (recall no top-k).
2. Retreina com treino + validação e avalia uma única vez no teste, contra os baselines.
3. Retreina com tudo que tem label e gera o ranking da partição previsao (t0 = último mês completo).

Saídas: data/gold/ranking_prioridade.parquet (+ .csv), data/gold/modelo_metricas.json
e docs/figuras/recall_top_k_teste.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from src import config
from src.gold import util as gold
from src.silver import util as silver

SEED = config.SEED
K = 15  # premissa: equipes disponíveis por mês
KS = list(range(5, 31, 5))
MESES_TEMPORADA = {7, 8, 9, 10, 11}  # meses-alvo da estiagem no Pará
FIGURA = Path(config.ROOT_DIR) / "docs" / "figuras" / "recall_top_k_teste.png"

BASELINES = {
    "baseline_mesmo_mes_ano_anterior": "focos_mes_alvo_ano_anterior",
    "baseline_ultimo_mes": "focos_m0",
}


def criar_modelos(features: list[str]) -> dict[str, Pipeline]:
    ciclicas = ["mes_alvo_sin", "mes_alvo_cos"]
    positivas = [f for f in features if f not in ciclicas]
    # Imputer e scaler ficam dentro do Pipeline: o fit acontece só nos dados de treino
    preparo_lr = ColumnTransformer([
        ("positivas", Pipeline([("imputar", SimpleImputer(strategy="median")),
                                ("log", FunctionTransformer(np.log1p)),
                                ("escala", StandardScaler())]), positivas),
        ("ciclicas", StandardScaler(), ciclicas),
    ])
    return {
        "regressao_logistica": Pipeline([
            ("preparo", preparo_lr),
            ("modelo", LogisticRegression(max_iter=2000, random_state=SEED)),
        ]),
        "gradient_boosting": Pipeline([
            ("modelo", HistGradientBoostingClassifier(
                learning_rate=0.05, max_iter=200, max_leaf_nodes=15, l2_regularization=1.0,
                early_stopping=False, random_state=SEED)),
        ]),
    }


def top_k(df: pd.DataFrame, score: str, k: int) -> dict:
    # Em cada t0, os k municípios de maior score recebem equipe
    ordenado = df.sort_values(["t0_ano_mes", score, "cod_ibge"], ascending=[True, False, True])
    sel = ordenado[ordenado.groupby("t0_ano_mes").cumcount() < k]
    acertos, positivos = int(sel["critico"].sum()), int(df["critico"].sum())
    meses = df["t0_ano_mes"].nunique()
    # Mesmo um modelo perfeito só captura até k por mês: em setembro há mais de k municípios críticos
    teto = int(df.groupby("t0_ano_mes")["critico"].sum().clip(upper=k).sum())
    return {
        "k": k,
        "recall": round(acertos / positivos, 4) if positivos else None,
        "recall_maximo_possivel": round(teto / positivos, 4) if positivos else None,
        "precisao": round(acertos / len(sel), 4),
        "acertos": acertos,
        "positivos": positivos,
        "nao_capturados": positivos - acertos,
        "falsos_positivos_por_mes": round((len(sel) - acertos) / meses, 2),
        "cobertura_focos": round(float(sel["alvo_n_focos"].sum() / df["alvo_n_focos"].sum()), 4),
    }


def avaliar(df: pd.DataFrame, scores: dict[str, str]) -> dict:
    temporada = df[pd.PeriodIndex(df["mes_alvo"], freq="M").month.isin(MESES_TEMPORADA)]
    resultado = {}
    for nome, coluna in scores.items():
        resultado[nome] = {
            "pr_auc": round(float(average_precision_score(df["critico"], df[coluna])), 4),
            "roc_auc": round(float(roc_auc_score(df["critico"], df[coluna])), 4),
            "top_k": top_k(df, coluna, K),
            "top_k_temporada": top_k(temporada, coluna, K),
            "curva_recall": {k: top_k(df, coluna, k)["recall"] for k in KS},
        }
    return resultado


def pontuar(modelo: Pipeline, treino: pd.DataFrame, alvo: pd.DataFrame, features: list[str]) -> np.ndarray:
    modelo.fit(treino[features], treino["critico"].astype(int))
    return modelo.predict_proba(alvo[features])[:, 1]


def desenhar_curva(resultado: dict, escolhido: str) -> None:
    FIGURA.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for nome in [escolhido, *BASELINES]:
        curva = resultado[nome]["curva_recall"]
        ax.plot(list(curva), list(curva.values()), marker="o", label=nome.replace("_", " "))
    ax.axvline(K, color="gray", linestyle="--", linewidth=1)
    ax.set_xlabel("municípios priorizados por mês (k)")
    ax.set_ylabel("meses críticos capturados (recall)")
    ax.set_ylim(0, 1)
    ax.set_title("Teste (meses-alvo de 2024 a 2026)")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURA, dpi=150)
    plt.close(fig)


def main() -> None:
    base = gold.ler("ml_base")
    meta = gold.ler_meta("ml_base")
    features = meta["features"]
    treino = base[base["particao"] == "treino"]
    validacao = base[base["particao"] == "validacao"].copy()
    teste = base[base["particao"] == "teste"].copy()
    previsao = base[base["particao"] == "previsao"].copy()

    # 1. Escolha do modelo na validação
    for nome, modelo in criar_modelos(features).items():
        validacao[nome] = pontuar(modelo, treino, validacao, features)
    scores_val = {**BASELINES, **{n: n for n in criar_modelos(features)}}
    res_val = avaliar(validacao, scores_val)
    modelos = list(criar_modelos(features))
    escolhido = max(modelos, key=lambda n: (res_val[n]["top_k"]["recall"], res_val[n]["pr_auc"]))

    # 2. Avaliação única no teste
    treino_val = base[base["particao"].isin(["treino", "validacao"])]
    modelo_teste = criar_modelos(features)[escolhido]
    teste[escolhido] = pontuar(modelo_teste, treino_val, teste, features)
    res_teste = avaliar(teste, {**BASELINES, escolhido: escolhido})
    desenhar_curva(res_teste, escolhido)

    imp = permutation_importance(modelo_teste, teste[features], teste["critico"].astype(int),
                                 scoring="average_precision", n_repeats=5, random_state=SEED)
    importancia = (pd.Series(imp.importances_mean, index=features)
                   .sort_values(ascending=False).round(4).to_dict())

    # 3. Ranking do próximo mês
    com_label = base[base["particao"] != "previsao"]
    previsao["score"] = pontuar(criar_modelos(features)[escolhido], com_label, previsao, features)
    dim = silver.ler("dim_municipio")[["cod_ibge", "nome", "regiao_intermediaria"]]
    ranking = (previsao.merge(dim, on="cod_ibge")
               .sort_values(["score", "cod_ibge"], ascending=[False, True]).reset_index(drop=True))
    ranking["posicao"] = ranking.index + 1
    ranking[f"top_{K}"] = ranking["posicao"] <= K
    ranking = ranking[["posicao", "cod_ibge", "nome", "regiao_intermediaria", "t0_ano_mes", "mes_alvo", "score",
                       f"top_{K}", "focos_m0", "focos_mes_alvo_ano_anterior", "media_hist_mes_alvo"]]
    gold.salvar(ranking, "ranking_prioridade")
    ranking.to_csv(gold.GOLD_DIR / "ranking_prioridade.csv", index=False)

    # Conferência posterior, não entra no modelo: focos já observados no mês-alvo (mês ainda em curso)
    mes_alvo = ranking["mes_alvo"].iloc[0]
    focos = silver.ler("foco_calor")
    parcial = focos[focos["ano_mes"] == mes_alvo].groupby("cod_ibge").size()
    ranking["focos_parciais_mes_alvo"] = ranking["cod_ibge"].map(parcial).fillna(0).astype(int)
    top_parcial = set(parcial.sort_values(ascending=False).head(K).index)
    conferencia = {
        "mes_alvo": mes_alvo,
        "dias_observados_ate": str(focos.loc[focos["ano_mes"] == mes_alvo, "data_local"].max()),
        "focos_parciais_no_top_k": int(ranking.loc[ranking[f"top_{K}"], "focos_parciais_mes_alvo"].sum()),
        "focos_parciais_total": int(parcial.sum()),
        "top_k_em_comum_com_o_parcial": len(top_parcial & set(ranking.loc[ranking[f"top_{K}"], "cod_ibge"])),
    }

    metricas = {
        "k": K,
        "limiar_label": meta["label"],
        "modelo_escolhido": escolhido,
        "validacao": res_val,
        "teste": res_teste,
        "importancia_permutacao_teste": importancia,
        "conferencia_mes_em_curso": conferencia,
    }
    (gold.GOLD_DIR / "modelo_metricas.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")

    print(f"Modelo escolhido na validação: {escolhido}")
    for etapa, res in [("VALIDAÇÃO", res_val), ("TESTE", res_teste)]:
        print(f"\n== {etapa} (k={K})")
        linhas = {n: {"pr_auc": r["pr_auc"], **{c: r["top_k"][c] for c in
                      ["recall", "recall_maximo_possivel", "precisao", "cobertura_focos"]},
                      "recall_temporada": r["top_k_temporada"]["recall"],
                      "precisao_temporada": r["top_k_temporada"]["precisao"]} for n, r in res.items()}
        print(pd.DataFrame(linhas).T.to_string())
    print(f"\nImportância (queda de PR-AUC no teste ao embaralhar):\n{pd.Series(importancia).head(8).to_string()}")
    print(f"\nRanking para {mes_alvo} (top {K}):")
    print(ranking.head(K)[["posicao", "nome", "regiao_intermediaria", "score", "focos_m0",
                           "focos_mes_alvo_ano_anterior", "focos_parciais_mes_alvo"]].to_string(index=False))
    print(f"\nConferência com o mês em curso: {conferencia}")


if __name__ == "__main__":
    main()
