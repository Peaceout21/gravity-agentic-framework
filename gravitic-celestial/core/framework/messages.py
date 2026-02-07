"""Message contracts shared across graph nodes and event bus."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from pydantic import BaseModel, Field  # type: ignore
except Exception:
    class BaseModel(object):
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def dict(self):
            return dict(self.__dict__)

    def Field(default=None, default_factory=None, description=None):  # noqa: ARG001
        if default_factory is not None:
            return default_factory()
        return default

TOPIC_FILING_FOUND = "FILING_FOUND"
TOPIC_ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
TOPIC_USER_QUERY = "USER_QUERY"
TOPIC_SYNTHESIS_COMPLETED = "SYNTHESIS_COMPLETED"
TOPIC_DEAD_LETTER = "DEAD_LETTER"


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique Message ID")
    source: str = Field(..., description="Agent Name")
    topic: str = Field(..., description="Event Topic")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FilingPayload(BaseModel):
    ticker: str
    accession_number: str
    filing_url: str
    raw_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AnalysisPayload(BaseModel):
    ticker: str
    accession_number: str
    kpis: List[Dict[str, str]] = Field(default_factory=list)
    summary: Dict[str, List[str]] = Field(default_factory=dict)
    guidance: List[Dict[str, str]] = Field(default_factory=list)


class IndexReceipt(BaseModel):
    accession_number: str
    chunk_count: int
    indexed_at: datetime = Field(default_factory=datetime.utcnow)


class MarkdownAnswer(BaseModel):
    question: str
    answer_markdown: str
    citations: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def make_message(source: str, topic: str, payload: Optional[Dict[str, Any]] = None) -> AgentMessage:
    return AgentMessage(source=source, topic=topic, payload=payload or {})
