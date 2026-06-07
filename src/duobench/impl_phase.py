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
import re
from dataclasses import dataclass, field
from pathlib import Path

from duobench.config import Model
from duobench.cost import PhaseCost, compute_cost
from duobench.pi_rpc import PiRpcError, PiSession, Usage
from duobench.transcript import new_transcript

# Heuristic completion markers the implementer is asked to emit when done.
_DONE_MARKERS = (
    "pr created", "pull request created", "opened pr", "created pr"
)
_CONTINUE_MSG = (
    "Continue working on the GitHub issue. If the PR has not been created yet, inspect the "
    "issue with gh, finish the code changes, run appropriate checks, commit, push, and open "
    "the PR. When the PR exists, reply with only the PR id."
)
_MAX_FOLLOW_UPS = 12  # safety bound on the nudge loop, not a per-agent turn cap


@dataclass
class ImplResult:
    cost: PhaseCost
    turns: int
    status: str                      # "complete" | "timeout" | "stopped"
    final_text: str = ""
    pr_id: str = ""
    notes: list[str] = field(default_factory=list)


def extract_pr_id(text: str) -> str:
    stripped = text.strip()
    url = re.search(r"https://github\.com/[^\s/]+/[^\s/]+/pull/(\d+)", stripped)
    if url:
        return url.group(1)
    number = re.search(r"(?:^|\s)#?(\d{1,10})(?:\s|$)", stripped)
    if number:
        return number.group(1)
    return ""


def _looks_done(text: str) -> bool:
    low = text.lower()
    return bool(extract_pr_id(text)) or any(m in low for m in _DONE_MARKERS)


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
    pr_id = ""
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
        initial_model=implementer.model_id if not implementer.provider else None,
    ) as s:
        if implementer.provider:
            s.set_model(implementer.provider, implementer.model_id)
        if thinking_level is not None:
            s.set_thinking(thinking_level)
        elif pin_temperature and implementer.provider:
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
            pr_id = extract_pr_id(result.text)
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
                    pr_id = extract_pr_id(result.text) or pr_id
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

    if status == "complete" and not pr_id:
        notes.append("completion detected but no PR id could be parsed from the final response")

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
        pr_id=pr_id,
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
