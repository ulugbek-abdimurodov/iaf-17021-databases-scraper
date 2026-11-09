"""Convert raw/kz_nca_ms_bodies.json (from scrape_kz_nca.py) into the CertiFind dataset."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (ISO22003_TO_EA, ISO50003_TO_EA, compress_ea_codes,  # noqa: E402
                              resolve_cert_number, write_certifind_csvs)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw" / "kz_nca_ms_bodies.json"
OUT = ROOT / "data" / "nca-kazakhstan"
BASE = "https://techreg.kezekte.kz"
SOURCE_URL = BASE + "/ru/acc/subjects"

SCHEMES = {"ISO 9001": "ISO 9001", "ISO 14001": "ISO 14001", "ISO 45001": "ISO 45001",
           "ISO 50001": "ISO 50001", "22000": "ISO 22000", "ISO/IEC 27001": "ISO/IEC 27001",
           "ISO/IEC 20000-1": "ISO/IEC 20000-1"}
SKIPPED = {"OHSAS 18001": "withdrawn standard (replaced by ISO 45001)",
           "29001": "ISO/TS 29001 (oil & gas sector QMS) not in CertiFind scheme list",
           "1179": "ST RK 1179 (national HACCP standard)", "1352": "ST RK 1352 (social responsibility)",
           "12.0.003": "GOST/ST RK 12.0.x national OHS standard", "12.0.004": "GOST/ST RK 12.0.x national OHS standard",
           "12.0.230": "GOST/ST RK 12.0.x national OHS standard", "LEGACY": "generic NACE table without scheme"}
CAT22003 = [("Животн", "A"), ("Растен", "B"), ("Производство пищев", "C"), ("Производство кормо", "D"),
            ("Организация питани", "E"), ("Распределение", "F"), ("Предоставление тра", "G"), ("Услуги", "H"),
            ("Производство упако", "I"), ("Производство обору", "J"), ("Производство (био)", "K")]
AREA50003 = {"Промышле": "A", "Тяжелая": "A", "Здания": "B", "Комплекс": "B", "Транспор": "E",
             "Горное д": "F", "Сельское": "G", "Энергоре": "D"}
STATUS = {"Действует": "active", "Отозван": "withdrawn", "Прекращен": "terminated", "Возобновлен": "active"}


def iso(d):
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d") if d else ""


def clean_name(n):
    n = n.strip().strip('"').replace('""', '"')
    form = "JSC" if re.search(r"(?i)акционерное общество", n) else "LLP"
    n = re.sub(r"(?i)^товарищество с ограниченной ответственностью\s*", "", n)
    n = re.sub(r"(?i)^акционерное общество\s*", "", n)
    n = re.sub(r"(?i)\s*жауапкершілігі шектеулі серіктестігі$", "", n)
    n = n.strip().strip('"').strip()
    if n.count('"') % 2:
        n += '"'
    return f"{n} {form}"


def contact(c, key):
    m = re.search(key + r":\s*(.+)", c)
    return m.group(1).strip() if m else ""


def address(c):
    a = contact(c, "Фактический адрес") or contact(c, "Юридический адрес")
    a = a.split(";")[0]
    a = re.sub(r"^(Казахстан|РК),\s*", "", a)
    return re.sub(r"\s+", " ", a).strip(" ,.")


def scope_ea(key, v):
    iaf, cats, zones, _ = v
    if key == "22000":
        letters = set()
        for c in cats.split("/"):
            c = c.replace("А -", "A -").replace("В -", "B -").strip()
            m = re.match(r"^([A-K]) -", c)
            letters.add(m.group(1) if m else next((L for p, L in CAT22003 if c.startswith(p) or p in c), ""))
        letters.discard("")
        ea = [e for L in letters for e in ISO22003_TO_EA[L]]
        return compress_ea_codes(ea), "ISO 22003-1 categories " + ", ".join(sorted(letters)) + " classified to EA"
    if key == "ISO 50001":
        areas = sorted({AREA50003[z] for z in zones.split("/") if z in AREA50003})
        ea = [e for L in areas for e in ISO50003_TO_EA[L]]
        return compress_ea_codes(ea), "ISO 50003 technical areas " + ", ".join(areas) + " classified to EA"
    if key in ("ISO/IEC 27001", "ISO/IEC 20000-1"):
        return "", "Annex lists the standard without sector restriction"
    return iaf, "IAF/EA sectors as listed in the NCA scope annex" if iaf else "No sectors listed in annex"


def main():
    data = json.loads(RAW.read_text(encoding="utf-8"))
    bodies, accs, scopes, review = {}, [], [], []
    seen = set()
    for vid, num, start, end, status, bin_, name, contacts, sc in data:
        if num in seen:
            continue
        seen.add(num)
        st = STATUS.get(status, status.lower())
        bname = clean_name(name)
        if st != "active":
            review.append(f"- {num} {bname} (BIN {bin_}): accreditation {status} (valid {start}–{end}); not imported")
            continue
        if not sc:
            review.append(f"- {num} {bname}: no scope tables on register page; not imported")
            continue
        for k in sc:
            if k in SKIPPED:
                review.append(f"- {num} {bname}: skipped scheme {k} — {SKIPPED[k]}")
        inscope = {k: v for k, v in sc.items() if k in SCHEMES}
        if not inscope:
            review.append(f"- {num} {bname}: only out-of-scope schemes; body excluded")
            continue
        bodies[bin_] = {"name": bname, "country": "Kazakhstan", "registration_no": num,
                        "phone": contact(contacts, "Телефон"), "email": contact(contacts, "Email"),
                        "website": "", "address": address(contacts), "source_url": SOURCE_URL, "verified_at": ""}
        proof = f"{BASE}/ru/acc/subjects/verifications/download/{vid}"
        acc_done = set()
        for k, v in inscope.items():
            std = SCHEMES[k]
            cert, acc_std = resolve_cert_number(num, std)
            if cert not in acc_done:
                acc_done.add(cert)
                accs.append({"ab_code": "NCA", "certificate_number": cert, "body_name": bname,
                             "accreditation_standard": acc_std, "status": st, "issue_date": iso(start),
                             "expiry_date": iso(end), "proof_url": proof})
            ea, note = scope_ea(k, v)
            scopes.append({"certificate_number": cert, "certification_standard": std, "ea_codes": ea,
                           "status": st, "scope_note": note})

    write_certifind_csvs(OUT, list(bodies.values()), accs, scopes)
    excluded = sum(1 for r in review if "not imported" in r or "excluded" in r)
    print(f"Excluded: {excluded}")
    (Path(__file__).parent / "nca_review.md").write_text(
        "# NCA (Kazakhstan) review log\n\nSkipped registrations and schemes from "
        f"{SOURCE_URL} (activity type: ОПС системы менеджмента).\n\n" + "\n".join(review) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
