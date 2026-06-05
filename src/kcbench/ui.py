"""Rich-powered live CLI dashboard for benchmark runs."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kcbench.pi_rpc import Usage


@dataclass
class PhaseMetrics:
    name: str = "idle"
    model: str = ""
    started_at: float = field(default_factory=time.time)
    events: int = 0
    messages: int = 0
    tool_calls: int = 0
    turns: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: float = 0.0
    reported_usd: float = 0.0
    last_event: str = ""
    last_tool: str = ""
    last_tool_at: float = 0.0


class NullUI:
    """No-op UI used for non-interactive output / --no-live."""

    live = False

    def start_run(self, *, run_dir: Path, conditions: list, trials: int, dry_run: bool) -> None:
        pass

    def stop(self) -> None:
        pass

    def start_phase(self, name: str, model: str = "") -> None:
        pass

    def end_phase(self, status: str = "complete") -> None:
        pass

    def add_turn_result(self, usage: Usage, cost_usd: float, reported_usd: float = 0.0) -> None:
        pass

    def on_rpc_event(self, ev: dict) -> None:
        pass

    def log(self, message: str) -> None:
        print(message, flush=True)


class RichUI(NullUI):
    """Small live dashboard. Durable data still lives in transcript/report files."""

    live = True

    def __init__(self) -> None:
        from rich.console import Console
        from rich.live import Live

        self.console = Console()
        self._Live = Live
        self._live = None
        self.run_dir: Path | None = None
        self.conditions: list = []
        self.trials = 1
        self.dry_run = False
        self.run_started_at = time.time()
        self.phase = PhaseMetrics()
        self.completed: list[str] = []
        self.current_condition = ""

    def start_run(self, *, run_dir: Path, conditions: list, trials: int, dry_run: bool) -> None:
        self.run_dir = run_dir
        self.conditions = conditions
        self.trials = trials
        self.dry_run = dry_run
        self.run_started_at = time.time()
        self._live = self._Live(self._render(), console=self.console, refresh_per_second=8, transient=False)
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.stop()
            self._live = None

    def log(self, message: str) -> None:
        if self._live:
            self.console.log(message)
        else:
            print(message, flush=True)

    def start_phase(self, name: str, model: str = "") -> None:
        self.phase = PhaseMetrics(name=name, model=model)
        self._refresh()

    def end_phase(self, status: str = "complete") -> None:
        elapsed = time.time() - self.phase.started_at
        self.completed.append(f"[green]✓[/green] {self.phase.name} {status} in {elapsed:.1f}s")
        self._refresh()

    def add_turn_result(self, usage: Usage, cost_usd: float, reported_usd: float = 0.0) -> None:
        self.phase.turns += 1
        self.phase.usage.add(usage)
        self.phase.cost_usd += cost_usd
        self.phase.reported_usd += reported_usd
        self._refresh()

    def on_rpc_event(self, ev: dict) -> None:
        self.phase.events += 1
        etype = str(ev.get("type", "event"))
        self.phase.last_event = etype
        if etype in {"message_start", "message_end"}:
            self.phase.messages += 1
        self.phase.tool_calls += _count_tool_markers(ev)
        tool_name = _tool_name(ev)
        if tool_name:
            self.phase.last_tool = tool_name
            self.phase.last_tool_at = time.time()
        self._refresh()

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render(self):
        from rich import box
        from rich.panel import Panel
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text
        from rich.columns import Columns

        elapsed = time.time() - self.run_started_at
        header = Table.grid(expand=True)
        header.add_column(ratio=1)
        header.add_column(ratio=1)
        conds = ", ".join(getattr(c, "id", str(c)) for c in self.conditions)
        header.add_row("[bold cyan]kimi-claude-bench[/bold cyan]", f"[bold]{'DRY RUN' if self.dry_run else 'REAL RUN'}[/bold]")
        header.add_row("run dir", str(self.run_dir or ""))
        header.add_row("conditions", conds)
        header.add_row("trials", str(self.trials))
        header.add_row("elapsed", _fmt_duration(elapsed))

        phase_elapsed = time.time() - self.phase.started_at
        spin = Spinner("dots", text=f"[bold]{self.phase.name}[/bold] {self.phase.model} ({_fmt_duration(phase_elapsed)})")

        metrics = Table(box=box.SIMPLE_HEAVY, expand=True)
        metrics.add_column("metric", style="dim")
        metrics.add_column("value", justify="right")
        usage = self.phase.usage
        metrics.add_row("turns", str(self.phase.turns))
        metrics.add_row("events", str(self.phase.events))
        metrics.add_row("messages", str(self.phase.messages))
        metrics.add_row("tool calls", str(self.phase.tool_calls))
        metrics.add_row("input tokens", f"{usage.input:,}")
        metrics.add_row("output tokens", f"{usage.output:,}")
        metrics.add_row("cache read", f"{usage.cache_read:,}")
        metrics.add_row("cache write", f"{usage.cache_write:,}")
        metrics.add_row("configured cost", f"${self.phase.cost_usd:.6f}")
        metrics.add_row("Pi reported", f"${self.phase.reported_usd:.6f}")
        metrics.add_row("last event", self.phase.last_event or "—")
        last_tool = self.phase.last_tool or "—"
        if self.phase.last_tool_at:
            last_tool = f"{last_tool} ({_fmt_duration(time.time() - self.phase.last_tool_at)} ago)"
        metrics.add_row("last tool call", last_tool)

        done = Text.from_markup("\n".join(self.completed[-8:]) or "[dim]No completed phases yet.[/dim]")
        return Panel.fit(
            Columns([
                Panel(header, title="Run", border_style="cyan"),
                Panel(spin, title="Current phase", border_style="magenta"),
                Panel(metrics, title="Live counters", border_style="green"),
                Panel(done, title="Completed", border_style="blue"),
            ], equal=True, expand=True),
            title="[bold]Benchmark dashboard[/bold]",
            border_style="bright_blue",
        )


def make_ui(enabled: bool | None = None) -> NullUI:
    if enabled is None:
        enabled = sys.stdout.isatty()
    if not enabled:
        return NullUI()
    try:
        return RichUI()
    except Exception:
        return NullUI()


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _content_blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _count_tool_markers(ev: dict) -> int:
    count = 0
    etype = str(ev.get("type", "")).lower()
    if "tool" in etype or "function" in etype:
        count += 1
    msg = ev.get("message")
    if isinstance(msg, dict):
        for block in _content_blocks(msg):
            btype = str(block.get("type", "")).lower()
            if "tool" in btype or "function" in btype:
                count += 1
    for block in _content_blocks(ev):
        btype = str(block.get("type", "")).lower()
        if "tool" in btype or "function" in btype:
            count += 1
    return count


def _tool_name(ev: dict) -> str:
    """Best-effort extraction of the latest tool/function call name from Pi events.

    Pi event shapes vary by version/provider. Tool names can appear directly on the
    event, inside message content blocks, or nested under input/toolUse/function_call
    objects. This recursive extractor keeps the live dashboard useful across shapes.
    """
    return _find_tool_name(ev)[:80]


def _find_tool_name(obj: Any) -> str:
    if isinstance(obj, list):
        for item in obj:
            found = _find_tool_name(item)
            if found:
                return found
        return ""
    if not isinstance(obj, dict):
        return ""

    obj_type = str(obj.get("type", "")).lower()
    looks_like_tool = any(s in obj_type for s in ("tool", "function")) or any(
        k in obj for k in ("tool", "toolName", "tool_name", "function_call", "toolUse", "tool_use")
    )

    if looks_like_tool:
        for key in ("toolName", "tool_name", "tool", "name"):
            val = obj.get(key)
            if isinstance(val, str) and val:
                return val
        fn = obj.get("function") or obj.get("function_call")
        if isinstance(fn, dict):
            val = fn.get("name")
            if isinstance(val, str) and val:
                return val
        if isinstance(fn, str) and fn:
            return fn

    # Prefer likely content/message containers first so we find the newest visible tool
    # block before generic metadata.
    for key in ("content", "message", "delta", "toolUse", "tool_use", "input"):
        if key in obj:
            found = _find_tool_name(obj[key])
            if found:
                return found
    for val in obj.values():
        found = _find_tool_name(val)
        if found:
            return found
    return ""
