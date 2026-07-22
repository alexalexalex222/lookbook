from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .routing_eval import compare_routing_profiles, write_routing_report
from .service import (
    audit_source_hygiene,
    build_index,
    build_design_embedding_index,
    build_visual_routing_index,
    code_density_metrics,
    donor_starvation_audit,
    export_opencode_bundle,
    get_pattern_card,
    inspect_design_library,
    prepare_golden_build_arena,
    resolve_design_packet,
    route_alternatives,
    run_golden_build_arena,
    validate_design_router,
)
from .schemas import DesignContextRequest


def _default_repo_root() -> Path:
    env_root = os.getenv("DESIGN_ROUTER_MCP_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "goldensets").is_dir() or (cwd / "src" / "design_router_mcp" / "goldensets").is_dir():
        return cwd
    module_root = Path(__file__).resolve().parent
    for candidate in (module_root.parent.parent, module_root):
        if (candidate / "goldensets").is_dir():
            return candidate.resolve()
    return cwd


def _load_request(request_file: str | None, request_json: str | None) -> DesignContextRequest:
    if request_file:
        return DesignContextRequest.model_validate_json(Path(request_file).read_text(encoding="utf-8"))
    if request_json:
        return DesignContextRequest.model_validate_json(request_json)
    stdin_payload = sys.stdin.read().strip()
    if stdin_payload:
        return DesignContextRequest.model_validate_json(stdin_payload)
    raise SystemExit("No request JSON provided. Use --request-file, --request-json, or stdin.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lookbook",
        description="Lookbook packet compiler — render and inspect frontend build packets.",
    )
    parser.add_argument("--repo-root", help="Repository containing goldensets/. Defaults to DESIGN_ROUTER_MCP_REPO_ROOT or cwd.")
    sub = parser.add_subparsers(dest="command")

    resolve = sub.add_parser("resolve", help="Render a packet from request JSON.")
    resolve.add_argument("--request-file")
    resolve.add_argument("--request-json")
    resolve.add_argument("--token-mode", default=None)
    resolve.add_argument("--code-profile", choices=["balanced", "code_first"], default=None)
    resolve.add_argument("--packet-intent", choices=["balanced", "code_first", "design_director", "visual_system", "implementation_blueprint"], default=None)
    resolve.add_argument("--output")

    alternatives = sub.add_parser("alternatives", help="Show top route alternatives and examples rejected by strict gates.")
    alternatives.add_argument("--request-file")
    alternatives.add_argument("--request-json")

    pattern_card = sub.add_parser("pattern-card", help="Expand one route-qualified optional Pattern Card.")
    pattern_card.add_argument("--request-file")
    pattern_card.add_argument("--request-json")
    pattern_card.add_argument("--pattern-id", required=True)
    pattern_card.add_argument("--tier", choices=["S", "M", "L"], default="M")

    audit = sub.add_parser("audit", help="Audit donor starvation for a request.")
    audit.add_argument("--request-file")
    audit.add_argument("--request-json")

    density = sub.add_parser("density", help="Return code-density metrics for a request.")
    density.add_argument("--request-file")
    density.add_argument("--request-json")

    list_cmd = sub.add_parser("list", help="List packs from the manifest index.")
    list_cmd.add_argument("--examples", action="store_true")

    sub.add_parser("validate", help="Validate local runtime and repo data.")

    hygiene = sub.add_parser("hygiene", help="Audit support-bank donor source for identity/proof/raster leakage.")
    hygiene.add_argument("--pack-id")
    hygiene.add_argument("--example-id")
    hygiene.add_argument("--max-files", type=int, default=200)

    index = sub.add_parser("index", help="Build or refresh the SQLite manifest index.")
    index.add_argument("--no-refresh", action="store_true")

    visual_index = sub.add_parser("visual-index", help="Build the structural visual retrieval index.")
    visual_index.add_argument("--output")

    embedding_index = sub.add_parser("embedding-index", help="Build the optional local dense embedding index.")
    embedding_index.add_argument("--model", default="nomic-embed-text")
    embedding_index.add_argument("--endpoint")
    embedding_index.add_argument("--batch-size", type=int, default=16)
    embedding_index.add_argument("--output")

    routing_eval = sub.add_parser("routing-eval", help="Evaluate routing against the versioned judgment ledger.")
    routing_eval.add_argument("--profile", default="hybrid_v4")
    routing_eval.add_argument("--ledger")
    routing_eval.add_argument("--output-dir", default="evals/reports/router-latest")
    routing_eval.add_argument("--compare", action="store_true")
    routing_eval.add_argument("--compare-profile", action="append")

    arena = sub.add_parser("arena", help="Prepare or evaluate a routed-vs-unrouted Golden Build Arena run.")
    arena.add_argument("--config", required=True)
    arena.add_argument("--output-dir", default="evals/arena/latest")
    arena.add_argument("--phase", choices=["prepare", "evaluate"], default="evaluate")
    arena.add_argument("--route-profile", default="hybrid_v5")
    arena.add_argument("--token-mode", default="unbounded")
    arena.add_argument("--no-browser", action="store_true")
    arena.add_argument("--no-shots", action="store_true")

    export = sub.add_parser("export", help="Export an OpenCode bundle.")
    export.add_argument("--surface", required=True)
    export.add_argument("--task", required=True)
    export.add_argument("--surface-kind")
    export.add_argument("--task-archetype")
    export.add_argument("--output-dir")
    export.add_argument("--token-mode", default="unbounded")
    export.add_argument("--stack", default="unknown")
    export.add_argument("--tone", action="append")
    export.add_argument("--layout-mode", default="homepage")
    export.add_argument("--constraint", action="append")
    export.add_argument("--anti-pattern", action="append")
    export.add_argument("--desired-density", default="balanced")
    export.add_argument("--route-profile", default="hybrid_v4")
    export.add_argument("--rerank-mode", choices=["off", "shadow", "active"], default="shadow")
    export.add_argument("--rerank-model")
    export.add_argument("--reference-image-path", action="append")
    export.add_argument(
        "--full-code-mode",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Compatibility flag. Selected routed source is complete either way.",
    )
    export.add_argument("--no-source-excerpts", action="store_true")
    export.add_argument("--code-profile", choices=["balanced", "code_first"], default="code_first")
    export.add_argument("--packet-intent", choices=["balanced", "code_first", "design_director", "visual_system", "implementation_blueprint"], default="balanced")
    export.add_argument("--no-optional-patterns", action="store_true")
    export.add_argument("--optional-pattern-count", type=int, default=8)
    export.add_argument(
        "--max-source-chars",
        type=int,
        default=None,
        help="Legacy compatibility argument; source exports are not clipped.",
    )

    # Backward-compatible root-level resolve options.
    parser.add_argument("--request-file")
    parser.add_argument("--request-json")
    parser.add_argument("--output")
    parser.add_argument("--token-mode", default=None)
    parser.add_argument("--code-profile", choices=["balanced", "code_first"], default=None)
    parser.add_argument("--packet-intent", choices=["balanced", "code_first", "design_director", "visual_system", "implementation_blueprint"], default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else _default_repo_root()

    if args.command == "list":
        print(json.dumps(inspect_design_library(repo_root, include_examples=args.examples), indent=2))
        return 0
    if args.command == "validate":
        print(json.dumps(validate_design_router(repo_root), indent=2))
        return 0
    if args.command == "hygiene":
        print(json.dumps(audit_source_hygiene(repo_root, pack_id=args.pack_id, example_id=args.example_id, max_files=args.max_files), indent=2))
        return 0
    if args.command == "index":
        print(json.dumps(build_index(repo_root, refresh=not args.no_refresh), indent=2))
        return 0
    if args.command == "visual-index":
        print(json.dumps(build_visual_routing_index(repo_root, output_path=args.output), indent=2))
        return 0
    if args.command == "embedding-index":
        print(
            json.dumps(
                build_design_embedding_index(
                    repo_root,
                    model=args.model,
                    endpoint=args.endpoint,
                    batch_size=args.batch_size,
                    output_path=args.output,
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "routing-eval":
        if args.compare:
            profiles = args.compare_profile or ["data_driven_v2", "hybrid_shadow_v1", "hybrid_v4", "hybrid_v5"]
            print(
                json.dumps(
                    compare_routing_profiles(
                        repo_root,
                        profiles=profiles,
                        ledger_path=args.ledger,
                    ),
                    indent=2,
                )
            )
            return 0
        report = write_routing_report(
            repo_root,
            args.output_dir,
            profile=args.profile,
            ledger_path=args.ledger,
        )
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "arena":
        if args.phase == "prepare":
            result = prepare_golden_build_arena(
                repo_root,
                config_path=args.config,
                output_dir=args.output_dir,
                route_profile=args.route_profile,
                token_mode=args.token_mode,
            )
        else:
            result = run_golden_build_arena(
                repo_root,
                config_path=args.config,
                output_dir=args.output_dir,
                browser=not args.no_browser,
                shots=not args.no_shots,
            )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "alternatives":
        request = _load_request(args.request_file, args.request_json)
        print(json.dumps(route_alternatives(repo_root, request), indent=2))
        return 0
    if args.command == "pattern-card":
        request = _load_request(args.request_file, args.request_json)
        print(
            json.dumps(
                get_pattern_card(
                    repo_root,
                    request,
                    pattern_id=args.pattern_id,
                    tier=args.tier,
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "audit":
        request = _load_request(args.request_file, args.request_json)
        print(json.dumps(donor_starvation_audit(repo_root, request), indent=2))
        return 0
    if args.command == "density":
        request = _load_request(args.request_file, args.request_json)
        print(json.dumps(code_density_metrics(repo_root, request), indent=2))
        return 0
    if args.command == "export":
        print(
            json.dumps(
                export_opencode_bundle(
                    repo_root,
                    surface=args.surface,
                    task=args.task,
                    surface_kind=args.surface_kind,
                    task_archetype=args.task_archetype,
                    output_dir=args.output_dir,
                    token_mode=args.token_mode,
                    stack=args.stack,
                    tone=args.tone,
                    layout_mode=args.layout_mode,
                    constraints=args.constraint,
                    anti_patterns=args.anti_pattern,
                    desired_density=args.desired_density,
                    route_profile=args.route_profile,
                    rerank_mode=args.rerank_mode,
                    rerank_model=args.rerank_model,
                    reference_image_paths=args.reference_image_path,
                    full_code_mode=args.full_code_mode,
                    include_source_excerpts=not args.no_source_excerpts,
                    code_profile=args.code_profile,
                    packet_intent=args.packet_intent,
                    include_optional_patterns=not args.no_optional_patterns,
                    optional_pattern_count=args.optional_pattern_count,
                    max_source_chars=args.max_source_chars,
                ),
                indent=2,
            )
        )
        return 0

    request_file = args.request_file
    request_json = args.request_json
    token_mode = args.token_mode
    output = args.output
    code_profile = args.code_profile
    packet_intent = args.packet_intent
    if args.command == "resolve":
        request_file = args.request_file
        request_json = args.request_json
        token_mode = args.token_mode
        output = args.output
        code_profile = args.code_profile
        packet_intent = args.packet_intent

    request = _load_request(request_file, request_json)
    packet_markdown = resolve_design_packet(request, repo_root, token_mode=token_mode, code_profile=code_profile, packet_intent=packet_intent)
    if output:
        Path(output).expanduser().resolve().write_text(packet_markdown + "\n", encoding="utf-8")
    else:
        print(packet_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
