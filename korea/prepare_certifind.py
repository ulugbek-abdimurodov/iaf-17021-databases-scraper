"""KAB (Korea Accreditation Board) -> CertiFind CSVs.
Usage: python prepare_certifind.py <kab_raw.txt> <dataset dir> [--today YYYY-MM-DD]
kab_raw.txt (from scrape_kr_kab.py): 'B|orgIdx|name|abbr|phone|web|address' then
'<scheme>|<acc no>|<issue date>||<sector field>' lines."""
import argparse, csv, importlib.util, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand
ALL = set(range(1, 40))
VIEW = "https://eng.kab.or.kr/eng/kcn/kcn/view.do?orgIdx={}&menuNo=500044"

STD = {"9001": "ISO 9001", "14001": "ISO 14001", "45001": "ISO 45001", "13485": "ISO 13485",
       "22000": "ISO 22000", "FSSC 22000": "FSSC 22000", "50001": "ISO 50001",
       "27001": "ISO/IEC 27001", "27701": "ISO/IEC 27701", "22301": "ISO 22301",
       "37001": "ISO 37001", "37301": "ISO 37301", "19443": "ISO 19443", "42001": "ISO/IEC 42001",
       "21001": "ISO 21001", "KS Q 9100": "AS 9100"}
SCHEME_ROWS = {"ISO/IEC 27001": ("ISO/IEC 27006", "27006"), "ISO/IEC 27701": ("ISO/IEC 27006", "27006"),
               "ISO 50001": ("ISO 50003", "50003"), "ISO 22000": ("ISO 22003-1", "22000"),
               "FSSC 22000": ("ISO 22003-1", "22000"), "ISO/IEC 20000-1": ("ISO/IEC 20000-6", "20000"),
               "ISO/IEC 42001": ("ISO/IEC 42006", "42001"), "ISO 22301": ("ISO/IEC 17021-6", "22301"),
               "ISO 37001": ("ISO/IEC 17021-9", "37001"), "ISO 55001": ("ISO/IEC 17021-5", "55001"),
               "ISO 39001": ("ISO/IEC 17021-7", "39001"), "AS 9100": ("AS 9104-1", "9104")}
# KAB ISO 13485 letters follow IAF MD 8 order: A non-active, B active non-implantable,
# C active implantable, D IVD, E sterilization, F specific substances, G parts/services.
MD8 = dict(zip("ABCDEFG", [esyd.MEDICAL_AREAS[i] for i in (0, 2, 1, 3, 4, 5, 6)]))
NOTE_ALL = "No sector list in the KAB register; recorded for all EA sectors"


def sectors(std, raw):
    if raw.startswith("#"):
        note = "IAF codes as listed in the KAB register"
        if std == "AS 9100":
            note += " (accredited as KS Q 9100, the Korean adoption of AS 9100)"
        return expand(raw[1:]), note
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted(set(re.findall(r"\(/?([A-K])", raw.replace("/(", "("))))
        ea = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
        return ea, f"ISO 22003-1 categories {', '.join(cats)} (classified to EA by sector)"
    if std == "ISO 13485":
        lets = sorted(set(re.findall(r"(?:^|,)([A-G])\(", raw)))
        ea = set().union(*(expand(MD8[l][2]) for l in lets))
        return ea, "ISO 13485 main technical areas: " + "; ".join(MD8[l][0] for l in lets) + " (classified to EA by sector)"
    if std == "ISO 22301":
        nums = {int(n) for n in re.findall(r"\d+", raw)} & ALL
        if nums:
            return nums, f"EA codes from the KAB ISO 22301 sector groups {raw}"
        return ALL, f"KAB ISO 22301 sector group {raw} without EA numbers; recorded for all EA sectors"
    note = NOTE_ALL + (f" (KAB categories {raw})" if raw else "")
    return ALL, note


def intl(phone):
    d = re.sub(r"\D", "", phone)
    if not d.startswith("0"):
        return ""
    d = d[1:]
    if d.startswith("2"):
        a, rest = "2", d[1:]
    else:
        a, rest = d[:2], d[2:]
    return f"+82 {a} {rest[:-4]} {rest[-4:]}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("raw"); p.add_argument("out")
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    bodies, accs, scopes, review = [], {}, [], []
    body = None
    for line in Path(a.raw).read_text(encoding="utf-8").splitlines():
        f = line.split("|")
        if f[0] == "B":
            _, oid, name, _abbr, ph, web, addr = f
            web = "https://www." + web[2:] if web.startswith("w:") else web
            phone = intl(ph)
            if not phone:
                review.append(f"- {name}: phone {ph} could not be made international; left empty")
            body = dict(name=name, country="South Korea", registration_no="", phone=phone, email="",
                        website=web, address=addr, source_url=VIEW.format(oid), verified_at="")
            bodies.append(body)
            continue
        key, accno, issued, _, raw = f
        accno = "KAB-" + accno
        std = STD.get(key)
        if not std:
            review.append(f"- {body['name']}: skipped {key} ({accno}) - not in the standards table")
            continue
        if key == "9001":
            body["registration_no"] = accno
        acc_std, suffix = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", ""))
        k = (body["name"], acc_std)
        if k not in accs:  # uq_cb_ab_standard: first KAB number per body+accreditation standard
            cert = f"{accno} ({suffix})" if suffix else accno
            accs[k] = dict(ab_code="KAB", certificate_number=cert, body_name=body["name"],
                           accreditation_standard=acc_std, status="ACTIVE", issue_date=issued,
                           expiry_date="", proof_url=body["source_url"])
        else:
            accs[k]["issue_date"] = min(accs[k]["issue_date"], issued)
        ea, note = sectors(std, raw)
        if accs[k]["certificate_number"].split(" ")[0] != accno:
            note += f"; KAB accreditation {accno}"
        scopes.append(dict(certificate_number=accs[k]["certificate_number"], certification_standard=std,
                           ea_codes=ea_spec(ea), status="ACTIVE", scope_note=note))
    for b in bodies:
        if not b["registration_no"]:
            b["registration_no"] = next(x["certificate_number"] for x in accs.values() if x["body_name"] == b["name"])
    def w(name, rows):
        with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    w("bodies", bodies); w("accreditations", list(accs.values())); w("scopes", scopes)
    from prune_inactive import prune
    removed = prune(out, a.today)
    rv = ["# KAB review", "", *review, "", "## Removed by prune_inactive", "", *(f"- {r}" for r in removed or ["none"])]
    (HERE / "kab_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    print(f"bodies {len(bodies)}, accreditations {len(accs)}, scopes {len(scopes)}, removed {len(removed)}")


if __name__ == "__main__":
    main()
