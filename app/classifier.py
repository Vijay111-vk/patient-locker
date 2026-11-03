"""Work out what kind of document a locker file is, and pull out key facts."""
import logging
import re
from functools import lru_cache

from . import llm, taxonomy
from .config import settings
from .privacy import redact_identifiers

log = logging.getLogger(__name__)

DATE_RE = re.compile(r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                     r"[a-z]*\.?,?\s+\d{2,4})\b", re.I)
AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I)


@lru_cache(maxsize=2048)
def _kw_regex(kw: str) -> re.Pattern:
    left = r"\b" if kw[0].isalnum() else ""
    right = r"\b" if kw[-1].isalnum() else ""
    return re.compile(left + re.escape(kw) + right, re.I)


def keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if _kw_regex(kw).search(text))


def classify_rules(text: str, filename: str) -> dict:
    body = (text or "")[:20000].lower()
    name = re.sub(r"[_\-.]+", " ", (filename or "").lower())
    scores: dict[str, float] = {}
    for key, meta in taxonomy.DOC_TYPES.items():
        kws = meta["doc_keywords"] + meta["ask_keywords"][:6]
        s = keyword_hits(body, meta["doc_keywords"]) + 3 * keyword_hits(name, kws)
        if s:
            scores[key] = s
    # Strong signals that override noisy keyword counts
    if re.search(r"discharge\s+summary|discharge\s+card", body[:1500]):
        scores["discharge_summary"] = scores.get("discharge_summary", 0) + 6
    if re.search(r"pharmacy|chemist|medical\s+store", body[:800]) and re.search(r"mrp|batch|qty", body):
        scores["pharmacy_bills"] = scores.get("pharmacy_bills", 0) + 5
    if re.search(r"cancel+ed", body) and re.search(r"cheque|ifsc", body):
        scores["cancelled_cheque"] = scores.get("cancelled_cheque", 0) + 6
    if re.search(r"(query|deficiency|requirement)\s+letter|kindly\s+(submit|provide)\s+the\s+following", body):
        scores["query_letter"] = scores.get("query_letter", 0) + 4
    doc_type = max(scores, key=scores.get) if scores else "other"
    return {"doc_type": doc_type, "summary": _summary(text, filename, doc_type), "key_facts": _facts(text)}


def _summary(text: str, filename: str, doc_type: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if len(ln.strip()) > 3]
    head = " / ".join(lines[:4])[:240]
    base = taxonomy.label(doc_type)
    if not text:
        return f"{base} (no readable text; classified from file name '{filename}')"
    return f"{base}: {head}"


def _facts(text: str) -> dict:
    facts: dict = {}
    dates = DATE_RE.findall(text or "")
    if dates:
        facts["dates"] = list(dict.fromkeys(dates))[:6]
    amounts = AMOUNT_RE.findall(text or "")
    if amounts:
        facts["amounts"] = list(dict.fromkeys(amounts))[:6]
    return facts


SYSTEM = """You classify documents stored in an Indian health-insurance claim file.
Return ONLY a JSON object, no prose."""

PROMPT = """Classify this document into exactly one type from this list:
{catalogue}
- query_letter: an insurer/TPA query or deficiency letter

Then summarise what the document actually contains, so a claims agent can later decide whether it answers
an insurer's query WITHOUT opening it. Mention specifics that matter for claims: whose document it is,
dates covered, hospital, whether a bill is itemised / has a breakup, whether it is signed/stamped,
which tests a report covers, what period a policy covers, etc.

File name: {filename}
Text (may be OCR, may be truncated):
<<<
{text}
>>>

JSON shape:
{{"doc_type": "<one key from the list>",
  "summary": "<2-4 sentences, specific>",
  "key_facts": {{"patient_name": "", "document_date": "", "hospital_or_issuer": "", "amount": "",
                 "covers_period": "", "itemised": null, "signed_or_stamped": null, "other": ""}}}}"""


def classify(text: str, filename: str) -> dict:
    """Returns dict(doc_type, summary, key_facts, engine). Summaries never carry ID/account numbers."""
    out = _classify(text, filename)
    out["summary"] = redact_identifiers(out["summary"])
    return out


def _classify(text: str, filename: str) -> dict:
    rules = classify_rules(text, filename)
    if not llm.enabled():
        return {**rules, "engine": "rules"}
    try:
        payload = redact_identifiers(text[:12000]) if settings.REDACT_IDS_FOR_LLM else text[:12000]
        out = llm.complete_json(SYSTEM, PROMPT.format(catalogue=taxonomy.type_catalogue_for_prompt(),
                                                      filename=filename, text=payload or "(no text extracted)"),
                                max_tokens=800)
        doc_type = out.get("doc_type", "")
        if not taxonomy.valid_type(doc_type):
            doc_type = rules["doc_type"]
        facts = {k: v for k, v in (out.get("key_facts") or {}).items() if v not in (None, "", [], {})}
        return {"doc_type": doc_type, "summary": str(out.get("summary") or rules["summary"])[:1500],
                "key_facts": facts or rules["key_facts"], "engine": "llm"}
    except Exception as exc:
        log.warning("LLM classification failed, using rules: %s", exc)
        return {**rules, "engine": "rules"}
