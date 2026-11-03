"""Document types used across the system.

Each type has:
  label         - what staff see in the portal
  plain         - how we name it to a patient (simple language)
  why           - default plain-language reason an insurer asks for it
  doc_keywords  - phrases that suggest a *document* is of this type (classification)
  ask_keywords  - phrases in a *query letter* that mean the insurer wants this type
"""

DOC_TYPES: dict[str, dict] = {
    "kyc": {
        "label": "KYC (Aadhaar / PAN / ID)",
        "plain": "a copy of your ID proof (Aadhaar card or PAN card)",
        "why": "so the insurer can confirm your identity",
        "doc_keywords": ["aadhaar", "aadhar", "unique identification authority", "uidai", "permanent account number",
                         "income tax department", "pan card", "voter id", "election commission", "passport",
                         "driving licence", "driving license", "kyc", "ckyc", "e-kyc"],
        "ask_keywords": ["kyc", "aadhaar", "aadhar", "pan card", "pan copy", "id proof", "identity proof",
                         "photo id", "address proof", "ckyc", "proof of identity"],
    },
    "policy_copy": {
        "label": "Policy copy / health card",
        "plain": "your insurance policy copy or health card (e-card)",
        "why": "so the insurer can check your cover and policy details",
        "doc_keywords": ["policy schedule", "policy number", "sum insured", "policy period", "certificate of insurance",
                         "health card", "e-card", "ecard", "tpa card", "member id", "policy wording", "insured member"],
        "ask_keywords": ["policy copy", "policy document", "health card", "e-card", "ecard", "tpa card",
                         "policy schedule", "previous policy", "portability", "renewal", "first policy",
                         "policy details", "member id card"],
    },
    "discharge_summary": {
        "label": "Discharge summary",
        "plain": "the discharge summary from the hospital",
        "why": "it explains why you were admitted and what treatment you got",
        "doc_keywords": ["discharge summary", "discharge card", "date of discharge", "condition at discharge",
                         "advice on discharge", "course in hospital", "hospital course", "final diagnosis",
                         "discharge advice", "summary of treatment"],
        "ask_keywords": ["discharge summary", "discharge card", "discharge certificate", "detailed discharge",
                         "summary of treatment", "final diagnosis"],
    },
    "final_bill": {
        "label": "Final hospital bill",
        "plain": "the final hospital bill (with the bill breakup)",
        "why": "it shows the full cost of your treatment",
        "doc_keywords": ["final bill", "inpatient bill", "ip bill", "hospital bill", "bill no", "bill number",
                         "net amount", "total amount", "grand total", "amount payable", "bill breakup",
                         "itemized bill", "itemised bill", "room charges", "nursing charges", "tax invoice"],
        "ask_keywords": ["final bill", "hospital bill", "original bill", "bill breakup", "bill break-up",
                         "break up", "breakup", "itemized bill", "itemised bill", "detailed bill", "main bill",
                         "summary bill", "ip bill", "inpatient bill", "invoice"],
    },
    "payment_receipt": {
        "label": "Payment receipts",
        "plain": "the payment receipts for money you paid to the hospital",
        "why": "they show how much you have already paid",
        "doc_keywords": ["receipt", "payment received", "received with thanks", "advance paid", "deposit receipt",
                         "paid by", "mode of payment"],
        "ask_keywords": ["receipt", "payment proof", "proof of payment", "advance receipt", "deposit receipt",
                         "paid receipt", "payment receipt"],
    },
    "investigation_reports": {
        "label": "Investigation reports",
        "plain": "your test reports (blood tests, scans, X-ray, etc.)",
        "why": "they support the diagnosis made by the doctor",
        "doc_keywords": ["laboratory", "lab report", "pathology", "haematology", "hematology", "biochemistry",
                         "radiology", "ultrasound", "usg", "x-ray", "xray", "ct scan", "mri", "ecg", "echo",
                         "histopathology", "biopsy", "reference range", "test name", "specimen", "impression",
                         "investigation report", "cbc", "hemoglobin", "haemoglobin", "culture", "angiography"],
        "ask_keywords": ["investigation", "lab report", "laboratory report", "test report", "reports", "pathology",
                         "radiology", "x-ray", "xray", "ct scan", "mri", "ultrasound", "usg", "ecg", "echo",
                         "histopathology", "biopsy", "blood report", "scan report", "imaging", "films",
                         "diagnostic report", "angiography", "cd of"],
    },
    "consultation_papers": {
        "label": "Consultation papers / prescriptions",
        "plain": "the doctor's consultation papers or prescriptions",
        "why": "they show what the doctor advised before and during treatment",
        "doc_keywords": ["prescription", "rx", "consultation", "opd", "out patient", "outpatient", "chief complaints",
                         "advised", "follow up", "follow-up", "doctor's notes", "referral"],
        "ask_keywords": ["consultation", "prescription", "opd paper", "opd papers", "opd record",
                         "doctor's advice", "advice for admission", "admission advice", "referral letter",
                         "first consultation", "treating doctor's prescription", "pre-hospitalisation consultation",
                         "pre-hospitalization consultation"],
    },
    "pharmacy_bills": {
        "label": "Pharmacy bills",
        "plain": "the pharmacy / medicine bills",
        "why": "they show the cost of medicines bought for your treatment",
        "doc_keywords": ["pharmacy", "chemist", "medical store", "drug license", "drug licence", "batch no",
                         "mrp", "tablet", "tab.", "cap.", "syrup", "injection", "inj.", "qty", "exp."],
        "ask_keywords": ["pharmacy bill", "pharmacy bills", "medicine bill", "medicine bills", "chemist bill",
                         "pharmacy invoice", "drug bill", "medical store bill"],
    },
    "cancelled_cheque": {
        "label": "Cancelled cheque / bank details",
        "plain": "a cancelled cheque (or bank passbook first page) with your name printed",
        "why": "so the claim amount can be paid into your bank account",
        "doc_keywords": ["cancelled", "canceled", "cheque", "check", "ifsc", "a/c no", "account no",
                         "pay to the order", "passbook", "bank statement", "micr"],
        "ask_keywords": ["cancelled cheque", "canceled cheque", "cancel cheque", "bank details", "neft",
                         "bank account", "ifsc", "passbook", "bank mandate", "account details"],
    },
    "claim_form": {
        "label": "Claim form",
        "plain": "the signed claim form",
        "why": "it is the formal request to the insurer to settle your claim",
        "doc_keywords": ["claim form", "part a", "part b", "to be filled by the insured",
                         "to be filled by the hospital", "declaration by the insured", "reimbursement claim"],
        "ask_keywords": ["claim form", "part a", "part b", "signed claim", "duly filled", "duly signed",
                         "reimbursement form"],
    },
    "indoor_case_papers": {
        "label": "Indoor case papers (ICP)",
        "plain": "the indoor case papers (the hospital's daily treatment record of your stay)",
        "why": "they show the day-by-day treatment given during your stay",
        "doc_keywords": ["indoor case", "case sheet", "progress notes", "nursing notes", "treatment chart",
                         "temperature chart", "tpr chart", "vitals chart", "daily notes", "doctor's order sheet",
                         "medication chart", "icp"],
        "ask_keywords": ["indoor case paper", "indoor case papers", "icp", "case sheet", "case papers",
                         "progress notes", "nursing notes", "treatment chart", "temperature chart", "tpr chart",
                         "vitals chart", "daily notes", "medication chart", "complete case papers"],
    },
    "operation_notes": {
        "label": "Operation / procedure notes",
        "plain": "the operation notes (surgery details) from the hospital",
        "why": "they describe the surgery or procedure that was done",
        "doc_keywords": ["operation notes", "operative notes", "ot notes", "procedure notes", "surgeon",
                         "anaesthesia", "anesthesia", "incision", "intra-operative", "post-operative",
                         "procedure performed"],
        "ask_keywords": ["operation notes", "operative notes", "ot notes", "surgery notes", "procedure notes",
                         "anaesthesia notes", "anesthesia notes", "operation theatre"],
    },
    "implant_invoice": {
        "label": "Implant invoice / sticker",
        "plain": "the implant invoice and implant sticker (barcode label) from the hospital",
        "why": "they confirm the implant used and its cost",
        "doc_keywords": ["implant", "stent", "lens", "iol", "prosthesis", "sticker", "barcode", "lot no"],
        "ask_keywords": ["implant", "stent", "sticker", "barcode", "pouch", "iol", "lens invoice", "prosthesis"],
    },
    "past_medical_records": {
        "label": "Past treatment records",
        "plain": "records of any earlier treatment for this illness (old prescriptions, reports, discharge papers)",
        "why": "the insurer wants to know when the illness first started",
        "doc_keywords": ["previous admission", "past history", "old records", "history of", "previous treatment"],
        "ask_keywords": ["past history", "previous treatment", "previous records", "old records",
                         "prior treatment", "earlier treatment", "first diagnosed", "first diagnosis", "since when",
                         "duration of ailment", "duration of the ailment", "duration of illness", "pre-existing",
                         "past medical", "past treatment", "previous admission", "history of"],
    },
    "accident_records": {
        "label": "FIR / MLC (accident)",
        "plain": "the FIR or MLC copy (police / medico-legal papers about the accident)",
        "why": "the insurer needs them for accident-related claims",
        "doc_keywords": ["first information report", "fir no", "police station", "medico legal", "medico-legal",
                         "mlc no", "mlc"],
        "ask_keywords": ["fir", "mlc", "medico legal", "medico-legal", "police report", "panchnama",
                         "accident report", "first information report"],
    },
    "certificate": {
        "label": "Doctor's certificate / letter",
        "plain": "a certificate or letter from your treating doctor",
        "why": "the insurer needs the doctor to confirm some details in writing",
        "doc_keywords": ["to whom it may concern", "certified that", "certificate", "this is to certify"],
        "ask_keywords": ["certificate from", "treating doctor certificate", "doctor's certificate",
                         "letter from treating doctor", "certificate stating", "fitness certificate",
                         "duly certified", "certificate of"],
    },
    "query_letter": {
        "label": "Insurer query letter",
        "plain": "insurer query letter",
        "why": "",
        "doc_keywords": ["query letter", "deficiency letter", "requirement letter", "we require the following",
                         "kindly submit the following", "claim is under process", "pending documents"],
        "ask_keywords": [],
    },
    "other": {
        "label": "Other document",
        "plain": "the requested document",
        "why": "the insurer needs it to process your claim",
        "doc_keywords": [],
        "ask_keywords": [],
    },
}

ASKABLE_TYPES = [k for k in DOC_TYPES if k not in ("query_letter",)]


def label(doc_type: str) -> str:
    return DOC_TYPES.get(doc_type, {}).get("label", doc_type.replace("_", " ").title())


def plain(doc_type: str) -> str:
    return DOC_TYPES.get(doc_type, DOC_TYPES["other"])["plain"]


def why(doc_type: str) -> str:
    return DOC_TYPES.get(doc_type, DOC_TYPES["other"])["why"]


def valid_type(doc_type: str) -> bool:
    return doc_type in DOC_TYPES


def type_catalogue_for_prompt() -> str:
    lines = []
    for key, meta in DOC_TYPES.items():
        if key == "query_letter":
            continue
        lines.append(f"- {key}: {meta['label']}")
    return "\n".join(lines)
