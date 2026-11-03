"""Read an insurer query letter and split it into separate query points."""
import logging
import re

from . import llm, taxonomy
from .classifier import keyword_hits
from .config import settings
from .privacy import redact_identifiers

log = logging.getLogger(__name__)

MARKER_RE = re.compile(
    r"^\s*(?:"
    r"\(?(?P<num>\d{1,2})[.)\]:]"            # 1.  1)  (1)
    r"|\(?(?P<alpha>[a-hA-H])[.)\]]"          # a)  (b)  C.
    r"|\(?(?P<roman>(?:i{1,3}|iv|v|vi{1,3}|ix|x))[.)\]]"  # i)  (iv)
    r"|(?P<bullet>[•▪➢►●◦\-\*–]|o(?=\s))"     # bullets
    r")\s+(?P<rest>\S.*)$", re.I)

REQUEST_RE = re.compile(
    r"\b(provide|submit|send|furnish|share|forward|clarif\w*|explain|justif\w*|confirm|mention|specify|"
    r"require[ds]?|need(?:ed)?|copy|copies|attach|produce|certificate|report|reports|bill|bills|records?|"
    r"papers?|details?|history|reason|proof|documents?|statement|declaration|sticker|invoice|cheque|card)\b", re.I)

BOILERPLATE_RE = re.compile(
    r"(claim (?:will|shall|may) be (?:closed|repudiated|rejected|denied)|failing which|"
    r"without prejudice|quote (?:the|your) claim|for any (?:further )?(?:queries|clarification)|"
    r"assuring you|thanking you|yours (?:sincerely|faithfully)|this is a system generated|"
    r"please ignore if already|reminder \d|toll[- ]free|customer care|do not reply|disclaimer|"
    r"\bthe above\b|within \d+ (?:working )?days|at the earliest|"
    r"^(?:sub|subject|ref|re)\s*[:.])", re.I)

KV_RE = re.compile(r"^(claim\s*(no|number|id)|policy\s*(no|number)|patient\s*name|insured\s*name|"
                   r"name of (?:the )?(?:patient|insured)|date of (?:admission|discharge)|hospital|"
                   r"uhid|ip\s*no|member\s*id|tpa|insurer|amount)\b.{0,6}[:\-]", re.I)

CLARIFY_RE = re.compile(r"\b(clarif\w*|explain|justif\w*|confirm|reason|why|how|when|whether|since when|"
                        r"mention|specify|details of|nature of|duration|history)\b", re.I)
DOC_WORD_RE = re.compile(r"\b(copy|copies|report|reports|bill|bills|records?|papers?|certificate|card|"
                         r"summary|cheque|invoice|sticker|form|prescription|notes|chart|film|cd)\b", re.I)

CLAIM_REF_RE = re.compile(r"claim\s*(?:no|number|id|ref(?:erence)?)\.?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", re.I)
DEADLINE_RE = re.compile(r"(within\s+\d+\s+(?:working\s+)?days(?:\s+(?:of|from)\s+(?:the\s+)?(?:date of\s+)?"
                         r"(?:this|receipt of this)\s+(?:letter|mail|communication))?|"
                         r"(?:on or before|not later than|latest by|by)\s+\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})", re.I)


def detect_requested_types(text: str) -> list[str]:
    found = []
    low = text.lower()
    for key, meta in taxonomy.DOC_TYPES.items():
        if meta["ask_keywords"] and keyword_hits(low, meta["ask_keywords"]):
            found.append(key)
    if not found and re.search(r"\bbills?\b", low):
        found.append("final_bill")
    # "Pharmacy bills" should not also imply the final hospital bill
    if "pharmacy_bills" in found and "final_bill" in found and not re.search(
            r"(final|hospital|ip|inpatient|main)\s+bill|break\s*-?\s*up|itemi[sz]ed", low):
        found.remove("final_bill")
    return found


def _header_info(text: str) -> dict:
    info = {"insurer_name": "", "claim_reference": "", "deadline": ""}
    for line in text.splitlines()[:15]:
        s = line.strip()
        if re.search(r"\b(insurance|assurance|tpa|health\s*insurance|general insurance)\b", s, re.I) and len(s) < 120:
            name = re.split(r"\s+[-–|]\s+", s)[0] if re.search(r"insurance|assurance|health", re.split(r"\s+[-–|]\s+", s)[0], re.I) else s
            info["insurer_name"] = name.strip(" ,.-")
            break
    m = CLAIM_REF_RE.search(text)
    if m:
        info["claim_reference"] = m.group(1).strip(" .,")
    m = DEADLINE_RE.search(text)
    if m:
        info["deadline"] = m.group(1).strip()
    return info


def _list_items(text: str) -> list[tuple[str, str]]:
    items: list[list[str]] = []
    refs: list[str] = []
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = MARKER_RE.match(line)
        if m:
            ref = m.group("num") or m.group("alpha") or m.group("roman") or "•"
            current = [m.group("rest").strip()]
            items.append(current)
            refs.append(ref)
        elif current is not None and line.strip():
            if BOILERPLATE_RE.search(line) or re.match(r"^\s*(note|regards|thanks|thank you|thanking|yours|warm regards)\b", line, re.I):
                current = None
            else:
                current.append(line.strip())
        elif not line.strip():
            current = None
    return [(r, " ".join(parts)) for r, parts in zip(refs, items)]


def _sentence_items(text: str) -> list[tuple[str, str]]:
    body = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[.;?])\s+(?=[A-Z(])", body)
    out = []
    for s in sentences:
        if REQUEST_RE.search(s) and re.search(r"\b(provide|submit|send|furnish|share|clarif|explain|confirm|"
                                              r"require|need|mention|specify|justif)", s, re.I):
            out.append((str(len(out) + 1), s.strip()))
    return out


def _is_point(text: str) -> bool:
    if len(text) < 6 or BOILERPLATE_RE.search(text):
        return False
    if KV_RE.match(text) and not re.search(r"\b(provide|submit|send|clarif|copy|explain)\b", text, re.I):
        return False
    return bool(REQUEST_RE.search(text) or detect_requested_types(text))


def parse_rules(text: str) -> dict:
    info = _header_info(text)
    items = [(r, t) for r, t in _list_items(text) if _is_point(t)]
    if not items:
        items = [(r, t) for r, t in _sentence_items(text) if _is_point(t)]
    points = []
    for i, (ref, t) in enumerate(items, 1):
        types = detect_requested_types(t)
        kind = "clarification" if CLARIFY_RE.search(t) and not (DOC_WORD_RE.search(t) or types) else "document"
        points.append({"ref": ref if ref != "•" else str(i), "insurer_text": t.strip(),
                       "summary": t.strip()[:200], "kind": kind, "requested_types": types})
    return {**info, "points": points}


SYSTEM = """You are a senior health-insurance claims executive in India. You read insurer / TPA query
(deficiency) letters and break them into individual requirements. Return ONLY JSON."""

PROMPT = """Read this insurer query letter and list EVERY separate thing the insurer is asking for.

Rules:
- One point per distinct requirement. If one numbered item asks for two different things
  (e.g. "final bill with breakup and pharmacy bills"), split it into sub-points with refs like "3a", "3b".
- Keep the insurer's own numbering in "ref" where it exists.
- Include clarifications/explanations the insurer wants, not only documents.
- Ignore letter boilerplate: addresses, greetings, warnings like "claim will be closed if not received",
  signatures, disclaimers, and header fields like claim number / patient name.
- "insurer_text" must be the insurer's wording for that point (trimmed).
- "summary" is a short neutral restatement for staff.
- "kind" is "document" if they want a document, "clarification" if they want information/explanation.
- "requested_types" lists the document types (keys below) that would satisfy the point. Use [] for a pure
  clarification that no stored document could answer. Use "other" if nothing fits.

Document type keys:
{catalogue}

Letter:
<<<
{text}
>>>

JSON shape:
{{"insurer_name": "", "claim_reference": "", "deadline": "<as written, or empty>",
  "points": [{{"ref": "1", "insurer_text": "", "summary": "", "kind": "document|clarification",
              "requested_types": ["..."]}}]}}"""


def parse(text: str) -> dict:
    """Returns dict(insurer_name, claim_reference, deadline, points[], engine)."""
    rules = parse_rules(text)
    if not llm.enabled():
        return {**rules, "engine": "rules"}
    try:
        payload = redact_identifiers(text[:15000]) if settings.REDACT_IDS_FOR_LLM else text[:15000]
        out = llm.complete_json(SYSTEM, PROMPT.format(catalogue=taxonomy.type_catalogue_for_prompt(),
                                                      text=payload), max_tokens=3000)
        points = []
        for i, p in enumerate(out.get("points") or [], 1):
            t = str(p.get("insurer_text") or p.get("summary") or "").strip()
            if not t:
                continue
            types = [x for x in (p.get("requested_types") or []) if taxonomy.valid_type(x) and x != "query_letter"]
            kind = p.get("kind") if p.get("kind") in ("document", "clarification") else "document"
            points.append({"ref": str(p.get("ref") or i)[:20], "insurer_text": t,
                           "summary": str(p.get("summary") or t)[:500], "kind": kind, "requested_types": types})
        if not points:
            raise llm.LLMError("No points returned")
        return {"insurer_name": out.get("insurer_name") or rules["insurer_name"],
                "claim_reference": out.get("claim_reference") or rules["claim_reference"],
                "deadline": out.get("deadline") or rules["deadline"],
                "points": points, "engine": "llm"}
    except Exception as exc:
        log.warning("LLM parsing failed, using rules: %s", exc)
        return {**rules, "engine": "rules"}
