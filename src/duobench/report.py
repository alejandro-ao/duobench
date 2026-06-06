"""Static HTML report generation for benchmark runs."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


CSS = """
:root { color-scheme: dark; --bg:#0b1020; --panel:#121a2e; --muted:#92a0b8; --text:#ecf2ff; --accent:#7c9cff; --ok:#63d297; --bad:#ff6b7a; --line:#24304a; }
*{box-sizing:border-box} body{margin:0;background:linear-gradient(135deg,#080b15,#101a33);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
a{color:#9db4ff}.layout{display:grid;grid-template-columns:300px 1fr;min-height:100vh}.side{position:sticky;top:0;height:100vh;overflow:auto;padding:22px;background:rgba(9,14,27,.92);border-right:1px solid var(--line)}.main{padding:28px;overflow:auto}h1{font-size:22px;margin:0 0 6px}h2{margin:28px 0 12px;font-size:20px}h3{margin:0 0 10px}.muted{color:var(--muted)}.nav a{display:block;padding:8px 10px;margin:5px 0;border-radius:8px;text-decoration:none;color:var(--text);background:rgba(255,255,255,.03)}.nav a:hover{background:rgba(124,156,255,.18)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.metric{background:rgba(255,255,255,.045);border:1px solid var(--line);padding:12px;border-radius:12px}.metric b{display:block;font-size:22px}.card{background:rgba(18,26,46,.88);border:1px solid var(--line);box-shadow:0 18px 60px rgba(0,0,0,.24);border-radius:16px;padding:18px;margin:0 0 22px}.pill{display:inline-flex;gap:6px;align-items:center;border:1px solid var(--line);background:rgba(255,255,255,.055);border-radius:999px;padding:4px 9px;margin:2px;color:#dbe6ff}.ok{color:var(--ok)}.bad{color:var(--bad)}details{border:1px solid var(--line);border-radius:12px;margin:10px 0;background:rgba(0,0,0,.12)}summary{cursor:pointer;padding:12px;font-weight:650}.turn{padding:0 12px 12px}.pre{white-space:pre-wrap;overflow:auto;background:#070b14;border:1px solid #1f2a42;border-radius:10px;padding:12px;max-height:460px}.shots{display:flex;gap:10px;overflow:auto;padding:8px 0}.shots img{height:180px;border-radius:10px;border:1px solid var(--line);background:#000}.build-frame{width:100%;height:520px;border:1px solid var(--line);border-radius:12px;background:white}.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:950px){.layout{grid-template-columns:1fr}.side{position:relative;height:auto}.two{grid-template-columns:1fr}}
"""


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _rel(run_dir: Path, path: str | Path) -> str:
    p = Path(path)
    try:
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        return html.escape(p.relative_to(run_dir.resolve()).as_posix())
    except Exception:
        return html.escape(str(path))


def _fmt_usd(v: Any) -> str:
    try:
        return f"${float(v):.6f}"
    except Exception:
        return "$0.000000"


def _metrics(stats: dict) -> str:
    items = [
        ("Duration", f"{stats.get('duration_s', 0):.1f}s" if isinstance(stats.get('duration_s', 0), (int, float)) else stats.get('duration_s', 0)),
        ("Turns", stats.get("turns", 0)),
        ("Messages", stats.get("messages", 0)),
        ("Tool calls", stats.get("tool_calls", 0)),
        ("Input tok", stats.get("input_tokens", 0)),
        ("Output tok", stats.get("output_tokens", 0)),
        ("Cache read", stats.get("cache_read_tokens", 0)),
        ("Cache write", stats.get("cache_write_tokens", 0)),
        ("Cost", _fmt_usd(stats.get("usd", 0))),
        ("Pi reported", _fmt_usd(stats.get("reported_usd", 0))),
    ]
    return "<div class='grid'>" + "".join(f"<div class='metric'><span class='muted'>{html.escape(str(k))}</span><b>{html.escape(str(v))}</b></div>" for k, v in items) + "</div>"


def _transcript_block(title: str, path: Path) -> str:
    tr = _load_json(path)
    if not tr:
        return f"<div class='card'><h3>{html.escape(title)}</h3><p class='muted'>No transcript found.</p></div>"
    stats = tr.get("stats", {})
    turns = tr.get("turns", []) or []
    parts = ["<div class='card'>", f"<h3>{html.escape(title)} <span class='pill'>{html.escape(tr.get('model_key',''))}</span> <span class='pill'>{html.escape(tr.get('status',''))}</span></h3>", _metrics(stats)]
    pi_session = tr.get("pi_session") or {}
    if pi_session:
        name = html.escape(str(pi_session.get("name") or pi_session.get("requested_name") or ""))
        session_file = html.escape(str(pi_session.get("session_file") or ""))
        parts.append(f"<p class='muted'>Pi session: <code>{name}</code>{' · <code>' + session_file + '</code>' if session_file else ''}</p>")
    for i, turn in enumerate(turns, 1):
        prompt = html.escape(str(turn.get("prompt", "")))
        text = html.escape(str(turn.get("assistant_text", "")))
        duration = turn.get("duration_s", 0)
        usage = turn.get("usage", {}) or {}
        cost = turn.get("cost", {}) or {}
        parts.append(
            f"<details><summary>Turn {i}: {html.escape(turn.get('kind','turn'))} · {duration}s · "
            f"in {usage.get('input_tokens',0)} / out {usage.get('output_tokens',0)} · {_fmt_usd(cost.get('usd',0))}</summary>"
            f"<div class='turn two'><div><h4>Prompt</h4><div class='pre'>{prompt}</div></div>"
            f"<div><h4>Assistant</h4><div class='pre'>{text}</div></div></div></details>"
        )
    parts.append("</div>")
    return "".join(parts)


def generate_report(run_dir: Path) -> Path:
    run_dir = run_dir.resolve()
    results = _load_json(run_dir / "results.json")
    trial_dirs = sorted((run_dir / "conditions").glob("*/trial-*"))

    nav = ["<div class='nav'>"]
    body = ["<div class='layout'><aside class='side'><h1>duobench report</h1>", f"<p class='muted'>{html.escape(run_dir.name)}</p>"]
    if results.get("conditions"):
        body.append("<h3>Leaderboard</h3>")
        for cid, data in sorted(results["conditions"].items(), key=lambda kv: kv[1].get("quality", 0), reverse=True):
            body.append(f"<div class='metric'><b>{html.escape(cid)}</b><span class='muted'>quality {data.get('quality',0)} · cost {_fmt_usd(data.get('cost_usd',0))}</span></div>")
    for td in trial_dirs:
        anchor = td.relative_to(run_dir).as_posix().replace("/", "-")
        nav.append(f"<a href='#{html.escape(anchor)}'>{html.escape(td.parent.name)} / {html.escape(td.name)}</a>")
    nav.append("</div></aside><main class='main'>")
    body.extend(nav)

    for td in trial_dirs:
        anchor = td.relative_to(run_dir).as_posix().replace("/", "-")
        trial = _load_json(td / "trial.json")
        verify = _load_json(td / "verify.json")
        rec = trial.get("record", {})
        meta = trial.get("meta", {})
        benchmark = trial.get("benchmark") or {}
        build_index = td / "build" / "index.html"
        body.append(f"<section id='{html.escape(anchor)}' class='card'><h2>{html.escape(td.parent.name)} / {html.escape(td.name)}</h2>")
        body.append("".join([
            f"<span class='pill'>planner: {html.escape(str(rec.get('planner','')))}</span>",
            f"<span class='pill'>implementer: {html.escape(str(rec.get('implementer','')))}</span>",
            f"<span class='pill'>status: {html.escape(str(rec.get('impl_status','')))}</span>",
            f"<span class='pill'>cost: {_fmt_usd(rec.get('cost_usd',0))}</span>",
            f"<span class='pill {'ok' if verify.get('boots_ok') else 'bad'}'>boots_ok: {verify.get('boots_ok')}</span>",
        ]))
        if benchmark.get("label"):
            body.append(f"<p class='muted'>benchmark: <code>{html.escape(str(benchmark.get('label')))}</code></p>")
        if build_index.exists():
            rel = _rel(run_dir, build_index)
            body.append(f"<p><a href='{rel}' target='_blank'>Open generated WebOS in a new tab</a></p><iframe class='build-frame' src='{rel}'></iframe>")
        shots = meta.get("screenshots") or verify.get("screenshots") or []
        if shots:
            body.append("<h3>Screenshots</h3><div class='shots'>" + "".join(f"<a href='{_rel(run_dir,s)}' target='_blank'><img src='{_rel(run_dir,s)}'></a>" for s in shots) + "</div>")
        body.append("</section>")
        body.append(_transcript_block("Planner thread", td / "planner-transcript.json"))
        body.append(_transcript_block("Implementer thread", td / "implementer-transcript.json"))
        judge_dir = td / "judge-transcripts"
        if judge_dir.exists():
            for jp in sorted(judge_dir.glob("*.json")):
                body.append(_transcript_block(f"Judge thread: {jp.stem}", jp))
    body.append("</main></div>")

    html_doc = "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>duobench report</title><style>" + CSS + "</style></head><body>" + "".join(body) + "</body></html>"
    out = run_dir / "report.html"
    out.write_text(html_doc)
    return out
