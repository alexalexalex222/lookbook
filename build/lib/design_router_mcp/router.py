from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atom_selector import select_shared_atoms
from .index_store import PackIndexRecord, RepositoryIndex, build_repository_index
from .lazy_loader import PackStore, load_shared_atoms
from .normalizer import normalize_request, request_tokens
from .rules import RoutingRules, load_routing_rules
from .schemas import (
    AtomSnippet,
    DesignContextRequest,
    ExampleSelection,
    LoadedPack,
    PackManifest,
    RouteResolution,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ScoredRecord:
    record: PackIndexRecord
    score: ScoreBreakdown


def _tokens_from_text(value: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _manifest_tokens(manifest: PackManifest) -> set[str]:
    parts: list[str] = [
        manifest.pack_id,
        manifest.family,
        *manifest.stack,
        *manifest.tones,
        *manifest.surfaces,
        *manifest.motif_tags,
        *manifest.supports_tasks,
        *manifest.origin_example_ids,
    ]
    return _tokens_from_text(" ".join(parts).replace("_", " ").replace("-", " "))


class DesignRouter:
    """Data-driven anchor/support router.

    The router can be constructed from either a RepositoryIndex (preferred) or
    the original LoadedPack list (compatibility). Routing uses only manifest
    metadata until the final selected packs/examples are hydrated by PackStore.
    """

    def __init__(
        self,
        packs_or_index: list[LoadedPack] | RepositoryIndex,
        shared_atoms: list[AtomSnippet] | None = None,
        *,
        repo_root: Path | str | None = None,
        rules: RoutingRules | None = None,
        store: PackStore | None = None,
    ) -> None:
        self.rules = rules or load_routing_rules(Path(repo_root).expanduser().resolve() if repo_root else None)
        self.shared_atoms = shared_atoms or []
        if isinstance(packs_or_index, RepositoryIndex):
            self.index = packs_or_index
            self.repo_root = self.index.repo_root
            self._legacy_packs: dict[str, LoadedPack] = {}
        else:
            root = Path(repo_root).expanduser().resolve() if repo_root else self._infer_repo_root(packs_or_index)
            records = []
            self._legacy_packs = {pack.manifest.pack_id: pack for pack in packs_or_index}
            for pack in packs_or_index:
                manifest_path = pack.pack_dir / "manifest.json"
                mtime = manifest_path.stat().st_mtime_ns if manifest_path.exists() else 0
                records.append(PackIndexRecord(pack.manifest, pack.pack_dir, manifest_path, mtime))
            self.index = RepositoryIndex(root, records)
            self.repo_root = root
        self.store = store or PackStore(self.repo_root, self.index)
        if not self.shared_atoms:
            self.shared_atoms = load_shared_atoms(self.repo_root)

    @classmethod
    def from_repo(cls, repo_root: Path | str, *, refresh_index: bool = False, rules_path: Path | str | None = None) -> "DesignRouter":
        root = Path(repo_root).expanduser().resolve()
        rules = load_routing_rules(root, rules_path)
        index = build_repository_index(root, refresh=refresh_index)
        store = PackStore(root, index)
        return cls(index, load_shared_atoms(root), repo_root=root, rules=rules, store=store)

    @staticmethod
    def _infer_repo_root(packs: list[LoadedPack]) -> Path:
        if not packs:
            return Path.cwd()
        pack_dir = packs[0].pack_dir.resolve()
        parts = list(pack_dir.parts)
        if "goldensets" in parts:
            idx = parts.index("goldensets")
            return Path(*parts[:idx]) if idx else Path("/")
        return pack_dir.parent

    @property
    def packs(self) -> list[LoadedPack]:
        if self._legacy_packs:
            return list(self._legacy_packs.values())
        return [self.store.get_pack(record.manifest.pack_id, include_full=False, max_code_chars=1600) for record in self.index.records]

    def _score_record(self, request: DesignContextRequest, normalized, record: PackIndexRecord) -> ScoreBreakdown:
        manifest = record.manifest
        weights = self.rules.weights
        manifest_tokens = _manifest_tokens(manifest)
        tokens = request_tokens(request)
        vertical_name = normalized.specialty_service_class
        vertical = self.rules.verticals.get(vertical_name) if vertical_name else None

        surface = 0
        if request.surface == manifest.family:
            surface = weights.get("surface_exact", 30)
        elif request.surface.startswith("website") and manifest.family.startswith("website"):
            surface = weights.get("surface_family", 14)

        motif_overlap = sorted(set(normalized.motif_tags).intersection(manifest.motif_tags))
        motif = min(24, len(motif_overlap) * weights.get("motif", 4))

        strength_overlap = sorted(set(normalized.strength_tags).intersection(set(manifest.motif_tags + manifest.supports_tasks + manifest.tones)))
        strength_bonus = min(12, len(strength_overlap) * weights.get("strength", 3))
        motif += strength_bonus

        stack = weights.get("stack", 10) if request.stack == "unknown" or request.stack in manifest.stack else 0
        tone_overlap = sorted(set(request.tone).intersection(manifest.tones))
        tone = min(18, len(tone_overlap) * weights.get("tone", 5))
        layout = weights.get("layout", 10) if request.layout_mode in manifest.surfaces else 0
        screenshot_fit = weights.get("screenshot_fit", 10) if normalized.requires_screenshot_fit and manifest.screenshot_paths else 0
        confidence = manifest.confidence_score * weights.get("confidence", 1)

        request_bias = 0
        vertical_matches: list[str] = []
        if vertical is not None:
            vertical_matches = sorted(manifest_tokens.intersection(vertical.all_keywords))
            request_bias += min(15, len(vertical_matches) * weights.get("vertical_pack_token", 3))
            request_bias += sum(weights.get("vertical_tone", 2) for tone_name in vertical.prefer_tones if tone_name in manifest.tones)
            request_bias += vertical.preferred_anchor_pack_ids.get(manifest.pack_id, 0)
            request_bias += vertical.penalized_anchor_pack_ids.get(manifest.pack_id, 0)

        if normalized.prefers_light_mode and ("light" in manifest.tones or "light_precision" in manifest.motif_tags):
            request_bias += 5
        if normalized.prefers_warm_mode and ("warm" in manifest.tones or "craftsmanship" in manifest.tones):
            request_bias += 5
        if normalized.prefers_residential_mode and "residential" in manifest.tones:
            request_bias += 5
        if normalized.prefers_editorial_mode and "editorial" in manifest.tones:
            request_bias += 5
        if normalized.prefers_dark_mode:
            if "dark" in manifest.tones or "dark_texture" in manifest.motif_tags:
                request_bias += 5
            if "light" in manifest.tones and "beauty" in manifest.tones:
                request_bias -= 12
            if manifest.pack_id in {"velvet_fig_beauty_editorial_v1", "aurelia_medspa_editorial_v1"}:
                request_bias -= 12
        if normalized.avoids_dark_mode and ("dark" in manifest.tones or "dark_texture" in manifest.motif_tags):
            request_bias -= 12
        if normalized.avoids_industrial_mode and ("industrial" in manifest.tones or "industrial_frame" in manifest.motif_tags):
            request_bias -= 12

        dashboard_request = request.surface.startswith("app.") or normalized.layout_mode == "dashboard"
        if dashboard_request:
            dashboard_motifs = {"command_surface", "glass_panel", "dashboard_panel", "tabs_panel"}
            if dashboard_motifs.intersection(manifest.motif_tags):
                request_bias += 20
            if manifest.pack_id in {
                "emberforge_fight_gym_black_red_v1",
                "iron_circuit_fight_academy_black_copper_v1",
            }:
                request_bias -= 45
            if "hero_shell" in manifest.motif_tags and not dashboard_motifs.intersection(manifest.motif_tags):
                request_bias -= 15

        direct_pack_overlap = sorted(tokens.intersection(manifest_tokens).difference({"website", "local", "service", "homepage", "landing"}))
        request_bias += min(9, len(direct_pack_overlap) * 3)

        total = surface + motif + stack + tone + layout + screenshot_fit + request_bias + confidence
        return ScoreBreakdown(
            pack_id=manifest.pack_id,
            role=manifest.role,
            total=int(total),
            surface=int(surface),
            motif=int(motif),
            stack=int(stack),
            tone=int(tone),
            layout=int(layout),
            screenshot_fit=int(screenshot_fit),
            request_bias=int(request_bias),
            confidence=int(confidence),
            matched_terms={
                "motif": motif_overlap,
                "strength": strength_overlap,
                "tone": tone_overlap,
                "vertical": vertical_matches,
                "request_pack_tokens": direct_pack_overlap,
            },
        )

    def _pick_anchor(self, request: DesignContextRequest, normalized) -> _ScoredRecord:
        return self._rank_anchors(request, normalized)[0]

    def _rank_anchors(self, request: DesignContextRequest, normalized) -> list[_ScoredRecord]:
        candidates = [_ScoredRecord(record, self._score_record(request, normalized, record)) for record in self.index.anchors]
        if not candidates:
            raise ValueError("No anchor packs are available. Expected at least one goldensets/**/manifest.json with role='anchor'.")
        candidates.sort(key=lambda item: (-item.score.total, item.record.manifest.token_budget_hint, item.record.manifest.pack_id))
        return candidates

    def _effective_donor_first(self, request: DesignContextRequest, normalized) -> bool:
        if request.donor_selection_mode == "site_donor_first_v1":
            return True
        if request.donor_selection_mode != "auto_lane_promotion_v1":
            return False
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        return bool(vertical and vertical.auto_donor_first)

    def _pick_hero_reference_record(self, anchor: _ScoredRecord, normalized) -> PackIndexRecord | None:
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        if vertical is None:
            return None
        for pack_id in vertical.hero_reference_pack_ids:
            if pack_id == anchor.record.manifest.pack_id:
                continue
            record = self.index.by_id.get(pack_id)
            if record is not None and record.manifest.role == "anchor":
                return record
        return None

    def _pick_support_bank(self, request: DesignContextRequest, normalized) -> _ScoredRecord | None:
        banks = self.index.support_banks
        if not banks:
            return None
        donor_first = self._effective_donor_first(request, normalized)
        if donor_first:
            preferred = [b for b in banks if b.manifest.pack_id in self.rules.donor_first_support_bank_ids]
            if preferred:
                banks = preferred
        elif len(banks) > 1:
            banks = [b for b in banks if b.manifest.pack_id not in self.rules.donor_first_support_bank_ids] or banks
        scored = [_ScoredRecord(record, self._score_record(request, normalized, record)) for record in banks]
        scored.sort(key=lambda item: (-item.score.total, item.record.manifest.pack_id))
        return scored[0]

    def _support_example_limit(self, request: DesignContextRequest, normalized, support: PackIndexRecord | None, hero: PackIndexRecord | None) -> int:
        if support is None:
            return 0
        if self._effective_donor_first(request, normalized):
            used = 1 + (1 if hero is not None else 0)
            return max(0, min(len(support.manifest.example_ids), request.donor_count - used))
        budget = self.rules.token_budget(request.token_mode)
        if request.include_full_library:
            return len(support.manifest.example_ids)
        return max(0, min(len(support.manifest.example_ids), request.max_examples - 1, budget.max_examples))

    def _infer_request_ux_roles(self, request: DesignContextRequest, normalized) -> set[str]:
        text = " ".join(
            [
                request.surface,
                request.task,
                request.layout_mode,
                request.stack,
                *request.constraints,
                *request.anti_patterns,
                *request.tone,
                *normalized.motif_tags,
                *normalized.strength_tags,
            ]
        ).lower()
        roles: set[str] = set()
        if any(token in text for token in ("trial", "assessment", "intake", "consultation", "form", "request", "application", "apply")):
            roles.add("form_intake")
        if any(token in text for token in ("schedule", "weekly", "rhythm", "calendar", "class times", "classes")):
            roles.add("schedule_grid")
        if any(token in text for token in ("proof", "results", "before", "after", "case", "evidence", "grounded")):
            roles.add("proof_rail")
        if any(token in text for token in ("process", "method", "sequence", "steps", "progression", "path")):
            roles.add("process_steps")
        if any(token in text for token in ("service area", "coverage", "near you", "local", "territory")):
            roles.add("coverage_signal")
        if "phone" in text or "call" in text:
            roles.add("phone_priority_layout")
        if any(token in text for token in ("testimonial", "trusted", "review", "trust", "credible")):
            roles.add("trust_rail")
        if "stats" in text or "metrics" in text:
            roles.add("stats_strip")
        if "footer" in text or "contact" in text:
            roles.add("footer_full")
        return roles

    def _atom_tag_terms(self, request: DesignContextRequest, normalized) -> set[str]:
        """Free-form terms matched against atom tags/category for relevance.

        Includes the request task tokens, declared/normalized tone, and the
        normalized motif/strength tags so a contact/intake request surfaces a form
        atom, a pricing request surfaces pricing, etc. Deterministic (set of tokens).
        """
        terms: set[str] = set()
        terms.update(_tokens_from_text(request.task))
        terms.update(t.lower() for t in request.tone)
        terms.update(t.lower() for t in normalized.tone)
        for tag in [*normalized.motif_tags, *normalized.strength_tags]:
            for piece in tag.lower().replace("-", " ").replace("_", " ").split():
                terms.add(piece)
        return terms

    def _select_shared_atoms(self, request: DesignContextRequest, normalized, *, mode: str) -> list[AtomSnippet]:
        request_roles = self._infer_request_ux_roles(request, normalized)
        tone = {*(t.lower() for t in request.tone), *(t.lower() for t in normalized.tone)}
        return select_shared_atoms(
            self.shared_atoms,
            mode=mode,
            surface=request.surface,
            request_roles=request_roles,
            tone=tone,
            tag_terms=self._atom_tag_terms(request, normalized),
        )

    @staticmethod
    def _starvation_meta(reason: str = "") -> dict[str, Any]:
        return {
            "native_count": 0,
            "mechanical_donor_count": 0,
            "mechanical_donors": [],
            "request_ux_roles": [],
            "dropped_for": {"blocked_tokens": 0, "preferred_required": 0, "conflict": 0, "ux_role_miss": 0},
            "reason": reason,
        }

    def _pick_support_examples(
        self,
        request: DesignContextRequest,
        normalized,
        anchor_record: PackIndexRecord,
        hero_record: PackIndexRecord | None,
        support_record: PackIndexRecord | None,
    ) -> tuple[list[ExampleSelection], dict[str, Any]]:
        starvation_meta = self._starvation_meta("not evaluated")
        if support_record is None:
            starvation_meta["reason"] = "no support bank selected"
            return [], starvation_meta
        limit = self._support_example_limit(request, normalized, support_record, hero_record)
        if limit <= 0:
            starvation_meta["reason"] = "support example limit is zero"
            return [], starvation_meta

        manifest = support_record.manifest
        blocked_ids = set(anchor_record.manifest.origin_example_ids)
        if hero_record is not None:
            blocked_ids.update(hero_record.manifest.origin_example_ids)
        tokens = request_tokens(request)
        stop_tokens = set(self.rules.generic_example_stop_tokens)
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        prefer_tokens = set(vertical.prefer_example_tokens) if vertical else set()
        blocked_tokens = set(vertical.blocked_example_tokens) if vertical else set()
        weights = self.rules.weights

        selections: list[ExampleSelection] = []
        for example_id in manifest.example_ids:
            if example_id in blocked_ids:
                starvation_meta["dropped_for"]["conflict"] += 1
                continue
            example_tokens = _tokens_from_text(example_id.replace("-", " ").replace("_", " "))
            if blocked_tokens and example_tokens.intersection(blocked_tokens) and not example_tokens.intersection(prefer_tokens):
                starvation_meta["dropped_for"]["blocked_tokens"] += 1
                continue
            strengths = set(manifest.example_strengths.get(example_id, []))
            motifs = set(manifest.motif_overlaps.get(example_id, []))
            strength_overlap = sorted(strengths.intersection(normalized.strength_tags))
            motif_overlap = sorted(motifs.intersection(normalized.motif_tags))
            conflicting_strengths = sorted(strengths.intersection(normalized.avoided_strength_tags))
            conflicting_motifs = sorted(motifs.intersection(normalized.avoided_motif_tags))
            request_overlap = sorted(tokens.intersection(example_tokens).difference(stop_tokens))
            preferred_overlap = sorted(prefer_tokens.intersection(example_tokens))
            if normalized.specialty_service_class == "combat_sports" and not preferred_overlap:
                starvation_meta["dropped_for"]["preferred_required"] += 1
                continue

            score = 0
            score += len(strength_overlap) * weights.get("strength", 3)
            score += len(motif_overlap) * weights.get("motif", 4)
            score += min(12, len(request_overlap) * weights.get("request_token_example", 3))
            score += len(preferred_overlap) * weights.get("preferred_example_token", 12)
            score -= len(conflicting_strengths) * weights.get("conflict_strength", 4)
            score -= len(conflicting_motifs) * weights.get("conflict_motif", 3)
            if request.layout_mode in {"homepage", "landing"} and "section_sequencing" in strengths:
                score += 4
            if normalized.prefers_light_mode and ("light_clarity" in strengths or "light_precision" in motifs):
                score += 4
            if normalized.prefers_warm_mode and {"premium_spacing", "visual_restraint"}.intersection(strengths):
                score += 4
            if normalized.avoids_dark_mode and {"dark_contrast", "industrial_tone"}.intersection(strengths):
                score -= 8
            if score <= 0 and not request.include_full_library:
                starvation_meta["dropped_for"]["conflict"] += 1
                continue
            selections.append(
                ExampleSelection(
                    example_id=example_id,
                    score=int(score),
                    strength_overlap=strength_overlap,
                    motif_overlap=motif_overlap,
                    conflicting_strength_tags=conflicting_strengths,
                    conflicting_motif_tags=conflicting_motifs,
                    matched_tokens=sorted(set(request_overlap + preferred_overlap)),
                )
            )
        selections.sort(
            key=lambda item: (
                len(item.conflicting_strength_tags) + len(item.conflicting_motif_tags),
                -item.score,
                item.example_id,
            )
        )
        native = selections[:limit]
        if native:
            starvation_meta["native_count"] = len(native)
            starvation_meta["reason"] = "native support selected"
            return native, starvation_meta

        fallback_roles = set(vertical.ux_role_fallback) if vertical else set()
        if not fallback_roles:
            starvation_meta["reason"] = "no ux_role_fallback configured"
            return [], starvation_meta
        request_roles = sorted(self._infer_request_ux_roles(request, normalized).intersection(fallback_roles))
        starvation_meta["request_ux_roles"] = request_roles
        if not request_roles:
            starvation_meta["reason"] = "no inferable ux_roles"
            return [], starvation_meta

        mechanical: list[ExampleSelection] = []
        blocked_mechanical: list[ExampleSelection] = []
        for example_id in manifest.example_ids:
            if example_id in blocked_ids:
                continue
            example_tokens = _tokens_from_text(example_id.replace("-", " ").replace("_", " "))
            blocked_by_vertical = bool(blocked_tokens and example_tokens.intersection(blocked_tokens) and not example_tokens.intersection(prefer_tokens))
            ux_roles = set(manifest.example_ux_roles.get(example_id, [])).intersection(fallback_roles)
            overlap = sorted(ux_roles.intersection(request_roles))
            if not overlap:
                starvation_meta["dropped_for"]["ux_role_miss"] += 1
                continue
            selection = ExampleSelection(
                example_id=example_id,
                score=int(len(overlap) * weights.get("ux_role_overlap", 5)),
                strength_overlap=[],
                motif_overlap=[],
                matched_tokens=overlap,
                ux_role_match=overlap,
            )
            if blocked_by_vertical:
                blocked_mechanical.append(selection)
            else:
                mechanical.append(selection)
        mechanical.sort(key=lambda item: (-item.score, item.example_id))
        blocked_mechanical.sort(key=lambda item: (-item.score, item.example_id))
        if not mechanical:
            mechanical = blocked_mechanical
        mechanical_limit = min(limit, max(1, request.donor_count - 1))
        mechanical = mechanical[:mechanical_limit]
        starvation_meta["mechanical_donor_count"] = len(mechanical)
        starvation_meta["mechanical_donors"] = [item.example_id for item in mechanical]
        starvation_meta["reason"] = "native donor starvation; selected mechanical donors by ux_role" if mechanical else "no mechanical donors matched request ux_roles"
        return mechanical, starvation_meta

    def route(self, request: DesignContextRequest) -> RouteResolution:
        normalized = normalize_request(request, self.rules)
        ranked_anchors = self._rank_anchors(request, normalized)
        anchor = ranked_anchors[0]
        # Multi-pattern routing: keep the strongest runner-up anchors so the packet
        # can surface alternative pattern sources, not just the single winner.
        anchor_alternatives = [
            {
                "pack_id": item.record.manifest.pack_id,
                "score": item.score.total,
                "family": item.record.manifest.family,
                "motif_tags": list(item.record.manifest.motif_tags[:6]),
                "tones": list(item.record.manifest.tones[:4]),
                "supports_tasks": list(item.record.manifest.supports_tasks[:3]),
            }
            for item in ranked_anchors[1:4]
            if item.score.total > 0
        ]
        if normalized.specialty_service_class is None and (
            request.surface.startswith("website") or "local" in request.surface or request.layout_mode == "homepage"
        ):
            scored = ranked_anchors
            top_total = scored[0].score.total if scored else 0
            tied = [
                f"{item.record.manifest.pack_id}={item.score.total}"
                for item in scored
                if item.score.total == top_total
            ][:8]
            logger.warning(
                "design router unrouted: vertical=None for website/local-service request; "
                "top tied anchors: %s; picked=%s; task_preview=%r",
                ", ".join(tied) if tied else "(none)",
                anchor.record.manifest.pack_id,
                (request.task or "")[:160],
            )
        hero_record = self._pick_hero_reference_record(anchor, normalized)
        support = self._pick_support_bank(request, normalized)
        selected_examples, starvation_meta = self._pick_support_examples(request, normalized, anchor.record, hero_record, support.record if support else None)

        effective_mode = self.rules.resolve_token_mode(request.token_mode, request.local_model_profile)
        budget = self.rules.token_budget(effective_mode)
        include_full = (request.full_code_mode or request.include_full_library) and budget.full_code_allowed
        max_code_chars = 14000 if include_full else (6500 if effective_mode in {"standard", "expanded"} else 4200)
        max_atoms = budget.max_snippets
        selected_shared_atoms = self._select_shared_atoms(request, normalized, mode=effective_mode)

        # Full-build mode: when full code is requested and the mode's budget allows it,
        # carry the COMPLETE anchor source (untruncated) so the builder model sees the
        # real quality bar instead of clipped snippets. Skips stale sibling stylesheets
        # when the primary HTML is already self-contained.
        anchor_full_source: list[dict[str, Any]] = []
        if include_full:
            pack_dir = anchor.record.pack_dir
            paths = list(anchor.record.manifest.source_paths)
            texts: dict[str, str] = {}
            for rel in paths:
                fp = pack_dir / rel
                if fp.is_file():
                    try:
                        texts[rel] = fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
            html_rels = [rel for rel in texts if rel.endswith(".html")]
            primary_html = next((rel for rel in html_rels if rel.endswith("index.html")), html_rels[0] if html_rels else None)
            # self-contained = inline <style> present and no local stylesheet link -> sibling css is stale
            self_contained = False
            if primary_html:
                head = texts[primary_html]
                self_contained = ("<style" in head) and ('rel="stylesheet"' not in head and "rel='stylesheet'" not in head)
            for rel, text in texts.items():
                if self_contained and rel != primary_html:
                    continue
                anchor_full_source.append({"path": rel, "chars": len(text), "text": text})

        anchor_pack = self.store.get_pack(anchor.record.manifest.pack_id, include_full=include_full, max_code_chars=max_code_chars, max_atoms=max_atoms)
        hero_pack = None
        if hero_record is not None:
            hero_pack = self.store.get_pack(hero_record.manifest.pack_id, include_full=include_full, max_code_chars=max_code_chars, max_atoms=max_atoms)
        support_pack = None
        if support is not None:
            support_pack = self.store.get_pack(
                support.record.manifest.pack_id,
                selected_examples=[selection.example_id for selection in selected_examples],
                include_full=include_full,
                max_code_chars=max_code_chars,
                max_atoms=max_atoms,
            )

        return RouteResolution(
            request=request,
            normalized_request=normalized,
            anchor_pack=anchor_pack,
            hero_reference_pack=hero_pack,
            support_bank=support_pack,
            selected_examples=selected_examples,
            auxiliary_anchor_packs=[],
            shared_atoms=selected_shared_atoms,
            anchor_score=anchor.score,
            support_bank_score=support.score if support else None,
            route_meta={
                "rules_version": self.rules.version,
                "vertical": normalized.specialty_service_class,
                "donor_first": self._effective_donor_first(request, normalized),
                "lazy_loaded": True,
                "include_full_code": include_full,
                "donor_starvation": starvation_meta,
                "mechanical_donor_ids": [selection.example_id for selection in selected_examples if selection.ux_role_match],
                "anchor_alternatives": anchor_alternatives,
                "anchor_full_source": anchor_full_source,
            },
        )
