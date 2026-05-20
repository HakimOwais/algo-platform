"""OrderManager — idempotent order lifecycle with explicit two-phase commit.

Phase 1 (pre-broker): dedupe → risk check → persist NEW/REJECTED  (one session)
Phase 2 (post-broker): apply broker response → persist fills + FILLED/ACKED (one session)

The broker call happens between the two sessions so it never holds a DB connection
open during network I/O.  Each phase is individually atomic; the SENT state acts
as the crash-recovery marker (a reconciler can detect orders stuck in SENT).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.models.enums import OrderStatus, OrderType, Side
from app.models.fill import Fill
from app.models.order import Order
from app.ports.broker import BrokerPort
from app.ports.repositories import PositionRepo
from app.services.risk_engine import RiskEngine


@asynccontextmanager
async def _uow(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class OrderManager:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BrokerPort,
        risk_engine: RiskEngine,
        position_repo: PositionRepo,
        event_hub: EventHub,
        price_lookup,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._risk_engine = risk_engine
        self._position_repo = position_repo
        self._event_hub = event_hub
        self._price_lookup = price_lookup

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

        # ── Phase 1: validate + insert ────────────────────────────────────
        order, rejected = await self._phase_one(
            key=key, strategy_name=strategy_name, symbol=symbol,
            side=side, quantity=quantity, order_type=order_type,
            limit_price=limit_price, is_paper=is_paper, notional=notional,
        )
        if rejected:
            await self._event_hub.broadcast(
                "order.rejected",
                {"order_id": order.id, "symbol": symbol, "reason": order.rejection_reason},
            )
            return order

        # ── Broker call (no DB session held) ─────────────────────────────
        broker_response = await self._broker.place_order(
            symbol=symbol, side=side, quantity=quantity
        )

        # ── Phase 2: apply broker result ──────────────────────────────────
        order = await self._phase_two(order.id, broker_response)

        event_type = "order.filled" if order.status == OrderStatus.FILLED else "order.updated"
        await self._event_hub.broadcast(
            event_type,
            {
                "order_id": order.id,
                "symbol": order.symbol,
                "status": order.status.value,
                "side": order.side.value,
                "quantity": order.quantity,
                "broker_order_id": order.broker_order_id,
                "reason": order.rejection_reason,
            },
        )
        return order

    # ── Private phase helpers ──────────────────────────────────────────────

    async def _phase_one(
        self, *, key, strategy_name, symbol, side, quantity,
        order_type, limit_price, is_paper, notional,
    ) -> tuple[Order, bool]:
        async with _uow(self._session_factory) as session:
            existing = await session.execute(
                select(Order).where(Order.idempotency_key == key)
            )
            duplicate = existing.scalar_one_or_none()
            if duplicate is not None:
                return duplicate, (duplicate.status == OrderStatus.REJECTED)

            order = Order(
                strategy_name=strategy_name, symbol=symbol, side=side,
                quantity=quantity, order_type=order_type, limit_price=limit_price,
                status=OrderStatus.NEW, idempotency_key=key, is_paper=is_paper,
            )
            session.add(order)
            await session.flush()  # get order.id

            decision = await self._risk_engine.evaluate_order(
                session=session, symbol=symbol, quantity=quantity, notional=notional
            )
            if not decision.allowed:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = decision.reason
                order.updated_at = datetime.now(timezone.utc)
                return order, True

            order.status = OrderStatus.SENT
            return order, False

    async def _phase_two(self, order_id: str, broker_response) -> Order:
        async with _uow(self._session_factory) as session:
            db_order = await session.get(Order, order_id)
            if db_order is None:
                raise RuntimeError(f"Order {order_id} disappeared during broker processing")

            db_order.broker_order_id = broker_response.broker_order_id
            db_order.updated_at = datetime.now(timezone.utc)

            if not broker_response.accepted:
                db_order.status = OrderStatus.REJECTED
                db_order.rejection_reason = broker_response.reason
            else:
                db_order.status = (
                    OrderStatus.FILLED if broker_response.fills else OrderStatus.ACKED
                )
                for bf in broker_response.fills:
                    fill = Fill(
                        order_id=db_order.id,
                        symbol=bf.symbol,
                        quantity=bf.quantity,
                        price=bf.price,
                        fee=bf.fee,
                        filled_at=bf.filled_at,
                    )
                    session.add(fill)
                    await self._apply_fill_to_position(session, db_order, fill)

            await session.flush()
            await session.refresh(db_order)
            return db_order

    async def _apply_fill_to_position(
        self, session: AsyncSession, order: Order, fill: Fill
    ) -> None:
        from app.models.position import Position  # local import avoids circular at module level

        result = await session.execute(
            select(Position).where(Position.symbol == fill.symbol)
        )
        position = result.scalar_one_or_none()
        if position is None:
            position = Position(
                symbol=fill.symbol, quantity=0, avg_price=0.0, realized_pnl=0.0
            )
            session.add(position)
            await session.flush()

        if order.side.value == "BUY":
            new_qty = position.quantity + fill.quantity
            if new_qty <= 0:
                position.quantity = 0
                position.avg_price = 0.0
            else:
                weighted = (
                    position.avg_price * position.quantity + fill.price * fill.quantity
                )
                position.avg_price = weighted / new_qty
                position.quantity = new_qty
        else:
            sell_qty = min(fill.quantity, max(position.quantity, 0))
            position.realized_pnl += (fill.price - position.avg_price) * sell_qty - fill.fee
            position.quantity -= sell_qty
            if position.quantity <= 0:
                position.quantity = 0
                position.avg_price = 0.0
