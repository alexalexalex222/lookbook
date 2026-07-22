from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HygieneHit:
    kind: str
    value: str
    start: int
    end: int


PHONE_RE = re.compile(r"(?<![\w])(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?![\w])")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
HTTP_URL_RE = re.compile(r"https?://[^\s\"')<>]+", re.IGNORECASE)
DOMAIN_RE = re.compile(r"\b(?:www\.)?[a-z0-9][a-z0-9\-]{1,62}\.(?:com|net|org|co|io|biz|info|us)\b", re.IGNORECASE)
MAILTO_RE = re.compile(r"mailto:[^\"'\s<>]+", re.IGNORECASE)
TEL_RE = re.compile(r"tel:[^\"'\s<>]+", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"/Users/[^\"'\s<>]+")
IMAGE_TAG_RE = re.compile(r"<\s*(?:img|picture|source)\b[^>]*>", re.IGNORECASE | re.DOTALL)
SRCSET_RE = re.compile(r"\s(?:src|srcset)\s*=\s*(['\"])[^'\"]*(?:https?://|data:image|\.jpg|\.jpeg|\.png|\.webp|\.gif)[^'\"]*\1", re.IGNORECASE)
CSS_RASTER_URL_RE = re.compile(r"url\(\s*(['\"]?)(?:https?://|data:image|[^)]*\.(?:jpg|jpeg|png|webp|gif))[^)]*\)", re.IGNORECASE)
EXTERNAL_LINK_TAG_RE = re.compile(
    r"<link\b(?=[^>]*\bhref\s*=\s*(['\"])(?:https?://|\[URL\]))[^>]*>\s*",
    re.IGNORECASE | re.DOTALL,
)
EXTERNAL_SCRIPT_TAG_RE = re.compile(
    r"<script\b(?=[^>]*\bsrc\s*=\s*(['\"])(?:https?://|\[URL\]))[^>]*>\s*</script>\s*",
    re.IGNORECASE | re.DOTALL,
)
EXTERNAL_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(['\"]?)(?:https?://|\[URL\])[^;)\n]*\1\s*\)?\s*;?",
    re.IGNORECASE,
)
EXTERNAL_FONT_FACE_RE = re.compile(
    r"@font-face\s*\{(?=[^}]*?(?:https?://|\[URL\]))[^}]*\}\s*",
    re.IGNORECASE | re.DOTALL,
)
PLACEHOLDER_URL_RE = re.compile(r"url\(\s*(['\"]?)\[URL\]\1\s*\)", re.IGNORECASE)
STAR_RATING_RE = re.compile(r"(?:\b\d(?:\.\d)?\s*/\s*5\b|\b\d(?:\.\d)?\s*-\s*star\b|\b\d(?:\.\d)?\s*star\b|\bfive\s*star\b|⭐+)", re.IGNORECASE)
YEARS_CLAIM_RE = re.compile(r"\b(?:since\s+\d{4}|\d{1,3}\+?\s+(?:years?|yrs?)(?:\s+of\s+[a-z ]{2,28})?)\b", re.IGNORECASE)
LARGE_PROOF_RE = re.compile(r"\b\d+(?:\.\d+)?\s*k\+?\s+(?:projects?|jobs?|clients?|customers?|moves?|installs?|reviews?)\b", re.IGNORECASE)
AWARD_CLAIM_RE = re.compile(r"\b(?:A\+\s*BBB|BBB|award[-\s]?winning|certified|#\s*1|number\s+one|best[-\s]?rated|top[-\s]?rated|trusted\s+experts?)\b", re.IGNORECASE)
TESTIMONIAL_RE = re.compile(r"\b(?:testimonial|testimonials|review\s+quote|review\s+quotes|reviewer|verified\s+reviews?)\b", re.IGNORECASE)
REVIEW_AUTHOR_RE = re.compile(r"(?:--|—)\s*[A-Z][A-Za-z .'-]{1,40},\s*[A-Z][A-Za-z .'-]{1,40}")

KNOWN_BRAND_TOKENS = (
    # Library reference-brand identities (synthetic). Longest forms first so the
    # alternation neutralizes the full name before any shorter overlapping token.
    "Cedarbrook Dental Associates",
    "Ashgrove Landscape & Design",
    "Cresthaul Moving of Augusta",
    "Beaconframe Construction",
    "Thermaline Heating & Air",
    "Oakline Custom Cabinets",
    "Finchline Body & Paint",
    "Velvet Fig Wax Studio",
    "Axlecraft Garage Door",
    "Terraverde Ecoscapes",
    "Mosswood Landscaping",
    "Emberforge Fight Gym",
    "Copperbeam Flooring",
    "Harborpipe Plumbing",
    "Stillwater Plumbing",
    "Summitline Roofing",
    "Stackpoint Storage",
    "Solace Medical Spa",
    "Ashgrove Landscape",
    "Thermaline Heating",
    "Pipewise Plumbing",
    "Silverwave MedSpa",
    "Willowbend Dental",
    "Oakline Cabinetry",
    "Cresthaul Moving",
    "Rivergate Dental",
    "Gullwing Roofing",
    "Oakline Cabinets",
    "Ridgecap Roofing",
    "Voltway Electric",
    "Quayside Dental",
    "Lumena Wellness",
    "Aurelia Med Spa",
    "Hale & Winslow",
    "Foster & Quinn",
    "Gatewood Fence",
    "Spa Larkspur",
    "Velvet Fig",
    "Emberforge",
    "Ashgrove",
)

CASE_SENSITIVE_BRAND_TOKENS = (
    # Synthetic/localhost donor identities captured for router pattern packs.
    # Keep these case-sensitive so common words such as "tape" and "epoch" are
    # not over-sanitized in unrelated user briefs.
    "AETHON",
    "Meridian",
    "Ardent",
    "TAPE",
    "Epoch",
    "Pénombre",
    "PÉNOMBRE",
    "TACET",
    "Umbra",
    "PHOSPHOR",
)

CONTEXTUAL_BRAND_PATTERNS = (
    # Lowercase docs donor identity appears in package/import/command contexts.
    # Avoid replacing the ordinary English word "epoch" in prose.
    r"(?<=install\s)epoch\b",
    r"\bepoch(?=(?:/|\s+(?:Docs|Labs|Cloud|deploy|dev|init|schema|react)))",
    r"\btape(?=-)",
    r"\btape-terminal\b",
    r"\bpénombre\b",
    r"\btacet\b",
    r"\bumbra\b",
    r"\bphosphor\b",
)

DONOR_COPY_PHRASES = (
    "Mass to orbit",
    "Read the tape",
    "tape   tape   tape",
    "tape tape tape",
    "Trust the screen",
    "Everything the desk reads, in one surface",
    "The market is moving",
    "The house",
    "Five hours await",
    "Engineered to disappear",
    "Most headphones have a sound",
    "Nothing here is decorative",
    "The quietest thing we build is the silence",
)

SCAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tel_link", TEL_RE),
    ("mailto_link", MAILTO_RE),
    ("email", EMAIL_RE),
    ("phone", PHONE_RE),
    ("local_path", LOCAL_PATH_RE),
    ("external_url", HTTP_URL_RE),
    ("domain", DOMAIN_RE),
    ("image_tag", IMAGE_TAG_RE),
    ("image_src", SRCSET_RE),
    ("css_raster_url", CSS_RASTER_URL_RE),
    ("star_rating", STAR_RATING_RE),
    ("years_claim", YEARS_CLAIM_RE),
    ("large_proof_claim", LARGE_PROOF_RE),
    ("award_claim", AWARD_CLAIM_RE),
    ("testimonial", TESTIMONIAL_RE),
    ("review_author", REVIEW_AUTHOR_RE),
)


def _brand_pattern() -> re.Pattern[str]:
    escaped = [re.escape(token) for token in KNOWN_BRAND_TOKENS]
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


BRAND_RE = _brand_pattern()
CASE_SENSITIVE_BRAND_RE = re.compile(r"\b(?:" + "|".join(re.escape(token) for token in CASE_SENSITIVE_BRAND_TOKENS) + r")\b")
CONTEXTUAL_BRAND_RE = re.compile(r"(?:" + "|".join(CONTEXTUAL_BRAND_PATTERNS) + r")")
DONOR_COPY_RE = re.compile(r"(?:" + "|".join(re.escape(phrase) for phrase in DONOR_COPY_PHRASES) + r")", re.IGNORECASE)


def scan_source_hygiene(text: str) -> list[HygieneHit]:
    """Return source hygiene hits that should not be handed to local models raw."""

    hits: list[HygieneHit] = []
    for kind, pattern in SCAN_PATTERNS:
        for match in pattern.finditer(text):
            hits.append(HygieneHit(kind=kind, value=match.group(0)[:160], start=match.start(), end=match.end()))
    for match in BRAND_RE.finditer(text):
        hits.append(HygieneHit(kind="brand_identity", value=match.group(0)[:160], start=match.start(), end=match.end()))
    for match in CASE_SENSITIVE_BRAND_RE.finditer(text):
        hits.append(HygieneHit(kind="brand_identity", value=match.group(0)[:160], start=match.start(), end=match.end()))
    for match in CONTEXTUAL_BRAND_RE.finditer(text):
        hits.append(HygieneHit(kind="brand_identity", value=match.group(0)[:160], start=match.start(), end=match.end()))
    for match in DONOR_COPY_RE.finditer(text):
        hits.append(HygieneHit(kind="donor_copy_phrase", value=match.group(0)[:160], start=match.start(), end=match.end()))
    hits.sort(key=lambda hit: (hit.start, hit.end, hit.kind))
    deduped: list[HygieneHit] = []
    seen: set[tuple[str, int, int]] = set()
    for hit in hits:
        key = (hit.kind, hit.start, hit.end)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def hygiene_hits_to_dicts(hits: list[HygieneHit], *, limit: int = 20) -> list[dict[str, object]]:
    return [asdict(hit) for hit in hits[:limit]]


def sanitize_source_text(text: str) -> str:
    """Neutralize donor identity, proof claims, and raster/external assets.

    The sanitizer intentionally uses placeholders rather than invented replacement
    copy so packets stay useful without modeling unsafe claims.
    """

    if not text:
        return ""
    sanitized = text
    sanitized = re.sub(r"<\s*picture\b[^>]*>.*?<\s*/\s*picture\s*>", "<!-- SVG/CSS visual required; raster source removed -->", sanitized, flags=re.IGNORECASE | re.DOTALL)
    sanitized = IMAGE_TAG_RE.sub("<!-- SVG/CSS visual required; raster source removed -->", sanitized)
    sanitized = SRCSET_RE.sub("", sanitized)
    sanitized = CSS_RASTER_URL_RE.sub("none", sanitized)
    sanitized = TEL_RE.sub("[PHONE]", sanitized)
    sanitized = MAILTO_RE.sub("[EMAIL]", sanitized)
    sanitized = EMAIL_RE.sub("[EMAIL]", sanitized)
    sanitized = PHONE_RE.sub("[PHONE]", sanitized)
    sanitized = LOCAL_PATH_RE.sub("[LOCAL_PATH]", sanitized)
    sanitized = HTTP_URL_RE.sub("[URL]", sanitized)
    sanitized = DOMAIN_RE.sub("[URL]", sanitized)
    sanitized = BRAND_RE.sub("[BUSINESS_NAME]", sanitized)
    sanitized = CASE_SENSITIVE_BRAND_RE.sub("[BUSINESS_NAME]", sanitized)
    sanitized = CONTEXTUAL_BRAND_RE.sub("[BUSINESS_NAME]", sanitized)
    sanitized = DONOR_COPY_RE.sub("[DONOR_COPY]", sanitized)
    sanitized = REVIEW_AUTHOR_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    sanitized = STAR_RATING_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    sanitized = YEARS_CLAIM_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    sanitized = LARGE_PROOF_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    sanitized = AWARD_CLAIM_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    sanitized = TESTIMONIAL_RE.sub("[VERIFY_FROM_BRIEF]", sanitized)
    return sanitized


def strip_external_dependencies(text: str) -> str:
    """Remove network-loaded code, fonts, and assets from emitted reference code.

    Source excerpts are still allowed to use inline SVG, CSS, and local/system
    fonts. This transform is request-scoped by the renderer for briefs that require
    a self-contained build.
    """

    if not text:
        return ""
    cleaned = EXTERNAL_SCRIPT_TAG_RE.sub("", text)
    cleaned = EXTERNAL_LINK_TAG_RE.sub("", cleaned)
    cleaned = EXTERNAL_IMPORT_RE.sub("", cleaned)
    cleaned = EXTERNAL_FONT_FACE_RE.sub("", cleaned)
    cleaned = PLACEHOLDER_URL_RE.sub("none", cleaned)

    def _drop_font_loader_comment(match: re.Match[str]) -> str:
        value = match.group(0).lower()
        markers = (
            "google font",
            "font load",
            "font loading",
            "required load",
            "copy them into <head>",
            "fonts.googleapis",
            "fonts.gstatic",
        )
        return "" if any(marker in value for marker in markers) else match.group(0)

    cleaned = re.sub(
        r"<!--.*?-->",
        _drop_font_loader_comment,
        cleaned,
        flags=re.DOTALL,
    )
    cleaned = re.sub(
        r"/\*.*?\*/",
        _drop_font_loader_comment,
        cleaned,
        flags=re.DOTALL,
    )
    return cleaned.strip()
