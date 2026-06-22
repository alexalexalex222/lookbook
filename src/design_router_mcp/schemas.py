from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TokenMode = Literal["micro", "compact", "standard", "expanded", "full_selected", "library_audit"]
LocalModelProfile = Literal["tiny_16k", "balanced_32k", "strong_64k", "moe_128k", "manual"]
DonorSelectionMode = Literal["default", "support_examples_v1", "site_donor_first_v1", "auto_lane_promotion_v1"]
RouteProfile = Literal["hybrid_survivor_v1", "legacy_exploration", "specialty_hardened", "data_driven_v2"]
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
    stack: str = Field(default="unknown")
    tone: list[str] = Field(default_factory=list)
    layout_mode: str = Field(default="homepage")
    constraints: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    desired_density: str = Field(default="balanced")
    max_examples: int = Field(default=3, ge=0, le=5)
    donor_selection_mode: DonorSelectionMode = Field(default="support_examples_v1")
    donor_count: int = Field(default=3, ge=1, le=3)
    route_profile: RouteProfile = Field(default="data_driven_v2")
    packet_profile: PacketProfile = Field(default="compact_v2")
    include_full_library: bool = Field(default=False)
    pattern_lock: bool = Field(default=False)
    pattern_lock_strict: bool = Field(default=False)
    pattern_lock_exact: bool = Field(default=False)
    full_code_mode: bool = Field(default=False)
    prefer_angular_geometry: bool = Field(default=True)
    host_browser_review: bool = Field(default=False)
    token_mode: TokenMode = Field(default="compact")
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


class NormalizedRequest(BaseModel):
    surface: str
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


class RouteResolution(BaseModel):
    request: DesignContextRequest
    normalized_request: NormalizedRequest
    anchor_pack: LoadedPack
    hero_reference_pack: LoadedPack | None = None
    support_bank: LoadedPack | None = None
    selected_examples: list[ExampleSelection] = Field(default_factory=list)
    auxiliary_anchor_packs: list[LoadedPack] = Field(default_factory=list)
    shared_atoms: list[AtomSnippet] = Field(default_factory=list)
    anchor_score: ScoreBreakdown
    support_bank_score: ScoreBreakdown | None = None
    route_meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def selected_example_ids(self) -> list[str]:
        return [example.example_id for example in self.selected_examples]


class RenderedPacket(BaseModel):
    markdown: str
    estimated_tokens: int
    token_mode: TokenMode = "compact"
    selected_files: list[str] = Field(default_factory=list)
    omitted_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
