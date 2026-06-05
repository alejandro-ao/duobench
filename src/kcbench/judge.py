"""Judge phase: a configurable panel scores every build on 3 dimensions.

Each judge model scores architecture / correctness / visual_ux (1-10) as strict JSON.
Cost efficiency is NOT judged — it's computed objectively in results aggregation.

Inputs per build: concatenated source code + smoke-test summary + screenshots (passed as
images when the Pi RPC prompt supports them; otherwise the judge scores visual_ux
conservatively from CSS, as instructed in the prompt).

Scores are averaged across the panel. Raw per-judge scores are kept so a judge×build
self-bias matrix can be plotted.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from kcbench.config import Config, Model
from kcbench.pi_rpc import PiRpcError, PiSession

DIMENSIONS = ("architecture", "correctness", "visual_ux")
_MAX_SOURCE_CHARS = 120_000           # cap concatenated source to stay within context
_SOURCE_EXTS = {".html", ".css", ".js", ".mjs", ".json", ".md"}
_SKIP_DIRS = {"node_modules", ".git", "screenshots"}


@dataclass
class JudgeScore:
    judge: str                        # model key
    architecture: int
    correctness: int
    visual_ux: int
    notes: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "judge": self.judge,
            "architecture": self.architecture,
            "correctness": self.correctness,
            "visual_ux": self.visual_ux,
            "notes": self.notes,
            "error": self.error,
        }


def collect_source(build_dir: Path) -> str:
    parts: list[str] = []
    total = 0
    for path in sorted(build_dir.rglob("*")):
        if any(d in path.parts for d in _SKIP_DIRS):
            continue
        if not path.is_file() or path.suffix.lower() not in _SOURCE_EXTS:
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        rel = path.relative_to(build_dir)
        chunk = f"\n===== FILE: {rel} =====\n{text}\n"
        if total + len(chunk) > _MAX_SOURCE_CHARS:
            parts.append(f"\n[...source truncated at {_MAX_SOURCE_CHARS} chars...]\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts) if parts else "[no source files found]"


def _encode_images(screenshots: list[str], limit: int = 5) -> list[dict]:
    imgs: list[dict] = []
    for sp in screenshots[:limit]:
        p = Path(sp)
        if not p.is_file():
            continue
        try:
            data = base64.b64encode(p.read_bytes()).decode()
            imgs.append({"type": "image", "data": data, "mimeType": "image/png"})
        except Exception:
            continue
    return imgs


def _parse_scores(text: str, judge_key: str) -> JudgeScore:
    # Extract the first JSON object from the response.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return JudgeScore(judge_key, 0, 0, 0, error=f"no JSON in response: {text[:120]}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return JudgeScore(judge_key, 0, 0, 0, error=f"bad JSON: {e}")

    def clamp(v) -> int:
        try:
            return max(1, min(10, int(round(float(v)))))
        except Exception:
            return 0

    return JudgeScore(
        judge=judge_key,
        architecture=clamp(obj.get("architecture")),
        correctness=clamp(obj.get("correctness")),
        visual_ux=clamp(obj.get("visual_ux")),
        notes=str(obj.get("notes", ""))[:500],
    )


def judge_build(
    judge_model: Model,
    judge_key: str,
    judge_prompt_template: str,
    source: str,
    smoke_summary: str,
    screenshots: list[str],
    *,
    timeout: float = 300.0,
) -> JudgeScore:
    prompt = (
        judge_prompt_template
        .replace("{smoke_results}", smoke_summary)
        .replace("{source}", source)
    )
    images = _encode_images(screenshots)
    with PiSession(cwd=Path.cwd(), enable_tools=False) as s:
        s.set_model(judge_model.provider, judge_model.model_id)
        s.set_thinking("off")  # determinism best-effort
        try:
            # Try with images first; fall back to text-only if the build/model rejects it.
            try:
                s._send({"type": "prompt", "message": prompt, "images": images} if images
                         else {"type": "prompt", "message": prompt})
                s._await_response("prompt", timeout=15.0)
                result = s._collect_until_agent_end(timeout=timeout)
            except PiRpcError:
                result = s.prompt(prompt, timeout=timeout)
        except PiRpcError as e:
            return JudgeScore(judge_key, 0, 0, 0, error=str(e))
    return _parse_scores(result.text, judge_key)


def judge_panel(
    cfg: Config,
    judge_prompt_template: str,
    build_dir: Path,
    smoke_summary: str,
    screenshots: list[str],
    *,
    timeout: float = 300.0,
) -> list[JudgeScore]:
    """Run every configured judge over one build."""
    source = collect_source(build_dir)
    scores: list[JudgeScore] = []
    for judge_key in cfg.judges:
        model = cfg.model(judge_key)
        scores.append(
            judge_build(
                model, judge_key, judge_prompt_template,
                source, smoke_summary, screenshots, timeout=timeout,
            )
        )
    return scores


def average_dimensions(scores: list[JudgeScore]) -> dict[str, float]:
    """Average each dimension across judges that returned valid (non-error) scores."""
    valid = [s for s in scores if s.error is None]
    if not valid:
        return {d: 0.0 for d in DIMENSIONS}
    return {
        d: round(sum(getattr(s, d) for s in valid) / len(valid), 3)
        for d in DIMENSIONS
    }
