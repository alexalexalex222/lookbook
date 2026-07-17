"""Regression tests for the 2026-07-09/10 router upgrades.

Three features, each proven live before these tests were written:
  1. Multi-pattern routing — runner-up anchors ride in route_meta["anchor_alternatives"]
     and render in the Selected Route section with borrow-don't-blend discipline.
  2. Full-build mode — token_mode=full_selected + full_code_mode=True embeds the COMPLETE
     anchor source in a required "Full Anchor Build" section (stale sibling css skipped
     when the primary html is self-contained).
  3. Mobile-First Gates — a required strict-quality section in normal modes, absent in micro.

These guard behavior (packet contents / route_meta shape), not implementation details.
"""
from pathlib import Path

import pytest

from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import get_router, resolve_design_packet

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "goldensets" / "website").is_dir(),
    reason=f"goldensets/website not present at {REPO_ROOT}",
)

MMA_REQ = {
    "surface": "website.martial_arts_gym",
    "task": "martial arts academy homepage with instructor bio and trial class call to action",
    "tone": ["disciplined", "strong"],
    "layout_mode": "homepage",
}


def _route(**overrides):
    req = DesignContextRequest(**{**MMA_REQ, **overrides})
    return get_router(REPO_ROOT).route(req), req


# ── 1. multi-pattern routing ──────────────────────────────────────────────────

def test_anchor_alternatives_in_route_meta():
    resolution, _ = _route()
    alts = resolution.route_meta.get("anchor_alternatives")
    assert isinstance(alts, list) and alts, "route_meta must carry anchor_alternatives"
    assert len(alts) <= 3
    selected = resolution.anchor_pack.manifest.pack_id
    for alt in alts:
        assert alt["pack_id"] != selected, "an alternative may never be the selected anchor"
        assert alt["score"] > 0, "zero-score anchors are noise, not alternatives"
        assert alt["motif_tags"], "alternatives must carry motifs (that's what gets borrowed)"


def test_alternatives_are_rank_ordered_runners_up():
    resolution, _ = _route()
    alts = resolution.route_meta["anchor_alternatives"]
    scores = [alt["score"] for alt in alts]
    assert scores == sorted(scores, reverse=True), "alternatives must be rank-ordered"
    assert resolution.anchor_score.total >= scores[0], "no alternative may outscore the winner"


def test_alternatives_render_in_packet_with_borrow_discipline():
    md = resolve_design_packet(MMA_REQ, REPO_ROOT)
    assert "pattern alternatives" in md, "Selected Route must surface the alternatives block"
    assert md.count("alt anchor:") >= 1
    assert "never blend two identities" in md, "the borrow-don't-blend clause is load-bearing"


# ── 2. full-build mode ────────────────────────────────────────────────────────

def test_full_build_packet_carries_complete_anchor_source():
    md = resolve_design_packet(
        {**MMA_REQ, "token_mode": "full_selected", "full_code_mode": True}, REPO_ROOT
    )
    assert "# Full Anchor Build" in md
    assert "PACKET TRUNCATED" not in md
    # the embedded source must be the real, complete file — check a deep tail chunk
    resolution, _ = _route(token_mode="full_selected", full_code_mode=True)
    files = resolution.route_meta.get("anchor_full_source")
    assert files, "full mode must populate anchor_full_source"
    primary = next(f for f in files if f["path"].endswith(".html"))
    src = (REPO_ROOT / "goldensets" / "website" / resolution.anchor_pack.manifest.pack_id / primary["path"])
    text = src.read_text(encoding="utf-8", errors="replace")
    assert primary["chars"] == len(text), "embedded source must be byte-complete, not clipped"
    deep_chunk = text[len(text) // 2 : len(text) // 2 + 120]  # a slice from the MIDDLE of the file
    assert deep_chunk in md, "the middle of the anchor source must appear verbatim in the packet"


def test_full_build_skips_stale_sibling_css_when_html_self_contained():
    resolution, _ = _route(token_mode="full_selected", full_code_mode=True)
    files = resolution.route_meta["anchor_full_source"]
    primary = next(f["path"] for f in files if f["path"].endswith(".html"))
    html = (
        REPO_ROOT / "goldensets" / "website" / resolution.anchor_pack.manifest.pack_id / primary
    ).read_text(encoding="utf-8", errors="replace")
    if "<style" in html and 'rel="stylesheet"' not in html:
        assert all(f["path"].endswith(".html") for f in files), (
            "self-contained html must not drag stale sibling stylesheets into the packet"
        )


def test_compact_mode_never_embeds_full_source():
    # Peek mode only: explicit compact + full_code off must not load full sources.
    peek = {"token_mode": "compact", "full_code_mode": False, "code_profile": "balanced"}
    md = resolve_design_packet({**MMA_REQ, **peek}, REPO_ROOT)
    assert "# Full Anchor Build" not in md
    resolution, _ = _route(**peek)
    assert not resolution.route_meta.get("anchor_full_source"), (
        "compact-mode routes must not pay the cost of reading full sources"
    )


def test_default_resolve_is_one_call_full_depth():
    """Builder defaults ship complete primary pattern — no second tool hop."""
    md = resolve_design_packet(MMA_REQ, REPO_ROOT)
    assert "# Full Anchor Build" in md
    assert "BUILD NOW" in md
    assert "Do NOT call resolve_design_context again" in md
    # No ready-to-run tool recipes (prohibition text may still name the tool).
    assert "get_source_excerpt(pack_id=" not in md
    assert "rerun `resolve_design_context`" not in md.lower()
    assert "PACKET TRUNCATED" not in md
    resolution, _ = _route()
    assert resolution.route_meta.get("anchor_full_source"), (
        "default route must load full primary pattern for one-call builds"
    )


# ── 3. mobile-first gates ─────────────────────────────────────────────────────

def test_mobile_first_gates_present_in_normal_modes():
    for mode in (None, "standard", "full_selected"):
        payload = {**MMA_REQ}
        if mode:
            payload["token_mode"] = mode
            payload["full_code_mode"] = mode != "compact"
        md = resolve_design_packet(payload, REPO_ROOT)
        assert "# Mobile-First Gates" in md, f"gates missing in mode={mode or 'default'}"
        assert "not a collapsed desktop" in md
        assert "44x44px" in md


def test_mobile_first_gates_absent_in_micro():
    md = resolve_design_packet({**MMA_REQ, "token_mode": "micro"}, REPO_ROOT)
    assert "# Mobile-First Gates" not in md, "micro packets must stay lean"
