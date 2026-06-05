"""Pi RPC driver.

Drives a `pi --mode rpc` subprocess over JSONL (stdin/stdout). Verified against the real
binary: events stream as `agent_start` → `turn_start` → `message_start`/`message_update`/
`message_end` → `turn_end` → `agent_end`. `agent_end` carries the full `messages` array;
assistant messages carry `usage = {input, output, cacheRead, cacheWrite, totalTokens, cost}`.

This module is provider-agnostic: it only passes `provider`/`model_id` through to
`set_model`. If Pi rejects the model (e.g. provider not registered), we raise PiRpcError
so the orchestrator can fail fast with a clear message.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue


class PiRpcError(Exception):
    """Raised on RPC protocol errors, rejected set_model, or timeout."""


def _reported_cost_to_float(value) -> float:
    """Coerce Pi/provider reported cost into USD when possible.

    Pi builds/providers are not fully consistent here: `usage.cost` may be a number,
    a numeric string, or a structured object such as {"usd": ...} / {"total": ...}.
    Unknown shapes are treated as 0 because configured pricing remains the benchmark
    source of truth.
    """
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    if isinstance(value, dict):
        for key in ("usd", "total", "totalUsd", "amount", "cost"):
            if key in value:
                return _reported_cost_to_float(value[key])
    return 0.0


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reported_cost: float = 0.0

    def add(self, other: "Usage") -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write += other.cache_write
        self.reported_cost += other.reported_cost

    def delta_since(self, previous: "Usage") -> "Usage":
        """Return the non-negative usage delta from a previous cumulative snapshot."""
        return Usage(
            input=max(0, self.input - previous.input),
            output=max(0, self.output - previous.output),
            cache_read=max(0, self.cache_read - previous.cache_read),
            cache_write=max(0, self.cache_write - previous.cache_write),
            reported_cost=max(0.0, self.reported_cost - previous.reported_cost),
        )

    @classmethod
    def from_message_usage(cls, u: dict) -> "Usage":
        return cls(
            input=int(u.get("input", 0) or 0),
            output=int(u.get("output", 0) or 0),
            cache_read=int(u.get("cacheRead", 0) or 0),
            cache_write=int(u.get("cacheWrite", 0) or 0),
            reported_cost=_reported_cost_to_float(u.get("cost")),
        )


@dataclass
class TurnResult:
    """Result of one prompt/follow_up turn driven to agent_end."""

    text: str                      # concatenated final assistant text
    usage: Usage                   # summed usage across assistant messages this turn
    raw_messages: list = field(default_factory=list)


class PiSession:
    """A single Pi RPC subprocess. One model, one working directory.

    Use as a context manager. `cwd` is where the agent's file tools operate, so the
    implementer writes its build there.
    """

    def __init__(
        self,
        cwd: str | Path,
        *,
        enable_tools: bool = False,
        startup_timeout: float = 30.0,
        pi_bin: str = "pi",
        extra_args: list[str] | None = None,
        event_callback: Callable[[dict], None] | None = None,
    ) -> None:
        self.cwd = str(cwd)
        self.enable_tools = enable_tools
        self.startup_timeout = startup_timeout
        self.pi_bin = pi_bin
        self.extra_args = extra_args or []
        self.event_callback = event_callback
        self._proc: subprocess.Popen | None = None
        self._events: "Queue[dict]" = Queue()
        self._reader: threading.Thread | None = None
        self._stderr_buf: list[str] = []
        # Pi agent_end contains the full message history. Keep cumulative snapshots so
        # prompt()/follow_up() return only the new usage/text for that turn.
        self._last_cumulative_usage = Usage()
        self._last_message_count = 0

    # -- lifecycle --

    def __enter__(self) -> "PiSession":
        args = [self.pi_bin, "--mode", "rpc", "--no-session"]
        if not self.enable_tools:
            args.append("--no-tools")
        args += self.extra_args
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._send({"type": "abort"})
            except Exception:
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # -- io --

    def _read_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            try:
                self._events.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self._stderr_buf.append(line)

    def _send(self, obj: dict) -> None:
        if not self._proc or not self._proc.stdin:
            raise PiRpcError("session not started")
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()

    def _stderr_tail(self, n: int = 800) -> str:
        return "".join(self._stderr_buf)[-n:]

    # -- commands --

    def set_model(self, provider: str, model_id: str, *, timeout: float = 15.0) -> None:
        """Set the model; raise PiRpcError if Pi rejects it (fail fast)."""
        self._send({"type": "set_model", "provider": provider, "modelId": model_id})
        resp = self._await_response("set_model", timeout=timeout)
        if not resp.get("success"):
            raise PiRpcError(
                f"set_model rejected for {provider}/{model_id}: "
                f"{resp.get('error', 'unknown error')}"
            )

    def set_thinking(self, level: str, *, timeout: float = 10.0) -> None:
        """Best-effort thinking/temperature control. Ignored if unsupported."""
        self._send({"type": "set_thinking", "level": level})
        try:
            self._await_response("set_thinking", timeout=timeout)
        except PiRpcError:
            pass  # not all builds support it; non-fatal

    def prompt(self, message: str, *, timeout: float) -> TurnResult:
        self._send({"type": "prompt", "message": message})
        self._await_response("prompt", timeout=15.0)
        return self._collect_until_agent_end(timeout=timeout)

    def follow_up(self, message: str, *, timeout: float) -> TurnResult:
        self._send({"type": "follow_up", "message": message})
        self._await_response("follow_up", timeout=15.0)
        return self._collect_until_agent_end(timeout=timeout)

    # -- event collection --

    def _await_response(self, command: str, *, timeout: float) -> dict:
        """Wait for the {type:response, command:...} ack for a command."""
        deadline = time.monotonic() + timeout
        pending: list[dict] = []
        while time.monotonic() < deadline:
            try:
                ev = self._events.get(timeout=0.2)
            except Empty:
                if self._proc and self._proc.poll() is not None:
                    raise PiRpcError(
                        f"pi exited before responding to '{command}'. "
                        f"stderr: {self._stderr_tail()}"
                    )
                continue
            if ev.get("type") == "response" and ev.get("command") == command:
                self._emit_event(ev)
                # re-queue any non-matching events we pulled
                for p in pending:
                    self._events.put(p)
                return ev
            pending.append(ev)
        raise PiRpcError(f"timeout waiting for response to '{command}'")

    def _collect_until_agent_end(self, *, timeout: float) -> TurnResult:
        """Drain events until agent_end; aggregate assistant text + usage."""
        deadline = time.monotonic() + timeout
        cumulative = Usage()
        final_text_parts: list[str] = []
        messages: list = []

        while time.monotonic() < deadline:
            try:
                ev = self._events.get(timeout=0.5)
            except Empty:
                if self._proc and self._proc.poll() is not None:
                    raise PiRpcError(
                        f"pi exited mid-turn. stderr: {self._stderr_tail()}"
                    )
                continue

            self._emit_event(ev)
            etype = ev.get("type")
            if etype == "agent_end":
                messages = ev.get("messages", []) or []
                # Aggregate cumulative usage from the full message list, then return only
                # the delta since the previous turn to avoid double-counting follow-ups.
                cumulative = Usage()
                final_text_parts = []
                new_messages = messages[self._last_message_count:]
                for m in messages:
                    if m.get("role") == "assistant":
                        u = m.get("usage")
                        if isinstance(u, dict):
                            cumulative.add(Usage.from_message_usage(u))
                for m in new_messages:
                    if m.get("role") != "assistant":
                        continue
                    for block in m.get("content", []) or []:
                        if block.get("type") == "text" and block.get("text"):
                            final_text_parts.append(block["text"])

                turn_usage = cumulative.delta_since(self._last_cumulative_usage)
                self._last_cumulative_usage = cumulative
                self._last_message_count = len(messages)
                return TurnResult(
                    text="\n".join(final_text_parts).strip(),
                    usage=turn_usage,
                    raw_messages=new_messages,
                )

        raise PiRpcError(f"turn exceeded wall-clock timeout of {timeout}s")

    def _emit_event(self, ev: dict) -> None:
        if not self.event_callback:
            return
        try:
            self.event_callback(ev)
        except Exception:
            pass
