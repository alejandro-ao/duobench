import pytest

from kcbench.config import Model, Pricing
from kcbench.cost import compute_cost
from kcbench.pi_rpc import Usage


def test_usage_delta_includes_cached_tokens_and_reported_cost() -> None:
    previous = Usage(input=100, output=20, cache_read=30, cache_write=40, reported_cost=0.01)
    current = Usage(input=150, output=25, cache_read=45, cache_write=50, reported_cost=0.015)

    delta = current.delta_since(previous)

    assert delta.input == 50
    assert delta.output == 5
    assert delta.cache_read == 15
    assert delta.cache_write == 10
    assert delta.reported_cost == pytest.approx(0.005)


def test_usage_accepts_structured_reported_cost() -> None:
    usage = Usage.from_message_usage({"input": 1, "output": 2, "cost": {"usd": "0.123"}})

    assert usage.reported_cost == pytest.approx(0.123)


def test_compute_cost_uses_explicit_cache_rates() -> None:
    model = Model(
        key="m",
        provider="p",
        model_id="id",
        pricing=Pricing(input=10.0, output=20.0, cache_read=1.0, cache_write=12.0),
    )
    usage = Usage(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000, reported_cost=123.0)

    cost = compute_cost(usage, model)

    assert cost.usd == 43.0
    assert cost.reported_usd == 123.0


def test_compute_cost_defaults_cache_rates_to_input_rate() -> None:
    model = Model(
        key="m",
        provider="p",
        model_id="id",
        pricing=Pricing(input=10.0, output=20.0),
    )
    usage = Usage(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000)

    cost = compute_cost(usage, model)

    assert cost.usd == 50.0
