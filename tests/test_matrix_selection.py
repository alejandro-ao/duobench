import pytest

from duobench.config import Condition, Config, ConfigError, Model, Pricing
from duobench.run import make_matrix_conditions, select_run_conditions


def _cfg() -> Config:
    models = {
        "kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2)),
        "gpt": Model("gpt", "gpt-provider", "gpt-model", Pricing(3, 4)),
        "opus": Model("opus", "opus-provider", "opus-model", Pricing(5, 6)),
    }
    conditions = [Condition("kimi-x-gpt", "kimi", "gpt")]
    return Config(models=models, judges=["kimi"], conditions=conditions)


def test_models_flag_generates_square_planner_implementer_matrix():
    conditions, mode = select_run_conditions(_cfg(), model_keys=["kimi", "gpt"])

    assert "full matrix" in mode
    assert [(c.id, c.planner, c.implementer) for c in conditions] == [
        ("kimi-solo", "kimi", "kimi"),
        ("kimi-x-gpt", "kimi", "gpt"),
        ("gpt-x-kimi", "gpt", "kimi"),
        ("gpt-solo", "gpt", "gpt"),
    ]


def test_role_specific_flags_generate_rectangular_matrix():
    conditions, mode = select_run_conditions(
        _cfg(),
        planner_keys=["kimi", "gpt"],
        implementer_keys=["opus"],
    )

    assert "rectangular matrix" in mode
    assert [(c.planner, c.implementer) for c in conditions] == [("kimi", "opus"), ("gpt", "opus")]


def test_explicit_conditions_still_use_conditions_config():
    conditions, mode = select_run_conditions(_cfg(), condition_ids=["kimi-x-gpt"])

    assert "conditions.yaml" in mode
    assert conditions == [Condition("kimi-x-gpt", "kimi", "gpt")]


def test_matrix_selection_rejects_unknown_models_and_mixed_styles():
    with pytest.raises(ConfigError):
        make_matrix_conditions(_cfg(), ["missing"], ["kimi"])
    with pytest.raises(ConfigError):
        select_run_conditions(_cfg(), condition_ids=["kimi-x-gpt"], model_keys=["kimi"])
    with pytest.raises(ConfigError):
        select_run_conditions(_cfg(), planner_keys=["kimi"])
