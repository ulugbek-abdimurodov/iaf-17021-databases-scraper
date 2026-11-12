"""Convert the SAE raw dump into CertiFind CSVs (data/sae-ecuador)."""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from certifind_common import (ISO22003_TO_EA, MD8_TO_EA, compress_ea_codes,
                              resolve_cert_number, write_certifind_csvs)

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "sae-ecuador"
DATA = OUT.parent
BASE = "https://sistema.acreditacion.gob.ec"
SOURCE_URL = f"{BASE}/accreditations/scopes-public"

COUNTRY_EN = {"España": "Spain", "Perú": "Peru", "México": "Mexico"}
# Bodies already in other datasets: reuse that dataset's row exactly
REUSE = {
    "Instituto Colombiano de Normas Técnicas y Certificación (ICONTEC)": ("onac-colombia", "INSTITUTO COLOMBIANO DE NORMAS TÉCNICAS Y CERTIFICACIÓN - ICONTEC"),
    "KIWA CQR SAS": ("onac-colombia", "KIWA CQR SAS Sigla: KIWA CQR"),
    "AENOR CONFÍA S.A.U.": ("enac-spain", "AENOR CONFÍA, S.A. (Unipersonal)"),
}
ALL_EA = list(range(1, 40))
# Same legal entity listed under spelling variants
CANON = {
    "INSTITUTO COLOMBIANO DE NORMAS TECNICAS Y CERTIFICACION ICONTEC": "Instituto Colombiano de Normas Técnicas y Certificación (ICONTEC)",
    "INSTITUTO COLOMBIANO DE NORMAS TECNICAS Y CERTIFICACIÓN": "Instituto Colombiano de Normas Técnicas y Certificación (ICONTEC)",
}
CITY = {"SAE CSC 23-002": "Mexico City", "SAE CSC 10-003": "Bogotá", "SAE CSC 25-001": "Bogotá",
        "SAE CSGAS 19-001": "Madrid", "SAE CSGAS 23-001": "Buenos Aires", "SAE CSA 24-001": "Lima"}


def scheme_of(l4: str) -> str | None:
    s = (l4 or "").upper()
    if "FSSC 22000" in s:
        return "FSSC 22000"
    if "37001" in s:
        return "ISO 37001"
    for std in ("9001", "14001", "45001", "13485", "22000", "50001"):
        if f"ISO {std}" in s or f"ISO-{std}" in s:
            return f"ISO {std}"
    return None


def title(s: str) -> str:
    return s.title() if s and s.isupper() else (s or "")


def ea_for(scheme: str, l5: str, l6: str) -> list[int]:
    if scheme in ("ISO 22000", "FSSC 22000"):
        m = re.match(r"\s*(?:Categor\w*:?\s*)?([A-K])\b", l6 or "")
        return ISO22003_TO_EA.get(m.group(1), []) if m else []
    if scheme == "ISO 37001":
        return ALL_EA
    if scheme == "ISO 13485":
        # SAE technical areas: 01 non-active, 02 active non-implantable, 03 active implantable,
        # 04 IVD, 05 sterilization, 06 specific substances/technologies, 07 parts or services
        keys = list(MD8_TO_EA)
        m = re.match(r"\s*0?([1-7])\b", l5 or "")
        idx = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}
        return MD8_TO_EA[keys[idx[int(m.group(1))]]] if m else []
    m = re.match(r"\s*(?:IAF\s*)?(\d{1,2})\s*[.)]", l5 or "")
    return [int(m.group(1))] if m else []


def main() -> None:
    rows = json.loads((HERE / "raw" / "sae_rows.json").read_text(encoding="utf-8"))
    scopes_raw = json.loads((HERE / "raw" / "sae_scopes.json").read_text(encoding="utf-8"))
    by_acc = {r[1]: r for r in rows}

    eas: dict[tuple, set] = defaultdict(set)
    unmapped: dict[tuple, set] = defaultdict(set)
    excluded: dict[str, set] = defaultdict(set)
    for acc, l4, l5, l6 in scopes_raw:
        sch = scheme_of(l4)
        if not sch:
            excluded[acc].add(l4)
            continue
        codes = ea_for(sch, l5, l6)
        eas[(acc, sch)].update(codes)
        if not codes:
            unmapped[(acc, sch)].add(f"{l5} / {l6}")

    def existing(ds, nm):
        with open(DATA / ds / "bodies.csv", encoding="utf-8", newline="") as f:
            return next(r for r in csv.DictReader(f) if r["name"] == nm)

    bodies, accs, scope_eas, notes, merged = {}, {}, defaultdict(set), {}, []
    first_cert: dict[tuple, str] = {}
    for (acc, sch), codes in sorted(eas.items()):
        r = by_acc[acc]
        _, _, state, init, res, name, ph, em, web, addr, city, country, pdf = r
        name = CANON.get(name, name)
        cert, acc_std = resolve_cert_number(acc, sch)
        country_en = COUNTRY_EN.get(country, country)
        city = city or CITY.get(acc, "")
        address = ", ".join(x for x in (addr.strip().rstrip("."), title(city)) if x and title(city) not in addr)
        if not address:
            address = addr
        if web and not web.startswith("http"):
            web = "https://" + web
        if name in REUSE:
            row = existing(*REUSE[name])
            bodies.setdefault(name, dict(row))
        else:
            b = bodies.setdefault(name, {"name": name, "country": country_en, "registration_no": acc,
                                         "phone": ph or "", "email": em or "", "website": web or "",
                                         "address": address, "source_url": SOURCE_URL, "verified_at": ""})
            if not b["website"] and web:
                b["website"] = web
        bname = bodies[name]["name"]
        # uq_cb_ab_standard: one accreditation per body + AB + accreditation standard
        key = (bname, acc_std)
        if key in first_cert and first_cert[key] != cert:
            merged.append(f"{cert} ({bname}, {sch}) merged into {first_cert[key]}")
            cert = first_cert[key]
        first_cert.setdefault(key, cert)
        proof = (BASE + pdf.replace(" ", "%20")) if pdf else SOURCE_URL
        if cert not in accs:
            accs[cert] = {"ab_code": "SAE", "certificate_number": cert, "body_name": bname,
                          "accreditation_standard": acc_std,
                          "status": "ACTIVE" if state == "Activo" else "WITHDRAWN",
                          "issue_date": init or res or "", "expiry_date": "", "proof_url": proof}
        scope_eas[(cert, sch)].update(codes)
        if sch == "ISO 37001":
            notes[(cert, sch)] = "No sector list in the SAE register; recorded for all EA sectors"
        elif unmapped.get((acc, sch)):
            notes[(cert, sch)] = "Unmapped SAE sectors: " + "; ".join(sorted(unmapped[(acc, sch)]))[:300]

    # prune: active rows only; every body needs an ISO/IEC 17021-1 row
    pruned = []
    accs = {c: a for c, a in accs.items() if a["status"] == "ACTIVE"}
    keep = {a["body_name"] for a in accs.values() if a["accreditation_standard"] == "ISO/IEC 17021-1"}
    for c, a in list(accs.items()):
        if a["body_name"] not in keep:
            pruned.append(f"{c} ({a['body_name']}): no ISO/IEC 17021-1 accreditation")
            del accs[c]
    bodies = {k: b for k, b in bodies.items() if b["name"] in keep}
    scopes = [{"certificate_number": c, "certification_standard": sch,
               "ea_codes": compress_ea_codes(sorted(v)), "status": "ACTIVE",
               "scope_note": notes.get((c, sch), "")}
              for (c, sch), v in sorted(scope_eas.items()) if c in accs]
    accs = list(accs.values())

    write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
    n_ex = sum(len(v) for v in excluded.values())
    print(f"Excluded: {n_ex} scheme entries")
    with open(HERE / "sae_review.md", "w", encoding="utf-8") as f:
        f.write("# SAE review log\n\nSkipped schemes (HACCP is not in the standards table):\n\n")
        for acc in sorted(excluded):
            f.write(f"- {acc} ({by_acc[acc][5]}): {'; '.join(sorted(excluded[acc]))}\n")
        only_ex = [a for a in excluded if not any(k[0] == a for k in eas)]
        f.write("\nAccreditations excluded entirely (only out-of-scope schemes): "
                + (", ".join(sorted(only_ex)) or "none") + "\n")
        f.write("\nSkipped activities: 5 Personas (ISO/IEC 17024), 6 Productos (ISO/IEC 17065); "
                "activity 28 Energía (ISO 50001) returned no accredited bodies.\n")
        if unmapped:
            f.write("\nScope rows that could not be mapped to EA codes:\n\n")
            for (acc, sch), v in sorted(unmapped.items()):
                f.write(f"- {acc} {sch}: {'; '.join(sorted(v))[:400]}\n")
        f.write("\nMerged registrations (uq_cb_ab_standard):\n\n" + "".join(f"- {m}\n" for m in merged))
        f.write("\nRemoved by prune (no ISO/IEC 17021-1 row):\n\n" + "".join(f"- {m}\n" for m in pruned))
        f.write("\nReused body rows: " + "; ".join(f"{k} -> {v[0]}" for k, v in REUSE.items()) + "\n")
        f.write("\nNotes: the latest signed resolutions for SAE CSC 14-001 (CICAYBECE, ISO 9001) and "
                "SAE CSA 24-001 (IQC Perú, ISO 14001) are titled as suspension resolutions while the "
                "register still shows 'Activo'; kept as active, check manually.\n")


if __name__ == "__main__":
    main()
