"""Angel One live market-data adapter — polls NSE prices via REST.

Satisfies MarketDataPort.  Gated to 09:15–15:30 IST Mon–Fri.
Adds:
  - Automatic JWT refresh every 20 h (prevents mid-session expiry)
  - Stale-history clear at the start of each new trading day

All bar-persistence, deque management, and event broadcasting are
handled by MarketDataBase; this class only implements the two hooks
plus the Angel One auth lifecycle.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.events import EventHub
from app.core.market_hours import ist_date_str
from app.infra.market_data._base import MarketDataBase
from app.models.bar import Bar

try:
    import pyotp
    from SmartApi import SmartConnect  # type: ignore
except ImportError:
    pyotp = None  # type: ignore[assignment]
    SmartConnect = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_SESSION_REFRESH_SECONDS = 20 * 3600  # refresh 4 h before 24-h hard-expiry


class AngelOneMarketData(MarketDataBase):
    is_live_feed = True
    _gate_to_market_hours = True

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        event_hub: EventHub,
        symbols: list[str],
        symbol_tokens: dict[str, str],
        poll_interval_seconds: float = 3.0,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            event_hub=event_hub,
            symbols=symbols,
            interval_seconds=poll_interval_seconds,
        )
        self._settings = settings
        self._symbol_tokens = {k.upper(): v for k, v in symbol_tokens.items()}
        self._client = None
        self._refresh_token: str | None = None
        self._last_cleared_ist_date: str | None = None
        self._session_refresh_task: asyncio.Task | None = None
        self._last_reauth_time: float = 0.0

    # ── Lifecycle overrides ────────────────────────────────────────────────

    async def run(self) -> None:
        self._session_refresh_task = asyncio.create_task(
            self._session_refresh_loop(), name="angel-one-session-refresh"
        )
        await super().run()

    async def stop(self) -> None:
        await super().stop()
        if self._session_refresh_task is not None:
            self._session_refresh_task.cancel()
            try:
                await self._session_refresh_task
            except asyncio.CancelledError:
                pass

    # ── MarketDataBase hooks ───────────────────────────────────────────────

    async def _setup(self, session: AsyncSession) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._authenticate)
        await self._fetch_prices_once()

    async def _tick(self, session: AsyncSession, timestamp: datetime) -> list[dict]:
        self._clear_stale_history_if_new_day()
        loop = asyncio.get_running_loop()
        bars: list[dict] = []
        for symbol in self._symbols:
            token = self._symbol_tokens.get(symbol)
            if not token:
                continue
            try:
                data = await loop.run_in_executor(
                    None, lambda s=symbol, t=token: self._ltp_data(s, t)
                )
            except Exception:
                logger.exception("Error polling LTP for %s", symbol)
                continue
            if not (data.get("status") and data.get("data")):
                logger.warning("Bad ltpData for %s: %s", symbol, data)
                continue

            ltp = round(float(data["data"]["ltp"]), 2)
            prev = self._latest_prices.get(symbol, ltp)
            session.add(Bar(
                instrument_id=self._instrument_ids[symbol],
                timestamp=timestamp,
                interval="1m-live",
                open=prev,
                high=round(max(prev, ltp), 2),
                low=round(min(prev, ltp), 2),
                close=ltp,
                volume=0.0,
            ))
            self._record_close(symbol, ltp)
            bars.append({
                "symbol": symbol,
                "open": prev,
                "high": round(max(prev, ltp), 2),
                "low": round(min(prev, ltp), 2),
                "close": ltp,
                "volume": 0.0,
                "timestamp": timestamp.isoformat(),
            })
        return bars

    # ── Auth helpers ───────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        if SmartConnect is None or pyotp is None:
            raise RuntimeError(
                "smartapi-python / pyotp not installed. "
                "Run: pip install smartapi-python pyotp"
            )
        s = self._settings
        if not (s.angel_one_api_key and s.angel_one_client_code
                and s.angel_one_pin and s.angel_one_totp_secret):
            raise RuntimeError(
                "Set ANGEL_ONE_API_KEY, ANGEL_ONE_CLIENT_CODE, ANGEL_ONE_PIN, "
                "ANGEL_ONE_TOTP_SECRET in .env to enable the live feed."
            )
        totp = pyotp.TOTP(s.angel_one_totp_secret).now()
        client = SmartConnect(api_key=s.angel_one_api_key)
        resp = client.generateSession(s.angel_one_client_code, s.angel_one_pin, totp)
        if not resp.get("status"):
            raise RuntimeError(f"Angel One login failed: {resp.get('message', 'unknown')}")
        self._client = client
        self._refresh_token = resp.get("data", {}).get("refreshToken")
        logger.info("Angel One session authenticated")

    @staticmethod
    def _is_invalid_token_response(response: dict) -> bool:
        if not isinstance(response, dict):
            return False
        if response.get("errorCode") == "AG8001":
            return True
        msg = str(response.get("message", "")).lower()
        return "invalid token" in msg or "token expired" in msg

    def _ltp_data(self, symbol: str, token: str) -> dict:
        if self._client is None:
            raise RuntimeError("Angel One client is not authenticated")
        data = self._client.ltpData("NSE", symbol, token)
        if self._is_invalid_token_response(data):
            now = time.monotonic()
            if now - self._last_reauth_time > 60:
                logger.warning(
                    "Invalid token for %s (AG8001); forcing full re-auth.", symbol
                )
                self._authenticate()
                self._last_reauth_time = now
            data = self._client.ltpData("NSE", symbol, token)
        return data

    def _refresh_session(self) -> None:
        if self._client is None or not self._refresh_token:
            logger.warning("No existing session; performing full re-auth.")
            self._authenticate()
            return
        try:
            resp = self._client.generateToken(self._refresh_token)
            if resp.get("status"):
                new_token = resp.get("data", {}).get("refreshToken")
                if new_token:
                    self._refresh_token = new_token
                logger.info("Angel One JWT refreshed.")
            else:
                logger.warning("Token refresh rejected (%s); falling back to full re-auth.",
                               resp.get("message", "unknown"))
                self._authenticate()
        except Exception:
            logger.exception("Exception during token refresh; attempting full re-auth.")
            self._authenticate()

    async def _session_refresh_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_SESSION_REFRESH_SECONDS)
            if not self._running:
                break
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._refresh_session)
            except Exception:
                logger.exception("Unhandled error in session refresh loop.")

    async def _fetch_prices_once(self) -> None:
        loop = asyncio.get_running_loop()
        for symbol in self._symbols:
            token = self._symbol_tokens.get(symbol)
            if not token:
                logger.warning(
                    "No Angel One token for %s — skipping "
                    "(add to ANGEL_ONE_SYMBOL_TOKENS)", symbol
                )
                continue
            try:
                data = await loop.run_in_executor(
                    None, lambda s=symbol, t=token: self._ltp_data(s, t)
                )
                if data.get("status") and data.get("data"):
                    ltp = round(float(data["data"]["ltp"]), 2)
                    self._record_close(symbol, ltp)
                else:
                    logger.warning("ltpData empty for %s: %s", symbol, data)
            except Exception:
                logger.exception("Failed initial LTP fetch for %s", symbol)

    def _clear_stale_history_if_new_day(self) -> None:
        today = ist_date_str()
        if self._last_cleared_ist_date != today:
            for sym in self._symbols:
                self._recent_closes[sym].clear()
            self._last_cleared_ist_date = today
            logger.info("Cleared overnight price history for new trading day: %s", today)
