from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.schemas.trading import DashboardResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardResponse)
async def dashboard_summary(
    container: ServiceContainer = Depends(get_container),
) -> DashboardResponse:
    positions = await container.positions.list_active()
    realized = await container.positions.total_realized_pnl()
    open_orders = await container.orders.open_count()

    prices = container.market_data.snapshot_prices()
    unrealized = sum(
        (prices.get(p.symbol, p.avg_price) - p.avg_price) * p.quantity
        for p in positions
    )

    nav = container.settings.initial_capital_inr + realized + unrealized
    return DashboardResponse(
        nav_estimate=round(nav, 2),
        realized_pnl=round(realized, 2),
        open_positions=sum(1 for p in positions if p.quantity > 0),
        open_orders=open_orders,
        latest_prices=prices,
        kill_switch=container.risk_engine.kill_switch,
    )
