import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from design_router_mcp.embedding_index import build_embedding_index
from design_router_mcp.index_store import build_repository_index
from design_router_mcp.routing_eval import compare_routing_profiles, evaluate_routing, load_judgments, write_routing_report
from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import get_router
from design_router_mcp.visual_index import build_visual_index


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evals" / "router" / "judgments.jsonl"


def test_versioned_judgment_ledger_covers_all_splits():
    judgments = load_judgments(LEDGER)

    assert len(judgments) == 39
    assert {judgment.split for judgment in judgments} == {
        "train",
        "calibration",
        "hidden",
    }
    assert len({judgment.judgment_id for judgment in judgments}) == len(judgments)


def test_hybrid_router_passes_hidden_gate_and_calibrates():
    report = evaluate_routing(ROOT, profile="hybrid_v4")

    assert report["metrics"]["pass_rate"] == 1.0
    assert report["splits"]["hidden"]["pass_rate"] == 1.0
    assert report["splits"]["hidden"]["forbidden_violations"] == 0
    assert report["calibration"] == {
        "available": True,
        "threshold": 0.57,
        "accuracy": 1.0,
        "false_confident": 0,
        "false_clarify": 0,
        "count": 16,
    }
    assert report["quality_gate"]["pass"] is True


def test_default_profile_comparison_includes_v5(monkeypatch):
    def fake_evaluate(repo_root, *, profile, ledger_path=None):
        return {
            "metrics": {"profile": profile},
            "splits": {"hidden": {"profile": profile}},
            "calibration": {"profile": profile},
        }

    monkeypatch.setattr("design_router_mcp.routing_eval.evaluate_routing", fake_evaluate)
    report = compare_routing_profiles(ROOT)

    assert report["profiles"] == [
        "data_driven_v2",
        "hybrid_shadow_v1",
        "hybrid_v4",
        "hybrid_v5",
    ]


def test_hybrid_retrieval_is_stable_across_hash_seeds():
    script = """
import json
from design_router_mcp.routing_eval import evaluate_routing
report = evaluate_routing('.', profile='hybrid_v4')
print(json.dumps([
    (row['judgment_id'], row['hybrid_winner'])
    for row in report['hybrid_disagreements']
]))
"""
    outputs = []
    for seed in ("1", "999"):
        env = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "PYTHONPATH": str(ROOT / "src"),
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(result.stdout.strip())

    assert outputs[0] == outputs[1]


def test_route_trace_id_is_deterministic_and_request_specific():
    router = get_router(ROOT, refresh_index=True)
    first = router.route(
        DesignContextRequest(surface="app", task="build account settings")
    )
    repeated = router.route(
        DesignContextRequest(surface="app", task="build account settings")
    )
    changed = router.route(
        DesignContextRequest(surface="app", task="build a notification center")
    )

    assert first.route_meta["trace_id"] == repeated.route_meta["trace_id"]
    assert first.route_meta["trace_id"] != changed.route_meta["trace_id"]
    assert len(first.route_meta["trace_id"]) == 16


def test_visual_index_profiles_every_anchor(tmp_path):
    output = tmp_path / "visual-index.json"
    result = build_visual_index(ROOT, output_path=output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result["anchor_count"] == len(payload["anchors"])
    assert result["source_coverage"] == result["anchor_count"]
    assert all(row["visual_terms"] for row in payload["anchors"].values())


def test_embedding_index_batches_and_persists(monkeypatch, tmp_path):
    from design_router_mcp import embedding_index

    def fake_post(endpoint, payload):
        return {
            "embeddings": [
                [float(index), 1.0, 0.5]
                for index, _ in enumerate(payload["input"], start=1)
            ]
        }

    monkeypatch.setattr(embedding_index, "_post_json", fake_post)
    output = tmp_path / "embeddings.json"
    result = build_embedding_index(
        ROOT,
        model="test-embed",
        endpoint="http://localhost.invalid/api/embed",
        batch_size=17,
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result["anchor_count"] == len(build_repository_index(ROOT).anchors)
    assert result["dimensions"] == 3
    assert payload["model"] == "test-embed"
    assert len(payload["anchors"]) == result["anchor_count"]


def test_routing_report_writes_searchable_dashboard(tmp_path):
    result = write_routing_report(ROOT, tmp_path, profile="hybrid_v4")
    page = Path(result["html"]).read_text(encoding="utf-8")

    assert result["metrics"]["pass_rate"] == 1.0
    assert "Quality audit" in page
    assert 'id="route-search"' in page
    assert 'data-filter="warning"' in page
    assert "Hidden gate" in page
    assert "evals/router/judgments.jsonl" in page
    assert str(ROOT) not in page


def test_mcp_server_registers_routing_intelligence_tools():
    import asyncio

    from design_router_mcp import mcp_server

    try:
        server = mcp_server.create_mcp_server(ROOT)
    except mcp_server.MissingMcpDependencyError:
        pytest.skip("optional mcp dependency not installed")
    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert {
        "routing_quality_audit",
        "build_visual_routing_index",
        "build_design_embedding_index",
        "run_golden_build_arena",
    }.issubset(tool_names)
