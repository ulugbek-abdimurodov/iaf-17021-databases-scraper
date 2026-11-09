"""Convert the SLAB (Sri Lanka) scrape into a CertiFind dataset.

Usage: python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]

<scrape folder> holds database/sri_lanka/slab_raw.tsv (registry rows) and txt/<pdf>.txt
(text of the scope schedule PDFs, dumped with pdfplumber). The schedules merge IAF cells
across rows, so the sector codes below were transcribed by hand from each schedule and are
mapped to EA with the ESYD tables. HACCP against SLS 1266 (a Sri Lankan national standard)
is skipped.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", ROOT / "greece" / "prepare_certifind.py")
sys.path.insert(0, str(ROOT))
from prune_inactive import prune  # noqa: E402

AB = "SLAB"
PREFIX_STD = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001",
              "FMS": "ISO 22000", "ENS": "ISO 50001", "IMS": "ISO/IEC 27001"}
SCHEME_ROWS = {"ISO 22000": ("ISO 22003-1", "22000"), "ISO 50001": ("ISO 50003", "50003"),
               "ISO/IEC 27001": ("ISO/IEC 27006", "27006")}

# IAF codes per registration, transcribed from the scope schedules (2026-11-09).
IAF = {
    "QMS 001-01": "3-8;12-15;17;19;25;28;30-32;35-37",
    "QMS 002-01": "1;3-4;14;29;31",
    "QMS 004-01": "3-4;14-15;22;28",
    "QMS 010-01": "4;19",
    "QMS 013-01": "1;3-7;10;14;17;22-23;28-30;32-37",
    "QMS 014-01": "3",
    "EMS 001-01": "3-5;12-15;19;25;28-30;32",
    "EMS 002-01": "1;3-4;14;24;30-31;39",
    "EMS 004-01": "4",
    "EMS 010-01": "28-29;31;34",
    "EMS 013-01": "1;3-7;10;14;17;22-23;28-30;32-37",
    "OHS 001-01": "1-4;9;12-17;19-20;23;25;28-29;31;35",
    "OHS 002-01": "3",
    "OHS 004-01": "4;7;12;23",
    "OHS 010-01": "15;17;23",
    "OHS 013-01": "34",
}
# ISO 22003-1 categories under ISO 22000 (HACCP / SLS 1266 rows ignored).
FOOD = {
    "FMS 001-01": "A C D E F G H I",
    "FMS 002-01": "C D E F G I K",
    "FMS 004-01": "C E I",
    "FMS 009-01": "C E F",
    "FMS 010-01": "C E G",
    "FMS 012-01": "C",
    "FMS 014-01": "C",
}
ENERGY = {
    "ENS 001-01": "A B C D E G H",
    "ENS 002-01": "A",
    "ENS 010-01": "A",
}
NOTES = {
    "IMS 010-01": "No sector list in the SLAB register; recorded for all EA sectors",
    "QMS 013-01": "IAF 10 (NACE 19) read from a merged table cell; check schedule",
    "EMS 013-01": "IAF 10 (NACE 19) read from a merged table cell; check schedule",
}


def ea_codes(cert: str) -> str:
    if cert in IAF:
        return IAF[cert]
    if cert in FOOD:
        return esyd.ea_spec(set().union(*(esyd.expand(esyd.FOOD_CATEGORIES[c]) for c in FOOD[cert].split())))
    if cert in ENERGY:
        areas = {a: spec for a, _, spec in esyd.ENERGY_AREAS}
        return esyd.ea_spec(set().union(*(esyd.expand(areas[c]) for c in ENERGY[cert].split())))
    return "1-39"


def address(txt: Path) -> str:
    if not txt.exists():
        return ""
    lines = txt.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines):
        if l.startswith("Accreditation Number"):
            out = []
            for l2 in lines[i + 2:]:
                if l2.startswith("Scope of Accreditation"):
                    break
                out.append(l2.strip().rstrip(".,"))
            return ", ".join(out)
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()

    rows = [l.split("\t") for l in (args.scrape / "database/sri_lanka/slab_raw.tsv")
            .read_text(encoding="utf-8").splitlines() if l.strip()]
    order = ["QMS", "EMS", "OHS", "FMS", "ENS", "IMS"]
    rows.sort(key=lambda r: (order.index(r[0][:3]), r[0]))

    bodies, accs, scopes, review = {}, {}, [], []
    base_cert = {}  # body -> certificate number of its ISO/IEC 17021-1 row
    for cert, name, web, issue, expiry, pdf in (r[:6] for r in rows):
        std = PREFIX_STD[cert[:3]]
        proof = f"https://www.slab.lk/media/file/{pdf}"
        if name not in bodies:
            bodies[name] = {"name": name, "country": "Sri Lanka", "registration_no": cert.split()[1][:3],
                            "phone": "", "email": "", "website": web,
                            "address": address(args.scrape / "txt" / (pdf[:-4] + ".txt")),
                            "source_url": "https://www.slab.lk/directory/registry/" + cert.replace(" ", "+"),
                            "verified_at": ""}
        if name not in base_cert:
            base_cert[name] = cert
            accs[cert] = [AB, cert, name, "ISO/IEC 17021-1", "ACTIVE", issue, expiry, proof]
        elif cert[:3] in ("QMS", "EMS", "OHS"):
            review.append(f"- {cert}: merged into {base_cert[name]} (one ISO/IEC 17021-1 row per body).")
        if std in SCHEME_ROWS:
            acc_std, suffix = SCHEME_ROWS[std]
            sc = f"{cert} ({suffix})"
            accs[sc] = [AB, sc, name, acc_std, "ACTIVE", issue, expiry, proof]
        else:
            sc = base_cert[name]
        scopes.append([sc, std, ea_codes(cert), "ACTIVE", NOTES.get(cert, "")])
        if cert[:3] == "FMS":
            review.append(f"- {cert}: HACCP against SLS 1266 (national standard) skipped where listed.")

    args.out.mkdir(parents=True, exist_ok=True)

    def write(fn, header, data):
        with open(args.out / fn, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data)

    write("bodies.csv", list(next(iter(bodies.values()))), [list(b.values()) for b in bodies.values()])
    write("accreditations.csv", ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                                 "status", "issue_date", "expiry_date", "proof_url"], accs.values())
    write("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status",
                         "scope_note"], scopes)
    removed = prune(args.out, args.today)
    (HERE / "slab_review.md").write_text(
        f"# SLAB review ({args.today})\n\n" + "\n".join(review + [f"- pruned: {r}" for r in removed])
        + f"\n\n{len(bodies)} bodies, {len(accs)} accreditations, {len(scopes)} scope rows.\n",
        encoding="utf-8")
    print(f"{len(bodies)} bodies, {len(accs)} accreditations, {len(scopes)} scopes, pruned {len(removed)}")


if __name__ == "__main__":
    main()
