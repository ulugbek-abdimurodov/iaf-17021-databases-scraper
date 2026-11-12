#!/usr/bin/env python3
"""Convert the EMA (Entidad Mexicana de Acreditación) register scrape into a CertiFind dataset.

Input: the scrape folder containing raw/ema_register.txt (written by scrape_mx_ema.py, three
blocks separated by "#" lines: body names / registrations "id~nameIdx~yyyymmdd~status~codes" /
client records "id~name~expiry~email~url~address"). EMA publishes scheme codes per registration
(SGC, SGA, SASST...) but no IAF/EA sectors, so every scope is recorded for EA 1-39.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug NAMES]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
AB_CODE = "EMA"
BASE = "ISO/IEC 17021-1"
SOURCE_URL = "https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the EMA register; recorded for all EA sectors"

# EMA scheme code -> CertiFind certification standard
SCHEME = {
    "SGC": "ISO 9001", "SGA": "ISO 14001", "SASST": "ISO 45001", "SGSST": "ISO 45001",
    "SGSI": "ISO/IEC 27001", "SGTI": "ISO/IEC 20000-1", "SGCN": "ISO 22301", "SGIA": "ISO 22000",
    "SGDM": "ISO 13485", "SGE": "ISO 50001", "SGAS": "ISO 37001", "SGCM": "ISO 37301",
    "SGOE": "ISO 21001", "SGS": "ISO 28000", "SGSP": "ISO 18788", "SGSV": "ISO 39001",
    "MSAI": "ISO/IEC 42001",
}
# certification standard -> (accreditation standard, certificate suffix)
SCHEME_ROWS = {
    "ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
    "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
    "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
    "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
    "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
    "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104"),
}
# Bodies outside Mexico (register gives no or an "Extranjero" address)
COUNTRY = {
    "Perry Johnson Registrars, Inc.": "United States",
    "BSI Group America Inc.": "United States",
    "ABS Quality Evaluations, Inc": "United States",
    "American Registrar of Management Systems, LLC": "United States",
    "INSTITUTO BOLIVIANO DE NORMALIZACION Y CALIDAD": "Bolivia",
    "Instituto Dominicano para la Calidad (INDOCAL)": "Dominican Republic",
}
# Bodies already in another dataset: reuse that row exactly (dataset, name there)
REUSE = {
    "EQA GROUP S.A. DE C.V.": ("sae-ecuador", "EQA GROUP S.A. DE C.V."),
    "Perry Johnson Registrars, Inc.": ("jab-japan", "Perry Johnson Registrars, Inc."),
}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def clean_name(s: str) -> str:
    return re.sub(r"\s+,", ",", re.sub(r"\s+", " ", s)).strip()


def clean_id(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .")


def clean_addr(a: str) -> str:
    a = re.sub(r",\s*,?\s*Extranjero, CP\. 99999, Extranjero", "", a).strip(" ,")
    parts = [p.strip() for p in a.split(",") if p.strip()]
    return ", ".join(p.title() if p.isupper() and len(p) > 3 else p for p in parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", default="")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data_root = args.out.parent

    raw = (args.scrape / "raw" / "ema_register.txt").read_text(encoding="utf-8")
    names, regs, clients_raw = (b.strip("\n").split("\n") for b in raw.split("\n#\n"))
    clients: dict[str, dict] = {}
    expiry: dict[str, str] = {}
    for line in clients_raw:
        acc, name, exp, email, url, addr = line.split("~")
        clients.setdefault(clean_name(name).upper(), {"email": email.strip(), "website": url.strip(),
                                                      "address": clean_addr(addr)})
        expiry[clean_id(acc)] = exp

    review: list[str] = []
    skipped: dict[str, list[str]] = defaultdict(list)
    # body -> ordered list of (reg id, start date, [standards])
    per_body: dict[str, list[tuple[str, str, list[tuple[str, str]]]]] = defaultdict(list)
    for line in regs:
        acc, ni, d, _status, codes = line.split("~")
        name, rid = clean_name(names[int(ni)]), clean_id(acc)
        start = f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else ""
        stds = []
        for code in codes.split(","):
            if code in SCHEME:
                stds.append((SCHEME[code], code))
            else:
                skipped[code].append(f"{name} ({rid})")
        per_body[name].append((rid, start, stds))

    bodies, accs, scopes = {}, {}, {}
    debug = {d.strip().casefold() for d in args.debug.split(",") if d.strip()}
    for name, items in per_body.items():
        importable = [it for it in items if it[2]]
        if not importable:
            review.append(f"{name}: no importable scheme ({', '.join(i[0] for i in items)}); dropped")
            continue
        base = min(importable, key=lambda it: it[1] or "9999")[0]  # earliest-issued registration
        if len(items) > 1:
            review.append(f"{name}: EMA registrations {', '.join(i[0] for i in items)} merged under {base}")
        if name in REUSE:
            ds, nm = REUSE[name]
            with open(data_root / ds / "bodies.csv", encoding="utf-8-sig", newline="") as f:
                row = next(r for r in csv.DictReader(f) if r["name"] == nm)
            bodies[nm] = dict(row)
            body_name = nm
            review.append(f"{name}: reuses body row from {ds}")
        else:
            c = clients.get(name.upper(), {})
            country = COUNTRY.get(name, "Mexico")
            if not c:
                review.append(f"{name}: no client record in the register (no address/email)"
                              + ("" if name in COUNTRY else "; country taken as Mexico"))
            if name in bodies:
                raise SystemExit(f"duplicate body name {name}")
            bodies[name] = {"name": name, "country": country, "registration_no": base, "phone": "",
                            "email": c.get("email", ""), "website": c.get("website", ""),
                            "address": c.get("address", ""), "source_url": SOURCE_URL, "verified_at": ""}
            body_name = name
        for rid, start, stds in importable:
            for std, code in stds:
                acc_std, suffix = SCHEME_ROWS.get(std, (BASE, ""))
                cert = f"{base} ({suffix})" if suffix else base
                a = accs.setdefault(cert, {"ab_code": AB_CODE, "certificate_number": cert, "body_name": body_name,
                                           "accreditation_standard": acc_std, "status": "ACTIVE",
                                           "issue_date": start, "expiry_date": "", "proof_url": SOURCE_URL})
                if start and (not a["issue_date"] or start < a["issue_date"]):
                    a["issue_date"] = start
                exp = expiry.get(rid, "")
                if exp and exp > a["expiry_date"]:
                    a["expiry_date"] = exp
                s = scopes.setdefault((cert, std), {"certificate_number": cert, "certification_standard": std,
                                                    "ea_codes": "1-39", "status": "ACTIVE", "notes": []})
                s["notes"].append(f"{code} {rid}")
        if name.casefold() in debug:
            print(name, items)

    scope_rows = [{**{k: v for k, v in s.items() if k != "notes"},
                   "scope_note": f"{ALL_NOTE} (EMA {', '.join(s['notes'])})"} for s in scopes.values()]
    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(bodies.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS, sorted(accs.values(), key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(bodies), len(accs), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "ema_review.md", "w", encoding="utf-8") as f:
        f.write(f"# EMA conversion review\n\nGenerated {args.today}: {counts[0]} bodies, {counts[1]} accreditations, "
                f"{counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Scheme codes not imported (code: registrations)\n\n"
                "Codes without a name in the register and not identifiable to a standard in the standards table.\n\n")
        for code, ids in sorted(skipped.items()):
            f.write(f"- {code}: {'; '.join(ids)}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'ema_review.md'}")


if __name__ == "__main__":
    main()
