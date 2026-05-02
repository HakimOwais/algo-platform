import os
from dataclasses import dataclass
from functools import lru_cache


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    timezone: str = "Asia/Kolkata"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/algo_platform"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "change-me"

    enable_market_sim: bool = True
    enable_paper_trading: bool = True
    default_broker: str = "paper"
    symbol_universe: str = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK"

    max_daily_loss_inr: float = 5000.0
    max_position_notional_inr: float = 100000.0
    max_open_orders: int = 20
    max_order_qty: int = 1000
    enable_monte_carlo_risk: bool = True
    mc_confidence: float = 0.95
    mc_horizon_steps: int = 20
    mc_paths: int = 2000
    max_mc_var_inr: float = 2500.0
    max_mc_cvar_inr: float = 4000.0
    min_risk_history_bars: int = 60

    angel_one_api_key: str = ""
    angel_one_client_code: str = ""
    angel_one_pin: str = ""
    angel_one_totp_secret: str = ""

    @property
    def symbols(self) -> list[str]:
        symbols = [part.strip().upper() for part in self.symbol_universe.split(",")]
        return [symbol for symbol in symbols if symbol]

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.getenv("APP_ENV", cls.app_env),
            timezone=os.getenv("TIMEZONE", cls.timezone),
            api_host=os.getenv("API_HOST", cls.api_host),
            api_port=int(os.getenv("API_PORT", cls.api_port)),
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            redis_url=os.getenv("REDIS_URL", cls.redis_url),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", cls.jwt_secret_key),
            enable_market_sim=_parse_bool(os.getenv("ENABLE_MARKET_SIM"), cls.enable_market_sim),
            enable_paper_trading=_parse_bool(
                os.getenv("ENABLE_PAPER_TRADING"), cls.enable_paper_trading
            ),
            default_broker=os.getenv("DEFAULT_BROKER", cls.default_broker),
            symbol_universe=os.getenv("SYMBOL_UNIVERSE", cls.symbol_universe),
            max_daily_loss_inr=float(os.getenv("MAX_DAILY_LOSS_INR", cls.max_daily_loss_inr)),
            max_position_notional_inr=float(
                os.getenv("MAX_POSITION_NOTIONAL_INR", cls.max_position_notional_inr)
            ),
            max_open_orders=int(os.getenv("MAX_OPEN_ORDERS", cls.max_open_orders)),
            max_order_qty=int(os.getenv("MAX_ORDER_QTY", cls.max_order_qty)),
            enable_monte_carlo_risk=_parse_bool(
                os.getenv("ENABLE_MONTE_CARLO_RISK"), cls.enable_monte_carlo_risk
            ),
            mc_confidence=float(os.getenv("MC_CONFIDENCE", cls.mc_confidence)),
            mc_horizon_steps=int(os.getenv("MC_HORIZON_STEPS", cls.mc_horizon_steps)),
            mc_paths=int(os.getenv("MC_PATHS", cls.mc_paths)),
            max_mc_var_inr=float(os.getenv("MAX_MC_VAR_INR", cls.max_mc_var_inr)),
            max_mc_cvar_inr=float(os.getenv("MAX_MC_CVAR_INR", cls.max_mc_cvar_inr)),
            min_risk_history_bars=int(
                os.getenv("MIN_RISK_HISTORY_BARS", cls.min_risk_history_bars)
            ),
            angel_one_api_key=os.getenv("ANGEL_ONE_API_KEY", cls.angel_one_api_key),
            angel_one_client_code=os.getenv("ANGEL_ONE_CLIENT_CODE", cls.angel_one_client_code),
            angel_one_pin=os.getenv("ANGEL_ONE_PIN", cls.angel_one_pin),
            angel_one_totp_secret=os.getenv("ANGEL_ONE_TOTP_SECRET", cls.angel_one_totp_secret),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
