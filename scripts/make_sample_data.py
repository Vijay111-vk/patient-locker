"""Generate demo data: 10 patient profiles with document PDFs, plus insurer query letters.

    python scripts/make_sample_data.py

Writes sample_data/profiles.json, sample_data/patients/<PATIENT_ID>/*.pdf and
sample_data/query_letters/<PATIENT_ID>_*.pdf. All people, numbers and companies are fictitious.
Replace this folder with the real sample profiles in the same layout and run scripts/seed.py.
"""
import json
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent / "sample_data"

PATIENTS = [
    dict(patient_code="PT-0001", full_name="Rajesh Kumar Sharma", phone="+919810000001", email="rajesh.sharma@example.com",
         dob="12/03/1978", gender="Male", hospital="Sunrise Multispeciality Hospital, Jaipur", insurer="Star Shield Health Insurance",
         policy_number="SSH/2025/448812", claim_number="CLM-2026-100231", admission_date="02/09/2026",
         discharge_date="06/09/2026", diagnosis="Acute appendicitis; laparoscopic appendectomy"),
    dict(patient_code="PT-0002", full_name="Priya Mehta", phone="+919810000002", email="priya.mehta@example.com",
         dob="25/07/1990", gender="Female", hospital="City Care Hospital, Ahmedabad", insurer="Nirmal General Insurance",
         policy_number="NGI-HL-77120", claim_number="CLM-2026-100245", admission_date="14/08/2026",
         discharge_date="19/08/2026", diagnosis="Dengue fever with thrombocytopenia"),
    dict(patient_code="PT-0003", full_name="Mohammed Irfan", phone="+919810000003", email="irfan.m@example.com",
         dob="03/01/1956", gender="Male", hospital="Vision Eye Institute, Lucknow", insurer="Bharat Suraksha Health",
         policy_number="BSH/IND/556301", claim_number="CLM-2026-100250", admission_date="21/08/2026",
         discharge_date="21/08/2026", diagnosis="Senile cataract right eye; phaco with IOL"),
    dict(patient_code="PT-0004", full_name="Sunita Devi", phone="+919810000004", email="sunita.devi@example.com",
         dob="18/11/1961", gender="Female", hospital="OrthoPlus Hospital, Indore", insurer="Star Shield Health Insurance",
         policy_number="SSH/2024/301177", claim_number="CLM-2026-100262", admission_date="05/09/2026",
         discharge_date="11/09/2026", diagnosis="Osteoarthritis left knee; total knee replacement"),
    dict(patient_code="PT-0005", full_name="Arjun Reddy", phone="+919810000005", email="arjun.reddy@example.com",
         dob="09/06/1995", gender="Male", hospital="Apex Trauma Centre, Hyderabad", insurer="Nirmal General Insurance",
         policy_number="NGI-HL-80455", claim_number="CLM-2026-100270", admission_date="28/08/2026",
         discharge_date="03/09/2026", diagnosis="Fracture shaft of right femur (road traffic accident); ORIF"),
    dict(patient_code="PT-0006", full_name="Kavita Joshi", phone="+919810000006", email="kavita.joshi@example.com",
         dob="30/04/1969", gender="Female", hospital="Lifeline Hospital, Pune", insurer="Bharat Suraksha Health",
         policy_number="BSH/IND/612090", claim_number="CLM-2026-100288", admission_date="10/09/2026",
         discharge_date="14/09/2026", diagnosis="Diabetic foot infection; Type 2 diabetes mellitus"),
    dict(patient_code="PT-0007", full_name="Vikram Singh", phone="+919810000007", email="vikram.singh@example.com",
         dob="14/02/1964", gender="Male", hospital="HeartCare Institute, Delhi", insurer="Star Shield Health Insurance",
         policy_number="SSH/2025/510034", claim_number="CLM-2026-100301", admission_date="15/09/2026",
         discharge_date="18/09/2026", diagnosis="Acute coronary syndrome; PTCA with one drug-eluting stent"),
    dict(patient_code="PT-0008", full_name="Anjali Nair", phone="+919810000008", email="anjali.nair@example.com",
         dob="05/10/1994", gender="Female", hospital="Motherhood Women's Hospital, Kochi", insurer="Nirmal General Insurance",
         policy_number="NGI-HL-81902", claim_number="CLM-2026-100315", admission_date="20/09/2026",
         discharge_date="23/09/2026", diagnosis="Term pregnancy; lower segment caesarean section"),
    dict(patient_code="PT-0009", full_name="Suresh Patel", phone="+919810000009", email="suresh.patel@example.com",
         dob="22/08/1958", gender="Male", hospital="Shree Krishna Hospital, Surat", insurer="Bharat Suraksha Health",
         policy_number="BSH/IND/598812", claim_number="CLM-2026-100322", admission_date="24/09/2026",
         discharge_date="29/09/2026", diagnosis="Community acquired pneumonia"),
    dict(patient_code="PT-0010", full_name="Fatima Shaikh", phone="+919810000010", email="fatima.shaikh@example.com",
         dob="11/12/1985", gender="Female", hospital="Noor Hospital, Mumbai", insurer="Star Shield Health Insurance",
         policy_number="SSH/2025/522901", claim_number="CLM-2026-100340", admission_date="01/10/2026",
         discharge_date="04/10/2026", diagnosis="Symptomatic cholelithiasis; laparoscopic cholecystectomy"),
]

# Which documents each sample locker holds (the gaps are deliberate, so matching can be tested)
LOCKERS = {
    "PT-0001": ["aadhaar", "policy", "discharge", "bill_summary", "lab", "usg", "consultation", "pharmacy", "cheque"],
    "PT-0002": ["pan", "health_card", "discharge", "bill_itemised", "lab"],
    "PT-0003": ["aadhaar", "policy", "discharge", "bill_itemised", "implant"],
    "PT-0004": ["aadhaar", "policy", "discharge", "bill_itemised", "ot_notes", "implant", "consultation"],
    "PT-0005": ["discharge", "bill_summary", "xray"],
    "PT-0006": ["aadhaar", "policy", "discharge", "bill_itemised", "lab", "consultation", "pharmacy", "cheque"],
    "PT-0007": ["aadhaar", "policy", "discharge", "angio", "bill_itemised", "implant", "cheque"],
    "PT-0008": ["health_card", "discharge", "bill_summary"],
    "PT-0009": ["aadhaar", "policy", "discharge", "bill_itemised", "lab", "xray", "consultation", "pharmacy", "cheque"],
    "PT-0010": ["aadhaar", "discharge", "bill_itemised", "usg", "pharmacy"],
}


def pdf(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, title)
    y -= 28
    c.setFont("Helvetica", 10.5)
    for line in lines:
        for chunk in _wrap(line, 95):
            if y < 60:
                c.showPage()
                c.setFont("Helvetica", 10.5)
                y = h - 60
            c.drawString(50, y, chunk)
            y -= 15
    c.save()


def _wrap(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    words, out, cur = text.split(" "), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    out.append(cur)
    return out


def docs_for(p: dict) -> dict[str, tuple[str, str, list[str]]]:
    n, hosp = p["full_name"], p["hospital"]
    adm, dis = p["admission_date"], p["discharge_date"]
    return {
        "aadhaar": ("aadhaar_card.pdf", "Government of India - Aadhaar",
                    ["Unique Identification Authority of India", f"Name: {n}", f"DOB: {p['dob']}",
                     f"Gender: {p['gender']}", "Aadhaar No: 4821 7730 19" + p["patient_code"][-2:],
                     "Mera Aadhaar, Meri Pehchaan"]),
        "pan": ("pan_card.pdf", "Income Tax Department - Govt. of India",
                ["Permanent Account Number Card", f"Name: {n.upper()}", f"Date of Birth: {p['dob']}",
                 "PAN: ABCPM" + p["patient_code"][-4:] + "K"]),
        "policy": ("policy_schedule.pdf", f"{p['insurer']} - Policy Schedule",
                   [f"Policy Number: {p['policy_number']}", "Product: Family Health Optima", f"Proposer / Insured: {n}",
                    "Policy Period: 15/06/2026 to 14/06/2027", "Sum Insured: Rs. 5,00,000", "Policy inception year: 2022",
                    "Certificate of Insurance issued subject to policy wording."]),
        "health_card": ("health_ecard.pdf", f"{p['insurer']} - Health Card",
                        ["E-card / TPA card", f"Member Name: {n}", "Member ID: MID" + p["patient_code"][-4:],
                         f"Policy Number: {p['policy_number']}", "Valid till: 14/06/2027"]),
        "discharge": ("discharge_summary.pdf", f"{hosp} - Discharge Summary",
                      [f"Patient Name: {n}", f"Date of Admission: {adm}", f"Date of Discharge: {dis}",
                       f"Final Diagnosis: {p['diagnosis']}", "Chief complaints: as per case record.",
                       "Course in hospital: Patient was admitted, investigated and treated. Recovered uneventfully.",
                       "Condition at discharge: Stable.", "Advice on discharge: Medicines as prescribed; review after 7 days.",
                       "Signed: Treating Consultant (stamp)"]),
        "bill_summary": ("final_bill.pdf", f"{hosp} - Final Bill",
                         [f"Patient: {n}", "IP Bill No: IPB/2026/" + p["patient_code"][-4:],
                          f"Admission: {adm}  Discharge: {dis}", "Hospitalisation package charges",
                          "Net Amount Payable: Rs. 1,48,500.00", "Amount paid in full. Thank you."]),
        "bill_itemised": ("final_bill_itemised.pdf", f"{hosp} - Final Inpatient Bill (Itemised)",
                          [f"Patient: {n}", "IP Bill No: IPB/2026/" + p["patient_code"][-4:],
                           f"Admission: {adm}  Discharge: {dis}", "Bill breakup:",
                           "Room charges (4 days)  Rs. 16,000", "Nursing charges  Rs. 6,000",
                           "Investigation charges  Rs. 12,400", "Pharmacy charges  Rs. 21,350",
                           "Consumables  Rs. 8,900", "Surgeon / procedure charges  Rs. 65,000",
                           "Grand Total: Rs. 1,29,650.00"]),
        "lab": ("lab_reports.pdf", f"{hosp} - Laboratory Report",
                [f"Patient: {n}", f"Sample date: {adm}", "Haematology - Complete Blood Count (CBC)",
                 "Haemoglobin 12.1 g/dL (Reference range 12-16)", "Platelet count 1.1 lakh/cumm", "Biochemistry - LFT, KFT",
                 "Impression: as per clinical correlation."]),
        "usg": ("usg_abdomen.pdf", "Radiology - Ultrasound (USG) Abdomen",
                [f"Patient: {n}", f"Date: {adm}", "Findings: as described.", "Impression: findings consistent with clinical diagnosis."]),
        "xray": ("xray_report.pdf", "Radiology - X-Ray Report",
                 [f"Patient: {n}", f"Date: {adm}", "X-ray: AP and lateral views.", "Impression: as per clinical diagnosis."]),
        "angio": ("coronary_angiography.pdf", "Cath Lab - Coronary Angiography Report",
                  [f"Patient: {n}", f"Date: {adm}", "Angiography: 90% stenosis proximal LAD.",
                   "Impression: single vessel disease; PTCA advised."]),
        "consultation": ("opd_prescription.pdf", f"{hosp} - OPD Consultation",
                         [f"Patient: {n}", f"Date: {adm}", "Chief complaints: as noted.", "Advised: admission for management.",
                          "Rx: as written. Follow up after discharge."]),
        "pharmacy": ("pharmacy_bills.pdf", "Hospital Pharmacy - Tax Invoice",
                     [f"Patient: {n}", "Drug Licence No: 20B/21B-4471", "Tab. Paracetamol 650 mg  Qty 10  MRP 30.00  Batch PX22",
                      "Inj. Ceftriaxone 1g  Qty 6  MRP 420.00", "Total: Rs. 2,870.00"]),
        "cheque": ("cancelled_cheque.pdf", "Cancelled Cheque",
                   ["State Bank of India", f"Pay to: {n}", "A/c No: 3012004455" + p["patient_code"][-2:],
                    "IFSC: SBIN0001234", "CANCELLED"]),
        "ot_notes": ("operation_notes.pdf", f"{hosp} - Operation Notes",
                     [f"Patient: {n}", f"Date: {adm}", "Procedure performed: as per diagnosis.", "Anaesthesia: spinal.",
                      "Surgeon: Dr. A. Kulkarni", "Post-operative course: stable."]),
        "implant": ("implant_invoice.pdf", "Implant Invoice and Sticker",
                    [f"Patient: {n}", "Implant: as used in procedure", "Lot No: LT-88213  Barcode sticker attached",
                     "Amount: Rs. 42,000"]),
    }


QUERY_LETTERS = {
    "PT-0001": ("Star Shield Health Insurance - Claims Department", [
        "Date: 10/09/2026",
        "Claim No: CLM-2026-100231   Patient Name: Rajesh Kumar Sharma",
        "Sub: Query / deficiency letter for reimbursement claim",
        "Dear Sir/Madam,",
        "With reference to the above claim, we require the following documents / clarifications to process the claim:",
        "1. Final hospital bill with detailed bill breakup (itemised).",
        "2. Indoor case papers including nursing notes and temperature chart.",
        "3. Operation notes signed by the operating surgeon.",
        "4. Copy of KYC documents of the proposer (Aadhaar / PAN).",
        "5. Cancelled cheque with the name of the proposer printed.",
        "Kindly submit the above within 15 days of receipt of this letter, failing which the claim will be closed.",
        "Yours faithfully, Claims Team"]),
    "PT-0002": ("Nirmal General Insurance Co. Ltd.", [
        "Claim Number: CLM-2026-100245",
        "Insured: Priya Mehta",
        "Kindly submit the following:",
        "a) Pharmacy bills along with the doctor's prescriptions for the medicines purchased.",
        "b) First consultation paper with the treating doctor's advice for admission.",
        "c) Cancelled cheque or bank passbook copy for NEFT.",
        "d) Platelet count reports for all days of hospitalisation.",
        "e) Clarify whether the patient had any similar complaints in the past.",
        "Please ignore if already submitted. Thanking you."]),
    "PT-0006": ("Bharat Suraksha Health - TPA Desk", [
        "Ref: Claim No CLM-2026-100288",
        "We have reviewed the claim of Mrs. Kavita Joshi. The claim is under process. To proceed further, please provide "
        "the past treatment records for diabetes since the first diagnosis, along with the duration of the ailment. "
        "Also send a certificate from the treating doctor stating the date of first diagnosis of diabetes. "
        "Please also submit the policy copy of the first year of insurance for continuity verification. "
        "In addition, kindly explain the reason for the delay in intimation of hospitalisation to the insurer.",
        "Requirements must reach us on or before 30/10/2026.",
        "Regards, Medical Team"]),
    "PT-0007": ("Star Shield Health Insurance", [
        "Claim No.: CLM-2026-100301",
        "Patient: Vikram Singh",
        "Pending documents:",
        "- Coronary angiography report",
        "- Stent invoice with sticker",
        "- Detailed final bill with breakup",
        "- KYC of the insured",
        "Kindly arrange to send the above at the earliest."]),
    "PT-0005": ("Nirmal General Insurance Co. Ltd. - Claims", [
        "Claim No: CLM-2026-100270",
        "Insured / Patient: Arjun Reddy",
        "Since the hospitalisation is due to a road traffic accident, please provide:",
        "1) FIR copy / MLC copy.",
        "2) Statement of the patient describing how the accident happened, and whether alcohol was consumed.",
        "3) X-ray films / reports.",
        "4) Policy copy and health card.",
        "5) Aadhaar card and PAN card of the insured.",
        "Submit within 7 days."]),
    "PT-0009": ("Bharat Suraksha Health", [
        "Claim Ref: CLM-2026-100322",
        "To process the claim of Mr. Suresh Patel please send:",
        "1. Discharge summary.",
        "2. Chest X-ray report.",
        "3. Final bill with breakup.",
        "4. Cancelled cheque.",
        "Thank you."]),
}


def main():
    if ROOT.exists():
        for sub in ("patients", "query_letters"):
            shutil.rmtree(ROOT / sub, ignore_errors=True)
    ROOT.mkdir(exist_ok=True)
    (ROOT / "profiles.json").write_text(json.dumps(PATIENTS, indent=2), encoding="utf-8")
    for p in PATIENTS:
        catalogue = docs_for(p)
        for key in LOCKERS[p["patient_code"]]:
            fname, title, lines = catalogue[key]
            pdf(ROOT / "patients" / p["patient_code"] / fname, title, lines)
    for code, (insurer, lines) in QUERY_LETTERS.items():
        pdf(ROOT / "query_letters" / f"{code}_query_letter.pdf", insurer, lines)
    print(f"Sample data written to {ROOT}")


if __name__ == "__main__":
    main()
