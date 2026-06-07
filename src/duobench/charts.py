"""Generate charts (matplotlib PNG) + raw CSV from the aggregated results dict.

Outputs into results_dir:
  leaderboard.png / .csv        — overall quality per condition (bar, with error bars)
  dimension-radar.png / .csv    — per-condition profile across the 3 judged dims
  cost-vs-quality.png / .csv    — the money chart: $ spent vs avg quality
  self-bias-matrix.png / .csv   — judge × condition heatmap
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from duobench.judge import DIMENSIONS  # noqa: E402


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate_charts(results: dict, results_dir: Path) -> list[Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    conditions: dict = results["conditions"]
    cids = list(conditions.keys())
    written: list[Path] = []

    # ---- leaderboard ----
    qualities = [conditions[c]["quality"] for c in cids]
    qstd = [conditions[c]["quality_std"] for c in cids]
    order = sorted(range(len(cids)), key=lambda i: qualities[i], reverse=True)
    o_cids = [cids[i] for i in order]
    o_q = [qualities[i] for i in order]
    o_std = [qstd[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(o_cids[::-1], o_q[::-1], xerr=o_std[::-1], color="#4c78a8", capsize=4)
    ax.set_xlabel("Average quality (mean of judged dimensions)")
    ax.set_title("Leaderboard — planner×implementer conditions")
    ax.set_xlim(0, 10)
    fig.tight_layout()
    p = results_dir / "leaderboard.png"
    fig.savefig(p, dpi=130); plt.close(fig); written.append(p)
    pc = results_dir / "leaderboard.csv"
    _write_csv(pc, ["condition", "quality", "quality_std"],
               [[o_cids[i], o_q[i], o_std[i]] for i in range(len(o_cids))])
    written.append(pc)

    # ---- dimension radar ----
    angles = [n / len(DIMENSIONS) * 2 * math.pi for n in range(len(DIMENSIONS))]
    angles += angles[:1]
    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, polar=True)
    for c in cids:
        vals = [conditions[c]["dimensions"][d] for d in DIMENSIONS]
        vals += vals[:1]
        ax.plot(angles, vals, label=c, linewidth=1.5)
        ax.fill(angles, vals, alpha=0.05)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([d.replace("_", "/") for d in DIMENSIONS])
    ax.set_ylim(0, 10)
    ax.set_title("Dimension profile per condition")
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), fontsize=8)
    fig.tight_layout()
    p = results_dir / "dimension-radar.png"
    fig.savefig(p, dpi=130); plt.close(fig); written.append(p)
    pc = results_dir / "dimensions.csv"
    _write_csv(pc, ["condition", *DIMENSIONS],
               [[c, *[conditions[c]["dimensions"][d] for d in DIMENSIONS]] for c in cids])
    written.append(pc)

    # ---- cost vs quality (the money chart) ----
    fig, ax = plt.subplots(figsize=(10, 7))
    for c in cids:
        x = conditions[c]["cost_usd"]
        y = conditions[c]["quality"]
        ax.scatter(x, y, s=80, color="#e45756", zorder=3)
        ax.annotate(c, (x, y), textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xlabel("Cost (USD, planner + implementer)")
    ax.set_ylabel("Average quality")
    ax.set_ylim(0, 10)
    ax.set_title("Cost vs Quality — top-left is the best trade-off")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = results_dir / "cost-vs-quality.png"
    fig.savefig(p, dpi=130); plt.close(fig); written.append(p)
    pc = results_dir / "cost-vs-quality.csv"
    _write_csv(pc, ["condition", "cost_usd", "quality", "cost_efficiency"],
               [[c, conditions[c]["cost_usd"], conditions[c]["quality"],
                 conditions[c]["cost_efficiency"]] for c in cids])
    written.append(pc)

    # ---- self-bias matrix ----
    judges = results.get("judges", [])
    self_bias: dict = results.get("self_bias", {})
    if judges:
        matrix = [[self_bias.get(j, {}).get(c, float("nan")) for c in cids] for j in judges]
        fig, ax = plt.subplots(figsize=(max(8, len(cids)), max(4, len(judges))))
        im = ax.imshow(matrix, cmap="viridis", vmin=0, vmax=10, aspect="auto")
        ax.set_xticks(range(len(cids))); ax.set_xticklabels(cids, rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(len(judges))); ax.set_yticklabels(judges, fontsize=9)
        ax.set_title("Self-bias matrix — judge (row) overall score per build (col)")
        for i in range(len(judges)):
            for k in range(len(cids)):
                v = matrix[i][k]
                if not math.isnan(v):
                    ax.text(k, i, f"{v:.1f}", ha="center", va="center", color="w", fontsize=7)
        fig.colorbar(im, ax=ax, label="overall score")
        fig.tight_layout()
        p = results_dir / "self-bias-matrix.png"
        fig.savefig(p, dpi=130); plt.close(fig); written.append(p)
        pc = results_dir / "self-bias.csv"
        _write_csv(pc, ["judge", *cids],
                   [[j, *[self_bias.get(j, {}).get(c, "") for c in cids]] for j in judges])
        written.append(pc)

    return written
