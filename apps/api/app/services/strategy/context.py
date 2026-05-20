"""Signal context objects passed through the strategy pipeline.

CycleContext  — shared data built once per run_once() call (covers all symbols).
SignalContext  — per-symbol mutable state mutated by each stage in sequence.

Both are plain dataclasses with no I/O.  Stages can be unit-tested by
constructing these objects directly, running a stage function, and asserting
on the resulting field values.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SignalContext:
    symbol: str
    closes: list[float]
    returns: list[float]
    signal_state: int     # +1 bullish / -1 bearish from EMA crossover
    base_qty: int

    # Scalars — each stage multiplies its contribution in
    vol_scale: float = 1.0
    alloc_scale: float = 1.0
    tail_scale: float = 1.0
    kelly_scale: float = 1.0
    regime_scalar: float = 1.0
    ml_veto: bool = False

    # Diagnostic payload persisted to DecisionLog
    diagnostics: dict = field(default_factory=dict)

    @property
    def combined_scale(self) -> float:
        return (
            self.vol_scale
            * self.alloc_scale
            * self.tail_scale
            * self.kelly_scale
            * self.regime_scalar
        )


@dataclass(frozen=True)
class CycleContext:
    """Immutable snapshot of the full symbol universe for one strategy cycle."""
    params: dict
    price_history: dict[str, list[float]]
    returns_by_symbol: dict[str, list[float]]
    mv_weights: dict[str, float]
    rp_weights: dict[str, float]
    cs_momentum: dict[str, float]
    anchor_symbol: str | None
