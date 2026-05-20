# DEPRECATED — superseded by infra/market_data/angel_one.py (AngelOneMarketData).
# Kept for git history only. Not imported anywhere.

"""Angel One market data service — live NSE prices via REST polling.

Phase 1 additions vs. original:
  - Automatic JWT session refresh every 20 h (prevents mid-session expiry).
  - Market hours gate: generate_once() is a no-op outside 09:15–15:30 IST Mon–Fri.
  - Stale history clear: price-history deques are flushed at the start of each new
    trading day so overnight identical LTP values don't corrupt EMA / vol estimates.

WebSocket upgrade (Angel One Smartstream) is tracked as a Phase 2 item — the
legacy SmartWebSocket in smartapi-python 1.5.5 uses a deprecated endpoint with
base64+zlib encoding and is not suitable for production use.
"""
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.events import EventHub
from app.core.market_hours import is_market_open, ist_date_str, ist_now
from app.models.bar import Bar
from app.models.instrument import Instrument

try:
    from SmartApi import SmartConnect  # type: ignore
except ImportError:
    SmartConnect = None

logger = logging.getLogger(__name__)

# Refresh 4 h before the 24-h JWT hard-expiry to leave a comfortable margin.
_SESSION_REFRESH_SECONDS = 20 * 3600  # 20 hours


class AngelOneMarketDataService:
    """Polls Angel One ltpData endpoint for real NSE prices; paper orders still fill locally."""

    is_live_feed: bool = True  # used by orchestrator to gate strategy to market hours

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        event_hub: EventHub,
        symbols: list[str],
        symbol_tokens: dict[str, str],
        poll_interval_seconds: float = 3.0,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._event_hub = event_hub
        self._symbols = [s.upper() for s in symbols]
        self._symbol_tokens = {k.upper(): v for k, v in symbol_tokens.items()}
        self._poll_interval = poll_interval_seconds

        self._client = None
        self._refresh_token: str | None = None
        self._latest_prices: dict[str, float] = {}
        self._recent_closes: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=256))
        self._instrument_ids: dict[str, int] = {}
        self._running = False
        self._last_cleared_ist_date: str | None = None
        self._session_refresh_task: asyncio.Task | None = None

    # ── Authentication ─────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        if SmartConnect is None:
            raise RuntimeError("smartapi-python not installed. Run: pip install smartapi-python")
        s = self._settings
        if not (s.angel_one_api_key and s.angel_one_client_code and s.angel_one_pin and s.angel_one_totp_secret):
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
        logger.info("Angel One session authenticated for live market feed")

    def _refresh_session(self) -> None:
        """Extend the JWT using the refresh token — no TOTP re-entry needed.

        Falls back to a full re-authentication if the refresh token itself is
        expired or the call fails (e.g. network timeout).
        """
        if self._client is None or not self._refresh_token:
            logger.warning("No existing session to refresh; performing full re-auth.")
            self._authenticate()
            return
        try:
            resp = self._client.generateToken(self._refresh_token)
            if resp.get("status"):
                new_refresh = resp.get("data", {}).get("refreshToken")
                if new_refresh:
                    self._refresh_token = new_refresh
                logger.info("Angel One JWT refreshed successfully.")
            else:
                logger.warning(
                    "Token refresh rejected (%s); falling back to full re-auth.",
                    resp.get("message", "unknown"),
                )
                self._authenticate()
        except Exception:
            logger.exception("Exception during token refresh; attempting full re-auth.")
            self._authenticate()

    async def _session_refresh_loop(self) -> None:
        """Background task: refresh the Angel One JWT every 20 hours."""
        while self._running:
            await asyncio.sleep(_SESSION_REFRESH_SECONDS)
            if not self._running:
                break
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, self._refresh_session)
            except Exception:
                logger.exception("Unhandled error in session refresh loop.")

    # ── Bootstrap ──────────────────────────────────────────────────────────

    async def bootstrap(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._authenticate)

        async with self._session_factory() as session:
            for symbol in self._symbols:
                result = await session.execute(
                    select(Instrument).where(
                        Instrument.symbol == symbol, Instrument.exchange == "NSE"
                    )
                )
                instrument = result.scalar_one_or_none()
                if instrument is None:
                    instrument = Instrument(
                        symbol=symbol, exchange="NSE", tick_size=0.05, lot_size=1
                    )
                    session.add(instrument)
                    await session.flush()
                self._instrument_ids[symbol] = instrument.id
            await session.commit()

        await self._fetch_prices_once()

    # ── Price helpers ──────────────────────────────────────────────────────

    async def _fetch_prices_once(self) -> None:
        loop = asyncio.get_event_loop()
        for symbol in self._symbols:
            token = self._symbol_tokens.get(symbol)
            if not token:
                logger.warning("No Angel One token for %s — skipping (add to ANGEL_ONE_SYMBOL_TOKENS)", symbol)
                continue
            try:
                data = await loop.run_in_executor(
                    None, lambda s=symbol, t=token: self._client.ltpData("NSE", s, t)
                )
                if data.get("status") and data.get("data"):
                    ltp = float(data["data"]["ltp"])
                    self._latest_prices[symbol] = round(ltp, 2)
                    self._recent_closes[symbol].append(round(ltp, 2))
                else:
                    logger.warning("ltpData empty for %s: %s", symbol, data)
            except Exception:
                logger.exception("Failed initial LTP fetch for %s", symbol)

    def _clear_stale_history_if_new_day(self) -> None:
        """Flush price-history deques at the start of each new IST trading day.

        Overnight the market is closed and Angel One returns the previous session's
        closing LTP unchanged.  If those identical values sit in the deque they
        look like a perfectly flat price series to the EMA and volatility models,
        producing misleading statistics for the first hour of the new session.
        """
        today = ist_date_str()
        if self._last_cleared_ist_date != today:
            for sym in self._symbols:
                self._recent_closes[sym].clear()
            self._last_cleared_ist_date = today
            logger.info("Cleared overnight price history for new trading day: %s", today)

    def get_latest_price(self, symbol: str) -> float | None:
        return self._latest_prices.get(symbol.upper())

    def get_recent_closes(self, symbol: str, lookback: int = 30) -> list[float]:
        values = list(self._recent_closes[symbol.upper()])
        return values[-lookback:]

    def snapshot_prices(self) -> dict[str, float]:
        return dict(self._latest_prices)

    # ── Main loops ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        self._session_refresh_task = asyncio.create_task(
            self._session_refresh_loop(), name="angel-one-session-refresh"
        )
        while self._running:
            await self.generate_once()
            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._session_refresh_task is not None:
            self._session_refresh_task.cancel()
            try:
                await self._session_refresh_task
            except asyncio.CancelledError:
                pass

    async def generate_once(self) -> None:
        # ── Market hours gate ──────────────────────────────────────────────
        # Outside 09:15–15:30 IST Mon–Fri: skip polling entirely.
        # Angel One returns the previous session's LTP when the market is closed;
        # adding those stale identical prices to the deque corrupts the EMA,
        # volatility, and regime models and can trigger false crossover signals.
        if not is_market_open(ist_now()):
            return

        # Flush overnight stale data on the first poll of each new trading day.
        self._clear_stale_history_if_new_day()

        timestamp = datetime.now(timezone.utc)
        loop = asyncio.get_event_loop()
        bars_payload = []

        async with self._session_factory() as session:
            for symbol in self._symbols:
                token = self._symbol_tokens.get(symbol)
                if not token:
                    continue
                prev = self._latest_prices.get(symbol)
                try:
                    data = await loop.run_in_executor(
                        None, lambda s=symbol, t=token: self._client.ltpData("NSE", s, t)
                    )
                    if not (data.get("status") and data.get("data")):
                        logger.warning("Bad ltpData for %s: %s", symbol, data)
                        continue
                    ltp = round(float(data["data"]["ltp"]), 2)
                    open_p = prev if prev else ltp
                    bar = Bar(
                        instrument_id=self._instrument_ids[symbol],
                        timestamp=timestamp,
                        interval="1m-live",
                        open=open_p,
                        high=round(max(open_p, ltp), 2),
                        low=round(min(open_p, ltp), 2),
                        close=ltp,
                        volume=0.0,
                    )
                    session.add(bar)
                    self._latest_prices[symbol] = ltp
                    self._recent_closes[symbol].append(ltp)
                    bars_payload.append({
                        "symbol": symbol,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "timestamp": timestamp.isoformat(),
                    })
                except Exception:
                    logger.exception("Error polling LTP for %s", symbol)
            await session.commit()

        if bars_payload:
            await self._event_hub.broadcast("market.bars", {"bars": bars_payload})
