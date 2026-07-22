from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TokenMode = Literal[
    "unbounded",
    "micro",
    "compact",
    "standard",
    "expanded",
    "full_selected",
    "library_audit",
]
LocalModelProfile = Literal["tiny_16k", "balanced_32k", "strong_64k", "moe_128k", "manual"]
DonorSelectionMode = Literal["default", "support_examples_v1", "site_donor_first_v1", "auto_lane_promotion_v1"]
PatternSourceKind = Literal["support_example", "anchor_excerpt"]
PatternDomainFit = Literal["native", "neutral", "adjacent"]
PatternIdentityRisk = Literal["low", "medium", "high"]
PatternCardTier = Literal["S", "M", "L"]
RouteProfile = Literal[
    "hybrid_survivor_v1",
    "legacy_exploration",
    "specialty_hardened",
    "data_driven_v2",
    "hybrid_shadow_v1",
    "hybrid_v4",
    "hybrid_v5",
]
RerankMode = Literal["off", "shadow", "active"]
PacketProfile = Literal["current_source_first_v1", "march12_exploratory", "march15_foldfit", "compact_v2"]
VisualQualityProfile = Literal["strict_design_router_gpt55_mcp_v1", "legacy_relaxed"]
CodeProfile = Literal["balanced", "code_first"]
PacketIntent = Literal["balanced", "code_first", "design_director", "visual_system", "implementation_blueprint"]
UxRole = Literal[
    "form_intake",
    "schedule_grid",
    "proof_rail",
    "service_lane_set",
    "process_steps",
    "coverage_signal",
    "consultation_flow",
    "phone_priority_layout",
    "footer_full",
    "header_sticky",
    "trust_rail",
    "stats_strip",
    "service_area_signal",
    "navigation_shell",
    "filter_toolbar",
    "data_table",
    "modal_flow",
    "hud_cluster",
    "overlay_state",
    "inventory_panel",
    "control_cluster",
    "gameplay_stage",
    "event_log",
    "responsive_control_dock",
]


class DesignContextRequest(BaseModel):
    """Public request schema.

    The original fields are kept for compatibility. The rebuild adds optional
    token_mode/local_model_profile fields so MCP tools do not need a parallel
    ad-hoc budget layer.
    """

    model_config = ConfigDict(extra="ignore")

    surface: str = Field(description="e.g. website.local_service")
    task: str = Field(description="Concrete frontend task description.")
    surface_kind: str | None = Field(
        default=None,
        description="Optional canonical surface class such as app, landing, dashboard, instrument, game, or docs.",
    )
    task_archetype: str | None = Field(
        default=None,
        description="Optional explicit workflow archetype such as settings, kanban, notifications, or file_manager.",
    )
    stack: str = Field(default="unknown")
    tone: list[str] = Field(default_factory=list)
    layout_mode: str = Field(default="homepage")
    constraints: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    desired_density: str = Field(default="balanced")
    max_examples: int = Field(default=3, ge=0)
    donor_selection_mode: DonorSelectionMode = Field(default="support_examples_v1")
    donor_count: int = Field(default=3, ge=1)
    include_optional_patterns: bool = Field(
        default=True,
        description="Include a diversified shelf of optional section-level patterns from compatible golden sets.",
    )
    optional_pattern_count: int = Field(
        default=8,
        ge=0,
        description="Requested optional pattern count. Routing quality gates may return fewer, but token modes never cap it.",
    )
    route_profile: RouteProfile = Field(default="hybrid_v4")
    rerank_mode: RerankMode = Field(
        default="shadow",
        description="V5 local-candidate reranking mode. Ignored by earlier route profiles.",
    )
    rerank_model: str | None = Field(
        default=None,
        description="Optional local Ollama model id for bounded V5 reranking. Endpoint configuration stays server-side.",
    )
    reference_image_paths: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Optional local reference screenshots for V5 pixel-aware retrieval. Paths must stay inside an allowed server-side root.",
    )
    packet_profile: PacketProfile = Field(default="compact_v2")
    include_full_library: bool = Field(default=False)
    pattern_lock: bool = Field(default=False)
    pattern_lock_strict: bool = Field(default=False)
    pattern_lock_exact: bool = Field(default=False)
    full_code_mode: bool = Field(
        default=True,
        description="Backward-compatible flag. Selected source is complete by default; false no longer enables clipping.",
    )
    prefer_angular_geometry: bool = Field(default=True)
    host_browser_review: bool = Field(default=False)
    token_mode: TokenMode = Field(
        default="unbounded",
        description="Packet detail label retained for compatibility. All normal modes use unbounded capacity.",
    )
    local_model_profile: LocalModelProfile | None = Field(default=None)
    visual_quality_profile: VisualQualityProfile = Field(default="strict_design_router_gpt55_mcp_v1")
    code_profile: CodeProfile = Field(
        default="balanced",
        description="Use 'code_first' when local models need more implementation code and less prose before building.",
    )
    packet_intent: PacketIntent = Field(
        default="balanced",
        description="Optional packet ordering/weighting intent. Non-balanced values guide renderer section priority while preserving code_profile compatibility.",
    )


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    pack_id: str
    role: Literal["anchor", "support_bank"]
    family: str
    source_paths: list[str] = Field(default_factory=list)
    origin_example_ids: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    tones: list[str] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)
    motif_tags: list[str] = Field(default_factory=list)
    supports_tasks: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    screenshot_paths: list[str] = Field(default_factory=list)
    token_budget_hint: int = Field(default=1000, gt=0)
    confidence_score: int = Field(default=5, ge=0, le=5)
    example_ids: list[str] = Field(default_factory=list)
    source_dirs: dict[str, str] = Field(default_factory=dict)
    preview_paths: dict[str, str] = Field(default_factory=dict)
    example_strengths: dict[str, list[str]] = Field(default_factory=dict)
    motif_overlaps: dict[str, list[str]] = Field(default_factory=dict)
    example_ux_roles: dict[str, list[UxRole]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_role_specific_fields(self) -> "PackManifest":
        if self.role == "support_bank" and not self.example_ids:
            raise ValueError("support_bank manifests must declare example_ids")
        unknown_role_examples = sorted(set(self.example_ux_roles).difference(self.example_ids))
        if unknown_role_examples:
            raise ValueError(f"example_ux_roles references unknown examples: {', '.join(unknown_role_examples)}")
        return self

    @model_validator(mode="after")
    def validate_source_path_containment(self) -> "PackManifest":
        # Manifest source paths/dirs are read relative to the pack directory. Reject
        # absolute paths or parent-directory traversal so a poisoned manifest cannot
        # escape its pack and read arbitrary files (path-traversal containment).
        def _contained(rel: str) -> bool:
            if not rel:
                return True
            if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute():
                return False
            return ".." not in PurePosixPath(rel).parts

        unsafe = [p for p in self.source_paths if not _contained(p)]
        unsafe += [d for d in self.source_dirs.values() if not _contained(d)]
        if unsafe:
            raise ValueError(f"source paths must stay within the pack directory (no absolute paths or '..'): {unsafe}")
        return self


class CodeFile(BaseModel):
    label: str
    language: str = "text"
    content: str


class AtomSnippet(BaseModel):
    """Reusable component-atom reference.

    The original fields (atom_id/notes/snippet/language) are preserved so existing
    construction stays valid. The rebuild adds optional, backward-compatible fields
    so a single atom can carry ALL of its real code files (html/css/js) plus the
    machine-readable selection metadata loaded from ``meta.json``.
    """

    atom_id: str
    notes: str = ""
    snippet: str | None = None
    language: str = "text"
    # Full set of code files for this atom (html, then css, then js). When present,
    # the renderer surfaces these as the primary copy-adaptable code; `snippet`
    # remains populated with the first file for legacy callers.
    code_blocks: list[CodeFile] = Field(default_factory=list)
    # Selection metadata sourced from meta.json (absent for the 5 legacy atoms).
    category: str = ""
    summary: str = ""
    surfaces: list[str] = Field(default_factory=list)
    ux_roles: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    has_meta: bool = False


class ExampleSummary(BaseModel):
    example_id: str
    summary_markdown: str = ""
    strength_tags: list[str] = Field(default_factory=list)
    motif_tags: list[str] = Field(default_factory=list)
    source_dir: str = ""
    preview_path: str = ""
    html_excerpt: str = ""
    css_excerpt: str = ""
    full_code_files: list[CodeFile] = Field(default_factory=list)
    section_job_excerpts: list[CodeFile] = Field(default_factory=list)


class LoadedPack(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    manifest: PackManifest
    pack_dir: Path
    prompt_markdown: str = ""
    principles_markdown: str = ""
    anti_copy_markdown: str = ""
    atoms: list[AtomSnippet] = Field(default_factory=list)
    example_summaries: dict[str, ExampleSummary] = Field(default_factory=dict)
    anchor_markup_excerpt: str = ""
    anchor_markup_language: str = "text"
    anchor_css_excerpt: str = ""
    anchor_css_language: str = "css"
    anchor_source_files: list[CodeFile] = Field(default_factory=list)


class ArchetypeCandidate(BaseModel):
    name: str
    score: int
    confidence: float
    exact_phrases: list[str] = Field(default_factory=list)
    exact_tokens: list[str] = Field(default_factory=list)
    fuzzy_tokens: list[str] = Field(default_factory=list)


class NormalizedRequest(BaseModel):
    surface: str
    surface_kind: str = "unknown"
    task_archetype: str | None = None
    task_archetype_confidence: float = 0.0
    task_archetype_candidates: list[ArchetypeCandidate] = Field(default_factory=list)
    task_archetype_ambiguous: bool = False
    motif_tags: list[str]
    strength_tags: list[str]
    avoided_motif_tags: list[str]
    avoided_strength_tags: list[str]
    tone: list[str]
    layout_mode: str
    stack: str
    requires_screenshot_fit: bool
    prefers_light_mode: bool
    prefers_warm_mode: bool
    prefers_residential_mode: bool
    prefers_editorial_mode: bool
    prefers_dark_mode: bool = False
    avoids_dark_mode: bool
    avoids_industrial_mode: bool
    prefers_real_imagery: bool
    specialty_service_class: str | None = None
    dark_service_vertical: str | None = None


class ScoreBreakdown(BaseModel):
    pack_id: str
    role: Literal["anchor", "support_bank"]
    total: int
    surface: int = 0
    motif: int = 0
    stack: int = 0
    tone: int = 0
    layout: int = 0
    screenshot_fit: int = 0
    task_fit: int = 0
    signature_fit: int = 0
    retrieval_fit: int = 0
    rerank_fit: int = 0
    family_fit: int = 0
    anti_pattern: int = 0
    request_bias: int = 0
    confidence: int = 0
    matched_terms: dict[str, list[str]] = Field(default_factory=dict)


class ExampleSelection(BaseModel):
    example_id: str
    score: int
    strength_overlap: list[str]
    motif_overlap: list[str]
    conflicting_strength_tags: list[str] = Field(default_factory=list)
    conflicting_motif_tags: list[str] = Field(default_factory=list)
    matched_tokens: list[str] = Field(default_factory=list)
    ux_role_match: list[UxRole] = Field(default_factory=list)


class OptionalPattern(BaseModel):
    pattern_id: str
    pack_id: str
    example_id: str | None = None
    source_kind: PatternSourceKind
    score: int
    score_axes: dict[str, int] = Field(default_factory=dict)
    domain_fit: PatternDomainFit = "neutral"
    mechanic_fit: int = Field(default=0, ge=0, le=100)
    quality_score: int = Field(default=0, ge=0, le=100)
    identity_risk: PatternIdentityRisk = "medium"
    ux_roles: list[UxRole] = Field(default_factory=list)
    priority_roles: list[UxRole] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    strength_tags: list[str] = Field(default_factory=list)
    motif_tags: list[str] = Field(default_factory=list)
    job_statement: str = ""
    when_to_use: str = ""
    when_not_to_use: str = ""
    states: list[str] = Field(default_factory=list)
    responsive_behavior: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    integration_hint: str = ""
    excerpt: CodeFile | None = None
    style_excerpt: CodeFile | None = None
    hygiene_clean: bool = True
    optional: bool = True


class PatternCatalogEntry(BaseModel):
    pattern_id: str
    pack_id: str
    example_id: str | None = None
    source_kind: PatternSourceKind
    score: int
    domain_fit: PatternDomainFit
    mechanic_fit: int
    quality_score: int
    identity_risk: PatternIdentityRisk
    ux_roles: list[UxRole] = Field(default_factory=list)
    priority_roles: list[UxRole] = Field(default_factory=list)
    job_statement: str = ""


class RouteResolution(BaseModel):
    request: DesignContextRequest
    normalized_request: NormalizedRequest
    anchor_pack: LoadedPack
    hero_reference_pack: LoadedPack | None = None
    support_bank: LoadedPack | None = None
    selected_examples: list[ExampleSelection] = Field(default_factory=list)
    optional_patterns: list[OptionalPattern] = Field(default_factory=list)
    optional_pattern_catalog: list[PatternCatalogEntry] = Field(default_factory=list)
    optional_pattern_candidates: list[OptionalPattern] = Field(
        default_factory=list,
        exclude=True,
        repr=False,
    )
    auxiliary_anchor_packs: list[LoadedPack] = Field(default_factory=list)
    shared_atoms: list[AtomSnippet] = Field(default_factory=list)
    anchor_score: ScoreBreakdown
    support_bank_score: ScoreBreakdown | None = None
    route_meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def selected_example_ids(self) -> list[str]:
        return [example.example_id for example in self.selected_examples]

    @property
    def optional_pattern_ids(self) -> list[str]:
        return [pattern.pattern_id for pattern in self.optional_patterns]


class RenderedPacket(BaseModel):
    markdown: str
    estimated_tokens: int
    token_mode: TokenMode = "unbounded"
    selected_files: list[str] = Field(default_factory=list)
    omitted_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
