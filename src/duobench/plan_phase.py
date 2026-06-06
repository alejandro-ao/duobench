"""Plan phase: a planner model produces an architecture plan from the architect prompt.

Session-isolated from implementation. The plan text is the only handoff artifact (mirrors
the production flow: plan → GitHub issue → fresh implementer). No tools needed — the
planner just writes a plan.
"""

from __future__ import annotations

import time
from pathlib import Path

from duobench.config import Model
from duobench.cost import PhaseCost, compute_cost
from duobench.pi_rpc import PiSession
from duobench.transcript import new_transcript


def run_plan_phase(
    planner: Model,
    architect_prompt: str,
    out_dir: Path,
    *,
    timeout: float = 600.0,
    pin_temperature: bool = False,
    ui=None,
) -> tuple[str, PhaseCost]:
    """Run the planner; write plan.md to out_dir. Returns (plan_text, cost)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = new_transcript("planner", planner)
    if ui:
        ui.start_phase("Planning", planner.key)
    with PiSession(
        cwd=out_dir,
        enable_tools=False,
        event_callback=getattr(ui, "on_rpc_event", None),
        raw_events_path=out_dir / "planner-events.jsonl",
    ) as s:
        s.set_model(planner.provider, planner.model_id)
        if pin_temperature:
            s.set_thinking("off")
        started = time.time()
        result = s.prompt(architect_prompt, timeout=timeout)
        ended = time.time()

    cost = compute_cost(result.usage, planner)
    transcript.add_turn(
        kind="prompt",
        prompt=architect_prompt,
        result=result,
        cost=cost,
        started_at=started,
        ended_at=ended,
    )
    transcript.status = "complete"
    transcript.write(out_dir / "planner-transcript.json")
    if ui:
        ui.add_turn_result(result.usage, cost.usd, cost.reported_usd)
        ui.end_phase("complete")

    plan_path = out_dir / "plan.md"
    plan_path.write_text(result.text)
    return result.text, cost
