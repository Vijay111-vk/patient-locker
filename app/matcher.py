"""Decide, per query point, whether the patient's locker already answers it or the patient must send
something new. The goal is twofold: never ask for what we already hold, never skip what is missing."""
import json
import logging
import re

from . import llm, taxonomy
from .config import settings
from .privacy import redact_identifiers

log = logging.getLogger(__name__)

ITEMISED_ASK_RE = re.compile(r"itemi[sz]ed|break\s*-?\s*up|detailed bill|bill\s+details", re.I)
PREV_POLICY_ASK_RE = re.compile(r"(first|previous|earlier|old|prior|last)\s+(year|years|policy|policies)|"
                                r"continuity|portability|since inception|renewal history", re.I)
ITEMISED_DOC_RE = re.compile(r"itemi[sz]ed|break\s*-?\s*up|room\s+(?:rent|charges)|nursing\s+charges|"
                             r"investigation\s+charges|pharmacy\s+charges|consumables", re.I)


def _doc_view(d) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "name": d.original_name, "summary": d.summary or "",
            "key_facts": d.key_facts or {}, "text": d.extracted_text or ""}


def _clean_request(text: str) -> str:
    """Turn the insurer's wording into something addressed to the patient."""
    t = text.strip()
    t = re.sub(r"^(?:to proceed further,?|in addition,?|additionally,?|also,?|further,?|further more,?|"
               r"furthermore,?|moreover,?)\s+", "", t, flags=re.I)
    t = re.sub(r"^(kindly|please|you are requested to|request you to|we request you to)\s+", "", t, flags=re.I)
    t = re.sub(r"^(provide|submit|send|furnish|share|forward)\s+(us\s+)?(with\s+)?(the\s+)?", "", t, flags=re.I)
    t = re.sub(r"^(clarify|explain|confirm|mention|specify|state|justify)\s+(?:to us\s+)?", "", t, flags=re.I)
    t = _to_you(t)
    return _sentence_case(t.rstrip(" .;")) or text


def _to_you(t: str) -> str:
    t = re.sub(r"\b(?:the\s+)?(?:patient|insured|proposer|claimant)'s\b", "your", t, flags=re.I)
    t = re.sub(r"\b(?:the\s+)(?:patient|insured|proposer|claimant)\b", "you", t, flags=re.I)
    t = re.sub(r"\byou (?:had|has)\b", "you had", t)
    t = re.sub(r"\byou was\b", "you were", t)
    return t


def _sentence_case(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def match_rules(points: list[dict], docs: list) -> list[dict]:
    views = [_doc_view(d) for d in docs]
    by_type: dict[str, list[dict]] = {}
    for v in views:
        by_type.setdefault(v["doc_type"], []).append(v)

    results = []
    for p in points:
        types = [t for t in p.get("requested_types", []) if t != "other"]
        text = p["insurer_text"]
        res = {"decision": "needed", "matched_document_ids": [], "reason": "", "patient_request": "",
               "patient_reason": ""}
        if not types:
            if re.match(r"^\W*(?:a\s+)?(?:signed\s+|written\s+)?(statement|declaration|undertaking|affidavit)\b", text, re.I):
                rest = re.sub(r"^\W*(?:a\s+)?(?:signed\s+|written\s+)?(?:statement|declaration|undertaking|affidavit)"
                              r"(?:\s+(?:of|from|by)\s+(?:the\s+)?(?:patient|insured|proposer|claimant))?\s*", "",
                              text, flags=re.I)
                res["reason"] = "Needs a statement from the patient; no stored document answers it."
                res["patient_request"] = "A signed note from you " + _to_you(rest).rstrip(" .;")
                res["patient_reason"] = "the insurer has asked for this in your own words"
            elif p.get("kind") == "clarification":
                res["reason"] = "Clarification that only the patient can give; no stored document answers it."
                res["patient_request"] = "Please tell us " + _lower_first(_clean_request(text))
                res["patient_reason"] = "the insurer has asked for this clarification"
            else:
                res["reason"] = "Could not map this request to any document type held in the locker."
                res["patient_request"] = _clean_request(text)
                res["patient_reason"] = "the insurer needs it to process your claim"
            results.append(res)
            continue

        # "certificate stating the date of first diagnosis" is one document, not also past records
        if "certificate" in types and "past_medical_records" in types and not re.search(r"\brecords?\b", text, re.I):
            types.remove("past_medical_records")

        have = [t for t in types if t in by_type]
        missing = [t for t in types if t not in by_type]

        # Attribute check: insurer wants an itemised bill but the bill we hold has no breakup.
        if "final_bill" in have and ITEMISED_ASK_RE.search(text):
            if not any(ITEMISED_DOC_RE.search(v["text"] + " " + v["summary"]) for v in by_type["final_bill"]):
                have.remove("final_bill")
                missing.append("final_bill_itemised")

        # Attribute check: insurer wants earlier years' policies but we only hold the current one.
        if "policy_copy" in have and PREV_POLICY_ASK_RE.search(text) and len(by_type["policy_copy"]) < 2:
            have.remove("policy_copy")
            missing.append("policy_previous")

        matched = [v["id"] for t in have for v in by_type[t]]
        if not missing:
            res.update(decision="available", matched_document_ids=matched,
                       reason="Locker already has: " + ", ".join(taxonomy.label(t) for t in have) + ".")
        else:
            asks, whys = [], []
            for t in missing:
                if t == "final_bill_itemised":
                    asks.append("an itemised final hospital bill that shows the breakup of every charge")
                    whys.append("the insurer needs to see each charge separately")
                elif t == "policy_previous":
                    asks.append("copies of your earlier years' policy documents (from the first year you were insured)")
                    whys.append("the insurer wants to check how long you have been continuously insured")
                else:
                    asks.append(taxonomy.plain(t))
                    whys.append(taxonomy.why(t))
            special = {"final_bill_itemised": "Itemised final bill", "policy_previous": "Earlier years' policy copies"}
            labels = [special.get(t, taxonomy.label(t)) for t in missing]
            res.update(decision="needed", matched_document_ids=matched,
                       reason="Missing from locker: " + ", ".join(labels) + "." +
                              (f" Already held: {', '.join(taxonomy.label(t) for t in have)}." if have else ""),
                       patient_request=_sentence_case("; ".join(asks)),
                       patient_reason=whys[0])
            if p.get("kind") == "clarification":
                res["patient_request"] += ", and please tell us " + _lower_first(_clean_request(text))
        results.append(res)
    return results


SYSTEM = """You are a meticulous health-insurance claims executive in India. You check an insurer's query
points against the documents already in a patient's file. You never ask a patient for something the file
already contains, and you never mark a point as covered unless a specific stored document truly satisfies it.
Return ONLY JSON."""

PROMPT = """Query points raised by the insurer:
{points}

Documents already in the patient's locker:
{inventory}

For EACH query point decide:
- "available": one or more stored documents fully satisfy it. List their ids in matched_document_ids.
- "needed": something must come from the patient (a new document, a corrected/complete version, or an
  explanation only the patient can give).

Be precise about details the insurer asks for. Examples of "needed" even though a similar document exists:
the insurer wants an itemised bill / breakup but the stored bill is a summary only; wants reports for a date
or test not covered; wants the previous year's policy but only the current one is stored; wants a signed or
stamped copy and the stored one is not; wants a certificate from the treating doctor that is not in the file.
Pure clarifications (e.g. "reason for delay in intimation") are "needed" unless a stored document clearly answers them.

Write for the patient in very simple English (no jargon, no insurance terms; explain abbreviations):
- patient_request: exactly what to send/tell, as a short noun phrase or instruction, e.g.
  "Your Aadhaar card or PAN card" or "A note explaining why the hospital was informed late".
  If part of the point is already in the locker, ask ONLY for the missing part.
- patient_reason: why the insurer needs it, one short phrase, e.g. "so the insurer can confirm your identity".
- reason: one sentence for staff explaining the decision, naming the stored document(s) you relied on.
For "available" points leave patient_request and patient_reason empty.

JSON shape:
{{"decisions": [{{"point_index": 0, "decision": "available|needed", "matched_document_ids": [],
                 "reason": "", "patient_request": "", "patient_reason": ""}}]}}"""


def _inventory(docs: list) -> str:
    per_doc = 1500 if len(docs) <= 15 else 600
    items = []
    for d in docs:
        excerpt = (d.extracted_text or "")[:per_doc]
        if settings.REDACT_IDS_FOR_LLM:
            excerpt = redact_identifiers(excerpt)
        items.append({"id": d.id, "type": d.doc_type, "type_label": taxonomy.label(d.doc_type),
                      "file_name": d.original_name, "summary": redact_identifiers(d.summary or ""),
                      "key_facts": d.key_facts or {}, "uploaded": d.uploaded_at.strftime("%Y-%m-%d"),
                      "text_excerpt": excerpt})
    return json.dumps(items, ensure_ascii=False, indent=1) if items else "[] (the locker is empty)"


def match(points: list[dict], docs: list) -> tuple[list[dict], str]:
    """Returns (decisions aligned with points, engine)."""
    rules = match_rules(points, docs)
    if not llm.enabled() or not points:
        return rules, "rules"
    try:
        pts = [{"point_index": i, "ref": p.get("ref"), "insurer_text": p["insurer_text"], "kind": p.get("kind"),
                "likely_document_types": p.get("requested_types", [])} for i, p in enumerate(points)]
        out = llm.complete_json(SYSTEM, PROMPT.format(points=json.dumps(pts, ensure_ascii=False, indent=1),
                                                      inventory=_inventory(docs)), max_tokens=4000)
        by_idx = {int(d.get("point_index", -1)): d for d in out.get("decisions") or [] if str(d.get("point_index", "")).lstrip("-").isdigit()}
        valid_ids = {d.id for d in docs}
        results = []
        for i, p in enumerate(points):
            d = by_idx.get(i)
            if not d:
                results.append(rules[i])  # model skipped this point: fall back for it
                continue
            ids = [int(x) for x in d.get("matched_document_ids") or [] if str(x).isdigit() and int(x) in valid_ids]
            decision = d.get("decision") if d.get("decision") in ("available", "needed") else rules[i]["decision"]
            if decision == "available" and not ids:
                decision = "needed"  # can't claim coverage without naming the document
            req = str(d.get("patient_request") or "").strip()
            why = str(d.get("patient_reason") or "").strip()
            if decision == "needed" and not req:
                req, why = rules[i]["patient_request"], why or rules[i]["patient_reason"]
            results.append({"decision": decision, "matched_document_ids": ids,
                            "reason": str(d.get("reason") or "")[:1000],
                            "patient_request": req[:600] if decision == "needed" else "",
                            "patient_reason": (why or "the insurer needs it to process your claim")[:300]
                            if decision == "needed" else ""})
        return results, "llm"
    except Exception as exc:
        log.warning("LLM matching failed, using rules: %s", exc)
        return rules, "rules"
