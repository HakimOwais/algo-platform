from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.models.enums import OrderStatus
from app.models.order import Order
from app.schemas.trading import DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardResponse)
async def dashboard_summary(container: ServiceContainer = Depends(get_container)) -> DashboardResponse:
    async with container.order_manager.session_factory() as session:
        positions = await container.portfolio_service.list_positions(session)
        realized = await container.portfolio_service.total_realized_pnl(session)
        open_orders_result = await session.execute(
            select(func.count(Order.id)).where(
                Order.status.in_(
                    [
                        OrderStatus.NEW,
                        OrderStatus.SENT,
                        OrderStatus.ACKED,
                        OrderStatus.PARTIALLY_FILLED,
                    ]
                )
            )
        )
        open_orders = int(open_orders_result.scalar_one() or 0)
        prices = container.market_data_service.snapshot_prices()
        unrealized = 0.0
        for position in positions:
            mkt = prices.get(position.symbol, position.avg_price)
            unrealized += (mkt - position.avg_price) * position.quantity

    nav = 1_000_000 + realized + unrealized
    return DashboardResponse(
        nav_estimate=round(nav, 2),
        realized_pnl=round(realized, 2),
        open_positions=len([position for position in positions if position.quantity > 0]),
        open_orders=open_orders,
        latest_prices=prices,
        kill_switch=container.risk_engine.kill_switch,
    )
