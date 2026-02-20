"""Confidence formatting helpers for Ask and dashboard surfaces."""

from typing import Any


def normalize_confidence(value):
    # type: (Any) -> float
    try:
        score = float(value)
    except Exception:
        return 0.0
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return round(score, 4)


def confidence_level(value):
    # type: (Any) -> str
    score = normalize_confidence(value)
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def confidence_label(value):
    # type: (Any) -> str
    score = normalize_confidence(value)
    level = confidence_level(score)
    if level == "high":
        return "High confidence (%.0f%%)" % (score * 100)
    if level == "medium":
        return "Medium confidence (%.0f%%)" % (score * 100)
    return "Low confidence (%.0f%%)" % (score * 100)


def low_confidence_warning(value):
    # type: (Any) -> str
    if confidence_level(value) != "low":
        return ""
    return "Low-confidence inference. Verify with cited filing text before using this in a decision."
