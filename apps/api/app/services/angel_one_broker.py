import uuid

from app.core.config import Settings
from app.models.enums import Side
from app.services.broker_types import BrokerOrderResponse

try:
    from SmartApi import SmartConnect  # type: ignore
except Exception:  # pragma: no cover
    SmartConnect = None


class AngelOneBroker:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None

    def _ensure_client(self):
        if SmartConnect is None:
            raise RuntimeError("smartapi-python is not installed")
        if self._client is None:
            if not self._settings.angel_one_api_key:
                raise RuntimeError("Missing Angel One API credentials")
            self._client = SmartConnect(api_key=self._settings.angel_one_api_key)
        return self._client

    async def place_order(self, symbol: str, side: Side, quantity: int) -> BrokerOrderResponse:
        # This method is intentionally conservative for safety.
        # Teams should add a dedicated auth refresh + token cache before enabling live mode.
        _ = self._ensure_client()
        return BrokerOrderResponse(
            accepted=False,
            broker_order_id=str(uuid.uuid4()),
            status="REJECTED",
            reason=(
                "Live Angel One execution is disabled in this default template. "
                "Use paper mode or extend adapter with session + 2FA flow."
            ),
        )

