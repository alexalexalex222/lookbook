from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .index_store import build_repository_index
from .service import (
    audit_source_hygiene,
    build_index,
    code_density_metrics,
    donor_starvation_audit,
    export_opencode_bundle,
    inspect_design_library,
    resolve_design_packet,
    route_alternatives,
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
        prog="design-router-gpt-5.5-packet",
        description="Render or inspect Design Router GPT-5.5 MCP packets.",
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

    audit = sub.add_parser("audit", help="Audit donor starvation for a request.")
    audit.add_argument("--request-file")
    audit.add_argument("--request-json")

    density = sub.add_parser("density", help="Return code-density metrics for a request.")
    density.add_argument("--request-file")
    density.add_argument("--request-json")

    list_cmd = sub.add_parser("list", help="List packs from the manifest index.")
    list_cmd.add_argument("--examples", action="store_true")

    validate = sub.add_parser("validate", help="Validate local runtime and repo data.")

    hygiene = sub.add_parser("hygiene", help="Audit support-bank donor source for identity/proof/raster leakage.")
    hygiene.add_argument("--pack-id")
    hygiene.add_argument("--example-id")
    hygiene.add_argument("--max-files", type=int, default=200)

    index = sub.add_parser("index", help="Build or refresh the SQLite manifest index.")
    index.add_argument("--no-refresh", action="store_true")

    export = sub.add_parser("export", help="Export an OpenCode bundle.")
    export.add_argument("--surface", required=True)
    export.add_argument("--task", required=True)
    export.add_argument("--output-dir")
    export.add_argument("--token-mode", default="compact")
    export.add_argument("--stack", default="unknown")
    export.add_argument("--tone", action="append")
    export.add_argument("--full-code-mode", action="store_true")
    export.add_argument("--no-source-excerpts", action="store_true")
    export.add_argument("--code-profile", choices=["balanced", "code_first"], default="code_first")
    export.add_argument("--packet-intent", choices=["balanced", "code_first", "design_director", "visual_system", "implementation_blueprint"], default="balanced")
    export.add_argument("--max-source-chars", type=int, default=8000)

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
    if args.command == "alternatives":
        request = _load_request(args.request_file, args.request_json)
        print(json.dumps(route_alternatives(repo_root, request), indent=2))
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
                    output_dir=args.output_dir,
                    token_mode=args.token_mode,
                    stack=args.stack,
                    tone=args.tone,
                    full_code_mode=args.full_code_mode,
                    include_source_excerpts=not args.no_source_excerpts,
                    code_profile=args.code_profile,
                    packet_intent=args.packet_intent,
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
