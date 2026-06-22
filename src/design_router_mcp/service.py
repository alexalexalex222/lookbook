from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .index_store import build_repository_index, write_sqlite_index
from .lazy_loader import PackStore, _extract_section_job_excerpts_from_text
from .normalizer import normalize_request, request_tokens
from .renderer import build_context_packet, estimate_tokens
from .sanitizer import sanitize_source_text
from .router import DesignRouter, _tokens_from_text
from .rules import RoutingRules, load_routing_rules
from .sanitizer import hygiene_hits_to_dicts, scan_source_hygiene
from .schemas import DesignContextRequest, RenderedPacket, TokenMode
from .validation import validate_repository

CODE_SOURCE_SUFFIXES = {".html", ".htm", ".css", ".tsx", ".ts", ".jsx", ".js", ".md"}


def coerce_request(payload: str | dict[str, Any] | DesignContextRequest) -> DesignContextRequest:
    if isinstance(payload, DesignContextRequest):
        return payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    return DesignContextRequest.model_validate(payload)


@lru_cache(maxsize=8)
def _cached_router(repo_root_str: str, rules_path: str | None = None) -> DesignRouter:
    return DesignRouter.from_repo(Path(repo_root_str), rules_path=rules_path)


def get_router(repo_root: Path | str, *, rules_path: Path | str | None = None, refresh_index: bool = False) -> DesignRouter:
    root = Path(repo_root).expanduser().resolve()
    if refresh_index:
        return DesignRouter.from_repo(root, refresh_index=True, rules_path=rules_path)
    return _cached_router(str(root), str(Path(rules_path).expanduser().resolve()) if rules_path else None)


def resolve_design_packet(
    payload: str | dict[str, Any] | DesignContextRequest,
    repo_root: Path | str,
    *,
    token_mode: TokenMode | str | None = None,
    code_profile: str | None = None,
    packet_intent: str | None = None,
    rules_path: Path | str | None = None,
) -> str:
    request = coerce_request(payload)
    if token_mode is not None:
        request = request.model_copy(update={"token_mode": token_mode})
    if code_profile is not None:
        request = request.model_copy(update={"code_profile": code_profile})
    if packet_intent is not None:
        request = request.model_copy(update={"packet_intent": packet_intent})
    router = get_router(repo_root, rules_path=rules_path)
    resolution = router.route(request)
    packet = build_context_packet(request, resolution, token_mode=token_mode, rules=router.rules)
    return packet.markdown


def resolve_design_context(
    repo_root: Path | str,
    *,
    surface: str,
    task: str,
    stack: str = "unknown",
    tone: list[str] | None = None,
    layout_mode: str = "homepage",
    constraints: list[str] | None = None,
    anti_patterns: list[str] | None = None,
    desired_density: str = "balanced",
    max_examples: int = 3,
    donor_selection_mode: str = "support_examples_v1",
    donor_count: int = 3,
    route_profile: str = "data_driven_v2",
    packet_profile: str = "compact_v2",
    include_full_library: bool = False,
    pattern_lock: bool = False,
    pattern_lock_strict: bool = False,
    pattern_lock_exact: bool = False,
    full_code_mode: bool = False,
    prefer_angular_geometry: bool = True,
    host_browser_review: bool = False,
    token_mode: TokenMode | str = "compact",
    local_model_profile: str | None = None,
    visual_quality_profile: str = "strict_design_router_gpt55_mcp_v1",
    code_profile: str = "balanced",
    packet_intent: str = "balanced",
    rules_path: Path | str | None = None,
) -> RenderedPacket:
    request = DesignContextRequest(
        surface=surface,
        task=task,
        stack=stack,
        tone=list(tone or []),
        layout_mode=layout_mode,
        constraints=list(constraints or []),
        anti_patterns=list(anti_patterns or []),
        desired_density=desired_density,
        max_examples=max_examples,
        donor_selection_mode=donor_selection_mode,  # type: ignore[arg-type]
        donor_count=donor_count,
        route_profile=route_profile,  # type: ignore[arg-type]
        packet_profile=packet_profile,  # type: ignore[arg-type]
        include_full_library=include_full_library,
        pattern_lock=pattern_lock,
        pattern_lock_strict=pattern_lock_strict,
        pattern_lock_exact=pattern_lock_exact,
        full_code_mode=full_code_mode,
        prefer_angular_geometry=prefer_angular_geometry,
        host_browser_review=host_browser_review,
        token_mode=token_mode,  # type: ignore[arg-type]
        local_model_profile=local_model_profile,  # type: ignore[arg-type]
        visual_quality_profile=visual_quality_profile,  # type: ignore[arg-type]
        code_profile=code_profile,  # type: ignore[arg-type]
        packet_intent=packet_intent,  # type: ignore[arg-type]
    )
    router = get_router(repo_root, rules_path=rules_path)
    resolution = router.route(request)
    return build_context_packet(request, resolution, token_mode=token_mode, rules=router.rules)


def _score_dict(score: Any) -> dict[str, Any]:
    return score.model_dump(mode="json") if hasattr(score, "model_dump") else dict(score)


def _rank_examples_without_strict_gate(router: DesignRouter, request: DesignContextRequest, normalized: Any, support_record: Any | None, limit: int = 5) -> list[dict[str, Any]]:
    if support_record is None:
        return []
    manifest = support_record.manifest
    vertical = router.rules.verticals.get(normalized.specialty_service_class or "")
    prefer_tokens = set(vertical.prefer_example_tokens) if vertical else set()
    blocked_tokens = set(vertical.blocked_example_tokens) if vertical else set()
    stop_tokens = set(router.rules.generic_example_stop_tokens)
    tokens = request_tokens(request)
    weights = router.rules.weights
    rows: list[dict[str, Any]] = []
    for example_id in manifest.example_ids:
        example_tokens = _tokens_from_text(example_id.replace("-", " ").replace("_", " "))
        strengths = set(manifest.example_strengths.get(example_id, []))
        motifs = set(manifest.motif_overlaps.get(example_id, []))
        strength_overlap = sorted(strengths.intersection(normalized.strength_tags))
        motif_overlap = sorted(motifs.intersection(normalized.motif_tags))
        request_overlap = sorted(tokens.intersection(example_tokens).difference(stop_tokens))
        preferred_overlap = sorted(prefer_tokens.intersection(example_tokens))
        blocked_overlap = sorted(blocked_tokens.intersection(example_tokens))
        score = 0
        score += len(strength_overlap) * weights.get("strength", 3)
        score += len(motif_overlap) * weights.get("motif", 4)
        score += min(12, len(request_overlap) * weights.get("request_token_example", 3))
        score += len(preferred_overlap) * weights.get("preferred_example_token", 12)
        score += len(set(manifest.example_ux_roles.get(example_id, [])).intersection(router._infer_request_ux_roles(request, normalized))) * weights.get("ux_role_overlap", 5)
        would_fail: list[str] = []
        if blocked_overlap and not preferred_overlap:
            would_fail.append("blocked_tokens")
        if normalized.specialty_service_class == "combat_sports" and not preferred_overlap:
            would_fail.append("preferred_required")
        rows.append(
            {
                "example_id": example_id,
                "score_without_preferred_gate": int(score),
                "strength_overlap": strength_overlap,
                "motif_overlap": motif_overlap,
                "matched_tokens": sorted(set(request_overlap + preferred_overlap)),
                "ux_roles": manifest.example_ux_roles.get(example_id, []),
                "blocked_token_hits": blocked_overlap,
                "would_fail_existing_gate": would_fail,
            }
        )
    rows.sort(key=lambda row: (-row["score_without_preferred_gate"], row["example_id"]))
    return rows[:limit]


def route_alternatives(repo_root: Path | str, request_payload: str | dict[str, Any] | DesignContextRequest, *, rules_path: Path | str | None = None) -> dict[str, Any]:
    request = coerce_request(request_payload)
    router = get_router(repo_root, rules_path=rules_path)
    normalized = normalize_request(request, router.rules)
    anchor_candidates = sorted(
        ((record, router._score_record(request, normalized, record)) for record in router.index.anchors),
        key=lambda item: (-item[1].total, item[0].manifest.token_budget_hint, item[0].manifest.pack_id),
    )
    support_candidates = sorted(
        ((record, router._score_record(request, normalized, record)) for record in router.index.support_banks),
        key=lambda item: (-item[1].total, item[0].manifest.pack_id),
    )
    support_record = support_candidates[0][0] if support_candidates else None
    return {
        "vertical": normalized.specialty_service_class,
        "top_anchors": [_score_dict(score) for _, score in anchor_candidates[:3]],
        "top_support_banks": [_score_dict(score) for _, score in support_candidates[:3]],
        "examples_without_preferred_gate": _rank_examples_without_strict_gate(router, request, normalized, support_record, limit=5),
    }


def donor_starvation_audit(repo_root: Path | str, request_payload: str | dict[str, Any] | DesignContextRequest, *, rules_path: Path | str | None = None) -> dict[str, Any]:
    request = coerce_request(request_payload)
    router = get_router(repo_root, rules_path=rules_path)
    resolution = router.route(request)
    meta = resolution.route_meta.get("donor_starvation", {})
    support = resolution.support_bank.manifest if resolution.support_bank is not None else None
    examples_with_roles = 0
    total_examples = 0
    if support is not None:
        total_examples = len(support.example_ids)
        examples_with_roles = sum(1 for example_id in support.example_ids if support.example_ux_roles.get(example_id))
    starved = meta.get("native_count") == 0
    recommendations = []
    if starved:
        recommendations.append(f"Add native support examples for vertical `{resolution.normalized_request.specialty_service_class or 'general_local_service'}`.")
        recommendations.append("Keep using mechanical donors only for UX roles until native examples exist.")
    if total_examples and examples_with_roles < total_examples:
        recommendations.append("Populate example_ux_roles for every support-bank example.")
    return {
        "starved": starved,
        "vertical": resolution.normalized_request.specialty_service_class,
        "support_bank": support.pack_id if support is not None else None,
        "native_count": meta.get("native_count", 0),
        "mechanical_donor_count": meta.get("mechanical_donor_count", 0),
        "mechanical_donors": meta.get("mechanical_donors", []),
        "request_ux_roles": meta.get("request_ux_roles", []),
        "dropped_for": meta.get("dropped_for", {}),
        "reason": meta.get("reason", ""),
        "support_bank_role_coverage": {"examples_with_roles": examples_with_roles, "total_examples": total_examples},
        "library_recommendations": recommendations,
    }


def code_density_metrics(repo_root: Path | str, request_payload: str | dict[str, Any] | DesignContextRequest, *, rules_path: Path | str | None = None) -> dict[str, Any]:
    request = coerce_request(request_payload)
    router = get_router(repo_root, rules_path=rules_path)
    resolution = router.route(request)
    packet = build_context_packet(request, resolution, token_mode=request.token_mode, rules=router.rules)
    return dict(packet.metadata.get("code_density", {}))


def _resolve_manifest_path(pack_dir: Path, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        return path
    return pack_dir / path


def _path_relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path)


def _code_source_files_for_path(path: Path, *, root: Path) -> list[str]:
    if path.is_file():
        return [_path_relative_to(path, root)] if path.suffix.lower() in CODE_SOURCE_SUFFIXES else []
    if not path.is_dir():
        return []
    preferred = ["index.html", "styles.css", "app_page.tsx", "page.tsx", "App.tsx", "app.jsx", "app_globals.css", "globals.css", "style.css"]
    files: list[Path] = []
    for name in preferred:
        candidate = path / name
        if candidate.is_file() and candidate.suffix.lower() in CODE_SOURCE_SUFFIXES:
            files.append(candidate)
    seen = {candidate.resolve() for candidate in files}
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in CODE_SOURCE_SUFFIXES:
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        files.append(candidate)
        seen.add(resolved)
        if len(files) >= 12:
            break
    return [_path_relative_to(candidate, root) for candidate in files]


def _source_path_status(record: Any, rel: str) -> dict[str, Any]:
    path = _resolve_manifest_path(record.pack_dir, rel)
    source_files = _code_source_files_for_path(path, root=record.pack_dir)
    return {
        "path": rel,
        "exists": path.exists(),
        "kind": "dir" if path.is_dir() else "file" if path.is_file() else "missing",
        "source_files": source_files,
        "source_file_count": len(source_files),
        "absolute": Path(rel).is_absolute(),
    }


def _example_source_status(record: Any, example_id: str) -> dict[str, Any]:
    source_dir = record.manifest.source_dirs.get(example_id, "")
    source_path = _resolve_manifest_path(record.pack_dir, source_dir) if source_dir else record.pack_dir / "examples" / example_id
    source_files = _code_source_files_for_path(source_path, root=record.pack_dir)
    return {
        "example_id": example_id,
        "source_dir": source_dir,
        "has_source": source_path.exists() and bool(source_files),
        "source_files": source_files,
        "source_file_count": len(source_files),
        "preview_path": record.manifest.preview_paths.get(example_id, ""),
        "targeted_pull": (
            f"get_source_excerpt(pack_id=\"{record.manifest.pack_id}\", "
            f"example_id=\"{example_id}\", include_full=true, include_section_snippets=true)"
        ),
    }


def _support_record_for_example(index: Any, example_id: str, *, preferred_pack_ids: list[str]) -> Any | None:
    for pack_id in preferred_pack_ids:
        record = index.by_id.get(pack_id)
        if record is not None and record.manifest.role == "support_bank" and example_id in record.manifest.example_ids:
            return record
    for record in index.support_banks:
        if example_id in record.manifest.example_ids:
            return record
    return None


def _safe_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return slug[:120] or "source"


def _hygiene_source_files(path: Path, *, limit: int = 12) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in CODE_SOURCE_SUFFIXES else []
    if not path.is_dir():
        return []
    preferred = ["index.html", "styles.css", "app_page.tsx", "page.tsx", "App.tsx", "app.jsx", "app_globals.css", "globals.css", "style.css"]
    files: list[Path] = []
    for name in preferred:
        candidate = path / name
        if candidate.is_file() and candidate.suffix.lower() in CODE_SOURCE_SUFFIXES:
            files.append(candidate)
    seen = {candidate.resolve() for candidate in files}
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in CODE_SOURCE_SUFFIXES:
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        files.append(candidate)
        seen.add(resolved)
        if len(files) >= limit:
            break
    return files


def audit_source_hygiene(repo_root: Path | str, *, pack_id: str | None = None, example_id: str | None = None, max_files: int = 200) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    index = build_repository_index(root)
    rows: list[dict[str, Any]] = []
    total_hits = 0
    scanned_files = 0
    records = [index.by_id[pack_id]] if pack_id else list(index.support_banks)
    for record in records:
        if record.manifest.role != "support_bank":
            continue
        example_ids = [example_id] if example_id else list(record.manifest.example_ids)
        for current_example_id in example_ids:
            if current_example_id not in record.manifest.example_ids:
                continue
            source_dir = record.manifest.source_dirs.get(current_example_id, "")
            source_path = _resolve_manifest_path(record.pack_dir, source_dir) if source_dir else record.pack_dir / "examples" / current_example_id
            for source_file in _hygiene_source_files(source_path):
                if scanned_files >= max_files:
                    break
                scanned_files += 1
                try:
                    text = source_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                hits = scan_source_hygiene(text)
                if not hits:
                    continue
                total_hits += len(hits)
                rows.append(
                    {
                        "pack_id": record.manifest.pack_id,
                        "example_id": current_example_id,
                        "path": _path_relative_to(source_file, root),
                        "hit_count": len(hits),
                        "kinds": sorted({hit.kind for hit in hits}),
                        "sample_hits": hygiene_hits_to_dicts(hits, limit=8),
                    }
                )
            if scanned_files >= max_files:
                break
    return {
        "repo_root": str(root),
        "pack_id": pack_id,
        "example_id": example_id,
        "scanned_files": scanned_files,
        "files_with_hits": len(rows),
        "hit_count": total_hits,
        "truncated": scanned_files >= max_files,
        "results": rows,
    }


def inspect_design_library(repo_root: Path | str, *, include_examples: bool = False, rules_path: Path | str | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    index = build_repository_index(root)
    rows = index.to_summary()
    if include_examples:
        for row in rows:
            record = index.get(row["pack_id"])
            source_status = [_source_path_status(record, rel) for rel in record.manifest.source_paths]
            source_files = [source_file for status in source_status for source_file in status["source_files"]]
            row["source_paths"] = list(record.manifest.source_paths)
            row["source_status"] = source_status
            row["source_files"] = source_files
            row["source_file_count"] = len(source_files)
            row["has_local_source"] = bool(source_files)
            row["examples"] = [
                {
                    "example_id": example_id,
                    "strength_tags": record.manifest.example_strengths.get(example_id, []),
                    "motif_tags": record.manifest.motif_overlaps.get(example_id, []),
                    "preview_path": record.manifest.preview_paths.get(example_id, ""),
                    **_example_source_status(record, example_id),
                }
                for example_id in record.manifest.example_ids
            ]
    rules = load_routing_rules(root, rules_path)
    return {
        "repo_root": str(root),
        "pack_count": len(rows),
        "anchor_count": sum(1 for row in rows if row["role"] == "anchor"),
        "support_bank_count": sum(1 for row in rows if row["role"] == "support_bank"),
        "rules_version": rules.version,
        "verticals": sorted(rules.verticals),
        "packs": rows,
    }


def _read_pack_markup(pack: Any) -> str:
    for rel in pack.manifest.source_paths:
        path = pack.pack_dir / rel
        if path.suffix.lower() in {".html", ".htm", ".tsx", ".jsx"} and path.exists():
            try:
                return sanitize_source_text(path.read_text(encoding="utf-8"))
            except OSError:
                continue
    return ""


def get_source_excerpt(
    repo_root: Path | str,
    *,
    pack_id: str,
    example_id: str | None = None,
    token_mode: TokenMode | str = "compact",
    max_chars: int = 3000,
    include_full: bool = False,
    include_section_snippets: bool = True,
) -> str:
    root = Path(repo_root).expanduser().resolve()
    index = build_repository_index(root)
    store = PackStore(root, index)
    rules = load_routing_rules(root)
    budget = rules.token_budget(token_mode)
    load_full = include_full or budget.full_code_allowed
    pack = store.get_pack(pack_id, selected_examples=[example_id] if example_id else [], include_full=load_full, max_code_chars=max_chars)
    parts: list[str] = [
        f"# Source Excerpt: `{pack_id}`",
        f"- token_mode: `{token_mode}`",
        f"- include_full: `{str(load_full).lower()}`",
    ]
    if example_id:
        ex = pack.example_summaries.get(example_id)
        if ex is None:
            return json.dumps({"error": f"Example '{example_id}' not found or not loaded for pack '{pack_id}'"}, indent=2)
        if ex.html_excerpt:
            parts.append(f"## `{example_id}` HTML\n```html\n{ex.html_excerpt[:max_chars]}\n```")
        if ex.css_excerpt:
            parts.append(f"## `{example_id}` CSS\n```css\n{ex.css_excerpt[:max_chars]}\n```")
        if include_section_snippets:
            for excerpt in ex.section_job_excerpts:
                parts.append(f"## Section Snippet `{excerpt.label}`\n```{excerpt.language}\n{excerpt.content[:max_chars]}\n```")
        if load_full:
            for file in ex.full_code_files:
                parts.append(f"## Full File `{file.label}`\n```{file.language}\n{file.content[:max_chars]}\n```")
    else:
        if pack.anchor_markup_excerpt:
            parts.append(f"## Anchor Markup\n```{pack.anchor_markup_language}\n{pack.anchor_markup_excerpt[:max_chars]}\n```")
        if pack.anchor_css_excerpt:
            parts.append(f"## Anchor CSS\n```{pack.anchor_css_language}\n{pack.anchor_css_excerpt[:max_chars]}\n```")
        for atom in pack.atoms[: budget.max_snippets]:
            if atom.snippet:
                parts.append(f"## Atom `{atom.atom_id}`\n{atom.notes}\n```{atom.language}\n{atom.snippet[:min(max_chars, 1000)]}\n```")
        if include_section_snippets:
            html_file = next((f for f in pack.anchor_source_files if f.language in {"html", "tsx", "jsx"}), None)
            anchor_markup = html_file.content if html_file else _read_pack_markup(pack)
            if anchor_markup:
                section_excerpts = _extract_section_job_excerpts_from_text(
                    anchor_markup,
                    example_id=pack_id,
                    max_sections=4,
                    max_chars=max_chars,
                )
                for excerpt in section_excerpts:
                    parts.append(f"## Section Snippet `{excerpt.label}`\n```{excerpt.language}\n{excerpt.content[:max_chars]}\n```")
        if load_full:
            for file in pack.anchor_source_files:
                parts.append(f"## Full File `{file.label}`\n```{file.language}\n{file.content[:max_chars]}\n```")
    output = "\n\n".join(parts)
    return f"<!-- estimated_tokens={estimate_tokens(output)} -->\n\n{output}"


def export_opencode_bundle(
    repo_root: Path | str,
    *,
    surface: str,
    task: str,
    output_dir: Path | str | None = None,
    token_mode: TokenMode | str = "compact",
    stack: str = "unknown",
    tone: list[str] | None = None,
    full_code_mode: bool = False,
    include_source_excerpts: bool = True,
    code_profile: str = "code_first",
    packet_intent: str = "balanced",
    max_source_chars: int = 8000,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve() if output_dir else root / "exports" / "latest"
    out.mkdir(parents=True, exist_ok=True)
    packet = resolve_design_context(
        root,
        surface=surface,
        task=task,
        stack=stack,
        tone=tone,
        token_mode=token_mode,
        full_code_mode=full_code_mode,
        code_profile=code_profile,
        packet_intent=packet_intent,
    )
    (out / "PACKET.md").write_text(packet.markdown + "\n", encoding="utf-8")
    files = ["PACKET.md", "SOURCES.json", "TOKEN_BUDGET.md", "NEXT_EXPANSIONS.md"]
    source_excerpts: list[dict[str, Any]] = []
    if include_source_excerpts:
        source_out = out / "SOURCE_EXCERPTS"
        source_out.mkdir(parents=True, exist_ok=True)
        index = build_repository_index(root)
        selected_pack_ids = [item for item in packet.selected_files if item in index.by_id]
        selected_example_ids = [item for item in packet.selected_files if item not in index.by_id]
        for pack_id in selected_pack_ids:
            record = index.by_id[pack_id]
            if record.manifest.role != "anchor":
                continue
            rel_path = f"SOURCE_EXCERPTS/{_safe_name(pack_id)}.md"
            excerpt = get_source_excerpt(
                root,
                pack_id=pack_id,
                token_mode=token_mode,
                max_chars=max_source_chars,
                include_full=True,
                include_section_snippets=True,
            )
            (out / rel_path).write_text(excerpt + "\n", encoding="utf-8")
            files.append(rel_path)
            source_excerpts.append({"pack_id": pack_id, "path": rel_path, "kind": "anchor"})
        for example_id in selected_example_ids:
            record = _support_record_for_example(index, example_id, preferred_pack_ids=selected_pack_ids)
            if record is None:
                continue
            rel_path = f"SOURCE_EXCERPTS/{_safe_name(record.manifest.pack_id)}__{_safe_name(example_id)}.md"
            excerpt = get_source_excerpt(
                root,
                pack_id=record.manifest.pack_id,
                example_id=example_id,
                token_mode=token_mode,
                max_chars=max_source_chars,
                include_full=True,
                include_section_snippets=True,
            )
            (out / rel_path).write_text(excerpt + "\n", encoding="utf-8")
            files.append(rel_path)
            source_excerpts.append({"pack_id": record.manifest.pack_id, "example_id": example_id, "path": rel_path, "kind": "support_example"})
    (out / "SOURCES.json").write_text(
        json.dumps(
            {
                "selected_files": packet.selected_files,
                "omitted_files": packet.omitted_files,
                "source_excerpts": source_excerpts,
                "code_profile": packet.metadata.get("code_profile"),
                "packet_intent": packet.metadata.get("packet_intent"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / "TOKEN_BUDGET.md").write_text(f"# Token Budget\n\n- mode: {packet.token_mode}\n- estimated_tokens: {packet.estimated_tokens}\n", encoding="utf-8")
    (out / "NEXT_EXPANSIONS.md").write_text("# Next Expansion\n\nRerun resolve_design_context with a larger token_mode when needed.\n", encoding="utf-8")
    return {"exported_to": str(out), "files": files, "source_excerpts": source_excerpts}


def build_index(repo_root: Path | str, *, refresh: bool = True) -> dict[str, Any]:
    index = build_repository_index(repo_root, refresh=refresh)
    cache = write_sqlite_index(index)
    return {"repo_root": str(index.repo_root), "cache": str(cache), "pack_count": len(index.records)}


def validate_design_router(repo_root: Path | str) -> dict[str, Any]:
    return validate_repository(Path(repo_root).expanduser().resolve())
