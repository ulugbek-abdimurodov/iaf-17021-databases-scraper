"""MNAS (Mongolia) -> CertiFind CSVs. Usage: python prepare_certifind.py <raw_mnas.json> <dataset> [--today YYYY-MM-DD]
raw_mnas.json holds the register fields + scope tables transcribed from the scanned certificates."""
import csv, json, re, sys, importlib.util
from datetime import date
from pathlib import Path
H = Path(__file__).resolve().parent
def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
esyd = _load("esyd_prepare", H.parent / "greece/prepare_certifind.py")
prune = _load("prune_inactive", H.parent / "prune_inactive.py").prune
B, REG = "https://e-accreditation.gov.mn", "https://e-accreditation.gov.mn/login"
ROWS = {"ISO/IEC 27001": ("27006", "ISO/IEC 27006"), "ISO 22000": ("22000", "ISO 22003-1"), "ISO 37001": ("37001", "ISO/IEC 17021-9")}
ALL = "1-39"

def iaf(s):
    return {c for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", s) for c in range(int(a), int(b or a) + 1)}

def food(s):
    letters = set(re.findall(r"\b([A-K])(?:0|I{1,3}|IV)?\b", s))
    for a, b in re.findall(r"\b([A-K])[0IV]*\s*-\s*([A-K])[0IV]*\b", s):
        letters |= {chr(c) for c in range(ord(a), ord(b) + 1)}
    return sorted(letters), {c for l in letters for c in esyd.expand(esyd.FOOD_CATEGORIES[l])}

def phone(p):
    d = re.sub(r"\D", "", p)
    return f"+976 {d[:4]} {d[4:]}" if len(d) == 8 else ""

def main(src, out, today=None):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    bodies, accs, scopes, review = [], [], [], []
    for r in json.load(open(src, encoding="utf-8")):
        base = r["cert"]; ph = phone(r["phone"])
        if not ph: review.append(f"- {base}: phone '{r['phone']}' not convertible, left empty")
        bodies.append(dict(name=r["name"], country="Mongolia", registration_no=base, phone=ph, email=r["email"], website="",
                           address=r["address"], source_url=REG, verified_at=""))
        sc = dict(r["scopes"])
        for s in r.get("skipped", []):
            if s.startswith("ISO 37001"): sc["ISO 37001"] = "-"
        seen = set()
        for std, txt in sc.items():
            suf, acc = ROWS.get(std, ("", "ISO/IEC 17021-1"))
            cn = f"{base} ({suf})" if suf else base
            if cn not in seen:
                seen.add(cn)
                accs.append(dict(ab_code="MNAS", certificate_number=cn, body_name=r["name"], accreditation_standard=acc,
                                 status=r["status"].upper(), issue_date=r["issue"], expiry_date=r["expiry"], proof_url=B + r["pdf"]))
            if std == "ISO 22000":
                cats, codes = food(txt); ea = esyd.ea_spec(codes)
                note = f"ISO 22003-1 categories {txt} classified to EA ({', '.join(cats)})"
            elif txt.startswith("IAF"):
                ea, note = esyd.ea_spec(iaf(txt)), ""
            else:
                ea, note = ALL, "No sector list in the MNAS register; recorded for all EA sectors"
            scopes.append(dict(certificate_number=cn, certification_standard=std, ea_codes=ea, status=r["status"].upper(), scope_note=note))
    for n, rows in (("bodies", bodies), ("accreditations", accs), ("scopes", scopes)):
        with open(out / f"{n}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    removed = prune(out, date.fromisoformat(today) if today else None)
    with open(H / "mnas_review.md", "w", encoding="utf-8") as f:
        f.write(f"# MNAS review ({today or date.today()})\n\n"
                "- Certificates are scanned PDFs; scope tables transcribed into raw_mnas.json (see scrape_mn_mnas.py).\n"
                "- ISO/IEC 27001 and ISO 37001 have no sector list -> EA 1-39.\n"
                "- ISO 22000 categories classified with the ESYD FOOD_CATEGORIES table.\n"
                "- Not imported: mnas.gov.mn national product-certification registry (not 17021-1 accreditations); "
                "an ISO 50001 accreditation mentioned in an MNAS infographic but on no certificate.\n"
                "- MSC 08 Digital Information Assessment LLC: only city known as address; no websites in register.\n"
                + "".join(l + "\n" for l in review) + "\n## Pruned\n" + "".join(f"- {l}\n" for l in removed))
    print(f"Bodies {len(bodies)} accs {len(accs)} scopes {len(scopes)}; pruned: {removed}")

if __name__ == "__main__":
    a = sys.argv[1:]; t = a[a.index("--today") + 1] if "--today" in a else None
    main(a[0], a[1], t)
