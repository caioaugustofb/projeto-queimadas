"""Executa a Silver na ordem de dependência: python -m src.silver.run_silver"""
from src.silver import dim_municipio, foco_calor, ibge_indicador_anual


def main() -> None:
    dim_municipio.main()
    ibge_indicador_anual.main()
    foco_calor.main()


if __name__ == "__main__":
    main()
