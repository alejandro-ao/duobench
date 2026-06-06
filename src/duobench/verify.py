"""Playwright headless verification: objective smoke signals + screenshots.

Builds vary wildly in markup, so checks are heuristic and resilient. We record objective
signals that feed Code correctness and capture screenshots for the Visual/UX judge input.

"Boots OK" (per DESIGN §11.3): desktop + taskbar render, no fatal console error, AND at
least 3 launchable app entry points were successfully opened. Per-app launch results are
recorded individually so partial builds score proportionally.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

BOOT_APP_THRESHOLD = 3
_NAV_WAIT_MS = 3500
_ACTION_WAIT_MS = 600


@dataclass
class AppLaunch:
    label: str
    launched: bool
    window_count_after: int


@dataclass
class VerifyResult:
    boots_ok: bool
    desktop_rendered: bool
    taskbar_rendered: bool
    fatal_console_errors: list[str] = field(default_factory=list)
    apps_attempted: int = 0
    apps_launched: int = 0
    app_results: list[AppLaunch] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def summary_for_judge(self) -> str:
        return json.dumps(
            {
                "boots_ok": self.boots_ok,
                "desktop_rendered": self.desktop_rendered,
                "taskbar_rendered": self.taskbar_rendered,
                "fatal_console_errors": self.fatal_console_errors[:5],
                "apps_attempted": self.apps_attempted,
                "apps_launched": self.apps_launched,
                "app_results": [
                    {"label": a.label, "launched": a.launched} for a in self.app_results
                ],
            },
            indent=2,
        )


# Selectors / roles likely to represent launchable entry points, in priority order.
_LAUNCHER_SELECTORS = [
    ".desktop-icon",
    "[data-app]",
    ".app-icon",
    ".start-menu-item",
    ".start-menu li",
    ".taskbar [data-app]",
    "[class*='icon'][class*='app']",
]
_WINDOW_SELECTORS = ".window, .os-window, [class*='window'], [data-window]"
_DESKTOP_SELECTORS = "#desktop, .desktop, [class*='desktop']"
_TASKBAR_SELECTORS = "#taskbar, .taskbar, [class*='taskbar']"


def _count_windows(page) -> int:
    try:
        return page.eval_on_selector_all(
            _WINDOW_SELECTORS,
            "els => els.filter(e => e.offsetParent !== null).length",
        )
    except Exception:
        return 0


def verify_build(build_dir: Path, screenshot_dir: Path) -> VerifyResult:
    index = build_dir / "index.html"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    res = VerifyResult(boots_ok=False, desktop_rendered=False, taskbar_rendered=False)

    if not index.exists():
        res.notes.append("no index.html at build root")
        return res

    console_errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        try:
            page.goto(index.resolve().as_uri(), wait_until="load", timeout=15000)
            page.wait_for_timeout(_NAV_WAIT_MS)
        except Exception as e:
            res.notes.append(f"navigation failed: {e}")
            browser.close()
            res.fatal_console_errors = console_errors
            return res

        res.desktop_rendered = page.query_selector(_DESKTOP_SELECTORS) is not None
        res.taskbar_rendered = page.query_selector(_TASKBAR_SELECTORS) is not None

        # Desktop screenshot
        desktop_png = screenshot_dir / "desktop.png"
        try:
            page.screenshot(path=str(desktop_png))
            res.screenshots.append(str(desktop_png))
        except Exception as e:
            res.notes.append(f"desktop screenshot failed: {e}")

        # Gather candidate launchers
        launchers = []
        for sel in _LAUNCHER_SELECTORS:
            try:
                els = page.query_selector_all(sel)
            except Exception:
                els = []
            for el in els:
                try:
                    if el.is_visible():
                        launchers.append(el)
                except Exception:
                    continue
            if launchers:
                break  # use the first selector family that finds anything

        # De-dupe by label, cap attempts
        seen_labels: set[str] = set()
        unique = []
        for el in launchers:
            try:
                label = (el.inner_text() or el.get_attribute("data-app") or "app").strip()[:40]
            except Exception:
                label = "app"
            if label in seen_labels:
                continue
            seen_labels.add(label)
            unique.append((label, el))
        unique = unique[:8]

        base_windows = _count_windows(page)
        for label, el in unique:
            res.apps_attempted += 1
            launched = False
            try:
                el.click(timeout=2000)
                page.wait_for_timeout(_ACTION_WAIT_MS)
                now = _count_windows(page)
                launched = now > base_windows
                if launched:
                    res.apps_launched += 1
                    shot = screenshot_dir / f"app-{res.apps_launched:02d}.png"
                    try:
                        page.screenshot(path=str(shot))
                        res.screenshots.append(str(shot))
                    except Exception:
                        pass
                base_windows = max(base_windows, now)
            except Exception as e:
                res.notes.append(f"launch '{label}' failed: {e}")
            res.app_results.append(AppLaunch(label, launched, base_windows))

        browser.close()

    res.fatal_console_errors = console_errors
    res.boots_ok = (
        res.desktop_rendered
        and res.taskbar_rendered
        and len(console_errors) == 0
        and res.apps_launched >= BOOT_APP_THRESHOLD
    )
    return res
