from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.models.strategy import StrategyConfig
from app.schemas.trading import StrategyRead, StrategyUpdateRequest

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyRead])
async def list_strategies(container: ServiceContainer = Depends(get_container)) -> list[StrategyRead]:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(StrategyConfig).order_by(StrategyConfig.name.asc()))
        return list(result.scalars().all())


@router.post("/{strategy_name}/deploy", response_model=StrategyRead)
async def deploy_strategy(
    strategy_name: str,
    payload: StrategyUpdateRequest,
    container: ServiceContainer = Depends(get_container),
) -> StrategyRead:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == strategy_name))
        strategy = result.scalar_one_or_none()
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")

        strategy.parameters = payload.parameters or strategy.parameters
        strategy.is_active = True if payload.is_active is None else payload.is_active
        if payload.version:
            strategy.version = payload.version
        await session.commit()
        await session.refresh(strategy)
        return strategy


@router.post("/{strategy_name}/pause", response_model=StrategyRead)
async def pause_strategy(strategy_name: str, container: ServiceContainer = Depends(get_container)) -> StrategyRead:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == strategy_name))
        strategy = result.scalar_one_or_none()
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.is_active = False
        await session.commit()
        await session.refresh(strategy)
        return strategy


@router.post("/{strategy_name}/resume", response_model=StrategyRead)
async def resume_strategy(strategy_name: str, container: ServiceContainer = Depends(get_container)) -> StrategyRead:
    async with container.order_manager.session_factory() as session:
        result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == strategy_name))
        strategy = result.scalar_one_or_none()
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        strategy.is_active = True
        await session.commit()
        await session.refresh(strategy)
        return strategy
