import json
from pathlib import Path

import pytest

from design_router_mcp.arena import evaluate_arena, prepare_arena, static_page_scan
from design_router_mcp.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]


GOOD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prepared interface</title>
<style>
:root { --bg: #fff; --ink: #151515; }
*:focus-visible { outline: 2px solid #125bd8; outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto; } }
</style>
</head>
<body>
<a href="#main">Skip to content</a>
<header><nav aria-label="Primary"><a href="#main">Home</a></nav></header>
<main id="main"><h1>Incident queue</h1><section><h2>Owned signals</h2><button type="button">Claim signal</button></section></main>
</body>
</html>
"""

BAD_PAGE = """<!doctype html>
<html><head><style>.wide { width: 3000px; }</style></head>
<body><div class="wide"><img src="https://example.com/fake.jpg"><h2>Best product ever</h2></div></body></html>
"""


def test_static_scan_distinguishes_good_page_from_known_bad_control(tmp_path):
    good = tmp_path / "good.html"
    bad = tmp_path / "bad.html"
    good.write_text(GOOD_PAGE, encoding="utf-8")
    bad.write_text(BAD_PAGE, encoding="utf-8")

    good_result = static_page_scan(good, domain_terms=["incident", "signal"])
    bad_result = static_page_scan(bad)

    assert good_result["hard_pass"] is True
    assert bad_result["hard_pass"] is False
    assert bad_result["violations"]


def test_prepare_arena_writes_baseline_prompt_and_routed_packet(tmp_path):
    config = tmp_path / "arena.json"
    config.write_text(
        json.dumps(
            {
                "version": "1.0",
                "cases": [
                    {
                        "case_id": "settings",
                        "request": {
                            "surface": "app",
                            "task": "Build account settings with privacy and security controls.",
                        },
                        "domain_terms": ["privacy", "security"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = prepare_arena(ROOT, config, tmp_path / "run", route_profile="hybrid_v5")
    case_dir = Path(result["cases"][0]["case_dir"])

    assert (case_dir / "baseline" / "PROMPT.md").is_file()
    assert (case_dir / "routed" / "PROMPT.md").is_file()
    assert (case_dir / "routed" / "PACKET.md").is_file()
    assert result["capacity_policy"] == "unbounded"
    assert "PACKET TRUNCATED" not in (
        case_dir / "routed" / "PACKET.md"
    ).read_text(encoding="utf-8")
    assert "hybrid_v5" in (case_dir / "routed" / "ROUTE.json").read_text(
        encoding="utf-8"
    )


def test_prepare_arena_rejects_application_level_output_caps(tmp_path):
    config = tmp_path / "arena.json"
    config.write_text(
        json.dumps(
            {
                "version": "1.0",
                "shared_instructions": "Keep index.html at or under 60000 bytes.",
                "cases": [
                    {
                        "case_id": "settings",
                        "request": {
                            "surface": "app",
                            "task": "Build account settings.",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="output capacity limits are disabled"):
        prepare_arena(ROOT, config, tmp_path / "run")


def test_arena_evaluation_requires_negative_control_and_writes_reports(tmp_path):
    baseline = tmp_path / "baseline.html"
    routed = tmp_path / "routed.html"
    baseline.write_text(BAD_PAGE, encoding="utf-8")
    routed.write_text(GOOD_PAGE, encoding="utf-8")
    config = tmp_path / "arena.json"
    config.write_text(
        json.dumps(
            {
                "version": "1.0",
                "cases": [
                    {
                        "case_id": "incident",
                        "request": {
                            "surface": "app",
                            "task": "Build an incident queue.",
                        },
                        "domain_terms": ["incident", "signal"],
                        "baseline_html": str(baseline),
                        "routed_html": str(routed),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_arena(ROOT, config, tmp_path / "report", browser=False)

    assert result["negative_control"]["passed"] is True
    assert result["summary"]["eligible_for_human_review"] == 1
    assert result["summary"]["promoted"] == 0
    assert Path(result["json"]).is_file()
    assert Path(result["markdown"]).is_file()
    assert Path(result["html"]).is_file()
    assert result["cases"][0]["gate"]["blockers"] == []


def test_cli_exposes_arena_prepare_phase():
    args = build_parser().parse_args(
        [
            "arena",
            "--config",
            "arena.json",
            "--phase",
            "prepare",
        ]
    )

    assert args.command == "arena"
    assert args.phase == "prepare"
    assert args.route_profile == "hybrid_v5"
