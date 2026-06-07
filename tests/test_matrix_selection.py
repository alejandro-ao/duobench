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


def test_matrix_selection_accepts_direct_pi_specs_and_rejects_mixed_styles():
    conditions = make_matrix_conditions(_cfg(), ["missing-model:high"], ["kimi"])
    assert conditions[0].planner == "missing-model:high"
    with pytest.raises(ConfigError):
        select_run_conditions(_cfg(), condition_ids=["kimi-x-gpt"], model_keys=["kimi"])
    with pytest.raises(ConfigError):
        select_run_conditions(_cfg(), planner_keys=["kimi"])


def test_model_spec_thinking_suffix_is_extracted_from_config():
    cfg = _cfg()
    parsed = cfg.model("kimi:high")
    assert parsed.thinking_level == "high"
    assert parsed.key == "kimi:high"
    assert parsed.model_id == "kimi-model"

    parsed_direct = cfg.model("opus-provider/opus-model:low")
    assert parsed_direct.thinking_level == "low"
    assert parsed_direct.provider == "opus-provider"
    assert parsed_direct.model_id == "opus-model"

    parsed_registry_override = cfg.model("kimi:low")
    assert parsed_registry_override.thinking_level == "low"
    assert parsed_registry_override.provider == "kimi-provider"

    with pytest.raises(ConfigError, match="unknown thinking level"):
        cfg.model("kimi:banana")
