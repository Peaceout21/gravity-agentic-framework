"""Factory for market providers."""

from core.tools.india_providers import BseProvider, NseProvider
from core.tools.market_provider import USSecProvider
from core.tools.sea_exchange_client import SeaProvider

SUPPORTED_MARKETS = ("US_SEC", "IN_NSE", "IN_BSE", "SEA_LOCAL")


def create_market_provider(market, sec_identity, timeout_seconds=20):
    # type: (str, str, int) -> object
    normalized = (market or "US_SEC").strip().upper()
    if normalized == "US_SEC":
        return USSecProvider(sec_identity=sec_identity, timeout_seconds=timeout_seconds)
    if normalized == "IN_NSE":
        return NseProvider(timeout_seconds=timeout_seconds)
    if normalized == "IN_BSE":
        return BseProvider(timeout_seconds=timeout_seconds)
    if normalized == "SEA_LOCAL":
        return SeaProvider(timeout_seconds=timeout_seconds)
    raise ValueError("Unsupported market: %s" % normalized)


def supported_markets():
    # type: () -> tuple
    return SUPPORTED_MARKETS
