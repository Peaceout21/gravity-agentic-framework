"""Template-driven Ask orchestration helpers."""

import time
from typing import Any, Dict, List, Optional, Tuple


class _SafeDict(dict):
    def __missing__(self, key):
        return "{%s}" % key


def render_question(template, ticker=None, params=None):
    # type: (Dict[str, Any], Optional[str], Optional[Dict[str, Any]]) -> str
    values = dict(params or {})
    if ticker:
        values["ticker"] = ticker.upper()
    values.setdefault("period", "latest quarter")
    values.setdefault("compare_to", "previous quarter")
    rendered = template["question_template"].format_map(_SafeDict(values))
    return " ".join(rendered.split())


def compute_relevance(template_rules, filings):
    # type: (List[Dict[str, Any]], List[Dict[str, Any]]) -> Tuple[str, float]
    if not filings:
        return "Low relevance", 0.0
    if not template_rules:
        return "Medium relevance", 0.6

    best_score = 0.0
    for filing in filings:
        filing_type = str(filing.get("filing_type", "")).upper()
        item_codes = _normalize_item_codes(filing.get("item_code", ""))
        for rule in template_rules:
            if filing_type != str(rule.get("filing_type", "")).upper():
                continue
            required_item = str(rule.get("item_code", "")).strip().upper()
            if required_item and required_item not in item_codes:
                continue
            weight = float(rule.get("weight", 0.0))
            if weight > best_score:
                best_score = weight

    if best_score >= 0.9:
        return "High relevance", best_score
    if best_score >= 0.5:
        return "Medium relevance", best_score
    return "Low relevance", best_score


def build_coverage_brief(filings, relevance_label, template_rules=None):
    # type: (List[Dict[str, Any]], str, Optional[List[Dict[str, Any]]]) -> str
    if not filings:
        hint = _format_rule_hint(template_rules)
        if hint:
            return "No analyzed filings available for this ticker yet. %s Run ingestion/backfill first." % hint
        return "No analyzed filings available for this ticker yet. Run ingestion/backfill first."
    seen = []
    for filing in filings[:3]:
        filing_type = filing.get("filing_type") or "Unknown form"
        filing_date = filing.get("filing_date") or filing.get("updated_at", "")
        filing_date = str(filing_date)[:10]
        item_code = filing.get("item_code") or ""
        detail = filing_type
        if item_code:
            detail = "%s Item %s" % (detail, item_code)
        seen.append("%s (%s)" % (detail, filing_date))
    joined = ", ".join(seen)
    if relevance_label == "Low relevance":
        hint = _format_rule_hint(template_rules)
        return (
            "Available: %s. %s"
            % (joined, hint if hint else "This template may be a weak fit for the available filing types.")
        )
    return "Based on analyzed filings: %s." % joined


def _format_rule_hint(template_rules):
    # type: (Optional[List[Dict[str, Any]]]) -> str
    """Build a human-readable hint of which filing types the template works best with."""
    if not template_rules:
        return ""
    parts = []
    for rule in sorted(template_rules, key=lambda r: -float(r.get("weight", 0))):
        filing_type = rule.get("filing_type", "")
        item_code = rule.get("item_code", "")
        if not filing_type:
            continue
        entry = filing_type
        if item_code:
            entry = "%s Item %s" % (entry, item_code)
        if entry not in parts:
            parts.append(entry)
    if not parts:
        return ""
    return "Best with: %s." % ", ".join(parts)


def run_template_query(state_manager, graph_runtime, org_id, user_id, template, ticker=None, params=None):
    # type: (...) -> Dict[str, Any]
    started = time.time()
    rendered_question = render_question(template, ticker=ticker, params=params)
    filings = state_manager.list_recent_analyzed_filings(ticker=ticker, limit=6)
    rules = state_manager.list_ask_template_rules(template["id"])
    relevance_label, relevance_score = compute_relevance(rules, filings)
    coverage_brief = build_coverage_brief(filings, relevance_label, template_rules=rules)

    answer = graph_runtime.answer_question(rendered_question, ticker=ticker or None)
    latency_ms = int((time.time() - started) * 1000)
    run_id = state_manager.create_ask_template_run(
        org_id=org_id,
        user_id=user_id,
        template_id=template["id"],
        ticker=ticker or "",
        rendered_question=rendered_question,
        relevance_label=relevance_label,
        coverage_brief=coverage_brief,
        answer_markdown=answer.answer_markdown,
        citations=answer.citations,
        confidence=float(getattr(answer, "confidence", 0.0) or 0.0),
        derivation_trace=list(getattr(answer, "derivation_trace", []) or []),
        latency_ms=latency_ms,
    )
    if hasattr(state_manager, "log_event"):
        state_manager.log_event(
            "TEMPLATE_RUN",
            "ask_templates",
            '{"template_id": %d, "relevance": "%s", "score": %.2f}' % (template["id"], relevance_label, relevance_score),
        )
        if relevance_label == "Low relevance":
            state_manager.log_event(
                "TEMPLATE_LOW_RELEVANCE",
                "ask_templates",
                '{"template_id": %d}' % template["id"],
            )
    return {
        "run_id": run_id,
        "template_id": template["id"],
        "template_title": template["title"],
        "question": rendered_question,
        "relevance_label": relevance_label,
        "relevance_score": relevance_score,
        "coverage_brief": coverage_brief,
        "answer_markdown": answer.answer_markdown,
        "citations": answer.citations,
        "confidence": float(getattr(answer, "confidence", 0.0) or 0.0),
        "derivation_trace": list(getattr(answer, "derivation_trace", []) or []),
        "latency_ms": latency_ms,
    }


def _normalize_item_codes(item_code):
    # type: (Any) -> List[str]
    if isinstance(item_code, list):
        values = item_code
    else:
        values = str(item_code or "").replace(";", ",").split(",")
    output = []
    for value in values:
        normalized = str(value).strip().upper()
        if normalized:
            output.append(normalized)
    return output
