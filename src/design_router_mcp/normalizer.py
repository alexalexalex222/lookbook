from __future__ import annotations

import re
from typing import Iterable

from .rules import RoutingRules, load_routing_rules
from .schemas import DesignContextRequest, NormalizedRequest

TOKEN_RE = re.compile(r"[a-z0-9]+")
INLINE_NEGATIVE_RE = re.compile(r"(?:do not|don't|avoid|without|not|no)\s+([^.;\n]+)", re.IGNORECASE)


def tokenize(parts: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        if part is None:
            continue
        tokens.update(TOKEN_RE.findall(str(part).lower()))
    return tokens


def extract_inline_negative_tokens(parts: Iterable[str]) -> set[str]:
    negative_tokens: set[str] = set()
    for part in parts:
        lower = str(part).lower()
        for match in INLINE_NEGATIVE_RE.finditer(lower):
            negative_tokens.update(TOKEN_RE.findall(match.group(1)))
    return negative_tokens


def request_tokens(request: DesignContextRequest, *, include_negative: bool = False) -> set[str]:
    positive = tokenize([request.surface, request.task, request.layout_mode, request.stack, *request.tone, *request.constraints])
    if include_negative:
        return positive
    return positive.difference(negative_tokens(request))


def negative_tokens(request: DesignContextRequest) -> set[str]:
    tokens = tokenize(request.anti_patterns)
    tokens.update(extract_inline_negative_tokens([request.task, *request.constraints]))
    return tokens


def _tags_from_keyword_map(tokens: set[str], keyword_map: dict[str, list[str]]) -> list[str]:
    matched: list[str] = []
    for tag, keywords in keyword_map.items():
        if any(keyword.lower() in tokens for keyword in keywords):
            matched.append(tag)
    return matched


def detect_vertical(tokens: set[str], rules: RoutingRules, source_text: str = "") -> str | None:
    phrase_text = " " + " ".join(TOKEN_RE.findall(source_text.lower())) + " "
    scored: list[tuple[int, int, str]] = []
    for name, vertical in rules.verticals.items():
        matches: set[str] = set()
        for keyword in vertical.all_keywords:
            parts = TOKEN_RE.findall(keyword)
            if not parts:
                continue
            if len(parts) == 1 and parts[0] in tokens:
                matches.add(keyword)
            elif len(parts) > 1 and f" {' '.join(parts)} " in phrase_text:
                matches.add(keyword)
        if matches:
            scored.append((-len(matches), vertical.priority, name))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def _preference_flags(tokens: set[str], rules: RoutingRules) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for pref, keywords in rules.preference_keywords.items():
        flags[pref] = bool(tokens.intersection({keyword.lower() for keyword in keywords}))
    return flags


def _collect_avoided_tags(tokens: set[str], rules: RoutingRules) -> tuple[set[str], set[str]]:
    avoided_motifs: set[str] = set()
    avoided_strengths: set[str] = set()
    for token, exclusion in rules.negative_style_exclusions.items():
        if token.lower() in tokens:
            avoided_motifs.update(exclusion.motif)
            avoided_strengths.update(exclusion.strength)
    return avoided_motifs, avoided_strengths


def _dedupe_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def normalize_request(request: DesignContextRequest, rules: RoutingRules | None = None) -> NormalizedRequest:
    rules = rules or load_routing_rules()
    source_text = " ".join([request.surface, request.task, request.layout_mode, request.stack, *request.tone, *request.constraints])
    positive = request_tokens(request, include_negative=True)
    negatives = negative_tokens(request)
    effective = positive.difference(negatives)

    motifs: list[str] = _tags_from_keyword_map(positive, rules.motif_keywords)
    strengths: list[str] = _tags_from_keyword_map(positive, rules.strength_keywords)

    vertical_name = None if request.route_profile == "legacy_exploration" else detect_vertical(effective, rules, source_text)
    vertical = rules.verticals.get(vertical_name) if vertical_name else None
    if vertical is not None:
        motifs.extend(vertical.motif_tags)
        strengths.extend(vertical.strength_tags)

    preferences = _preference_flags(effective, rules)
    for pref, enabled in preferences.items():
        if not enabled:
            continue
        expansion = rules.preference_tag_expansions.get(pref)
        if expansion is None:
            continue
        motifs.extend(expansion.motif)
        strengths.extend(expansion.strength)

    if request.surface == "website.homepage_hero":
        motifs.append("hero_shell")
    if request.surface.startswith("website"):
        strengths.append("hero_treatment")
    elif request.surface.startswith("app.") or request.layout_mode == "dashboard":
        motifs.extend(["command_surface", "glass_panel", "dashboard_panel"])
        strengths.extend(["navigation_clarity", "section_sequencing"])
        if vertical_name is None:
            vertical_name = "saas_dashboard"
            vertical = rules.verticals.get(vertical_name)
            if vertical is not None:
                motifs.extend(vertical.motif_tags)
                strengths.extend(vertical.strength_tags)
    if "hero_shell" in motifs:
        strengths.append("headline_hierarchy")

    avoided_motifs, avoided_strengths = _collect_avoided_tags(negatives, rules)
    motifs = [tag for tag in motifs if tag not in avoided_motifs]
    strengths = [tag for tag in strengths if tag not in avoided_strengths]

    requires_screenshot_fit = bool(
        {"screenshot", "viewport", "fold", "1512x812", "390x844", "pixel", "fit"}.intersection(effective)
        or any("1512x812" in c or "390x844" in c for c in request.constraints)
    )

    dark_vertical = None
    if effective.intersection({"grading", "excavation", "earthworks", "earthwork", "sitework", "dirt"}):
        dark_vertical = "grading"
    elif effective.intersection({"roofing", "roofer", "roof", "shingle", "shingles"}):
        dark_vertical = "roofing"

    avoids_dark = "dark" in negatives
    # Dark industrial preference so null-vertical ties do not elect light beauty packs by budget.
    prefers_dark = (not avoids_dark) and bool(
        effective.intersection({"dark", "industrial", "garage", "showroom"})
        or any(t.lower() in {"dark", "industrial", "garage", "showroom"} for t in request.tone)
    )

    return NormalizedRequest(
        surface=request.surface,
        motif_tags=_dedupe_sorted(motifs),
        strength_tags=_dedupe_sorted(strengths),
        avoided_motif_tags=sorted(avoided_motifs),
        avoided_strength_tags=sorted(avoided_strengths),
        tone=list(request.tone),
        layout_mode=request.layout_mode,
        stack=request.stack,
        requires_screenshot_fit=requires_screenshot_fit,
        prefers_light_mode=preferences.get("light", False),
        prefers_warm_mode=preferences.get("warm", False),
        prefers_residential_mode=preferences.get("residential", False),
        prefers_editorial_mode=preferences.get("editorial", False),
        prefers_dark_mode=prefers_dark,
        avoids_dark_mode=avoids_dark,
        avoids_industrial_mode=bool({"industrial", "heavy", "equipment"}.intersection(negatives)),
        prefers_real_imagery=preferences.get("real_imagery", False),
        specialty_service_class=vertical_name,
        dark_service_vertical=dark_vertical,
    )
