"""The phase runner + results assembly, exercised offline (PiSession monkeypatched).

These pin the result.json sentinel contract and that trial.json stays
aggregate-compatible, without any real Pi call, git worktree, or network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from duobench.config import Condition, Config, Model, Pricing
from duobench.cost import PhaseCost
from duobench.impl_phase import ImplResult

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import run_phase  # noqa: E402


def _cfg() -> Config:
    models = {
        "kimi": Model("kimi", "kimi-provider", "kimi-model", Pricing(1, 2)),
        "gpt": Model("gpt", "gpt-provider", "gpt-model", Pricing(3, 4)),
    }
    return Config(models=models, judges=["kimi", "gpt"], conditions=[Condition("kimi-solo", "kimi", "kimi")])


@pytest.fixture()
def patched(monkeypatch):
    """Patch config loading + the phase engine calls so no Pi/git is needed."""
    import duobench.engine as engine

    monkeypatch.setattr(run_phase, "load_config", lambda *a, **k: _cfg())
    return engine


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def test_plan_phase_writes_result_sentinel(tmp_path, patched, monkeypatch):
    def fake_run_plan_phase(planner, prompt, out_dir, **kwargs):
        (out_dir / "plan.md").write_text("the plan")
        return "the plan", PhaseCost(1, 1, 0, 0, 0.05, source="configured"), 3.0

    monkeypatch.setattr(patched, "run_plan_phase", fake_run_plan_phase)
    out = tmp_path / "shared-plans" / "kimi" / "trial-0"
    rc = run_phase.main([
        "--phase", "plan", "--run-dir", str(tmp_path), "--out-dir", str(out),
        "--issue", "https://x/issues/1", "--planner", "kimi", "--trial", "0",
    ])
    assert rc == 0
    res = _read(out / "result.json")
    assert res["phase"] == "plan"
    assert res["status"] == "complete"
    assert res["exit_ok"] is True
    assert res["cost_usd"] == 0.05
    assert res["artifact"]["plan_path"].endswith("plan.md")
    assert (out / "plan.md").is_file()
    assert (out / "shared-plan.json").is_file()


def test_implement_phase_writes_trial_and_result(tmp_path, patched, monkeypatch):
    # plan input
    plan_dir = tmp_path / "shared-plans" / "kimi" / "trial-0"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text("plan")
    (plan_dir / "shared-plan.json").write_text(json.dumps({"cost_usd": 0.02, "cost_source": "configured", "duration_s": 1.0}))

    # a real git repo to stand in for the worktree
    repo = tmp_path / "wt"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True)
    (repo / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "c"], cwd=repo, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    monkeypatch.setattr(patched, "prepare_worktree", lambda repo_dir, build_dir, *, branch, submission_mode: repo)
    monkeypatch.setattr(patched, "run_impl_phase", lambda *a, **k: ImplResult(
        cost=PhaseCost(1, 1, 0, 0, 0.30, source="configured"),
        turns=1, status="complete", final_text=sha, commit_sha=sha,
        submission_mode="local_commit", duration_s=2.0, notes=[],
    ))

    out = tmp_path / "conditions" / "kimi-solo" / "trial-0"
    rc = run_phase.main([
        "--phase", "implement", "--run-dir", str(tmp_path), "--out-dir", str(out),
        "--issue", "https://x/issues/1", "--condition", "kimi-solo",
        "--planner", "kimi", "--implementer", "kimi",
        "--plan-path", str(plan_dir / "plan.md"), "--trial", "0",
    ])
    assert rc == 0
    res = _read(out / "result.json")
    assert res["status"] == "complete"
    assert res["artifact"]["commit_sha"] == sha
    trial = _read(out / "trial.json")
    # aggregate-compatible shape
    assert set(trial) >= {"benchmark", "artifacts", "record", "meta"}
    assert trial["record"]["condition_id"] == "kimi-solo"
    assert trial["artifacts"]["commit"]["sha"] == sha


def test_phase_failure_still_writes_error_sentinel(tmp_path, patched, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(patched, "run_plan_phase", boom)
    out = tmp_path / "shared-plans" / "kimi" / "trial-0"
    rc = run_phase.main([
        "--phase", "plan", "--run-dir", str(tmp_path), "--out-dir", str(out),
        "--issue", "https://x/issues/1", "--planner", "kimi", "--trial", "0",
    ])
    assert rc == 1
    res = _read(out / "result.json")
    assert res["status"] == "error"
    assert res["exit_ok"] is False
    assert "planner exploded" in res["error"]


def test_judge_sentinel_goes_under_results(tmp_path, patched, monkeypatch):
    from duobench.judge import JudgeScore

    out = tmp_path / "conditions" / "kimi-solo" / "trial-0"
    out.mkdir(parents=True)
    (out / "verify.json").write_text("{}")
    build = out / "worktree"
    build.mkdir()
    (build / "f.txt").write_text("x")

    def fake_judge_build(model, key, *a, transcript_path=None, **k):
        if transcript_path:
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(json.dumps({"turns": [{"assistant_text": "{}", "cost": {"usd": 0.01, "source": "configured"}}], "stats": {"usd": 0.01}}))
        return JudgeScore(key, 8, 7, 9, 6, notes="ok")

    monkeypatch.setattr(patched, "judge_build", fake_judge_build)
    rc = run_phase.main([
        "--phase", "judge", "--run-dir", str(tmp_path), "--out-dir", str(out),
        "--condition", "kimi-solo", "--issue", "https://x/issues/1",
        "--judge-key", "gpt", "--build-dir", str(build), "--commit-sha", "abc1234", "--trial", "0",
    ])
    assert rc == 0
    res = _read(out / "results" / "judge-gpt.json")
    assert res["status"] == "complete"
    assert res["artifact"]["scores"]["task_completion"] == 8


def test_assemble_results_folds_judges_into_results(tmp_path):
    from duobench.engine import assemble_results

    (tmp_path / "run_state.json").write_text(json.dumps({
        "issue": "https://github.com/example/repo/issues/123",
        "issue_created_at": "2026-05-20T12:00:00Z",
        "base_commit_sha": "abc123",
        "fix_commit_sha": "def456",
    }))

    # one condition, one trial, two judge sentinels
    td = tmp_path / "conditions" / "kimi-solo" / "trial-0"
    td.mkdir(parents=True)
    td.joinpath("trial.json").write_text(json.dumps({
        "benchmark": {}, "artifacts": {},
        "record": {"condition_id": "kimi-solo", "planner": "kimi", "implementer": "kimi",
                   "trial": 0, "cost_usd": 0.5, "dimensions": {}, "per_judge": {},
                   "impl_status": "complete", "cost_source": "configured"},
        "meta": {},
    }))
    (td / "results").mkdir()
    for jk, val in (("kimi", 8), ("gpt", 6)):
        (td / "results" / f"judge-{jk}.json").write_text(json.dumps({
            "artifact": {"scores": {"judge": jk, "task_completion": val, "correctness": val,
                                     "code_quality": val, "verification": val, "notes": "", "error": None}},
        }))

    results = assemble_results(tmp_path)
    cond = results["conditions"]["kimi-solo"]
    assert cond["dimensions"]["task_completion"] == 7.0  # mean of 8 and 6
    assert set(results["self_bias"]) == {"kimi", "gpt"}
    assert results["run"]["issue_created_at"] == "2026-05-20T12:00:00Z"
    assert results["run"]["base_commit_sha"] == "abc123"
    assert results["run"]["fix_commit_sha"] == "def456"
    # scores written back into trial.json
    trial = _read(td / "trial.json")
    assert len(trial["judge_scores"]) == 2
    assert (tmp_path / "results.json").is_file()
