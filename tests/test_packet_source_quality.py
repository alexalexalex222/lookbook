from pathlib import Path

import pytest

from design_router_mcp.rules import load_routing_rules
from design_router_mcp.sanitizer import sanitize_source_text, strip_external_dependencies
from design_router_mcp.service import (
    export_opencode_bundle,
    get_source_excerpt,
    resolve_design_context,
)


ROOT = Path(__file__).resolve().parents[1]

CASES = [
    (
        "martial-arts",
        "website",
        "landing",
        "Build a serious professional martial arts academy website for adult beginners, "
        "intermediate students, and active fighters. Include striking, grappling, "
        "fundamentals, and fight-team pathways; a usable class schedule; coach-role "
        "profiles with labeled placeholders rather than invented biographies; first-visit "
        "guidance; facility and equipment context; a trial-class inquiry flow; FAQ; and "
        "mobile navigation.",
        "iron_circuit_fight_academy_black_copper_v1",
        ["foundation_design_tokens_v1"],
        ["emberforge", "::calendar::", "holland_dirt", "velvet_fig"],
    ),
    (
        "plumber",
        "website",
        "landing",
        "Build a residential plumbing company website with a clear emergency-versus-"
        "scheduled service split, symptom-based diagnostics, repair and installation "
        "categories, water and pressure system context, service-area qualification, "
        "maintenance guidance, and an estimate request form.",
        "clear_ridge_water_works_field_blue_v1",
        ["foundation_design_tokens_v1"],
        ["stillwater", "ashgrove", "::file-manager::", "::calendar::"],
    ),
    (
        "arcade-racer",
        "game",
        "game",
        "Build a polished playable top-down arcade racer with steering, acceleration, "
        "braking, track boundaries, checkpoints, laps, timer, speed display, pause, "
        "restart, victory state, keyboard controls, and touch controls.",
        "neon_apex_arcade_racer_v1",
        [],
        ["::breakout::", "::boids::", "pricing_tiers_v1", "faq_accordion_v1"],
    ),
    (
        "dungeon-tactics",
        "game",
        "game",
        "Build a polished playable turn-based dungeon tactics game with a stable grid map, "
        "player movement, walls, deterministic enemies, attack range, health, exit "
        "objective, turn counter, event log, restart, keyboard controls, and touch controls.",
        "ashvault_dungeon_tactics_v1",
        [],
        ["::tower-defense::", "::solitaire::", "::chess::", "::sudoku::", "card_service_v1"],
    ),
]


@pytest.mark.parametrize(
    "case_id,surface,surface_kind,task,anchor,shared_atoms,blocked_markers",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_complete_anchors_withhold_redundant_or_conflicting_sources(
    case_id,
    surface,
    surface_kind,
    task,
    anchor,
    shared_atoms,
    blocked_markers,
):
    packet = resolve_design_context(
        ROOT,
        surface=surface,
        surface_kind=surface_kind,
        task=task,
        stack="html-css-js",
        constraints=[
            "single-file index.html",
            "no external dependencies",
            "responsive at 360px and 1512px",
        ],
        token_mode="expanded",
        route_profile="hybrid_v5",
        rerank_mode="off",
        code_profile="code_first",
        packet_intent="design_director",
        optional_pattern_count=12,
    )
    source = packet.metadata["source_selection"]

    assert packet.selected_files[0] == anchor
    assert source["anchor_self_sufficient"] is True
    assert source["support_examples"] == []
    assert source["shared_atoms"] == shared_atoms
    assert source["optional_patterns"] == []
    assert not any(marker in packet.markdown.lower() for marker in blocked_markers)
    assert "alt anchor:" not in packet.markdown
    assert "fonts.googleapis" not in packet.markdown
    assert "fonts.gstatic" not in packet.markdown
    assert "each component loads its own web fonts" not in packet.markdown.lower()
    assert "[URL]" not in packet.markdown


def test_external_dependency_stripper_preserves_inline_code():
    source = """
    <!-- REQUIRED font load. Copy them into <head>. -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="[URL]" rel="stylesheet">
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter');
      @font-face { font-family: X; src: url([URL]); }
      .surface { background: url([URL]); }
    </style>
    <script src="https://cdn.example.com/app.js"></script>
    <div class="surface">Keep me</div>
    """

    cleaned = strip_external_dependencies(source)

    assert "Keep me" in cleaned
    assert "https://" not in cleaned
    assert "[URL]" not in cleaned
    assert "@import" not in cleaned
    assert "@font-face" not in cleaned


def test_export_bundle_preserves_request_constraints(tmp_path):
    export_opencode_bundle(
        ROOT,
        surface="website",
        surface_kind="landing",
        task=CASES[0][3],
        output_dir=tmp_path,
        token_mode="expanded",
        stack="html-css-js",
        constraints=["single-file index.html", "no external dependencies"],
        route_profile="hybrid_v5",
        rerank_mode="off",
        code_profile="code_first",
        packet_intent="design_director",
    )

    packet = (tmp_path / "PACKET.md").read_text(encoding="utf-8")
    source_excerpt = next((tmp_path / "SOURCE_EXCERPTS").glob("*.md")).read_text(
        encoding="utf-8"
    )
    capacity = (tmp_path / "PACKET_CAPACITY.md").read_text(encoding="utf-8")
    assert "fonts.googleapis" not in packet
    assert "fonts.gstatic" not in packet
    assert "emberforge" not in packet.lower()
    assert "## Full File" in source_excerpt
    assert "capacity_policy: `unbounded`" in source_excerpt
    assert "truncated" not in source_excerpt.lower()
    assert "fonts.googleapis" not in source_excerpt
    assert "fonts.gstatic" not in source_excerpt
    assert "capacity_policy: unbounded" in capacity
    assert "trimming: disabled" in capacity


def test_packet_capacity_is_unbounded_even_in_compact_mode():
    packet = resolve_design_context(
        ROOT,
        surface="website",
        surface_kind="landing",
        task=CASES[0][3],
        stack="html-css-js",
        constraints=["single-file index.html", "no external dependencies"],
        token_mode="compact",
        route_profile="hybrid_v5",
        rerank_mode="off",
        code_profile="code_first",
        packet_intent="design_director",
    )

    assert packet.metadata["capacity_policy"] == "unbounded"
    assert "# Full Anchor Build" in packet.markdown
    assert "PACKET TRUNCATED" not in packet.markdown
    assert "... [truncated]" not in packet.markdown
    assert "/* truncated */" not in packet.markdown
    assert "<!-- truncated -->" not in packet.markdown
    assert "- budget:" not in packet.markdown


def test_targeted_source_pull_ignores_legacy_character_ceiling():
    pack_id = CASES[0][4]
    source_path = (
        ROOT
        / "goldensets"
        / "website"
        / pack_id
        / "source_snapshot"
        / "index.html"
    )
    expected = sanitize_source_text(
        source_path.read_text(encoding="utf-8", errors="replace")
    )
    deep_chunk = expected[len(expected) // 2 : len(expected) // 2 + 180]

    excerpt = get_source_excerpt(
        ROOT,
        pack_id=pack_id,
        token_mode="compact",
        max_chars=32,
        include_full=True,
    )

    assert "## Full File" in excerpt
    assert deep_chunk in excerpt
    assert "truncated" not in excerpt.lower()


def test_default_rules_expose_unbounded_capacity_policy():
    rules = load_routing_rules(ROOT)

    for mode, budget in rules.token_modes.items():
        if mode == "library_audit":
            continue
        assert budget.max_packet_tokens is None
        assert budget.max_snippets is None
        assert budget.max_examples is None
        assert budget.full_code_allowed is True
