from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.models.strategy import StrategyConfig
from app.schemas.trading import StrategyRead, StrategyUpdateRequest

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyRead])
async def list_strategies(
    container: ServiceContainer = Depends(get_container),
) -> list[StrategyRead]:
    return list(await container.strategies.list_all())


@router.post("/{strategy_name}/deploy", response_model=StrategyRead)
async def deploy_strategy(
    strategy_name: str,
    payload: StrategyUpdateRequest,
    container: ServiceContainer = Depends(get_container),
) -> StrategyRead:
    strategy = await container.strategies.get_by_name(strategy_name)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    strategy.parameters = payload.parameters or strategy.parameters
    strategy.is_active = True if payload.is_active is None else payload.is_active
    if payload.version:
        strategy.version = payload.version

    return await container.strategies.save(strategy)


@router.post("/{strategy_name}/pause", response_model=StrategyRead)
async def pause_strategy(
    strategy_name: str,
    container: ServiceContainer = Depends(get_container),
) -> StrategyRead:
    strategy = await container.strategies.get_by_name(strategy_name)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.is_active = False
    return await container.strategies.save(strategy)


@router.post("/{strategy_name}/resume", response_model=StrategyRead)
async def resume_strategy(
    strategy_name: str,
    container: ServiceContainer = Depends(get_container),
) -> StrategyRead:
    strategy = await container.strategies.get_by_name(strategy_name)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.is_active = True
    return await container.strategies.save(strategy)
