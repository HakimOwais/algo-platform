from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fill import Fill
from app.models.order import Order
from app.models.position import Position


class PortfolioService:
    async def apply_fill(self, session: AsyncSession, order: Order, fill: Fill) -> None:
        result = await session.execute(select(Position).where(Position.symbol == fill.symbol))
        position = result.scalar_one_or_none()
        if position is None:
            position = Position(symbol=fill.symbol, quantity=0, avg_price=0.0, realized_pnl=0.0)
            session.add(position)
            await session.flush()

        if order.side.value == "BUY":
            new_qty = position.quantity + fill.quantity
            if new_qty <= 0:
                position.quantity = 0
                position.avg_price = 0.0
            else:
                weighted_old = position.avg_price * position.quantity
                weighted_new = fill.price * fill.quantity
                position.avg_price = (weighted_old + weighted_new) / new_qty
                position.quantity = new_qty
        else:
            sell_qty = min(fill.quantity, max(position.quantity, 0))
            realized = ((fill.price - position.avg_price) * sell_qty) - fill.fee
            position.realized_pnl += realized
            position.quantity -= sell_qty
            if position.quantity <= 0:
                position.quantity = 0
                position.avg_price = 0.0

    async def get_position_qty(self, session: AsyncSession, symbol: str) -> int:
        result = await session.execute(select(Position.quantity).where(Position.symbol == symbol))
        quantity = result.scalar_one_or_none()
        return quantity or 0

    async def list_positions(self, session: AsyncSession) -> list[Position]:
        result = await session.execute(select(Position).order_by(Position.symbol.asc()))
        return list(result.scalars().all())

    async def total_realized_pnl(self, session: AsyncSession) -> float:
        result = await session.execute(select(func.coalesce(func.sum(Position.realized_pnl), 0.0)))
        total = result.scalar_one()
        return float(total or 0.0)

    async def latest_fills(self, session: AsyncSession, limit: int = 50) -> list[Fill]:
        result = await session.execute(select(Fill).order_by(Fill.filled_at.desc()).limit(limit))
        return list(result.scalars().all())

