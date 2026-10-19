"""Executa a Gold na ordem de dependência: python -m src.gold.run_gold"""
from src.gold import focos_municipio_mes, ml_base


def main() -> None:
    focos_municipio_mes.main()
    ml_base.main()


if __name__ == "__main__":
    main()
