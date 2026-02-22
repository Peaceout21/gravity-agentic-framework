"""Gemini extraction and synthesis adapters with robust fallbacks."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

try:
    from langchain_core.prompts import PromptTemplate  # type: ignore
except Exception:
    PromptTemplate = None


class GeminiAdapter(object):
    def __init__(self, model_name=None, api_key=None):
        self.model_candidates = []
        if model_name:
            self.model_candidates.append(model_name)
        self.model_candidates.extend(["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"])
        self.model_candidates = dedupe_strings(self.model_candidates)
        self.api_key = api_key
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
        except Exception:
            self._client = None

    def generate_text(self, prompt):
        if self._client is None:
            return ""
        for model_name in self.model_candidates:
            try:
                response = self._client.models.generate_content(model=model_name, contents=prompt)
                text = getattr(response, "text", "") or ""
                if text.strip():
                    return text
            except Exception:
                logging.exception("Gemini generate_text failed model=%s", model_name)
        return ""

    def generate_json(self, prompt):
        if self._client is None:
            return {}
        for model_name in self.model_candidates:
            try:
                response = self._client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                text = getattr(response, "text", "") or ""
                parsed = safe_json_extract(text)
                if parsed:
                    return parsed
            except TypeError:
                # Backward compatibility if SDK signature changes.
                try:
                    response = self._client.models.generate_content(model=model_name, contents=prompt)
                    text = getattr(response, "text", "") or ""
                    parsed = safe_json_extract(text)
                    if parsed:
                        return parsed
                except Exception:
                    logging.exception("Gemini generate_json failed model=%s", model_name)
            except Exception:
                logging.exception("Gemini generate_json failed model=%s", model_name)
        return {}


class ExtractionEngine(object):
    REQUIRED_KPI_KEYS = ["metric", "value"]
    REVENUE_ALIASES = [
        "revenue",
        "net sales",
        "sales",
        "turnover",
        "top line",
        "total revenue",
        "product revenue",
        "services revenue",
    ]

    def __init__(self, adapter=None):
        self.adapter = adapter or GeminiAdapter()

    def extract(self, raw_text, reflection=False, market="US_SEC"):
        prompt = self._build_prompt(raw_text, reflection=reflection, market=market)
        data = self.adapter.generate_json(prompt)
        if not isinstance(data, dict):
            return {}
        return self._normalize_metric_aliases(data)

    def extract_with_reflection(self, raw_text, market="US_SEC"):
        primary = self.extract(raw_text, reflection=False, market=market)
        if self.is_valid(primary):
            return primary
        return self.extract(raw_text, reflection=True, market=market)

    def is_valid(self, data):
        if not data:
            return False
        kpis = data.get("kpis")
        if not isinstance(kpis, list) or not kpis:
            return False
        for item in kpis:
            if not isinstance(item, dict):
                return False
            for key in self.REQUIRED_KPI_KEYS:
                if key not in item:
                    return False
        if self._contains_revenue_metric(kpis):
            return True
        # Agentic fallback: if extraction used alternate wording, ask model to classify
        # whether one KPI is revenue-equivalent (e.g., net sales, turnover).
        return self._llm_deduces_revenue(data)

    def _contains_revenue_metric(self, kpis):
        # type: (List[Dict[str, Any]]) -> bool
        for item in kpis:
            metric = str(item.get("metric", "")).lower()
            for alias in self.REVENUE_ALIASES:
                if alias in metric:
                    return True
        return False

    def _normalize_metric_aliases(self, data):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        kpis = data.get("kpis")
        if not isinstance(kpis, list):
            return data
        for item in kpis:
            if not isinstance(item, dict):
                continue
            metric = str(item.get("metric", ""))
            lower = metric.lower()
            for alias in self.REVENUE_ALIASES:
                if alias in lower:
                    if metric != "Revenue":
                        item.setdefault("raw_metric", metric)
                        item["metric"] = "Revenue"
                    break
        return data

    def _llm_deduces_revenue(self, data):
        # type: (Dict[str, Any]) -> bool
        generator = getattr(self.adapter, "generate_text", None)
        if generator is None:
            return False
        try:
            probe = {
                "kpis": data.get("kpis", []),
                "summary": data.get("summary", {}),
                "guidance": data.get("guidance", []),
            }
            prompt = (
                "Determine if any KPI is revenue-equivalent (revenue, net sales, turnover, top line). "
                "Answer with YES or NO only.\n\nData:\n%s" % json.dumps(probe, ensure_ascii=True)
            )
            decision = (generator(prompt) or "").strip().upper()
            return decision.startswith("YES")
        except Exception:
            logging.exception("Revenue-equivalent KPI inference failed")
            return False

    @staticmethod
    def _build_prompt(raw_text, reflection=False, market="US_SEC"):
        if market == "SEA_LOCAL":
            if PromptTemplate is not None:
                template = (
                    "Extract financial data as JSON with keys: kpis, summary, guidance. "
                    "Previous extraction failed. Identify the source language and currency, translate to English, and normalize monetary values to USD.\n\nText:\n{text}"
                    if reflection
                    else "You are an expert financial analyst. Your task is to process a Southeast Asian financial filing.\n"
                    "1. Identify original language and currency.\n"
                    "2. Translate narrative management guidance into English.\n"
                    "3. Normalize all monetary KPI values to USD.\n"
                    "Return valid JSON only with keys: kpis, summary, guidance. Each KPI requires metric and value.\n\nText:\n{text}"
                )
                return PromptTemplate.from_template(template).format(text=raw_text)
            if reflection:
                return (
                    "Extract financial data as JSON with keys: kpis, summary, guidance. "
                    "Previous extraction failed. Identify the source language and currency, translate to English, and normalize monetary values to USD.\n\n"
                    "Text:\n%s" % raw_text
                )
            return (
                "You are an expert financial analyst. Your task is to process a Southeast Asian financial filing.\n"
                "1. Identify original language and currency.\n"
                "2. Translate narrative management guidance into English.\n"
                "3. Normalize all monetary KPI values to USD.\n"
                "Return valid JSON only with keys: kpis, summary, guidance. Each KPI requires metric and value.\n\nText:\n%s" % raw_text
            )

        if PromptTemplate is not None:
            template = (
                "Extract financial data as JSON with keys: kpis, summary, guidance. "
                "Previous extraction failed. Ensure Revenue (or equivalent such as net sales/turnover) is present when available.\n\nText:\n{text}"
                if reflection
                else "You are a CFA-level financial analyst. Return valid JSON only with keys: kpis, summary, guidance. "
                "Each KPI requires metric and value. Normalize revenue-equivalent metrics (e.g., net sales) to metric='Revenue'.\n\nText:\n{text}"
            )
            return PromptTemplate.from_template(template).format(text=raw_text)
        if reflection:
            return (
                "Extract financial data as JSON with keys: kpis, summary, guidance. "
                "Previous extraction failed. Ensure Revenue (or equivalent such as net sales/turnover) is present when available.\n\n"
                "Text:\n%s" % raw_text
            )
        return (
            "You are a CFA-level financial analyst. Return valid JSON only with keys: kpis, summary, guidance. "
            "Each KPI requires metric and value. Normalize revenue-equivalent metrics (e.g., net sales) to metric='Revenue'.\n\nText:\n%s"
            % raw_text
        )


class SynthesisEngine(object):
    def __init__(self, adapter=None):
        self.adapter = adapter or GeminiAdapter()

    def synthesize(self, question, contexts):
        joined_context = "\n\n".join(contexts)
        prompt = (
            "Answer in markdown, grounded only in provided context. Include a short citations section.\n"
            "Question: %s\n\nContext:\n%s" % (question, joined_context)
        )
        text = self.adapter.generate_text(prompt)
        if text.strip():
            return text
        return "### Answer\nInsufficient context to provide a grounded response."


def safe_json_extract(text):
    text = text.strip()
    for candidate in build_json_candidates(text):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    decoder = json.JSONDecoder()
    start_positions = [idx for idx, char in enumerate(text) if char == "{"][:20]
    for start in start_positions:
        try:
            parsed, _ = decoder.raw_decode(text[start:])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    logging.exception("Failed to parse JSON from model output")
    return {}


def dedupe_strings(values):
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def build_json_candidates(text):
    candidates = [text]
    fenced = re.findall(r"```json\\s*(.*?)\\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)

    non_greedy = re.findall(r"\\{.*?\\}", text, flags=re.DOTALL)
    for snippet in non_greedy:
        if ":" in snippet:
            candidates.append(snippet)
    return dedupe_strings(candidates)
