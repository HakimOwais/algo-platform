from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.models.decision_log import DecisionLog
from app.models.fill import Fill
from app.models.order import Order
from app.schemas.trading import (
    DecisionLogRead,
    FillRead,
    OrderCreateRequest,
    OrderRead,
    PositionRead,
    RiskToggleRequest,
)

router = APIRouter(tags=["trading"])


@router.post("/orders", response_model=OrderRead)
async def create_order(
    payload: OrderCreateRequest,
    container: ServiceContainer = Depends(get_container),
) -> OrderRead:
    order = await container.order_manager.place_order(
        strategy_name=payload.strategy_name,
        symbol=payload.symbol,
        side=payload.side,
        quantity=payload.quantity,
        order_type=payload.order_type,
        limit_price=payload.limit_price,
        idempotency_key=payload.idempotency_key,
        is_paper=container.settings.default_broker != "angel_one",
    )
    return order


@router.get("/orders", response_model=list[OrderRead])
async def list_orders(container: ServiceContainer = Depends(get_container), limit: int = 100) -> list[OrderRead]:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(Order).order_by(Order.requested_at.desc()).limit(limit))
        return list(result.scalars().all())


@router.get("/fills", response_model=list[FillRead])
async def list_fills(container: ServiceContainer = Depends(get_container), limit: int = 100) -> list[FillRead]:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(Fill).order_by(Fill.filled_at.desc()).limit(limit))
        return list(result.scalars().all())


@router.get("/positions", response_model=list[PositionRead])
async def list_positions(container: ServiceContainer = Depends(get_container)) -> list[PositionRead]:
    async with container.order_manager.session_factory() as session:
        return await container.portfolio_service.list_positions(session)


@router.post("/ops/kill-switch")
async def toggle_kill_switch(
    payload: RiskToggleRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    async with container.order_manager.session_factory() as session:
        await container.risk_engine.set_kill_switch(
            session=session,
            engaged=payload.engaged,
            message=payload.message,
        )
    await container.event_hub.broadcast(
        "risk.kill_switch",
        {"engaged": payload.engaged, "message": payload.message},
    )
    return {"status": "ok", "engaged": payload.engaged}


@router.get("/risk/status")
async def risk_status(container: ServiceContainer = Depends(get_container)) -> dict:
    async with container.order_manager.session_factory() as session:
        return await container.risk_engine.status(session)


@router.get("/decisions", response_model=list[DecisionLogRead])
async def decision_logs(container: ServiceContainer = Depends(get_container), limit: int = 100) -> list[DecisionLogRead]:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(DecisionLog).order_by(DecisionLog.created_at.desc()).limit(limit))
        return list(result.scalars().all())
