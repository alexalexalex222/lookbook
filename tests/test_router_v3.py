import json
from pathlib import Path

import pytest

from design_router_mcp.normalizer import normalize_request
from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import get_router, route_alternatives


ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((Path(__file__).parent / "fixtures" / "router_v3_briefs.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def router():
    return get_router(ROOT)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_labeled_briefs_route_to_expected_anchor_and_archetype(router, case):
    request = DesignContextRequest(**case["request"])
    resolution = router.route(request)

    assert resolution.normalized_request.task_archetype == case["expected_archetype"]
    assert resolution.anchor_pack.manifest.pack_id == case["expected_top1"]


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["request"]["surface"] in {"app", "instrument"}],
    ids=[case["id"] for case in CASES if case["request"]["surface"] in {"app", "instrument"}],
)
def test_app_briefs_gate_local_service_anchors(router, case):
    alternatives = route_alternatives(ROOT, case["request"])
    for score in alternatives["top_anchors"][:3]:
        assert router.index.get(score["pack_id"]).manifest.family != "website.local_service"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_screenshot_constraints_do_not_change_semantic_winner(router, case):
    base = DesignContextRequest(**case["request"])
    screenshot = base.model_copy(update={"constraints": ["Match the supplied desktop screenshot at 1512x812."]})

    assert router.route(base).anchor_pack.manifest.pack_id == router.route(screenshot).anchor_pack.manifest.pack_id
    assert normalize_request(screenshot, router.rules).requires_screenshot_fit is True


@pytest.mark.parametrize("case_id", ["settings", "kanban", "notifications", "code-playground", "gradient-generator"])
def test_task_archetype_overrides_generic_website_surface(router, case_id):
    case = next(item for item in CASES if item["id"] == case_id)
    explicit = DesignContextRequest(**case["request"])
    generic = explicit.model_copy(update={"surface": "website"})

    assert router.route(generic).anchor_pack.manifest.pack_id == case["expected_top1"]


def test_route_metadata_exposes_gate_and_confidence(router):
    case = next(item for item in CASES if item["id"] == "kanban")
    resolution = router.route(DesignContextRequest(**case["request"]))

    gate = resolution.route_meta["candidate_gate"]
    confidence = resolution.route_meta["route_confidence"]
    assert gate["surface_kind"] == "app"
    assert gate["task_archetype"] == "kanban"
    assert 0 < gate["archetype_gate_count"] <= gate["surface_gate_count"] < gate["initial_anchor_count"]
    assert confidence["level"] in {"low", "medium", "high"}
    assert 0.0 <= confidence["value"] <= 1.0


def test_manifest_anti_patterns_can_penalize_incompatible_requests(router):
    request = DesignContextRequest(
        surface="website",
        task="Build a marketing hero and pricing landing page for a code playground",
    )
    normalized = normalize_request(request, router.rules)
    record = router.index.get("spark_code_playground_v1")
    score = router._score_record(request, normalized, record)

    assert score.anti_pattern < 0
    assert {"marketing", "pricing"}.issubset(set(score.matched_terms["anti_pattern"]))
