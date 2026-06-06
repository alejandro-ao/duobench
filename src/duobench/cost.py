"""Token → dollar cost, using per-model pricing from models.yaml (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass

from duobench.config import Model
from duobench.pi_rpc import Usage


@dataclass(frozen=True)
class PhaseCost:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    usd: float
    reported_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "usd": round(self.usd, 6),
            "reported_usd": round(self.reported_usd, 6),
        }


def compute_cost(usage: Usage, model: Model) -> PhaseCost:
    """Cost in USD from configured rates.

    `input`/`output` are required. `cache_read` and `cache_write` are optional and
    default to the input rate for backward compatibility/conservative accounting.
    Pi/provider reported cost is preserved separately for auditing, not used as the
    benchmark source of truth.
    """
    rate_in = model.pricing.input / 1_000_000
    rate_out = model.pricing.output / 1_000_000
    rate_cache_read = (model.pricing.cache_read if model.pricing.cache_read is not None else model.pricing.input) / 1_000_000
    rate_cache_write = (model.pricing.cache_write if model.pricing.cache_write is not None else model.pricing.input) / 1_000_000
    usd = (
        usage.input * rate_in
        + usage.output * rate_out
        + usage.cache_read * rate_cache_read
        + usage.cache_write * rate_cache_write
    )
    return PhaseCost(
        input_tokens=usage.input,
        output_tokens=usage.output,
        cache_read_tokens=usage.cache_read,
        cache_write_tokens=usage.cache_write,
        usd=usd,
        reported_usd=usage.reported_cost,
    )
