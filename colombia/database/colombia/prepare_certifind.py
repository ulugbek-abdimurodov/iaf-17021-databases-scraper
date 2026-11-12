"""Convert onac_raw.tsv into CertiFind CSVs (data/onac-colombia)."""
import csv, re
from pathlib import Path
from certifind_common import (compress_ea_codes, resolve_cert_number, write_certifind_csvs,
                              ISO22003_TO_EA, SCHEME_ACCREDITATION_MAP)

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "onac-colombia"
SRC = "https://onac.org.co/directorio-de-acreditados/"
ALL = list(range(1, 40)); ALL.remove(11)


def nums(s):
    if s == "ALL":
        return ALL
    out = []
    for p in filter(None, s.split(",")):
        a, _, b = p.partition("-")
        out += range(int(a), int(b or a) + 1)
    return out


bodies, accs, scopes, excluded = [], [], [], []
for r in csv.DictReader(open(HERE / "onac_raw.tsv", encoding="utf-8"), delimiter="\t"):
    items = [p.split(":", 1) for p in r["scopes"].split("|")]
    keep = [(s, v) for s, v in items if s in SCHEME_ACCREDITATION_MAP]
    skipped = [s for s, _ in items if s not in SCHEME_ACCREDITATION_MAP]
    if skipped:
        excluded.append((r["code"], r["name"], skipped, not keep))
    if not keep:
        continue
    bodies.append(dict(name=r["name"], country=r["country"], registration_no=r["code"], phone=r["phone"],
                       email=r["email"].lower(), website=r["website"], address=r["address"],
                       source_url=SRC, verified_at=""))
    seen = set()
    for std, val in keep:
        cert, acc_std = resolve_cert_number(r["code"], std)
        if cert not in seen:
            seen.add(cert)
            accs.append(dict(ab_code="ONAC", certificate_number=cert, body_name=r["name"],
                             accreditation_standard=acc_std, status="active", issue_date=r["issued"],
                             expiry_date=r["expiry"], proof_url=f"https://onac.org.co/certificados/{r['code']}.pdf"))
        if re.fullmatch(r"[A-K](,[A-K])*", val):
            ea = compress_ea_codes(e for c in val.split(",") for e in ISO22003_TO_EA[c])
            note = f"Classified to EA from ISO 22003-1 categories {val.replace(',', ', ')}"
        elif val:
            ea, note = compress_ea_codes(nums(val)), "IAF codes as listed in the ONAC scope certificate"
        else:
            ea, note = "", "ONAC scope lists no IAF sectors for this scheme (No aplica)"
        scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea,
                           status="active", scope_note=note))

write_certifind_csvs(OUT, bodies, accs, scopes)
with open(HERE / "onac_review.md", "w", encoding="utf-8") as f:
    f.write("# ONAC review: skipped schemes/bodies\n\nOut-of-scope schemes (not in CertiFind scheme map): "
            "NTC 5555, NTC 6001, ISO 18788, ISO 28000, ISO 28001, ISO 37001, ISO 39001, ISO 55001.\n\n"
            "| Registration | Body | Skipped schemes | Body excluded |\n|---|---|---|---|\n")
    for c, n, s, x in excluded:
        f.write(f"| {c} | {n} | {', '.join(s)} | {'yes' if x else 'no'} |\n")
    f.write("\nParsing notes: scope PDFs are multi-column; IAF code lists that wrap around the scheme label "
            "were merged from two line-order heuristics. Sector 11 (nuclear) is never listed, so \"all\" = 1-10;12-39. "
            "Footnote limitations (e.g. '07* limited to pulp and paper') are not modelled.\n")
print(f"Excluded bodies: {sum(x for *_, x in excluded)}")
