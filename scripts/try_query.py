"""Dry run: show what the system would decide and send for a query letter, without saving or sending.

    python -m scripts.try_query PT-0001 sample_data/query_letters/PT-0001_query_letter.pdf
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import matcher, messaging, pipeline, query_parser, taxonomy  # noqa: E402
from app.db import init_db, session_scope  # noqa: E402
from app.extraction import extract_text  # noqa: E402
from app.models import Patient  # noqa: E402


def main(code: str, letter: str):
    init_db()
    text = extract_text(Path(letter))
    with session_scope() as db:
        p = db.scalar(select(Patient).where(Patient.patient_code == code))
        if not p:
            sys.exit(f"No patient {code}. Run python -m scripts.seed first.")
        pipeline.ensure_documents_ready(p.id)
        docs = pipeline._ready_docs(db, p.id)
        print(f"\nLocker for {p.full_name}: " + ", ".join(f"{taxonomy.label(d.doc_type)}" for d in docs))
        parsed = query_parser.parse(text)
        decisions, engine = matcher.match(parsed["points"], docs)
        print(f"Insurer: {parsed['insurer_name']} | Claim: {parsed['claim_reference']} | Deadline: {parsed['deadline']}")
        print(f"Engines: parse={parsed['engine']} match={engine}\n")
        pts = []
        for i, (pt, d) in enumerate(zip(parsed["points"], decisions)):
            mark = "IN LOCKER " if d["decision"] == "available" else "ASK       "
            print(f"[{pt['ref']}] {mark} {pt['insurer_text']}\n      -> {d['reason']}")
            if d["decision"] == "needed":
                print(f"      patient: {d['patient_request']} ({d['patient_reason']})")
            pts.append(SimpleNamespace(**pt, **d))
        q = SimpleNamespace(points=pts, insurer_name=parsed["insurer_name"], claim_reference=parsed["claim_reference"],
                            deadline=parsed["deadline"])
        msg = messaging.render(db, p, q, {d.id: d for d in p.documents})
        print("\n----- message -----\nSubject: " + msg["subject"] + "\n\n" + msg["body"])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
