from collections.abc import Sequence
from dataclasses import dataclass
import math
import random

from app.quant._numeric import EPS, clean, mean, variance, quantile
from app.quant.returns import log_returns


@dataclass(frozen=True)
class MonteCarloRiskResult:
    confidence: float
    horizon_steps: int
    paths: int
    mean_return: float
    volatility: float
    var_return: float
    cvar_return: float
    var_amount: float
    cvar_amount: float


def monte_carlo_var_cvar_from_returns(
    returns: Sequence[float],
    notional: float,
    confidence: float = 0.95,
    horizon_steps: int = 20,
    paths: int = 2_000,
    random_seed: int | None = 7,
) -> MonteCarloRiskResult | None:
    arr = clean(returns)
    if len(arr) < 2:
        return None

    confidence = min(max(float(confidence), 0.5), 0.999)
    horizon_steps = max(int(horizon_steps), 1)
    paths = max(int(paths), 250)

    mu = mean(arr)
    vol = max(math.sqrt(variance(arr)), EPS)
    rng = random.Random(random_seed)

    terminal_returns: list[float] = []
    for _ in range(paths):
        total_log_return = sum(rng.gauss(mu, vol) for _ in range(horizon_steps))
        terminal_returns.append(math.exp(total_log_return) - 1.0)

    left_tail = 1.0 - confidence
    var_return = quantile(terminal_returns, left_tail)
    tail = [v for v in terminal_returns if v <= var_return]
    cvar_return = mean(tail) if tail else var_return

    safe_notional = max(float(notional), 0.0)
    return MonteCarloRiskResult(
        confidence=confidence,
        horizon_steps=horizon_steps,
        paths=paths,
        mean_return=mu,
        volatility=vol,
        var_return=var_return,
        cvar_return=cvar_return,
        var_amount=max(0.0, -var_return) * safe_notional,
        cvar_amount=max(0.0, -cvar_return) * safe_notional,
    )


def monte_carlo_var_cvar_from_prices(
    prices: Sequence[float],
    notional: float,
    confidence: float = 0.95,
    horizon_steps: int = 20,
    paths: int = 2_000,
    random_seed: int | None = 7,
) -> MonteCarloRiskResult | None:
    returns = log_returns(prices)
    if len(returns) < 2:
        return None
    return monte_carlo_var_cvar_from_returns(
        returns=returns,
        notional=notional,
        confidence=confidence,
        horizon_steps=horizon_steps,
        paths=paths,
        random_seed=random_seed,
    )


def probability_of_drawdown(
    returns: Sequence[float],
    drawdown_threshold: float = 0.03,
    horizon_steps: int = 20,
    paths: int = 2_000,
    random_seed: int | None = 11,
) -> float:
    arr = clean(returns)
    if len(arr) < 2:
        return 0.0
    mu = mean(arr)
    vol = max(math.sqrt(variance(arr)), EPS)
    threshold = -abs(float(drawdown_threshold))
    rng = random.Random(random_seed)

    breaches = 0
    total = max(int(paths), 250)
    for _ in range(total):
        cumulative = 0.0
        min_path = 0.0
        for _ in range(max(int(horizon_steps), 1)):
            cumulative += rng.gauss(mu, vol)
            running_return = math.exp(cumulative) - 1.0
            if running_return < min_path:
                min_path = running_return
        if min_path <= threshold:
            breaches += 1
    return breaches / total
