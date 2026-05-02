from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.schemas.trading import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(container: ServiceContainer = Depends(get_container)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=container.settings.app_env,
        broker=container.settings.default_broker,
        market_simulation=container.settings.enable_market_sim,
    )

