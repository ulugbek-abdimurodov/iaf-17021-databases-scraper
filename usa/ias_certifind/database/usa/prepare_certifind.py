"""Convert the IAS (International Accreditation Service, USA) MSCB raw dump into CertiFind CSVs.

Input : raw/ias_raw.txt  (one line per MSCB registration, produced by scrape_us_ias.py)
Output: data/ias-usa/{bodies,accreditations,scopes}.csv
"""
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (ISO22003_TO_EA, MD8_TO_EA, compress_ea_codes,  # noqa: E402
                              resolve_cert_number, write_certifind_csvs)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw" / "ias_raw.txt"
OUT = ROOT / "data" / "ias-usa"
REGISTER = "https://www.iasonline.org/search-accredited-organizations-2/"
PDF_BASE = "https://www.iasonline.org/wp-content/uploads/"

COUNTRIES = {
    "AE": "United Arab Emirates", "AL": "Albania", "AU": "Australia", "BG": "Bulgaria", "BR": "Brazil",
    "CA": "Canada", "CL": "Chile", "CN": "China", "CY": "Cyprus", "GB": "United Kingdom", "GR": "Greece",
    "HK": "Hong Kong", "HR": "Croatia", "IN": "India", "JP": "Japan", "KR": "South Korea", "MN": "Mongolia",
    "MX": "Mexico", "NG": "Nigeria", "OM": "Oman", "QA": "Qatar", "RO": "Romania", "SA": "Saudi Arabia",
    "SG": "Singapore", "SM": "San Marino", "TR": "Turkey", "TW": "Taiwan", "US": "United States",
}
STD = {"I9001": "ISO 9001", "I14001": "ISO 14001", "I45001": "ISO 45001", "I13485": "ISO 13485",
       "I22000": "ISO 22000", "I50001": "ISO 50001", "I/27001": "ISO/IEC 27001", "I/27701": "ISO/IEC 27701",
       "SO/IEC 27701": "ISO/IEC 27701", "I/20000-1": "ISO/IEC 20000-1", "I22301": "ISO 22301"}
MD8_KEYS = list(MD8_TO_EA)  # Table A1.1 .. A1.7 in IAF MD 8 order
UPPER_KEEP = {"USA", "U.S.A.", "UK", "PO", "P.O.", "NW", "NE", "SW", "SE", "R&D", "PC:", "LLC"}


def iso(d: str) -> str:
    d = d.replace(" ", "")
    for f in ("%B%d,%Y", "%b%d,%Y"):
        try:
            return datetime.strptime(d, f).date().isoformat()
        except ValueError:
            pass
    return ""


def clean_addr(a: str) -> str:
    a = a.replace("§", "&")
    a = re.sub(r"\s+-\s+", "-", a)
    a = re.sub(r"\s+,", ",", a)
    a = re.sub(r"\s{2,}", " ", a).strip(" ,;")
    a = ", ".join(p.strip(" ,") for p in a.split(";") if p.strip(" ,"))
    if sum(c.isupper() for c in a) > sum(c.islower() for c in a):
        a = " ".join(w if w in UPPER_KEEP or re.search(r"\d", w) else w.title() for w in a.split(" "))
    return a


def clean_web(w: str) -> str:
    w = w.strip().lower().rstrip("/")
    if not w or w == "w.website.com":
        return ""
    w = re.sub(r"^w\.", "www.", w)
    return w if w.startswith("http") else "https://" + w


def main() -> None:
    bodies, accs, scopes, excluded, skipped_bodies = [], [], [], {}, []
    for line in RAW.read_text(encoding="utf-8").splitlines():
        f = line.split("|")
        if len(f) < 11 or not f[0].isdigit():
            continue
        num, exp, name, cc, status, pdf, addr, web, eff, since, sch = f[:11]
        reg = f"MSCB-{num}"
        name = name.replace("§", "&").strip()
        pdf_url = PDF_BASE + (pdf.replace("~", "-Cert.pdf") if pdf.endswith("~") else pdf)
        st = "suspended" if status.lower().startswith("suspended") else "active"
        merged: dict[str, dict] = {}
        for part in filter(None, sch.split(";")):
            p = (part.split("~") + ["", "", ""])[:4]
            key = p[0].strip()
            std = "FSSC 22000" if key.startswith("FSSC") else STD.get(key)
            if not std:
                excluded.setdefault(re.sub(r"^I/", "ISO/IEC ", re.sub(r"^I(?=\d)", "ISO ", key)), []).append(reg)
                continue
            m = merged.setdefault(std, {"ea": set(), "note": ""})
            if std in ("ISO 9001", "ISO 14001", "ISO 45001"):
                for r in filter(None, p[1].split(",")):
                    a, _, b = r.partition("-")
                    m["ea"].update(range(int(a), int(b or a) + 1))
                m["note"] = "IAF/EA sectors as listed in the IAS scope of accreditation"
            elif std == "ISO 13485":
                tabs = sorted({int(t) for t in p[2].split(",") if t})
                for t in tabs:
                    m["ea"].update(MD8_TO_EA[MD8_KEYS[t - 1]])
                m["note"] = "Classified to EA from IAF MD 8 main technical areas (" + "; ".join(MD8_KEYS[t - 1] for t in tabs) + ")"
            elif std in ("ISO 22000", "FSSC 22000"):
                cats = sorted({c for c in p[3].split(",") if c})
                for c in cats:
                    m["ea"].update(ISO22003_TO_EA[c])
                m["note"] = "Classified to EA from ISO/TS 22003-1 food chain categories " + ", ".join(cats)
            else:
                m["note"] = "No sectors listed (Certification Sectors – N/A)"
        if not merged:
            skipped_bodies.append(f"{reg} {name} ({COUNTRIES.get(cc, cc)}): only {', '.join(sorted({k for k, v in excluded.items() if reg in v})) or 'no parsable scheme'}")
            continue
        bodies.append({"name": name, "country": COUNTRIES.get(cc, cc), "registration_no": reg, "phone": "",
                       "email": "", "website": clean_web(web), "address": clean_addr(addr),
                       "source_url": REGISTER, "verified_at": ""})
        seen = set()
        for std, m in merged.items():
            cert, acc_std = resolve_cert_number(reg, std)
            if cert not in seen:
                seen.add(cert)
                accs.append({"ab_code": "IAS", "certificate_number": cert, "body_name": name,
                             "accreditation_standard": acc_std, "status": st, "issue_date": iso(eff),
                             "expiry_date": iso(exp), "proof_url": pdf_url})
            scopes.append({"certificate_number": cert, "certification_standard": std,
                           "ea_codes": compress_ea_codes(m["ea"]), "status": st, "scope_note": m["note"]})
    write_certifind_csvs(OUT, bodies, accs, scopes)
    print(f"Excluded: {len(skipped_bodies)} bodies, {sum(len(v) for v in excluded.values())} scheme rows")
    review = Path(__file__).parent / "ias_review.md"
    lines = ["# IAS review log", "", "## Bodies not imported (only out-of-scope schemes)", ""]
    lines += [f"- {s}" for s in skipped_bodies] or ["- none"]
    lines += ["", "## Schemes skipped (no CertiFind accreditation-standard mapping)", ""]
    lines += [f"- {k}: {len(v)} — {', '.join(v)}" for k, v in sorted(excluded.items())]
    lines += ["", "## Other notes", "",
              "- Register row 'IGNYTE ASSURANCE LLC.' without a certificate link was a duplicate of MSCB-391; dropped.",
              "- Suspended bodies (MSCB-277, -294, -335, -360): imported with status `suspended`; address left empty because the suspension watermark replaces page 1.",
              "- Country is the register's country column (e.g. MSCB-283 listed SA with a Chinese address, MSCB-218 listed IN with a US address).",
              "- ISO 50001 / 27001 / 27701 / 20000-1 / 22301 scopes carry no sectors in IAS annexes, so `ea_codes` is empty.",
              "- Spurious 'Table A1.x' / letter matches outside ISO 13485 / ISO 22000 blocks were ignored."]
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
