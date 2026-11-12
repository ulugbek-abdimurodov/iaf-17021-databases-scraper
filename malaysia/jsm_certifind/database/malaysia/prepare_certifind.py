#!/usr/bin/env python3
"""Parse downloaded JSM ACB schedules into CertiFind CSVs.

Requires the project's existing certifind_common.py on PYTHONPATH.
Run from repository root:
  pip install pdfplumber
  python database/malaysia/prepare_certifind.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import pdfplumber
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from certifind_common import (
    SCHEME_ACCREDITATION_MAP, compress_ea_codes, resolve_cert_number,
    write_certifind_csvs,
)

DATA = ROOT / "data" / "jsm-malaysia"
PDF_DIR = DATA / "pdfs"
REVIEW = ROOT / "database" / "malaysia" / "jsm_review.md"
REGISTER = DATA / "register_records.json"

# JSM programme names mapped to certification standards. Schemes without a
# helper-map equivalent are deliberately reviewed, not silently guessed.
PROGRAMME_TO_STANDARD = {
    "QUALITY MANAGEMENT SYSTEMS (QMS)": "ISO 9001",
    "ENVIRONMENTAL MANAGEMENT SYSTEMS (EMS)": "ISO 14001",
    "OCCUPATIONAL SAFETY & HEALTH MANAGEMENT SYSTEMS (OSH)": "ISO 45001",
    "INFORMATION SECURITY MANAGEMENT SYSTEM(ISMS)": "ISO/IEC 27001",
    "INFORMATION SECURITY MANAGEMENT SYSTEM (ISMS)": "ISO/IEC 27001",
    "MEDICAL DEVICES QUALITY MANAGEMENT SYSTEM (MDQMS)": "ISO 13485",
    "MEDICAL DEVICE QUALITY MANAGEMENT SYSTEM (MDQMS)": "ISO 13485",
    "ENERGY MANAGEMENT SYSTEM(EnMS)": "ISO 50001",
    "ENERGY MANAGEMENT SYSTEM (EnMS)": "ISO 50001",
    "FOOD SAFETY MANAGEMENT SYSTEM (FSMS)": "ISO 22000",
    "FOOD SAFETY SYSTEM CERTIFICATION (FSSC)": "FSSC 22000",
    "ANTI-BRIBERY MANAGEMENT SYSTEM (ABMS)": "ISO 37001",
    "ANTI BRIBERY MANAGEMENT SYSTEM (ABMS)": "ISO 37001",
    "BUSINESS CONTINUITY MANAGEMENT SYSTEMS (BCMS)": "ISO 22301",
    "ROAD TRANSPORT SAFETY MANAGEMENT SYSTEMS (RTSMS)": "ISO 39001",
    "ADVENTURE TOURISM SAFETY MANAGEMENT SYSTEMS (ATSMS)": "ISO 21101",
}
# Only a narrow allowlist is imported. The PDF's accreditation criteria must
# explicitly contain ISO/IEC 17021-1; programme name alone is insufficient.
MANAGEMENT_PROGRAMMES = set(PROGRAMME_TO_STANDARD)

def norm(s): return re.sub(r"\s+", " ", s or "").strip()
def date_from(text, label):
    m = re.search(rf"{label}\s*:\s*(\d{{1,2}}\s+[A-Za-z]+\s+\d{{4}})", text, re.I)
    return m.group(1) if m else ""

def parse_iaf_codes(text):
    # Extract explicit IAF ID 1 sector codes; do not treat these as EA codes.
    found = []
    in_scope = False
    for line in text.splitlines():
        if re.search(r"SCOPE OF ACCREDITATION", line, re.I): in_scope = True
        if in_scope:
            m = re.match(r"^\s*(\d{1,2})\s+(?:[A-Z].*|Limited to.*)$", line.strip())
            if m:
                n = int(m.group(1))
                if 1 <= n <= 39: found.append(n)
    return sorted(set(found))

def pages_as_text(path):
    with pdfplumber.open(path) as pdf:
        return [p.extract_text(layout=False) or "" for p in pdf.pages]

def split_programme_blocks(page_texts):
    # Programme heading usually begins a page and continues until the next
    # "PROGRAMME:" heading. The first schedule pages only list programme names.
    joined = "\n\f\n".join(page_texts)
    matches = list(re.finditer(r"(?im)^\s*PROGRAMME\s*:\s*(.+?)(?=\n)", joined))
    blocks = []
    for i, m in enumerate(matches):
        end = matches[i+1].start() if i+1 < len(matches) else len(joined)
        blocks.append((norm(m.group(1)).upper(), joined[m.start():end]))
    return blocks, joined

def country_from_address(address):
    # ACB schedules identify the country as the last explicit country line.
    m = re.search(r"\b(MALAYSIA|SINGAPORE|THAILAND|INDIA|UNITED KINGDOM|CHINA|JAPAN)\b", address, re.I)
    return m.group(1).title() if m else "Malaysia"

def main():
    records = json.loads(REGISTER.read_text(encoding="utf-8"))
    # Keep one record per ACB number; each programme/status remains a separate accreditation.
    body_records = {}
    accs, scopes, skipped = [], [], []
    for rec in records:
        rid = rec["registration_no"]
        body_records.setdefault(rid, rec)
    for rid, body in body_records.items():
        pdf = PDF_DIR / f"{rid}.pdf"
        if not pdf.exists():
            skipped.append(f"- {rid} {body['name']}: schedule PDF missing ({body['proof_url']})")
            continue
        pages = pages_as_text(pdf)
        blocks, full_text = split_programme_blocks(pages)
        issue = date_from(full_text, "Issue date")
        expiry = date_from(full_text, "Valid until")
        for rec in [r for r in records if r["registration_no"] == rid]:
            programme = norm(rec["programme"]).upper()
            if programme not in MANAGEMENT_PROGRAMMES:
                skipped.append(f"- {rid} {body['name']}: excluded/unmapped programme `{rec['programme']}` (register status: {rec['programme_status']})")
                continue
            standard = PROGRAMME_TO_STANDARD[programme]
            block = next((b for name,b in blocks if name.startswith(programme.split("(")[0].strip()) or programme in name), "")
            if not block:
                # Search PDF full text around the programme label if extraction layout differs.
                idx = full_text.upper().find(programme)
                block = full_text[idx:idx+12000] if idx >= 0 else ""
            if "ISO/IEC 17021-1" not in block:
                skipped.append(f"- {rid} {body['name']}: {rec['programme']} lacks explicit ISO/IEC 17021-1 evidence in extracted block")
                continue
            if standard not in SCHEME_ACCREDITATION_MAP:
                skipped.append(f"- {rid} {body['name']}: `{standard}` is not present in certifind_common.SCHEME_ACCREDITATION_MAP")
                continue
            cert_no, acc_std = resolve_cert_number(rid, standard)
            accs.append({
                "ab_code": "JSM", "certificate_number": cert_no, "body_name": body["name"],
                "accreditation_standard": acc_std, "status": rec["programme_status"],
                "issue_date": issue, "expiry_date": expiry, "proof_url": body["proof_url"],
            })
            iaf = parse_iaf_codes(block)
            # IAF ID 1 sector codes are not EA codes. Never put them into ea_codes.
            scopes.append({
                "certificate_number": cert_no, "certification_standard": standard,
                "ea_codes": "",
                "status": rec["programme_status"],
                "scope_note": ("IAF ID 1 codes extracted from the JSM schedule: " +
                               (", ".join(map(str, iaf)) if iaf else "no machine-readable IAF codes found") +
                               ". EA mapping not inferred; review required."),
            })
    bodies = []
    for rid, rec in body_records.items():
        bodies.append({
            "name": rec["name"], "country": country_from_address(rec.get("address_raw","")),
            "registration_no": rid, "phone": rec.get("phone",""), "email": rec.get("email",""),
            "website": rec.get("website",""), "address": rec.get("address_raw",""),
            "source_url": "https://cab.jsm.gov.my/cab-directories/resultAcb", "verified_at": "",
        })
    write_certifind_csvs(DATA, bodies, accs, scopes)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text(
        "# JSM review notes\n\n"
        "## Assumptions and limitations\n"
        "- Register programmes are queried individually across every status option discovered in the live form.\n"
        "- One ACB registration number identifies a body/schedule; programme rows are separate accreditation records.\n"
        "- Imported only the allowlisted ISO management-system programmes and only where the corresponding schedule block explicitly contains ISO/IEC 17021-1.\n"
        "- Product certification, certification of persons, GMP, HACCP, forestry/MSPO/PEFC and other unmapped schemes are not imported by default; see exclusions below.\n"
        "- JSM scope schedules expose IAF ID 1 codes. These are not EA codes. `ea_codes` is intentionally blank until an authoritative IAF-to-EA or NACE crosswalk is supplied/verified; IAF values are retained in `scope_note`.\n"
        "- Body country is inferred from the schedule/register address when a country name is present; otherwise defaults to Malaysia and must be reviewed.\n"
        "- Contact fields are taken from the register listing. Missing fields remain empty.\n"
        "- Issue/expiry dates are schedule-level dates (Issue date / Valid until), not initial accreditation dates.\n"
        "- The schedule PDF can contain multiple programme annexes. The parser uses the programme-specific block; OCR/scanned layouts may need manual review.\n\n"
        "## Skipped schemes / bodies\n" + ("\n".join(sorted(set(skipped))) if skipped else "- None detected by the current rules.") + "\n",
        encoding="utf-8")
    print(f"Bodies: {len(bodies)}")
    print(f"Accreditations: {len(accs)}")
    print(f"Scopes: {len(scopes)}")
    print(f"Excluded: {len(set(skipped))}")

if __name__ == "__main__":
    main()
