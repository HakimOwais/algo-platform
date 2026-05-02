from collections.abc import Sequence
import math


def clean_prices(prices: Sequence[float]) -> list[float]:
    cleaned: list[float] = []
    for price in prices:
        value = float(price)
        if not math.isfinite(value) or value <= 0:
            continue
        cleaned.append(value)
    return cleaned


def log_returns(prices: Sequence[float]) -> list[float]:
    values = clean_prices(prices)
    if len(values) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(values, values[1:]):
        if prev <= 0 or curr <= 0:
            continue
        returns.append(math.log(curr / prev))
    return returns


def simple_returns(prices: Sequence[float]) -> list[float]:
    values = clean_prices(prices)
    if len(values) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(values, values[1:]):
        if prev <= 0:
            continue
        returns.append((curr / prev) - 1.0)
    return returns
