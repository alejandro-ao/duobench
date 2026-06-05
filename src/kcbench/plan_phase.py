"""Plan phase: a planner model produces an architecture plan from the architect prompt.

Session-isolated from implementation. The plan text is the only handoff artifact (mirrors
the production flow: plan → GitHub issue → fresh implementer). No tools needed — the
planner just writes a plan.
"""

from __future__ import annotations

from pathlib import Path

from kcbench.config import Model
from kcbench.cost import PhaseCost, compute_cost
from kcbench.pi_rpc import PiSession


def run_plan_phase(
    planner: Model,
    architect_prompt: str,
    out_dir: Path,
    *,
    timeout: float = 600.0,
    pin_temperature: bool = False,
) -> tuple[str, PhaseCost]:
    """Run the planner; write plan.md to out_dir. Returns (plan_text, cost)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with PiSession(cwd=out_dir, enable_tools=False) as s:
        s.set_model(planner.provider, planner.model_id)
        if pin_temperature:
            s.set_thinking("off")
        result = s.prompt(architect_prompt, timeout=timeout)

    plan_path = out_dir / "plan.md"
    plan_path.write_text(result.text)
    return result.text, compute_cost(result.usage, planner)
