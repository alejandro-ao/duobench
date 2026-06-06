"""Orchestrator CLI — a deterministic script (NOT an agent).

Sequences: plan → implement → verify per condition×trial, then judge panel over every
build, aggregates, and draws charts. The only agentic work is inside the Pi sessions.

Usage:
  uv run duobench run [--trials N] [--conditions a,b,c] [--dry-run] [--out DIR]
"""

from __future__ import annotations

import argparse
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
from duobench.config import Condition, Config, ConfigError, load_config
from duobench.judge import DIMENSIONS, average_dimensions, judge_panel
from duobench.plan_phase import run_plan_phase
from duobench.impl_phase import run_impl_phase
from duobench.verify import verify_build
from duobench.pi_rpc import PiRpcError
from duobench.report import generate_report
from duobench.ui import make_ui
from duobench.fingerprint import make_benchmark_fingerprint

AUTO_PARALLEL_WORKERS = 2


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


def _stub_plan() -> str:
    return "# Stub plan\nA minimal WebOS: WindowManager, AppRegistry, FileSystem, Taskbar.\n"


def _stub_build(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "index.html").write_text(
        "<!doctype html><html><body>"
        "<div id='desktop'><div class='desktop-icon' data-app='a'>A</div>"
        "<div class='desktop-icon' data-app='b'>B</div>"
        "<div class='desktop-icon' data-app='c'>C</div></div>"
        "<div class='taskbar'></div>"
        "<script>document.querySelectorAll('.desktop-icon').forEach(i=>"
        "i.onclick=()=>{const w=document.createElement('div');w.className='window';"
        "document.body.appendChild(w);});</script></body></html>"
    )


def select_conditions(cfg: Config, only: list[str] | None) -> list[Condition]:
    if not only:
        return cfg.conditions
    by_id = {c.id: c for c in cfg.conditions}
    missing = [o for o in only if o not in by_id]
    if missing:
        sys.exit(f"unknown condition id(s): {', '.join(missing)}")
    return [by_id[o] for o in only]


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
    try:
        workers = int(value)
    except ValueError as e:
        raise ConfigError("--parallel must be 'auto' or a positive integer") from e
    if workers < 1:
        raise ConfigError("--parallel must be 'auto' or a positive integer")
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
        plan_text = _stub_plan()
        (plan_dir / "plan.md").write_text(plan_text)
        plan_cost = 0.0
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
        _stub_build(build_dir)
        impl_cost = 0.0
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


def _main() -> None:
    ap = argparse.ArgumentParser(
        prog="duobench",
        description="Run planner×implementer model benchmarks over Pi RPC.",
        epilog=(
            "Examples:\n"
            "  duobench run --dry-run\n"
            "  duobench run --conditions kimi-solo --trials 1\n"
            "  duobench run --conditions kimi-solo,gpt-x-kimi --trials 3"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run", help="run the benchmark")
    rp.add_argument("--trials", type=int, default=1)
    rp.add_argument("--conditions", type=str, default="", help="comma-separated condition ids")
    rp.add_argument("--dry-run", action="store_true", help="stub all model calls")
    rp.add_argument("--out", type=str, default="runs")
    rp.add_argument("--models-config", type=str, default="config/models.yaml")
    rp.add_argument("--conditions-config", type=str, default="config/conditions.yaml")
    rp.add_argument("--plan-timeout", type=float, default=600.0)
    rp.add_argument("--impl-timeout", type=float, default=1800.0)
    rp.add_argument("--judge-timeout", type=float, default=300.0)
    rp.add_argument("--parallel", type=str, default="auto",
                    help="planner/build concurrency: 'auto' (default) or a positive integer; use 1 for serial")
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
    only = [c.strip() for c in args.conditions.split(",") if c.strip()] or None
    conditions = select_conditions(cfg, only)
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
    ui.log(f"parallel workers: {args.parallel} ({parallel_workers} max)")
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
            # canned scores so the wiring runs without real judges
            for jk in cfg.judges:
                rec.per_judge[jk] = {d: 6 for d in DIMENSIONS}
            rec.dimensions = {d: 6.0 for d in DIMENSIONS}
            trial_dir = Path(meta["build_dir"]).parent
            existing_trial = json.loads((trial_dir / "trial.json").read_text())
            (trial_dir / "trial.json").write_text(json.dumps(
                {
                    "benchmark": existing_trial.get("benchmark"),
                    "artifacts": existing_trial.get("artifacts"),
                    "record": rec.__dict__,
                    "meta": meta,
                    "judge_scores": [],
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
