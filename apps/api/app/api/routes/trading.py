from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import ServiceContainer
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
async def list_orders(
    container: ServiceContainer = Depends(get_container),
    limit: int = 100,
) -> list[OrderRead]:
    return list(await container.orders.list_recent(limit))


@router.get("/fills", response_model=list[FillRead])
async def list_fills(
    container: ServiceContainer = Depends(get_container),
    limit: int = 100,
) -> list[FillRead]:
    return list(await container.fills.list_recent(limit))


@router.get("/positions", response_model=list[PositionRead])
async def list_positions(
    container: ServiceContainer = Depends(get_container),
) -> list[PositionRead]:
    return list(await container.positions.list_active())


@router.post("/ops/kill-switch")
async def toggle_kill_switch(
    payload: RiskToggleRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    from app.core.database import get_session_factory
    async with get_session_factory()() as session:
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
    from app.core.database import get_session_factory
    async with get_session_factory()() as session:
        return await container.risk_engine.status(session)


@router.get("/decisions", response_model=list[DecisionLogRead])
async def decision_logs(
    container: ServiceContainer = Depends(get_container),
    limit: int = 100,
) -> list[DecisionLogRead]:
    return list(await container.decisions.list_recent(limit))
