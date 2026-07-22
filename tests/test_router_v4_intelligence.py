import json
from pathlib import Path

import pytest

from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import get_router, resolve_design_packet, route_alternatives


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "router_v4_adversarial.json").read_text(encoding="utf-8")
)
ROUTES = FIXTURE["routes"]
CLARIFY = FIXTURE["clarify"]


@pytest.fixture(scope="module")
def router():
    return get_router(ROOT)


@pytest.mark.parametrize("case_id,surface,task,expected", ROUTES, ids=[row[0] for row in ROUTES])
def test_adversarial_paraphrases_typos_and_negations_route_correctly(router, case_id, surface, task, expected):
    resolution = router.route(DesignContextRequest(surface=surface, task=task))

    assert resolution.anchor_pack.manifest.pack_id == expected
    assert resolution.route_meta["route_confidence"]["decision"] == "route"


@pytest.mark.parametrize("case_id,surface,task", CLARIFY, ids=[row[0] for row in CLARIFY])
def test_underspecified_or_conflicting_briefs_fail_closed(router, case_id, surface, task):
    resolution = router.route(DesignContextRequest(surface=surface, task=task))
    confidence = resolution.route_meta["route_confidence"]

    assert confidence["decision"] == "clarify"
    assert confidence["needs_clarification"] is True
    assert confidence["clarification_question"]
    assert confidence["value"] < 0.5


def test_conflicting_archetypes_preserve_ranked_evidence(router):
    resolution = router.route(
        DesignContextRequest(
            surface="app",
            task="build a calendar and kanban project workspace",
        )
    )
    candidates = resolution.normalized_request.task_archetype_candidates

    assert resolution.normalized_request.task_archetype_ambiguous is True
    assert [candidate.name for candidate in candidates[:2]] == ["kanban", "calendar"]
    assert resolution.route_meta["candidate_gate"]["archetype_gate_count"] == resolution.route_meta["candidate_gate"]["surface_gate_count"]


def test_fuzzy_evidence_is_deduplicated_and_diagnostic(router):
    resolution = router.route(
        DesignContextRequest(
            surface="app",
            task="acount prefernces and securty setings with notificatons and apperance",
        )
    )
    candidates = resolution.normalized_request.task_archetype_candidates

    assert candidates[0].name == "settings"
    assert candidates[0].fuzzy_tokens == ["prefernces->preferences", "setings->settings"]
    assert resolution.normalized_request.task_archetype_ambiguous is False


def test_negated_workflow_is_not_used_as_positive_archetype_evidence(router):
    resolution = router.route(
        DesignContextRequest(
            surface="app",
            task="not an email client; build a notification center for unread alerts",
        )
    )
    names = [candidate.name for candidate in resolution.normalized_request.task_archetype_candidates]

    assert names[0] == "notifications"
    assert "email_client" not in names


def test_marketing_page_for_tool_uses_landing_candidates(router):
    request = {
        "surface": "website",
        "task": "build a marketing landing page for an in-browser code playground product with hero benefits and call to action",
    }
    resolution = router.route(DesignContextRequest(**request))
    alternatives = route_alternatives(ROOT, request)

    assert resolution.normalized_request.surface_kind == "landing"
    assert resolution.anchor_pack.manifest.pack_id == "nimbus_command_palette_v1"
    assert "spark_code_playground_v1" not in [row["pack_id"] for row in alternatives["top_anchors"]]


def test_explicit_surface_kind_can_override_marketing_vocabulary(router):
    resolution = router.route(
        DesignContextRequest(
            surface="website",
            surface_kind="app",
            task="build the actual code playground app, not just its marketing hero",
        )
    )

    assert resolution.normalized_request.surface_kind == "app"
    assert resolution.anchor_pack.manifest.pack_id == "spark_code_playground_v1"


@pytest.mark.parametrize(
    "case_id,task,expected",
    [
        (
            "rural-water-diagnostic",
            "Build a rural well pump and water filtration service website with an interactive symptom diagnostic, "
            "a well-to-home system cutaway, emergency versus planned service, and a quote request form.",
            "clear_ridge_water_works_field_blue_v1",
        ),
        (
            "grading-process",
            "Build a land clearing and grading contractor website with an excavator terrain hero, "
            "before-and-after grading comparison, fleet, service area, process timeline, and ballpark estimate flow.",
            "holland_dirt_black_yellow_v1",
        ),
        (
            "martial-arts-schedule",
            "Build a grounded black-and-copper martial arts academy website for MMA, striking, and grappling "
            "with a class schedule matrix, first-week onboarding, coach placeholders, and trial booking.",
            "iron_circuit_fight_academy_black_copper_v1",
        ),
        (
            "cabinetry-materials",
            "Build a custom cabinetry and architectural millwork studio website with detailed cabinet elevations, "
            "exploded joinery, a material selector, project process, specifications, and a design consultation form.",
            "oakline_cabinetry_craftsmanship_v1",
        ),
        (
            "aerospace-manifest",
            "Build a private aerospace launch provider website with a detailed rocket technical drawing, vehicle "
            "specifications, orbit visualization, mission sequence, program roadmap, and payload manifest intake.",
            "orbital_launch_manifest_dark_editorial_v1",
        ),
        (
            "mechanical-watch",
            "Build a premium mechanical watch product-detail website with an inspectable watch hero, exploded "
            "case anatomy, six material surface views, specification table, strap selector, price, and reservation form.",
            "reference_product_black_spec_v1",
        ),
        (
            "beauty-booking",
            "Build an editorial sugaring and skin studio website with a detailed illustrative portrait hero, "
            "treatment menu, preparation guide, studio locations, membership comparison, FAQ, and booking request review.",
            "velvet_fig_beauty_editorial_v1",
        ),
    ],
    ids=[
        "rural-water-diagnostic",
        "grading-process",
        "martial-arts-schedule",
        "cabinetry-materials",
        "aerospace-manifest",
        "mechanical-watch",
        "beauty-booking",
    ],
)
def test_explicit_homepage_routes_by_vertical_despite_incidental_app_vocabulary(router, case_id, task, expected):
    resolution = router.route(
        DesignContextRequest(
            surface="website.homepage",
            task=task,
        )
    )

    assert resolution.normalized_request.surface_kind == "landing"
    assert resolution.anchor_pack.manifest.pack_id == expected
    assert resolution.route_meta["route_confidence"]["decision"] != "clarify"


def test_incident_operations_signature_selects_signalstack(router):
    resolution = router.route(
        DesignContextRequest(
            surface="app",
            task="Build an incident operations SaaS workspace centered on an owned alert queue with triage filters, "
            "a selected-signal detail panel, workflow stages, permission boundaries, operational states, and deployment options.",
        )
    )

    assert resolution.normalized_request.task_archetype == "analytics_dashboard"
    assert resolution.anchor_pack.manifest.pack_id == "signalstack_saas_analytics_ink_v1"
    assert resolution.route_meta["route_confidence"]["decision"] != "clarify"


def test_retired_freezebreeze_pack_is_absent_from_active_rules_and_index(router):
    rules_text = (ROOT / "src" / "design_router_mcp" / "defaults" / "routing_rules.default.json").read_text(
        encoding="utf-8"
    )

    assert "freezebreeze_live_lab_ice_blue_v1" not in rules_text
    assert all(
        record.manifest.pack_id != "freezebreeze_live_lab_ice_blue_v1"
        for record in router.index.anchors
    )


def test_rebuilt_anchor_runtime_files_match_packaged_copies():
    pack_ids = [
        "clear_ridge_water_works_field_blue_v1",
        "holland_dirt_black_yellow_v1",
        "iron_circuit_fight_academy_black_copper_v1",
        "oakline_cabinetry_craftsmanship_v1",
        "orbital_launch_manifest_dark_editorial_v1",
        "reference_product_black_spec_v1",
        "signalstack_saas_analytics_ink_v1",
        "velvet_fig_beauty_editorial_v1",
    ]

    for pack_id in pack_ids:
        canonical = ROOT / "goldensets" / "website" / pack_id
        packaged = ROOT / "src" / "design_router_mcp" / "goldensets" / "website" / pack_id
        manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
        runtime_files = [
            "manifest.json",
            "prompt.md",
            "principles.md",
            "anti_copy.md",
            *manifest["source_paths"],
            *manifest["screenshot_paths"],
        ]

        for relative_path in runtime_files:
            assert (canonical / relative_path).read_bytes() == (packaged / relative_path).read_bytes()


@pytest.mark.parametrize(
    "surface_kind,expected",
    [
        ("dashboard", "app"),
        ("homepage", "landing"),
        ("documentation", "docs"),
    ],
)
def test_surface_kind_aliases_are_canonicalized(router, surface_kind, expected):
    resolution = router.route(
        DesignContextRequest(
            surface="website",
            surface_kind=surface_kind,
            task="build a settings page for privacy",
        )
    )

    assert resolution.normalized_request.surface_kind == expected


def test_unknown_explicit_router_hints_fail_loudly(router):
    with pytest.raises(ValueError, match="Unknown surface_kind"):
        router.route(
            DesignContextRequest(
                surface="website",
                surface_kind="space_portal",
                task="build a settings page",
            )
        )
    with pytest.raises(ValueError, match="Unknown task_archetype"):
        router.route(
            DesignContextRequest(
                surface="app",
                task_archetype="mystery_console",
                task="build a console",
            )
        )


def test_specific_archetype_supersedes_broad_parent_without_false_ambiguity(router):
    resolution = router.route(
        DesignContextRequest(
            surface="app",
            task="build a code playground with editor preview and console",
        )
    )

    assert [candidate.name for candidate in resolution.normalized_request.task_archetype_candidates[:2]] == [
        "code_playground",
        "editor",
    ]
    assert resolution.normalized_request.task_archetype_ambiguous is False
    assert resolution.anchor_pack.manifest.pack_id == "spark_code_playground_v1"


def test_provisional_packet_surfaces_clarification_question():
    packet = resolve_design_packet(
        {
            "surface": "app",
            "task": "build an image tool with effects and export",
        },
        ROOT,
    )

    assert "route decision: `clarify`" in packet
    assert "provisional route" in packet
    assert "Which direction is primary:" in packet


@pytest.mark.parametrize(
    "transform",
    [
        lambda task: task.upper(),
        lambda task: f"Please help me create this carefully: {task}. Keep it accessible.",
        lambda task: task.replace(", ", "; ").replace(" with ", "\nwith "),
    ],
    ids=["uppercase", "polite-noise", "punctuation"],
)
def test_labeled_routes_are_stable_under_nonsemantic_prompt_noise(router, transform):
    v3_cases = json.loads(
        (Path(__file__).parent / "fixtures" / "router_v3_briefs.json").read_text(encoding="utf-8")
    )
    for case in v3_cases:
        request = DesignContextRequest(
            **{
                **case["request"],
                "task": transform(case["request"]["task"]),
            }
        )
        assert router.route(request).anchor_pack.manifest.pack_id == case["expected_top1"], case["id"]
