"""LangGraph nodes for analyst workflow."""

from core.framework.messages import AnalysisPayload


class AnalystNodes(object):
    def __init__(self, extraction_engine):
        self.extraction_engine = extraction_engine

    @staticmethod
    def _merge(state, updates):
        merged = dict(state)
        merged.update(updates)
        return merged

    def build_prompt(self, state):
        return self._merge(state, {"trace": state.get("trace", []) + ["build_prompt"]})

    def call_gemini_extract(self, state):
        payload = state.get("filing_payload")
        if payload is None:
            return self._merge(state, {"analysis_dict": {}, "errors": state.get("errors", []) + ["missing_filing_payload"]})
        extracted = self.extraction_engine.extract(payload.raw_text, reflection=False)
        return self._merge(
            state,
            {
                "analysis_dict": extracted,
                "reflection_attempted": False,
                "trace": state.get("trace", []) + ["call_gemini_extract"],
            },
        )

    def validate_json(self, state):
        analysis_dict = state.get("analysis_dict", {})
        is_valid = self.extraction_engine.is_valid(analysis_dict)
        return self._merge(state, {"is_valid": is_valid, "trace": state.get("trace", []) + ["validate_json"]})

    def route_after_validation(self, state):
        if state.get("is_valid"):
            return "emit"
        if state.get("reflection_attempted"):
            return "dead_letter"
        return "reflect"

    def reflection_retry_once(self, state):
        payload = state.get("filing_payload")
        reflected = self.extraction_engine.extract(payload.raw_text, reflection=True)
        return self._merge(
            state,
            {
                "analysis_dict": reflected,
                "reflection_attempted": True,
                "trace": state.get("trace", []) + ["reflection_retry_once"],
            },
        )

    def dead_letter(self, state):
        payload = state.get("filing_payload")
        errors = list(state.get("errors", []))
        errors.append("analysis_validation_failed")
        return self._merge(
            state,
            {
                "errors": errors,
                "dead_letter": {
                    "ticker": payload.ticker,
                    "accession_number": payload.accession_number,
                    "reason": "validation_failed_after_reflection",
                },
                "trace": state.get("trace", []) + ["dead_letter"],
            },
        )

    def emit_analysis_payload(self, state):
        filing_payload = state.get("filing_payload")
        analysis_dict = normalize_analysis_dict(state.get("analysis_dict", {}))
        payload = AnalysisPayload(
            ticker=filing_payload.ticker,
            accession_number=filing_payload.accession_number,
            kpis=analysis_dict.get("kpis", []),
            summary=analysis_dict.get("summary", {}),
            guidance=analysis_dict.get("guidance", []),
        )
        return self._merge(state, {"analysis": payload, "trace": state.get("trace", []) + ["emit_analysis_payload"]})


def normalize_analysis_dict(data):
    if not isinstance(data, dict):
        return {"kpis": [], "summary": {}, "guidance": []}

    kpis = data.get("kpis", [])
    if isinstance(kpis, dict):
        kpis = [kpis]
    elif not isinstance(kpis, list):
        kpis = []
    kpis = [item for item in kpis if isinstance(item, dict)]

    summary = data.get("summary", {})
    if isinstance(summary, str):
        summary = {"highlights": [summary]}
    elif isinstance(summary, list):
        summary = {"highlights": [str(item) for item in summary]}
    elif not isinstance(summary, dict):
        summary = {}

    guidance = data.get("guidance", [])
    if isinstance(guidance, dict):
        guidance = [guidance]
    elif isinstance(guidance, str):
        guidance = [{"note": guidance}]
    elif not isinstance(guidance, list):
        guidance = []
    guidance = [item for item in guidance if isinstance(item, dict)]

    return {"kpis": kpis, "summary": summary, "guidance": guidance}
