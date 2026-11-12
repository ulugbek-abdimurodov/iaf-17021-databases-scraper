"""Convert the OUA (Uruguay) scrape snapshot into CertiFind CSVs.

Usage: python prepare_certifind.py <raw_oua.json> <dataset dir> [--today YYYY-MM-DD]

OUA issues one registration per scheme (OCSC quality, OCSGA environment, OCSST OHS, OCSGIA food).
The DB allows one accreditation per body + AB + accreditation standard, so all 17021-1 schemes are
merged under the OCSC row; ISO 22000 gets its own ISO 22003-1 row with suffix "(22000)".
"""
import argparse, csv, datetime, importlib.util, sys
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand, FOOD = esyd.ea_spec, esyd.expand, esyd.FOOD_CATEGORIES

AB = "OUA"
BASE = "https://www.organismouruguayodeacreditacion.org"
SCHEME_ROWS = {"ISO 22000": ("ISO 22003-1", "(22000)")}
COLS = {
    "bodies.csv": ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"],
    "accreditations.csv": ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"],
    "scopes.csv": ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    raw = json.load(open(a.scrape, encoding="utf-8"))
    B, A, S = [], [], []
    for b in raw["bodies"]:
        if b["cycle"][1] < a.today:
            continue
        base = b["ids"]["ISO 9001"]
        pdf = BASE + b["pdf"]
        regs = ", ".join(f"{s} {i}" for s, i in b["ids"].items())
        B.append(dict(name=b["name"], country="Uruguay", registration_no=base, phone=b["phone"], email="",
                      website=b["website"], address=b["address"], source_url=raw["register_url"], verified_at=""))
        rows = {}
        for std, reg in b["ids"].items():
            acc, suf = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", ""))
            cert = f"{base} {suf}".strip()
            if cert not in rows:
                rows[cert] = 1
                A.append(dict(ab_code=AB, certificate_number=cert, body_name=b["name"], accreditation_standard=acc,
                              status="ACTIVE", issue_date=b["cycle"][0], expiry_date=b["cycle"][1], proof_url=pdf))
            note = f"OUA registration {reg}"
            if std == "ISO 22000":
                ea = set().union(*(expand(FOOD[c[0]]) for c in b["cat22000"]))
                note += "; ISO 22003-1 categories " + ", ".join(b["cat22000"]) + " (classified to EA by sector)"
            else:
                ea = set(b["ea"][std])
            S.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea_spec(ea),
                          status="ACTIVE", scope_note=note))
    a.out.mkdir(parents=True, exist_ok=True)
    for fn, data in zip(COLS, (B, A, S)):
        with open(a.out / fn, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, COLS[fn]); w.writeheader(); w.writerows(data)
    print(f"bodies {len(B)}, accreditations {len(A)}, scopes {len(S)}")


if __name__ == "__main__":
    main()
