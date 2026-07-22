from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .service import (
    audit_source_hygiene,
    build_design_embedding_index,
    build_visual_routing_index,
    code_density_metrics,
    donor_starvation_audit,
    export_opencode_bundle,
    get_pattern_card,
    get_source_excerpt,
    inspect_design_library,
    prepare_golden_build_arena,
    route_alternatives,
    resolve_design_context,
    run_golden_build_arena,
    routing_quality_audit,
    validate_design_router,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class MissingMcpDependencyError(RuntimeError):
    pass


def _default_repo_root() -> Path:
    env_root = os.getenv("DESIGN_ROUTER_MCP_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    module_root = Path(__file__).resolve().parent
    for candidate in (module_root.parent.parent, module_root):
        if (candidate / "goldensets").is_dir() or (candidate / "src" / "design_router_mcp" / "goldensets").is_dir():
            return candidate.resolve()
    return Path.cwd().resolve()


def log_knowledge_route(result: dict[str, Any], brief: str, mode: str, k: int,
                        user_message: str) -> None:
    """Append one routing event to <corpus>/telemetry/ROUTES.jsonl.

    This ledger is the corpus's content flywheel: abstains and low-confidence
    routes accumulate here from REAL usage, and mining it answers "which
    chapter should the book grow next" with evidence instead of opinion.
    Serving-path only (the router library stays pure), append-only, and never
    allowed to break a route — any failure is swallowed.
    """
    try:
        from datetime import datetime, timezone

        from .knowledge_router import default_root

        lane = result.get("lane_inference") or {}
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "brief": brief[:400],
            "user_message_supplied": bool(user_message),
            "mode": mode,
            "k": k,
            "abstain": bool(result.get("abstain")),
            "reason": (result.get("reason") or "")[:120],
            "picks": result.get("picks", []),
            "skill_picks": result.get("skill_picks", []),
            "confidence": result.get("confidence"),
            "semantic_reranked": bool(lane.get("semantic_reranked")),
            "semantic_rescued": lane.get("semantic_rescued"),
            "closest_topics": result.get("top5", [])[:3],
        }
        tdir = default_root() / "telemetry"
        tdir.mkdir(parents=True, exist_ok=True)
        with open(tdir / "ROUTES.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_fastmcp() -> type[FastMCP]:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise MissingMcpDependencyError("Optional MCP dependency missing. Install with `pip install -e '.[mcp]'`.") from exc
    return FastMCP


def create_mcp_server(repo_root: str | Path | None = None) -> FastMCP:
    resolved = Path(repo_root).expanduser().resolve() if repo_root else _default_repo_root()
    FastMCP = _load_fastmcp()
    server = FastMCP(
        name="lookbook-mcp",
        instructions=(
            "Lookbook MCP — packet compiler for production-grade frontend work. "
            "Default to `resolve_design_context` for any frontend brief; the returned packet sets the engineering, accessibility, motion, typography, and craft bar for the page you build. "
            "Treat every contract in the returned packet (Hard UI Rules, Visual Asset Discipline, Design Tokens Contract, Motion Grammar, Typography Discipline, Accessibility Contract, State Completeness, Performance Discipline, Microcopy Contract, Layout QA Gates, Anti-Copy Contract, Claim Realism, Implementation Contract, Vertical Guardrails) as a hard floor for shipped code — not a target, not a suggestion. "
            "Read the V3 director sections when present: Composition Brief, Visual Artifact Specs, Optional Pattern Shelf, Local Model Failure Patterns, Donor Starvation Warning, and Mechanical Donors (UX Role Only). The primary anchor owns the page; Optional Pattern Shelf fragments are zero-or-more section mechanics the model may use or ignore. "
            "Packet capacity is unbounded: relevance gates decide what enters, every selected source arrives complete, and estimated token counts are telemetry only. Legacy token-mode labels remain accepted but never trim output. "
            "Use `code_profile='code_first'` when the builder is a local coding model that needs source excerpts and route diagnostics before prose. "
            "Use `inspect_design_library` for inventory without loading source. Use `get_pattern_card` to expand one qualified catalog item without loading unrelated donors. Use `get_source_excerpt` only for targeted provenance or source inspection after routing. Use `export_opencode_bundle` for filesystem hand-off. Use `audit_source_hygiene` to inspect donor leakage risk. Use `validate_design_router` for setup checks. "
            "Never invent identity, copy, claims, names, statistics, testimonials, awards, or images. Borrow composition from the anchor; build the rest from the brief. When the brief is thin, write generalized phrasing that does not require invented specifics."
        ),
    )

    @server.tool(name="resolve_design_context", description="Resolve a frontend design task into an anchor-first packet. Use code_profile='code_first' for implementation-heavy local model builds.")
    def tool_resolve_design_context(
        surface: str,
        task: str,
        surface_kind: str | None = None,
        task_archetype: str | None = None,
        stack: str = "unknown",
        tone: list[str] | None = None,
        layout_mode: str = "homepage",
        constraints: list[str] | None = None,
        anti_patterns: list[str] | None = None,
        token_mode: str = "unbounded",
        max_examples: int = 3,
        donor_selection_mode: str = "support_examples_v1",
        donor_count: int = 3,
        include_optional_patterns: bool = True,
        optional_pattern_count: int = 8,
        route_profile: str = "hybrid_v4",
        rerank_mode: str = "shadow",
        rerank_model: str | None = None,
        reference_image_paths: list[str] | None = None,
        pattern_lock: bool = False,
        full_code_mode: bool = True,
        include_full_library: bool = False,
        host_browser_review: bool = False,
        local_model_profile: str | None = None,
        visual_quality_profile: str = "strict_design_router_gpt55_mcp_v1",
        code_profile: str = "balanced",
        packet_intent: str = "balanced",
    ) -> str:
        packet = resolve_design_context(
            resolved,
            surface=surface,
            task=task,
            surface_kind=surface_kind,
            task_archetype=task_archetype,
            stack=stack,
            tone=tone,
            layout_mode=layout_mode,
            constraints=constraints,
            anti_patterns=anti_patterns,
            token_mode=token_mode,
            max_examples=max_examples,
            donor_selection_mode=donor_selection_mode,
            donor_count=donor_count,
            include_optional_patterns=include_optional_patterns,
            optional_pattern_count=optional_pattern_count,
            route_profile=route_profile,
            rerank_mode=rerank_mode,
            rerank_model=rerank_model,
            reference_image_paths=reference_image_paths,
            pattern_lock=pattern_lock,
            full_code_mode=full_code_mode,
            include_full_library=include_full_library,
            host_browser_review=host_browser_review,
            local_model_profile=local_model_profile,
            visual_quality_profile=visual_quality_profile,
            code_profile=code_profile,
            packet_intent=packet_intent,
        )
        return packet.markdown

    @server.tool(name="inspect_design_library", description="List packs, vertical rules, and optional per-example local source inventory without loading full donor source text.")
    def tool_inspect_design_library(include_examples: bool = False) -> str:
        return json.dumps(inspect_design_library(resolved, include_examples=include_examples), indent=2)

    @server.tool(name="get_source_excerpt", description="Load targeted anchor/example code after routing. Selected source files are returned complete; legacy character-limit arguments are ignored.")
    def tool_get_source_excerpt(
        pack_id: str,
        example_id: str | None = None,
        token_mode: str = "unbounded",
        max_chars: int | None = None,
        include_full: bool = True,
        include_section_snippets: bool = True,
    ) -> str:
        return get_source_excerpt(
            resolved,
            pack_id=pack_id,
            example_id=example_id,
            token_mode=token_mode,
            max_chars=max_chars,
            include_full=include_full,
            include_section_snippets=include_section_snippets,
        )

    @server.tool(
        name="get_pattern_card",
        description="Expand one route-qualified optional Pattern Card by exact pattern_id. Returns only that card at tier S, M, or L; foreign or unqualified patterns are rejected.",
    )
    def tool_get_pattern_card(
        request_json: str,
        pattern_id: str,
        tier: str = "M",
    ) -> str:
        return json.dumps(
            get_pattern_card(
                resolved,
                request_json,
                pattern_id=pattern_id,
                tier=tier,
            ),
            indent=2,
        )

    @server.tool(name="export_opencode_bundle", description="Write an unbounded PACKET.md, capacity telemetry, and complete relevance-selected SOURCE_EXCERPTS/*.md files for OpenCode/local coding agents.")
    def tool_export_opencode_bundle(
        surface: str,
        task: str,
        surface_kind: str | None = None,
        task_archetype: str | None = None,
        output_dir: str = "",
        token_mode: str = "unbounded",
        stack: str = "unknown",
        tone: list[str] | None = None,
        layout_mode: str = "homepage",
        constraints: list[str] | None = None,
        anti_patterns: list[str] | None = None,
        desired_density: str = "balanced",
        route_profile: str = "hybrid_v4",
        rerank_mode: str = "shadow",
        rerank_model: str | None = None,
        reference_image_paths: list[str] | None = None,
        full_code_mode: bool = True,
        include_source_excerpts: bool = True,
        code_profile: str = "code_first",
        packet_intent: str = "balanced",
        include_optional_patterns: bool = True,
        optional_pattern_count: int = 8,
        max_source_chars: int | None = None,
    ) -> str:
        result = export_opencode_bundle(
            resolved,
            surface=surface,
            task=task,
            surface_kind=surface_kind,
            task_archetype=task_archetype,
            output_dir=output_dir or None,
            token_mode=token_mode,
            stack=stack,
            tone=tone,
            layout_mode=layout_mode,
            constraints=constraints,
            anti_patterns=anti_patterns,
            desired_density=desired_density,
            route_profile=route_profile,
            rerank_mode=rerank_mode,
            rerank_model=rerank_model,
            reference_image_paths=reference_image_paths,
            full_code_mode=full_code_mode,
            include_source_excerpts=include_source_excerpts,
            code_profile=code_profile,
            packet_intent=packet_intent,
            include_optional_patterns=include_optional_patterns,
            optional_pattern_count=optional_pattern_count,
            max_source_chars=max_source_chars,
        )
        return json.dumps(result, indent=2)

    @server.tool(name="route_alternatives", description="Explain top anchor/support candidates and examples that would rank if the strict preferred-example gate were softened.")
    def tool_route_alternatives(request_json: str) -> str:
        return json.dumps(route_alternatives(resolved, request_json), indent=2)

    @server.tool(name="donor_starvation_audit", description="Report donor-starvation status, dropped-example counters, mechanical donors, and library remediation hints.")
    def tool_donor_starvation_audit(request_json: str) -> str:
        return json.dumps(donor_starvation_audit(resolved, request_json), indent=2)

    @server.tool(name="code_density_metrics", description="Return code-density metrics for a fresh resolve without rendering the full packet to the caller.")
    def tool_code_density_metrics(request_json: str) -> str:
        return json.dumps(code_density_metrics(resolved, request_json), indent=2)

    @server.tool(name="audit_source_hygiene", description="Audit support-bank donor source for identity, proof, testimonial, and raster/external-asset leakage.")
    def tool_audit_source_hygiene(pack_id: str | None = None, example_id: str | None = None, max_files: int = 200) -> str:
        return json.dumps(audit_source_hygiene(resolved, pack_id=pack_id, example_id=example_id, max_files=max_files), indent=2)

    @server.tool(name="validate_design_router", description="Validate repo root, rules, index, manifests, and source paths.")
    def tool_validate_design_router() -> str:
        return json.dumps(validate_design_router(resolved), indent=2)

    @server.tool(name="routing_quality_audit", description="Evaluate the active design router against the versioned train/calibration/hidden judgment ledger and return failures, calibration, and hybrid disagreements.")
    def tool_routing_quality_audit(profile: str = "hybrid_v4", ledger_path: str = "") -> str:
        return json.dumps(
            routing_quality_audit(
                resolved,
                profile=profile,
                ledger_path=ledger_path or None,
            ),
            indent=2,
        )

    @server.tool(name="build_visual_routing_index", description="Build or refresh the local structural visual index used as an optional hybrid retrieval channel.")
    def tool_build_visual_routing_index(output_path: str = "") -> str:
        return json.dumps(
            build_visual_routing_index(
                resolved,
                output_path=output_path or None,
            ),
            indent=2,
        )

    @server.tool(name="build_design_embedding_index", description="Build or refresh the optional local dense embedding index through an Ollama-compatible embedding endpoint.")
    def tool_build_design_embedding_index(
        model: str = "nomic-embed-text",
        endpoint: str = "",
        batch_size: int = 16,
        output_path: str = "",
    ) -> str:
        return json.dumps(
            build_design_embedding_index(
                resolved,
                model=model,
                endpoint=endpoint or None,
                batch_size=batch_size,
                output_path=output_path or None,
            ),
            indent=2,
        )

    @server.tool(name="run_golden_build_arena", description="Prepare or evaluate a routed-vs-unrouted Golden Build Arena run. Promotion always requires deterministic gates plus explicit human approval in the arena config.")
    def tool_run_golden_build_arena(
        config_path: str,
        output_dir: str,
        phase: str = "evaluate",
        route_profile: str = "hybrid_v5",
        token_mode: str = "unbounded",
        browser: bool = True,
        shots: bool = True,
    ) -> str:
        if phase == "prepare":
            result = prepare_golden_build_arena(
                resolved,
                config_path=config_path,
                output_dir=output_dir,
                route_profile=route_profile,
                token_mode=token_mode,
            )
        elif phase == "evaluate":
            result = run_golden_build_arena(
                resolved,
                config_path=config_path,
                output_dir=output_dir,
                browser=browser,
                shots=shots,
            )
        else:
            return json.dumps({"error": "phase must be 'prepare' or 'evaluate'"}, indent=2)
        return json.dumps(result, indent=2)

    @server.tool(name="resolve_knowledge_context", description="Route an engineering brief (backend/APIs/databases/reliability/agents/LLM/security/browser-automation/computer-use) to a Golden Book knowledge packet: distilled playbooks + micro cards + method skills. HOW TO CALL: write the brief in concrete action words describing what the system DOES (click, drive, charge, queue, retry, upload) — abstract audit-style summaries route poorly — and ALWAYS pass the user's original message VERBATIM as user_message (summaries strip the words that route). Returns picks, confidence, skill_picks, abstain flag, and the packet — APPLY the packet per its USE CONTRACT header line. If abstain=true, do NOT silently proceed without the book: follow the returned retry_guide (nearest chapters as symptom lines + exactly how to re-call). mode: micro (16k contexts) | compact (default) | standard.")
    def tool_resolve_knowledge_context(brief: str, mode: str = "compact", k: int = 2, user_message: str = "") -> str:
        from .knowledge_router import KnowledgeRouter
        result = KnowledgeRouter().resolve(brief, mode=mode, k=k, user_message=user_message)
        log_knowledge_route(result, brief, mode, k, user_message)
        return json.dumps(result, indent=2)

    @server.tool(name="validate_knowledge_router", description="Validate the Golden Book knowledge corpus: root exists, playbook/micro/skill counts, canned route and abstain checks.")
    def tool_validate_knowledge_router() -> str:
        from .knowledge_router import validate_knowledge_router
        return json.dumps(validate_knowledge_router(), indent=2)

    # ------------------------------------------------------------------
    # Facade dispatcher — single tool that routes to all Golden Book ops.
    # Workaround for Codex deferred-tool-discovery namespace drop (issue #23839).
    # Every call is structurally identical: golden_book(action="...", args={...})
    # ------------------------------------------------------------------
    @server.tool(
        name="golden_book",
        description=(
            "Golden Book dispatcher — one tool to rule them all. "
            "Pass action='resolve_design_context'|'resolve_knowledge_context'|'get_pattern_card'|'get_source_excerpt'|"
            "'inspect_design_library'|'route_alternatives'|'donor_starvation_audit'|"
            "'code_density_metrics'|'audit_source_hygiene'|'export_opencode_bundle'|"
            "'routing_quality_audit'|'build_visual_routing_index'|'build_design_embedding_index'|"
            "'run_golden_build_arena'|"
            "'validate_design_router'|'validate_knowledge_router' "
            "plus args (JSON object with the parameters for that action)."
        ),
    )
    def tool_golden_book(action: str, args: str = "{}") -> str:
        try:
            params = json.loads(args) if isinstance(args, str) else (args or {})
        except json.JSONDecodeError:
            return json.dumps({"error": f"Invalid JSON in args: {args!r}"}, indent=2)

        if action == "resolve_design_context":
            return tool_resolve_design_context(
                surface=params.get("surface", ""),
                task=params.get("task", ""),
                surface_kind=params.get("surface_kind"),
                task_archetype=params.get("task_archetype"),
                stack=params.get("stack", "unknown"),
                tone=params.get("tone"),
                layout_mode=params.get("layout_mode", "homepage"),
                constraints=params.get("constraints"),
                anti_patterns=params.get("anti_patterns"),
                token_mode=params.get("token_mode", "unbounded"),
                max_examples=params.get("max_examples", 3),
                donor_selection_mode=params.get("donor_selection_mode", "support_examples_v1"),
                donor_count=params.get("donor_count", 3),
                include_optional_patterns=params.get("include_optional_patterns", True),
                optional_pattern_count=params.get("optional_pattern_count", 8),
                route_profile=params.get("route_profile", "hybrid_v4"),
                rerank_mode=params.get("rerank_mode", "shadow"),
                rerank_model=params.get("rerank_model"),
                reference_image_paths=params.get("reference_image_paths"),
                pattern_lock=params.get("pattern_lock", False),
                full_code_mode=params.get("full_code_mode", True),
                include_full_library=params.get("include_full_library", False),
                host_browser_review=params.get("host_browser_review", False),
                local_model_profile=params.get("local_model_profile"),
                visual_quality_profile=params.get("visual_quality_profile", "strict_design_router_gpt55_mcp_v1"),
                code_profile=params.get("code_profile", "balanced"),
                packet_intent=params.get("packet_intent", "balanced"),
            )
        if action == "resolve_knowledge_context":
            return tool_resolve_knowledge_context(
                brief=params.get("brief", ""),
                mode=params.get("mode", "compact"),
                k=params.get("k", 2),
                user_message=params.get("user_message", ""),
            )
        if action == "get_source_excerpt":
            return tool_get_source_excerpt(
                pack_id=params.get("pack_id", ""),
                example_id=params.get("example_id"),
                token_mode=params.get("token_mode", "unbounded"),
                max_chars=params.get("max_chars"),
                include_full=params.get("include_full", True),
                include_section_snippets=params.get("include_section_snippets", True),
            )
        if action == "get_pattern_card":
            return tool_get_pattern_card(
                request_json=params.get("request_json", "{}"),
                pattern_id=params.get("pattern_id", ""),
                tier=params.get("tier", "M"),
            )
        if action == "inspect_design_library":
            return tool_inspect_design_library(
                include_examples=params.get("include_examples", False),
            )
        if action == "route_alternatives":
            return tool_route_alternatives(
                request_json=params.get("request_json", "{}"),
            )
        if action == "donor_starvation_audit":
            return tool_donor_starvation_audit(
                request_json=params.get("request_json", "{}"),
            )
        if action == "code_density_metrics":
            return tool_code_density_metrics(
                request_json=params.get("request_json", "{}"),
            )
        if action == "audit_source_hygiene":
            return tool_audit_source_hygiene(
                pack_id=params.get("pack_id"),
                example_id=params.get("example_id"),
                max_files=params.get("max_files", 200),
            )
        if action == "export_opencode_bundle":
            return tool_export_opencode_bundle(
                surface=params.get("surface", ""),
                task=params.get("task", ""),
                surface_kind=params.get("surface_kind"),
                task_archetype=params.get("task_archetype"),
                output_dir=params.get("output_dir", ""),
                token_mode=params.get("token_mode", "unbounded"),
                stack=params.get("stack", "unknown"),
                tone=params.get("tone"),
                layout_mode=params.get("layout_mode", "homepage"),
                constraints=params.get("constraints"),
                anti_patterns=params.get("anti_patterns"),
                desired_density=params.get("desired_density", "balanced"),
                route_profile=params.get("route_profile", "hybrid_v4"),
                rerank_mode=params.get("rerank_mode", "shadow"),
                rerank_model=params.get("rerank_model"),
                reference_image_paths=params.get("reference_image_paths"),
                full_code_mode=params.get("full_code_mode", True),
                include_source_excerpts=params.get("include_source_excerpts", True),
                code_profile=params.get("code_profile", "code_first"),
                packet_intent=params.get("packet_intent", "balanced"),
                include_optional_patterns=params.get("include_optional_patterns", True),
                optional_pattern_count=params.get("optional_pattern_count", 8),
                max_source_chars=params.get("max_source_chars"),
            )
        if action == "validate_design_router":
            return tool_validate_design_router()
        if action == "routing_quality_audit":
            return tool_routing_quality_audit(
                profile=params.get("profile", "hybrid_v4"),
                ledger_path=params.get("ledger_path", ""),
            )
        if action == "build_visual_routing_index":
            return tool_build_visual_routing_index(
                output_path=params.get("output_path", ""),
            )
        if action == "build_design_embedding_index":
            return tool_build_design_embedding_index(
                model=params.get("model", "nomic-embed-text"),
                endpoint=params.get("endpoint", ""),
                batch_size=params.get("batch_size", 16),
                output_path=params.get("output_path", ""),
            )
        if action == "run_golden_build_arena":
            return tool_run_golden_build_arena(
                config_path=params.get("config_path", ""),
                output_dir=params.get("output_dir", ""),
                phase=params.get("phase", "evaluate"),
                route_profile=params.get("route_profile", "hybrid_v5"),
                token_mode=params.get("token_mode", "unbounded"),
                browser=params.get("browser", True),
                shots=params.get("shots", True),
            )
        if action == "validate_knowledge_router":
            return tool_validate_knowledge_router()

        return json.dumps({
            "error": f"Unknown action: {action!r}",
            "valid_actions": [
                "resolve_design_context", "resolve_knowledge_context",
                "get_pattern_card", "get_source_excerpt", "inspect_design_library",
                "route_alternatives", "donor_starvation_audit",
                "code_density_metrics", "audit_source_hygiene",
                "export_opencode_bundle", "routing_quality_audit",
                "build_visual_routing_index", "build_design_embedding_index",
                "run_golden_build_arena",
                "validate_design_router",
                "validate_knowledge_router",
            ],
        }, indent=2)

    return server


create_design_router_gpt55_mcp_server = create_mcp_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lookbook-mcp",
        description="Start the Lookbook MCP stdio server.",
    )
    parser.add_argument("--repo-root", help="Repository containing goldensets/. Defaults to DESIGN_ROUTER_MCP_REPO_ROOT or cwd.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        server = create_mcp_server(args.repo_root)
    except MissingMcpDependencyError as exc:
        raise SystemExit(str(exc)) from exc
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
