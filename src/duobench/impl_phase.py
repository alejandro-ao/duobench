"""Implementation phase: a fresh implementer session builds the WebOS from the plan.

The implementer never sees the planner's reasoning — only the plan text injected into the
prompt. Tools are enabled and the session CWD is the build dir, so the agent writes files
there directly.

No hard turn cap (per design): realistic looping behavior naturally inflates cost. The only
guardrail is a wall-clock timeout; a build that hits it is recorded as a `timeout`
failure-mode data point rather than crashing the suite. A bounded multi-turn loop nudges
the agent to keep building until it signals completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from duobench.config import Model
from duobench.cost import PhaseCost, compute_cost
from duobench.pi_rpc import PiRpcError, PiSession, Usage
from duobench.transcript import new_transcript

# Heuristic completion markers the implementer is asked to emit when done.
_DONE_MARKERS = ("build is complete", "build complete", "fully functional", "done building",
                 "implementation is complete", "completed the build")
_CONTINUE_MSG = (
    "Continue building. If anything from the plan is missing or incomplete (apps, games, "
    "window manager, persistence, theming), implement it now. When the entire WebOS is "
    "complete and functional with index.html at the root, reply with exactly: BUILD COMPLETE"
)
_MAX_FOLLOW_UPS = 12  # safety bound on the nudge loop, not a per-agent turn cap


@dataclass
class ImplResult:
    cost: PhaseCost
    turns: int
    status: str                      # "complete" | "timeout" | "stopped"
    final_text: str = ""
    notes: list[str] = field(default_factory=list)


def _looks_done(text: str) -> bool:
    low = text.lower()
    return "build complete" in low or any(m in low for m in _DONE_MARKERS)


def run_impl_phase(
    implementer: Model,
    implement_prompt_template: str,
    plan_text: str,
    build_dir: Path,
    *,
    timeout: float = 1800.0,
    pin_temperature: bool = False,
    ui=None,
) -> ImplResult:
    """Build the WebOS into build_dir. Accumulates usage across the multi-turn loop."""
    build_dir.mkdir(parents=True, exist_ok=True)
    prompt = implement_prompt_template.replace("{plan}", plan_text)

    total = Usage()
    turns = 0
    status = "stopped"
    final_text = ""
    notes: list[str] = []

    transcript = new_transcript("implementer", implementer)
    if ui:
        ui.start_phase("Implementing", implementer.key)

    deadline = time.monotonic() + timeout

    def remaining_timeout() -> float:
        return max(1.0, deadline - time.monotonic())

    with PiSession(
        cwd=build_dir,
        enable_tools=True,
        event_callback=getattr(ui, "on_rpc_event", None),
        raw_events_path=build_dir.parent / "implementer-events.jsonl",
    ) as s:
        s.set_model(implementer.provider, implementer.model_id)
        if pin_temperature:
            s.set_thinking("off")
        try:
            started = time.time()
            result = s.prompt(prompt, timeout=remaining_timeout())
            ended = time.time()
            turns += 1
            total.add(result.usage)
            turn_cost = compute_cost(result.usage, implementer)
            transcript.add_turn(kind="prompt", prompt=prompt, result=result, cost=turn_cost, started_at=started, ended_at=ended)
            if ui:
                ui.add_turn_result(result.usage, turn_cost.usd, turn_cost.reported_usd)
            final_text = result.text
            if _looks_done(result.text):
                status = "complete"
            else:
                for _ in range(_MAX_FOLLOW_UPS):
                    if time.monotonic() >= deadline:
                        status = "timeout"
                        notes.append(f"implementation exceeded total wall-clock timeout of {timeout}s")
                        break
                    started = time.time()
                    result = s.follow_up(_CONTINUE_MSG, timeout=remaining_timeout())
                    ended = time.time()
                    turns += 1
                    total.add(result.usage)
                    turn_cost = compute_cost(result.usage, implementer)
                    transcript.add_turn(kind="follow_up", prompt=_CONTINUE_MSG, result=result, cost=turn_cost, started_at=started, ended_at=ended)
                    if ui:
                        ui.add_turn_result(result.usage, turn_cost.usd, turn_cost.reported_usd)
                    final_text = result.text
                    if _looks_done(result.text):
                        status = "complete"
                        break
                else:
                    status = "stopped"
                    notes.append(f"hit max follow-ups ({_MAX_FOLLOW_UPS}) without completion signal")
        except PiRpcError as e:
            status = "timeout"
            notes.append(f"pi_rpc error/timeout: {e}")

    # If nothing was written, flag it (correctness will score it via verify anyway).
    if not (build_dir / "index.html").exists():
        notes.append("no index.html at build root after implementation")

    transcript.status = status
    transcript.notes = notes
    transcript.write(build_dir.parent / "implementer-transcript.json")
    if ui:
        ui.end_phase(status)

    return ImplResult(
        cost=compute_cost(total, implementer),
        turns=turns,
        status=status,
        final_text=final_text,
        notes=notes,
    )
