from types import SimpleNamespace

from app import matcher, query_parser
from app.messaging import friendly_deadline

LETTER = """Star Shield Health Insurance
Claim No: CLM-2026-555001
Dear Sir,
We require the following:
1. Final hospital bill with detailed bill breakup (itemised).
2. Indoor case papers including nursing notes.
3. Copy of KYC documents (Aadhaar / PAN).
4. Clarify the reason for delay in intimation.
Kindly submit the above within 15 days, failing which the claim will be closed.
Regards"""


def doc(i, t, text=""):
    return SimpleNamespace(id=i, doc_type=t, original_name=f"{t}.pdf", summary="", key_facts={}, extracted_text=text)


def test_parse_points_and_header():
    out = query_parser.parse_rules(LETTER)
    assert out["claim_reference"] == "CLM-2026-555001"
    assert out["insurer_name"] == "Star Shield Health Insurance"
    assert out["deadline"].startswith("within 15 days")
    assert [p["ref"] for p in out["points"]] == ["1", "2", "3", "4"]
    assert "final_bill" in out["points"][0]["requested_types"]
    assert out["points"][1]["requested_types"] == ["indoor_case_papers"]
    assert out["points"][2]["requested_types"] == ["kyc"]
    assert out["points"][3]["kind"] == "clarification"


def test_parse_prose_letter():
    text = ("We have reviewed the claim. Please provide the past treatment records for diabetes. "
            "Also send a certificate from the treating doctor. Kindly explain the reason for delay in intimation.")
    pts = query_parser.parse_rules(text)["points"]
    assert len(pts) == 3


def test_never_asks_for_what_is_in_locker():
    pts = query_parser.parse_rules(LETTER)["points"]
    docs = [doc(1, "kyc"), doc(2, "final_bill", "Bill breakup: Room charges Rs 1000; Nursing charges Rs 500")]
    res = matcher.match_rules(pts, docs)
    assert res[0]["decision"] == "available" and res[0]["matched_document_ids"] == [2]
    assert res[1]["decision"] == "needed"
    assert res[2]["decision"] == "available" and res[2]["matched_document_ids"] == [1]
    assert res[3]["decision"] == "needed"
    assert res[3]["patient_request"].startswith("Please tell us")


def test_summary_bill_is_not_enough_for_itemised_request():
    pts = query_parser.parse_rules(LETTER)["points"]
    res = matcher.match_rules(pts, [doc(2, "final_bill", "Net amount payable Rs 1,48,500")])
    assert res[0]["decision"] == "needed"
    assert "itemised" in res[0]["patient_request"].lower()


def test_patient_wording_addresses_patient():
    pts = [{"ref": "1", "insurer_text": "Clarify whether the patient had any similar complaints in the past.",
            "kind": "clarification", "requested_types": []}]
    req = matcher.match_rules(pts, [])[0]["patient_request"]
    assert req == "Please tell us whether you had any similar complaints in the past"


def test_deadline_phrasing():
    assert friendly_deadline("") == "as soon as possible"
    assert friendly_deadline("on or before 30/10/2026") == "by 30/10/2026"
    assert friendly_deadline("within 15 days of receipt of this letter") == "within 15 days of the insurer's letter"
