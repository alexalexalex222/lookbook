import json
import struct
import zlib
from pathlib import Path

import pytest

from design_router_mcp.local_reranker import rerank_candidates
from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import get_router
from design_router_mcp.service import resolve_design_context
from design_router_mcp.visual_features import (
    analyze_image,
    visual_similarity,
    visual_target_from_request,
)
from design_router_mcp.visual_features import _decode_png
from design_router_mcp.visual_index import build_visual_index


ROOT = Path(__file__).resolve().parents[1]


def _write_rgb_png(
    path: Path, width: int, height: int, rgb: tuple[int, int, int]
) -> None:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def test_pixel_profiles_read_real_image_content(tmp_path):
    dark_warm = tmp_path / "dark-warm.png"
    light_cool = tmp_path / "light-cool.png"
    _write_rgb_png(dark_warm, 12, 12, (74, 28, 18))
    _write_rgb_png(light_cool, 12, 12, (220, 238, 252))

    warm_profile = analyze_image(dark_warm)
    cool_profile = analyze_image(light_cool)

    assert warm_profile["available"] is True
    assert cool_profile["available"] is True
    assert warm_profile["features"]["mean_luma"] < cool_profile["features"]["mean_luma"]
    assert warm_profile["features"]["warmth"] > cool_profile["features"]["warmth"]
    assert len(warm_profile["vector"]) >= 10


@pytest.mark.parametrize(
    "path",
    [
        ROOT
        / "goldensets"
        / "website"
        / "neon_apex_arcade_racer_v1"
        / "screenshots"
        / "desktop-1512.png",
        ROOT
        / "goldensets"
        / "website"
        / "ashvault_dungeon_tactics_v1"
        / "screenshots"
        / "desktop-1512.png",
    ],
)
def test_native_game_screenshots_support_stdlib_png_decoder(path):
    pixels, width, height = _decode_png(path, max_side=32)

    assert pixels
    assert width <= 32
    assert height <= 32
    assert len(pixels) == width * height


def test_text_visual_preferences_rank_matching_pixel_profile(tmp_path):
    dark_warm = tmp_path / "dark-warm.png"
    light_cool = tmp_path / "light-cool.png"
    _write_rgb_png(dark_warm, 12, 12, (74, 28, 18))
    _write_rgb_png(light_cool, 12, 12, (220, 238, 252))
    request = DesignContextRequest(
        surface="website.homepage",
        task="Build a restrained dark product page with warm copper accents and high contrast.",
        tone=["dark", "warm", "high-contrast", "restrained"],
        route_profile="hybrid_v5",
    )
    target = visual_target_from_request(request)

    assert target["active"] is True
    assert visual_similarity(target, analyze_image(dark_warm)) > visual_similarity(
        target,
        analyze_image(light_cool),
    )


def test_reference_screenshot_can_drive_pixel_target(tmp_path):
    reference = tmp_path / "reference.png"
    matching = tmp_path / "matching.png"
    opposite = tmp_path / "opposite.png"
    _write_rgb_png(reference, 12, 12, (36, 48, 68))
    _write_rgb_png(matching, 12, 12, (42, 52, 72))
    _write_rgb_png(opposite, 12, 12, (244, 221, 176))
    request = DesignContextRequest(
        surface="website.homepage",
        task="Build the page.",
        route_profile="hybrid_v5",
        reference_image_paths=["reference.png"],
    )
    target = visual_target_from_request(request, repo_root=tmp_path)

    assert target["reference_images"]["profiled"] == 1
    assert visual_similarity(target, analyze_image(matching)) > visual_similarity(
        target,
        analyze_image(opposite),
    )


def test_visual_target_reports_blended_request_and_reference_provenance(tmp_path):
    reference = tmp_path / "reference.png"
    _write_rgb_png(reference, 12, 12, (36, 48, 68))
    request = DesignContextRequest(
        surface="website.homepage",
        task="Build a dark, restrained page.",
        route_profile="hybrid_v5",
        reference_image_paths=["reference.png"],
    )

    target = visual_target_from_request(request, repo_root=tmp_path)

    assert target["source"] == "request_terms+reference_images"


def test_visual_index_v2_persists_pixel_profiles(tmp_path):
    output = tmp_path / "visual-index.json"
    result = build_visual_index(ROOT, output_path=output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    profiled = [
        row
        for row in payload["anchors"].values()
        if row.get("pixel_profile", {}).get("available")
    ]

    assert payload["version"] == "2.0"
    assert result["pixel_coverage"] == len(profiled)
    assert result["pixel_coverage"] > 0
    assert all(row["pixel_profile"]["vector"] for row in profiled)


def test_v5_pixel_channel_is_opt_in_and_v4_stays_compatible():
    router = get_router(ROOT, refresh_index=True)
    request = DesignContextRequest(
        surface="website.homepage",
        task="Build a dark warm premium mechanical watch page.",
        tone=["dark", "warm", "premium"],
    )
    records = router.index.anchors
    rules_rank = [record.pack_id for record in records]
    router.hybrid_retriever.pixel_profiles = {
        "reference_product_black_spec_v1": analyze_image(
            ROOT
            / "goldensets"
            / "website"
            / "reference_product_black_spec_v1"
            / "screenshots"
            / "router-desktop-1512x812.png"
        )
    }

    v4 = router.hybrid_retriever.rank(
        request, records, rules_rank=rules_rank, include_pixel=False
    )
    v5 = router.hybrid_retriever.rank(
        request, records, rules_rank=rules_rank, include_pixel=True
    )

    assert all("pixel" not in row.channel_scores for row in v4)
    assert any("pixel" in row.channel_scores for row in v5)


def test_local_reranker_rejects_unknown_candidate(monkeypatch):
    monkeypatch.setenv("DESIGN_ROUTER_RERANK_MODEL", "test-model")
    captured = {}

    def fake_post(endpoint, payload, timeout):
        captured["payload"] = payload
        return {
            "response": json.dumps(
                {
                    "winner": "not-in-pool",
                    "ranking": ["not-in-pool"],
                    "confidence": 0.99,
                    "abstain": False,
                    "reason": "malicious promotion",
                }
            )
        }

    monkeypatch.setattr("design_router_mcp.local_reranker._post_json", fake_post)
    result = rerank_candidates(
        DesignContextRequest(
            surface="app", task="build account settings", route_profile="hybrid_v5"
        ),
        [
            {"pack_id": "alpha", "score": 100},
            {"pack_id": "beta", "score": 96},
        ],
        mode="active",
    )

    assert result["available"] is True
    assert result["valid"] is False
    assert result["promote"] is False
    assert result["reason_code"] == "candidate_escape"
    assert captured["payload"]["options"] == {"temperature": 0}


def test_local_reranker_promotes_only_close_qualified_candidate(monkeypatch):
    monkeypatch.setenv("DESIGN_ROUTER_RERANK_MODEL", "test-model")

    def fake_post(endpoint, payload, timeout):
        return {
            "response": json.dumps(
                {
                    "winner": "beta",
                    "ranking": ["beta", "alpha"],
                    "confidence": 0.91,
                    "abstain": False,
                    "reason": "Beta matches the requested owned queue workflow.",
                }
            )
        }

    monkeypatch.setattr("design_router_mcp.local_reranker._post_json", fake_post)
    result = rerank_candidates(
        DesignContextRequest(
            surface="app", task="build an owned alert queue", route_profile="hybrid_v5"
        ),
        [
            {"pack_id": "alpha", "score": 100},
            {"pack_id": "beta", "score": 94},
        ],
        mode="active",
        max_promotion_gap=18,
    )

    assert result["valid"] is True
    assert result["promote"] is True
    assert result["winner"] == "beta"
    assert result["promotion_bonus"] == 7


def test_local_reranker_fails_open_when_endpoint_is_unavailable(monkeypatch):
    monkeypatch.setenv("DESIGN_ROUTER_RERANK_MODEL", "test-model")

    def unavailable(endpoint, payload, timeout):
        raise OSError("offline")

    monkeypatch.setattr("design_router_mcp.local_reranker._post_json", unavailable)
    result = rerank_candidates(
        DesignContextRequest(
            surface="app", task="build account settings", route_profile="hybrid_v5"
        ),
        [{"pack_id": "alpha", "score": 100}],
        mode="active",
    )

    assert result["available"] is False
    assert result["promote"] is False
    assert result["reason_code"] == "endpoint_unavailable"


def test_local_reranker_blocks_remote_endpoint_by_default(monkeypatch):
    monkeypatch.setenv("DESIGN_ROUTER_RERANK_MODEL", "test-model")
    monkeypatch.setenv("DESIGN_ROUTER_RERANK_URL", "https://example.com/api/generate")

    result = rerank_candidates(
        DesignContextRequest(
            surface="app", task="build account settings", route_profile="hybrid_v5"
        ),
        [{"pack_id": "alpha", "score": 100}],
        mode="active",
    )

    assert result["available"] is False
    assert result["reason_code"] == "non_local_endpoint_blocked"


def test_hybrid_v5_without_local_model_preserves_v4_winner(monkeypatch):
    monkeypatch.delenv("DESIGN_ROUTER_RERANK_MODEL", raising=False)
    router = get_router(ROOT, refresh_index=True)
    v4 = router.route(
        DesignContextRequest(
            surface="app", task="build account settings", route_profile="hybrid_v4"
        )
    )
    v5 = router.route(
        DesignContextRequest(
            surface="app", task="build account settings", route_profile="hybrid_v5"
        )
    )

    assert v5.anchor_pack.manifest.pack_id == v4.anchor_pack.manifest.pack_id
    assert (
        v5.route_meta["candidate_gate"]["local_reranker"]["reason_code"]
        == "model_not_configured"
    )


def test_service_exposes_v5_rerank_controls():
    packet = resolve_design_context(
        ROOT,
        surface="app",
        task="Build account settings.",
        route_profile="hybrid_v5",
        rerank_mode="off",
    )

    reranker = packet.metadata["candidate_gate"]["local_reranker"]
    assert reranker["mode"] == "off"
    assert reranker["reason_code"] == "disabled"


@pytest.mark.parametrize(
    ("surface_kind", "task", "expected_anchor", "expected_archetype"),
    [
        (
            "landing",
            "Build a serious martial arts academy website with striking, grappling and fundamentals programs, class schedule, instructor profiles, trial-class inquiry, and mobile navigation.",
            "iron_circuit_fight_academy_black_copper_v1",
            None,
        ),
        (
            "landing",
            "Build a residential plumbing company website with emergency versus scheduled service paths, symptom-based diagnostics, service categories, service area, and an estimate request form.",
            "pipewise_plumbing_telemetry_v1",
            None,
        ),
        (
            "game",
            "Build a playable top-down arcade racer with steering, acceleration, track boundaries, checkpoints, laps, timer, speed display, pause, restart, and touch controls.",
            "neon_apex_arcade_racer_v1",
            "arcade_game",
        ),
        (
            "game",
            "Build a playable turn-based dungeon tactics game with a grid map, player movement, walls, deterministic enemies, attack range, health, exit objective, turn counter, event log, restart, and touch controls.",
            "ashvault_dungeon_tactics_v1",
            "tactics_game",
        ),
    ],
)
def test_v5_routes_historical_four_surface_failures(
    surface_kind,
    task,
    expected_anchor,
    expected_archetype,
):
    router = get_router(ROOT, refresh_index=True)
    resolution = router.route(
        DesignContextRequest(
            surface="website" if surface_kind == "landing" else "game",
            surface_kind=surface_kind,
            task=task,
            route_profile="hybrid_v5",
            rerank_mode="off",
        )
    )

    assert resolution.anchor_pack.manifest.pack_id == expected_anchor
    assert resolution.normalized_request.task_archetype == expected_archetype
    assert resolution.route_meta["route_confidence"]["decision"] != "clarify"
