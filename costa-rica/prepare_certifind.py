"""ECA (Costa Rica) -> CertiFind CSVs.

Usage: python prepare_certifind.py <scrape-dir> <dataset-dir> [--today YYYY-MM-DD]

<scrape-dir> holds scrape_cr_eca.py (raw data transcribed from the ECA register and scope PDFs).
"""
import csv, importlib.util, os, sys

SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
}
ALL_NOTE = "No sector list in the ECA register; recorded for all EA sectors"
INTL = "4256/ocsg-001-inteco-alcance-acreditacion-reconocimiento-internacional.pdf"
NATL = "4257/ocsg-001-inteco-alcance-acreditacion-reconocimiento-nacional.pdf"
# Schemes present in the annexes but missing from the transcribed raw data (no sector list given).
EXTRA = {"OCSG-001": [("ISO 28000", [], NATL), ("ISO 37001", [], NATL)]}
SKIPPED = [
    "INTE G38-3:2021 (gender equality management) - national scheme, not in standards table",
    "ISO 22000 / FSSC 22000 - voluntarily reduced from INTECO's scope; not accredited",
]


def compress(codes):
    codes = sorted(set(codes)); out = []; i = 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1: j += 1
        out.append(str(codes[i]) if i == j else f"{codes[i]}-{codes[j]}"); i = j + 1
    return ";".join(out)


def main():
    scrape, dataset = sys.argv[1], sys.argv[2]
    today = sys.argv[sys.argv.index("--today") + 1] if "--today" in sys.argv else ""
    spec = importlib.util.spec_from_file_location("eca_raw", os.path.join(scrape, "scrape_cr_eca.py"))
    raw = importlib.util.module_from_spec(spec); spec.loader.exec_module(raw)
    B, A, S, notes = [], [], [], []
    for r in raw.RAW:
        B.append(dict(name=r["name"], country="Costa Rica", registration_no=r["id"], phone=r["phone"],
                      email=r["email"], website=r["website"], address=r["address"],
                      source_url=r["source_url"], verified_at=""))
        accs = {}
        def acc(std, pdf):
            a, suf = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", None))
            cn = f"{r['id']} ({suf})" if suf else r["id"]
            if cn not in accs:
                accs[cn] = dict(ab_code="ECA", certificate_number=cn, body_name=r["name"], accreditation_standard=a,
                                status="ACTIVE", issue_date=r["issue_date"], expiry_date="", proof_url=raw.BASE + pdf)
            return cn
        acc("ISO 9001", INTL)  # base 17021-1 row first
        for std, ea, pdf in list(r["schemes"]) + EXTRA.get(r["id"], []):
            cn = acc(std, pdf)
            S.append(dict(certificate_number=cn, certification_standard=std,
                          ea_codes=compress(ea) if ea else "1-39", status="ACTIVE",
                          scope_note="" if ea else ALL_NOTE))
            if not ea: notes.append(f"{r['id']} {std}: no sector list -> EA 1-39")
        A.extend(accs.values())
    os.makedirs(dataset, exist_ok=True)
    for fn, rows in (("bodies.csv", B), ("accreditations.csv", A), ("scopes.csv", S)):
        with open(os.path.join(dataset, fn), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    try:
        import prune_inactive; prune_inactive.prune(dataset)
    except ImportError:
        notes.append("prune_inactive.py not found; prune skipped (every body has an ISO/IEC 17021-1 row)")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "eca_review.md"), "w", encoding="utf-8") as f:
        f.write(f"# ECA review ({today})\n\nRegister lists one ISO/IEC 17021-1 body: OCSG-001 INTECO.\n\n"
                "## Skipped\n" + "".join(f"- {s}\n" for s in SKIPPED) +
                "\n## Notes\n" + "".join(f"- {n}\n" for n in notes) +
                "- Accreditation valid indefinitely: expiry_date empty.\n"
                "- ISO/IEC 27001, ISO 28000, ISO 37001 are on the national (non-MLA) annex.\n")
    print(f"Bodies {len(B)}, accreditations {len(A)}, scopes {len(S)}")


if __name__ == "__main__":
    main()
