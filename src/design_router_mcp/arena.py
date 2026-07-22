from __future__ import annotations

import html
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .schemas import DesignContextRequest


_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_EXTERNAL_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.IGNORECASE | re.DOTALL)
_EMOJI_RE = re.compile(
    "[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff\U00002600-\U000027bf]"
)
_STATE_TERMS = {"loading", "empty", "error", "success"}
_STRUCTURE_TERMS = {
    "timeline",
    "process",
    "proof",
    "schedule",
    "comparison",
    "filter",
    "queue",
    "table",
    "specification",
    "coverage",
    "review",
}
_OUTPUT_CAP_RE = re.compile(
    r"(?:keep|limit|cap|restrict|at or under|no more than|maximum|max(?:imum)?)"
    r"[^\n]{0,80}\b\d[\d,_]*\s*(?:bytes?|characters?|chars?|tokens?|lines?)",
    re.IGNORECASE,
)
_NEGATIVE_CONTROL = """<!doctype html>
<html><head><style>.overflow { width: 4000px }</style></head>
<body><div class="overflow"><img src="https://example.com/fake.jpg"><h2>Best ever</h2></div></body></html>
"""


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _load_config(path: Path | str) -> tuple[Path, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("arena config must be an object with a cases array")
    seen: set[str] = set()
    instruction_blocks = [str(payload.get("shared_instructions") or "")]
    for case in payload["cases"]:
        if not isinstance(case, dict):
            raise ValueError("arena cases must be objects")
        case_id = str(case.get("case_id") or "")
        if not _CASE_ID_RE.fullmatch(case_id):
            raise ValueError(f"invalid arena case_id: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"duplicate arena case_id: {case_id}")
        seen.add(case_id)
        instruction_blocks.append(str(case.get("build_instructions") or ""))
        DesignContextRequest.model_validate(case.get("request") or {})
    capped = [block for block in instruction_blocks if _OUTPUT_CAP_RE.search(block)]
    if capped:
        raise ValueError(
            "arena output capacity limits are disabled; remove byte, character, "
            "line, or completion-token ceilings from build instructions"
        )
    return resolved, payload


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title_depth = 0
        self.title_text: list[str] = []
        self.body_depth = 0
        self.body_text: list[str] = []
        self.counts: dict[str, int] = {}
        self.external_refs: list[str] = []
        self.raster_refs: list[str] = []
        self.input_ids: set[str] = set()
        self.label_for: set[str] = set()
        self.unlabelled_inputs: list[str] = []
        self.skip_link = False
        self.skip_link_depth = 0
        self.inline_style_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        self.counts[lowered] = self.counts.get(lowered, 0) + 1
        if lowered == "html":
            self.lang = attributes.get("lang", "")
        elif lowered == "title":
            self.title_depth += 1
        elif lowered == "body":
            self.body_depth += 1
        if "style" in attributes:
            self.inline_style_count += 1
        for key in ("src", "href", "poster"):
            value = attributes.get(key, "")
            if value and _EXTERNAL_RE.match(value):
                self.external_refs.append(value)
        if lowered in {"img", "picture", "source", "video"}:
            value = (
                attributes.get("src")
                or attributes.get("srcset")
                or attributes.get("poster")
                or lowered
            )
            self.raster_refs.append(value)
        if lowered == "a" and attributes.get("href", "").startswith("#"):
            self.skip_link_depth += 1
            if (
                "skip" in attributes.get("class", "").lower()
                or "skip" in attributes.get("aria-label", "").lower()
            ):
                self.skip_link = True
        if lowered == "label" and attributes.get("for"):
            self.label_for.add(attributes["for"])
        if lowered in {"input", "select", "textarea"}:
            input_type = attributes.get("type", "").lower()
            if input_type not in {"hidden", "button", "submit", "reset"}:
                identifier = attributes.get("id", "")
                if identifier:
                    self.input_ids.add(identifier)
                if (
                    not attributes.get("aria-label")
                    and not attributes.get("aria-labelledby")
                    and not identifier
                ):
                    self.unlabelled_inputs.append(lowered)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title" and self.title_depth:
            self.title_depth -= 1
        elif lowered == "body" and self.body_depth:
            self.body_depth -= 1
        elif lowered == "a" and self.skip_link_depth:
            self.skip_link_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_text.append(data)
        if self.body_depth and data.strip():
            self.body_text.append(data.strip())
        if self.skip_link_depth and "skip" in data.lower():
            self.skip_link = True


def _score_static(scan: dict[str, Any]) -> int:
    score = 0
    score += 12 if scan["title"] else 0
    score += 8 if scan["lang"] else 0
    score += 12 if scan["counts"].get("h1") == 1 else 0
    score += min(14, scan["counts"].get("section", 0) * 2)
    score += min(10, scan["counts"].get("button", 0) + scan["counts"].get("a", 0))
    score += 8 if scan["focus_visible"] else 0
    score += 6 if scan["reduced_motion"] else 0
    score += 5 if scan["skip_link"] else 0
    score += min(10, scan["domain_term_hits"] * 2)
    score += min(10, scan["structure_marker_hits"] * 2)
    score -= min(30, len(scan["violations"]) * 10)
    return max(0, min(100, score))


def static_page_scan(
    path: Path | str, *, domain_terms: list[str] | None = None
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    source = resolved.read_text(encoding="utf-8", errors="replace")
    parser = _PageParser()
    parser.feed(source)
    lowered = source.lower()
    visible_text = " ".join(parser.body_text)
    missing_labels = sorted(parser.input_ids.difference(parser.label_for))
    css_urls = [
        value
        for _, value in _CSS_URL_RE.findall(source)
        if value
        and not value.startswith("#")
        and not value.startswith("data:image/svg+xml")
    ]
    external_css_urls = [value for value in css_urls if _EXTERNAL_RE.match(value)]
    svg_blocks = [
        re.sub(r"\s+", " ", block.strip()) for block in _SVG_RE.findall(source)
    ]
    repeated_svg_count = sum(
        count - 1 for count in Counter(svg_blocks).values() if count > 1
    )
    terms = [term.lower() for term in domain_terms or [] if term.strip()]
    domain_hits = sum(term in visible_text.lower() for term in terms)
    state_hits = sum(term in lowered for term in _STATE_TERMS)
    structure_hits = sum(term in lowered for term in _STRUCTURE_TERMS)
    violations: list[str] = []
    title = " ".join(parser.title_text).strip()
    if not title:
        violations.append("missing_title")
    if not parser.lang:
        violations.append("missing_html_lang")
    if parser.counts.get("h1", 0) != 1:
        violations.append("heading_flow_requires_one_h1")
    if parser.raster_refs:
        violations.append("raster_media_present")
    if parser.external_refs or external_css_urls:
        violations.append("external_asset_reference")
    if _EMOJI_RE.search(visible_text):
        violations.append("emoji_in_visible_copy")
    if missing_labels or parser.unlabelled_inputs:
        violations.append("unlabelled_form_control")
    if not visible_text:
        violations.append("empty_body")
    warnings: list[str] = []
    if parser.inline_style_count:
        warnings.append("inline_styles_present")
    if repeated_svg_count:
        warnings.append("repeated_identical_svg")
    result = {
        "path": str(resolved),
        "hard_pass": not violations,
        "violations": violations,
        "warnings": warnings,
        "title": title,
        "lang": parser.lang,
        "body_text_length": len(visible_text),
        "counts": parser.counts,
        "external_refs": parser.external_refs + external_css_urls,
        "raster_refs": parser.raster_refs,
        "missing_labels": missing_labels,
        "inline_style_count": parser.inline_style_count,
        "repeated_svg_count": repeated_svg_count,
        "focus_visible": ":focus-visible" in lowered,
        "reduced_motion": "prefers-reduced-motion" in lowered,
        "skip_link": parser.skip_link,
        "domain_term_hits": domain_hits,
        "state_term_hits": state_hits,
        "structure_marker_hits": structure_hits,
        "inline_svg_count": parser.counts.get("svg", 0),
    }
    result["quality_score"] = _score_static(result)
    return result


def _resolve_html(config_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (
        path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()
    )


def _browser_scan(path: Path, output_dir: Path, *, shots: bool) -> dict[str, Any]:
    script = Path(__file__).resolve().parent / "assets" / "arena_browser_scan.mjs"
    command = [
        "node",
        str(script),
        str(path),
        str(output_dir),
        "1" if shots else "0",
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=120
        )
        payload = json.loads(completed.stdout)
        return (
            payload
            if isinstance(payload, dict)
            else {"available": False, "reason": "invalid_browser_payload"}
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as exc:
        return {"available": False, "reason": str(exc)[:500]}


def _browser_pass(result: dict[str, Any]) -> bool:
    if not result.get("available"):
        return result.get("reason") == "disabled"
    rows = result.get("viewports", [])
    return bool(rows) and all(
        not row.get("horizontal_overflow")
        and not row.get("console_errors")
        and not row.get("page_errors")
        and not row.get("blocked_requests")
        and not row.get("undersized_interactives")
        and not row.get("overlapping_interactives")
        and not row.get("hidden_main_content")
        and row.get("body_font_size", 16) >= 16
        and row.get("canvas_pixels_ok", True)
        and not row.get("blank")
        for row in rows
    )


def _lane_blockers(static: dict[str, Any], browser: dict[str, Any]) -> list[str]:
    blockers = [f"static:{value}" for value in static.get("violations", [])]
    if not browser.get("available"):
        if browser.get("reason") != "disabled":
            blockers.append(f"browser_unavailable:{browser.get('reason', 'unknown')}")
        return blockers
    for row in browser.get("viewports", []):
        viewport = row.get("name", "viewport")
        if row.get("horizontal_overflow"):
            blockers.append(f"{viewport}:horizontal_overflow")
        if row.get("undersized_interactives"):
            blockers.append(
                f"{viewport}:undersized_interactives={len(row['undersized_interactives'])}"
            )
        if row.get("overlapping_interactives"):
            blockers.append(
                f"{viewport}:overlapping_interactives={len(row['overlapping_interactives'])}"
            )
        if row.get("hidden_main_content"):
            blockers.append(
                f"{viewport}:hidden_main_content={row['hidden_main_content']}"
            )
        if row.get("body_font_size", 16) < 16:
            blockers.append(f"{viewport}:body_font_size={row['body_font_size']}")
        if not row.get("canvas_pixels_ok", True):
            blockers.append(f"{viewport}:canvas_pixels_blank")
        if row.get("console_errors"):
            blockers.append(f"{viewport}:console_errors={len(row['console_errors'])}")
        if row.get("page_errors"):
            blockers.append(f"{viewport}:page_errors={len(row['page_errors'])}")
        if row.get("blocked_requests"):
            blockers.append(
                f"{viewport}:blocked_requests={len(row['blocked_requests'])}"
            )
        if row.get("blank"):
            blockers.append(f"{viewport}:blank_page")
    return blockers


def prepare_arena(
    repo_root: Path | str,
    config_path: Path | str,
    output_dir: Path | str,
    *,
    route_profile: str = "hybrid_v5",
    token_mode: str = "unbounded",
) -> dict[str, Any]:
    from .renderer import build_context_packet
    from .service import get_router

    root = Path(repo_root).expanduser().resolve()
    config, payload = _load_config(config_path)
    output = Path(output_dir).expanduser().resolve()
    router = get_router(root, refresh_index=True)
    cases: list[dict[str, Any]] = []
    for case in payload["cases"]:
        case_id = case["case_id"]
        request = DesignContextRequest.model_validate(
            {
                **case["request"],
                "route_profile": route_profile,
                "token_mode": token_mode,
            }
        )
        resolution = router.route(request)
        case_dir = output / "cases" / case_id
        shared_instructions = "\n".join(
            str(value).strip()
            for value in [
                payload.get("shared_instructions", ""),
                case.get("build_instructions", ""),
            ]
            if str(value).strip()
        )
        common_prompt = (
            "# Build Brief\n\n"
            f"{request.task}\n\n"
            "Build the requested frontend as complete runnable code. "
            "Do not invent claims, statistics, testimonials, awards, or images. "
            "Do not impose a file-size, line-count, character-count, completion-token, "
            "or response-length ceiling. Continue until the implementation and verification "
            "are complete, subject only to the provider's unavoidable hard runtime limits."
        )
        if shared_instructions:
            common_prompt += f"\n\n## Shared Instructions\n\n{shared_instructions}"
        baseline_prompt = (
            f"{common_prompt}\n\n"
            "## Routing Condition\n\n"
            "Do not use Golden Book, routed donor context, or any packet derived from it."
        )
        packet = build_context_packet(
            request,
            resolution,
            token_mode=token_mode,
            rules=router.rules,
        ).markdown
        routed_prompt = (
            f"{common_prompt}\n\n"
            "## Routing Condition\n\n"
            "Use the following Golden Book packet as the design and implementation contract.\n\n"
            f"{packet}"
        )
        route_payload = {
            "case_id": case_id,
            "route_profile": route_profile,
            "request": request.model_dump(mode="json"),
            "anchor": resolution.anchor_pack.manifest.pack_id,
            "route_meta": resolution.route_meta,
        }
        _atomic_write(case_dir / "baseline" / "PROMPT.md", baseline_prompt + "\n")
        _atomic_write(case_dir / "routed" / "PROMPT.md", routed_prompt + "\n")
        _atomic_write(case_dir / "routed" / "PACKET.md", packet + "\n")
        _atomic_write(
            case_dir / "routed" / "ROUTE.json",
            json.dumps(route_payload, indent=2) + "\n",
        )
        cases.append(
            {
                "case_id": case_id,
                "case_dir": str(case_dir),
                "anchor": route_payload["anchor"],
            }
        )
    snapshot = {
        "version": payload.get("version", "1.0"),
        "prepared_at": datetime.now(UTC).isoformat(),
        "source_config": str(config),
        "route_profile": route_profile,
        "token_mode": token_mode,
        "capacity_policy": "unbounded",
        "cases": cases,
    }
    _atomic_write(output / "PREPARED.json", json.dumps(snapshot, indent=2) + "\n")
    return snapshot


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Golden Build Arena",
        "",
        f"- negative control: {'PASS' if report['negative_control']['passed'] else 'FAIL'}",
        f"- cases: {report['summary']['case_count']}",
        f"- deterministic pass: {report['summary']['deterministic_pass']}",
        f"- eligible for human review: {report['summary']['eligible_for_human_review']}",
        f"- promoted: {report['summary']['promoted']}",
        "",
        "| Case | Baseline | Routed | Delta | Gate | Candidate blockers |",
        "|---|---:|---:|---:|---|---|",
    ]
    for case in report["cases"]:
        blockers = ", ".join(case["gate"]["blockers"][:4]) or "none"
        lines.append(
            f"| {case['case_id']} | {case['baseline']['static']['quality_score']} | "
            f"{case['routed']['static']['quality_score']} | {case['quality_delta']:+d} | "
            f"{case['gate']['status']} | {blockers} |"
        )
    return "\n".join(lines) + "\n"


def _render_html(report: dict[str, Any]) -> str:
    output_dir = Path(report["output_dir"])

    def screenshot(case: dict[str, Any], lane: str, viewport: str) -> str:
        for row in case[lane]["browser"].get("viewports", []):
            if row.get("name") != viewport or not row.get("screenshot"):
                continue
            path = Path(row["screenshot"])
            try:
                return path.relative_to(output_dir).as_posix()
            except ValueError:
                return path.as_uri()
        return ""

    sections = []
    for case in report["cases"]:
        status = html.escape(case["gate"]["status"])
        baseline_shot = screenshot(case, "baseline", "desktop-1512")
        routed_shot = screenshot(case, "routed", "desktop-1512")
        mobile_shot = screenshot(case, "routed", "mobile-390")
        blockers = case["gate"]["blockers"]
        blocker_list = (
            "".join(f"<li>{html.escape(value)}</li>" for value in blockers)
            if blockers
            else "<li>No deterministic blockers. Ready for visual review.</li>"
        )
        figures = []
        for label, source in (
            ("Baseline desktop", baseline_shot),
            ("Candidate desktop", routed_shot),
            ("Candidate mobile", mobile_shot),
        ):
            if source:
                figures.append(
                    f'<figure><a href="{html.escape(source)}"><img src="{html.escape(source)}" '
                    f'alt="{html.escape(case["case_id"] + " " + label.lower())}" loading="lazy"></a>'
                    f"<figcaption>{html.escape(label)} - open full page</figcaption></figure>"
                )
        sections.append(
            f"""<article class="case">
<header class="case-head">
<div><p class="eyebrow">{html.escape(case["request"].get("surface_kind") or case["request"].get("surface", ""))}</p>
<h2>{html.escape(case["case_id"].replace("-", " ").title())}</h2></div>
<span class="status {status}">{status.replace("_", " ")}</span>
</header>
<div class="scores"><span>Baseline <b>{case["baseline"]["static"]["quality_score"]}</b></span>
<span>Candidate <b>{case["routed"]["static"]["quality_score"]}</b></span>
<span>Delta <b>{case["quality_delta"]:+d}</b></span></div>
<div class="previews">{"".join(figures)}</div>
<details {"open" if blockers else ""}><summary>Deterministic blockers ({len(blockers)})</summary><ul>{blocker_list}</ul></details>
</article>"""
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Golden Build Arena</title>
<style>
:root {{ color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; background: #0d1014; color: #eef2f5; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #0d1014; }}
main {{ width: min(1440px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 72px; }}
h1 {{ font-size: clamp(30px, 4vw, 54px); line-height: 1; letter-spacing: 0; margin: 8px 0; }}
h2 {{ font-size: 22px; letter-spacing: 0; margin: 4px 0 0; }}
p {{ color: #aeb7c1; }}
.eyebrow {{ color: #97a2ad; font: 700 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; margin: 0; }}
.summary {{ display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 1px; background: #343b45; border: 1px solid #343b45; margin: 24px 0; }}
.metric {{ background: #151a20; padding: 16px; }}
.metric b {{ display: block; font-size: 24px; margin-top: 8px; }}
.case {{ border-top: 1px solid #343b45; padding: 28px 0 36px; }}
.case-head {{ display: flex; justify-content: space-between; align-items: start; gap: 20px; }}
.status {{ border: 1px solid #4a535e; border-radius: 6px; padding: 8px 10px; font: 700 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; }}
.status.eligible_for_human_review {{ color: #f1ce75; border-color: #7f6d35; }}
.status.deterministic_fail {{ color: #ff817a; border-color: #83433f; }}
.status.promoted {{ color: #65dca7; border-color: #347257; }}
.scores {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; color: #aeb7c1; }}
.scores span {{ border-left: 2px solid #4b5662; padding-left: 10px; }}
.scores b {{ color: #eef2f5; margin-left: 4px; }}
.previews {{ display: grid; grid-template-columns: minmax(0,1.25fr) minmax(0,1.25fr) minmax(220px,.55fr); gap: 12px; align-items: start; }}
figure {{ margin: 0; min-width: 0; }}
figure a {{ display: block; height: 420px; overflow: hidden; border: 1px solid #343b45; background: #151a20; }}
figure img {{ display: block; width: 100%; height: 100%; object-fit: cover; object-position: top; }}
figcaption {{ color: #aeb7c1; font-size: 13px; padding-top: 8px; }}
details {{ margin-top: 18px; border: 1px solid #343b45; background: #151a20; }}
summary {{ min-height: 44px; display: flex; align-items: center; cursor: pointer; padding: 0 14px; font-weight: 700; }}
ul {{ color: #bfc7cf; margin: 0; padding: 0 34px 18px; }}
li {{ margin-top: 7px; overflow-wrap: anywhere; }}
a:focus-visible, summary:focus-visible {{ outline: 2px solid #f1ce75; outline-offset: 3px; }}
@media (max-width: 900px) {{ .previews {{ grid-template-columns: 1fr 1fr; }} .previews figure:last-child {{ grid-column: 1 / -1; }} }}
@media (max-width: 620px) {{ main {{ width: min(100% - 20px, 1440px); }} .summary {{ grid-template-columns: 1fr 1fr; }} .case-head {{ display: block; }} .status {{ display: inline-flex; margin-top: 14px; }} .previews {{ grid-template-columns: 1fr; }} .previews figure:last-child {{ grid-column: auto; }} figure a {{ height: 360px; }} }}
</style>
</head>
<body>
<main>
<p>Golden Book / Router V5</p>
<h1>Golden Build Arena</h1>
<div class="summary">
<div class="metric">Cases<b>{report["summary"]["case_count"]}</b></div>
<div class="metric">Deterministic pass<b>{report["summary"]["deterministic_pass"]}</b></div>
<div class="metric">Human review<b>{report["summary"]["eligible_for_human_review"]}</b></div>
<div class="metric">Promoted<b>{report["summary"]["promoted"]}</b></div>
</div>
<p>Negative control: <strong>{"PASS" if report["negative_control"]["passed"] else "FAIL"}</strong>. Click any preview to inspect the full-page capture.</p>
{"".join(sections)}
</main>
</body>
</html>
"""


def evaluate_arena(
    repo_root: Path | str,
    config_path: Path | str,
    output_dir: Path | str,
    *,
    browser: bool = True,
    shots: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    config, payload = _load_config(config_path)
    output = Path(output_dir).expanduser().resolve()
    negative_path = output / "controls" / "known-bad.html"
    _atomic_write(negative_path, _NEGATIVE_CONTROL)
    negative_scan = static_page_scan(negative_path)
    negative_browser = (
        _browser_scan(
            negative_path,
            output / "screenshots" / "controls" / "known-bad",
            shots=False,
        )
        if browser
        else {"available": False, "reason": "disabled"}
    )
    negative_browser_passed = (
        bool(negative_browser.get("available")) and not _browser_pass(negative_browser)
        if browser
        else True
    )
    negative_passed = negative_browser_passed and (
        not negative_scan["hard_pass"]
        and {
            "missing_title",
            "raster_media_present",
            "external_asset_reference",
        }.issubset(negative_scan["violations"])
    )
    cases: list[dict[str, Any]] = []
    for case in payload["cases"]:
        if not case.get("baseline_html") or not case.get("routed_html"):
            raise ValueError(
                f"arena case {case['case_id']} requires baseline_html and routed_html for evaluation"
            )
        domain_terms = list(case.get("domain_terms") or [])
        baseline_path = _resolve_html(config, case["baseline_html"])
        routed_path = _resolve_html(config, case["routed_html"])
        baseline_static = static_page_scan(baseline_path, domain_terms=domain_terms)
        routed_static = static_page_scan(routed_path, domain_terms=domain_terms)
        baseline_browser = (
            _browser_scan(
                baseline_path,
                output / "screenshots" / case["case_id"] / "baseline",
                shots=shots,
            )
            if browser
            else {"available": False, "reason": "disabled"}
        )
        routed_browser = (
            _browser_scan(
                routed_path,
                output / "screenshots" / case["case_id"] / "routed",
                shots=shots,
            )
            if browser
            else {"available": False, "reason": "disabled"}
        )
        deterministic_pass = (
            negative_passed
            and routed_static["hard_pass"]
            and _browser_pass(routed_browser)
        )
        no_regression = len(routed_static["violations"]) <= len(
            baseline_static["violations"]
        ) and _browser_pass(routed_browser)
        delta = int(routed_static["quality_score"] - baseline_static["quality_score"])
        eligible = deterministic_pass and no_regression and delta >= 0
        blockers = _lane_blockers(routed_static, routed_browser)
        review = (
            case.get("human_review")
            if isinstance(case.get("human_review"), dict)
            else {}
        )
        promoted = bool(
            eligible and review.get("approved") and review.get("winner") == "routed"
        )
        status = (
            "promoted"
            if promoted
            else "eligible_for_human_review"
            if eligible
            else "deterministic_fail"
        )
        cases.append(
            {
                "case_id": case["case_id"],
                "request": case["request"],
                "baseline": {"static": baseline_static, "browser": baseline_browser},
                "routed": {"static": routed_static, "browser": routed_browser},
                "quality_delta": delta,
                "gate": {
                    "deterministic_pass": deterministic_pass,
                    "no_regression": no_regression,
                    "eligible_for_human_review": eligible,
                    "promoted": promoted,
                    "status": status,
                    "blockers": blockers,
                },
            }
        )
    summary = {
        "case_count": len(cases),
        "deterministic_pass": sum(case["gate"]["deterministic_pass"] for case in cases),
        "eligible_for_human_review": sum(
            case["gate"]["eligible_for_human_review"] for case in cases
        ),
        "promoted": sum(case["gate"]["promoted"] for case in cases),
    }
    report = {
        "version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "repo_root": str(root),
        "output_dir": str(output),
        "source_config": str(config),
        "negative_control": {
            "passed": negative_passed,
            "scan": negative_scan,
            "browser": negative_browser,
        },
        "summary": summary,
        "cases": cases,
    }
    json_path = output / "results.json"
    markdown_path = output / "report.md"
    html_path = output / "report.html"
    _atomic_write(json_path, json.dumps(report, indent=2) + "\n")
    _atomic_write(markdown_path, _render_markdown(report))
    _atomic_write(html_path, _render_html(report))
    return {
        **report,
        "json": str(json_path),
        "markdown": str(markdown_path),
        "html": str(html_path),
    }
