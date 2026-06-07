"""Implementation phase: a fresh implementer session completes the task from the plan.

The implementer never sees the planner's reasoning — only the user task and plan text.
Tools are enabled and the session CWD is the build dir, so the agent writes files there
directly.

No hard turn cap (per design): realistic looping behavior naturally inflates cost. The only
guardrail is a wall-clock timeout; a build that hits it is recorded as a `timeout`
failure-mode data point rather than crashing the suite. A bounded multi-turn loop nudges
the agent to keep working until it signals completion.
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
_DONE_MARKERS = (
    "task complete", "implementation complete", "implementation is complete",
    "build complete", "build is complete"
)
_CONTINUE_MSG = (
    "Continue working on the task. If anything from the user request or plan is missing or "
    "incomplete, implement it now and run appropriate checks if possible. When everything is "
    "complete, reply with exactly: TASK COMPLETE"
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
    thinking_level: str | None = None,
    persist_pi_session: bool = False,
    session_name: str | None = None,
    ui=None,
) -> ImplResult:
    """Complete the task in build_dir. Accumulates usage across the multi-turn loop."""
    build_dir.mkdir(parents=True, exist_ok=True)
    prompt = implement_prompt_template.replace("{plan}", plan_text)

    total = Usage()
    turns = 0
    status = "stopped"
    final_text = ""
    notes: list[str] = []
    session_state: dict = {}

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
        persist_session=persist_pi_session,
        session_name=session_name,
    ) as s:
        s.set_model(implementer.provider, implementer.model_id)
        if thinking_level is not None:
            s.set_thinking(thinking_level)
        elif pin_temperature:
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
        try:
            session_state = s.get_state()
        except Exception:
            session_state = {}

    # If nothing was written, flag it (correctness will score it via verify anyway).
    if not any(build_dir.iterdir()):
        notes.append("no files written in build directory after implementation")

    transcript.status = status
    transcript.notes = notes
    transcript.pi_session = _session_metadata(session_state, session_name)
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


def _session_metadata(state: dict, requested_name: str | None) -> dict | None:
    if not state and not requested_name:
        return None
    return {
        "requested_name": requested_name,
        "name": state.get("sessionName") or requested_name,
        "session_file": state.get("sessionFile"),
        "session_id": state.get("sessionId"),
    }
