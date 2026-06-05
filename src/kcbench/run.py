"""Orchestrator CLI — a deterministic script (NOT an agent).

Sequences: plan → implement → verify per condition×trial, then judge panel over every
build, aggregates, and draws charts. The only agentic work is inside the Pi sessions.

Usage:
  uv run kcbench run [--trials N] [--conditions a,b,c] [--dry-run] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from kcbench.aggregate import TrialRecord, aggregate
from kcbench.charts import generate_charts
from kcbench.config import Condition, Config, ConfigError, load_config
from kcbench.judge import DIMENSIONS, average_dimensions, judge_panel
from kcbench.plan_phase import run_plan_phase
from kcbench.impl_phase import run_impl_phase
from kcbench.verify import verify_build
from kcbench.pi_rpc import PiRpcError
from kcbench.report import generate_report

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text()


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


def run_condition_trial(
    cfg: Config,
    cond: Condition,
    trial: int,
    trial_dir: Path,
    prompts: dict[str, str],
    *,
    dry_run: bool,
    plan_timeout: float,
    impl_timeout: float,
) -> tuple[TrialRecord, dict]:
    planner = cfg.model(cond.planner)
    implementer = cfg.model(cond.implementer)
    build_dir = trial_dir / "build"
    shots_dir = trial_dir / "screenshots"
    print(f"  [{cond.id} trial {trial}] plan={cond.planner} impl={cond.implementer}")

    # --- plan ---
    if dry_run:
        plan_text = _stub_plan()
        (trial_dir / "plan.md").write_text(plan_text)
        plan_cost = 0.0
    else:
        plan_text, pc = run_plan_phase(planner, prompts["architect"], trial_dir,
                                       timeout=plan_timeout, pin_temperature=True)
        plan_cost = pc.usd

    # --- implement ---
    if dry_run:
        _stub_build(build_dir)
        impl_cost = 0.0
        impl_status = "complete"
    else:
        impl = run_impl_phase(implementer, prompts["implement"], plan_text, build_dir,
                              timeout=impl_timeout, pin_temperature=True)
        impl_cost = impl.cost.usd
        impl_status = impl.status

    # --- verify ---
    vres = verify_build(build_dir, shots_dir)
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
    (trial_dir / "trial.json").write_text(json.dumps(
        {"record": record.__dict__, "meta": record_meta}, indent=2, default=str))
    return record, record_meta


def _main() -> None:
    ap = argparse.ArgumentParser(
        prog="kcbench",
        description="Run planner×implementer model benchmarks over Pi RPC.",
        epilog=(
            "Examples:\n"
            "  kcbench run --dry-run\n"
            "  kcbench run --conditions kimi-solo --trials 1\n"
            "  kcbench run --conditions kimi-solo,gpt-x-kimi --trials 3"
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

    prompts = {
        "architect": _load_prompt("architect.md"),
        "implement": _load_prompt("implement.md"),
        "judge": _load_prompt("judge.md"),
    }

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = Path(args.out) / ts
    cond_root = run_dir / "conditions"
    cond_root.mkdir(parents=True, exist_ok=True)
    print("\n=== kimi-claude-bench ===")
    print(f"mode: {'DRY RUN (no model/API calls)' if args.dry_run else 'REAL RUN'}")
    print(f"run dir: {run_dir}")
    print(f"trials per condition: {args.trials}")
    print("conditions:")
    for c in conditions:
        print(f"  - {c.id}: planner={c.planner} implementer={c.implementer}")
    if not args.dry_run:
        print("\nTip: if this is your first run, `kcbench run --dry-run` validates the pipeline without API spend.")
    print()

    # --- phase 1: plan + implement + verify per condition×trial ---
    records: list[TrialRecord] = []
    metas: list[dict] = []
    for cond in conditions:
        for trial in range(args.trials):
            trial_dir = cond_root / cond.id / f"trial-{trial}"
            trial_dir.mkdir(parents=True, exist_ok=True)
            rec, meta = run_condition_trial(
                cfg, cond, trial, trial_dir, prompts,
                dry_run=args.dry_run,
                plan_timeout=args.plan_timeout, impl_timeout=args.impl_timeout,
            )
            records.append(rec)
            metas.append(meta)

    # --- phase 2: judge panel over every build ---
    print("judging...")
    for rec, meta in zip(records, metas):
        if args.dry_run:
            # canned scores so the wiring runs without real judges
            for jk in cfg.judges:
                rec.per_judge[jk] = {d: 6 for d in DIMENSIONS}
            rec.dimensions = {d: 6.0 for d in DIMENSIONS}
            trial_dir = Path(meta["build_dir"]).parent
            (trial_dir / "trial.json").write_text(json.dumps(
                {"record": rec.__dict__, "meta": meta, "judge_scores": []},
                indent=2, default=str,
            ))
            continue
        trial_dir = Path(meta["build_dir"]).parent
        scores = judge_panel(
            cfg, prompts["judge"], Path(meta["build_dir"]),
            meta["smoke_summary"], meta["screenshots"], timeout=args.judge_timeout,
            transcripts_dir=trial_dir / "judge-transcripts",
        )
        rec.per_judge = {
            s.judge: {d: getattr(s, d) for d in DIMENSIONS} for s in scores if s.error is None
        }
        rec.dimensions = average_dimensions(scores)
        trial_dir = Path(meta["build_dir"]).parent
        (trial_dir / "trial.json").write_text(json.dumps(
            {"record": rec.__dict__, "meta": meta, "judge_scores": [s.to_dict() for s in scores]},
            indent=2, default=str,
        ))

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

    report_path = generate_report(run_dir)

    print(f"\ndone. results.json + {len(written)} chart/csv files in {results_dir}")
    print(f"report: {report_path}")
    print(f"copied to {top_results}/ for the video")
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
            "  - `uv run kcbench run --dry-run` to validate local wiring\n"
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
