import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.models.enums import OrderStatus, OrderType, Side
from app.models.fill import Fill
from app.models.order import Order
from app.services.portfolio_service import PortfolioService
from app.services.risk_engine import RiskEngine


class OrderManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker,
        risk_engine: RiskEngine,
        portfolio_service: PortfolioService,
        event_hub: EventHub,
        price_lookup,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._risk_engine = risk_engine
        self._portfolio_service = portfolio_service
        self._event_hub = event_hub
        self._price_lookup = price_lookup

    @property
    def session_factory(self):
        return self._session_factory

    async def place_order(
        self,
        strategy_name: str,
        symbol: str,
        side: Side,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
        idempotency_key: str | None = None,
        is_paper: bool = True,
    ) -> Order:
        key = idempotency_key or str(uuid.uuid4())
        symbol = symbol.upper()
        reference_price = limit_price or self._price_lookup(symbol) or 0.0
        notional = reference_price * quantity

        async with self._session_factory() as session:
            existing = await session.execute(select(Order).where(Order.idempotency_key == key))
            duplicate = existing.scalar_one_or_none()
            if duplicate is not None:
                return duplicate

            order = Order(
                strategy_name=strategy_name,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                status=OrderStatus.NEW,
                idempotency_key=key,
                is_paper=is_paper,
            )
            session.add(order)
            await session.flush()

            decision = await self._risk_engine.evaluate_order(
                session=session, symbol=symbol, quantity=quantity, notional=notional
            )
            if not decision.allowed:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = decision.reason
                order.updated_at = datetime.now(timezone.utc)
                await session.commit()
                await self._event_hub.broadcast(
                    "order.rejected",
                    {
                        "order_id": order.id,
                        "symbol": symbol,
                        "reason": decision.reason,
                    },
                )
                return order

            order.status = OrderStatus.SENT
            await session.commit()

        broker_response = await self._broker.place_order(symbol=symbol, side=side, quantity=quantity)

        async with self._session_factory() as session:
            db_order = await session.get(Order, order.id)
            if db_order is None:
                raise RuntimeError("Order disappeared while processing broker response")

            db_order.broker_order_id = broker_response.broker_order_id
            db_order.updated_at = datetime.now(timezone.utc)

            if not broker_response.accepted:
                db_order.status = OrderStatus.REJECTED
                db_order.rejection_reason = broker_response.reason
            else:
                db_order.status = OrderStatus.FILLED if broker_response.fills else OrderStatus.ACKED
                for broker_fill in broker_response.fills:
                    fill = Fill(
                        order_id=db_order.id,
                        symbol=broker_fill.symbol,
                        quantity=broker_fill.quantity,
                        price=broker_fill.price,
                        fee=broker_fill.fee,
                        filled_at=broker_fill.filled_at,
                    )
                    session.add(fill)
                    await self._portfolio_service.apply_fill(session, db_order, fill)
            await session.commit()
            await session.refresh(db_order)

        event_type = "order.filled" if db_order.status == OrderStatus.FILLED else "order.updated"
        await self._event_hub.broadcast(
            event_type,
            {
                "order_id": db_order.id,
                "symbol": db_order.symbol,
                "status": db_order.status.value,
                "side": db_order.side.value,
                "quantity": db_order.quantity,
                "broker_order_id": db_order.broker_order_id,
                "reason": db_order.rejection_reason,
            },
        )
        return db_order
