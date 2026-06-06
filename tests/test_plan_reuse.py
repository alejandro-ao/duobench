import json

from duobench.config import Condition, Config, Model, Pricing
from duobench.run import prepare_shared_plans, run_condition_trial


class _FakeVerifyResult:
    boots_ok = True
    screenshots = []

    def to_dict(self):
        return {
            "boots_ok": True,
            "desktop_rendered": True,
            "taskbar_rendered": True,
            "fatal_console_errors": [],
            "apps_attempted": 3,
            "apps_launched": 3,
            "app_results": [],
            "screenshots": [],
            "notes": [],
        }

    def summary_for_judge(self):
        return "{}"


def _cfg() -> Config:
    models = {
        "kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2)),
        "gpt": Model("gpt", "gpt-provider", "gpt-model", Pricing(3, 4)),
    }
    conditions = [
        Condition("kimi-solo", "kimi", "kimi"),
        Condition("kimi-x-gpt", "kimi", "gpt"),
        Condition("gpt-solo", "gpt", "gpt"),
    ]
    return Config(models=models, judges=["kimi", "gpt"], conditions=conditions)


def test_shared_plans_are_created_once_per_planner_and_trial(tmp_path):
    cfg = _cfg()
    prompts = {"architect": "plan", "implement": "implement", "judge": "judge"}

    plans = prepare_shared_plans(
        cfg,
        cfg.conditions,
        1,
        tmp_path,
        prompts,
        dry_run=True,
        plan_timeout=600,
    )

    assert sorted(plans) == [("gpt", 0), ("kimi", 0)]
    assert plans[("kimi", 0)].source_dir == tmp_path / "shared-plans" / "kimi" / "trial-0"
    assert plans[("kimi", 0)].cost_usd > 0
    assert (plans[("kimi", 0)].source_dir / "plan.md").exists()
    assert (plans[("kimi", 0)].source_dir / "planner-transcript.json").exists()


def test_condition_trials_reference_same_shared_plan(tmp_path, monkeypatch):
    import duobench.run as run_mod

    monkeypatch.setattr(run_mod, "verify_build", lambda build_dir, shots_dir: _FakeVerifyResult())
    cfg = _cfg()
    prompts = {"architect": "plan", "implement": "implement", "judge": "judge"}
    plans = prepare_shared_plans(
        cfg,
        cfg.conditions[:2],
        1,
        tmp_path,
        prompts,
        dry_run=True,
        plan_timeout=600,
    )
    shared_plan = plans[("kimi", 0)]

    for cond in cfg.conditions[:2]:
        trial_dir = tmp_path / "conditions" / cond.id / "trial-0"
        run_condition_trial(
            cfg,
            cond,
            0,
            trial_dir,
            prompts,
            shared_plan=shared_plan,
            dry_run=True,
            plan_timeout=600,
            impl_timeout=1800,
            judge_timeout=300,
        )

    first = json.loads((tmp_path / "conditions" / "kimi-solo" / "trial-0" / "trial.json").read_text())
    second = json.loads((tmp_path / "conditions" / "kimi-x-gpt" / "trial-0" / "trial.json").read_text())

    assert first["artifacts"]["plan"]["shared"] is True
    assert first["artifacts"]["plan"]["source_dir"] == second["artifacts"]["plan"]["source_dir"]
    assert first["record"]["cost_usd"] > first["artifacts"]["plan"]["cost_usd"]
    assert (tmp_path / "conditions" / "kimi-solo" / "trial-0" / "plan.md").read_text() == shared_plan.plan_text
    assert (tmp_path / "conditions" / "kimi-x-gpt" / "trial-0" / "plan.md").read_text() == shared_plan.plan_text
    assert (tmp_path / "conditions" / "kimi-solo" / "trial-0" / "implementer-transcript.json").exists()
