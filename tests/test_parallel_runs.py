import threading

import pytest

from duobench.aggregate import TrialRecord
from duobench.config import Condition, Config, Model, Pricing
from duobench.judge import DIMENSIONS
from duobench.run import SharedPlan, prepare_shared_plans, resolve_parallel, run_condition_trials


def _cfg() -> Config:
    models = {
        "kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2)),
        "gpt": Model("gpt", "gpt-provider", "gpt-model", Pricing(3, 4)),
    }
    conditions = [
        Condition("kimi-solo", "kimi", "kimi"),
        Condition("gpt-solo", "gpt", "gpt"),
    ]
    return Config(models=models, judges=["kimi", "gpt"], conditions=conditions)


def test_resolve_parallel_accepts_auto_and_positive_ints():
    assert resolve_parallel("auto") == 2
    assert resolve_parallel("1") == 1
    assert resolve_parallel("4") == 4


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_resolve_parallel_rejects_invalid_values(value):
    with pytest.raises(Exception):
        resolve_parallel(value)


def test_prepare_shared_plans_runs_independent_planners_concurrently(tmp_path, monkeypatch):
    import duobench.run as run_mod

    cfg = _cfg()
    prompts = {"architect": "plan", "implement": "implement", "judge": "judge"}
    barrier = threading.Barrier(2)

    def fake_run_shared_plan(cfg, planner_key, trial, plan_dir, prompts, *, dry_run, plan_timeout, ui=None):
        barrier.wait(timeout=2)
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "plan.md").write_text(f"plan from {planner_key}")
        return SharedPlan(planner_key, trial, f"plan from {planner_key}", 0.1, plan_dir)

    monkeypatch.setattr(run_mod, "run_shared_plan", fake_run_shared_plan)

    plans = prepare_shared_plans(
        cfg,
        cfg.conditions,
        1,
        tmp_path,
        prompts,
        dry_run=False,
        plan_timeout=600,
        parallel_workers=2,
    )

    assert sorted(plans) == [("gpt", 0), ("kimi", 0)]


def test_run_condition_trials_runs_independent_builds_concurrently(tmp_path, monkeypatch):
    import duobench.run as run_mod

    cfg = _cfg()
    prompts = {"architect": "plan", "implement": "implement", "judge": "judge"}
    barrier = threading.Barrier(2)
    shared_plans = {
        ("kimi", 0): SharedPlan("kimi", 0, "kimi plan", 0.1, tmp_path / "plans/kimi"),
        ("gpt", 0): SharedPlan("gpt", 0, "gpt plan", 0.1, tmp_path / "plans/gpt"),
    }

    def fake_run_condition_trial(cfg, cond, trial, trial_dir, prompts, shared_plan, **kwargs):
        barrier.wait(timeout=2)
        rec = TrialRecord(
            condition_id=cond.id,
            planner=cond.planner,
            implementer=cond.implementer,
            trial=trial,
            cost_usd=0.1,
            dimensions={d: 0.0 for d in DIMENSIONS},
        )
        return rec, {"build_dir": str(trial_dir / "build"), "smoke_summary": "{}", "screenshots": []}

    monkeypatch.setattr(run_mod, "run_condition_trial", fake_run_condition_trial)

    records, metas = run_condition_trials(
        cfg,
        cfg.conditions,
        1,
        tmp_path / "conditions",
        prompts,
        shared_plans,
        dry_run=False,
        plan_timeout=600,
        impl_timeout=1800,
        judge_timeout=300,
        parallel_workers=2,
    )

    assert [r.condition_id for r in records] == ["kimi-solo", "gpt-solo"]
    assert len(metas) == 2
