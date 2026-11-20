"""Convert the OLAS (Luxembourg) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py <scrape out> <dataset dir> [--today YYYY-MM-DD]

Input: olas_17065_raw.json (register: number, name, address, dates, annex URL) and annex_transcription.csv next to
this script. The three annexes ("Annexe technique", French, 2 pages each) set their columns side by side, so their
lines were transcribed by reading the PDFs. Contacts (phone, e-mail) come from the annex first page, because the
register page gives none. Output: bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "greece" / "esyd-greece-17065"))
import prepare_certifind_17065 as gr  # noqa: E402  (column lists, refs)

AB_CODE = "OLAS"
# contact from the annex first page ("Personne de contact", "Tél.", "E-Mail")
CONTACTS = {
    "5/004": ("+352 54 70 51 240", "fanny.ragot@luxcontrol.com"),
    "5/005": ("+352 26 53 29 66", "sneuberg@signa.lu"),
    "5/001": ("+352 26 15 70 250", "camille.delgoffe@snch.lu"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--today", default=date.today().isoformat())
    a = ap.parse_args()
    a.dataset.mkdir(parents=True, exist_ok=True)
    data_root = a.dataset.resolve().parent
    raw = json.loads((a.scrape / "olas_17065_raw.json").read_text(encoding="utf-8"))
    lines = list(csv.DictReader(open(HERE / "annex_transcription.csv", encoding="utf-8")))
    used = {r["certificate_number"] for r in csv.DictReader(open(data_root / "olas-luxembourg" / "accreditations.csv", encoding="utf-8"))}
    others = {}
    for f in data_root.glob("*/bodies.csv"):
        if f.parent != a.dataset.resolve():
            for r in csv.DictReader(open(f, encoding="utf-8")):
                others.setdefault((r["country"], r["name"]), r)

    bodies, accs, ps = [], [], []
    for rec in sorted(raw, key=lambda r: r["registration_no"]):
        no, name = rec["registration_no"], gr.clean(rec["name"])
        mine = [l for l in lines if l["registration_no"] == no]
        if not mine:
            print(f"no transcribed line for {no} {name}; skipped")
            continue
        body = others.get(("Luxembourg", name))
        if body is None:
            phone, email = CONTACTS.get(no, ("", ""))
            addr = rec["address"].rsplit(", Luxembourg", 1)[0]
            body = {"name": name, "country": "Luxembourg", "registration_no": no, "phone": phone, "email": email,
                    "website": "", "address": addr, "source_url": rec["page_url"], "verified_at": ""}
        cert = no if no not in used else f"{no} (17065)"
        bodies.append({k: body.get(k, "") for k in gr.BODY_COLUMNS})
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": "ISO/IEC 17065", "status": "ACTIVE", "issue_date": rec["issued"],
                     "expiry_date": rec["expiry"], "proof_url": rec["annex_urls"][0]})
        for l in mine:
            full = " ".join([l["product_text"], l["scheme_text"], l["normative_docs"]])
            ps.append({"certificate_number": cert, "line_no": l["line_no"], "scheme": l["scheme"],
                       "industry": "" if l["scheme"] else l["industry"], "product_text": l["product_text"],
                       "product_text_en": "", "scheme_text": l["scheme_text"], "normative_docs": l["normative_docs"],
                       "standard_refs": gr.refs(full), "status": "ACTIVE"})

    def write(path, cols, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    write(a.dataset / "bodies.csv", gr.BODY_COLUMNS, bodies)
    write(a.dataset / "accreditations.csv", gr.ACC_COLUMNS, accs)
    write(a.dataset / "scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write(a.dataset / "product_scopes.csv", gr.PS_COLUMNS, ps)
    (HERE / "olas_17065_review.md").write_text(
        f"# OLAS 17065 review ({a.today})\n\n"
        f"Bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} "
        f"({sum(1 for p in ps if p['scheme'])} with a scheme).\n\n"
        "- All three bodies are new (not in olas-luxembourg or another dataset).\n"
        "- Phones and e-mails are the annex contact persons' (the register page lists none).\n"
        "- SNCH vehicle type approval (EU / UNECE) has no catalogue scheme (one body): text + transport_equipment.\n"
        "- SIGNA Audit organic: categories a, b, d, f of Reg. (EU) 2018/848 art. 35(7), one line each.\n",
        encoding="utf-8")
    print(f"bodies {len(bodies)} accreditations {len(accs)} lines {len(ps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
