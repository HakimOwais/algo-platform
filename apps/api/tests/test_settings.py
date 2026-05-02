from app.core.config import Settings


def test_symbols_parser() -> None:
    settings = Settings(symbol_universe="RELIANCE, tcs , INFY")
    assert settings.symbols == ["RELIANCE", "TCS", "INFY"]

