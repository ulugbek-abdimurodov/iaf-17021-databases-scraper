"""Convert the INN (Chile) ISO/IEC 17065 scrape into a CertiFind product dataset.

Usage: python prepare_certifind_17065.py [--dataset DIR]

Input: inn_17065_raw.json (from scrape_cl_inn_17065.py). Output in DIR (default chile/data/inn-chile-17065):
bodies.csv, accreditations.csv, scopes.csv (header only), product_scopes.csv; inn_17065_review.md next to
this script. One accreditation per INN code (CP xxx / ST xxx); one product line per accreditation = the register
area, with category/sector/industry from the scraper's AREAS map. Annex PDFs are not parsed yet (no tokens).
"""
import argparse, collections, csv, json, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from scrape_cl_inn_17065 import classify  # noqa: E402

AB_CODE, STD, SRC = "INN", "ISO/IEC 17065", "https://directorio.inn.cl/"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"]
ACC_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date",
               "expiry_date", "proof_url"]
PS_COLUMNS = ["certificate_number", "line_no", "scheme", "industry", "category", "sector", "product_text",
              "product_text_en", "scheme_text", "normative_docs", "standard_refs", "status"]
# Same spellings as the MS dataset (data/inn-chile) so bodies merge; truncated register name expanded.
NAMES = {"SGS CHILE LTDA.": "SGS Chile Ltda.",
         "Bureau Veritas Certification Chile S.A": "Bureau Veritas Certification Chile S.A.",
         "SCI CERTIFICACIONES LIMITADA": "SCI Certificaciones Limitada",
         "Centro de estudios medición y certificación de cal":
             "Centro de Estudios, Medición y Certificación de Calidad (CESMEC)",
         "Sociedad de ingenerÍa y certificación de calidad S.A.": "Sociedad de Ingeniería y Certificación de Calidad S.A.",
         "5M SpA.": "5M SpA"}
d = lambda s: datetime.strptime(s, "%d-%m-%Y").strftime("%Y-%m-%d")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", type=Path, default=HERE.parent / "data" / "inn-chile-17065")
    a = ap.parse_args()
    recs = json.load(open(HERE / "inn_17065_raw.json", encoding="utf-8"))
    today = datetime.now().strftime("%Y-%m-%d")

    bodies, accs, ps, review = {}, [], [], collections.defaultdict(list)
    for r in recs:
        name = NAMES.get(r["name"], r["name"]).strip()
        cert = r["id"]
        status = "active" if r["status"] == "Vigente" else "suspended"
        if status == "active" and d(r["expiry"]) < today:
            review["Vigente but expired in register"].append(f"{r['registration_no']} {name}: expiry {d(r['expiry'])}")
        if r["status"] != "Vigente":
            review["Suspended"].append(f"{r['registration_no']} {name} ({r['area']})")
        if not r["address"]:
            review["No commune in register"].append(f"{r['registration_no']} {name}")
        bodies.setdefault(name, dict(name=name, country="Chile", registration_no=cert, phone=r["phone"], email="",
                                     website="", address=f"{r['address']}, Chile" if r["address"] else "Chile",
                                     source_url=SRC, verified_at=""))
        accs.append(dict(ab_code=AB_CODE, certificate_number=cert, body_name=name, accreditation_standard=STD,
                         status=status, issue_date=d(r["issued"]), expiry_date=d(r["expiry"]),
                         proof_url=r["annex_urls"][0] if r["annex_urls"] else SRC))
        cat, sec, ind = classify(r["area"])
        ps.append(dict(certificate_number=cert, line_no=1, scheme="", industry=ind, category=cat, sector=sec,
                       product_text=r["area"], product_text_en=cat, scheme_text="", normative_docs="",
                       standard_refs="", status=status))

    a.dataset.mkdir(parents=True, exist_ok=True)

    def write(name, cols, rows):
        with open(a.dataset / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    write("bodies.csv", BODY_COLUMNS, bodies.values())
    write("accreditations.csv", ACC_COLUMNS, accs)
    write("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], [])
    write("product_scopes.csv", PS_COLUMNS, ps)

    sectors = collections.Counter(p["sector"] for p in ps)
    out = ["# INN Chile 17065 review", "",
           f"{len(bodies)} bodies, {len(accs)} accreditations, {len(ps)} product lines.", "",
           "## Lines by sector", ""] + [f"- {s}: {n}" for s, n in sectors.most_common()] + [""]
    for k, v in review.items():
        out += [f"## {k}", ""] + [f"- {x}" for x in v] + [""]
    out += ["## Notes", "",
            "- Product lines are the register's accreditation area only; annex PDFs not downloaded (DOCUMENTO_ENCRYPT "
            "tokens missing from the export), so no schemes, standards or detailed products yet.",
            "- ST codes are tourism service certification (NCh tourism standards), kept under sector Services.",
            "- Register gives commune only (no street, email or website).", ""]
    (HERE / "inn_17065_review.md").write_text("\n".join(out), encoding="utf-8")
    print(f"Bodies: {len(bodies)}  Accreditations: {len(accs)}  Product lines: {len(ps)}  -> {a.dataset}")


if __name__ == "__main__":
    main()
