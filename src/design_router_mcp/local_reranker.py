from __future__ import annotations

import json
import os
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .schemas import DesignContextRequest


def _post_json(
    endpoint: str, payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("reranker endpoint returned a non-object response")
    return result


def _response_object(payload: dict[str, Any]) -> dict[str, Any]:
    if {"winner", "ranking"}.intersection(payload):
        return payload
    content: Any = payload.get("response")
    if content is None and isinstance(payload.get("message"), dict):
        content = payload["message"].get("content")
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("reranker response did not include JSON content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("reranker JSON content was not an object")
    return parsed


def _local_endpoint_allowed(endpoint: str) -> bool:
    hostname = urlparse(endpoint).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _prompt(request: DesignContextRequest, candidates: list[dict[str, Any]]) -> str:
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "pack_id": candidate["pack_id"],
                "deterministic_score": candidate["score"],
                "family": candidate.get("family", ""),
                "tones": candidate.get("tones", []),
                "surfaces": candidate.get("surfaces", []),
                "motif_tags": candidate.get("motif_tags", []),
                "supports_tasks": candidate.get("supports_tasks", []),
                "matched_terms": candidate.get("matched_terms", {}),
                "pixel_profile": candidate.get("pixel_profile", {}),
            }
        )
    return (
        "You are a candidate-constrained design-route reranker. Reorder ONLY the supplied candidate pack_ids. "
        "Never invent or admit another pack. Prefer task fit, surface fit, visual-direction fit, "
        "state completeness, and anti-copy safety. If the brief is underspecified or candidates "
        "are indistinguishable, set abstain=true. Return strict JSON with keys winner, ranking, "
        "confidence (0..1), abstain, and reason. ranking must contain only supplied IDs.\n\n"
        f"REQUEST:\n{json.dumps(request.model_dump(mode='json'), sort_keys=True)}\n\n"
        f"CANDIDATES:\n{json.dumps(rows, sort_keys=True)}"
    )


def rerank_candidates(
    request: DesignContextRequest,
    candidates: list[dict[str, Any]],
    *,
    mode: str,
    max_promotion_gap: int = 18,
    min_confidence: float = 0.72,
) -> dict[str, Any]:
    base = {
        "mode": mode,
        "available": False,
        "valid": False,
        "promote": False,
        "winner": candidates[0]["pack_id"] if candidates else None,
        "ranking": [candidate["pack_id"] for candidate in candidates],
        "confidence": 0.0,
        "abstain": False,
        "reason": "",
        "reason_code": "",
        "promotion_bonus": 0,
    }
    if mode == "off":
        return {**base, "reason_code": "disabled"}
    if not candidates:
        return {**base, "reason_code": "empty_pool"}
    model = request.rerank_model or os.getenv("DESIGN_ROUTER_RERANK_MODEL", "")
    if not model:
        return {**base, "reason_code": "model_not_configured"}
    endpoint = os.getenv(
        "DESIGN_ROUTER_RERANK_URL", "http://localhost:11434/api/generate"
    )
    if os.getenv(
        "DESIGN_ROUTER_ALLOW_REMOTE_RERANK"
    ) != "1" and not _local_endpoint_allowed(endpoint):
        return {
            **base,
            "reason": "Only loopback rerank endpoints are allowed by default.",
            "reason_code": "non_local_endpoint_blocked",
        }
    try:
        timeout = float(os.getenv("DESIGN_ROUTER_RERANK_TIMEOUT", "30"))
    except ValueError:
        return {**base, "reason_code": "invalid_timeout"}
    try:
        response = _post_json(
            endpoint,
            {
                "model": model,
                "prompt": _prompt(request, candidates),
                "stream": False,
                "format": "json",
                "think": False,
                "options": {"temperature": 0},
            },
            timeout,
        )
    except Exception as exc:
        return {
            **base,
            "reason": str(exc)[:240],
            "reason_code": "endpoint_unavailable",
        }
    try:
        decision = _response_object(response)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            **base,
            "available": True,
            "reason": str(exc)[:240],
            "reason_code": "invalid_response",
        }

    allowed = [candidate["pack_id"] for candidate in candidates]
    allowed_set = set(allowed)
    winner = str(decision.get("winner") or "")
    ranking = decision.get("ranking")
    if not isinstance(ranking, list):
        ranking = [winner] if winner else []
    ranking = [str(pack_id) for pack_id in ranking]
    if winner not in allowed_set or any(
        pack_id not in allowed_set for pack_id in ranking
    ):
        return {
            **base,
            "available": True,
            "reason": str(decision.get("reason") or "")[:500],
            "reason_code": "candidate_escape",
        }
    ranking = list(dict.fromkeys([winner, *ranking, *allowed]))
    try:
        confidence = max(0.0, min(1.0, float(decision.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return {
            **base,
            "available": True,
            "reason": "confidence must be numeric",
            "reason_code": "invalid_response",
        }
    abstain = bool(decision.get("abstain"))
    reason = str(decision.get("reason") or "")[:500]
    valid = {
        **base,
        "available": True,
        "valid": True,
        "winner": winner,
        "ranking": ranking,
        "confidence": round(confidence, 4),
        "abstain": abstain,
        "reason": reason,
    }
    if mode == "shadow":
        return {**valid, "reason_code": "shadow_only"}
    if abstain:
        return {**valid, "reason_code": "model_abstained"}
    if confidence < min_confidence:
        return {**valid, "reason_code": "low_confidence"}
    if winner == allowed[0]:
        return {**valid, "reason_code": "baseline_confirmed"}
    scores = {candidate["pack_id"]: int(candidate["score"]) for candidate in candidates}
    gap = scores[allowed[0]] - scores[winner]
    if gap > max_promotion_gap:
        return {**valid, "reason_code": "outside_promotion_corridor"}
    bonus = max(1, gap + 1)
    return {
        **valid,
        "promote": True,
        "reason_code": "bounded_promotion",
        "promotion_bonus": bonus,
    }
