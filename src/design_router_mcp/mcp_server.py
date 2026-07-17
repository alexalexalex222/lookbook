from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .service import (
    audit_source_hygiene,
    code_density_metrics,
    donor_starvation_audit,
    export_opencode_bundle,
    get_source_excerpt,
    inspect_design_library,
    route_alternatives,
    resolve_design_context,
    resolve_design_packet,
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
            "TOOL BUDGET (hard): for a normal build, call resolve_design_context ONCE, then write files. "
            "Do not call get_source_excerpt, inspect_design_library, route_alternatives, donor_starvation_audit, "
            "audit_source_hygiene, validate_design_router, or resolve_design_context a second time after a non-empty packet. "
            "Optional second call only: export_opencode_bundle if you need the packet on disk. Max 1–2 design-router tools per user task. "
            "Defaults already ship full depth: token_mode=full_selected, full_code_mode=true, code_profile=code_first "
            "(complete primary pattern + all contracts in one packet). "
            "Treat every contract in the returned packet as a hard floor for shipped code. "
            "Read V3 director sections when present (Composition Brief, Visual Artifact Specs, Local Model Failure Patterns). "
            "For engineering/backend briefs use resolve_knowledge_context once (not design). "
            "Never invent identity, copy, claims, names, statistics, testimonials, awards, or images. "
            "Borrow composition from the anchor; build the rest from the brief."
        ),
    )

    @server.tool(
        name="resolve_design_context",
        description=(
            "ONE-CALL full build packet: routes the brief and returns mandatory depth + complete primary pattern source. "
            "Defaults (full_selected + full_code_mode + code_first) are enough — do not re-call or chain get_source_excerpt. "
            "After a non-empty packet, stop design-router tools and implement."
        ),
    )
    def tool_resolve_design_context(
        surface: str,
        task: str,
        stack: str = "unknown",
        tone: list[str] | None = None,
        layout_mode: str = "homepage",
        constraints: list[str] | None = None,
        anti_patterns: list[str] | None = None,
        token_mode: str = "full_selected",
        max_examples: int = 3,
        donor_selection_mode: str = "support_examples_v1",
        donor_count: int = 3,
        pattern_lock: bool = False,
        full_code_mode: bool = True,
        include_full_library: bool = False,
        host_browser_review: bool = False,
        local_model_profile: str | None = None,
        visual_quality_profile: str = "strict_design_router_gpt55_mcp_v1",
        code_profile: str = "code_first",
        packet_intent: str = "balanced",
    ) -> str:
        packet = resolve_design_context(
            resolved,
            surface=surface,
            task=task,
            stack=stack,
            tone=tone,
            layout_mode=layout_mode,
            constraints=constraints,
            anti_patterns=anti_patterns,
            token_mode=token_mode,
            max_examples=max_examples,
            donor_selection_mode=donor_selection_mode,
            donor_count=donor_count,
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

    @server.tool(
        name="get_source_excerpt",
        description=(
            "OPTIONAL recovery only: load a pack/example source when resolve_design_context was called "
            "with a peek token_mode that omitted full code. Do NOT use after a normal full_selected resolve — "
            "that packet already includes the primary pattern."
        ),
    )
    def tool_get_source_excerpt(
        pack_id: str,
        example_id: str | None = None,
        token_mode: str = "compact",
        max_chars: int = 3000,
        include_full: bool = False,
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

    @server.tool(name="export_opencode_bundle", description="Write PACKET.md, source/budget metadata, and selected SOURCE_EXCERPTS/*.md files for OpenCode/local coding agents.")
    def tool_export_opencode_bundle(
        surface: str,
        task: str,
        output_dir: str = "",
        token_mode: str = "full_selected",
        stack: str = "unknown",
        tone: list[str] | None = None,
        full_code_mode: bool = True,
        include_source_excerpts: bool = True,
        code_profile: str = "code_first",
        packet_intent: str = "balanced",
        max_source_chars: int = 8000,
    ) -> str:
        result = export_opencode_bundle(
            resolved,
            surface=surface,
            task=task,
            output_dir=output_dir or None,
            token_mode=token_mode,
            stack=stack,
            tone=tone,
            full_code_mode=full_code_mode,
            include_source_excerpts=include_source_excerpts,
            code_profile=code_profile,
            packet_intent=packet_intent,
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

    @server.tool(
        name="resolve_knowledge_context",
        description=(
            "ONE-CALL knowledge packet for engineering briefs (backend/APIs/reliability/agents/LLM/security/browser-automation). "
            "Write the brief in concrete action words; pass the user's original message VERBATIM as user_message. "
            "After a non-empty non-abstain packet: APPLY it and do NOT re-call. "
            "Only if abstain=true may you re-call once using retry_guide (2-call max). "
            "mode: micro | compact (default) | standard."
        ),
    )
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
            "Pass action='resolve_design_context'|'resolve_knowledge_context'|'get_source_excerpt'|"
            "'inspect_design_library'|'route_alternatives'|'donor_starvation_audit'|"
            "'code_density_metrics'|'audit_source_hygiene'|'export_opencode_bundle'|"
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
                stack=params.get("stack", "unknown"),
                tone=params.get("tone"),
                layout_mode=params.get("layout_mode", "homepage"),
                constraints=params.get("constraints"),
                anti_patterns=params.get("anti_patterns"),
                token_mode=params.get("token_mode", "full_selected"),
                max_examples=params.get("max_examples", 3),
                donor_selection_mode=params.get("donor_selection_mode", "support_examples_v1"),
                donor_count=params.get("donor_count", 3),
                pattern_lock=params.get("pattern_lock", False),
                full_code_mode=params.get("full_code_mode", True),
                include_full_library=params.get("include_full_library", False),
                host_browser_review=params.get("host_browser_review", False),
                local_model_profile=params.get("local_model_profile"),
                visual_quality_profile=params.get("visual_quality_profile", "strict_design_router_gpt55_mcp_v1"),
                code_profile=params.get("code_profile", "code_first"),
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
                token_mode=params.get("token_mode", "compact"),
                max_chars=params.get("max_chars", 3000),
                include_full=params.get("include_full", False),
                include_section_snippets=params.get("include_section_snippets", True),
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
                output_dir=params.get("output_dir", ""),
                token_mode=params.get("token_mode", "compact"),
                stack=params.get("stack", "unknown"),
                tone=params.get("tone"),
                full_code_mode=params.get("full_code_mode", False),
                include_source_excerpts=params.get("include_source_excerpts", True),
                code_profile=params.get("code_profile", "code_first"),
                packet_intent=params.get("packet_intent", "balanced"),
                max_source_chars=params.get("max_source_chars", 8000),
            )
        if action == "validate_design_router":
            return tool_validate_design_router()
        if action == "validate_knowledge_router":
            return tool_validate_knowledge_router()

        return json.dumps({
            "error": f"Unknown action: {action!r}",
            "valid_actions": [
                "resolve_design_context", "resolve_knowledge_context",
                "get_source_excerpt", "inspect_design_library",
                "route_alternatives", "donor_starvation_audit",
                "code_density_metrics", "audit_source_hygiene",
                "export_opencode_bundle", "validate_design_router",
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
