"""Convert the TAF (Taiwan) scrape (raw/msv_*.txt) into CertiFind CSVs.
Usage: python prepare_certifind.py <scrape dir> <dataset dir> [--today YYYY-MM-DD] [--debug IDs]"""
import argparse, csv, importlib.util, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
prune_inactive = _load("prune_inactive", HERE.parent / "prune_inactive.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

LIST = "https://www.taftw.org.tw/en/find-facility/scheme/msv/"
SCOPE = "https://accreditation.taftw.org.tw/taf/public/basic/viewApplyItems.action?unitNo={}&language=EN"
BASE = "ISO/IEC 17021-1"
SCHEME_ROWS = {"ISO 22000": ("22000", "ISO 22003-1"), "ISO/IEC 27001": ("27006", "ISO/IEC 27006"),
               "ISO 50001": ("50003", "ISO 50003")}
SCHEMES = {"01": "ISO 9001", "02": "ISO 14001", "0301": "ISO 45001", "0401": "ISO 22000",
           "0501": "ISO/IEC 27001", "07": "ISO 46001"}
SKIP = {"0302": "TOSHMS (Taiwan national OSH scheme)",
        "0502": "Cyber Security Management Act scheme (Taiwan national)"}
# TAF 06xx = ISO 50003 technical areas, in the standard's order
ENERGY = {"01": "Industry – light to medium", "02": "Industry – heavy", "03": "Buildings",
          "04": "Building complexes", "05": "Transport", "06": "Mining", "07": "Agriculture",
          "08": "Energy supply"}
# Bodies already in another dataset: reuse that row exactly
EXISTING = {"MS017": ("ukas-united-kingdom", "Ares International Certification Ltd")}
ALL_EA = "1-39"


def energy_ea(label):
    low = label.lower()
    for _, keys, spec in esyd.ENERGY_AREAS:
        if any(k in low for k in keys):
            return spec
    raise KeyError(label)


def food_ea(cats):
    return ea_spec(set().union(*(expand(esyd.FOOD_CATEGORIES[c[0]]) for c in cats)))


def phone(raw, notes, cid):
    first = re.split(r"[/、,]", raw)[0]
    first = re.split(r"\s*#", first)[0]
    d = re.sub(r"\D", "", first)
    if d.startswith("09") and len(d) == 10:
        return f"+886 {d[1:4]} {d[4:7]} {d[7:]}"
    if d.startswith("02") and len(d) == 10:
        return f"+886 2 {d[2:6]} {d[6:]}"
    if d.startswith("0") and len(d) in (9, 10):
        return f"+886 {d[1]} {d[2:-4]} {d[-4:]}"
    notes.append(f"| {cid} | phone `{raw}` could not be normalised; left empty |")
    return ""


def clean_addr(a):
    a = re.sub(r",?\s*\(?R\.?O\.?C\.?\)?\s*$", "", a.strip()).strip(" ,")
    a = re.sub(r"\s+,", ",", a)
    return a if "Taiwan" in a.split(",")[-1] else a + ", Taiwan"


def existing_body(data_root, ds, name):
    with open(data_root / ds / "bodies.csv", encoding="utf-8-sig", newline="") as f:
        return next(r for r in csv.DictReader(f) if r["name"] == name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape")
    ap.add_argument("out")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--debug", default="")
    a = ap.parse_args()
    scrape, out = Path(a.scrape), Path(a.out)
    debug = set(filter(None, a.debug.split(",")))
    braw = {l.split("|")[0]: l.split("|")
            for l in (scrape / "raw/msv_bodies.txt").read_text("utf-8").splitlines() if l}
    bodies, accs, scopes, skipped, notes = [], [], [], [], []
    for line in (scrape / "raw/msv_scopes.txt").read_text("utf-8").splitlines():
        if not line:
            continue
        cid, issued, _, exp, sc = line.split("|")
        _, name, addr, ph, web, mail = braw[cid]
        groups = dict(g.split(":", 1) for g in sc.split(";") if g)
        rows, energy = [], []
        for k, v in groups.items():
            items = [x for x in v.split(",") if x]
            susp = [x[:-1] for x in items if x.endswith("#")]
            act = [x for x in items if not x.endswith("#")]
            if re.fullmatch(r"06\d\d", k):
                energy.append(ENERGY[k[2:]])
                continue
            if k in SKIP:
                skipped.append(f"| {cid} | {name} | {SKIP[k]} | national scheme |")
                continue
            std = SCHEMES.get(k)
            if std is None:
                skipped.append(f"| {cid} | {name} | TAF scheme code {k} | unknown scheme |")
                continue
            note = ""
            if std == "ISO 22000":
                ea, note = food_ea(act), f"ISO 22003-1 categories {', '.join(act)}; classified to EA"
            elif std in ("ISO/IEC 27001", "ISO 46001"):
                ea, note = ALL_EA, "No sector list in the TAF register; recorded for all EA sectors"
            else:
                ea = ea_spec({int(x) for x in act})
            if susp:
                note = (note + "; " if note else "") + f"suspended IAF {', '.join(s.lstrip('0') for s in susp)} excluded"
            if ea:
                rows.append((std, ea, note))
        if energy:
            ea = ea_spec(set().union(*(expand(energy_ea(e)) for e in energy)))
            rows.append(("ISO 50001", ea, "ISO 50003 technical areas: " + "; ".join(energy) + "; classified to EA"))
        if cid in debug:
            print(cid, name, rows)
        if not rows:
            skipped.append(f"| {cid} | {name} | all schemes | nothing importable; body dropped |")
            continue
        if cid in EXISTING:
            body = existing_body(out.parent, *EXISTING[cid])
            name = body["name"]
            notes.append(f"| {cid} | reuses body row `{name}` from {EXISTING[cid][0]} |")
        else:
            body = dict(name=name, country="Taiwan", registration_no=cid, phone=phone(ph, notes, cid), email=mail,
                        website=web, address=clean_addr(addr), source_url=LIST, verified_at="")
        bodies.append(body)
        status = "ACTIVE" if date.fromisoformat(exp.replace("/", "-")) >= a.today else "WITHDRAWN"
        seen = set()
        for std, ea, note in rows:
            suf, acc_std = SCHEME_ROWS.get(std, (None, BASE))
            num = f"{cid} ({suf})" if suf else cid
            if num not in seen:
                seen.add(num)
                accs.append(dict(ab_code="TAF", certificate_number=num, body_name=name, accreditation_standard=acc_std,
                                 status=status, issue_date=issued.replace("/", "-"), expiry_date=exp.replace("/", "-"),
                                 proof_url=SCOPE.format(cid)))
            scopes.append(dict(certificate_number=num, certification_standard=std, ea_codes=ea,
                               status="ACTIVE", scope_note=note))
    out.mkdir(parents=True, exist_ok=True)
    for fn, cols, rows in [
        ("bodies.csv", ["name", "country", "registration_no", "phone", "email", "website", "address",
                        "source_url", "verified_at"], bodies),
        ("accreditations.csv", ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status",
                                "issue_date", "expiry_date", "proof_url"], accs),
        ("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], scopes)]:
        with open(out / fn, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    removed = prune_inactive.prune(out, a.today)
    (HERE / "taf_review.md").write_text(
        "# TAF (Taiwan) review log\n\n## Skipped schemes / bodies\n\n| ID | Body | Scheme | Reason |\n|---|---|---|---|\n"
        + "\n".join(skipped) + "\n\n## Notes\n\n| ID | Note |\n|---|---|\n" + "\n".join(notes)
        + "\n\n## Pruned (prune_inactive)\n\n" + "\n".join(f"- {r}" for r in removed) + "\n", "utf-8")
    print(f"bodies {len(bodies)} accs {len(accs)} scopes {len(scopes)}; pruned {len(removed)}")
    for r in removed:
        print(" ", r)


if __name__ == "__main__":
    main()
