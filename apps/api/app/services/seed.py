from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy import StrategyConfig


async def seed_defaults(session: AsyncSession) -> None:
    result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == "ema_cross"))
    strategy = result.scalar_one_or_none()
    if strategy is None:
        strategy = StrategyConfig(
            name="ema_cross",
            version="1.0.0",
            is_active=True,
            mode="PAPER",
            parameters={
                "fast_window": 8,
                "slow_window": 21,
                "trade_quantity": 5,
                "lookback_bars": 120,
                "target_vol_annual": 0.22,
                "bars_per_day": 390,
                "min_position_scale": 0.35,
                "max_position_scale": 2.5,
                "max_trade_quantity": 120,
                "risk_budget_per_order_inr": 1200.0,
                "use_garch_sizing": True,
                "use_monte_carlo_guard": True,
                "enable_pairs_context": True,
                "mc_confidence": 0.95,
                "mc_horizon_steps": 12,
                "mc_paths": 1500,
            },
        )
        session.add(strategy)
        await session.commit()
