"""Orchestrator CLI — a deterministic script (NOT an agent).

Sequences: plan → implement → verify per condition×trial, then judge panel over every
build, aggregates, and draws charts. The only agentic work is inside the Pi sessions.

Usage:
  uv run duobench run [--trials N] [--conditions a,b,c] [--dry-run] [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from duobench.aggregate import TrialRecord, aggregate
from duobench.charts import generate_charts
from duobench.config import Condition, Config, ConfigError, Model, load_config
from duobench.cost import PhaseCost, compute_cost
from duobench.judge import DIMENSIONS, JudgeScore, average_dimensions, judge_panel
from duobench.plan_phase import run_plan_phase
from duobench.impl_phase import run_impl_phase
from duobench.verify import verify_build
from duobench.pi_rpc import PiRpcError, TurnResult, Usage
from duobench.report import generate_report
from duobench.fingerprint import make_benchmark_fingerprint
from duobench.transcript import new_transcript
from duobench.ui import make_ui

AUTO_PARALLEL_WORKERS = 2
ALL_PARALLEL_WORKERS = 10_000


@dataclass(frozen=True)
class SharedPlan:
    planner: str
    trial: int
    plan_text: str
    cost_usd: float
    source_dir: Path


class LogOnlyUI:
    """UI proxy for worker threads: keep logs, suppress single-phase counters."""

    def __init__(self, ui) -> None:
        self._ui = ui

    def log(self, message: str) -> None:
        if self._ui:
            self._ui.log(message)
        else:
            print(message, flush=True)

    def start_phase(self, name: str, model: str = "") -> None:
        pass

    def end_phase(self, status: str = "complete") -> None:
        pass

    def add_turn_result(self, usage, cost_usd: float, reported_usd: float = 0.0) -> None:
        pass

    def on_rpc_event(self, ev: dict) -> None:
        pass


def _load_prompt(name: str) -> str:
    """Load prompt from ./prompts when present, otherwise from packaged defaults."""
    local = Path("prompts") / name
    if local.is_file():
        return local.read_text()
    return (resources.files("duobench.defaults.prompts") / name).read_text()


def _stable_int(key: str, low: int, high: int) -> int:
    """Deterministic pseudo-random integer, inclusive."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return low + (int(digest[:12], 16) % (high - low + 1))


def _model_quality_hint(model_key: str) -> float:
    """Small dry-run-only quality prior so demo results are varied and plausible."""
    low = model_key.lower()
    if any(s in low for s in ("opus", "claude")):
        base = 8.8
    elif any(s in low for s in ("gpt", "openai")):
        base = 8.4
    elif "kimi" in low:
        base = 7.6
    elif any(s in low for s in ("glm", "deepseek", "qwen")):
        base = 7.3
    elif any(s in low for s in ("mini", "minimax", "mistral")):
        base = 7.0
    else:
        base = 6.8
    return base + (_stable_int(model_key, -20, 20) / 100)


def _clamp_score(value: float) -> int:
    return max(1, min(10, int(round(value))))


def _fake_usage(key: str, phase: str, trial: int) -> Usage:
    if phase == "plan":
        return Usage(
            input=_stable_int(f"{key}:{phase}:{trial}:in", 18_000, 42_000),
            output=_stable_int(f"{key}:{phase}:{trial}:out", 3_000, 9_000),
            cache_read=_stable_int(f"{key}:{phase}:{trial}:cache", 0, 8_000),
        )
    if phase == "judge":
        return Usage(
            input=_stable_int(f"{key}:{phase}:{trial}:in", 25_000, 65_000),
            output=_stable_int(f"{key}:{phase}:{trial}:out", 500, 1_500),
            cache_read=_stable_int(f"{key}:{phase}:{trial}:cache", 0, 5_000),
        )
    return Usage(
        input=_stable_int(f"{key}:{phase}:{trial}:in", 70_000, 180_000),
        output=_stable_int(f"{key}:{phase}:{trial}:out", 18_000, 55_000),
        cache_read=_stable_int(f"{key}:{phase}:{trial}:cache", 0, 20_000),
    )


def _fake_turn_result(text: str, usage: Usage, *, tool_calls: int = 0) -> TurnResult:
    content: list[dict] = [{"type": "text", "text": text}]
    for idx in range(tool_calls):
        content.append({"type": "tool_use", "name": "write" if idx == 0 else "edit", "input": {}})
    return TurnResult(
        text=text,
        usage=usage,
        raw_messages=[
            {"role": "user", "content": [{"type": "text", "text": "[dry-run synthetic prompt]"}]},
            {
                "role": "assistant",
                "content": content,
                "usage": {
                    "input": usage.input,
                    "output": usage.output,
                    "cacheRead": usage.cache_read,
                    "cacheWrite": usage.cache_write,
                    "cost": usage.reported_cost,
                },
            },
        ],
    )


def _write_fake_transcript(
    *,
    phase: str,
    model: Model,
    prompt: str,
    assistant_text: str,
    usage: Usage,
    cost: PhaseCost,
    path: Path,
    status: str = "complete",
    duration_s: float = 12.0,
    tool_calls: int = 0,
) -> None:
    transcript = new_transcript(phase, model)
    transcript.add_turn(
        kind="dry_run",
        prompt=prompt,
        result=_fake_turn_result(assistant_text, usage, tool_calls=tool_calls),
        cost=cost,
        started_at=0.0,
        ended_at=duration_s,
    )
    transcript.status = status
    transcript.notes = ["synthetic dry-run transcript; no model/API call was made"]
    transcript.write(path)


def _stub_plan(planner_key: str = "stub-planner") -> str:
    return (
        f"# Dry-run WebOS plan from {planner_key}\n\n"
        "- Build a desktop shell with a taskbar, launcher, notifications, and windows.\n"
        "- Implement apps for Files, Notes, Browser, Terminal, Music, Settings, and Games.\n"
        "- Keep state in localStorage and split behavior into WindowManager, AppRegistry, "
        "FileSystem, and ThemeManager modules.\n"
    )


def _stub_build(build_dir: Path, *, title: str = "Dry-run WebOS", accent: str = "#7c9cff") -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "index.html").write_text(
        f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body{{margin:0;height:100vh;background:linear-gradient(135deg,#111827,#1f2a44);font-family:system-ui;color:white;overflow:hidden}}
    #desktop{{display:grid;grid-template-columns:repeat(4,92px);gap:18px;padding:28px}}
    .desktop-icon{{display:grid;place-items:center;height:82px;border-radius:18px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);cursor:pointer}}
    .desktop-icon:before{{content:attr(data-app);display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:{accent};margin-bottom:6px}}
    .taskbar{{position:fixed;left:18px;right:18px;bottom:14px;height:54px;border-radius:18px;background:rgba(5,8,16,.72);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.18)}}
    .window{{position:absolute;left:160px;top:110px;width:420px;height:280px;border-radius:18px;background:#f8fafc;color:#111827;box-shadow:0 24px 80px rgba(0,0,0,.38);overflow:hidden}}
    .window header{{padding:12px 16px;background:{accent};color:white;font-weight:700}}
    .window main{{padding:18px}}
  </style>
</head>
<body>
  <div id="desktop">
    <div class="desktop-icon" data-app="Files">Files</div>
    <div class="desktop-icon" data-app="Notes">Notes</div>
    <div class="desktop-icon" data-app="Browser">Browser</div>
    <div class="desktop-icon" data-app="Terminal">Terminal</div>
    <div class="desktop-icon" data-app="Music">Music</div>
    <div class="desktop-icon" data-app="Settings">Settings</div>
  </div>
  <div class="taskbar"></div>
  <script>
    document.querySelectorAll('.desktop-icon').forEach(icon => icon.onclick = () => {{
      const w = document.createElement('section');
      w.className = 'window';
      w.innerHTML = `<header>${{icon.dataset.app}}</header><main><h2>${{icon.dataset.app}}</h2><p>Synthetic dry-run app shell.</p></main>`;
      document.body.appendChild(w);
    }});
  </script>
</body>
</html>"""
    )


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _dedupe_ordered(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _validate_model_keys(cfg: Config, keys: list[str], flag: str) -> list[str]:
    keys = _dedupe_ordered(keys)
    if not keys:
        raise ConfigError(f"{flag} must include at least one model key")
    missing = [key for key in keys if key not in cfg.models]
    if missing:
        known = ", ".join(cfg.models)
        raise ConfigError(f"unknown model key(s) in {flag}: {', '.join(missing)}. Known models: {known}")
    return keys


def select_conditions(cfg: Config, only: list[str] | None) -> list[Condition]:
    if not only:
        return cfg.conditions
    by_id = {c.id: c for c in cfg.conditions}
    missing = [o for o in only if o not in by_id]
    if missing:
        raise ConfigError(f"unknown condition id(s): {', '.join(missing)}")
    return [by_id[o] for o in only]


def make_matrix_conditions(cfg: Config, planners: list[str], implementers: list[str]) -> list[Condition]:
    """Generate the full planner×implementer matrix for the requested model keys."""
    planners = _validate_model_keys(cfg, planners, "--planners/--models")
    implementers = _validate_model_keys(cfg, implementers, "--implementers/--models")
    conditions: list[Condition] = []
    used_ids: set[str] = set()
    for planner in planners:
        for implementer in implementers:
            base = (
                f"{_safe_path_part(planner)}-solo"
                if planner == implementer
                else f"{_safe_path_part(planner)}-x-{_safe_path_part(implementer)}"
            )
            cid = base
            suffix = 2
            while cid in used_ids:
                cid = f"{base}-{suffix}"
                suffix += 1
            used_ids.add(cid)
            conditions.append(Condition(id=cid, planner=planner, implementer=implementer))
    return conditions


def select_run_conditions(
    cfg: Config,
    *,
    condition_ids: list[str] | None = None,
    model_keys: list[str] | None = None,
    planner_keys: list[str] | None = None,
    implementer_keys: list[str] | None = None,
) -> tuple[list[Condition], str]:
    """Resolve CLI selection into concrete planner×implementer conditions.

    The simple path is ``--models a,b,c``: it creates one shared planning run per
    model/trial and then every planner×implementer build. ``--conditions`` remains as a
    backwards-compatible escape hatch for hand-picked pairs from conditions.yaml.
    """
    condition_ids = condition_ids or []
    model_keys = model_keys or []
    planner_keys = planner_keys or []
    implementer_keys = implementer_keys or []

    matrix_requested = bool(model_keys or planner_keys or implementer_keys)
    if condition_ids and matrix_requested:
        raise ConfigError("use either --conditions or matrix flags (--models/--planners/--implementers), not both")

    if condition_ids:
        return select_conditions(cfg, condition_ids), "explicit conditions from conditions.yaml"

    if model_keys:
        if planner_keys or implementer_keys:
            raise ConfigError("--models cannot be combined with --planners or --implementers; use one style")
        keys = _validate_model_keys(cfg, model_keys, "--models")
        return make_matrix_conditions(cfg, keys, keys), f"full matrix from --models ({len(keys)} models)"

    if planner_keys or implementer_keys:
        if not planner_keys or not implementer_keys:
            raise ConfigError("provide both --planners and --implementers, or use --models for a square matrix")
        planners = _validate_model_keys(cfg, planner_keys, "--planners")
        implementers = _validate_model_keys(cfg, implementer_keys, "--implementers")
        return make_matrix_conditions(cfg, planners, implementers), (
            f"rectangular matrix from --planners/--implementers ({len(planners)}×{len(implementers)})"
        )

    return cfg.conditions, "explicit conditions from conditions.yaml"


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)


def _unique_planners(conditions: list[Condition]) -> list[str]:
    planners: list[str] = []
    seen: set[str] = set()
    for cond in conditions:
        if cond.planner not in seen:
            seen.add(cond.planner)
            planners.append(cond.planner)
    return planners


def resolve_parallel(value: str, *, auto_default: int = AUTO_PARALLEL_WORKERS) -> int:
    if value == "auto":
        return max(1, auto_default)
    if value == "all":
        return ALL_PARALLEL_WORKERS
    try:
        workers = int(value)
    except ValueError as e:
        raise ConfigError("--parallel must be 'auto', 'all', or a positive integer") from e
    if workers < 1:
        raise ConfigError("--parallel must be 'auto', 'all', or a positive integer")
    return workers


def _phase_ui(ui, parallel_workers: int):
    return ui if parallel_workers <= 1 else LogOnlyUI(ui)


def run_shared_plan(
    cfg: Config,
    planner_key: str,
    trial: int,
    plan_dir: Path,
    prompts: dict[str, str],
    *,
    dry_run: bool,
    plan_timeout: float,
    ui=None,
) -> SharedPlan:
    planner = cfg.model(planner_key)
    plan_dir.mkdir(parents=True, exist_ok=True)
    (ui.log if ui else print)(f"  [shared plan trial {trial}] planner={planner_key}")
    if dry_run:
        plan_text = _stub_plan(planner_key)
        (plan_dir / "plan.md").write_text(plan_text)
        usage = _fake_usage(planner_key, "plan", trial)
        pc = compute_cost(usage, planner)
        _write_fake_transcript(
            phase="planner",
            model=planner,
            prompt=prompts["architect"],
            assistant_text=plan_text,
            usage=usage,
            cost=pc,
            path=plan_dir / "planner-transcript.json",
            duration_s=float(_stable_int(f"{planner_key}:plan:{trial}:duration", 18, 75)),
        )
        plan_cost = pc.usd
    else:
        plan_text, pc = run_plan_phase(
            planner,
            prompts["architect"],
            plan_dir,
            timeout=plan_timeout,
            pin_temperature=True,
            ui=ui,
        )
        plan_cost = pc.usd
    (plan_dir / "shared-plan.json").write_text(json.dumps(
        {
            "planner": planner_key,
            "trial": trial,
            "cost_usd": round(plan_cost, 6),
            "plan_dir": str(plan_dir),
        },
        indent=2,
    ))
    return SharedPlan(
        planner=planner_key,
        trial=trial,
        plan_text=plan_text,
        cost_usd=plan_cost,
        source_dir=plan_dir,
    )


def prepare_shared_plans(
    cfg: Config,
    conditions: list[Condition],
    trials: int,
    run_dir: Path,
    prompts: dict[str, str],
    *,
    dry_run: bool,
    plan_timeout: float,
    parallel_workers: int = 1,
    ui=None,
) -> dict[tuple[str, int], SharedPlan]:
    plan_root = run_dir / "shared-plans"
    jobs: list[tuple[int, str, int, Path]] = []
    for trial in range(trials):
        for planner_key in _unique_planners(conditions):
            plan_dir = plan_root / _safe_path_part(planner_key) / f"trial-{trial}"
            jobs.append((len(jobs), planner_key, trial, plan_dir))

    plans: dict[tuple[str, int], SharedPlan] = {}
    phase_ui = _phase_ui(ui, parallel_workers)
    if parallel_workers <= 1 or len(jobs) <= 1:
        for _, planner_key, trial, plan_dir in jobs:
            plans[(planner_key, trial)] = run_shared_plan(
                cfg,
                planner_key,
                trial,
                plan_dir,
                prompts,
                dry_run=dry_run,
                plan_timeout=plan_timeout,
                ui=phase_ui,
            )
        return plans

    with ThreadPoolExecutor(max_workers=min(parallel_workers, len(jobs))) as pool:
        futures = {
            pool.submit(
                run_shared_plan,
                cfg,
                planner_key,
                trial,
                plan_dir,
                prompts,
                dry_run=dry_run,
                plan_timeout=plan_timeout,
                ui=phase_ui,
            ): (planner_key, trial)
            for _, planner_key, trial, plan_dir in jobs
        }
        for fut in as_completed(futures):
            planner_key, trial = futures[fut]
            plans[(planner_key, trial)] = fut.result()
    return plans


def copy_plan_artifacts(plan: SharedPlan, trial_dir: Path) -> None:
    trial_dir.mkdir(parents=True, exist_ok=True)
    for name in ("plan.md", "planner-transcript.json", "planner-events.jsonl"):
        src = plan.source_dir / name
        if src.exists():
            shutil.copy(src, trial_dir / name)
    if not (trial_dir / "plan.md").exists():
        (trial_dir / "plan.md").write_text(plan.plan_text)


def run_condition_trial(
    cfg: Config,
    cond: Condition,
    trial: int,
    trial_dir: Path,
    prompts: dict[str, str],
    shared_plan: SharedPlan,
    *,
    dry_run: bool,
    plan_timeout: float,
    impl_timeout: float,
    judge_timeout: float,
    ui=None,
) -> tuple[TrialRecord, dict]:
    benchmark = make_benchmark_fingerprint(
        cfg, cond, prompts,
        dry_run=dry_run,
        plan_timeout=plan_timeout,
        impl_timeout=impl_timeout,
        judge_timeout=judge_timeout,
    )
    implementer = cfg.model(cond.implementer)
    build_dir = trial_dir / "build"
    shots_dir = trial_dir / "screenshots"
    (ui.log if ui else print)(f"  [{cond.id} trial {trial}] plan={cond.planner} impl={cond.implementer}")

    # --- plan handoff ---
    copy_plan_artifacts(shared_plan, trial_dir)
    plan_text = shared_plan.plan_text
    plan_cost = shared_plan.cost_usd

    # --- implement ---
    if dry_run:
        accent = f"#{_stable_int(cond.id, 0, 0xFFFFFF):06x}"
        _stub_build(build_dir, title=f"{cond.id} dry-run WebOS", accent=accent)
        usage = _fake_usage(cond.id, "implement", trial)
        ic = compute_cost(usage, implementer)
        _write_fake_transcript(
            phase="implementer",
            model=implementer,
            prompt=prompts["implement"].replace("{plan}", plan_text),
            assistant_text=f"Built synthetic WebOS for {cond.id}. BUILD COMPLETE",
            usage=usage,
            cost=ic,
            path=trial_dir / "implementer-transcript.json",
            duration_s=float(_stable_int(f"{cond.id}:impl:{trial}:duration", 90, 900)),
            tool_calls=_stable_int(f"{cond.id}:impl:{trial}:tools", 4, 24),
        )
        impl_cost = ic.usd
        impl_status = "complete"
    else:
        impl = run_impl_phase(implementer, prompts["implement"], plan_text, build_dir,
                              timeout=impl_timeout, pin_temperature=True, ui=ui)
        impl_cost = impl.cost.usd
        impl_status = impl.status

    # --- verify ---
    if ui:
        ui.start_phase("Verifying", "Playwright")
    vres = verify_build(build_dir, shots_dir)
    if ui:
        ui.end_phase("complete" if vres.boots_ok else "issues found")
    (trial_dir / "verify.json").write_text(json.dumps(vres.to_dict(), indent=2))

    record = TrialRecord(
        condition_id=cond.id,
        planner=cond.planner,
        implementer=cond.implementer,
        trial=trial,
        cost_usd=round(plan_cost + impl_cost, 6),
        dimensions={d: 0.0 for d in DIMENSIONS},   # filled after judging
        per_judge={},
        impl_status=impl_status,
    )
    # stash paths for the judging pass
    record_meta = {
        "build_dir": str(build_dir),
        "smoke_summary": vres.summary_for_judge(),
        "screenshots": vres.screenshots,
    }
    artifacts = {
        "plan": {
            "shared": True,
            "planner": shared_plan.planner,
            "trial": shared_plan.trial,
            "source_dir": str(shared_plan.source_dir),
            "cost_usd": round(shared_plan.cost_usd, 6),
        }
    }
    (trial_dir / "trial.json").write_text(json.dumps(
        {
            "benchmark": benchmark.to_dict(),
            "artifacts": artifacts,
            "record": record.__dict__,
            "meta": record_meta,
        },
        indent=2,
        default=str,
    ))
    return record, record_meta


def run_condition_trials(
    cfg: Config,
    conditions: list[Condition],
    trials: int,
    cond_root: Path,
    prompts: dict[str, str],
    shared_plans: dict[tuple[str, int], SharedPlan],
    *,
    dry_run: bool,
    plan_timeout: float,
    impl_timeout: float,
    judge_timeout: float,
    parallel_workers: int = 1,
    ui=None,
) -> tuple[list[TrialRecord], list[dict]]:
    jobs: list[tuple[int, Condition, int, Path]] = []
    for cond in conditions:
        for trial in range(trials):
            trial_dir = cond_root / cond.id / f"trial-{trial}"
            trial_dir.mkdir(parents=True, exist_ok=True)
            jobs.append((len(jobs), cond, trial, trial_dir))

    phase_ui = _phase_ui(ui, parallel_workers)

    def run_job(cond: Condition, trial: int, trial_dir: Path) -> tuple[int, TrialRecord, dict]:
        if ui:
            ui.start_trial(cond.id, trial, "running")
        try:
            rec, meta = run_condition_trial(
                cfg,
                cond,
                trial,
                trial_dir,
                prompts,
                shared_plan=shared_plans[(cond.planner, trial)],
                dry_run=dry_run,
                plan_timeout=plan_timeout,
                impl_timeout=impl_timeout,
                judge_timeout=judge_timeout,
                ui=phase_ui,
            )
            if ui:
                ui.finish_trial(cond.id, trial, "built")
            return rec.trial, rec, meta
        except Exception:
            if ui:
                ui.finish_trial(cond.id, trial, "failed")
            raise

    results: list[tuple[int, TrialRecord, dict]] = []
    if parallel_workers <= 1 or len(jobs) <= 1:
        for idx, cond, trial, trial_dir in jobs:
            _, rec, meta = run_job(cond, trial, trial_dir)
            results.append((idx, rec, meta))
    else:
        with ThreadPoolExecutor(max_workers=min(parallel_workers, len(jobs))) as pool:
            futures = {
                pool.submit(run_job, cond, trial, trial_dir): idx
                for idx, cond, trial, trial_dir in jobs
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                _, rec, meta = fut.result()
                results.append((idx, rec, meta))

    results.sort(key=lambda item: item[0])
    records = [rec for _, rec, _ in results]
    metas = [meta for _, _, meta in results]
    return records, metas


def _dry_run_judge_scores(cfg: Config, rec: TrialRecord) -> list[JudgeScore]:
    planner_q = _model_quality_hint(rec.planner)
    implementer_q = _model_quality_hint(rec.implementer)
    base = {
        "architecture": 0.72 * planner_q + 0.28 * implementer_q,
        "correctness": 0.22 * planner_q + 0.78 * implementer_q,
        "visual_ux": 0.15 * planner_q + 0.85 * implementer_q,
    }
    scores: list[JudgeScore] = []
    for judge_key in cfg.judges:
        jitter = _stable_int(f"{judge_key}:{rec.condition_id}:{rec.trial}:jitter", -6, 6) / 10
        # Tiny visible self-bias in the demo so the self-bias matrix is meaningful.
        bias = 0.25 if judge_key in {rec.planner, rec.implementer} else 0.0
        scores.append(
            JudgeScore(
                judge=judge_key,
                architecture=_clamp_score(base["architecture"] + jitter + bias),
                correctness=_clamp_score(base["correctness"] + jitter + bias),
                visual_ux=_clamp_score(base["visual_ux"] + jitter + bias),
                notes="synthetic dry-run score; no judge model was called",
            )
        )
    return scores


def _write_dry_run_judge_transcripts(
    cfg: Config,
    scores: list[JudgeScore],
    trial_dir: Path,
    judge_prompt: str,
    trial: int,
) -> None:
    judge_dir = trial_dir / "judge-transcripts"
    judge_dir.mkdir(parents=True, exist_ok=True)
    for score in scores:
        model = cfg.model(score.judge)
        usage = _fake_usage(f"{score.judge}:{trial_dir.parent.name}", "judge", trial)
        cost = compute_cost(usage, model)
        assistant_text = json.dumps(
            {
                "architecture": score.architecture,
                "correctness": score.correctness,
                "visual_ux": score.visual_ux,
                "notes": score.notes,
            }
        )
        _write_fake_transcript(
            phase="judge",
            model=model,
            prompt=judge_prompt,
            assistant_text=assistant_text,
            usage=usage,
            cost=cost,
            path=judge_dir / f"{score.judge}.json",
            duration_s=float(_stable_int(f"{score.judge}:{trial_dir}:judge-duration", 8, 45)),
        )


def _main() -> None:
    ap = argparse.ArgumentParser(
        prog="duobench",
        description="Run planner×implementer model benchmarks over Pi RPC.",
        epilog=(
            "Examples:\n"
            "  duobench run --dry-run\n"
            "  duobench run --models kimi-k2.6,gpt-5.5 --trials 1\n"
            "  duobench run --planners kimi-k2.6,gpt-5.5 --implementers gpt-5.5 --trials 3\n"
            "  duobench run --conditions kimi-solo,gpt-x-kimi --trials 3"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run", help="run the benchmark")
    rp.add_argument("--trials", type=int, default=1)
    rp.add_argument("--conditions", type=str, default="", help="comma-separated condition ids from conditions.yaml")
    rp.add_argument("--models", type=str, default="",
                    help="comma-separated model keys; generate the full planner×implementer matrix")
    rp.add_argument("--planners", type=str, default="",
                    help="comma-separated planner model keys for a rectangular matrix")
    rp.add_argument("--implementers", type=str, default="",
                    help="comma-separated implementer model keys for a rectangular matrix")
    rp.add_argument("--dry-run", action="store_true", help="stub all model calls with synthetic plans, builds, costs, and judge scores")
    rp.add_argument("--out", type=str, default="runs")
    rp.add_argument("--models-config", type=str, default="config/models.yaml")
    rp.add_argument("--conditions-config", type=str, default="config/conditions.yaml")
    rp.add_argument("--plan-timeout", type=float, default=600.0)
    rp.add_argument("--impl-timeout", type=float, default=1800.0)
    rp.add_argument("--judge-timeout", type=float, default=300.0)
    rp.add_argument("--parallel", type=str, default="auto",
                    help="planner/build concurrency: 'auto' (default), 'all', or a positive integer; use 1 for serial")
    rp.add_argument("--live", action=argparse.BooleanOptionalAction, default=None,
                    help="enable/disable the Rich live dashboard (default: auto when attached to a TTY)")
    rp.add_argument("--debug", action="store_true", help="show full Python tracebacks on errors")
    rep = sub.add_parser("report", help="generate/re-generate report.html for an existing run")
    rep.add_argument("run_dir", type=str)
    rep.add_argument("--debug", action="store_true", help="show full Python tracebacks on errors")
    args = ap.parse_args()

    if args.cmd == "report":
        report_path = generate_report(Path(args.run_dir))
        print(f"report written: {report_path}")
        return

    cfg = load_config(args.models_config, args.conditions_config)
    conditions, selection_mode = select_run_conditions(
        cfg,
        condition_ids=_parse_csv(args.conditions),
        model_keys=_parse_csv(args.models),
        planner_keys=_parse_csv(args.planners),
        implementer_keys=_parse_csv(args.implementers),
    )
    parallel_workers = resolve_parallel(args.parallel)

    prompts = {
        "architect": _load_prompt("architect.md"),
        "implement": _load_prompt("implement.md"),
        "judge": _load_prompt("judge.md"),
    }

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = Path(args.out) / ts
    cond_root = run_dir / "conditions"
    cond_root.mkdir(parents=True, exist_ok=True)
    ui = make_ui(args.live)
    ui.start_run(run_dir=run_dir, conditions=conditions, trials=args.trials, dry_run=args.dry_run)
    ui.log("\n=== duobench ===")
    ui.log(f"mode: {'DRY RUN (no model/API calls)' if args.dry_run else 'REAL RUN'}")
    ui.log(f"run dir: {run_dir}")
    ui.log(f"trials per condition: {args.trials}")
    ui.log(f"selection: {selection_mode}")
    parallel_label = "all jobs in each phase" if args.parallel == "all" else f"{parallel_workers} max"
    ui.log(f"parallel workers: {args.parallel} ({parallel_label})")
    plan_jobs = len(_unique_planners(conditions)) * args.trials
    impl_jobs = len(conditions) * args.trials
    judge_jobs = impl_jobs * len(cfg.judges)
    ui.log(f"phase plan: {plan_jobs} shared planner run(s) → build: {impl_jobs} implementation run(s) → judge: {judge_jobs} judge run(s)")
    ui.log("conditions:")
    for c in conditions:
        ui.log(f"  - {c.id}: planner={c.planner} implementer={c.implementer}")
    if not args.dry_run:
        ui.log("\nTip: if this is your first run, `duobench run --dry-run` validates the pipeline without API spend.")
    ui.log("")

    # --- phase 1: shared planning, then implement + verify per condition×trial ---
    ui.log("planning shared planner samples...")
    shared_plans = prepare_shared_plans(
        cfg,
        conditions,
        args.trials,
        run_dir,
        prompts,
        dry_run=args.dry_run,
        plan_timeout=args.plan_timeout,
        parallel_workers=parallel_workers,
        ui=ui,
    )

    records, metas = run_condition_trials(
        cfg,
        conditions,
        args.trials,
        cond_root,
        prompts,
        shared_plans,
        dry_run=args.dry_run,
        plan_timeout=args.plan_timeout,
        impl_timeout=args.impl_timeout,
        judge_timeout=args.judge_timeout,
        parallel_workers=parallel_workers,
        ui=ui,
    )

    # --- phase 2: judge panel over every build ---
    ui.log("judging...")
    for rec, meta in zip(records, metas):
        ui.start_trial(rec.condition_id, rec.trial, "judging")
        if args.dry_run:
            scores = _dry_run_judge_scores(cfg, rec)
            rec.per_judge = {
                s.judge: {d: getattr(s, d) for d in DIMENSIONS} for s in scores if s.error is None
            }
            rec.dimensions = average_dimensions(scores)
            trial_dir = Path(meta["build_dir"]).parent
            _write_dry_run_judge_transcripts(cfg, scores, trial_dir, prompts["judge"], rec.trial)
            existing_trial = json.loads((trial_dir / "trial.json").read_text())
            (trial_dir / "trial.json").write_text(json.dumps(
                {
                    "benchmark": existing_trial.get("benchmark"),
                    "artifacts": existing_trial.get("artifacts"),
                    "record": rec.__dict__,
                    "meta": meta,
                    "judge_scores": [s.to_dict() for s in scores],
                },
                indent=2, default=str,
            ))
            ui.finish_trial(rec.condition_id, rec.trial, "done")
            continue
        trial_dir = Path(meta["build_dir"]).parent
        scores = judge_panel(
            cfg, prompts["judge"], Path(meta["build_dir"]),
            meta["smoke_summary"], meta["screenshots"], timeout=args.judge_timeout,
            transcripts_dir=trial_dir / "judge-transcripts",
            ui=ui,
        )
        rec.per_judge = {
            s.judge: {d: getattr(s, d) for d in DIMENSIONS} for s in scores if s.error is None
        }
        rec.dimensions = average_dimensions(scores)
        trial_dir = Path(meta["build_dir"]).parent
        existing_trial = json.loads((trial_dir / "trial.json").read_text())
        (trial_dir / "trial.json").write_text(json.dumps(
            {
                "benchmark": existing_trial.get("benchmark"),
                "artifacts": existing_trial.get("artifacts"),
                "record": rec.__dict__,
                "meta": meta,
                "judge_scores": [s.to_dict() for s in scores],
            },
            indent=2, default=str,
        ))
        ui.finish_trial(rec.condition_id, rec.trial, "done")

    # --- phase 3: aggregate + charts ---
    results = aggregate(records, cfg.judges)
    (run_dir / "results.json").write_text(json.dumps(results, indent=2))

    results_dir = run_dir / "results"
    written = generate_charts(results, results_dir)
    # mirror committed artifacts to top-level results/ for the video
    top_results = Path("results")
    top_results.mkdir(exist_ok=True)
    for f in written + [run_dir / "results.json"]:
        shutil.copy(f, top_results / f.name)

    if ui:
        ui.start_phase("Generating report", "HTML")
    report_path = generate_report(run_dir)
    if ui:
        ui.end_phase("complete")
        ui.stop()

    print(f"\ndone. results.json + {len(written)} chart/csv files in {results_dir}")
    print(f"report: {report_path}")
    print(f"copied to {top_results}/")
    # leaderboard preview
    ranked = sorted(results["conditions"].items(), key=lambda kv: kv[1]["quality"], reverse=True)
    print("\nleaderboard (quality | cost$ | efficiency):")
    for cid, c in ranked:
        print(f"  {cid:14} {c['quality']:5.2f} | {c['cost_usd']:.4f} | {c['cost_efficiency']:.2f}")


def main() -> None:
    try:
        _main()
    except (ConfigError, PiRpcError) as e:
        if "--debug" in sys.argv:
            raise
        sys.exit(
            "\nERROR: " + str(e) +
            "\n\nTry:\n"
            "  - `uv run duobench run --dry-run` to validate local wiring\n"
            "  - check provider/model IDs in config/models.yaml\n"
            "  - rerun with `--debug` for a full traceback"
        )
    except KeyboardInterrupt:
        sys.exit("\nInterrupted by user.")
    except Exception as e:
        if "--debug" in sys.argv:
            raise
        sys.exit(
            f"\nUnexpected error: {e}\n\n"
            "Rerun with `--debug` for the full traceback."
        )


if __name__ == "__main__":
    main()
