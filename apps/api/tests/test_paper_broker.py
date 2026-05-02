import asyncio

from app.models.enums import Side
from app.services.paper_broker import PaperBroker


def test_paper_broker_places_fill() -> None:
    broker = PaperBroker(price_lookup=lambda symbol: 2500.0 if symbol == "RELIANCE" else None)
    response = asyncio.run(broker.place_order(symbol="RELIANCE", side=Side.BUY, quantity=5))

    assert response.accepted is True
    assert response.status == "FILLED"
    assert len(response.fills) == 1
    fill = response.fills[0]
    assert fill.symbol == "RELIANCE"
    assert fill.quantity == 5
    assert fill.price > 2500.0


def test_paper_broker_rejects_missing_price() -> None:
    broker = PaperBroker(price_lookup=lambda _symbol: None)
    response = asyncio.run(broker.place_order(symbol="UNKNOWN", side=Side.SELL, quantity=2))

    assert response.accepted is False
    assert response.status == "REJECTED"
    assert "No market price available" in (response.reason or "")
