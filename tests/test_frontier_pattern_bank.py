"""Route + render proofs for the frontier_pattern_bank support pack (72 non-landing
interactive patterns). These assert behavior, not implementation: the bank is
registered, an app/tool request selects it and surfaces relevant donor examples,
and packet size remains telemetry rather than a clipping boundary."""
from pathlib import Path

from design_router_mcp.index_store import build_repository_index
from design_router_mcp.router import DesignRouter
from design_router_mcp.rules import load_routing_rules
from design_router_mcp.schemas import DesignContextRequest
from design_router_mcp.service import resolve_design_context

ROOT = Path(__file__).resolve().parents[1]
PACK_ID = "frontier_pattern_bank_20260628_v1"


def _route(**req):
    router = DesignRouter.from_repo(ROOT, refresh_index=False)
    return router, router.route(DesignContextRequest(**req))


def test_frontier_bank_registered_as_support_bank():
    index = build_repository_index(ROOT)
    record = index.by_id.get(PACK_ID)
    assert record is not None, "frontier pack not indexed"
    assert record.manifest.role == "support_bank"
    assert len(record.manifest.example_ids) == 72
    # every example must declare a vendored source dir (no silent gaps)
    assert all(record.manifest.source_dirs.get(eid) for eid in record.manifest.example_ids)


def test_app_dashboard_request_selects_frontier_bank():
    _, resolution = _route(
        surface="app.tool",
        task="interactive analytics dashboard with live charts, a data table, and a sidebar",
        layout_mode="dashboard",
        stack="html_css",
        tone=["technical", "precise", "dark"],
    )
    assert resolution.support_bank is not None
    assert resolution.support_bank.manifest.pack_id == PACK_ID
    # selects at least one donor, and the dashboard archetype surfaces for a dashboard ask
    assert resolution.selected_example_ids
    assert any("analytics" in eid for eid in resolution.selected_example_ids)


def test_editor_request_surfaces_code_examples():
    _, resolution = _route(
        surface="app.tool",
        task="a code editor and live playground workspace with a sidebar file tree",
        layout_mode="app",
        stack="html_css",
        tone=["technical", "dark"],
    )
    assert resolution.support_bank.manifest.pack_id == PACK_ID
    assert any(eid in {"code-editor", "code-playground"} for eid in resolution.selected_example_ids)


def test_named_pattern_surfaces_by_token():
    # naming the pattern in the task must surface that specific donor
    _, resolution = _route(
        surface="app.tool",
        task="a single-screen sudoku puzzle game UI with a board and number pad",
        layout_mode="app",
        stack="html_css",
        tone=["interactive", "playful"],
    )
    assert "sudoku" in resolution.selected_example_ids


def test_existing_website_routing_unaffected():
    # the new app/tool bank must not hijack a website landing request
    packet = resolve_design_context(
        ROOT,
        surface="website.local_service",
        task="Build a B2B SaaS analytics dashboard landing page",
        stack="html_css",
        token_mode="compact",
    )
    assert "signalstack_saas_analytics_ink_v1" in packet.markdown


def test_render_reports_size_without_enforcing_a_token_budget():
    rules = load_routing_rules(ROOT)
    packet = resolve_design_context(
        ROOT,
        surface="app.tool",
        task="a kanban board app shell with draggable cards and a sidebar",
        layout_mode="app",
        stack="html_css",
        token_mode="compact",
    )
    assert packet.markdown.strip()
    assert packet.estimated_tokens > 0
    budget = rules.token_budget(packet.token_mode)
    assert budget.max_packet_tokens is None
    assert packet.metadata["capacity_policy"] == "unbounded"
    assert "PACKET TRUNCATED" not in packet.markdown
