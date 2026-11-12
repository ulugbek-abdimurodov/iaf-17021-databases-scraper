import csv, re
from pathlib import Path
from certifind_common import resolve_cert_number, write_certifind_csvs
HERE = Path(__file__).parent; ROOT = HERE.parent.parent
AREA = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OH&SMS": "ISO 45001", "MDMS": "ISO 13485",
        "ISMS": "ISO/IEC 27001", "PIMS": "ISO/IEC 27701", "EnMS": "ISO 50001",
        "BCMS": "ISO 22301", "ITSMS": "ISO/IEC 20000-1"}
SKIP = {"CSC": "CyberSecure Canada", "AIMS": "ISO/IEC 42001", "AQMS": "AS9100", "ABMS": "ISO 37001", "SF": "Sustainable Forestry (CSA Z809/SFI)"}
CTRY = {"USA": "United States"}
B = "https://scc-ccn.ca"
bodies, accs, scopes, excl = [], [], [], []
for r in csv.reader(open(HERE / "scc_raw.tsv", encoding="utf-8"), delimiter="\t"):
    name, addr, city, ctry, web, phone, fileno, init, exp, areas, pdf, slug, email = r
    name = re.sub(r" Client L$", "", name).strip()
    m = re.match(r"(.*?)(?: Province (.*?))?(?: Postal Code (.*))?$", city)
    cty, prov, pc = m.group(1), m.group(2) or "", m.group(3) or ""
    cty = cty.title() if cty.isupper() else cty
    address = ", ".join(x for x in [addr, " ".join(x for x in [pc, cty] if x), prov] if x)
    codes = re.findall(r"\(([^)]+)\)", areas) + (["SF"] if "Sustainable Forestry" in areas else [])
    stds = [AREA[c] for c in codes if c in AREA]
    for c in codes:
        if c not in AREA: excl.append((name, fileno, SKIP.get(c, c)))
    src = f"{B}/accreditation/management-systems/{slug}"; proof = f"{B}/system/files/{pdf}" if pdf else ""
    if not stds: continue
    reg = fileno
    bodies.append(dict(name=name, country=CTRY.get(ctry, ctry), registration_no=reg, phone=phone, email=email,
                       website=("https://" + web) if web and not web.startswith("http") else web,
                       address=address, source_url=src, verified_at=""))
    seen = {}
    for s in stds:
        cert, acc_std = resolve_cert_number(reg, s)
        if cert not in seen:
            seen[cert] = 1
            accs.append(dict(ab_code="SCC", certificate_number=cert, body_name=name, accreditation_standard=acc_std,
                             status="active", issue_date=init, expiry_date=exp, proof_url=proof))
        scopes.append(dict(certificate_number=cert, certification_standard=s, ea_codes="", status="active",
                           scope_note="EA codes not extracted: scope PDF not parsed (see SOURCES.md)"))
out = ROOT / "data/scc-canada"
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    write_certifind_csvs(out, bodies, accs, scopes)
with open(HERE / "scc_review.md", "w", encoding="utf-8") as f:
    f.write("# SCC review: skipped schemes\n\nSchemes outside the CertiFind scheme map (no body excluded entirely).\n\n| Body | File No. | Skipped scheme |\n|---|---|---|\n")
    f.writelines(f"| {a} | {b} | {c} |\n" for a, b, c in excl)
    f.write("\n## Open issue\nEA codes are empty: scope PDFs (proof_url) could not be downloaded into the build workspace (host blocked) and in-browser PDF parsing was not permitted. Re-run with PDF access to fill `ea_codes`.\n")
print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excl)} scheme entries, 0 bodies")
