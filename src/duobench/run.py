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
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from duobench.aggregate import TrialRecord, aggregate
from duobench.charts import generate_charts
from duobench.config import Condition, Config, ConfigError, Model, load_config
from duobench.cost import PhaseCost, compute_cost
from duobench.judge import DIMENSIONS, JudgeScore, average_dimensions, judge_panel
from duobench.pi_rpc import PiSession
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
DEFAULT_ISSUE_URL = "https://github.com/example/repo/issues/1"


@dataclass(frozen=True)
class SharedPlan:
    planner: str
    trial: int
    plan_text: str
    cost_usd: float
    cost_source: str
    source_dir: Path
    duration_s: float = 0.0


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

    def start_job(self, job_id: str, kind: str, label: str, status: str = "running") -> None:
        if hasattr(self._ui, "start_job"):
            self._ui.start_job(job_id, kind, label, status)

    def finish_job(self, job_id: str, status: str = "complete") -> None:
        if hasattr(self._ui, "finish_job"):
            self._ui.finish_job(job_id, status)

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


def _load_issue_url(issue: str, *, dry_run: bool) -> str:
    text = issue.strip()
    if text:
        return text
    if dry_run:
        return DEFAULT_ISSUE_URL
    raise ConfigError("--issue is required for real runs; duobench is coupled to the GitHub issue → PR workflow")


def validate_pi_models(model_specs: list[str], *, timeout: float = 60.0, ui=None) -> None:
    # Validate with the full spec (including thinking label): some models
    # (e.g. minimax/MiniMax-M3) return empty final text with thinking off,
    # which would fail validation even though the benchmark phases always
    # set a thinking level explicitly.
    for spec in _dedupe_ordered(model_specs):
        if ui:
            ui.log(f"validating Pi model: {spec}")
        try:
            with PiSession(cwd=Path.cwd(), enable_tools=False, persist_session=False, initial_model=spec) as s:
                result = s.prompt("Reply with OK.", timeout=timeout)
                if "ok" not in result.text.lower():
                    raise ConfigError(f"model validation for {spec!r} returned unexpected response: {result.text[:120]}")
        except Exception as e:
            if isinstance(e, ConfigError):
                raise
            raise ConfigError(f"Pi model validation failed for {spec!r}: {e}") from e


def _check_issue_prereqs(*, dry_run: bool) -> None:
    if dry_run:
        return
    if shutil.which("git") is None:
        raise ConfigError("git is required for real GitHub issue → PR runs")
    if shutil.which("gh") is None:
        raise ConfigError("gh CLI is required for real GitHub issue → PR runs")
    _git(["rev-parse", "--show-toplevel"], Path.cwd())


def _is_unknown_model(cfg: Config, spec: str) -> bool:
    """Return True when the spec has no registry entry in models.yaml.

    Such specs are passed straight to Pi and skip the registry's defaults
    for provider, thinking, and pricing (an optional `:thinking` suffix
    does not affect registry lookup).
    """
    return spec.partition(":")[0] not in cfg.models


def _merge_cost_source(*sources: str) -> str:
    """Combine per-phase cost sources into a single label for the trial.

    Priority: any 'unknown' dominates (the user can't trust the dollar
    number); then 'configured'; then 'pi_reported'. This way the warning
    banner surfaces the weakest source for the trial.
    """
    if any(s == "unknown" for s in sources):
        return "unknown"
    if any(s == "configured" for s in sources):
        return "configured"
    return "pi_reported"


def _issue_url_from(prompts: dict[str, str]) -> str:
    return prompts.get("issue_url", DEFAULT_ISSUE_URL)


def _format_prompt_template(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError as e:
        missing = e.args[0]
        raise ConfigError(f"prompt template references unknown placeholder {{{missing}}}") from e


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
        f"# Dry-run GitHub issue plan from {planner_key}\n\n"
        "- Inspect the issue with `gh issue view` and confirm acceptance criteria.\n"
        "- Identify the relevant code paths and make a focused fix.\n"
        "- Add or update tests where practical, run checks, then open a PR referencing the issue.\n"
    )


def _stub_build(build_dir: Path, *, title: str = "Dry-run MiniDesk", accent: str = "#7c9cff") -> None:
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


def _normalize_argv(argv: list[str]) -> list[str]:
    """Allow `duobench --issue ...` as shorthand for `duobench run --issue ...`."""
    if argv and argv[0] not in {"run", "report", "-h", "--help"}:
        return ["run", *argv]
    return argv


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


def _validate_model_specs(keys: list[str], flag: str) -> list[str]:
    keys = _dedupe_ordered(keys)
    if not keys:
        raise ConfigError(f"{flag} must include at least one Pi model spec")
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
    """Generate the full planner×implementer matrix for the requested Pi model specs."""
    planners = _validate_model_specs(planners, "--planners/--models")
    implementers = _validate_model_specs(implementers, "--implementers/--models")
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
        keys = _validate_model_specs(model_keys, "--models")
        return make_matrix_conditions(cfg, keys, keys), f"full matrix from --models ({len(keys)} models)"

    if planner_keys or implementer_keys:
        if not planner_keys or not implementer_keys:
            raise ConfigError("provide both --planners and --implementers, or use --models for a square matrix")
        planners = _validate_model_specs(planner_keys, "--planners")
        implementers = _validate_model_specs(implementer_keys, "--implementers")
        return make_matrix_conditions(cfg, planners, implementers), (
            f"rectangular matrix from --planners/--implementers ({len(planners)}×{len(implementers)})"
        )

    return cfg.conditions, "explicit conditions from conditions.yaml"


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)


def _git(args: list[str], cwd: Path, *, timeout: float = 60.0) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise ConfigError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def prepare_worktree(repo_dir: Path, worktree_dir: Path, *, branch: str) -> Path:
    """Create an isolated git worktree for one implementer trial."""
    _git(["rev-parse", "--show-toplevel"], repo_dir)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if worktree_dir.exists():
        shutil.rmtree(worktree_dir)
    _git(["worktree", "add", "-B", branch, str(worktree_dir), "HEAD"], repo_dir, timeout=120.0)
    return worktree_dir


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


def _pi_session_name(run_label: str, role: str, model_key: str, *, trial: int, condition_id: str | None = None) -> str:
    parts = ["duobench", "minidesk", run_label, role]
    if condition_id:
        parts.append(condition_id)
    parts += [model_key, f"trial-{trial}"]
    return " ".join(parts)


def run_shared_plan(
    cfg: Config,
    planner_key: str,
    trial: int,
    plan_dir: Path,
    prompts: dict[str, str],
    *,
    dry_run: bool,
    plan_timeout: float,
    save_pi_sessions: bool = False,
    run_label: str = "run",
    workspace_dir: Path | None = None,
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
        plan_duration = float(_stable_int(f"{planner_key}:plan:{trial}:duration", 18, 75))
        _write_fake_transcript(
            phase="planner",
            model=planner,
            prompt=_format_prompt_template(prompts["architect"], issue_url=_issue_url_from(prompts)),
            assistant_text=plan_text,
            usage=usage,
            cost=pc,
            path=plan_dir / "planner-transcript.json",
            duration_s=plan_duration,
        )
        plan_cost = pc.usd
        plan_source = pc.source
    else:
        plan_text, pc, plan_duration = run_plan_phase(
            planner,
            _format_prompt_template(prompts["architect"], issue_url=_issue_url_from(prompts)),
            plan_dir,
            workspace_dir=workspace_dir,
            timeout=plan_timeout,
            pin_temperature=True,
            thinking_level=planner.thinking_level,
            persist_pi_session=save_pi_sessions,
            session_name=_pi_session_name(run_label, "planner", planner_key, trial=trial),
            ui=ui,
        )
        plan_cost = pc.usd
        plan_source = pc.source
    (plan_dir / "shared-plan.json").write_text(json.dumps(
        {
            "planner": planner_key,
            "trial": trial,
            "cost_usd": round(plan_cost, 6),
            "cost_source": plan_source,
            "duration_s": round(plan_duration, 2),
            "plan_dir": str(plan_dir),
        },
        indent=2,
    ))
    return SharedPlan(
        planner=planner_key,
        trial=trial,
        plan_text=plan_text,
        cost_usd=plan_cost,
        cost_source=plan_source,
        source_dir=plan_dir,
        duration_s=plan_duration,
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
    save_pi_sessions: bool = False,
    run_label: str = "run",
    workspace_dir: Path | None = None,
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

    def run_plan_job(planner_key: str, trial: int, plan_dir: Path) -> SharedPlan:
        job_id = f"plan:{planner_key}:{trial}"
        if ui:
            ui.start_job(job_id, "Planning", f"{planner_key} trial {trial}")
        try:
            plan = run_shared_plan(
                cfg,
                planner_key,
                trial,
                plan_dir,
                prompts,
                dry_run=dry_run,
                plan_timeout=plan_timeout,
                save_pi_sessions=save_pi_sessions,
                run_label=run_label,
                workspace_dir=workspace_dir,
                ui=phase_ui,
            )
            if ui:
                ui.finish_job(job_id, "complete")
            return plan
        except Exception:
            if ui:
                ui.finish_job(job_id, "failed")
            raise

    if parallel_workers <= 1 or len(jobs) <= 1:
        for _, planner_key, trial, plan_dir in jobs:
            plans[(planner_key, trial)] = run_plan_job(planner_key, trial, plan_dir)
        return plans

    with ThreadPoolExecutor(max_workers=min(parallel_workers, len(jobs))) as pool:
        futures = {
            pool.submit(run_plan_job, planner_key, trial, plan_dir): (planner_key, trial)
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
    save_pi_sessions: bool = False,
    run_label: str = "run",
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
    build_dir = trial_dir / ("build" if dry_run else "worktree")
    shots_dir = trial_dir / "screenshots"
    pr_id = ""
    (ui.log if ui else print)(f"  [{cond.id} trial {trial}] plan={cond.planner} impl={cond.implementer}")

    # --- plan handoff ---
    copy_plan_artifacts(shared_plan, trial_dir)
    plan_text = shared_plan.plan_text
    plan_cost = shared_plan.cost_usd
    plan_source = shared_plan.cost_source
    plan_duration = shared_plan.duration_s

    # --- implement ---
    if dry_run:
        accent = f"#{_stable_int(cond.id, 0, 0xFFFFFF):06x}"
        _stub_build(build_dir, title=f"{cond.id} dry-run MiniDesk", accent=accent)
        usage = _fake_usage(cond.id, "implement", trial)
        ic = compute_cost(usage, implementer)
        impl_duration = float(_stable_int(f"{cond.id}:impl:{trial}:duration", 90, 900))
        _write_fake_transcript(
            phase="implementer",
            model=implementer,
            prompt=_format_prompt_template(prompts["implement"], issue_url=_issue_url_from(prompts), plan=plan_text),
            assistant_text="1",
            usage=usage,
            cost=ic,
            path=trial_dir / "implementer-transcript.json",
            duration_s=impl_duration,
            tool_calls=_stable_int(f"{cond.id}:impl:{trial}:tools", 4, 24),
        )
        impl_cost = ic.usd
        impl_source = ic.source
        impl_status = "complete"
        pr_id = "1"
    else:
        branch = _safe_path_part(f"duobench/{run_label}/{cond.id}/trial-{trial}")
        prepare_worktree(Path.cwd(), build_dir, branch=branch)
        impl = run_impl_phase(
            implementer,
            _format_prompt_template(prompts["implement"], issue_url=_issue_url_from(prompts), plan=plan_text),
            plan_text,
            build_dir,
            timeout=impl_timeout,
            pin_temperature=True,
            thinking_level=implementer.thinking_level,
            persist_pi_session=save_pi_sessions,
            session_name=_pi_session_name(run_label, "implementer", cond.implementer, trial=trial, condition_id=cond.id),
            ui=ui,
        )
        impl_cost = impl.cost.usd
        impl_source = impl.cost.source
        impl_status = impl.status
        impl_duration = impl.duration_s
        pr_id = impl.pr_id

    # --- verify / harness metadata ---
    if dry_run:
        if ui:
            ui.start_phase("Verifying", "Playwright")
        vres = verify_build(build_dir, shots_dir)
        if ui:
            ui.end_phase("complete" if vres.boots_ok else "issues found")
        verify_payload = vres.to_dict()
        smoke_summary = vres.summary_for_judge()
        screenshots = vres.screenshots
    else:
        if ui:
            ui.start_phase("Recording PR metadata", "git/gh")
        verify_payload = {
            "pr_id": pr_id,
            "worktree": str(build_dir),
            "notes": ["Implementation agent is responsible for tests, commit, push, and PR creation."],
        }
        smoke_summary = json.dumps(verify_payload, indent=2)
        screenshots = []
        if ui:
            ui.end_phase("complete" if pr_id else "missing PR id")
    (trial_dir / "verify.json").write_text(json.dumps(verify_payload, indent=2))

    record = TrialRecord(
        condition_id=cond.id,
        planner=cond.planner,
        implementer=cond.implementer,
        trial=trial,
        cost_usd=round(plan_cost + impl_cost, 6),
        dimensions={d: 0.0 for d in DIMENSIONS},   # filled after judging
        per_judge={},
        impl_status=impl_status,
        cost_source=_merge_cost_source(plan_source, impl_source),
        plan_duration_s=round(plan_duration, 2),
        impl_duration_s=round(impl_duration, 2),
    )
    # stash paths for the judging pass
    record_meta = {
        "build_dir": str(build_dir),
        "pr_id": pr_id,
        "smoke_summary": smoke_summary,
        "screenshots": screenshots,
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
    save_pi_sessions: bool = False,
    run_label: str = "run",
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
        job_id = f"build:{cond.id}:{trial}"
        if ui:
            ui.start_trial(cond.id, trial, "running")
            ui.start_job(job_id, "Build+verify", f"{cond.id} trial {trial} impl={cond.implementer}")
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
                save_pi_sessions=save_pi_sessions,
                run_label=run_label,
                ui=phase_ui,
            )
            if ui:
                ui.finish_trial(cond.id, trial, "built")
                ui.finish_job(job_id, "built")
            return rec.trial, rec, meta
        except Exception:
            if ui:
                ui.finish_trial(cond.id, trial, "failed")
                ui.finish_job(job_id, "failed")
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
        "task_completion": 0.45 * planner_q + 0.55 * implementer_q,
        "correctness": 0.25 * planner_q + 0.75 * implementer_q,
        "code_quality": 0.35 * planner_q + 0.65 * implementer_q,
        "verification": 0.20 * planner_q + 0.80 * implementer_q,
    }
    scores: list[JudgeScore] = []
    for judge_key in cfg.judges:
        jitter = _stable_int(f"{judge_key}:{rec.condition_id}:{rec.trial}:jitter", -6, 6) / 10
        # Tiny visible self-bias in the demo so the self-bias matrix is meaningful.
        bias = 0.25 if judge_key in {rec.planner, rec.implementer} else 0.0
        scores.append(
            JudgeScore(
                judge=judge_key,
                task_completion=_clamp_score(base["task_completion"] + jitter + bias),
                correctness=_clamp_score(base["correctness"] + jitter + bias),
                code_quality=_clamp_score(base["code_quality"] + jitter + bias),
                verification=_clamp_score(base["verification"] + jitter + bias),
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
                "task_completion": score.task_completion,
                "correctness": score.correctness,
                "code_quality": score.code_quality,
                "verification": score.verification,
                "notes": score.notes,
            }
        )
        rendered_prompt = (
            judge_prompt
            .replace("{issue_url}", DEFAULT_ISSUE_URL)
            .replace("{pr_id}", "1")
            .replace("{plan}", "[dry-run synthetic plan]")
            .replace("{smoke_results}", "[dry-run synthetic smoke results]")
        )
        _write_fake_transcript(
            phase="judge",
            model=model,
            prompt=rendered_prompt,
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
    rp.add_argument("--issue", type=str, default="", help="GitHub issue URL or issue reference to fix; required for real runs")
    rp.add_argument("--conditions", type=str, default="", help="comma-separated condition ids from conditions.yaml")
    rp.add_argument("--models", type=str, default="",
                    help="comma-separated Pi model specs; generate the full planner×implementer matrix")
    rp.add_argument("--planners", type=str, default="",
                    help="comma-separated planner Pi model specs for a rectangular matrix")
    rp.add_argument("--implementers", type=str, default="",
                    help="comma-separated implementer Pi model specs for a rectangular matrix")
    rp.add_argument("--judges", type=str, default="",
                    help="comma-separated judge Pi model specs; defaults to --models or models.yaml judges")
    rp.add_argument("--dry-run", action="store_true", help="stub all model calls with synthetic plans, builds, costs, and judge scores")
    rp.add_argument("--out", type=str, default="runs")
    rp.add_argument("--models-config", type=str, default="config/models.yaml")
    rp.add_argument("--conditions-config", type=str, default="config/conditions.yaml")
    rp.add_argument("--costs-config", type=str, default="costs.yaml")
    rp.add_argument("--plan-timeout", type=float, default=600.0)
    rp.add_argument("--impl-timeout", type=float, default=1800.0)
    rp.add_argument("--judge-timeout", type=float, default=300.0)
    rp.add_argument("--parallel", type=str, default="auto",
                    help="planner/build concurrency: 'auto' (default), 'all', or a positive integer; use 1 for serial")
    rp.add_argument("--pi-sessions", action=argparse.BooleanOptionalAction, default=True,
                    help="save real Pi RPC sessions in Pi's default session store with descriptive names")
    rp.add_argument("--live", action=argparse.BooleanOptionalAction, default=None,
                    help="enable/disable the Rich live dashboard (default: auto when attached to a TTY)")
    rp.add_argument("--skip-model-check", action="store_true", help="skip fail-fast Pi model/auth validation")
    rp.add_argument("--debug", action="store_true", help="show full Python tracebacks on errors")
    rep = sub.add_parser("report", help="generate/re-generate report.html for an existing run")
    rep.add_argument("run_dir", type=str)
    rep.add_argument("--debug", action="store_true", help="show full Python tracebacks on errors")
    args = ap.parse_args(_normalize_argv(sys.argv[1:]))

    if args.cmd == "report":
        report_path = generate_report(Path(args.run_dir))
        print(f"report written: {report_path}")
        return

    cfg = load_config(args.models_config, args.conditions_config, args.costs_config)
    model_keys = _parse_csv(args.models)
    planner_keys = _parse_csv(args.planners)
    implementer_keys = _parse_csv(args.implementers)
    judge_keys = _parse_csv(args.judges) or model_keys or cfg.judges
    cfg = replace(cfg, judges=_validate_model_specs(judge_keys, "--judges"))
    conditions, selection_mode = select_run_conditions(
        cfg,
        condition_ids=_parse_csv(args.conditions),
        model_keys=model_keys,
        planner_keys=planner_keys,
        implementer_keys=implementer_keys,
    )
    parallel_workers = resolve_parallel(args.parallel)

    issue_url = _load_issue_url(args.issue, dry_run=args.dry_run)
    _check_issue_prereqs(dry_run=args.dry_run)
    prompts = {
        "issue_url": issue_url,
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
    prompt_source = "--issue" if args.issue else "dry-run default issue"
    ui.log(f"GitHub issue: {prompt_source} ({len(issue_url)} chars)")
    parallel_label = "all jobs in each phase" if args.parallel == "all" else f"{parallel_workers} max"
    ui.log(f"parallel workers: {args.parallel} ({parallel_label})")
    plan_jobs = len(_unique_planners(conditions)) * args.trials
    impl_jobs = len(conditions) * args.trials
    judge_jobs = impl_jobs * len(cfg.judges)
    ui.log(f"phase plan: {plan_jobs} shared planner run(s) → PR: {impl_jobs} implementation run(s) → judge: {judge_jobs} judge run(s)")
    ui.log(f"Pi sessions: {'saved with descriptive names' if args.pi_sessions and not args.dry_run else 'not saved'}")
    if not args.dry_run and not args.skip_model_check:
        # Resolve registry aliases (e.g. `kimi-k2.6`) to full Pi specs before
        # validating — Pi cannot resolve bare registry keys itself.
        def _pi_spec(key: str) -> str:
            m = cfg.model(key)
            spec = f"{m.provider}/{m.model_id}" if m.provider else m.model_id
            return f"{spec}:{m.thinking_level}" if m.thinking_level else spec
        validate_pi_models([_pi_spec(k) for k in (*(c.planner for c in conditions), *(c.implementer for c in conditions), *cfg.judges)], ui=ui)
    ui.log("conditions:")
    unknown_models: set[str] = set()
    for c in conditions:
        planner_model = cfg.model(c.planner)
        implementer_model = cfg.model(c.implementer)
        planner_thinking = planner_model.thinking_level or "default/off"
        implementer_thinking = implementer_model.thinking_level or "default/off"
        planner_note = " *" if _is_unknown_model(cfg, c.planner) else ""
        implementer_note = " *" if _is_unknown_model(cfg, c.implementer) else ""
        ui.log(
            f"  - {c.id}: planner={c.planner}{planner_note} (thinking={planner_thinking}) "
            f"implementer={c.implementer}{implementer_note} (thinking={implementer_thinking})"
        )
        if planner_note:
            unknown_models.add(c.planner)
        if implementer_note:
            unknown_models.add(c.implementer)
    if unknown_models:
        ui.log(
            "\n* model key(s) not in config/models.yaml; using spec directly with Pi. "
            "Add them to models.yaml to set provider defaults, thinking, and pricing."
        )
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
        save_pi_sessions=args.pi_sessions and not args.dry_run,
        run_label=run_dir.name,
        workspace_dir=Path.cwd(),
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
        save_pi_sessions=args.pi_sessions and not args.dry_run,
        run_label=run_dir.name,
        ui=ui,
    )

    # --- phase 2: judge panel over every build ---
    ui.log("judging...")
    for rec, meta in zip(records, metas):
        judge_job_id = f"judge:{rec.condition_id}:{rec.trial}"
        ui.start_trial(rec.condition_id, rec.trial, "judging")
        ui.start_job(judge_job_id, "Judging", f"{rec.condition_id} trial {rec.trial} ({len(cfg.judges)} judges)")
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
            ui.finish_job(judge_job_id, "done")
            continue
        trial_dir = Path(meta["build_dir"]).parent
        scores = judge_panel(
            cfg, prompts["judge"], Path(meta["build_dir"]),
            meta["smoke_summary"], meta["screenshots"],
            issue_url=_issue_url_from(prompts),
            pr_id=meta.get("pr_id", ""),
            plan=(trial_dir / "plan.md").read_text() if (trial_dir / "plan.md").exists() else "",
            timeout=args.judge_timeout,
            transcripts_dir=trial_dir / "judge-transcripts",
            persist_pi_session=args.pi_sessions,
            session_name_prefix=_pi_session_name(run_dir.name, "judge", "panel", trial=rec.trial, condition_id=rec.condition_id),
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
        ui.finish_job(judge_job_id, "done")

    # --- phase 3: aggregate + charts ---
    results = aggregate(records, cfg.judges)
    (run_dir / "results.json").write_text(json.dumps(results, indent=2))

    results_dir = run_dir / "results"
    written = generate_charts(results, results_dir)

    if ui:
        ui.start_phase("Generating report", "HTML")
    report_path = generate_report(run_dir)
    if ui:
        ui.end_phase("complete")
        ui.stop()

    abs_run_dir = run_dir.resolve()
    abs_results_dir = results_dir.resolve()
    abs_results_json = (run_dir / "results.json").resolve()
    abs_report_path = report_path.resolve()
    print(f"\ndone. results.json + {len(written)} chart/csv files written for this run")
    print(f"run dir: {abs_run_dir}")
    print(f"results dir: {abs_results_dir}")
    print(f"results json: {abs_results_json}")
    print(f"report: {abs_report_path}")
    print(f"open report: {abs_report_path.as_uri()}")
    if args.pi_sessions and not args.dry_run:
        print("Pi sessions: saved in Pi's default session store; paths are recorded in transcripts/report.html")
    # leaderboard preview
    ranked = sorted(results["conditions"].items(), key=lambda kv: kv[1]["quality"], reverse=True)
    print("\nleaderboard (quality | cost$ | cost-source | efficiency | time):")
    unknown_pricing: list[str] = []
    for cid, c in ranked:
        source = c.get("cost_source", "unknown")
        if source == "unknown":
            unknown_pricing.append(cid)
        duration = c.get("duration_s", 0.0)
        time_label = f"{duration / 60:.1f}m" if duration else "n/a"
        print(f"  {cid:14} {c['quality']:5.2f} | {c['cost_usd']:.4f} | {source:12} | {c['cost_efficiency']:.2f} | {time_label}")
    if unknown_pricing:
        print(
            "\nwarning: cost$ is 0.0000 with source 'unknown' for: "
            + ", ".join(unknown_pricing)
            + ". Add the model keys to config/models.yaml (pricing block) or create "
              "a costs.yaml with rates for those keys. cost_efficiency is meaningless "
              "until pricing is set."
        )


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
