from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .index_store import PackIndexRecord, RepositoryIndex, build_repository_index
from .sanitizer import sanitize_source_text
from .schemas import AtomSnippet, CodeFile, ExampleSummary, LoadedPack, PackManifest

CODE_SUFFIXES = {".html", ".htm", ".css", ".tsx", ".ts", ".jsx", ".js", ".md"}

# First-party reference atoms are clean authored code: they must NOT be passed through
# `sanitize_source_text` (that sanitizer is for reference-pack source excerpts only).
# Selected first-party atoms are loaded whole. Packet size is telemetry, not a
# reason to clip source.
SHARED_ATOM_FILE_CHARS: int | None = None

# Order code files html -> css -> js -> other so weak models read markup first.
_ATOM_FILE_ORDER = {".html": 0, ".htm": 0, ".css": 1, ".js": 2, ".jsx": 2, ".ts": 3, ".tsx": 3}


def _read_text(path: Path, *, max_chars: int | None = None) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n/* truncated */"
    return text


def _language_for_path(path: Path | None) -> str:
    if path is None:
        return "text"
    suffix = path.suffix.lower()
    return {
        ".tsx": "tsx",
        ".ts": "ts",
        ".jsx": "jsx",
        ".js": "js",
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".md": "markdown",
    }.get(suffix, suffix.removeprefix(".") or "text")


def _load_code_file(path: Path, label: str | None = None, *, max_chars: int | None = None) -> CodeFile | None:
    if path.suffix.lower() not in CODE_SUFFIXES:
        return None
    text = _read_text(path, max_chars=max_chars).strip()
    if not text:
        return None
    return CodeFile(label=label or path.name, language=_language_for_path(path), content=text)


def _find_balanced_block(markup: str, start: int, tag_name: str) -> str:
    open_pattern = re.compile(rf"<{tag_name}\b", re.IGNORECASE)
    close_pattern = re.compile(rf"</{tag_name}>", re.IGNORECASE)
    depth = 1
    cursor = open_pattern.search(markup, start)
    if cursor is None:
        return ""
    cursor_pos = cursor.end()
    while depth > 0:
        next_open = open_pattern.search(markup, cursor_pos)
        next_close = close_pattern.search(markup, cursor_pos)
        if next_close is None:
            return markup[start:].strip()
        if next_open is not None and next_open.start() < next_close.start():
            depth += 1
            cursor_pos = next_open.end()
            continue
        depth -= 1
        cursor_pos = next_close.end()
    return markup[start:cursor_pos].strip()


def _slug_from_block(block: str, fallback: str) -> str:
    heading = re.search(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", block, re.I | re.S)
    text = heading.group(1) if heading else fallback
    text = re.sub(r"<[^>]+>", " ", text)
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:5]) or fallback


# Interior blocks worth pulling as component snippets when a build has few
# top-level <section> tags (app shells, dashboards, editors wrap everything in one
# <main> of nested divs). Matched against the element's opening tag only.
_PANEL_CLASS_RE = re.compile(
    r"class(?:Name)?=['\"][^'\"]*\b("
    r"panel|card|sidebar|side-?nav|side-?bar|toolbar|table|board|canvas|chart|graph|"
    r"grid|widget|stat|kpi|metric|column|drawer|inspector|console|editor|tabs?|"
    r"dialog|modal|palette|tree|list-?view"
    r")\b",
    re.IGNORECASE,
)

_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HTML_TAG_RE = re.compile(r"<!--.*?-->|<![^>]*>|<[^>]+>", re.S)


def _trim_balanced_markup(markup: str, max_chars: int | None = None) -> str:
    text = markup.strip()
    if max_chars is None or len(text) <= max_chars:
        return text
    cutoff = text.rfind(">", 0, max_chars + 1)
    if cutoff < 0:
        return ""
    prefix = text[: cutoff + 1].rstrip()
    stack: list[str] = []
    for match in _HTML_TAG_RE.finditer(prefix):
        tag = match.group(0)
        if tag.startswith(("<!--", "<!")):
            continue
        parsed = re.match(r"<\s*(/?)\s*([a-zA-Z0-9:-]+)", tag)
        if parsed is None:
            continue
        closing, name = parsed.groups()
        name = name.lower()
        if closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index] == name:
                    del stack[index:]
                    break
            continue
        if name in _VOID_HTML_TAGS or tag.rstrip().endswith("/>"):
            continue
        stack.append(name)
    closers = "".join(f"</{name}>" for name in reversed(stack))
    return f"{prefix}{closers}\n<!-- shortened at a tag boundary -->"


def _extract_section_job_excerpts_from_text(
    markup: str,
    *,
    example_id: str,
    max_sections: int = 4,
    max_chars: int | None = None,
) -> list[CodeFile]:
    if not markup:
        return []
    excerpts: list[CodeFile] = []
    seen: set[str] = set()

    def _try_add(tag_name: str, start: int) -> None:
        block = _find_balanced_block(markup, start, tag_name)
        lowered = block.lower()
        if not block or len(block) < 180:
            return
        if not any(marker in lowered for marker in ("<h1", "<h2", "<h3", "class=", "classname=")):
            return
        slug = _slug_from_block(block, f"{tag_name}-{len(excerpts) + 1:02d}")
        content = _trim_balanced_markup(block, max_chars)
        if not content:
            return
        fingerprint = re.sub(r"\s+", " ", content[:420]).strip()
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        excerpts.append(CodeFile(label=f"{example_id}/section-{len(excerpts) + 1:02d}-{slug}.html", language="html", content=content))

    # Pass 1: top-level semantic regions (landing pages fill this with <section>s).
    for match in re.compile(r"<(section|main|header|footer|aside|nav)\b[^>]*>", re.IGNORECASE).finditer(markup):
        if len(excerpts) >= max_sections:
            return excerpts
        _try_add(match.group(1).lower(), match.start())

    # Pass 2: labeled interior panels — surfaces real component pieces from app /
    # dashboard / editor builds that have one big <main> instead of many sections.
    if len(excerpts) < max_sections:
        for match in re.compile(r"<(div|section|article|aside)\b[^>]*>", re.IGNORECASE).finditer(markup):
            if len(excerpts) >= max_sections:
                break
            if not _PANEL_CLASS_RE.search(match.group(0)):
                continue
            _try_add(match.group(1).lower(), match.start())
    return excerpts


def extract_markup_excerpt(markup: str, *, max_chars: int | None = None) -> str:
    if not markup:
        return ""
    class_attr = r"(?:class|className)"
    patterns = [
        re.compile(rf"<section\b[^>]*{class_attr}=['\"][^'\"]*hero[^'\"]*['\"][^>]*>", re.IGNORECASE),
        re.compile(rf"<main\b[^>]*{class_attr}=['\"][^'\"]*hero[^'\"]*['\"][^>]*>", re.IGNORECASE),
        re.compile(rf"<main\b[^>]*{class_attr}=['\"][^'\"]*core-layer[^'\"]*['\"][^>]*>", re.IGNORECASE),
        re.compile(rf"<section\b[^>]*{class_attr}=['\"][^'\"]*split[^'\"]*['\"][^>]*>", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(markup)
        if match:
            tag_name = "main" if match.group(0).lower().startswith("<main") else "section"
            return _trim_balanced_markup(_find_balanced_block(markup, match.start(), tag_name), max_chars)
    for tag_name in ("section", "main"):
        pattern = re.compile(rf"<{tag_name}\b[^>]*>", re.IGNORECASE)
        for match in pattern.finditer(markup):
            block = _find_balanced_block(markup, match.start(), tag_name)
            if "<h1" in block.lower() or "<h2" in block.lower():
                return _trim_balanced_markup(block, max_chars)
    return _trim_balanced_markup(markup, max_chars)


def _trim(text: str, max_chars: int | None = None) -> str:
    text = text.strip()
    if max_chars is None or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n<!-- truncated -->"


def _extract_inline_style_blocks(markup: str, *, max_chars: int | None = None) -> str:
    blocks = [m.group(1).strip() for m in re.finditer(r"<style\b[^>]*>(.*?)</style>", markup, re.I | re.S)]
    return _trim("\n\n".join(blocks), max_chars) if blocks else ""


def _read_source_markup(path: Path, *, max_chars: int | None = None) -> str:
    if path.is_file():
        return _read_text(path, max_chars=max_chars)
    for name in ("index.html", "app_page.tsx", "page.tsx", "App.tsx", "app.jsx"):
        text = _read_text(path / name, max_chars=max_chars)
        if text:
            return text
    return ""


def _read_source_css(path: Path, *, max_chars: int | None = None) -> str:
    if path.is_file():
        return _extract_inline_style_blocks(_read_text(path, max_chars=max_chars), max_chars=max_chars)
    for name in ("styles.css", "app_globals.css", "globals.css", "style.css"):
        text = _read_text(path / name, max_chars=max_chars)
        if text:
            return text
    return _extract_inline_style_blocks(_read_source_markup(path, max_chars=max_chars), max_chars=max_chars)


def _load_atoms(
    pack_dir: Path,
    *,
    max_snippets: int | None = None,
    max_chars: int | None = None,
) -> list[AtomSnippet]:
    atoms_dir = pack_dir / "atoms"
    if not atoms_dir.exists():
        return []
    atoms: list[AtomSnippet] = []
    for atom_dir in sorted(p for p in atoms_dir.iterdir() if p.is_dir()):
        # Pack-local atoms are extracted from reference-pack source, so sanitize like other excerpts.
        notes = sanitize_source_text(_read_text(atom_dir / "notes.md"))
        snippet_files = sorted(p for p in atom_dir.iterdir() if p.name.startswith("snippet."))
        if not snippet_files:
            atoms.append(AtomSnippet(atom_id=atom_dir.name, notes=notes, snippet=None, language="text"))
        for snippet_path in snippet_files[:1]:
            atoms.append(
                AtomSnippet(
                    atom_id=atom_dir.name,
                    notes=notes,
                    snippet=sanitize_source_text(_read_text(snippet_path, max_chars=max_chars)),
                    language=_language_for_path(snippet_path),
                )
            )
        if max_snippets is not None and len(atoms) >= max_snippets:
            break
    return atoms


def _load_anchor_reference(
    pack_dir: Path,
    manifest: PackManifest,
    *,
    include_full: bool,
    max_code_chars: int | None,
) -> tuple[str, str, str, str, list[CodeFile]]:
    markup = ""
    markup_lang = "text"
    css = ""
    css_lang = "css"
    files: list[CodeFile] = []
    for rel in manifest.source_paths:
        path = pack_dir / rel
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        if include_full:
            code_file = _sanitize_code_file(_load_code_file(path, rel, max_chars=max_code_chars))
            if code_file is not None:
                files.append(code_file)
        if not markup and suffix in {".html", ".htm", ".tsx", ".jsx", ".js"}:
            raw = _read_text(path, max_chars=max_code_chars)
            markup = extract_markup_excerpt(raw, max_chars=max_code_chars)
            markup_lang = _language_for_path(path)
        if not css and suffix == ".css":
            css = _read_text(path, max_chars=max_code_chars).strip()
            css_lang = _language_for_path(path)
    if not markup and manifest.source_paths:
        path = pack_dir / manifest.source_paths[0]
        raw = _read_source_markup(path, max_chars=max_code_chars)
        markup = extract_markup_excerpt(raw, max_chars=max_code_chars)
        markup_lang = _language_for_path(path)
    if not css and manifest.source_paths:
        path = pack_dir / manifest.source_paths[0]
        css = _read_source_css(path, max_chars=max_code_chars)
    # Anchor source is run through the same sanitizer as support examples so reference
    # identity/PII/raster/proof placeholders never leak into emitted packets or bundles.
    return sanitize_source_text(markup), markup_lang, sanitize_source_text(css), css_lang, files


def _sanitize_code_file(code_file: CodeFile | None) -> CodeFile | None:
    if code_file is None:
        return None
    return code_file.model_copy(update={"content": sanitize_source_text(code_file.content)})


def _load_full_source_files(
    source_path: Path,
    example_id: str,
    *,
    max_code_chars: int | None,
    sanitize: bool = False,
) -> list[CodeFile]:
    if source_path.is_file():
        code_file = _load_code_file(source_path, f"{example_id}/{source_path.name}", max_chars=max_code_chars)
        if sanitize:
            code_file = _sanitize_code_file(code_file)
        return [code_file] if code_file else []
    preferred_names = (
        "index.html",
        "styles.css",
        "script.js",
        "app.js",
        "app_page.tsx",
        "page.tsx",
        "App.tsx",
        "app.jsx",
        "app_globals.css",
        "globals.css",
        "style.css",
    )
    candidates: list[Path] = []
    for name in preferred_names:
        candidate = source_path / name
        if candidate.is_file() and candidate.suffix.lower() in CODE_SUFFIXES:
            candidates.append(candidate)
    seen = {candidate.resolve() for candidate in candidates}
    for candidate in sorted(source_path.rglob("*")):
        if not candidate.is_file() or candidate.suffix.lower() not in CODE_SUFFIXES:
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        candidates.append(candidate)
        seen.add(resolved)
    files: list[CodeFile] = []
    for candidate in candidates:
        label = f"{example_id}/{candidate.relative_to(source_path).as_posix()}"
        code_file = _load_code_file(candidate, label, max_chars=max_code_chars)
        if sanitize:
            code_file = _sanitize_code_file(code_file)
        if code_file:
            files.append(code_file)
    return files


def _load_example(
    pack_dir: Path,
    manifest: PackManifest,
    example_id: str,
    *,
    include_full: bool,
    max_code_chars: int | None,
) -> ExampleSummary:
    examples_dir = pack_dir / "examples"
    summary_path = examples_dir / f"{example_id}.md"
    source_dir = manifest.source_dirs.get(example_id, "")
    html_excerpt = sanitize_source_text(_read_text(examples_dir / example_id / "hero.html", max_chars=max_code_chars)).strip()
    css_excerpt = sanitize_source_text(_read_text(examples_dir / example_id / "hero.css", max_chars=max_code_chars)).strip()
    full_files: list[CodeFile] = []
    section_job_excerpts: list[CodeFile] = []
    if source_dir:
        source_path = Path(source_dir)
        if not source_path.is_absolute():
            source_path = pack_dir / source_path
        source_markup = sanitize_source_text(
            _read_source_markup(source_path, max_chars=max_code_chars)
        )
        section_markup = source_markup
        section_job_excerpts = _extract_section_job_excerpts_from_text(
            section_markup,
            example_id=example_id,
            max_chars=None,
        )
        if include_full:
            full_files = _load_full_source_files(source_path, example_id, max_code_chars=max_code_chars, sanitize=True)
        if not html_excerpt:
            html_excerpt = extract_markup_excerpt(source_markup, max_chars=max_code_chars)
        if not css_excerpt:
            css_excerpt = sanitize_source_text(_read_source_css(source_path, max_chars=max_code_chars))
    return ExampleSummary(
        example_id=example_id,
        summary_markdown=sanitize_source_text(_read_text(summary_path)),
        strength_tags=manifest.example_strengths.get(example_id, []),
        motif_tags=manifest.motif_overlaps.get(example_id, []),
        source_dir=source_dir,
        preview_path=manifest.preview_paths.get(example_id, ""),
        html_excerpt=html_excerpt,
        css_excerpt=css_excerpt,
        full_code_files=full_files,
        section_job_excerpts=section_job_excerpts,
    )


def _atom_file_sort_key(path: Path) -> tuple[int, str]:
    return (_ATOM_FILE_ORDER.get(path.suffix.lower(), 9), path.name)


def _load_atom_meta(atom_dir: Path) -> dict | None:
    meta_path = atom_dir / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_shared_atom(atom_dir: Path, *, max_chars: int | None) -> AtomSnippet:
    """Load one first-party reference atom with ALL of its code files + meta.

    First-party atoms are clean authored code and are intentionally NOT run through
    the donor sanitizer.
    """
    notes = _read_text(atom_dir / "notes.md")
    meta = _load_atom_meta(atom_dir)

    snippet_files = sorted(
        (p for p in atom_dir.iterdir() if p.is_file() and p.name.startswith("snippet.")),
        key=_atom_file_sort_key,
    )
    code_blocks: list[CodeFile] = []
    for snippet_path in snippet_files:
        content = _read_text(snippet_path, max_chars=max_chars).strip()
        if not content:
            continue
        code_blocks.append(
            CodeFile(
                label=snippet_path.name,
                language=_language_for_path(snippet_path),
                content=content,
            )
        )

    first = code_blocks[0] if code_blocks else None
    fields: dict = {
        "atom_id": atom_dir.name,
        "notes": notes,
        "snippet": first.content if first else None,
        "language": first.language if first else "text",
        "code_blocks": code_blocks,
    }
    if meta is not None:
        fields.update(
            {
                "category": str(meta.get("category", "")),
                "summary": str(meta.get("summary", "")),
                "surfaces": [str(s) for s in meta.get("surfaces", []) if isinstance(s, str)],
                "ux_roles": [str(r) for r in meta.get("ux_roles", []) if isinstance(r, str)],
                "tags": [str(t) for t in meta.get("tags", []) if isinstance(t, str)],
                "tone": [str(t) for t in meta.get("tone", []) if isinstance(t, str)],
                "has_meta": True,
            }
        )
    return AtomSnippet(**fields)


def load_shared_atoms(
    repo_root: Path,
    *,
    max_chars: int | None = SHARED_ATOM_FILE_CHARS,
) -> list[AtomSnippet]:
    """Load ALL first-party reference atoms with their full code + selection metadata.

    No atom cap and no per-atom file cap: every atom dir is loaded with every
    ``snippet.*`` file (html/css/js) so the full component library is available in
    memory. Relevance selection and per-mode trimming happen downstream in the
    router/renderer — not here.
    """
    candidates = [repo_root / "goldensets" / "shared_atoms", repo_root / "src" / "design_router_mcp" / "goldensets" / "shared_atoms"]
    shared_dir = next((p for p in candidates if p.exists()), None)
    if shared_dir is None:
        return []
    atoms: list[AtomSnippet] = []
    for atom_dir in sorted(p for p in shared_dir.iterdir() if p.is_dir()):
        atoms.append(_load_shared_atom(atom_dir, max_chars=max_chars))
    return atoms


class PackStore:
    def __init__(self, repo_root: Path | str, index: RepositoryIndex | None = None) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.index = index or build_repository_index(self.repo_root)

    @lru_cache(maxsize=64)
    def _load_cached(
        self,
        pack_id: str,
        example_key: str,
        include_full: bool,
        max_code_chars: int | None,
        max_atoms: int | None,
    ) -> LoadedPack:
        record = self.index.get(pack_id)
        selected_examples = [eid for eid in example_key.split("\0") if eid]
        return self._load_from_record(record, selected_examples=selected_examples, include_full=include_full, max_code_chars=max_code_chars, max_atoms=max_atoms)

    def get_pack(
        self,
        pack_id: str,
        *,
        selected_examples: Iterable[str] | None = None,
        include_full: bool = True,
        max_code_chars: int | None = None,
        max_atoms: int | None = None,
    ) -> LoadedPack:
        example_key = "\0".join(sorted(selected_examples or []))
        return self._load_cached(pack_id, example_key, include_full, max_code_chars, max_atoms)

    def _load_from_record(
        self,
        record: PackIndexRecord,
        *,
        selected_examples: list[str],
        include_full: bool,
        max_code_chars: int | None,
        max_atoms: int | None,
    ) -> LoadedPack:
        manifest = record.manifest
        prompt = sanitize_source_text(_read_text(record.pack_dir / "prompt.md"))
        principles = sanitize_source_text(_read_text(record.pack_dir / "principles.md"))
        anti_copy = sanitize_source_text(_read_text(record.pack_dir / "anti_copy.md"))
        atoms = _load_atoms(record.pack_dir, max_snippets=max_atoms)
        markup, markup_lang, css, css_lang, source_files = _load_anchor_reference(
            record.pack_dir,
            manifest,
            include_full=include_full,
            max_code_chars=max_code_chars,
        )
        example_summaries: dict[str, ExampleSummary] = {}
        for example_id in selected_examples:
            if example_id in manifest.example_ids:
                example_summaries[example_id] = _load_example(
                    record.pack_dir,
                    manifest,
                    example_id,
                    include_full=include_full,
                    max_code_chars=max_code_chars,
                )
        return LoadedPack(
            manifest=manifest,
            pack_dir=record.pack_dir,
            prompt_markdown=prompt,
            principles_markdown=principles,
            anti_copy_markdown=anti_copy,
            atoms=atoms,
            example_summaries=example_summaries,
            anchor_markup_excerpt=markup,
            anchor_markup_language=markup_lang,
            anchor_css_excerpt=css,
            anchor_css_language=css_lang,
            anchor_source_files=source_files,
        )


def load_pack(pack_dir: Path) -> LoadedPack:
    manifest = PackManifest.model_validate_json((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    record = PackIndexRecord(manifest=manifest, pack_dir=pack_dir, manifest_path=pack_dir / "manifest.json", manifest_mtime_ns=(pack_dir / "manifest.json").stat().st_mtime_ns)
    store = PackStore(pack_dir.parent.parent if pack_dir.parent.name != "goldensets" else pack_dir.parent)
    return store._load_from_record(record, selected_examples=manifest.example_ids if manifest.role == "support_bank" else [], include_full=False, max_code_chars=5000, max_atoms=3)


def load_repository_packs(repo_root: Path | str, *, load_examples: bool = False) -> tuple[list[LoadedPack], list[AtomSnippet]]:
    root = Path(repo_root).expanduser().resolve()
    index = build_repository_index(root)
    store = PackStore(root, index)
    packs: list[LoadedPack] = []
    for record in index.records:
        examples = record.manifest.example_ids if load_examples and record.manifest.role == "support_bank" else []
        packs.append(store.get_pack(record.manifest.pack_id, selected_examples=examples, include_full=False, max_code_chars=3000))
    return packs, load_shared_atoms(root)
