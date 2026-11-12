#!/usr/bin/env python3
"""Convert scraped ENAC (Spain) raw data into the CertiFind dataset.

Reads:
  raw_records.json  one object per (body x ENAC accreditation) from the register
  raw_ea.txt        annex-parsed  annex|issue(dd/mm/yyyy)|rev|ea(;)|note

Writes data/enac-spain/{bodies,accreditations,scopes}.csv and prints a 4-line
summary. Schemes with no ISO/IEC 17021-1 certifind standard are excluded and
logged in enac_review.md.
"""
import json
import re
from pathlib import Path

from certifind_common import (
    SCHEME_ACCREDITATION_MAP,
    compress_ea_codes,
    write_certifind_csvs,
)

HERE = Path(__file__).parent
OUT = HERE.parent.parent / "data" / "enac-spain"
REGISTER_URL = "https://www.enac.es/web/english/accredited-bodies/products-and-services-searchs"
AB_CODE = "ENAC"
GENERIC_EMAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "gob.es"}

# Spanish register scope text -> CertiFind certification standard (None = out of scope)
def classify(scope: str):
    s = scope
    if re.search(r"Aeroespacial", s, re.I):
        return None, "EN 9100 (aerospace quality) - not in CertiFind scheme map"
    if re.search(r"esquema TEDAE", s, re.I):
        return None, "TEDAE aerospace/defence scheme - sector scheme, not an ISO MSS"
    if re.search(r"Tac.grafos", s, re.I):
        return None, "Digital tachograph centres - regulatory scheme, not an ISO MSS"
    if re.search(r"condici.n de residuo", s, re.I):
        return None, "End-of-waste - national regulatory scheme, not an ISO MSS"
    if re.search(r"Innovaci.n", s, re.I):
        return None, "Innovation management (UNE 166002 / ISO 56002) - not in CertiFind scheme map"
    if re.search(r"Compliance", s, re.I):
        return None, "Compliance / criminal-compliance (UNE 19601 / ISO 37301) - not in CertiFind scheme map"
    if re.search(r"Forestal|PEFC", s, re.I):
        return None, "PEFC sustainable forest management - not an ISO MSS"
    if re.search(r"Antisoborno", s, re.I):
        return None, "Anti-bribery (ISO 37001) - not in CertiFind scheme map"
    if re.search(r"Homologaci.n", s, re.I):
        return None, "Vehicle type-approval - regulatory scheme, not an ISO MSS"
    if re.search(r"de Activos", s, re.I):
        return None, "Asset management (ISO 55001) - not in CertiFind scheme map"
    # in-scope ISO management system standards
    if re.search(r"Seguridad y\s*Salud", s, re.I):
        return "ISO 45001", ""
    if re.search(r"Seguridad de la Informaci", s, re.I):
        return "ISO/IEC 27001", ""
    if re.search(r"Seguridad de los Alimentos|Seguridad Alimentaria", s, re.I):
        return "ISO 22000", ""
    if re.search(r"Ambiental|Medioambiental", s, re.I):
        return "ISO 14001", ""
    if re.search(r"Energ.a", s, re.I):
        return "ISO 50001", ""
    if re.search(r"Producto Sanitario", s, re.I):
        return "ISO 13485", ""
    if re.search(r"Continuidad del Negocio", s, re.I):
        return "ISO 22301", ""
    if re.search(r"Tecnolog.as de la Informaci", s, re.I):
        return "ISO/IEC 20000-1", ""
    if re.search(r"Calidad", s, re.I):
        return "ISO 9001", ""
    return None, "unclassified scope"


def norm_date(d: str) -> str:
    d = (d or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def clean_address(raw: str) -> str:
    raw = re.sub(r"\s+", " ", (raw or "").strip())
    m = re.match(r"^(.*?)\.?\s*(\d{5})\s*-\s*(.+?)\s*\(([^)]+)\)\s*$", raw)
    if not m:
        return raw
    street, pc, city, _prov = m.groups()
    street = street.strip().rstrip(".,").strip()
    city = city.strip()
    if city.isupper():
        city = city.title()
    return f"{street}, {pc} {city}"


def website_from_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return ""
    domain = email.split("@")[-1].strip().lower()
    if not domain or domain in GENERIC_EMAIL:
        return ""
    return f"https://www.{domain}"


def main():
    records = json.loads((HERE / "raw_records.json").read_text(encoding="utf-8"))
    ea = {}
    for line in (HERE / "raw_ea.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        annex, issue, rev, codes, note = (line.split("|") + ["", "", "", "", ""])[:5]
        ea[annex] = {
            "issue": norm_date(issue),
            "rev": norm_date(rev),
            "codes": [int(c) for c in codes.split(";") if c.strip().isdigit()],
            "note": note,
        }

    bodies, accreditations, scopes = [], [], []
    review = []  # (name, num, scope, reason)
    seen_bodies = {}  # name -> body dict
    body_inscope_nums = {}  # name -> list of in-scope nums (for registration_no)

    for r in records:
        std, reason = classify(r["scope"])
        if std is None:
            review.append((r["name"], r["num"], r["scope"], reason))
            continue
        e = ea.get(r["annex"], {"issue": "", "codes": [], "note": ""})
        cert_no = r["num"]
        acc_std = SCHEME_ACCREDITATION_MAP[std][1]
        proof = f"https://www.enac.es/documents/7020/{r['annex']}"

        accreditations.append({
            "ab_code": AB_CODE,
            "certificate_number": cert_no,
            "body_name": r["name"],
            "accreditation_standard": acc_std,
            "status": "active",
            "issue_date": e["issue"],
            "expiry_date": "",
            "proof_url": proof,
        })

        if e["codes"]:
            ea_str = compress_ea_codes(e["codes"])
            note = "EA sectors (IAF/EA codes) as listed in the ENAC technical annex"
            if e["note"].startswith("food-cat"):
                note = f"Food-chain categories mapped to EA (ISO 22003-1): annex {e['note']}"
            elif e["note"].startswith("md8"):
                note = "IAF MD 8 medical-device technical areas mapped to EA codes"
        else:
            ea_str = ""
            note = "ENAC annex accredits this scheme without EA sector restriction (annex lists the standard, not sectors)"
        scopes.append({
            "certificate_number": cert_no,
            "certification_standard": std,
            "ea_codes": ea_str,
            "status": "active",
            "scope_note": note,
        })

        body_inscope_nums.setdefault(r["name"], []).append((std, cert_no))
        if r["name"] not in seen_bodies:
            seen_bodies[r["name"]] = {
                "name": r["name"],
                "country": "Spain",
                "registration_no": "",  # filled below
                "phone": (r["phone"] or "").strip(),
                "email": (r["email"] or "").strip(),
                "website": website_from_email(r["email"]),
                "address": clean_address(r["addr"]),
                "source_url": REGISTER_URL,
                "verified_at": "",
            }

    # registration_no = body's ISO 9001 number if held, else first in-scope number
    for name, body in seen_bodies.items():
        nums = body_inscope_nums[name]
        q = next((n for s, n in nums if s == "ISO 9001"), None)
        body["registration_no"] = q or nums[0][1]
        bodies.append(body)

    bodies.sort(key=lambda b: b["name"])
    OUT.mkdir(parents=True, exist_ok=True)
    write_certifind_csvs(OUT, bodies, accreditations, scopes)

    # review log of excluded schemes and of bodies dropped entirely
    kept_names = set(seen_bodies)
    all_names = {r["name"] for r in records}
    dropped_bodies = sorted(all_names - kept_names)
    lines = ["# ENAC (Spain) review - skipped schemes and bodies", ""]
    lines.append(f"Excluded accreditations (scheme not in the CertiFind ISO/IEC 17021-1 map): {len(review)}")
    lines.append("")
    lines.append("| Body | ENAC no. | Scope (ES) | Reason |")
    lines.append("| --- | --- | --- | --- |")
    for name, num, scope, reason in sorted(review):
        lines.append(f"| {name} | {num} | {scope} | {reason} |")
    lines.append("")
    lines.append(f"Bodies excluded entirely (hold only out-of-scope schemes): {len(dropped_bodies)}")
    for n in dropped_bodies:
        lines.append(f"- {n}")
    (HERE / "enac_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Bodies: {len(bodies)} | Accreditations: {len(accreditations)} | "
          f"Scopes: {len(scopes)} | Excluded: {len(review)}")


if __name__ == "__main__":
    main()
