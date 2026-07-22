import json
from pathlib import Path

import pytest
from design_router_mcp.lazy_loader import _trim_balanced_markup
from design_router_mcp.renderer import _safe_css_excerpt
from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import (
    export_opencode_bundle,
    get_pattern_card,
    get_router,
    resolve_design_context,
)


ROOT = Path(__file__).resolve().parents[1]

CASES = [
    (
        "martial-arts",
        "website.homepage",
        "landing",
        "Build a serious martial arts academy website with striking, grappling and fundamentals programs, "
        "class schedule, instructor profiles, trial-class inquiry, and mobile navigation.",
    ),
    (
        "plumber",
        "website.homepage",
        "landing",
        "Build a trustworthy local plumbing website with emergency service, drain clearing, water heater repair, "
        "service areas, proof, process, phone-first contact, and estimate request.",
    ),
    (
        "arcade-racer",
        "game",
        "game",
        "Build a neon arcade racing game interface with speedometer HUD, lap position, rival roster, track selection, "
        "garage upgrades, pause overlay, and responsive controls.",
    ),
    (
        "dungeon-tactics",
        "game",
        "game",
        "Build a tactical dungeon crawler game interface with party HUD, turn order, inventory, skill actions, map, "
        "combat log, reward modal, and responsive controls.",
    ),
]

FOREIGN_MARKERS = {
    "martial-arts": (
        "plumb",
        "roof",
        "moving",
        "dental",
        "racer",
        "roguelike",
        "browser-os",
        "file-manager",
        "markets-terminal",
        "orbital-launch",
        "reference-product",
        "luxury-maison",
        "instrument-studio",
        "developer-docs",
    ),
    "plumber": (
        "fight",
        "martial",
        "roof",
        "moving",
        "dental",
        "racer",
        "roguelike",
        "browser-os",
        "file-manager",
        "markets-terminal",
        "orbital-launch",
        "reference-product",
        "luxury-maison",
        "instrument-studio",
        "developer-docs",
    ),
    "arcade-racer": (
        "plumb",
        "roof",
        "moving",
        "dental",
        "browser-os",
        "db-browser",
        "reference-product",
        "orbital-launch",
        "roguelike",
        "::chess::",
        "tower-defense",
        "solitaire",
        "sudoku",
    ),
    "dungeon-tactics": (
        "plumb",
        "roof",
        "moving",
        "dental",
        "browser-os",
        "db-browser",
        "reference-product",
        "orbital-launch",
        "::racer::",
        "::boids::",
        "::breakout::",
        "physics-sandbox",
    ),
}


@pytest.fixture(scope="module")
def router():
    return get_router(ROOT, refresh_index=True)


def _request(surface: str, surface_kind: str, task: str, **updates) -> DesignContextRequest:
    return DesignContextRequest(
        surface=surface,
        surface_kind=surface_kind,
        task=task,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
        **updates,
    )


def test_request_accepts_pattern_counts_above_the_legacy_ceiling():
    request = DesignContextRequest(
        surface="website.homepage",
        task="Build a service website.",
        optional_pattern_count=12,
    )

    assert request.optional_pattern_count == 12
    expanded = DesignContextRequest(
        surface="website.homepage",
        task="Build a service website.",
        optional_pattern_count=40,
    )
    assert expanded.optional_pattern_count == 40


@pytest.mark.parametrize("case_id,surface,surface_kind,task", CASES, ids=[case[0] for case in CASES])
def test_routes_emit_qualified_pattern_cards_without_foreign_domains(
    router,
    case_id,
    surface,
    surface_kind,
    task,
):
    resolution = router.route(_request(surface, surface_kind, task))
    patterns = resolution.optional_patterns
    catalog = resolution.optional_pattern_catalog
    meta = resolution.route_meta["optional_pattern_pool"]

    assert meta["selected_count"] == len(patterns)
    assert meta["catalog_count"] == len(catalog)
    assert len(resolution.optional_pattern_candidates) == len(catalog)
    assert "optional_pattern_candidates" not in resolution.model_dump()
    if meta["anchor_self_sufficient"]:
        assert patterns == []
        assert catalog == []
        assert resolution.selected_examples == []
        assert meta["selection_strategy"] == "anchor_gap_analysis_withheld_redundant_patterns"
        assert not meta["uncovered_roles"]
        return

    assert 1 <= len(patterns) <= 5
    assert len(catalog) >= len(patterns)
    assert len(catalog) >= 2
    assert len(catalog) + len(resolution.selected_examples) >= 3
    assert len({pattern.pattern_id for pattern in patterns}) == len(patterns)
    assert all(pattern.optional and pattern.hygiene_clean for pattern in patterns)
    assert all(pattern.pack_id != resolution.anchor_pack.manifest.pack_id for pattern in patterns)
    assert all(pattern.job_statement and pattern.when_to_use and pattern.when_not_to_use for pattern in patterns)
    assert all(pattern.integration_hint and pattern.responsive_behavior and pattern.invariants for pattern in patterns)
    assert all(
        pattern.excerpt is not None and pattern.excerpt.content.strip()
        if pattern.source_kind == "support_example"
        else pattern.excerpt is None and pattern.style_excerpt is None
        for pattern in patterns
    )
    assert sum(pattern.source_kind == "anchor_excerpt" for pattern in patterns) <= 1
    assert meta["selection_strategy"] == "hard_domain_gate_then_priority_role_fill_with_elbow_stop"

    per_pack_counts = {
        pack_id: sum(pattern.pack_id == pack_id for pattern in patterns)
        for pack_id in {pattern.pack_id for pattern in patterns}
    }
    assert all(count <= meta["max_per_pack"] for count in per_pack_counts.values())

    all_pattern_ids = " ".join(entry.pattern_id.lower() for entry in catalog)
    assert not any(marker in all_pattern_ids for marker in FOREIGN_MARKERS[case_id])
    if surface_kind == "game":
        assert all(entry.domain_fit == "native" for entry in catalog)

    if case_id == "plumber":
        assert any(pattern.domain_fit == "native" and "plumb" in pattern.pattern_id for pattern in patterns)
        assert resolution.support_bank.manifest.family == "website.local_service"
        assert all(
            any(token in selection.example_id for token in ("plumb", "harborpipe", "stillwater", "pipewise"))
            for selection in resolution.selected_examples
        )
    elif case_id == "arcade-racer":
        assert resolution.support_bank.manifest.pack_id == "frontier_pattern_bank_20260628_v1"
        assert resolution.selected_example_ids == ["racer"]
        assert all(
            selection.example_id in {"racer", "breakout", "physics-sandbox", "boids"}
            for selection in resolution.selected_examples
        )
        assert len(catalog) + len(resolution.selected_examples) >= 3
        assert not resolution.auxiliary_anchor_packs
    elif case_id == "dungeon-tactics":
        assert resolution.support_bank.manifest.pack_id == "frontier_pattern_bank_20260628_v1"
        assert resolution.selected_example_ids == ["roguelike"]
        assert all(
            selection.example_id in {"roguelike", "tower-defense", "chess", "sudoku", "solitaire"}
            for selection in resolution.selected_examples
        )
        assert len(catalog) + len(resolution.selected_examples) >= 4
        assert len(patterns) < 4
        assert not resolution.auxiliary_anchor_packs


def test_optional_pattern_order_and_catalog_are_deterministic(router):
    _, surface, surface_kind, task = CASES[2]
    request = _request(surface, surface_kind, task)

    first = router.route(request)
    second = router.route(request)

    assert first.optional_pattern_ids == second.optional_pattern_ids
    assert [pattern.score for pattern in first.optional_patterns] == [
        pattern.score for pattern in second.optional_patterns
    ]
    assert [entry.pattern_id for entry in first.optional_pattern_catalog] == [
        entry.pattern_id for entry in second.optional_pattern_catalog
    ]


def test_standard_packet_renders_pattern_cards_and_catalog():
    _, surface, surface_kind, task = CASES[2]
    packet = resolve_design_context(
        ROOT,
        surface=surface,
        surface_kind=surface_kind,
        task=task,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
        code_profile="code_first",
        optional_pattern_count=8,
    )

    selected_count = packet.metadata["optional_pattern_pool"]["selected_count"]
    assert "# Optional Pattern Shelf" in packet.markdown
    assert "Choose zero, one, or several fragments" in packet.markdown
    assert "The primary anchor still owns the page skeleton" in packet.markdown
    assert "Rendered card tier: `L`" in packet.markdown
    assert "## Qualified Pattern Catalog (not inlined)" in packet.markdown
    assert packet.markdown.count("## Optional Pattern `") == selected_count
    assert packet.metadata["code_density"]["optional_pattern_slices"] == selected_count
    assert packet.metadata["code_density"]["optional_pattern_catalog_entries"] >= selected_count
    assert all("score_axes" in pattern for pattern in packet.metadata["optional_patterns"])
    assert packet.metadata["capacity_policy"] == "unbounded"
    assert "PACKET TRUNCATED" not in packet.markdown


def test_compact_mode_uses_quality_selection_without_a_mode_ceiling():
    _, surface, surface_kind, task = CASES[2]
    packet = resolve_design_context(
        ROOT,
        surface=surface,
        surface_kind=surface_kind,
        task=task,
        token_mode="compact",
        route_profile="hybrid_v5",
        rerank_mode="off",
        optional_pattern_count=12,
    )

    selected_count = packet.metadata["optional_pattern_pool"]["selected_count"]
    assert 1 <= selected_count <= 12
    assert packet.metadata["optional_pattern_pool"]["mode_cap"] is None
    assert packet.metadata["optional_pattern_pool"]["capacity_policy"] == "unbounded"
    assert len(packet.metadata["optional_pattern_catalog"]) > selected_count
    assert "Rendered card tier: `L`" in packet.markdown
    assert packet.markdown.count("## Optional Pattern `") == selected_count
    assert "PACKET TRUNCATED" not in packet.markdown


def test_get_pattern_card_expands_one_qualified_candidate_and_rejects_others(router):
    _, surface, surface_kind, task = CASES[2]
    request = _request(surface, surface_kind, task)
    resolution = router.route(request)
    selected_ids = set(resolution.optional_pattern_ids)
    catalog_only = next(
        entry for entry in resolution.optional_pattern_catalog
        if entry.pattern_id not in selected_ids and entry.source_kind == "support_example"
    )

    result = get_pattern_card(
        ROOT,
        request,
        pattern_id=catalog_only.pattern_id,
        tier="L",
    )

    assert "error" not in result
    assert result["pattern"]["pattern_id"] == catalog_only.pattern_id
    assert result["markdown"].count("## Optional Pattern `") == 1
    assert "invariants:" in result["markdown"]

    auxiliary = next(
        (
            entry for entry in resolution.optional_pattern_catalog
            if entry.source_kind == "anchor_excerpt"
        ),
        None,
    )
    if auxiliary is not None:
        auxiliary_result = get_pattern_card(
            ROOT,
            request,
            pattern_id=auxiliary.pattern_id,
            tier="L",
        )
        assert "No donor markup is emitted" in auxiliary_result["markdown"]
        assert "```html" not in auxiliary_result["markdown"]

    rejected = get_pattern_card(
        ROOT,
        request,
        pattern_id="foreign_pack::unqualified::pattern",
        tier="M",
    )
    assert "not qualified" in rejected["error"]
    assert catalog_only.pattern_id in rejected["available_pattern_ids"]


def test_optional_pattern_shelf_can_be_disabled():
    _, surface, surface_kind, task = CASES[1]
    packet = resolve_design_context(
        ROOT,
        surface=surface,
        surface_kind=surface_kind,
        task=task,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
        include_optional_patterns=False,
    )

    assert "# Optional Pattern Shelf" not in packet.markdown
    assert packet.metadata["optional_pattern_pool"]["selected_count"] == 0
    assert packet.metadata["code_density"]["optional_pattern_slices"] == 0
    assert packet.metadata["optional_pattern_catalog"] == []


def test_export_bundle_preserves_exact_pattern_provenance_without_auxiliary_source_leak(tmp_path):
    _, surface, _, task = CASES[1]
    result = export_opencode_bundle(
        ROOT,
        surface=surface,
        task=task,
        surface_kind="landing",
        output_dir=tmp_path,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
        optional_pattern_count=8,
        max_source_chars=1200,
    )
    optional_sources = [
        source for source in result["source_excerpts"] if source["kind"] == "optional_pattern"
    ]
    sources_payload = json.loads((tmp_path / "SOURCES.json").read_text(encoding="utf-8"))
    selected_support_cards = [
        pattern
        for pattern in sources_payload["optional_patterns"]
        if pattern["source_kind"] == "support_example"
    ]

    assert len(optional_sources) == len(selected_support_cards)
    assert all(source["pack_id"] and source["example_id"] and source["pattern_id"] for source in optional_sources)
    assert all(source["source_kind"] == "support_example" for source in optional_sources)
    assert all((tmp_path / source["path"]).is_file() for source in optional_sources)
    assert sources_payload["route_profile"] == "hybrid_v5"
    assert sources_payload["rerank_mode"] == "off"
    assert sources_payload["route_trace_id"]
    assert len(sources_payload["optional_pattern_catalog"]) >= len(sources_payload["optional_patterns"])
    assert "# Optional Pattern Shelf" in (tmp_path / "PACKET.md").read_text(encoding="utf-8")


def test_reexport_removes_stale_generated_source_excerpts(tmp_path):
    _, first_surface, _, first_task = CASES[0]
    export_opencode_bundle(
        ROOT,
        surface=first_surface,
        surface_kind="landing",
        task=first_task,
        output_dir=tmp_path,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
    )
    first_payload = json.loads((tmp_path / "SOURCES.json").read_text(encoding="utf-8"))
    first_paths = {source["path"] for source in first_payload["source_excerpts"]}

    _, second_surface, _, second_task = CASES[3]
    export_opencode_bundle(
        ROOT,
        surface=second_surface,
        surface_kind="game",
        task=second_task,
        output_dir=tmp_path,
        token_mode="standard",
        route_profile="hybrid_v5",
        rerank_mode="off",
    )
    second_payload = json.loads((tmp_path / "SOURCES.json").read_text(encoding="utf-8"))
    second_paths = {source["path"] for source in second_payload["source_excerpts"]}

    stale_paths = first_paths.difference(second_paths)
    assert stale_paths
    assert all(not (tmp_path / rel_path).exists() for rel_path in stale_paths)
    assert not list(tmp_path.rglob("*.new"))


def test_legacy_markup_trimming_stays_balanced_but_packet_css_is_complete():
    markup = (
        '<section class="schedule"><div><h2>Classes</h2>'
        "<p>Monday Tuesday Wednesday Thursday Friday</p></div></section>"
    )
    trimmed_markup = _trim_balanced_markup(markup, 72)
    assert trimmed_markup.endswith("<!-- shortened at a tag boundary -->")
    assert trimmed_markup.count("<section") == trimmed_markup.count("</section>")
    assert trimmed_markup.count("<div") == trimmed_markup.count("</div>")

    css = ".first { color: red; }\n.second { color: blue; padding: 2rem; }"
    trimmed_css = _safe_css_excerpt(css, max_chars=31)
    assert ".first" in trimmed_css
    assert ".second" in trimmed_css
    assert trimmed_css.count("{") == trimmed_css.count("}")
    assert "shortened" not in trimmed_css
