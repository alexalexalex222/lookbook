from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .router import DesignRouter
from .schemas import DesignContextRequest


class RoutingJudgment(BaseModel):
    judgment_id: str
    split: Literal["train", "calibration", "hidden"]
    request: DesignContextRequest
    expected_decision: Literal["route", "clarify"]
    expected_top1: str | None = None
    acceptable_top3: list[str] = Field(default_factory=list)
    forbidden_pack_ids: list[str] = Field(default_factory=list)
    forbidden_families: list[str] = Field(default_factory=list)
    source: str = "synthetic"
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


def default_judgment_path(repo_root: Path) -> Path:
    return repo_root / "evals" / "router" / "judgments.jsonl"


def load_judgments(path: Path) -> list[RoutingJudgment]:
    judgments: list[RoutingJudgment] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        try:
            judgments.append(RoutingJudgment.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(
                f"Invalid routing judgment at {path}:{line_number}: {exc}"
            ) from exc
    ids = [judgment.judgment_id for judgment in judgments]
    duplicates = sorted(
        identifier for identifier, count in Counter(ids).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"Duplicate routing judgment ids: {duplicates}")
    return judgments


def _top_ids(resolution: Any) -> list[str]:
    selected = resolution.anchor_pack.manifest.pack_id
    alternatives = [
        row.get("pack_id")
        for row in resolution.route_meta.get("anchor_alternatives", [])
        if row.get("pack_id")
    ]
    return [selected, *alternatives]


def _evaluate_one(
    router: DesignRouter,
    judgment: RoutingJudgment,
    profile: str,
) -> dict[str, Any]:
    request = DesignContextRequest.model_validate(
        {
            **judgment.request.model_dump(mode="json"),
            "route_profile": profile,
        }
    )
    resolution = router.route(request)
    confidence = resolution.route_meta.get("route_confidence", {})
    top_ids = _top_ids(resolution)
    winner = top_ids[0]
    family = resolution.anchor_pack.manifest.family
    acceptable = set(judgment.acceptable_top3)
    if judgment.expected_top1:
        acceptable.add(judgment.expected_top1)
    top1_correct = judgment.expected_top1 is None or winner == judgment.expected_top1
    top3_acceptable = not acceptable or bool(acceptable.intersection(top_ids[:3]))
    actual_decision = confidence.get("decision")
    actual_binary_decision = "clarify" if actual_decision == "clarify" else "route"
    decision_correct = actual_binary_decision == judgment.expected_decision
    forbidden_violation = (
        winner in judgment.forbidden_pack_ids or family in judgment.forbidden_families
    )
    passed = (
        decision_correct
        and top1_correct
        and top3_acceptable
        and not forbidden_violation
    )
    hybrid = resolution.route_meta.get("candidate_gate", {}).get("hybrid_retrieval", {})
    return {
        "judgment_id": judgment.judgment_id,
        "split": judgment.split,
        "tags": judgment.tags,
        "expected_decision": judgment.expected_decision,
        "actual_decision": actual_decision,
        "actual_binary_decision": actual_binary_decision,
        "expected_top1": judgment.expected_top1,
        "winner": winner,
        "top3": top_ids[:3],
        "confidence": confidence.get("value", 0.0),
        "top1_correct": top1_correct,
        "top3_acceptable": top3_acceptable,
        "decision_correct": decision_correct,
        "forbidden_violation": forbidden_violation,
        "passed": passed,
        "clarification_question": confidence.get("clarification_question", ""),
        "hybrid_disagreement": bool(hybrid.get("disagreement")),
        "hybrid_winner": hybrid.get("hybrid_winner"),
        "baseline_winner": hybrid.get("baseline_winner"),
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if not total:
        return {
            "count": 0,
            "pass_rate": 0.0,
            "top1_accuracy": 0.0,
            "top3_acceptance": 0.0,
            "decision_accuracy": 0.0,
            "forbidden_violations": 0,
            "hybrid_disagreements": 0,
        }
    return {
        "count": total,
        "pass_rate": round(sum(row["passed"] for row in rows) / total, 4),
        "top1_accuracy": round(sum(row["top1_correct"] for row in rows) / total, 4),
        "top3_acceptance": round(
            sum(row["top3_acceptable"] for row in rows) / total, 4
        ),
        "decision_accuracy": round(
            sum(row["decision_correct"] for row in rows) / total, 4
        ),
        "forbidden_violations": sum(row["forbidden_violation"] for row in rows),
        "hybrid_disagreements": sum(row["hybrid_disagreement"] for row in rows),
    }


def _tag_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    tags = sorted({tag for row in rows for tag in row["tags"]})
    return {tag: _metrics([row for row in rows if tag in row["tags"]]) for tag in tags}


def _confidence_bins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bins: list[dict[str, Any]] = []
    for lower in (0.0, 0.25, 0.5, 0.75):
        upper = lower + 0.25
        selected = [
            row
            for row in rows
            if lower <= row["confidence"] <= upper
            if upper == 1.0 or row["confidence"] < upper
        ]
        bins.append(
            {
                "range": f"{lower:.2f}-{upper:.2f}",
                "count": len(selected),
                "accuracy": (
                    round(
                        sum(row["decision_correct"] for row in selected)
                        / len(selected),
                        4,
                    )
                    if selected
                    else None
                ),
                "route_rate": (
                    round(
                        sum(row["actual_decision"] != "clarify" for row in selected)
                        / len(selected),
                        4,
                    )
                    if selected
                    else None
                ),
            }
        )
    return bins


def fit_confidence_threshold(rows: list[dict[str, Any]]) -> dict[str, Any]:
    calibration = [row for row in rows if row["split"] == "calibration"]
    if not calibration:
        return {"available": False}
    best: tuple[float, float, int, int] | None = None
    for index in range(5, 96):
        threshold = index / 100.0
        correct = 0
        false_confident = 0
        false_clarify = 0
        for row in calibration:
            predicted = "clarify" if row["confidence"] < threshold else "route"
            correct += predicted == row["expected_decision"]
            false_confident += (
                predicted == "route" and row["expected_decision"] == "clarify"
            )
            false_clarify += (
                predicted == "clarify" and row["expected_decision"] == "route"
            )
        candidate = (
            correct / len(calibration),
            -false_confident,
            -false_clarify,
            threshold,
        )
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    return {
        "available": True,
        "threshold": best[3],
        "accuracy": round(best[0], 4),
        "false_confident": -best[1],
        "false_clarify": -best[2],
        "count": len(calibration),
    }


def evaluate_routing(
    repo_root: Path | str,
    *,
    profile: str = "hybrid_v4",
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    path = (
        Path(ledger_path).expanduser().resolve()
        if ledger_path
        else default_judgment_path(root)
    )
    judgments = load_judgments(path)
    router = DesignRouter.from_repo(root, refresh_index=True)
    rows = [_evaluate_one(router, judgment, profile) for judgment in judgments]
    split_metrics = {
        split: _metrics([row for row in rows if row["split"] == split])
        for split in ("train", "calibration", "hidden")
    }
    return {
        "profile": profile,
        "ledger_path": str(path),
        "judgment_count": len(judgments),
        "metrics": _metrics(rows),
        "splits": split_metrics,
        "tags": _tag_metrics(rows),
        "confidence_bins": _confidence_bins(rows),
        "calibration": fit_confidence_threshold(rows),
        "quality_gate": {
            "pass": (
                split_metrics["hidden"]["pass_rate"] == 1.0
                and split_metrics["hidden"]["decision_accuracy"] == 1.0
                and split_metrics["hidden"]["forbidden_violations"] == 0
            ),
            "requirements": {
                "hidden_pass_rate": 1.0,
                "hidden_decision_accuracy": 1.0,
                "hidden_forbidden_violations": 0,
            },
        },
        "hybrid_disagreements": [row for row in rows if row["hybrid_disagreement"]],
        "failures": [row for row in rows if not row["passed"]],
        "rows": rows,
    }


def compare_routing_profiles(
    repo_root: Path | str,
    *,
    profiles: list[str] | None = None,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    selected = profiles or [
        "data_driven_v2",
        "hybrid_shadow_v1",
        "hybrid_v4",
        "hybrid_v5",
    ]
    reports = {
        profile: evaluate_routing(repo_root, profile=profile, ledger_path=ledger_path)
        for profile in selected
    }
    return {
        "profiles": selected,
        "summary": {
            profile: {
                "overall": report["metrics"],
                "hidden": report["splits"]["hidden"],
                "calibration": report["calibration"],
            }
            for profile, report in reports.items()
        },
        "reports": reports,
    }


def render_routing_report(report: dict[str, Any]) -> str:
    profile = html.escape(str(report["profile"]))
    ledger_path = Path(str(report["ledger_path"]))
    ledger_parts = ledger_path.parts
    ledger_label = (
        str(Path(*ledger_parts[ledger_parts.index("evals") :]))
        if "evals" in ledger_parts
        else ledger_path.name
    )
    metrics = report["metrics"]
    rows = report["rows"]
    body_rows = []
    for row in rows:
        tags = " ".join(row["tags"])
        state = "pass" if row["passed"] else "fail"
        if row["hybrid_disagreement"] and row["passed"]:
            state = "warning"
        body_rows.append(
            f'<tr data-state="{state}" data-search="{html.escape((row["judgment_id"] + " " + tags + " " + row["winner"]).lower())}">'
            f"<td>{html.escape(row['judgment_id'])}</td>"
            f'<td><span class="badge split">{html.escape(row["split"])}</span></td>'
            f"<td>{html.escape(row['expected_decision'])} / {html.escape(str(row['actual_decision']))}</td>"
            f"<td>{html.escape(str(row['expected_top1'] or ''))}</td>"
            f"<td>{html.escape(row['winner'])}</td>"
            f"<td>{row['confidence']:.3f}</td>"
            f"<td>{html.escape(tags)}</td>"
            f'<td><span class="badge {state}">{"PASS" if row["passed"] else "FAIL"}{" + RRF" if row["hybrid_disagreement"] else ""}</span></td>'
            "</tr>"
        )
    split_rows = "".join(
        "<tr>"
        f"<td>{html.escape(split)}</td>"
        f"<td>{values['count']}</td>"
        f"<td>{values['pass_rate']:.1%}</td>"
        f"<td>{values['top1_accuracy']:.1%}</td>"
        f"<td>{values['decision_accuracy']:.1%}</td>"
        f"<td>{values['hybrid_disagreements']}</td>"
        "</tr>"
        for split, values in report["splits"].items()
    )
    calibration = report["calibration"]
    quality_gate = report["quality_gate"]
    quality_label = "PASS" if quality_gate["pass"] else "FAIL"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Golden Book Routing Evaluation</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #0b0d10; color: #f3f5f7; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #0b0d10; color: #f3f5f7; }}
button, input {{ font: inherit; }}
button:focus-visible, input:focus-visible {{ outline: 2px solid #f3c969; outline-offset: 2px; }}
main {{ width: min(1560px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 64px; }}
header {{ display: flex; align-items: end; justify-content: space-between; gap: 24px; border-bottom: 1px solid #323842; padding-bottom: 20px; }}
.eyebrow {{ color: #9ba6b2; font: 600 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; }}
h1 {{ font-size: clamp(24px, 3vw, 38px); line-height: 1.08; margin: 6px 0 0; letter-spacing: 0; }}
.meta {{ color: #aeb7c1; margin: 6px 0 0; overflow-wrap: anywhere; }}
.gate {{ min-width: 142px; border-left: 3px solid #63d9a1; padding: 8px 0 8px 14px; }}
.gate.fail {{ border-color: #ff7770; }}
.gate b {{ display: block; font: 700 22px/1 ui-monospace, SFMono-Regular, Menlo, monospace; margin-top: 7px; }}
.summary {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 1px; background: #303640; border: 1px solid #303640; margin: 24px 0; }}
.metric {{ background: #14181d; padding: 16px; min-height: 90px; }}
.metric span {{ color: #9ba6b2; font-size: 13px; }}
.metric b {{ display: block; font: 700 24px/1 ui-monospace, SFMono-Regular, Menlo, monospace; margin-top: 14px; }}
.section-head {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 30px 0 12px; }}
h2 {{ font-size: 18px; margin: 0; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.controls button {{ min-height: 44px; border: 1px solid #3a424d; border-radius: 6px; background: #14181d; color: #dce2e8; padding: 0 14px; cursor: pointer; }}
.controls button:hover {{ background: #1c2229; }}
.controls button[aria-pressed="true"] {{ background: #f3f5f7; color: #0b0d10; border-color: #f3f5f7; }}
.search {{ width: min(420px, 100%); min-height: 44px; border: 1px solid #3a424d; border-radius: 6px; background: #111419; color: #f3f5f7; padding: 0 14px; }}
.table-wrap {{ overflow: auto; max-height: 680px; border: 1px solid #303640; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 11px 12px; text-align: left; border-bottom: 1px solid #262b33; white-space: nowrap; }}
th {{ position: sticky; top: 0; z-index: 1; background: #1b2027; color: #aeb8c4; }}
tbody tr:hover {{ background: #14191f; }}
.badge {{ display: inline-flex; align-items: center; min-height: 24px; border: 1px solid #46505c; border-radius: 999px; padding: 2px 8px; font: 700 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }}
.badge.pass {{ color: #6ee7aa; border-color: #296c4c; }}
.badge.fail {{ color: #ff8982; border-color: #863e3a; }}
.badge.warning {{ color: #f3c969; border-color: #7b672c; }}
.badge.split {{ color: #c7d0da; }}
.split-table {{ max-width: 780px; }}
.empty {{ display: none; color: #aeb7c1; border: 1px solid #303640; padding: 24px; }}
@media (max-width: 1000px) {{ .summary {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} header {{ align-items: start; }} }}
@media (max-width: 620px) {{ main {{ width: min(100% - 20px, 1560px); padding-top: 18px; }} header {{ display: block; }} .gate {{ margin-top: 18px; }} .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .section-head {{ align-items: stretch; flex-direction: column; }} .controls {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }} .controls button {{ padding: 0 8px; }} .search {{ width: 100%; }} }}
</style>
</head>
<body><main>
<header>
<div><div class="eyebrow">Golden Book / Routing Intelligence</div><h1>Quality audit</h1>
<p class="meta">Profile: <strong>{profile}</strong> · Ledger: {html.escape(ledger_label)}</p></div>
<div class="gate {"pass" if quality_gate["pass"] else "fail"}"><span class="eyebrow">Hidden gate</span><b>{quality_label}</b></div>
</header>
<section class="summary">
<div class="metric">Judgments<b>{metrics["count"]}</b></div>
<div class="metric">Pass rate<b>{metrics["pass_rate"]:.1%}</b></div>
<div class="metric">Top-1<b>{metrics["top1_accuracy"]:.1%}</b></div>
<div class="metric">Decision<b>{metrics["decision_accuracy"]:.1%}</b></div>
<div class="metric">Forbidden<b>{metrics["forbidden_violations"]}</b></div>
<div class="metric">Threshold<b>{calibration.get("threshold", 0):.2f}</b></div>
</section>
<div class="section-head"><h2>Performance by split</h2></div>
<div class="table-wrap split-table"><table>
<thead><tr><th>Split</th><th>Cases</th><th>Pass rate</th><th>Top-1</th><th>Decision</th><th>RRF disagreements</th></tr></thead>
<tbody>{split_rows}</tbody>
</table></div>
<div class="section-head"><h2>Judgment ledger</h2><div class="controls" role="group" aria-label="Filter judgments">
<button type="button" data-filter="all" aria-pressed="true">All</button>
<button type="button" data-filter="warning" aria-pressed="false">RRF</button>
<button type="button" data-filter="fail" aria-pressed="false">Failures</button>
</div></div>
<input class="search" id="route-search" type="search" placeholder="Filter by case, tag, or anchor" aria-label="Filter routing judgments">
<div class="table-wrap"><table>
<thead><tr><th>ID</th><th>Split</th><th>Decision</th><th>Expected anchor</th><th>Winner</th><th>Confidence</th><th>Tags</th><th>Status</th></tr></thead>
<tbody>{"".join(body_rows)}</tbody>
</table></div>
<p class="empty" id="empty-state">No judgments match this filter.</p>
</main>
<script>
const rows = [...document.querySelectorAll("tbody tr[data-state]")];
const buttons = [...document.querySelectorAll("[data-filter]")];
const search = document.querySelector("#route-search");
const empty = document.querySelector("#empty-state");
let active = "all";
function applyFilters() {{
  const query = search.value.trim().toLowerCase();
  let shown = 0;
  for (const row of rows) {{
    const stateMatch = active === "all" || row.dataset.state === active;
    const queryMatch = !query || row.dataset.search.includes(query);
    row.hidden = !(stateMatch && queryMatch);
    if (!row.hidden) shown += 1;
  }}
  empty.style.display = shown ? "none" : "block";
}}
for (const button of buttons) {{
  button.addEventListener("click", () => {{
    active = button.dataset.filter;
    for (const item of buttons) item.setAttribute("aria-pressed", String(item === button));
    applyFilters();
  }});
}}
search.addEventListener("input", applyFilters);
</script>
</body></html>"""


def write_routing_report(
    repo_root: Path | str,
    output_dir: Path | str,
    *,
    profile: str = "hybrid_v4",
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = evaluate_routing(repo_root, profile=profile, ledger_path=ledger_path)
    json_path = output / "routing-eval.json"
    html_path = output / "routing-eval.html"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(render_routing_report(report), encoding="utf-8")
    return {
        "profile": profile,
        "json": str(json_path),
        "html": str(html_path),
        "metrics": report["metrics"],
        "splits": report["splits"],
        "calibration": report["calibration"],
        "quality_gate": report["quality_gate"],
        "failure_count": len(report["failures"]),
        "failures": report["failures"],
        "hybrid_disagreement_count": len(report["hybrid_disagreements"]),
        "hybrid_disagreements": report["hybrid_disagreements"],
    }
