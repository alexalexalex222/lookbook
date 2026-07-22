from __future__ import annotations

import colorsys
import math
import os
import statistics
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .schemas import DesignContextRequest


PIXEL_FEATURE_KEYS = (
    "mean_luma",
    "contrast",
    "mean_saturation",
    "warmth",
    "dark_ratio",
    "light_ratio",
    "edge_density",
    "entropy",
    "colorfulness",
    "horizontal_imbalance",
    "vertical_imbalance",
    "center_emphasis",
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    diagonal_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= diagonal_distance:
        return left
    if up_distance <= diagonal_distance:
        return up
    return upper_left


def _decode_png(
    path: Path, *, max_side: int
) -> tuple[list[tuple[int, int, int]], int, int]:
    data = path.read_bytes()
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("not a PNG")
    offset = len(_PNG_SIGNATURE)
    width = height = bit_depth = color_type = interlace = 0
    palette: list[tuple[int, int, int]] = []
    transparency: bytes = b""
    compressed: list[bytes] = []
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            if compression != 0 or filtering != 0:
                raise ValueError("unsupported PNG compression/filtering")
        elif kind == b"PLTE":
            palette = [
                (payload[index], payload[index + 1], payload[index + 2])
                for index in range(0, len(payload), 3)
            ]
        elif kind == b"tRNS":
            transparency = payload
        elif kind == b"IDAT":
            compressed.append(payload)
        elif kind == b"IEND":
            break
    if bit_depth != 8 or interlace != 0:
        raise ValueError(
            "only 8-bit non-interlaced PNG images are supported without Pillow"
        )
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if not channels or not width or not height:
        raise ValueError("unsupported or incomplete PNG")
    expected = height * ((width * channels) + 1)
    if expected > 300_000_000:
        raise ValueError("image is too large to profile")
    raw = zlib.decompress(b"".join(compressed))
    if len(raw) < expected:
        raise ValueError("truncated PNG data")

    x_step = max(1, math.ceil(width / max_side))
    y_step = max(1, math.ceil(height / max_side))
    sample_width = math.ceil(width / x_step)
    sample_height = math.ceil(height / y_step)
    row_size = width * channels
    previous = bytearray(row_size)
    pixels: list[tuple[int, int, int]] = []
    cursor = 0
    for y in range(height):
        filter_type = raw[cursor]
        cursor += 1
        encoded = raw[cursor : cursor + row_size]
        cursor += row_size
        row = bytearray(row_size)
        for index, value in enumerate(encoded):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                decoded = value
            elif filter_type == 1:
                decoded = value + left
            elif filter_type == 2:
                decoded = value + up
            elif filter_type == 3:
                decoded = value + ((left + up) // 2)
            elif filter_type == 4:
                decoded = value + _paeth(left, up, upper_left)
            else:
                raise ValueError(f"unsupported PNG filter {filter_type}")
            row[index] = decoded & 0xFF
        if y % y_step == 0:
            for x in range(0, width, x_step):
                start = x * channels
                if color_type == 0:
                    gray = row[start]
                    pixels.append((gray, gray, gray))
                elif color_type == 2:
                    pixels.append((row[start], row[start + 1], row[start + 2]))
                elif color_type == 3:
                    palette_index = row[start]
                    if palette_index >= len(palette):
                        pixels.append((0, 0, 0))
                    elif (
                        palette_index < len(transparency)
                        and transparency[palette_index] == 0
                    ):
                        pixels.append((255, 255, 255))
                    else:
                        pixels.append(palette[palette_index])
                elif color_type == 4:
                    gray, alpha = row[start], row[start + 1]
                    pixels.append(
                        tuple(
                            round((gray * alpha + 255 * (255 - alpha)) / 255)
                            for _ in range(3)
                        )
                    )
                else:
                    red, green, blue, alpha = row[start : start + 4]
                    pixels.append(
                        (
                            round((red * alpha + 255 * (255 - alpha)) / 255),
                            round((green * alpha + 255 * (255 - alpha)) / 255),
                            round((blue * alpha + 255 * (255 - alpha)) / 255),
                        )
                    )
        previous = row
    return pixels, sample_width, sample_height


def _decode_with_pillow(
    path: Path, *, max_side: int
) -> tuple[list[tuple[int, int, int]], int, int]:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))
        width, height = image.size
        pixels = (
            image.get_flattened_data()
            if hasattr(image, "get_flattened_data")
            else image.getdata()
        )
        return list(pixels), width, height


def _decode_image(
    path: Path, *, max_side: int
) -> tuple[list[tuple[int, int, int]], int, int, str]:
    try:
        pixels, width, height = _decode_with_pillow(path, max_side=max_side)
        return pixels, width, height, "pillow"
    except (ImportError, OSError, ValueError):
        pixels, width, height = _decode_png(path, max_side=max_side)
        return pixels, width, height, "png-stdlib"


def _edge_density(luma: list[float], width: int, height: int) -> float:
    if width < 2 or height < 2 or len(luma) < width * height:
        return 0.0
    edges = comparisons = 0
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if x + 1 < width:
                edges += abs(luma[index] - luma[index + 1]) >= 0.12
                comparisons += 1
            if y + 1 < height:
                edges += abs(luma[index] - luma[index + width]) >= 0.12
                comparisons += 1
    return edges / comparisons if comparisons else 0.0


def _region_mean(
    values: list[float],
    width: int,
    height: int,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> float:
    selected: list[float] = []
    for y in range(
        max(0, int(height * y0)), min(height, max(1, math.ceil(height * y1)))
    ):
        start = y * width
        for x in range(
            max(0, int(width * x0)), min(width, max(1, math.ceil(width * x1)))
        ):
            selected.append(values[start + x])
    return statistics.fmean(selected) if selected else 0.0


def _dominant_palette(
    pixels: Iterable[tuple[int, int, int]], *, limit: int = 5
) -> list[str]:
    buckets = Counter(
        (red // 32, green // 32, blue // 32) for red, green, blue in pixels
    )
    colors: list[str] = []
    for (red, green, blue), _ in buckets.most_common(limit):
        colors.append(
            f"#{min(255, red * 32 + 16):02x}{min(255, green * 32 + 16):02x}{min(255, blue * 32 + 16):02x}"
        )
    return colors


def _visual_terms(features: dict[str, float]) -> list[str]:
    terms: set[str] = set()
    terms.add(
        "dark-pixel-field" if features["mean_luma"] < 0.42 else "light-pixel-field"
    )
    if features["contrast"] >= 0.24:
        terms.add("high-pixel-contrast")
    elif features["contrast"] <= 0.14:
        terms.add("low-pixel-contrast")
    if features["mean_saturation"] >= 0.48:
        terms.add("saturated-palette")
    elif features["mean_saturation"] <= 0.25:
        terms.add("muted-palette")
    if features["warmth"] >= 0.57:
        terms.add("warm-palette")
    elif features["warmth"] <= 0.43:
        terms.add("cool-palette")
    if features["edge_density"] >= 0.2:
        terms.add("visually-dense")
    elif features["edge_density"] <= 0.08:
        terms.add("visually-airy")
    if features["horizontal_imbalance"] >= 0.12:
        terms.add("asymmetric-horizontal-composition")
    if features["center_emphasis"] >= 0.1:
        terms.add("center-emphasis")
    return sorted(terms)


def analyze_image(path: Path | str, *, max_side: int = 96) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    base = {
        "path": str(resolved),
        "available": False,
        "decoder": "",
        "sample_width": 0,
        "sample_height": 0,
        "features": {},
        "vector": [],
        "terms": [],
        "dominant_colors": [],
    }
    try:
        pixels, width, height, decoder = _decode_image(resolved, max_side=max_side)
    except (OSError, ValueError, zlib.error):
        return base
    if not pixels or width <= 0 or height <= 0:
        return base

    red = [pixel[0] / 255.0 for pixel in pixels]
    green = [pixel[1] / 255.0 for pixel in pixels]
    blue = [pixel[2] / 255.0 for pixel in pixels]
    luma = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in zip(red, green, blue)]
    saturation = [colorsys.rgb_to_hsv(r, g, b)[1] for r, g, b in zip(red, green, blue)]
    luma_bins = Counter(min(15, int(value * 16)) for value in luma)
    entropy = (
        -sum(
            (count / len(luma)) * math.log2(count / len(luma))
            for count in luma_bins.values()
            if count
        )
        / 4.0
    )
    left = _region_mean(luma, width, height, 0.0, 0.5, 0.0, 1.0)
    right = _region_mean(luma, width, height, 0.5, 1.0, 0.0, 1.0)
    top = _region_mean(luma, width, height, 0.0, 1.0, 0.0, 0.5)
    bottom = _region_mean(luma, width, height, 0.0, 1.0, 0.5, 1.0)
    center = _region_mean(luma, width, height, 0.25, 0.75, 0.25, 0.75)
    mean_luma = statistics.fmean(luma)
    rg = [r - g for r, g in zip(red, green)]
    yb = [0.5 * (r + g) - b for r, g, b in zip(red, green, blue)]
    colorfulness = _clamp(
        (
            math.sqrt(statistics.pvariance(rg) + statistics.pvariance(yb))
            + 0.3 * math.sqrt(statistics.fmean(rg) ** 2 + statistics.fmean(yb) ** 2)
        )
        / 0.75
    )
    features = {
        "mean_luma": _clamp(mean_luma),
        "contrast": _clamp(statistics.pstdev(luma) / 0.5),
        "mean_saturation": _clamp(statistics.fmean(saturation)),
        "warmth": _clamp(
            0.5 + statistics.fmean(r - b for r, b in zip(red, blue)) / 2.0
        ),
        "dark_ratio": sum(value <= 0.25 for value in luma) / len(luma),
        "light_ratio": sum(value >= 0.75 for value in luma) / len(luma),
        "edge_density": _clamp(_edge_density(luma, width, height)),
        "entropy": _clamp(entropy),
        "colorfulness": colorfulness,
        "horizontal_imbalance": _clamp(abs(left - right)),
        "vertical_imbalance": _clamp(abs(top - bottom)),
        "center_emphasis": _clamp(abs(center - mean_luma)),
    }
    return {
        **base,
        "available": True,
        "decoder": decoder,
        "sample_width": width,
        "sample_height": height,
        "features": {key: round(value, 6) for key, value in features.items()},
        "vector": [round(features[key], 6) for key in PIXEL_FEATURE_KEYS],
        "terms": _visual_terms(features),
        "dominant_colors": _dominant_palette(pixels),
    }


def aggregate_profiles(profiles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    available = [
        profile
        for profile in profiles
        if profile.get("available") and profile.get("features")
    ]
    if not available:
        return {
            "available": False,
            "image_count": 0,
            "features": {},
            "vector": [],
            "terms": [],
        }
    features = {
        key: statistics.fmean(float(profile["features"][key]) for profile in available)
        for key in PIXEL_FEATURE_KEYS
    }
    return {
        "available": True,
        "image_count": len(available),
        "features": {key: round(value, 6) for key, value in features.items()},
        "vector": [round(features[key], 6) for key in PIXEL_FEATURE_KEYS],
        "terms": sorted(
            {term for profile in available for term in profile.get("terms", [])}
        ),
    }


def visual_target_from_request(
    request: DesignContextRequest,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    tokens = {
        token
        for value in [
            request.task,
            request.layout_mode,
            request.desired_density,
            *request.tone,
            *request.constraints,
        ]
        for token in value.lower().replace("-", " ").replace("_", " ").split()
    }
    values: dict[str, list[tuple[float, float]]] = {}
    weights: dict[str, float] = {}

    def add(key: str, value: float, weight: float = 1.0) -> None:
        values.setdefault(key, []).append((value, weight))
        weights[key] = max(weights.get(key, 0.0), weight)

    if tokens.intersection({"dark", "black", "charcoal", "night", "ink"}):
        add("mean_luma", 0.24, 1.4)
        add("dark_ratio", 0.68, 1.2)
    if tokens.intersection({"light", "white", "bright", "airy"}):
        add("mean_luma", 0.78, 1.4)
        add("light_ratio", 0.62, 1.1)
    if tokens.intersection({"warm", "copper", "brass", "gold", "cream", "rose"}):
        add("warmth", 0.72, 1.2)
    if tokens.intersection({"cool", "blue", "cyan", "ice", "aqua"}):
        add("warmth", 0.3, 1.2)
    if tokens.intersection({"vibrant", "colorful", "saturated", "neon"}):
        add("mean_saturation", 0.7, 1.0)
        add("colorfulness", 0.72, 0.9)
    if tokens.intersection({"muted", "restrained", "neutral", "calm", "minimal"}):
        add("mean_saturation", 0.24, 1.0)
        add("colorfulness", 0.25, 0.8)
    if ("high" in tokens and "contrast" in tokens) or "high-contrast" in request.tone:
        add("contrast", 0.62, 1.3)
    if "low" in tokens and "contrast" in tokens:
        add("contrast", 0.12, 1.1)
    if tokens.intersection(
        {"dense", "dashboard", "terminal", "technical", "industrial"}
    ):
        add("edge_density", 0.32, 0.8)
        add("entropy", 0.72, 0.7)
    if tokens.intersection({"airy", "quiet", "editorial", "minimal"}):
        add("edge_density", 0.08, 0.8)
    if tokens.intersection({"asymmetric", "asymmetrical"}):
        add("horizontal_imbalance", 0.22, 0.7)
    if tokens.intersection({"centered", "centred", "object-focused"}):
        add("center_emphasis", 0.18, 0.7)

    request_term_features = bool(values)
    reference_profiles: list[dict[str, Any]] = []
    blocked_reference_count = 0
    if repo_root is not None:
        root = Path(repo_root).expanduser().resolve()
        allowed_roots = allowed_reference_roots(root)
        for raw_path in request.reference_image_paths:
            candidate = Path(raw_path).expanduser()
            candidate = (
                candidate.resolve()
                if candidate.is_absolute()
                else (root / candidate).resolve()
            )
            if (
                candidate.suffix.lower()
                not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                or not candidate.is_file()
                or not any(
                    candidate.is_relative_to(allowed) for allowed in allowed_roots
                )
            ):
                blocked_reference_count += 1
                continue
            profile = analyze_image(candidate)
            if profile.get("available"):
                reference_profiles.append(profile)
    reference_profile = aggregate_profiles(reference_profiles)
    for key, value in reference_profile.get("features", {}).items():
        add(key, float(value), 2.0)

    features = {
        key: sum(value * weight for value, weight in items)
        / sum(weight for _, weight in items)
        for key, items in values.items()
    }
    return {
        "active": bool(features),
        "features": {key: round(value, 6) for key, value in features.items()},
        "weights": weights,
        "source": (
            "request_terms+reference_images"
            if reference_profiles and request_term_features
            else "reference_images"
            if reference_profiles
            else "request_terms"
        ),
        "reference_images": {
            "requested": len(request.reference_image_paths),
            "profiled": len(reference_profiles),
            "blocked_or_unreadable": blocked_reference_count,
        },
    }


def visual_similarity(target: dict[str, Any], profile: dict[str, Any]) -> float:
    if not target.get("active") or not profile.get("available"):
        return 0.0
    target_features = target.get("features", {})
    profile_features = profile.get("features", {})
    weights = target.get("weights", {})
    total = matched = 0.0
    for key, wanted in target_features.items():
        if key not in profile_features:
            continue
        weight = float(weights.get(key, 1.0))
        matched += weight * (1.0 - abs(float(wanted) - float(profile_features[key])))
        total += weight
    return round(_clamp(matched / total if total else 0.0), 6)


def allowed_reference_roots(repo_root: Path) -> list[Path]:
    roots = [repo_root.resolve()]
    configured = os.getenv("DESIGN_ROUTER_REFERENCE_IMAGE_ROOTS", "")
    for value in configured.split(os.pathsep):
        if value.strip():
            roots.append(Path(value).expanduser().resolve())
    return roots
