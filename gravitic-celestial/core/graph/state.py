"""Typed graph state shared by LangGraph nodes."""

from typing import Any, Dict, List, Optional, TypedDict

from core.framework.messages import AnalysisPayload, FilingPayload, IndexReceipt


class GraphState(TypedDict, total=False):
    market: str
    exchange: str
    issuer_id: str
    source_event_id: str
    ticker: str
    accession_number: str
    filing_url: str
    raw_text: str
    filings_queue: List[Dict[str, Any]]
    current_filing: Dict[str, Any]
    filing_payloads: List[FilingPayload]
    analysis: AnalysisPayload
    analysis_dict: Dict[str, Any]
    index_receipt: IndexReceipt
    retrieval_results: List[Dict[str, Any]]
    semantic_results: List[Dict[str, Any]]
    keyword_results: List[Dict[str, Any]]
    question: str
    answer: str
    answer_citations: List[str]
    answer_confidence: float
    derivation_trace: List[str]
    errors: List[str]
    trace: List[str]
    reflection_attempted: bool
    is_valid: bool
