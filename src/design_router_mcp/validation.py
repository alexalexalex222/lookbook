from __future__ import annotations

from pathlib import Path
from typing import Any

from .hybrid_retrieval import HybridRetriever
from .index_store import build_repository_index, find_goldensets_root
from .normalizer import normalize_request
from .routing_eval import default_judgment_path, load_judgments
from .rules import load_routing_rules
from .sanitizer import scan_source_hygiene
from .schemas import DesignContextRequest

CODE_SUFFIXES = {".html", ".htm", ".css", ".tsx", ".ts", ".jsx", ".js", ".md"}
SOURCE_FILE_NAMES = ("index.html", "styles.css", "app_page.tsx", "app_globals.css", "page.tsx", "App.tsx", "app.jsx", "style.css")
CRITICAL_MIRROR_FILES = (
    "schemas.py",
    "rules.py",
    "normalizer.py",
    "router.py",
    "renderer.py",
    "service.py",
    "mcp_server.py",
    "cli.py",
    "validation.py",
    "lazy_loader.py",
    "index_store.py",
)


def _exists(repo_root: Path, path_text: str) -> bool:
    if not path_text:
        return False
    path = Path(path_text)
    if not path.is_absolute():
        path = repo_root / path
    return path.exists()


def _resolve_pack_path(pack_dir: Path, path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else pack_dir / path


def _has_source_code(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in CODE_SUFFIXES
    if not path.is_dir():
        return False
    return any((path / name).is_file() for name in SOURCE_FILE_NAMES) or any(
        child.is_file() and child.suffix.lower() in CODE_SUFFIXES for child in path.iterdir()
    )


def _source_files(path: Path, *, limit: int = 12) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in CODE_SUFFIXES else []
    if not path.is_dir():
        return []
    files: list[Path] = []
    for name in SOURCE_FILE_NAMES:
        candidate = path / name
        if candidate.is_file() and candidate.suffix.lower() in CODE_SUFFIXES:
            files.append(candidate)
    seen = {candidate.resolve() for candidate in files}
    for candidate in sorted(path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in CODE_SUFFIXES:
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        files.append(candidate)
        seen.add(resolved)
        if len(files) >= limit:
            break
    return files


def _mirror_drift(repo_root: Path) -> dict[str, Any]:
    active = repo_root / "src" / "design_router_mcp"
    src_rebuild = repo_root / "src_rebuild"
    rebuild_pkg = repo_root / "rebuild_package" / "design_router_mcp"
    if not active.exists():
        return {"available": False, "drift": []}
    if not src_rebuild.exists() and not rebuild_pkg.exists():
        return {
            "available": False,
            "drift": [],
            "note": "Legacy mirror trees are not present; src/design_router_mcp is canonical.",
        }
    drift: list[dict[str, str]] = []
    mirrors = [("src_rebuild", src_rebuild), ("rebuild_package", rebuild_pkg)]
    for file_name in CRITICAL_MIRROR_FILES:
        active_file = active / file_name
        if not active_file.is_file():
            continue
        try:
            active_text = active_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, mirror in mirrors:
            mirror_file = mirror / file_name
            if not mirror_file.exists():
                drift.append({"mirror": label, "file": file_name, "status": "missing"})
                continue
            try:
                mirror_text = mirror_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                drift.append({"mirror": label, "file": file_name, "status": "unreadable"})
                continue
            if mirror_text != active_text:
                drift.append({"mirror": label, "file": file_name, "status": "diff"})
    for rel in ("defaults/routing_rules.default.json",):
        active_file = active / rel
        if not active_file.is_file():
            continue
        active_text = active_file.read_text(encoding="utf-8", errors="ignore")
        for label, mirror in mirrors:
            mirror_file = mirror / rel
            if not mirror_file.exists():
                drift.append({"mirror": label, "file": rel, "status": "missing"})
                continue
            if mirror_file.read_text(encoding="utf-8", errors="ignore") != active_text:
                drift.append({"mirror": label, "file": rel, "status": "diff"})
    return {"available": True, "drift": drift}


def validate_repository(repo_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append({"check": "repo_exists", "pass": repo_root.exists(), "path": str(repo_root)})
    goldensets = find_goldensets_root(repo_root)
    checks.append({"check": "goldensets_dir", "pass": goldensets.exists(), "path": str(goldensets)})

    try:
        rules = load_routing_rules(repo_root)
        checks.append(
            {
                "check": "rules_load",
                "pass": True,
                "version": rules.version,
                "vertical_count": len(rules.verticals),
                "task_archetype_count": len(rules.task_archetypes),
            }
        )
        alias_failures: list[dict[str, Any]] = []
        alias_count = 0
        for name, archetype in rules.task_archetypes.items():
            surface = "docs" if name == "docs" else "instrument" if name == "interactive_instrument" else "app"
            for alias in archetype.aliases:
                alias_count += 1
                normalized = normalize_request(
                    DesignContextRequest(surface=surface, task=f"build a {alias}"),
                    rules,
                )
                if normalized.task_archetype != name:
                    alias_failures.append(
                        {
                            "expected": name,
                            "alias": alias,
                            "actual": normalized.task_archetype,
                            "candidates": [
                                candidate.name for candidate in normalized.task_archetype_candidates[:3]
                            ],
                        }
                    )
        checks.append(
            {
                "check": "task_archetype_alias_resolution",
                "pass": not alias_failures,
                "alias_count": alias_count,
                "failures": alias_failures[:20],
            }
        )
        recipe_verticals = sorted(rules.composition_recipes)
        missing_recipes = sorted(set(rules.verticals).difference(recipe_verticals))
        checks.append(
            {
                "check": "composition_recipes",
                "pass": not missing_recipes,
                "recipes_present_for": recipe_verticals,
                "missing_recipe_for": missing_recipes,
                "warning_only": True,
            }
        )
    except Exception as exc:
        checks.append({"check": "rules_load", "pass": False, "error": str(exc)})
        rules = None

    judgment_path = default_judgment_path(repo_root)
    try:
        judgments = load_judgments(judgment_path)
        split_counts = {
            split: sum(judgment.split == split for judgment in judgments)
            for split in ("train", "calibration", "hidden")
        }
        checks.append(
            {
                "check": "routing_judgment_ledger",
                "pass": bool(judgments) and all(split_counts.values()),
                "path": str(judgment_path),
                "judgment_count": len(judgments),
                "split_counts": split_counts,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check": "routing_judgment_ledger",
                "pass": False,
                "path": str(judgment_path),
                "error": str(exc),
            }
        )

    try:
        index = build_repository_index(repo_root)
        checks.append({"check": "index_load", "pass": True, "pack_count": len(index.records), "anchor_count": len(index.anchors), "support_bank_count": len(index.support_banks)})
        checks.append({"check": "has_anchor", "pass": len(index.anchors) > 0})
        retrieval_health = HybridRetriever(repo_root, index.anchors).health()
        required_channels = {"rules", "bm25", "character"}
        checks.append(
            {
                "check": "hybrid_retrieval",
                "pass": required_channels.issubset(retrieval_health["channels"]),
                **retrieval_health,
            }
        )
        checks.append(
            {
                "check": "visual_retrieval_index",
                "pass": (
                    retrieval_health["visual_index_present"]
                    and retrieval_health["visual_coverage"]["covered"]
                    == retrieval_health["visual_coverage"]["total"]
                ),
                "warning_only": True,
                "visual_index_present": retrieval_health["visual_index_present"],
                "coverage": retrieval_health["visual_coverage"],
                "remediation": "Run `lookbook --repo-root . visual-index` to refresh structural visual retrieval.",
            }
        )
        checks.append(
            {
                "check": "pixel_visual_retrieval",
                "pass": (
                    retrieval_health.get("visual_index_version") == "2.0"
                    and retrieval_health["pixel_coverage"]["covered"] > 0
                ),
                "warning_only": True,
                "visual_index_version": retrieval_health.get("visual_index_version"),
                "coverage": retrieval_health["pixel_coverage"],
                "remediation": "Run `lookbook --repo-root . visual-index` to build V2 screenshot pixel profiles.",
            }
        )
        if rules is not None:
            archetype_errors: list[str] = []
            term_owners: dict[str, list[str]] = {}
            pack_ids = set(index.by_id)
            for name, archetype in rules.task_archetypes.items():
                unknown_preferred = sorted(set(archetype.preferred_pack_ids).difference(pack_ids))
                unknown_signatures = sorted(set(archetype.pack_signatures).difference(pack_ids))
                unknown_parents = sorted(set(archetype.supersedes).difference(rules.task_archetypes))
                if unknown_preferred:
                    archetype_errors.append(f"{name}: unknown preferred packs {unknown_preferred}")
                if unknown_signatures:
                    archetype_errors.append(f"{name}: unknown signature packs {unknown_signatures}")
                if unknown_parents:
                    archetype_errors.append(f"{name}: unknown superseded archetypes {unknown_parents}")
                if archetype.clarify_without_signature:
                    missing_signatures = sorted(
                        set(archetype.preferred_pack_ids).difference(archetype.pack_signatures)
                    )
                    if missing_signatures:
                        archetype_errors.append(
                            f"{name}: clarify_without_signature packs missing signatures {missing_signatures}"
                        )
                for term in archetype.all_keywords:
                    term_owners.setdefault(term, []).append(name)
            collisions = [
                {"term": term, "archetypes": sorted(owners)}
                for term, owners in sorted(term_owners.items())
                if len(owners) > 1
            ]
            checks.append(
                {
                    "check": "task_archetype_integrity",
                    "pass": not archetype_errors,
                    "archetype_count": len(rules.task_archetypes),
                    "errors": archetype_errors[:20],
                }
            )
            checks.append(
                {
                    "check": "task_archetype_collisions",
                    "pass": not collisions,
                    "warning_only": True,
                    "collision_count": len(collisions),
                    "collisions": collisions[:20],
                }
            )
        broken_sources: list[str] = []
        broken_example_sources: list[str] = []
        absolute_sources: list[str] = []
        broken_screenshots: list[str] = []
        ux_role_coverage: list[dict[str, Any]] = []
        hygiene_rows: list[dict[str, Any]] = []
        hygiene_total = 0
        for record in index.records:
            for rel in record.manifest.source_paths:
                if Path(rel).is_absolute():
                    absolute_sources.append(f"{record.manifest.pack_id}:{rel}")
                if not _resolve_pack_path(record.pack_dir, rel).exists():
                    broken_sources.append(f"{record.manifest.pack_id}:{rel}")
            if record.manifest.role == "support_bank":
                examples_with_roles = sum(1 for example_id in record.manifest.example_ids if record.manifest.example_ux_roles.get(example_id))
                ux_role_coverage.append(
                    {
                        "pack_id": record.manifest.pack_id,
                        "examples_with_roles": examples_with_roles,
                        "total_examples": len(record.manifest.example_ids),
                        "missing": [example_id for example_id in record.manifest.example_ids if not record.manifest.example_ux_roles.get(example_id)][:20],
                    }
                )
                for example_id in record.manifest.example_ids:
                    source_dir = record.manifest.source_dirs.get(example_id, "")
                    if not source_dir:
                        broken_example_sources.append(f"{record.manifest.pack_id}:{example_id}:missing source_dir")
                        continue
                    if Path(source_dir).is_absolute():
                        absolute_sources.append(f"{record.manifest.pack_id}:{example_id}:{source_dir}")
                    source_path = _resolve_pack_path(record.pack_dir, source_dir)
                    if not source_path.exists():
                        broken_example_sources.append(f"{record.manifest.pack_id}:{example_id}:missing {source_dir}")
                    elif not _has_source_code(source_path):
                        broken_example_sources.append(f"{record.manifest.pack_id}:{example_id}:no code files in {source_dir}")
                    for source_file in _source_files(source_path, limit=8):
                        try:
                            text = source_file.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            continue
                        hits = scan_source_hygiene(text)
                        if not hits:
                            continue
                        hygiene_total += len(hits)
                        hygiene_rows.append(
                            {
                                "pack_id": record.manifest.pack_id,
                                "example_id": example_id,
                                "path": str(source_file.relative_to(record.pack_dir)),
                                "hit_count": len(hits),
                                "kinds": sorted({hit.kind for hit in hits})[:12],
                            }
                        )
            for rel in record.manifest.screenshot_paths:
                if not _exists(repo_root, rel) and not (record.pack_dir / rel).exists():
                    broken_screenshots.append(f"{record.manifest.pack_id}:{rel}")
        checks.append({"check": "source_paths", "pass": not broken_sources, "broken": broken_sources[:20]})
        checks.append({"check": "support_source_dirs", "pass": not broken_example_sources, "broken": broken_example_sources[:20]})
        checks.append({"check": "local_source_paths", "pass": not absolute_sources, "absolute": absolute_sources[:20]})
        anchors_with_screenshots = sum(1 for record in index.anchors if record.manifest.screenshot_paths)
        anchor_count = len(index.anchors)
        checks.append(
            {
                "check": "screenshot_paths",
                "pass": not broken_screenshots,
                "warning_only": True,
                "missing": broken_screenshots[:20],
            }
        )
        checks.append(
            {
                "check": "anchor_screenshot_coverage",
                "pass": anchors_with_screenshots == anchor_count,
                "warning_only": True,
                "anchors_with_screenshots": anchors_with_screenshots,
                "anchor_count": anchor_count,
                "coverage_ratio": round(anchors_with_screenshots / anchor_count, 3) if anchor_count else 0.0,
            }
        )
        checks.append(
            {
                "check": "ux_role_coverage",
                "pass": all(item["examples_with_roles"] == item["total_examples"] for item in ux_role_coverage),
                "support_banks": ux_role_coverage,
                "warning_only": True,
            }
        )
        checks.append(
            {
                "check": "source_hygiene",
                "pass": hygiene_total == 0,
                "warning_only": True,
                "hit_count": hygiene_total,
                "files_with_hits": len(hygiene_rows),
                "examples": hygiene_rows[:20],
            }
        )
        mirror = _mirror_drift(repo_root)
        checks.append(
            {
                "check": "mirror_drift",
                "pass": not mirror["drift"],
                "warning_only": True,
                "available": mirror["available"],
                "canonical_tree": "src/design_router_mcp",
                "legacy_mirrors": ["src_rebuild", "rebuild_package/design_router_mcp"],
                "watched_files_only": True,
                "watched_files": list(CRITICAL_MIRROR_FILES) + ["defaults/routing_rules.default.json"],
                "note": (
                    "Partial check: compares ONLY the watched files above between the canonical "
                    "src/design_router_mcp tree and the deprecated legacy mirrors. drift_count==0 is "
                    "NOT a full-parity guarantee (e.g. atom_selector.py and goldensets are not tracked). "
                    "src/ is canonical; the mirrors are slated for removal. See CANONICAL_SOURCE.md."
                ),
                "drift": mirror["drift"][:20],
                "drift_count": len(mirror["drift"]),
            }
        )
    except Exception as exc:
        checks.append({"check": "index_load", "pass": False, "error": str(exc)})

    required_checks = [check for check in checks if not check.get("warning_only")]
    warnings = [check for check in checks if check.get("warning_only") and not check.get("pass", False)]
    all_required = all(check.get("pass", False) for check in required_checks)
    return {
        "all_pass": all_required,
        "all_clean": all_required and not warnings,
        "warning_count": len(warnings),
        "warnings": [check["check"] for check in warnings],
        "checks": checks,
    }
