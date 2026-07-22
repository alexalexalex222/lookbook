from __future__ import annotations

from dataclasses import dataclass

from .rules import RoutingRules, load_routing_rules
from .sanitizer import sanitize_source_text, strip_external_dependencies
from .schemas import (
    CodeFile,
    DesignContextRequest,
    LoadedPack,
    OptionalPattern,
    PatternCardTier,
    RenderedPacket,
    RouteResolution,
    TokenMode,
)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _trim(text: str, max_chars: int | None = None) -> str:
    """Compatibility helper retained for callers; packet text is never clipped."""
    return (text or "").strip()


def _request_forbids_external_dependencies(
    request: DesignContextRequest | None,
) -> bool:
    if request is None:
        return False
    text = " ".join(request.constraints).lower().replace("_", " ").replace("-", " ")
    return any(
        phrase in text
        for phrase in (
            "no external dependencies",
            "no external assets",
            "self contained",
            "single file",
            "offline",
        )
    )


def _prepare_code_for_request(
    code: str,
    request: DesignContextRequest | None,
) -> str:
    if _request_forbids_external_dependencies(request):
        return strip_external_dependencies(code)
    return code


def _code_block(
    language: str,
    code: str,
    *,
    max_chars: int | None = None,
    request: DesignContextRequest | None = None,
) -> str:
    code = _prepare_code_for_request(code, request)
    code = _trim(code, max_chars)
    if not code:
        return ""
    return f"```{language or 'text'}\n{code}\n```"


def _code_file_block(
    file: CodeFile,
    *,
    max_chars: int | None = None,
    request: DesignContextRequest | None = None,
) -> str:
    return (
        f"### Full File `{file.label}`\n"
        f"{_code_block(file.language, file.content, max_chars=max_chars, request=request)}"
    )


@dataclass(frozen=True)
class _Section:
    title: str
    body: str
    required: bool = False

    def render(self) -> str:
        body = self.body.strip()
        return f"# {self.title}\n{body}" if body else f"# {self.title}"


def _join_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def _selected_route(resolution: RouteResolution) -> str:
    confidence = resolution.route_meta.get("route_confidence", {})
    lines = [
        f"anchor: `{resolution.anchor_pack.manifest.pack_id}` (score {resolution.anchor_score.total})",
        f"surface kind: `{resolution.normalized_request.surface_kind}`",
        f"task archetype: `{resolution.normalized_request.task_archetype or 'none'}` "
        f"(confidence {resolution.normalized_request.task_archetype_confidence:.2f})",
        f"route decision: `{confidence.get('decision', 'unknown')}` "
        f"(confidence {confidence.get('value', 0):.2f}; margin {confidence.get('margin', 0)})",
        f"vertical: `{resolution.normalized_request.specialty_service_class or 'none (unrouted)'}`",
        f"matched motifs: {', '.join('`' + t + '`' for t in resolution.normalized_request.motif_tags) or 'none'}",
        f"matched strengths: {', '.join('`' + t + '`' for t in resolution.normalized_request.strength_tags) or 'none'}",
    ]
    if resolution.normalized_request.task_archetype_ambiguous:
        candidates = ", ".join(
            f"`{candidate.name}` ({candidate.confidence:.2f})"
            for candidate in resolution.normalized_request.task_archetype_candidates[:3]
        )
        lines.append(f"archetype ambiguity: {candidates or 'multiple plausible workflows'}")
    if confidence.get("needs_clarification"):
        lines.append(
            "provisional route: do not treat this anchor as final until the primary workflow is clarified."
        )
        if confidence.get("clarification_question"):
            lines.append(f"clarification question: {confidence['clarification_question']}")
    if resolution.hero_reference_pack is not None:
        lines.append(f"hero reference: `{resolution.hero_reference_pack.manifest.pack_id}`")
    if resolution.support_bank is not None and resolution.selected_examples:
        display_map = _example_display_map(resolution)
        examples = ", ".join(f"`{_display_id(display_map, s.example_id)}` ({s.score})" for s in resolution.selected_examples) or "none"
        lines.append(f"support bank: `{resolution.support_bank.manifest.pack_id}`")
        lines.append(f"support examples: {examples}")
    if resolution.optional_patterns:
        source_packs = sorted({pattern.pack_id for pattern in resolution.optional_patterns})
        lines.append(
            f"optional pattern shelf: {len(resolution.optional_patterns)} inlined Pattern Cards from "
            f"{len(source_packs)} golden sets; {len(resolution.optional_pattern_catalog)} total "
            "qualified cards are available for explicit expansion."
        )
    source_selection = resolution.route_meta.get("source_selection", {})
    if source_selection.get("anchor_self_sufficient"):
        lines.append(
            "secondary source policy: the selected anchor covers the requested UX jobs; "
            "redundant support donors, generic atoms, and optional patterns were withheld."
        )
    alternatives = resolution.route_meta.get("anchor_alternatives") or []
    if alternatives and (
        confidence.get("decision") != "route"
        or float(confidence.get("value", 0) or 0) < 0.72
    ):
        lines.append(
            "pattern alternatives (diagnostic only): the selected anchor above OWNS the composition skeleton and visual identity. "
            "Do not borrow from a runner-up merely because it appears below. Only fragments explicitly emitted in the "
            "Optional Pattern Shelf are approved secondary sources, and those remain optional section mechanics only; "
            "never blend two identities or switch skeletons mid-page."
        )
        for alt in alternatives:
            motifs = ", ".join(f"`{m}`" for m in alt.get("motif_tags", [])) or "none"
            tones = ", ".join(alt.get("tones", [])) or "none"
            tasks = ", ".join(alt.get("supports_tasks", [])) or "none"
            lines.append(
                f"alt anchor: `{alt.get('pack_id')}` (score {alt.get('score')}) — motifs: {motifs}; tones: {tones}; strong for: {tasks}"
            )
    return _join_bullets(lines)


def _full_anchor_build(resolution: RouteResolution) -> str:
    files = resolution.route_meta.get("anchor_full_source") or []
    if not files:
        return ""
    pack_id = resolution.anchor_pack.manifest.pack_id
    parts = [
        f"This is the COMPLETE source of the selected anchor build `{pack_id}` — the quality bar for this job. "
        "Use it as your composition skeleton and craft reference: match its structural depth, section count, "
        "interaction states, responsive handling, and finish level. TRANSLATE it to the target business under "
        "the Anti-Copy Contract: replace ALL brand identity (name, copy, palette values, logo, decorative "
        "signatures) with the target's; keep the bones and the bar. Shipping the fictional brand's name, copy, "
        "or exact palette is a FAILURE.",
    ]
    for f in files:
        rel = f.get("path", "file")
        lang = "html" if str(rel).endswith(".html") else ("css" if str(rel).endswith(".css") else "text")
        rendered = _code_block(
            lang,
            str(f.get("text", "")),
            max_chars=max(1, len(str(f.get("text", ""))) + 1),
            request=resolution.request,
        )
        parts.append(f"**`{rel}`** ({f.get('chars', 0):,} chars):\n{rendered}")
    return "\n\n".join(parts)


def _source_inventory(resolution: RouteResolution) -> str:
    lines = [
        "This is the selected code map for repeatable builds. Prefer these exact source pulls over guessing from screenshots.",
        f"anchor pack: `{resolution.anchor_pack.manifest.pack_id}`",
    ]
    if resolution.anchor_pack.manifest.source_paths:
        for rel in resolution.anchor_pack.manifest.source_paths:
            lines.append(f"anchor source file: `{rel}`")
    else:
        lines.append("anchor source file: none declared")
    if resolution.hero_reference_pack is not None:
        lines.append(f"hero reference pack: `{resolution.hero_reference_pack.manifest.pack_id}`")
        for rel in resolution.hero_reference_pack.manifest.source_paths:
            lines.append(f"hero reference source file: `{rel}`")
    if resolution.support_bank is not None and resolution.selected_examples:
        display_map = _example_display_map(resolution)
        lines.append(f"support bank: `{resolution.support_bank.manifest.pack_id}`")
        for selection in resolution.selected_examples:
            example = resolution.support_bank.example_summaries.get(selection.example_id)
            source_dir = example.source_dir if example is not None else resolution.support_bank.manifest.source_dirs.get(selection.example_id, "")
            display_id = _display_id(display_map, selection.example_id)
            lines.append(f"support example: `{display_id}`")
            if source_dir:
                lines.append(f"support source dir: `{source_dir}`")
            if example is not None and example.preview_path:
                lines.append(f"support preview path: `{example.preview_path}`")
            lines.append(
                "operator excerpt pull: "
                f"`get_source_excerpt(pack_id=\"{resolution.support_bank.manifest.pack_id}\", "
                f"example_id=\"{selection.example_id}\", include_full=true, include_section_snippets=true)`"
            )
    for pattern in resolution.optional_patterns:
        lines.append(f"optional pattern: `{pattern.pattern_id}`")
        if pattern.source_kind == "support_example" and pattern.example_id:
            lines.append(
                "optional pattern provenance pull: "
                f"`get_source_excerpt(pack_id=\"{pattern.pack_id}\", "
                f"example_id=\"{pattern.example_id}\", include_full=true, include_section_snippets=true)`"
            )
        else:
            lines.append(
                "auxiliary treatment summary only: this route does not approve donor markup or a full-source pull "
                "from the runner-up anchor."
            )
    if resolution.optional_pattern_catalog:
        lines.append(
            "catalog expansion: call `get_pattern_card` with the same request, a catalog `pattern_id`, "
            "and tier `S`, `M`, or `L`; only that card is returned."
        )
    return _join_bullets(lines)


def _score_line(label: str, score) -> str:
    return (
        f"{label}: `{score.pack_id}` total={score.total} "
        f"surface={score.surface} family_fit={score.family_fit} task_fit={score.task_fit} "
        f"signature_fit={score.signature_fit} retrieval_fit={score.retrieval_fit} "
        f"anti_pattern={score.anti_pattern} motif={score.motif} tone={score.tone} "
        f"layout={score.layout} request_bias={score.request_bias} confidence={score.confidence}"
    )


def _route_diagnostics(resolution: RouteResolution) -> str:
    lines = [_score_line("anchor score", resolution.anchor_score)]
    if resolution.anchor_score.matched_terms:
        for key, values in resolution.anchor_score.matched_terms.items():
            if values:
                lines.append(f"anchor matched {key}: {', '.join('`' + value + '`' for value in values)}")
    if resolution.support_bank_score is not None:
        lines.append(_score_line("support bank score", resolution.support_bank_score))
    display_map = _example_display_map(resolution)
    for selection in resolution.selected_examples:
        display_id = _display_id(display_map, selection.example_id)
        bits = [
            f"support `{display_id}` score={selection.score}",
            f"strengths={selection.strength_overlap or []}",
            f"motifs={selection.motif_overlap or []}",
            f"tokens={selection.matched_tokens or []}",
        ]
        if selection.conflicting_strength_tags or selection.conflicting_motif_tags:
            bits.append(f"conflicts={selection.conflicting_strength_tags + selection.conflicting_motif_tags}")
        lines.append("; ".join(bits))
    for pattern in resolution.optional_patterns:
        lines.append(
            f"optional pattern `{pattern.pattern_id}` score={pattern.score}; "
            f"domain={pattern.domain_fit}; mechanic={pattern.mechanic_fit}; "
            f"roles={pattern.ux_roles or []}; priority={pattern.priority_roles or []}; "
            f"matches={pattern.matched_terms or []}; axes={pattern.score_axes or {}}"
        )
    lines.append("Repeatability rule: same vertical + same selected anchor + same top support example should stay stable across paraphrases of the same business niche.")
    return _join_bullets(lines)


def _anchor_grammar(pack: LoadedPack) -> str:
    m = pack.manifest
    bullets = [
        f"Use `{m.pack_id}` as the composition skeleton, not as visual identity.",
        f"Family: `{m.family}`; tones to preserve: {', '.join(m.tones) or 'none declared'}.",
        f"Motifs to borrow: {', '.join(m.motif_tags) or 'none declared'}.",
        f"Tasks this pack supports: {', '.join(m.supports_tasks[:6]) or 'none declared'}.",
        "Translate section jobs into the target business; do not preserve source brand names, exact copy, palette values, or decorative signatures.",
    ]
    if pack.principles_markdown.strip():
        bullets.append("Principles excerpt: " + _trim(" ".join(pack.principles_markdown.split()), 900))
    return _join_bullets(bullets)


def _visual_references(resolution: RouteResolution) -> str:
    lines: list[str] = [
        "Reference-only: screenshots and previews describe visual grammar. Do not place these paths in the generated page, and do not use them as `<img>`, `<picture>`, `<source>`, or CSS `background-image` assets unless the user explicitly supplied those exact image files for the target site.",
    ]
    display_map = _example_display_map(resolution)
    visual_packs = [
        ("anchor", resolution.anchor_pack),
        ("hero_reference", resolution.hero_reference_pack),
        ("support", resolution.support_bank),
        *[("optional_anchor", pack) for pack in resolution.auxiliary_anchor_packs],
    ]
    for label, pack in visual_packs:
        if pack is None:
            continue
        for path in pack.manifest.screenshot_paths:
            lines.append(f"{label} screenshot: `{path}`")
        for example_id, path in pack.manifest.preview_paths.items():
            if label == "support" and example_id not in resolution.selected_example_ids:
                continue
            preview_id = _display_id(display_map, example_id) if label == "support" else example_id
            lines.append(f"{label} preview `{preview_id}`: `{path}`")
    return _join_bullets(lines or ["No screenshot paths declared. Build from code excerpts and manifest grammar only."])


def _example_display_id(example_id: str, *, mechanical: bool, index: int) -> str:
    if mechanical:
        return f"mechanical-ux-donor-{index + 1}"
    return example_id


def _is_mechanical_selection(resolution: RouteResolution, selection) -> bool:
    mechanical_ids = set(resolution.route_meta.get("mechanical_donor_ids") or [])
    return selection.example_id in mechanical_ids or bool(selection.ux_role_match)


def _example_display_map(resolution: RouteResolution) -> dict[str, str]:
    mapping: dict[str, str] = {}
    mech_index = 0
    for selection in resolution.selected_examples:
        if _is_mechanical_selection(resolution, selection):
            mapping[selection.example_id] = _example_display_id(selection.example_id, mechanical=True, index=mech_index)
            mech_index += 1
        else:
            mapping[selection.example_id] = selection.example_id
    for example_id in resolution.route_meta.get("mechanical_donor_ids") or []:
        if example_id not in mapping:
            mapping[example_id] = _example_display_id(example_id, mechanical=True, index=mech_index)
            mech_index += 1
    return mapping


def _display_id(display_map: dict[str, str], example_id: str) -> str:
    return display_map.get(example_id, example_id)


def _support_roles(resolution: RouteResolution, rules: RoutingRules) -> str:
    if resolution.support_bank is None or not resolution.selected_examples:
        return "No support examples selected. Stay with the anchor grammar and anti-copy contract."
    vertical = rules.verticals.get(resolution.normalized_request.specialty_service_class or "")
    role = vertical.support_role if vertical else "Use support examples only to sharpen section jobs; do not let them replace the anchor."
    lines = [role]
    display_map = _example_display_map(resolution)
    for selection in resolution.selected_examples:
        example = resolution.support_bank.example_summaries.get(selection.example_id)
        display_id = _display_id(display_map, selection.example_id)
        mechanical = _is_mechanical_selection(resolution, selection)
        if example is None:
            lines.append(f"`{display_id}`: selected by tags/tokens; source summary was not loaded.")
            continue
        tags = ", ".join([*selection.strength_overlap, *selection.motif_overlap, *selection.matched_tokens]) or "route fit"
        summary = _trim(' '.join(sanitize_source_text(example.summary_markdown).split()), 700) or "No summary markdown provided."
        if display_id != selection.example_id:
            summary = summary.replace(selection.example_id, display_id)
        lines.append(f"`{display_id}`: borrow for {tags}. {summary}")
        if mechanical:
            lines.append(
                f"operator excerpt pull (real example id): `get_source_excerpt(pack_id=\"{resolution.support_bank.manifest.pack_id}\", "
                f"example_id=\"{selection.example_id}\", include_section_snippets=true)`"
            )
    return _join_bullets(lines)


def _optional_pattern_card_tier(mode: str) -> str:
    return "L"


def _safe_css_excerpt(css: str, *, max_chars: int | None = None) -> str:
    """Return the complete selected style source; max_chars is legacy-only."""
    return css.strip()


def optional_pattern_metadata(pattern: OptionalPattern) -> dict[str, object]:
    return {
        "pattern_id": pattern.pattern_id,
        "pack_id": pattern.pack_id,
        "example_id": pattern.example_id,
        "source_kind": pattern.source_kind,
        "score": pattern.score,
        "score_axes": pattern.score_axes,
        "domain_fit": pattern.domain_fit,
        "mechanic_fit": pattern.mechanic_fit,
        "quality_score": pattern.quality_score,
        "identity_risk": pattern.identity_risk,
        "ux_roles": pattern.ux_roles,
        "priority_roles": pattern.priority_roles,
        "matched_terms": pattern.matched_terms,
        "strength_tags": pattern.strength_tags,
        "motif_tags": pattern.motif_tags,
        "job_statement": pattern.job_statement,
        "when_to_use": pattern.when_to_use,
        "when_not_to_use": pattern.when_not_to_use,
        "states": pattern.states,
        "responsive_behavior": pattern.responsive_behavior,
        "invariants": pattern.invariants,
        "dependencies": pattern.dependencies,
        "integration_hint": pattern.integration_hint,
        "excerpt_label": pattern.excerpt.label if pattern.excerpt is not None else None,
        "style_excerpt_label": (
            pattern.style_excerpt.label if pattern.style_excerpt is not None else None
        ),
        "hygiene_clean": pattern.hygiene_clean,
        "optional": pattern.optional,
    }


def render_pattern_card(
    pattern: OptionalPattern,
    *,
    tier: PatternCardTier | str = "M",
    request: DesignContextRequest | None = None,
) -> str:
    normalized_tier = str(tier).upper()
    if normalized_tier not in {"S", "M", "L"}:
        raise ValueError("Pattern Card tier must be S, M, or L.")
    roles = ", ".join(f"`{role}`" for role in pattern.ux_roles) or "route-compatible section mechanics"
    matches = ", ".join(f"`{term}`" for term in pattern.matched_terms[:10]) or "structural route fit"
    source = (
        f"`{pattern.pack_id}` / `{pattern.example_id}`"
        if pattern.example_id
        else f"auxiliary anchor `{pattern.pack_id}`"
    )
    pattern_parts = [
        f"## Optional Pattern `{pattern.pattern_id}`",
        _join_bullets(
            [
                f"source: {source}",
                f"job: {pattern.job_statement or 'one bounded section or interaction mechanic'}",
                f"fit: total={pattern.score}; domain=`{pattern.domain_fit}`; mechanic={pattern.mechanic_fit}; quality={pattern.quality_score}; identity_risk=`{pattern.identity_risk}`",
                f"candidate jobs: {roles}",
                f"priority roles covered: {', '.join(f'`{role}`' for role in pattern.priority_roles) or 'none'}",
                f"matched route terms: {matches}",
                f"when to use: {pattern.when_to_use}",
                f"when not to use: {pattern.when_not_to_use}",
                f"integration: {pattern.integration_hint}",
                f"dependencies: {', '.join(f'`{item}`' for item in pattern.dependencies) or 'anchor tokens only'}",
            ]
        ),
    ]
    if normalized_tier in {"M", "L"}:
        if pattern.states:
            pattern_parts.append("states: " + ", ".join(f"`{state}`" for state in pattern.states))
        if pattern.responsive_behavior:
            pattern_parts.append("responsive behavior:\n" + _join_bullets(pattern.responsive_behavior))
    if normalized_tier == "L" and pattern.invariants:
        pattern_parts.append("invariants:\n" + _join_bullets(pattern.invariants))
    if pattern.excerpt is not None:
        pattern_parts.append(
            f"`{pattern.excerpt.label}`\n"
            f"{_code_block(pattern.excerpt.language, pattern.excerpt.content, max_chars=max(3000, len(pattern.excerpt.content) + 1), request=request)}"
        )
    else:
        pattern_parts.append(
            "No donor markup is emitted for this auxiliary treatment summary. "
            "Use only the stated job and integration guidance."
        )
    if pattern.style_excerpt is not None:
        safe_css = _safe_css_excerpt(pattern.style_excerpt.content)
        if safe_css:
            pattern_parts.append(
                f"`{pattern.style_excerpt.label}`\n"
                f"{_code_block(pattern.style_excerpt.language, safe_css, max_chars=len(safe_css) + 1, request=request)}"
            )
    return "\n".join(item for item in pattern_parts if item)


def _optional_pattern_shelf(resolution: RouteResolution, *, mode: str) -> str:
    if not resolution.optional_patterns:
        return ""
    tier = _optional_pattern_card_tier(mode)
    parts = [
        _join_bullets(
            [
                "This shelf is optional, not a checklist. Choose zero, one, or several fragments only when they solve a concrete job in the brief; ignore every fragment that does not improve the build.",
                "The primary anchor still owns the page skeleton, hierarchy, shape language, and identity. Shelf fragments may contribute one local mechanic such as a schedule, proof rail, HUD, overlay, form, navigation treatment, responsive control dock, or data view.",
                "Never merge donor identities. Borrow the interaction or section logic, then rewrite class names, copy, palette, claims, labels, and decorative signatures for the target.",
                "Before implementation, name the chosen pattern IDs in build notes with the job each one solves. Using none is valid when the anchor and first-party component library are already sufficient.",
                f"Rendered card tier: `{tier}`. Every selected markup and CSS fragment is emitted complete.",
            ]
        )
    ]
    for pattern in resolution.optional_patterns:
        parts.append(
            render_pattern_card(
                pattern,
                tier=tier,
                request=resolution.request,
            )
        )
    selected_ids = set(resolution.optional_pattern_ids)
    catalog_rows = [
        entry for entry in resolution.optional_pattern_catalog if entry.pattern_id not in selected_ids
    ]
    if catalog_rows:
        parts.append(
            "## Qualified Pattern Catalog (not inlined)\n"
            + _join_bullets(
                [
                    f"`{entry.pattern_id}` — {entry.job_statement}; roles={entry.priority_roles or entry.ux_roles}; "
                    f"domain={entry.domain_fit}; mechanic={entry.mechanic_fit}; identity_risk={entry.identity_risk}. "
                    "Expand explicitly with `get_pattern_card`."
                    for entry in catalog_rows
                ]
            )
        )
    return "\n\n".join(parts)


def _anti_copy(resolution: RouteResolution) -> str:
    base = [
        "Borrow: section sequencing, hierarchy of attention, interaction patterns, density rhythm, anchor-to-proof flow, and the underlying logic that makes the donor work.",
        "Do not copy exact palette values, source headlines word-for-word, source body copy, brand identity, customer logos, testimonial claims, named clients, named staff, project counts, statistics, or section order one-to-one.",
        "Support donors sharpen the page; they never become the page. If your draft reads as a recolor of the donor with brand swaps, you have failed the contract — restart from the brief.",
        "Optional shelf patterns are zero-or-more local mechanics, never additional page identities. If two chosen fragments disagree with the primary anchor, keep the anchor and drop the fragments.",
        "Do not fall back to generic local-business hero plus three-card grid plus CTA strip if source excerpts are thin. Build a page that earns its sections — if you cannot fill a section honestly from the brief and the anchor grammar, cut the section.",
        "If the source uses three big proof cards with specific named clients, build a proof rail with the target business's actual specifics from the brief. Lacking those, use neutral verifiable structure (process steps, service capabilities, geographic coverage, methodology) and zero invented names.",
        "Headlines, body copy, and microcopy are written fresh against the brief. Source copy is reference for tone and density only — never raw material for the target page.",
    ]
    if resolution.anchor_pack.anti_copy_markdown.strip():
        base.append("Anchor anti-copy excerpt: " + _trim(" ".join(resolution.anchor_pack.anti_copy_markdown.split()), 900))
    return _join_bullets(base)


def _vertical_rule(resolution: RouteResolution, rules: RoutingRules):
    return rules.verticals.get(resolution.normalized_request.specialty_service_class or "")


def _visual_quality_enabled(request: DesignContextRequest) -> bool:
    return request.visual_quality_profile == "strict_design_router_gpt55_mcp_v1"


def _hard_ui_rules() -> str:
    return _join_bullets(
        [
            "No emojis anywhere in visible UI copy, labels, buttons, badges, testimonials, headings, placeholders, tooltips, table cells, footer copy, or empty states. Decorative symbols that read as emoji at 14px (stars, hearts, sparkles, fire icons, checkmark glyphs used as accents) also count. Use real typography, real iconography, real proof.",
            "One SVG, one job. Do not recycle the same polygon, blob, circle cluster, gradient mesh, abstract wave, decorative card, noise layer, avatar silhouette, or icon family across multiple sections as filler. Every visual block must earn its place and stand inspection on its own.",
            "Do not use `<img>`, `<picture>`, `<source>`, raster CSS `background-image: url(...)`, route screenshot paths, preview paths, or invented image URLs unless the user explicitly supplied those image assets for the target site.",
            "When the user did not provide images, every visual/proof/media block ships as a unique inline SVG/vector composition. CSS color, borders, gradients, and grid scaffolding are fine as support, never as fake photo placeholders.",
            "Inline SVG is intentional: define a `viewBox`, set `fill` and `stroke` through CSS classes so design tokens flow through, give meaningful art a `<title>` (and `<desc>` when it carries information), and mark purely decorative SVG with `aria-hidden=\"true\"`. No clip-art aesthetics, no isometric-people-with-laptops, no abstract waveforms as filler.",
            "Class-based styling only. Inline styles are reserved for one-off dynamic values bound to state — never for layout, spacing rhythm, color, typography, or any part of the visual system.",
            "Sticky or fixed headers must reserve space and must not cover hero copy or section anchors; section targets need `scroll-margin-top` (or equivalent) so anchor jumps land cleanly with the target heading visible.",
            "Spacing comes from a clamp-based scale tied to design tokens, not from magic numbers. Buttons, badges, counters, hero media, cards, and CTA rows must hold their grid at 1512, 1440, 1280, 1024, 768, and 390 widths without overlap, clipping, or wrap that destroys meaning.",
            "Button and badge text must fit at 390px width without clipped letters, ellipsis on primary CTAs, unreadable wrapping, or stacked one-word-per-line wrapping that breaks the button shape. Touch targets are 44x44px minimum on mobile with at least 8px between adjacent tap targets.",
            "Reject placeholder copy in shipped output: no Lorem ipsum, no bracket placeholders, no generic SaaS verbs (transform, unlock, supercharge, elevate, empower, seamless, robust, world-class, revolutionary, game-changing, next-generation). Write copy specific to the vertical and task. When specifics are not supplied by the brief, write generalized phrasing that does not require invented numbers, names, or claims.",
            "No console errors in shipped output. No layout shift from font swap, image dimension miss, or async hydration. No focus rings hidden by `outline: none` without a styled replacement — `focus-visible` must register on every focusable control on both light and dark surfaces.",
        ]
    )


def _visual_asset_discipline() -> str:
    return _join_bullets(
        [
            "Every visual block has a distinct job: hero proof, service hierarchy, method or process diagram, facility or material proof, schedule or coverage map, authority signal, project evidence, or conversion support. Name the job first; build the visual to serve it.",
            "User-provided images are the only raster/photo assets allowed. Route screenshots, preview images, source screenshots, and manifest paths are references for grammar only — they never ship as `<img>`, `<picture>`, `<source>`, or `background-image: url()` in the generated page.",
            "If the user provides no images, use SVG-only visual assets: purposeful inline SVG proof boards, schedule diagrams, equipment or material samples, method maps, coverage diagrams, process timelines, or abstract facility compositions. Each one shaped to its section's job.",
            "Do not repeat polygon/blob SVGs, decorative cards, background noise layers, avatar silhouettes, gradient mesh wallpaper, or icon-only art as substitutes for distinct proof. The same SVG vocabulary used twice on the same page is slop. Three times is a tell.",
            "Icons are secondary UI affordances — they label, they signal direction, they classify. They never carry the main visual proof for a hero, program, coach, project, or facility section. A hero with only icon clusters as imagery has failed.",
            "Every media or proof block is inspectable and responsive. Avoid dark blurred stock-like rectangles, masked photos, or low-contrast plates that hide the thing the user needs to judge. If a block exists to prove something, the proof must be legible at the size the block appears.",
            "SVG craft: define a `viewBox`, prefer presentation through CSS classes that read tokens, use `<title>` for meaningful art, set `aria-hidden=\"true\"` on decoration, avoid filter stacks that crush in dark mode, and keep stroke widths visually consistent across the page.",
            "Geometry has a job too: pick one shape language (angular, rounded, organic) and hold it across the surface. Mixing languages without intent reads as accidental — restraint is a design choice.",
        ]
    )


def _claim_realism(resolution: RouteResolution, rules: RoutingRules) -> str:
    vertical = _vertical_rule(resolution, rules)
    lines = [
        "Do not invent championships, awards, certifications, league affiliations, rankings, famous clients, named coaches, testimonials, reviews, ratings, statistics, years-in-business numbers, or project counts.",
        "No fake UFC, Bellator, PFL, ONE, IBJJF, ADCC, Olympic, collegiate, military, or law-enforcement claims unless supplied by the user or source material.",
        "No fake \"As seen in\" press logos. No invented \"trusted by\" customer wordmarks. No fabricated star ratings. No invented review counts. No fake industry badges, ISO numbers, or accreditation seals.",
        "When proof is missing, use neutral verifiable phrasing: training format, intake process, class structure, facility features, coaching methodology, service capability, geographic coverage logic, or next-step clarity. The page can still convince without invented authority.",
        "Avoid absurd numbers, unverifiable superlatives, and adjective-stacked authority claims. Do not imply medical, legal, safety, financial-return, or guaranteed-outcome results.",
        "Numerical specifics, when used, come from the brief. \"11 years in commercial HVAC retrofit\" works only if the brief supplies the 11 and the specialty. If it does not, write copy that does not lean on the specific.",
        "Testimonials, when shipped, must be supplied verbatim by the brief and attributed to a real, supplied source. Do not paraphrase, do not embellish, do not generate plausible-sounding quotes.",
    ]
    if vertical and vertical.claim_guardrails:
        lines.extend(vertical.claim_guardrails)
    return _join_bullets(lines)


def _layout_qa_gates() -> str:
    return _join_bullets(
        [
            "Review the page at 1512x812 (primary review viewport), 1440px, 1280px, 1024px, 768px, and 390px. Capture the first viewport at each width and scroll the full page at 1512 and 390. Edge widths are the canary widths — they fail first.",
            "First-viewport check at each width: brand signal visible, primary CTA visible or one scroll-anchor away, secondary nav clearly accessible, hero content readable without horizontal scroll, no oversized first folds that delay the page's intent.",
            "Mid-page check: section transitions read as intentional. No accidental gaps from collapsed margins, no card heights jumping due to uneven content, no empty padding pools, no orphan headings without a connecting paragraph or visual.",
            "At 390px: tap targets at least 44x44px, primary CTA full-width or unambiguously tappable, headlines wrap without orphan words, phone numbers ship as `tel:` links, sticky header collapses cleanly without covering the hero. At 1512: hero composition does not feel under-filled, container `max-width` is honored, content does not stretch to soup.",
            "Tab through the entire page: focus order matches visual order. Every interactive element receives a visible focus ring. No focus traps. Skip-to-content link works and is visible on focus.",
            "Toggle `prefers-reduced-motion`: every animation, parallax, scroll-tied effect, autoplay, and animated SVG collapses to an instant or near-instant state. If shipping a dark theme: contrast still passes WCAG AA at every text/surface pair, and brand color remains a punctuation mark, not a wash.",
            "Console: zero errors, zero deprecated-API warnings, zero hydration mismatch. Network: no failed requests, no preload misses, no oversized images. Lighthouse for marketing surfaces: Performance ≥ 90, Accessibility ≥ 95, Best Practices ≥ 95 — document any deviation with a reason.",
            "Do not rely on viewport-scaled font sizes. Use clamp(min, preferred, max) with bounded min and max so type reads at every breakpoint. Responsive containers, grid tracks, min/max, and stable component dimensions over magic numbers.",
            "Fix on sight: hero overlap, oversized first folds, sticky-header anchor clipping, mobile nav blocking, floating-card collisions, card-height chaos, CTA wrapping, image dimension miss, font-swap layout shift, and any text that depends on viewport-scaled sizing without bounds.",
        ]
    )


def _mobile_first_gates() -> str:
    return _join_bullets(
        [
            "Mobile is a DESIGNED experience, not a collapsed desktop. The bar at 390/360px: the page should feel composed — intentional rhythm, purposeful section framing — not merely 'nothing broken'. Anchor patterns are desktop-tuned; translate their mobile treatment deliberately.",
            "Sticky/fixed CTA bars may NEVER coexist on screen with a duplicate in-flow CTA. If both exist, suppress one contextually (hide the sticky bar while the in-flow control is visible — IntersectionObserver or scroll logic). Two stacked 'book now' controls is an automatic fail.",
            "The wordmark/nav must fit the REAL brand name at 390 and 360. Anchor wordmark treatments are tuned to their fictional name's length — re-fit yours: clamp the size, allow a deliberate single-line fallback, and never let the menu button clip off-edge or the name wrap mid-word.",
            "Kill dead scroll: desktop padding tokens (64-96px section pads) usually need a mobile step-down; a mobile page that is mostly empty vertical space between thin content columns reads as neglect.",
            "Every tap target ≥ 44x44px effective (visible size may stay smaller with an expanded hit-area). Check filter chips, carousel dots, social icons, close buttons — the small controls are where this fails.",
            "Wide components (tables, terminals, multi-column stat rails) get a REAL mobile treatment: stack, or horizontal scroll with a visible affordance cue. Never let one squeeze to illegibility or force page-level horizontal overflow.",
            "Fixed floating elements (back-to-top, chat bubbles, sticky bars) must clear the footer's last content line at true scroll-end on every width, and hide while overlays/modals are open.",
            "Before finishing: render at BOTH 390 and 360 (360 fails first), full-page scroll, zero horizontal overflow (scrollWidth === innerWidth), and every interactive control click-tested at mobile width.",
        ]
    )


def _production_bar_preamble() -> str:
    return _join_bullets(
        [
            "Every contract below is a hard floor for production code, not a target or a suggestion. The page ships only when each contract is satisfied.",
            "Donors give you composition skeleton and density rhythm. The brief gives you identity, copy, and proof. The contracts give you the engineering, accessibility, and craft bar. Borrow only what the donor provides. Build the rest. Invent nothing.",
            "When in doubt: cut decoration, add specificity, verify contrast, test the smallest viewport, and write the smallest correct CSS rather than the largest plausible. Restraint is a design choice.",
        ]
    )


def _micro_production_discipline() -> str:
    return _join_bullets(
        [
            "No emojis in visible UI. No fake images, no fake stats, no fake testimonials, no invented authority claims, no Lorem ipsum, no bracket placeholders.",
            "One SVG, one job. Never recycle the same polygon, blob, gradient mesh, or icon family across sections as filler. Raster/photo images only when the user supplied them; otherwise build inline SVG/vector proof surfaces unique per section.",
            "Class-based CSS only, reading from tokens (color pairs, type scale, 4px or 8px spacing, named radii, motion durations). No magic numbers. No hardcoded hex outside the token file.",
            "Spacing on a clamp scale. Buttons fit at 390px width without clipped letters. Touch targets 44x44px minimum on mobile with 8px gaps. Sticky headers reserve space and do not cover anchors.",
            "Focus-visible rings on every focusable element — never hide with `outline: none` without a styled replacement. Keyboard reach for every action. Semantic HTML first. Skip-to-content link as the first focusable element.",
            "Honor `prefers-reduced-motion`. Animate `transform` and `opacity` only. ~150ms micro-interactions, ~220ms transitions, ~320ms reveals. Nothing past 450ms outside a deliberate hero choreography.",
            "Body 15-18px, line-height 1.5-1.65, measure 50-75ch. Two type families maximum, three weights per family maximum. WCAG AA contrast at every text/surface pair.",
            "Borrow composition from the anchor; build identity, copy, and proof from the brief. Invent nothing — no awards, no stats, no named clients, no testimonials, no years-in-business, no project counts.",
            "Review at 1512x812, 1440px, 1280px, 1024px, 768px, and 390px width. No console errors. No layout shift. No focus traps.",
        ]
    )


def _design_tokens_contract() -> str:
    return _join_bullets(
        [
            "Define tokens before writing components. A color palette in semantic pairs (surface and on-surface, brand and on-brand, plus success/warning/danger and their on-* foregrounds). A type scale of six to eight named steps from a single ratio (1.125, 1.2, 1.25, or 1.333). A 4px or 8px base spacing scale. Named radii (radius-none/sm/md/lg) chosen as a system and held. Motion durations (fast ~150ms, base ~220ms, slow ~320ms). Motion easings (standard, entrance, exit). A z-index layering scheme.",
            "Tokens live as CSS custom properties on `:root` (and at most one alternate theme scope). Every component reads from tokens. No hardcoded hex outside the token file. No one-off px values for spacing. No inline `rgba()` per element.",
            "Color tokens come in pairs with verified WCAG contrast: AA (4.5:1) for body text, AA Large (3:1) for ≥18px or ≥14px bold. Verify pairs at every used combination — never assume a brand color works on every surface. Disabled state still registers at 3:1 minimum.",
            "Type tokens carry both `font-size` and `line-height`. Headline tokens carry `letter-spacing` (slightly negative for large display, neutral for body, slightly positive for small caps and label/badge type). Body tokens carry a `max-width` measure bound between 50ch and 75ch.",
            "Reject brand-named utility classes (e.g. `text-blue-500` baked into markup) that fossilize palette decisions. Prefer semantic names — `text-primary`, `surface-elevated`, `border-subtle`, `brand-accent` — so a theme swap is one variable change.",
            "Choose at most two type families: one display/heading, one body/UI. A monospace family is permitted for tabular numerics or code. Three families maximum. No more than three weights in active use per family (400/500/700 is a defensible default).",
            "Brand color is a punctuation mark, not a wash. Limit its surface coverage to roughly 10-15% of the visible viewport at any time. The base canvas is neutral; brand color marks intent, state, and the primary action.",
        ]
    )


def _motion_grammar() -> str:
    return _join_bullets(
        [
            "Default durations: ~150ms for micro-interactions (hover, focus, press), ~220ms for component transitions (panel open, tab change, modal), ~320ms for page-section reveals. Nothing exceeds 450ms unless it is a single deliberate hero choreography.",
            "Easing: `cubic-bezier(0.22, 1, 0.36, 1)` for entrances, `cubic-bezier(0.4, 0, 0.2, 1)` for state transitions, `linear` only for indeterminate loading. Reserve bouncy or elastic springs for marketing-only moments; functional UI uses calm, deterministic curves.",
            "Honor `prefers-reduced-motion`. Every transform, parallax, scroll-tied effect, autoplay, fade-on-scroll, and animated SVG must collapse to an instant or near-instant state when reduced motion is requested. Test this branch — do not assume the user reaches a working page if you skip it.",
            "Choreograph entrances: nearby elements move together, distant elements stagger by 40-80ms. Do not animate every element on the page independently — the eye reads chaos, not delight. Two synchronized reveals beat seven independent ones.",
            "Animate `transform` and `opacity` for performant motion. Do not animate `width`, `height`, `top`, `left`, `margin`, or `background-color` on hot paths. Use `transform: translate3d()` and `will-change` only on the elements actually animating, and remove the hint after.",
            "Scroll-tied animation runs through `IntersectionObserver`, CSS scroll-driven animations, or rAF-throttled handlers — never per-scroll-event JS.",
            "No autoplaying video with audio. No marquees. No carousels that auto-rotate faster than ~6 seconds per slide; auto-rotation pauses on pointer hover and keyboard focus.",
            "Motion serves clarity, not delight-for-its-own-sake. Every animation answers: what state changed, what relationship is being shown, what is the user being directed to. If it answers none, cut it.",
        ]
    )


def _typography_discipline() -> str:
    return _join_bullets(
        [
            "Body copy ranges 15-18px on desktop, 16-17px on mobile. Line-height 1.5-1.65 for body, 1.1-1.25 for display headings. Measure (line length) stays between 50ch and 75ch for primary reading surfaces.",
            "Display headings adjust letter-spacing at scale: -1% to -3% tracking for large display, 0 for body, +1% to +4% for small caps and label/badge type.",
            "Use `clamp(min, preferred, max)` for fluid display sizing with min and max bounded so the page reads at every breakpoint. Never set body font-size in `vw` alone.",
            "Optical sizing where the font supports it: `font-variation-settings` or `font-optical-sizing: auto` for variable fonts. Tabular figures (`font-feature-settings: 'tnum'`) for numeric tables and counters.",
            "Headlines name the specific value for the specific buyer of the specific business. Avoid abstract verbs and category nouns. A first-fold headline must answer: who this is for, what it does, why now.",
            "All-caps is reserved for eyebrow labels, small tags, and badge type with positive tracking. Never set body, sub-headings, or primary CTAs in all-caps.",
            "Sentence case for buttons and most UI labels. Title Case only if the brand voice is explicitly Title Case. Pick one and hold it across the entire surface.",
            "Hyphenation and orphan control: enable `text-wrap: balance` for headlines, `text-wrap: pretty` for body where supported, and avoid single-word orphans on display lines.",
        ]
    )


def _accessibility_contract() -> str:
    return _join_bullets(
        [
            "Semantic HTML first: `<button>` for actions, `<a>` for navigation, `<h1>`-`<h3>` in document order, landmarks (`<nav>`, `<main>`, `<footer>`, `<aside>`), and `<label for>` on every input. Heading levels never skip.",
            "Every interactive control is keyboard reachable via Tab; every dismissible surface via Escape; every menu, listbox, and tablist via arrow keys where the convention applies. Focus never disappears into the void after activation — it lands on the next logical control or the surface that opened.",
            "Focus-visible rings on every focusable element. Style them — never remove with `outline: none` unless you ship a styled replacement that registers at 3:1 contrast against both the focused element and its surrounding surface, with a 2px minimum and offset.",
            "ARIA only when semantics fall short. `aria-label` only when no visible label exists. `aria-live` for async announcements. `aria-expanded` / `aria-controls` on disclosure widgets. `role` only when the native element does not exist. Mis-applied ARIA is worse than no ARIA.",
            "Skip-to-content link as the first focusable element on every page. Visible on focus.",
            "Image alt text describes the image's purpose, not its appearance. Decorative SVG gets `aria-hidden=\"true\"`. Iconography that carries meaning gets an accessible name via `<title>` or `aria-label`.",
            "Never communicate state with color alone. Pair color with an icon, a shape, or a text label.",
            "Touch targets are 44x44px minimum on mobile with at least 8px between adjacent tap targets.",
            "Form errors identify the specific field, the specific problem, and the specific fix. Errors are programmatically associated with the input via `aria-describedby`. `aria-invalid=\"true\"` on the failing input.",
            "Honor `prefers-reduced-motion`, `prefers-color-scheme`, and `prefers-contrast` where the design supplies a variant. If a variant is not supplied, default to the lower-stimulation choice.",
        ]
    )


def _state_completeness_contract() -> str:
    return _join_bullets(
        [
            "Every interactive element ships its full state vocabulary: default, hover, focus-visible, active, disabled, and where applicable, loading and selected. Buttons, links, inputs, tabs, accordions, switches, checkboxes, cards-as-links, table-rows-as-links.",
            "Every async surface ships four states: loading (skeleton matching the content shape), empty (with a clear next action — never just a sad icon and a noun), error (with a concrete recovery path), and success.",
            "Inputs ship: idle, focus, filled, error with message, success when validation is informative, disabled. Error messages name the specific problem and the specific fix.",
            "Skeletons mirror the shape of the content they replace. Spinners belong inside buttons during action, not in content panels. Skeletons last at most ~1.5s before timing out into an error state with a retry path.",
            "Disabled never means \"the button looks faded but still fires\". A disabled control is genuinely uninteractive (`disabled` attribute, `aria-disabled` where appropriate). A validating control stays enabled with clear messaging.",
            "Toast and notification system: success, info, warning, error with consistent placement, dismiss affordance, and timing that scales with severity (errors persist until acknowledged; success auto-dismisses after a few seconds; never block the viewport).",
            "Optimistic UI is permitted only when the failure path is also designed: how the rollback looks, what the user sees, and how they retry.",
        ]
    )


def _performance_discipline() -> str:
    return _join_bullets(
        [
            "LCP candidate (hero headline, hero image, or hero card) ships with explicit `width`/`height` or `aspect-ratio`, `fetchpriority=\"high\"` on the LCP image if it is an image, and zero layout shift on render.",
            "Above-the-fold content does not depend on JS hydration to be readable. Server-render or static-generate the hero, primary nav, and footer CTA.",
            "Font loading: `font-display: swap` with a tuned fallback metric (`size-adjust`, `ascent-override`, `descent-override`) to avoid CLS. Preload the LCP font weight only — never every weight.",
            "Images carry `width`/`height` attributes (or `aspect-ratio` CSS) so the browser reserves space before fetch. Below-the-fold images use `loading=\"lazy\"`; LCP images do not.",
            "Code-split below the fold. Lazy-load components on intersection or interaction. The initial JS bundle for a marketing surface stays under a defensible budget (under 100KB compressed for landing pages is a reasonable starting line).",
            "No layout shift after first paint. Reserve space for embeds, async banners, cookie notices, third-party widgets, and async-mounted UI.",
            "No console errors. No mixed content. No 404s for assets. No render-blocking third-party scripts in the critical path. No `document.write`. No synchronous `XMLHttpRequest`.",
            "Cache discipline: long cache headers on hashed assets, sensible cache for HTML, and a service worker only when the offline story is real.",
        ]
    )


def _microcopy_contract() -> str:
    return _join_bullets(
        [
            "Headlines are specific to the buyer, the offer, and the situation. Avoid abstract verbs and category nouns. \"Heated-floor installation for renovated brownstones\" beats \"Premium flooring solutions.\"",
            "Buttons name the action and what happens after. \"Request a same-week quote\" beats \"Get started\". \"Call (XXX) XXX-XXXX\" beats \"Contact us\" when the phone is real and supplied by the brief.",
            "Empty states tell the user what is missing and what to do. \"No reviews yet — be the first\" with a primary action beats \"No data\".",
            "Error messages identify the specific problem and the specific fix. Never \"An error occurred.\" or \"Something went wrong.\" without specifics. Errors that are not the user's fault apologize once, name what failed, and offer a path forward.",
            "Form labels live above inputs, help text below input, error text below help text. Required indicated consistently — either by `*` with a legend, or inline `(required)`. Pick one and hold across the page.",
            "Strike SaaS clichés on sight: transform, unlock, supercharge, elevate, empower, seamless, robust, cutting-edge, world-class, revolutionary, game-changing, next-generation, AI-powered (without specifics), best-in-class, enterprise-grade.",
            "Numerical specifics, when used, come from the brief. \"11 years in commercial HVAC retrofit\" works only if the brief supplies the 11 and the specialty. If a specific is not supplied, write copy that does not require one — never invent.",
            "Voice is grounded and exact. Avoid exclamation points outside genuine moments of celebration. Avoid hedging modifiers (\"basically\", \"essentially\", \"just\") in primary copy. Avoid stacked adjectives (\"premium, world-class, end-to-end\") that read as filler.",
            "Sentence rhythm: vary length. A paragraph of seven 14-word sentences reads as machine-generated. Mix short with longer. Read it aloud — if it stumbles, rewrite.",
        ]
    )


def _vertical_guardrails(resolution: RouteResolution, rules: RoutingRules) -> str:
    vertical = _vertical_rule(resolution, rules)
    if vertical is None:
        return ""
    lines: list[str] = []
    if vertical.visual_direction:
        lines.append("Visual direction:")
        lines.extend(f"  - {item}" for item in vertical.visual_direction)
    if vertical.reject_patterns:
        lines.append("Reject:")
        lines.extend(f"  - {item}" for item in vertical.reject_patterns)
    return "\n".join(lines)


def _active_packet_intent(request: DesignContextRequest) -> str:
    if request.packet_intent not in {"balanced", "code_first"}:
        return request.packet_intent
    if request.code_profile == "code_first" and request.packet_intent == "balanced":
        return "code_first"
    return request.packet_intent


def _composition_recipe(resolution: RouteResolution, rules: RoutingRules) -> dict:
    vertical = resolution.normalized_request.specialty_service_class or ""
    recipe = rules.composition_recipes.get(vertical, {})
    return recipe if isinstance(recipe, dict) else {}


def _composition_brief(resolution: RouteResolution, rules: RoutingRules) -> str:
    recipe = _composition_recipe(resolution, rules)
    if not recipe:
        return ""
    target = recipe.get("section_count_target", [])
    if isinstance(target, list) and len(target) == 2:
        target_text = f"[{target[0]}, {target[1]}]"
    else:
        target_text = "not specified"
    lines = [
        f"section_count_target: {target_text}",
        f"surface_palette_distribution: {recipe.get('surface_palette_distribution', 'not specified')}",
        f"density_curve: {recipe.get('density_curve', 'not specified')}",
        "The page needs at least two deliberate rhythm breaks: one in the first viewport and one mid-page. Do not let section after section share the same card row or plate shape.",
    ]
    rhythm_breaks = recipe.get("rhythm_breaks") or []
    if rhythm_breaks:
        lines.append("Required rhythm breaks:")
        lines.extend(f"  - {item}" for item in rhythm_breaks)
    forbidden = recipe.get("forbidden_repetitions") or []
    if forbidden:
        lines.append("Forbidden repetitions:")
        lines.extend(f"  - {item}" for item in forbidden)
    artifact_briefs = recipe.get("artifact_briefs") or []
    if artifact_briefs:
        lines.append("Composition slots:")
        for brief in artifact_briefs:
            slot = brief.get("slot", "section")
            vocabulary = brief.get("vocabulary", "unspecified")
            layout_shape = brief.get("layout_shape", "unspecified")
            lines.append(f"  - slot `{slot}` uses layout_shape `{layout_shape}` and artifact vocabulary `{vocabulary}`.")
    return "\n".join(lines)


def _visual_artifact_specs(resolution: RouteResolution, rules: RoutingRules) -> str:
    recipe = _composition_recipe(resolution, rules)
    artifact_briefs = recipe.get("artifact_briefs") or []
    if not artifact_briefs:
        return ""
    blocks = [
        "Use a distinct artifact vocabulary per slot. If two sections start to share the same SVG grammar, rebuild the later one with a different vocabulary from this list.",
    ]
    vocabularies: list[str] = []
    for brief in artifact_briefs:
        slot = brief.get("slot", "section")
        vocabulary = str(brief.get("vocabulary", "unspecified"))
        vocabularies.append(vocabulary)
        must_carry = ", ".join(brief.get("must_carry") or []) or "section job and next action"
        forbidden = ", ".join(brief.get("forbidden_motifs") or []) or "reused donor identity"
        viewbox = brief.get("viewbox") or "0 0 900 600"
        blocks.append(
            "\n".join(
                [
                    f"## Artifact: {slot}",
                    f"- vocabulary: `{vocabulary}`",
                    f"- layout_shape: `{brief.get('layout_shape', 'unspecified')}`",
                    f"- viewBox: `{viewbox}`",
                    f"- must_carry: {must_carry}",
                    f"- forbidden_motifs: {forbidden}",
                ]
            )
        )
    unique = sorted(set(vocabularies))
    blocks.append(
        "Forbidden cross-section recycling: do not reuse an artifact vocabulary from one slot in another slot. "
        f"Allowed vocabularies for this route: {', '.join(f'`{item}`' for item in unique)}."
    )
    return "\n\n".join(blocks)


def _local_model_failure_patterns(resolution: RouteResolution, rules: RoutingRules) -> str:
    recipe = _composition_recipe(resolution, rules)
    patterns = recipe.get("local_model_failure_patterns") or []
    if not patterns:
        return ""
    lines = []
    for pattern in patterns:
        trigger = pattern.get("if", "").strip()
        fix = pattern.get("then", "").strip()
        if trigger and fix:
            lines.append(f"If {trigger}, then {fix}.")
    return _join_bullets(lines[:10])


def _donor_starvation_warning(resolution: RouteResolution) -> str:
    meta = resolution.route_meta.get("donor_starvation", {})
    if meta.get("native_count") != 0:
        return ""
    lines = [
        "Native support examples for this vertical are donor-starved. This is a routing warning, not permission to copy unrelated identity.",
        f"reason: {meta.get('reason', 'not specified')}",
        f"inferred ux_roles: {', '.join('`' + role + '`' for role in meta.get('request_ux_roles', [])) or 'none'}",
    ]
    dropped_for = meta.get("dropped_for", {})
    if dropped_for:
        lines.append(
            "dropped_for: "
            + ", ".join(f"{key}={value}" for key, value in dropped_for.items())
        )
    display_map = _example_display_map(resolution)
    donors = meta.get("mechanical_donors", [])
    donor_labels = ", ".join(f"`{_display_id(display_map, donor)}`" for donor in donors) or "none"
    lines.append(f"mechanical donors: {donor_labels}")
    lines.append("Borrow only UX mechanics such as intake flow, proof placement, schedule clarity, or process sequencing. Do not borrow identity, copy, palette, business name, section labels, decorative motifs, claims, testimonials, statistics, or vertical tone.")
    lines.append("Route alternative: add native examples for this vertical when possible; mechanical donors are a bridge for structure, not a design identity.")
    return _join_bullets(lines)


def _mechanical_donors(resolution: RouteResolution) -> str:
    if resolution.support_bank is None or not resolution.route_meta.get("mechanical_donor_ids"):
        return ""
    lines = [
        "Mechanical donors are UX-role-only references. They are selected because the native vertical donor pool was empty.",
        "Hard boundary: do not borrow identity/copy/palette/business name/section labels, decorative motifs, claims, testimonials, statistics, or tone.",
    ]
    display_map = _example_display_map(resolution)
    for selection in resolution.selected_examples:
        if not selection.ux_role_match:
            continue
        display_id = _display_id(display_map, selection.example_id)
        roles = ", ".join(f"`{role}`" for role in selection.ux_role_match)
        lines.append(f"`{display_id}`: borrow {roles}; do_not_borrow: identity/copy/palette/business name/section labels.")
        lines.append(
            "operator excerpt pull: "
            f"`get_source_excerpt(pack_id=\"{resolution.support_bank.manifest.pack_id}\", "
            f"example_id=\"{selection.example_id}\", include_full=true, include_section_snippets=true)`"
        )
    return _join_bullets(lines)


def _implementation_contract(request: DesignContextRequest, resolution: RouteResolution) -> str:
    geometry = "low-radius/angular geometry" if request.prefer_angular_geometry else "geometry that fits the source grammar"
    browser = (
        "Run a real browser review loop before declaring the page done: open every viewport width listed in Layout QA Gates, scroll the full page at the edge widths, and fix what you see."
        if request.host_browser_review
        else "Preview locally if the host workflow supports it. If it does not, state the assumptions you made about responsive behavior and accessibility in your handoff — never quietly ship untested."
    )
    strict = ""
    if request.pattern_lock_exact:
        strict = "Pattern lock exact: preserve the anchor's visible slot structure, then translate content and identity into the target business."
    elif request.pattern_lock_strict:
        strict = "Pattern lock strict: preserve anchor slot-level hierarchy before allowing styling variation."
    elif request.pattern_lock:
        strict = "Pattern lock: map each major anchor section to an equivalent target-business section."
    else:
        strict = "Flexible borrow: keep the anchor's organizing logic while adapting layout details to the brief."
    vertical = resolution.normalized_request.specialty_service_class or "general local service"
    lines = [
        f"Target vertical: `{vertical}`.",
        f"Default shape language: {geometry}. Hold one shape language across the surface — mixing rounded, angular, and organic without intent reads as accidental.",
        strict,
        "Component boundaries: separate component from layout from page. A Card knows nothing about which grid it sits in. A Section knows the grid but not the page. Pages compose; they do not redefine.",
        "Naming: PascalCase components, files matching component names, camelCase props, kebab-case or BEM CSS class names (pick one and hold it), and semantic design tokens prefixed by `surface-`, `text-`, `border-`, `brand-`, `state-`.",
        "Progressive enhancement on marketing surfaces: the page renders and core actions work without JS. JS adds polish, not load-bearing behavior. Hydrate only the islands that need it.",
        "Server-render the hero, primary nav, and footer CTA at minimum. Avoid client-side date or locale formatting that produces hydration mismatch — render server-side or use a stable formatter.",
        "Use raster/photo image paths only when the user supplied them for this target site; otherwise build unique inline SVG/vector proof surfaces instead of fake image placeholders.",
        "Copy is real to the brief. Do not invent claims, names, statistics, testimonials, awards, certifications, locations served, years in business, project counts, pricing, or contact details. When specifics are not supplied, write generalized phrasing that does not require them.",
        "Optional patterns are decisions, not obligations. Record the chosen pattern IDs and the single job each solves; choosing none is valid. Drop any fragment that conflicts with the anchor or adds a second identity.",
        "Smallest correct CSS over largest plausible. Smallest correct markup over largest plausible. If a rule, class, attribute, or element does not earn its place, delete it before shipping.",
        browser,
    ]
    return _join_bullets(lines)


def _section_plan(resolution: RouteResolution, rules: RoutingRules) -> str:
    vertical = resolution.normalized_request.specialty_service_class or "local service"
    vertical_rule = _vertical_rule(resolution, rules)
    if vertical_rule and vertical_rule.section_plan:
        plan = list(vertical_rule.section_plan)
    else:
        plan = [
            f"Hero: one clear promise for the {vertical} business, primary CTA, phone/contact path, and one proof/authority object.",
            "Trust rail: compact credentials, service area, process reassurance, or review proof; no fake claims.",
            "Service clarity: group 3-5 services by buyer intent, not by generic card filler.",
            "Proof/process section: show what happens next, before/after logic, material/process detail, or project evidence depending on available assets.",
            "Conversion band: restate fit, show next step, and make contact friction low.",
        ]
        tags = set(resolution.normalized_request.motif_tags + resolution.normalized_request.strength_tags)
        if "service_map" in tags or "map_or_coverage_signal" in tags:
            plan.insert(3, "Coverage section: name service-area logic and make local availability easy to scan.")
        if "material_showcase" in tags:
            plan.insert(3, "Material/detail section: show craft, finishes, components, or restoration evidence with restrained pacing.")
        if "process_timeline" in tags:
            plan.insert(3, "Process timeline: make the start-to-finish path concrete and short.")
    return _join_bullets(plan)


def _append_block(
    blocks: list[str],
    block: str,
) -> bool:
    if not block:
        return False
    blocks.append(block)
    return True


def _atom_file_chars(atom, mode: str) -> None:
    return None


def _atom_adapt_line(atom) -> str:
    """One short 'how to adapt' line from meta summary or notes."""
    if getattr(atom, "summary", ""):
        return _trim(" ".join(atom.summary.split()), 240)
    notes = (atom.notes or "").strip()
    if not notes:
        return "Adapt class names, copy, palette, and claims to the target business; keep the structure, tokens, motion, and a11y."
    # First non-heading line of notes.
    for line in notes.splitlines():
        stripped = line.strip().lstrip("# ").strip()
        if stripped:
            return _trim(" ".join(stripped.split()), 240)
    return _trim(" ".join(notes.split()), 240)


def _render_atom_block(
    atom,
    *,
    mode: str,
    request: DesignContextRequest | None = None,
) -> str:
    header = f"## Component `{atom.atom_id}`"
    if getattr(atom, "category", ""):
        header += f" ({atom.category})"
    parts = [header, f"How to adapt: {_atom_adapt_line(atom)}"]
    roles_tags = []
    if getattr(atom, "ux_roles", None):
        roles_tags.append("ux_roles: " + ", ".join(f"`{r}`" for r in atom.ux_roles))
    if getattr(atom, "tags", None):
        roles_tags.append("tags: " + ", ".join(atom.tags[:8]))
    if roles_tags:
        parts.append(" · ".join(roles_tags))
    file_chars = _atom_file_chars(atom, mode)
    code_blocks = list(getattr(atom, "code_blocks", []) or [])
    if not code_blocks and atom.snippet:
        parts.append(
            _code_block(
                atom.language,
                atom.snippet,
                max_chars=file_chars,
                request=request,
            )
        )
    for code_file in code_blocks:
        block = _code_block(
            code_file.language,
            code_file.content,
            max_chars=file_chars,
            request=request,
        )
        if block:
            parts.append(f"`{code_file.label}`\n{block}")
    return "\n".join(parts)


def _design_tokens_starter(resolution: RouteResolution, *, mode: str) -> str:
    """The foundation `:root` token starter code.

    Kept in its own section (contract-class, never trimmed) so the keystone token
    block every other component reads from always survives, even under tight budget.
    At micro/compact this renders the token CSS (the `:root` block + helpers); at
    standard+ it also includes the demo HTML so the full atom is visible.
    """
    from .atom_selector import FOUNDATION_ATOM_ID

    atom = next((a for a in resolution.shared_atoms if a.atom_id == FOUNDATION_ATOM_ID), None)
    if atom is None:
        return ""
    intro = _join_bullets(
        [
            "Paste this `:root` token block once at the top of your stylesheet; every component below reads from these custom properties. This IS the design-system contract expressed as code.",
            "Swap the palette/brand values for the target business, but keep the token names, the type scale, the spacing scale, the radii, and the motion tokens — the components depend on them.",
        ]
    )
    file_chars = _atom_file_chars(atom, mode)
    blocks = [intro]
    code_blocks = list(getattr(atom, "code_blocks", []) or [])
    for code_file in code_blocks:
        block = _code_block(
            code_file.language,
            code_file.content,
            max_chars=file_chars,
            request=resolution.request,
        )
        if block:
            blocks.append(f"`{code_file.label}`\n{block}")
    if not code_blocks and atom.snippet:
        blocks.append(
            _code_block(
                atom.language,
                atom.snippet,
                max_chars=file_chars,
                request=resolution.request,
            )
        )
    return "\n\n".join(blocks)


def _reusable_component_library(resolution: RouteResolution, *, mode: str) -> str:
    """Surface the SELECTED first-party reference COMPONENTS WITH their real code.

    A primary deliverable for local models: every relevance-selected, complete,
    copy-adaptable component (html, then css, then js). The foundation token starter
    is rendered separately.
    """
    from .atom_selector import FOUNDATION_ATOM_ID

    atoms = [a for a in resolution.shared_atoms if a.atom_id != FOUNDATION_ATOM_ID]
    if not atoms:
        return ""
    intro = _join_bullets(
        [
            "Real, copy-adaptable component code built on the Design Tokens Starter above. Translate class names, copy, palette, and claims to the target business — keep the token discipline, motion, responsive structure, and accessibility.",
            (
                "External font and asset loaders have been removed for this self-contained brief. "
                "Use system fonts or user-supplied local assets; do not restore network imports."
                if _request_forbids_external_dependencies(resolution.request)
                else "Keep one project-level font strategy instead of duplicating font loads per component."
            ),
            "These are reference implementations, not brand identity — do not ship placeholder copy (`[TESTIMONIAL_QUOTE]`, `[PRICE]`, etc.).",
        ]
    )
    blocks: list[str] = [intro]
    for atom in atoms:
        block = _render_atom_block(
            atom,
            mode=mode,
            request=resolution.request,
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _code_reference_intro(resolution: RouteResolution, *, mode: str, rules: RoutingRules) -> str:
    lines = [
        "Use these as implementation reference code, not copy-paste identity. Translate class names, content, palette, and claims to the target business.",
        f"Capacity policy: `unbounded`. The `{mode}` label does not cap code blocks, source characters, sections, or estimated tokens.",
        "Every relevance-selected source file and pattern fragment is emitted complete. Estimated token counts are telemetry only.",
        f"code_profile: `{resolution.request.code_profile}`.",
    ]
    if resolution.request.code_profile == "code_first":
        lines.append("Code-first mode: selected implementation source is promoted before generic atoms so local models see real donor mechanics early.")
    if resolution.support_bank is not None and resolution.selected_examples:
        display_map = _example_display_map(resolution)
        examples = ", ".join(f"`{_display_id(display_map, selection.example_id)}`" for selection in resolution.selected_examples)
        lines.append(f"Selected support examples included in full: {examples}.")
    if resolution.optional_patterns:
        lines.append(
            f"The Optional Pattern Shelf contains {len(resolution.optional_patterns)} inlined Pattern Cards and "
            f"{len(resolution.optional_pattern_catalog)} qualified catalog entries. Cards are zero-or-more choices "
            "and do not count against the primary anchor."
        )
    return _join_bullets(lines)


def _code_patterns(resolution: RouteResolution, *, mode: str, rules: RoutingRules) -> str:
    max_chars = css_chars = atom_chars = None
    blocks: list[str] = []
    anchor = resolution.anchor_pack
    blocks.append(_code_reference_intro(resolution, mode=mode, rules=rules))
    anchor_is_in_full_build = bool(resolution.route_meta.get("anchor_full_source"))
    if anchor.anchor_markup_excerpt and not anchor_is_in_full_build:
        _append_block(
            blocks,
            "## Anchor markup excerpt\n"
            + _code_block(
                anchor.anchor_markup_language,
                anchor.anchor_markup_excerpt,
                max_chars=max_chars,
                request=resolution.request,
            ),
        )
    if anchor.anchor_css_excerpt and not anchor_is_in_full_build:
        _append_block(
            blocks,
            "## Anchor CSS excerpt\n"
            + _code_block(
                anchor.anchor_css_language,
                anchor.anchor_css_excerpt,
                max_chars=css_chars,
                request=resolution.request,
            ),
        )
    if resolution.hero_reference_pack is not None:
        for file in resolution.hero_reference_pack.anchor_source_files:
            blocks.append(
                "## Hero Reference Source\n"
                + _code_file_block(
                    file,
                    max_chars=max_chars,
                    request=resolution.request,
                )
            )
    display_map = _example_display_map(resolution)
    if resolution.support_bank is not None:
        for selection in resolution.selected_examples:
            example = resolution.support_bank.example_summaries.get(selection.example_id)
            if example is None:
                continue
            display_id = _display_id(display_map, selection.example_id)
            if example.full_code_files:
                blocks.append(f"## Full Support Source `{display_id}`")
                for file in example.full_code_files:
                    blocks.append(
                        _code_file_block(
                            file,
                            max_chars=max_chars,
                            request=resolution.request,
                        )
                    )
                continue
            if example.html_excerpt:
                blocks.append(
                    f"## Support `{display_id}` hero/markup snippet\n"
                    + _code_block(
                        "html",
                        example.html_excerpt,
                        max_chars=max_chars,
                        request=resolution.request,
                    )
                )
            for excerpt in example.section_job_excerpts:
                blocks.append(
                    f"## Support section snippet `{excerpt.label}`\n"
                    + _code_block(
                        excerpt.language,
                        excerpt.content,
                        max_chars=max_chars,
                        request=resolution.request,
                    )
                )
            if example.css_excerpt:
                blocks.append(
                    f"## Support `{display_id}` CSS snippet\n"
                    + _code_block(
                        "css",
                        example.css_excerpt,
                        max_chars=css_chars,
                        request=resolution.request,
                    )
                )
    # Shared reference atoms are surfaced in their own dedicated "Reusable Component
    # Library" section with full code; only pack-local anchor atoms appear here.
    for atom in anchor.atoms:
        if atom.snippet:
            blocks.append(
                f"## Atom `{atom.atom_id}`\n{_trim(atom.notes, 500)}\n"
                + _code_block(
                    atom.language,
                    atom.snippet,
                    max_chars=atom_chars,
                    request=resolution.request,
                )
            )
    return "\n\n".join(blocks) if blocks else "No code excerpts found for selected route."

def _code_density_metrics(resolution: RouteResolution) -> dict[str, int]:
    support_blocks = 0
    section_slices = 0
    support_full_files = 0
    if resolution.support_bank is not None:
        for selection in resolution.selected_examples:
            example = resolution.support_bank.example_summaries.get(selection.example_id)
            if example is None:
                continue
            support_blocks += int(bool(example.html_excerpt)) + int(bool(example.css_excerpt))
            section_slices += len(example.section_job_excerpts)
            support_full_files += len(example.full_code_files)
    atom_blocks = sum(1 for atom in [*resolution.anchor_pack.atoms, *resolution.shared_atoms] if atom.snippet)
    return {
        "anchor_blocks": int(bool(resolution.anchor_pack.anchor_markup_excerpt)),
        "anchor_css_blocks": int(bool(resolution.anchor_pack.anchor_css_excerpt)),
        "atom_blocks": atom_blocks,
        "support_blocks": support_blocks,
        "section_slices": section_slices,
        "optional_pattern_slices": len(resolution.optional_patterns),
        "optional_pattern_style_blocks": sum(
            int(pattern.style_excerpt is not None) for pattern in resolution.optional_patterns
        ),
        "optional_pattern_code_blocks": sum(
            int(pattern.excerpt is not None) for pattern in resolution.optional_patterns
        ),
        "optional_pattern_catalog_entries": len(resolution.optional_pattern_catalog),
        "full_files": len(resolution.anchor_pack.anchor_source_files) + support_full_files,
    }


def _omissions(resolution: RouteResolution, *, mode: str, rules: RoutingRules) -> tuple[str, list[str]]:
    omitted: list[str] = []
    if resolution.support_bank is not None:
        selected = set(resolution.selected_example_ids)
        unselected_count = len(
            set(resolution.support_bank.manifest.example_ids).difference(selected)
        )
        if unselected_count:
            if resolution.route_meta.get("source_selection", {}).get(
                "anchor_self_sufficient"
            ):
                omitted.append(
                    "secondary donors: withheld because the anchor covers the requested UX jobs"
                )
            else:
                omitted.append(
                    f"support examples: {unselected_count} incompatible or redundant donors withheld"
                )
    optional_meta = resolution.route_meta.get("optional_pattern_pool", {})
    optional_target = int(optional_meta.get("requested_count", 0) or 0)
    selected_optional = int(optional_meta.get("selected_count", 0) or 0)
    if optional_target and selected_optional < optional_target:
        reason = (
            "the anchor already covers the requested UX jobs"
            if optional_meta.get("anchor_self_sufficient")
            else "lower-fit fragments were withheld"
        )
        omitted.append(
            f"optional pattern slots: selected {selected_optional} of {optional_target}; {reason}"
        )
    if not omitted:
        omitted.append("none")
    return _join_bullets(omitted[:20]), omitted


def _packet_header(request: DesignContextRequest, resolution: RouteResolution, *, mode: str, rules: RoutingRules, body: str = "") -> str:
    density = _code_density_metrics(resolution)
    starvation = resolution.route_meta.get("donor_starvation", {})
    mechanical_ids = resolution.route_meta.get("mechanical_donor_ids", [])
    lines = [
        "# Design Router Packet",
        f"- token_mode: `{mode}`",
        f"- code_profile: `{request.code_profile}`",
        f"- packet_intent: `{_active_packet_intent(request)}`",
        "- capacity_policy: `unbounded`",
        "- estimated_tokens: telemetry only; never used to trim, drop, or shorten selected material",
        "- code_density: "
        f"anchor_blocks={density['anchor_blocks']}, "
        f"atom_blocks={density['atom_blocks']}, "
        f"support_blocks={density['support_blocks']}, "
        f"section_slices={density['section_slices']}, "
        f"optional_patterns={density['optional_pattern_slices']}, "
        f"optional_catalog={density['optional_pattern_catalog_entries']}, "
        f"full_files={density['full_files']}",
        f"- request: {request.task}",
        f"- anchor: `{resolution.anchor_pack.manifest.pack_id}`",
    ]
    if resolution.support_bank is not None and resolution.selected_examples:
        lines.append(f"- support_bank: `{resolution.support_bank.manifest.pack_id}`")
    if resolution.optional_patterns:
        lines.append(
            f"- optional_pattern_shelf: {len(resolution.optional_patterns)} inlined cards; "
            f"{len(resolution.optional_pattern_catalog)} qualified catalog entries (use zero or more)"
        )
    if starvation.get("native_count") == 0:
        display_map = _example_display_map(resolution)
        donor_labels = ", ".join(_display_id(display_map, donor) for donor in mechanical_ids) or "none"
        lines.append(f"- donor_starvation: yes (mechanical donors: {donor_labels})")
    lines.append("- expansion: unnecessary; selected source is already complete")
    return "\n".join(lines)


def _pack_sections(request: DesignContextRequest, resolution: RouteResolution, *, mode: str, rules: RoutingRules) -> list[_Section]:
    omit_text, _ = _omissions(resolution, mode=mode, rules=rules)
    strict_quality_sections: list[_Section] = []
    core_contract_sections: list[_Section] = []
    extended_contract_sections: list[_Section] = []
    if _visual_quality_enabled(request):
        strict_quality_sections = [
            _Section("Production Bar", _production_bar_preamble(), True),
            _Section("Hard UI Rules", _hard_ui_rules(), True),
            _Section("Visual Asset Discipline", _visual_asset_discipline(), True),
            _Section("Claim Realism / Proof Discipline", _claim_realism(resolution, rules), True),
            _Section("Layout QA Gates", _layout_qa_gates(), True),
            _Section("Mobile-First Gates", _mobile_first_gates(), True),
        ]
        core_contract_sections.extend(
            [
                _Section("Design Tokens Contract", _design_tokens_contract(), True),
                _Section("Motion Grammar", _motion_grammar(), True),
                _Section("Typography Discipline", _typography_discipline(), True),
                _Section("Accessibility Contract", _accessibility_contract(), True),
            ]
        )
        extended_contract_sections.extend(
            [
                _Section("State Completeness", _state_completeness_contract(), True),
                _Section("Performance Discipline", _performance_discipline(), True),
                _Section("Microcopy Contract", _microcopy_contract(), True),
            ]
        )
    token_starter_sections: list[_Section] = []
    component_library_sections: list[_Section] = []
    optional_pattern_sections: list[_Section] = []
    starter_body = _design_tokens_starter(resolution, mode=mode)
    if starter_body:
        token_starter_sections.append(_Section("Design Tokens Starter", starter_body, True))
    library_body = _reusable_component_library(resolution, mode=mode)
    if library_body:
        component_library_sections.append(_Section("Reusable Component Library", library_body, True))
    optional_pattern_body = _optional_pattern_shelf(resolution, mode=mode)
    if optional_pattern_body:
        optional_pattern_sections.append(_Section("Optional Pattern Shelf", optional_pattern_body, True))
    vertical_guardrails = _vertical_guardrails(resolution, rules)
    composition_sections: list[_Section] = []
    donor_sections: list[_Section] = []
    failure_sections: list[_Section] = []
    composition = _composition_brief(resolution, rules)
    artifacts = _visual_artifact_specs(resolution, rules)
    if composition:
        composition_sections.append(_Section("Composition Brief", composition, True))
    if artifacts:
        composition_sections.append(_Section("Visual Artifact Specs", artifacts, True))
    donor_warning = _donor_starvation_warning(resolution)
    mechanical_donors = _mechanical_donors(resolution)
    if donor_warning:
        donor_sections.append(_Section("Donor Starvation Warning", donor_warning, True))
    if mechanical_donors:
        donor_sections.append(_Section("Mechanical Donors (UX Role Only)", mechanical_donors, True))
    failures = _local_model_failure_patterns(resolution, rules)
    if failures:
        failure_sections.append(_Section("Local Model Failure Patterns", failures, True))

    # The selected anchor implementation is always complete.
    full_build_sections: list[_Section] = []
    full_build_body = _full_anchor_build(resolution)
    if full_build_body:
        full_build_sections.append(_Section("Full Anchor Build (translate under Anti-Copy — never ship its brand)", full_build_body, True))

    intent = _active_packet_intent(request)
    if intent == "implementation_blueprint":
        sections = [
            _Section("Selected Route", _selected_route(resolution), True),
            _Section("Anchor Grammar", _anchor_grammar(resolution.anchor_pack), True),
            *full_build_sections,
            *optional_pattern_sections,
            *core_contract_sections,
            _Section("Section Plan", _section_plan(resolution, rules), True),
            _Section("Implementation Contract", _implementation_contract(request, resolution), True),
            *composition_sections,
            *failure_sections,
            *token_starter_sections,
            *component_library_sections,
            _Section("Minimal Code Patterns", _code_patterns(resolution, mode=mode, rules=rules), True),
            _Section("Source Inventory", _source_inventory(resolution), False),
            _Section("Support Donor Roles", _support_roles(resolution, rules), True),
            *donor_sections,
            _Section("Anti-Copy Contract", _anti_copy(resolution), True),
            *strict_quality_sections,
            *([_Section("Vertical Guardrails", vertical_guardrails, True)] if vertical_guardrails else []),
            _Section("Route Diagnostics", _route_diagnostics(resolution), False),
            _Section("Visual References", _visual_references(resolution), False),
            *extended_contract_sections,
            _Section("Omitted Files", omit_text, True),
        ]
    elif intent == "code_first":
        sections = [
            _Section("Selected Route", _selected_route(resolution), True),
            _Section("Source Inventory", _source_inventory(resolution), True),
            _Section("Anchor Grammar", _anchor_grammar(resolution.anchor_pack), True),
            *full_build_sections,
            *optional_pattern_sections,
            # CORE design-system contract — placed immediately after Anchor Grammar
            # and before the code sections so it can never be truncated away.
            *core_contract_sections,
            # Keystone token starter code (protected like a contract section).
            *token_starter_sections,
            # Primary deliverable: real, copy-adaptable component code.
            *component_library_sections,
            _Section("Minimal Code Patterns", _code_patterns(resolution, mode=mode, rules=rules), True),
            _Section("Route Diagnostics", _route_diagnostics(resolution), False),
            *composition_sections,
            *failure_sections,
            _Section("Support Donor Roles", _support_roles(resolution, rules), True),
            *donor_sections,
            _Section("Implementation Contract", _implementation_contract(request, resolution), True),
            _Section("Anti-Copy Contract", _anti_copy(resolution), True),
            *strict_quality_sections,
            *([_Section("Vertical Guardrails", vertical_guardrails, True)] if vertical_guardrails else []),
            _Section("Section Plan", _section_plan(resolution, rules), True),
            _Section("Visual References", _visual_references(resolution), False),
            *extended_contract_sections,
            _Section("Omitted Files", omit_text, True),
        ]
    else:
        sections = [
            _Section("Selected Route", _selected_route(resolution), True),
            _Section("Anchor Grammar", _anchor_grammar(resolution.anchor_pack), True),
            *full_build_sections,
            *optional_pattern_sections,
            # CORE design-system contract — placed immediately after Anchor Grammar
            # and before the code sections so it can never be truncated away.
            *core_contract_sections,
            # Keystone token starter code (protected like a contract section).
            *token_starter_sections,
            # Primary deliverable: real, copy-adaptable component code.
            *component_library_sections,
            _Section("Minimal Code Patterns", _code_patterns(resolution, mode=mode, rules=rules), True),
            _Section("Source Inventory", _source_inventory(resolution), False),
            _Section("Visual References", _visual_references(resolution), True),
            *composition_sections,
            *failure_sections,
            _Section("Anti-Copy Contract", _anti_copy(resolution), True),
            *strict_quality_sections,
            *extended_contract_sections,
            *([_Section("Vertical Guardrails", vertical_guardrails, True)] if vertical_guardrails else []),
            _Section("Support Donor Roles", _support_roles(resolution, rules), False),
            *donor_sections,
            _Section("Implementation Contract", _implementation_contract(request, resolution), True),
            _Section("Section Plan", _section_plan(resolution, rules), True),
            _Section("Omitted Files", omit_text, True),
        ]
    return sections


def _assemble(header: str, sections: list[_Section]) -> str:
    return "\n\n".join([header, *(s.render() for s in sections)]).strip()


def _finalize(sections: list[_Section], *, request: DesignContextRequest, resolution: RouteResolution, mode: str, rules: RoutingRules) -> RenderedPacket:
    header = _packet_header(request, resolution, mode=mode, rules=rules)
    code_density = _code_density_metrics(resolution)
    markdown = _assemble(header, sections)
    omitted_text, omitted_files = _omissions(resolution, mode=mode, rules=rules)
    selected_files = [resolution.anchor_pack.manifest.pack_id]
    if resolution.hero_reference_pack is not None:
        selected_files.append(resolution.hero_reference_pack.manifest.pack_id)
    if resolution.support_bank is not None and resolution.selected_examples:
        selected_files.append(resolution.support_bank.manifest.pack_id)
        selected_files.extend(resolution.selected_example_ids)
    for pattern in resolution.optional_patterns:
        if pattern.source_kind == "support_example":
            selected_files.append(pattern.pack_id)
        if pattern.source_kind == "support_example" and pattern.example_id:
            selected_files.append(f"{pattern.pack_id}::{pattern.example_id}")
    selected_files = list(dict.fromkeys(selected_files))
    code_density = {**code_density, "estimated_tokens": estimate_tokens(markdown)}
    recipe = _composition_recipe(resolution, rules)
    artifact_vocabularies = sorted({str(item.get("vocabulary")) for item in recipe.get("artifact_briefs", []) if item.get("vocabulary")})
    return RenderedPacket(
        markdown=markdown,
        estimated_tokens=estimate_tokens(markdown),
        token_mode=mode,  # type: ignore[arg-type]
        selected_files=selected_files,
        omitted_files=omitted_files,
        metadata={
            "capacity_policy": "unbounded",
            "estimated_tokens_are_telemetry_only": True,
            "rules_version": rules.version,
            "route_trace_id": resolution.route_meta.get("trace_id"),
            "route_profile": request.route_profile,
            "rerank_mode": request.rerank_mode,
            "omitted_summary": omitted_text,
            "visual_quality_profile": request.visual_quality_profile,
            "code_profile": request.code_profile,
            "packet_intent": _active_packet_intent(request),
            "code_density": code_density,
            "donor_starvation": resolution.route_meta.get("donor_starvation", {}),
            "source_selection": resolution.route_meta.get("source_selection", {}),
            "composition_brief_count": 1 if recipe else 0,
            "artifact_vocabularies_named": artifact_vocabularies,
            "vertical": resolution.normalized_request.specialty_service_class or "none (unrouted)",
            "surface_kind": resolution.normalized_request.surface_kind,
            "task_archetype": resolution.normalized_request.task_archetype,
            "route_confidence": resolution.route_meta.get("route_confidence", {}),
            "candidate_gate": resolution.route_meta.get("candidate_gate", {}),
            "anchor_score": resolution.anchor_score.model_dump(mode="json"),
            "support_bank_score": resolution.support_bank_score.model_dump(mode="json") if resolution.support_bank_score else None,
            "optional_pattern_pool": resolution.route_meta.get("optional_pattern_pool", {}),
            "optional_patterns": [
                optional_pattern_metadata(pattern)
                for pattern in resolution.optional_patterns
            ],
            "optional_pattern_catalog": [
                entry.model_dump(mode="json")
                for entry in resolution.optional_pattern_catalog
            ],
        },
    )


def build_context_packet(
    request: DesignContextRequest,
    resolution: RouteResolution,
    *,
    token_mode: TokenMode | str | None = None,
    rules: RoutingRules | None = None,
) -> RenderedPacket:
    rules = rules or load_routing_rules()
    mode = rules.resolve_token_mode(token_mode or request.token_mode, request.local_model_profile)
    sections = _pack_sections(request, resolution, mode=mode, rules=rules)
    return _finalize(sections, request=request, resolution=resolution, mode=mode, rules=rules)
