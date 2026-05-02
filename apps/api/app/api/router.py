from fastapi import APIRouter

from app.api.routes import auth, backtest, dashboard, health, ml_train, quant, strategies, trading

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(strategies.router)
api_router.include_router(trading.router)
api_router.include_router(dashboard.router)
api_router.include_router(quant.router)
api_router.include_router(backtest.router)
api_router.include_router(ml_train.router)
