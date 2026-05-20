from app.core.config import Settings
from app.ports.broker import BrokerPort
from app.services.angel_one_broker import AngelOneBroker
from app.services.paper_broker import PaperBroker


def build_broker(settings: Settings, price_lookup) -> BrokerPort:
    if settings.default_broker.lower() == "angel_one":
        return AngelOneBroker(settings)
    return PaperBroker(price_lookup=price_lookup)
