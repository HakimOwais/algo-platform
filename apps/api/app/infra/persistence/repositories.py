"""Concrete SQLAlchemy repository implementations.

Each class satisfies the matching Protocol in ports/repositories.py.
Services and routes depend only on the protocols; this module is the
single place that imports sqlalchemy, selects, and commits.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.decision_log import DecisionLog
from app.models.enums import OrderStatus
from app.models.fill import Fill
from app.models.order import Order
from app.models.position import Position
from app.models.strategy import StrategyConfig


# ── Shared unit-of-work helper ─────────────────────────────────────────────

class SqlaOrderRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_recent(self, limit: int = 100) -> list[Order]:
        async with self._sf() as s:
            result = await s.execute(
                select(Order).order_by(Order.requested_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def open_count(self) -> int:
        open_states = [
            OrderStatus.NEW, OrderStatus.SENT,
            OrderStatus.ACKED, OrderStatus.PARTIALLY_FILLED,
        ]
        async with self._sf() as s:
            result = await s.execute(
                select(func.count(Order.id)).where(Order.status.in_(open_states))
            )
            return int(result.scalar_one())


class SqlaFillRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_recent(self, limit: int = 50) -> list[Fill]:
        async with self._sf() as s:
            result = await s.execute(
                select(Fill).order_by(Fill.filled_at.desc()).limit(limit)
            )
            return list(result.scalars().all())


class SqlaPositionRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_active(self) -> list[Position]:
        async with self._sf() as s:
            result = await s.execute(select(Position).order_by(Position.symbol.asc()))
            return list(result.scalars().all())

    async def held_qty(self, symbol: str) -> int:
        async with self._sf() as s:
            result = await s.execute(
                select(Position.quantity).where(Position.symbol == symbol)
            )
            qty = result.scalar_one_or_none()
            return qty or 0

    async def total_realized_pnl(self) -> float:
        async with self._sf() as s:
            result = await s.execute(
                select(func.coalesce(func.sum(Position.realized_pnl), 0.0))
            )
            return float(result.scalar_one() or 0.0)

    async def apply_fill(self, order: Order, fill: Fill) -> None:
        async with self._sf() as s:
            result = await s.execute(
                select(Position).where(Position.symbol == fill.symbol)
            )
            position = result.scalar_one_or_none()
            if position is None:
                position = Position(
                    symbol=fill.symbol, quantity=0, avg_price=0.0, realized_pnl=0.0
                )
                s.add(position)
                await s.flush()

            if order.side.value == "BUY":
                new_qty = position.quantity + fill.quantity
                if new_qty <= 0:
                    position.quantity = 0
                    position.avg_price = 0.0
                else:
                    weighted = position.avg_price * position.quantity + fill.price * fill.quantity
                    position.avg_price = weighted / new_qty
                    position.quantity = new_qty
            else:
                sell_qty = min(fill.quantity, max(position.quantity, 0))
                realized = (fill.price - position.avg_price) * sell_qty - fill.fee
                position.realized_pnl += realized
                position.quantity -= sell_qty
                if position.quantity <= 0:
                    position.quantity = 0
                    position.avg_price = 0.0

            await s.commit()


class SqlaDecisionRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_recent(self, limit: int = 100) -> list[DecisionLog]:
        async with self._sf() as s:
            result = await s.execute(
                select(DecisionLog).order_by(DecisionLog.created_at.desc()).limit(limit)
            )
            return list(result.scalars().all())

    async def record(self, decision: DecisionLog) -> None:
        async with self._sf() as s:
            s.add(decision)
            await s.commit()


class SqlaStrategyRepo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_active(self, names: tuple[str, ...]) -> StrategyConfig | None:
        async with self._sf() as s:
            result = await s.execute(
                select(StrategyConfig)
                .where(StrategyConfig.name.in_(names))
                .where(StrategyConfig.is_active.is_(True))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> StrategyConfig | None:
        async with self._sf() as s:
            result = await s.execute(
                select(StrategyConfig).where(StrategyConfig.name == name)
            )
            return result.scalar_one_or_none()

    async def save(self, strategy: StrategyConfig) -> StrategyConfig:
        async with self._sf() as s:
            merged = await s.merge(strategy)
            await s.commit()
            await s.refresh(merged)
            return merged

    async def list_all(self) -> list[StrategyConfig]:
        async with self._sf() as s:
            result = await s.execute(
                select(StrategyConfig).order_by(StrategyConfig.name.asc())
            )
            return list(result.scalars().all())
