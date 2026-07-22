from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from typing import Any

from .index_store import PackIndexRecord, build_repository_index
from .visual_features import aggregate_profiles, analyze_image


SOURCE_SUFFIXES = {".css", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx"}
TAG_NAMES = (
    "header",
    "nav",
    "main",
    "section",
    "aside",
    "footer",
    "form",
    "table",
    "dialog",
    "canvas",
    "svg",
    "img",
    "video",
    "button",
    "input",
    "textarea",
    "select",
)
LAYOUT_PATTERNS = {
    "grid-layout": r"display\s*:\s*grid",
    "flex-layout": r"display\s*:\s*flex",
    "sticky-positioning": r"position\s*:\s*sticky",
    "fixed-positioning": r"position\s*:\s*fixed",
    "responsive-breakpoints": r"@media\b",
    "container-queries": r"@container\b",
    "motion-keyframes": r"@keyframes\b",
    "css-variables": r"--[a-z0-9_-]+\s*:",
    "scroll-snap": r"scroll-snap-(?:type|align)",
    "multi-column": r"(?:column-count|columns)\s*:",
}


def default_visual_index_path(repo_root: Path) -> Path:
    return repo_root / ".design_router" / "visual_index.json"


def _source_files(record: PackIndexRecord, *, limit: int = 16) -> list[Path]:
    files: list[Path] = []
    for rel in record.manifest.source_paths:
        path = record.pack_dir / rel
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file() and candidate.suffix.lower() in SOURCE_SUFFIXES
            )
        if len(files) >= limit:
            break
    return files[:limit]


def _read_sources(record: PackIndexRecord) -> tuple[str, list[str]]:
    chunks: list[str] = []
    paths: list[str] = []
    remaining = 1_000_000
    for path in _source_files(record):
        if remaining <= 0:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:remaining]
        except OSError:
            continue
        chunks.append(text)
        paths.append(str(path.relative_to(record.pack_dir)))
        remaining -= len(text)
    return "\n".join(chunks), paths


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                return struct.unpack(">II", header[16:24])
            if header.startswith((b"GIF87a", b"GIF89a")) and len(header) >= 10:
                return struct.unpack("<HH", header[6:10])
            if header[:2] != b"\xff\xd8":
                return None
            handle.seek(2)
            while True:
                marker_start = handle.read(1)
                if not marker_start:
                    return None
                if marker_start != b"\xff":
                    continue
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_bytes = handle.read(2)
                if len(length_bytes) != 2:
                    return None
                length = struct.unpack(">H", length_bytes)[0]
                if marker in {
                    b"\xc0",
                    b"\xc1",
                    b"\xc2",
                    b"\xc3",
                    b"\xc5",
                    b"\xc6",
                    b"\xc7",
                    b"\xc9",
                    b"\xca",
                    b"\xcb",
                    b"\xcd",
                    b"\xce",
                    b"\xcf",
                }:
                    data = handle.read(5)
                    if len(data) != 5:
                        return None
                    height, width = struct.unpack(">HH", data[1:5])
                    return width, height
                handle.seek(max(0, length - 2), 1)
    except OSError:
        return None


def _resolve_screenshot(
    repo_root: Path, record: PackIndexRecord, rel: str
) -> Path | None:
    for candidate in (record.pack_dir / rel, repo_root / rel):
        if candidate.is_file():
            return candidate
    return None


def _screenshot_profile(repo_root: Path, record: PackIndexRecord) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    terms: set[str] = set()
    pixel_profiles: list[dict[str, Any]] = []
    for rel in record.manifest.screenshot_paths:
        path = _resolve_screenshot(repo_root, record, rel)
        dimensions = _image_dimensions(path) if path else None
        row: dict[str, Any] = {"path": rel, "available": path is not None}
        if dimensions:
            width, height = dimensions
            ratio = width / max(1, height)
            aspect = (
                "wide" if ratio >= 1.45 else "tall" if ratio <= 0.78 else "balanced"
            )
            row.update({"width": width, "height": height, "aspect": aspect})
            terms.add(f"{aspect}-screenshot")
        if path is not None:
            pixel = analyze_image(path)
            pixel.pop("path", None)
            row["pixel_profile"] = pixel
            if pixel.get("available"):
                pixel_profiles.append(pixel)
                terms.update(pixel.get("terms", []))
        rows.append(row)
    return {
        "count": len(rows),
        "items": rows,
        "terms": sorted(terms),
        "pixel_profile": aggregate_profiles(pixel_profiles),
    }


def _classify_structure(text: str) -> tuple[dict[str, int], list[str]]:
    lowered = text.lower()
    counts = {tag: len(re.findall(rf"<{tag}\b", lowered)) for tag in TAG_NAMES}
    layout_counts = {
        label: len(re.findall(pattern, lowered))
        for label, pattern in LAYOUT_PATTERNS.items()
    }
    counts.update(layout_counts)
    terms = {label for label, count in layout_counts.items() if count}
    interactive = sum(counts[tag] for tag in ("button", "input", "textarea", "select"))
    if counts["table"] or interactive >= 12:
        terms.add("dense-operational-ui")
    if (
        counts["form"]
        or sum(counts[tag] for tag in ("input", "textarea", "select")) >= 4
    ):
        terms.add("form-heavy")
    if counts["nav"] or counts["aside"]:
        terms.add("navigation-shell")
    if counts["canvas"]:
        terms.add("canvas-visualization")
    if counts["svg"] >= 4:
        terms.add("svg-rich")
    if counts["img"] + counts["video"] >= 3:
        terms.add("media-rich")
    if counts["section"] >= 5 and interactive < 8:
        terms.add("long-form-sections")
    if re.search(r"font-family\s*:[^;]*(?:serif|georgia|times)", lowered):
        terms.add("serif-typography")
    if re.search(r"font-family\s*:[^;]*(?:mono|menlo|consolas|courier)", lowered):
        terms.add("monospace-typography")
    radius_values = [
        float(value)
        for value in re.findall(r"border-radius\s*:\s*(\d+(?:\.\d+)?)px", lowered)
    ]
    if radius_values:
        median = sorted(radius_values)[len(radius_values) // 2]
        terms.add("rounded-geometry" if median >= 12 else "angular-geometry")
    return counts, sorted(terms)


def profile_anchor(repo_root: Path, record: PackIndexRecord) -> dict[str, Any]:
    source_text, source_paths = _read_sources(record)
    structure, structure_terms = _classify_structure(source_text)
    screenshot = _screenshot_profile(repo_root, record)
    terms = sorted(
        {
            *structure_terms,
            *screenshot["terms"],
            *record.manifest.surfaces,
            *record.manifest.tones,
            *record.manifest.motif_tags,
            *record.manifest.supports_tasks,
        }
    )
    return {
        "pack_id": record.manifest.pack_id,
        "family": record.manifest.family,
        "source_paths": source_paths,
        "source_chars_scanned": len(source_text),
        "structure": structure,
        "screenshot": {
            "count": screenshot["count"],
            "items": screenshot["items"],
        },
        "pixel_profile": screenshot["pixel_profile"],
        "visual_terms": terms,
    }


def build_visual_index(
    repo_root: Path | str,
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    index = build_repository_index(root)
    anchors = {
        record.manifest.pack_id: profile_anchor(root, record)
        for record in index.anchors
    }
    fingerprint_source = json.dumps(
        anchors, sort_keys=True, separators=(",", ":")
    ).encode()
    payload = {
        "version": "2.0",
        "anchor_count": len(anchors),
        "fingerprint": hashlib.sha256(fingerprint_source).hexdigest(),
        "anchors": anchors,
    }
    path = (
        Path(output_path).expanduser().resolve()
        if output_path
        else default_visual_index_path(root)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {
        "path": str(path),
        "version": payload["version"],
        "anchor_count": len(anchors),
        "fingerprint": payload["fingerprint"],
        "source_coverage": sum(bool(row["source_paths"]) for row in anchors.values()),
        "screenshot_coverage": sum(
            bool(row["screenshot"]["count"]) for row in anchors.values()
        ),
        "pixel_coverage": sum(
            bool(row["pixel_profile"].get("available")) for row in anchors.values()
        ),
    }


def load_visual_index(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    path = default_visual_index_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    anchors = payload.get("anchors")
    return payload if isinstance(anchors, dict) else {}
