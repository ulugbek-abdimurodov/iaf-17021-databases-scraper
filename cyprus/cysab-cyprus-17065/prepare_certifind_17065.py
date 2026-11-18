"""CYS-CYSAB (Cyprus) ISO/IEC 17065 annexes -> CertiFind dataset (bodies, accreditations, empty scopes, product_scopes).

Usage: python prepare_certifind_17065.py <pdf dir> <dataset dir> [--today YYYY-MM-DD]

The gov.cy register is behind an Azure WAF and was not captured (cysab_17065/scrape_17065.log), so bodies,
certificate numbers and dates come from the seven accreditation certificates in <pdf dir>. The annex entries
are transcribed verbatim in annex_transcription.csv next to this file (one row per annex entry).
Bureau Veritas Hellas is copied exactly from data/esyd-greece/bodies.csv (same body, same row).
Rules: .claude/skills/add-country-17065/SKILL.md in the certifind repo.
"""
import argparse, csv, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2] / "certifind"  # database/cyprus/cysab-cyprus-17065 -> CertiFind/certifind
AB = "CYSAB"
STANDARD = "ISO/IEC 17065"
REGISTER = "https://www.gov.cy/meci-cysab/documents/diapisteymenoi-foreis/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "product_text", "product_text_en", "scheme_text",
              "normative_docs", "standard_refs", "status"]

# Catalogue codes used by this dataset (all present in `schemes`; checked with psql after the import).
SCHEMES = {
    "EU Geographical Indications (DOP/IGP/STG)",
    "EU Organic Regulation (EU) 2018/848",
    "Construction Products Regulation (EU) 305/2011",
    "Lifts Directive 2014/33/EU",
    "Machinery Directive 2006/42/EC",
    "Pressure Equipment Directive 2014/68/EU",
    "ATEX Directive 2014/34/EU",
    "CEN Keymark",
    "ISO 3834",
}
# The 19 industry codes of V70__product_industries_19.sql.
INDUSTRIES = {
    "agriculture", "food", "textiles", "wood_paper", "chemicals", "rubber_plastics", "construction", "metals",
    "machinery", "electrical", "transport_equipment", "other_manufacturing", "energy", "trade_logistics", "tourism",
    "ict", "professional", "public_education", "health",
}

# One row per certificate (accreditation). Source: the certificate PDF named in `pdf`.
# Bodies are listed in certificate order; dates are the certificate's issue date and validity end.
CERTS = [
    dict(cert="C 008-1", pdf="3.pdf", name="BUREAU VERITAS HELLAS SINGLE PERSON SOCIETE ANONYME (BUREAU VERITAS HELLAS S.P. S.A.)",
         reuse=True, issue="2025-07-03", expiry="2029-07-02"),
    dict(cert="ΦΠ 005-2", pdf="6.pdf", name="CERTIFYBIO", country="Cyprus",
         address="Certifybio Ltd, Νέας Έγκωμης, 33, 2409 Λευκωσία, Cyprus",
         issue="2025-04-09", expiry="2027-12-18"),
    dict(cert="ΦΠ 001-5", pdf="C-001-ΦΠ001-LACON-GR.pdf",
         name="Lacon Institute for Inspection and Certification in Agriculture and Food Processing Limited",
         country="Cyprus", address="", issue="2026-02-04", expiry="2029-02-05"),
    dict(cert="C 007-2", pdf="C007_2.pdf", name="NORTEST (CYPRUS) LIMITED", country="Cyprus",
         address="98, Arch. Makariou, CY-2224 Latsia, Nicosia, Cyprus", issue="2026-05-20", expiry="2029-12-12"),
    dict(cert="C 009", pdf="C009-ΦΠ009-EN.pdf", name="MYCERT LTD", country="Cyprus",
         address="120, Faneromenis Avenue, Office 401, 6031 Larnaca, Cyprus", issue="2025-10-08", expiry="2029-10-07"),
    dict(cert="C 006-2", pdf="ΚΕΠ-C006-2025-En.pdf", name="CYPRUS CERTIFICATION COMPANY", country="Cyprus",
         address="30, Costa Anaxagora str, 2014 Strovolos, Nicosia, Cyprus", issue="2026-06-29", expiry="2029-07-14"),
    dict(cert="C 004-4", pdf="ΦΠΠ006-C004.pdf", name="TUV CYPRUS LIMITED", country="Cyprus",
         address="2 Papaflessa Street, 2235 Latsia, Nicosia, Cyprus", issue="2026-10-14", expiry="2029-10-30"),
]
TRANSCRIPTION = HERE / "annex_transcription.csv"
ESYD_BODIES = REPO / "data" / "esyd-greece" / "bodies.csv"


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def esyd_row(name: str) -> dict:
    with open(ESYD_BODIES, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["name"] == name:
                return {c: row.get(c, "") for c in BODY_COLUMNS}
    sys.exit(f"reuse row not found in {ESYD_BODIES}: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_dir")
    ap.add_argument("dataset_dir")
    ap.add_argument("--today", default=date.today().isoformat())
    a = ap.parse_args()
    pdf_dir, out = Path(a.pdf_dir), Path(a.dataset_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors, log = [], []

    for c in CERTS:
        if not (pdf_dir / c["pdf"]).exists():
            errors.append(f"missing certificate PDF {c['pdf']}")
    with open(TRANSCRIPTION, encoding="utf-8", newline="") as f:
        lines = list(csv.DictReader(f))
    by_cert = {c["cert"]: c for c in CERTS}
    seen = set()
    for r in lines:
        cert, n = r["certificate_number"], r["line_no"]
        if cert not in by_cert:
            errors.append(f"line {cert}/{n}: unknown certificate")
            continue
        if (cert, n) in seen:
            errors.append(f"line {cert}/{n}: duplicate line_no")
        seen.add((cert, n))
        if r["source"] != by_cert[cert]["pdf"]:
            errors.append(f"line {cert}/{n}: source {r['source']} is not the certificate PDF")
        if r["scheme"] and r["scheme"] not in SCHEMES:
            errors.append(f"line {cert}/{n}: scheme {r['scheme']!r} not in the catalogue list")
        if r["industry"] and r["industry"] not in INDUSTRIES:
            errors.append(f"line {cert}/{n}: industry {r['industry']!r} is not a V70 code")
        if r["industry"] and r["scheme"]:
            errors.append(f"line {cert}/{n}: industry is only set on lines without a scheme")
        if not (r["scheme"] or r["industry"] or r["product_text"] or r["normative_docs"]):
            errors.append(f"line {cert}/{n}: nothing to filter on")
    for c in CERTS:
        if not any(r["certificate_number"] == c["cert"] for r in lines):
            errors.append(f"certificate {c['cert']}: no importable line")
    if errors:
        sys.exit("\n".join(errors))

    bodies, accs, ps = [], [], []
    for c in CERTS:
        if c.get("reuse"):
            body = esyd_row(c["name"])
        else:
            body = {"name": c["name"], "country": c["country"], "registration_no": "", "phone": "", "email": "",
                    "website": "", "address": c["address"], "source_url": REGISTER, "verified_at": ""}
            if not c["address"]:
                log.append(f"{c['cert']} {c['name']}: address and phone not on the certificate; left empty")
        bodies.append(body)
        accs.append({"ab_code": AB, "certificate_number": c["cert"], "body_name": c["name"],
                     "accreditation_standard": STANDARD, "status": "ACTIVE", "issue_date": c["issue"],
                     "expiry_date": c["expiry"], "proof_url": REGISTER})
        if c["expiry"] < a.today:
            log.append(f"{c['cert']}: expired {c['expiry']} (kept as EXPIRED)")
            accs[-1]["status"] = "EXPIRED"

    order = {c["cert"]: i for i, c in enumerate(CERTS)}
    for r in sorted(lines, key=lambda r: (order[r["certificate_number"]], int(r["line_no"]))):
        ps.append({"certificate_number": r["certificate_number"], "line_no": r["line_no"],
                   "scheme": r["scheme"], "industry": r["industry"],
                   "product_text": clean(r["product_text"]), "product_text_en": "",
                   "scheme_text": clean(r["scheme_text"]), "normative_docs": clean(r["normative_docs"]),
                   "standard_refs": clean(r["standard_refs"]), "status": r["status"]})

    write(out / "bodies.csv", BODY_COLUMNS, bodies)
    write(out / "accreditations.csv", ACC_COLUMNS, accs)
    write(out / "scopes.csv", SCOPE_COLUMNS, [])
    write(out / "product_scopes.csv", PS_COLUMNS, ps)

    with_scheme = sum(1 for p in ps if p["scheme"])
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nProduct lines: {len(ps)}")
    print(f"  with scheme: {with_scheme}\n  industry only: {sum(1 for p in ps if p['industry'] and not p['scheme'])}"
          f"\n  text only: {sum(1 for p in ps if not p['scheme'] and not p['industry'])}")
    for m in log:
        print("NOTE", m)


if __name__ == "__main__":
    main()
