"""Exercise the AI code paths with a fake model (no network)."""
from types import SimpleNamespace

from app import classifier, llm, matcher, query_parser


def doc(i, t):
    return SimpleNamespace(id=i, doc_type=t, original_name=f"{t}.pdf", summary="s", key_facts={}, extracted_text="x",
                           uploaded_at=__import__("datetime").datetime(2026, 9, 1))


def test_llm_parse_and_match(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    calls = []

    def fake(system, user, max_tokens=0):
        calls.append(user)
        if "list EVERY separate thing" in user:
            return {"insurer_name": "ACME Health", "claim_reference": "[ID-NUMBER]", "deadline": "",
                    "points": [{"ref": "1a", "insurer_text": "KYC of insured", "kind": "document",
                                "requested_types": ["kyc", "bogus_type"]},
                               {"ref": "1b", "insurer_text": "ICP", "kind": "document",
                                "requested_types": ["indoor_case_papers"]},
                               {"ref": "2", "insurer_text": "Reason for delay", "kind": "clarification",
                                "requested_types": []}]}
        return {"decisions": [
            {"point_index": 0, "decision": "available", "matched_document_ids": [7]},
            {"point_index": 1, "decision": "available", "matched_document_ids": []},  # no evidence -> needed
            # point 2 omitted -> rules fallback for that point
        ]}

    monkeypatch.setattr(llm, "complete_json", fake)
    parsed = query_parser.parse("Claim No: CLM-1234567\nletter text")
    assert parsed["engine"] == "llm"
    assert parsed["points"][0]["requested_types"] == ["kyc"]  # invalid type dropped
    out, engine = matcher.match(parsed["points"], [doc(7, "kyc")])
    assert engine == "llm"
    assert out[0]["decision"] == "available" and out[0]["matched_document_ids"] == [7]
    assert out[1]["decision"] == "needed" and out[1]["patient_request"]  # filled from rules
    assert out[2]["decision"] == "needed"


def test_llm_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)

    def boom(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "complete_json", boom)
    assert query_parser.parse("1. Provide cancelled cheque.")["engine"] == "rules"
    assert classifier.classify("Discharge Summary\nDate of discharge", "a.pdf")["engine"] == "rules"


def test_text_sent_to_llm_is_redacted(monkeypatch):
    monkeypatch.setattr(llm, "enabled", lambda: True)
    seen = {}

    def capture(system, user, max_tokens=0):
        seen["user"] = user
        return {"doc_type": "kyc", "summary": "Aadhaar 1234 5678 9012", "key_facts": {}}

    monkeypatch.setattr(llm, "complete_json", capture)
    out = classifier.classify("Aadhaar No: 1234 5678 9012 PAN ABCDE1234F phone 9876543210", "id.pdf")
    assert "1234 5678 9012" not in seen["user"] and "ABCDE1234F" not in seen["user"]
    assert "9876543210" not in seen["user"]
    assert "1234 5678 9012" not in out["summary"]


def test_parse_json_handles_fences():
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
