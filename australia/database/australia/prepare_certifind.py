"""Convert raw/jasanz_cabs.json (JASANZ register API scrape) into CertiFind CSVs + review log.

Usage: python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD] [--debug ACCNO ...]
"""
import argparse, csv, json, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(r"C:\Users\vbrgr\Desktop\CertiFind\database")))
sys.path.insert(0, str(HERE))
from certifind_common import write_certifind_csvs  # noqa: E402
from prune_inactive import prune  # noqa: E402

REG = "https://register.jasanz.org/accredited-bodies"
ALL_EA = "1-39"
NO_SECTORS = "No sector list in the JASANZ register; recorded for all EA sectors"
COUNTRY = {"Korea, Republic of": "South Korea", "Korea,Republic of": "South Korea", "Viet Nam": "Vietnam",
           "Taiwan Province of China": "Taiwan"}
CC = {"Australia": "61", "New Zealand": "64", "India": "91", "South Korea": "82", "Malaysia": "60", "Japan": "81",
      "United States": "1", "China": "86", "Mongolia": "976", "South Africa": "27", "Vietnam": "84",
      "Singapore": "65", "United Arab Emirates": "971", "Taiwan": "886"}
# Numbers the generic normaliser gets wrong (extension ranges, unusual grouping).
PHONE_FIX = {"M4490510IF": "+91 129 4178070", "M4430310IC": "+91 94441 82838", "E2450402VH": "+84 24 3756 1025",
             "M4701210AB": "+61 7 5533 9988", "M25741021AC": "+61 487 106 055", "M5310713AR": "+61 419 497 073",
             "Z25510519UD": "+61 2 7258 6886"}

# Register scheme prefix -> (CertiFind certification standard, suffix, accreditation standard)
SCHEMES = [
    ("ISO/IEC 20000-1", "ISO/IEC 20000-1", " (20000)", "ISO/IEC 20000-6"),
    ("ISO/IEC 27001", "ISO/IEC 27001", " (27006)", "ISO/IEC 27006"),
    ("ISO/IEC 27701", "ISO/IEC 27701", " (27006)", "ISO/IEC 27006"),
    ("FSSC 22000", "FSSC 22000", " (22000)", "ISO 22003-1"),
    ("ISO 22000", "ISO 22000", " (22000)", "ISO 22003-1"),
    ("ISO 50001", "ISO 50001", " (50003)", "ISO 50003"),
    ("ISO 9001", "ISO 9001", "", "ISO/IEC 17021-1"),
    ("ISO 14001", "ISO 14001", "", "ISO/IEC 17021-1"),
    ("ISO 45001", "ISO 45001", "", "ISO/IEC 17021-1"),
    ("ISO 13485", "ISO 13485", "", "ISO/IEC 17021-1"),
    # JASANZ-named schemes for international standards (no sector list in the register)
    ("Artificial Intelligence Management System Scheme", "ISO/IEC 42001", " (42001)", "ISO/IEC 42006"),
    ("Asset Management Systems Scheme of Australasia", "ISO 55001", " (55001)", "ISO/IEC 17021-5"),
]


def scheme(name):
    return next((s for s in SCHEMES if name.startswith(s[0])), None)


def iso(d):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def title(s):
    return s.title() if s.isupper() and len(s) > 3 else s


def web(u):
    u = (u or "").split(";")[0].strip()
    if not u:
        return ""
    u = re.sub(r"^ttp://", "http://", u)
    return u if u.startswith("http") else "https://" + u


def address(loc, name):
    if not loc:
        return ""
    l1, l2, l3, city, state, pc, _ = [re.sub(r"\s+", " ", x or "").strip().strip(",") for x in loc]
    parts = [p for p in (l1, l2, l3) if p and not name.lower().startswith(p.lower()[:20])]
    tail = " ".join(p for p in (title(city), state, pc) if p)
    return ", ".join(parts + ([tail] if tail else []))


def phone(raw, country, accno, notes):
    if accno in PHONE_FIX:
        return PHONE_FIX[accno]
    if not raw:
        return ""
    p = re.split(r"[,/;]", raw)[0]
    p = re.sub(r"\(ext[^)]*\)|\(0\)", " ", p)
    toks = re.sub(r"[().\-]", " ", p).split()
    cc = CC.get(country)
    if toks and toks[0] == "+":
        toks = toks[1:]
        toks[0] = "+" + toks[0]
    if toks and toks[0].startswith("+"):
        cc, toks = toks[0][1:], toks[1:]
    if not cc or not toks:
        notes.append(f"phone `{raw}` could not be made international; left empty")
        return ""
    if toks[0].startswith("0"):
        toks[0] = toks[0][1:]
        toks = [t for t in toks if t]
    if cc == "61" and toks and re.match(r"1[38]00$", toks[0]):
        notes.append(f"phone `{raw}` is an Australian 1300/1800 number, not reachable from abroad; left empty")
        return ""
    return "+" + cc + " " + " ".join(toks)


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return " ".join(w for w in s.split() if w not in {"pvt", "private", "ltd", "limited", "co", "pty", "p"})


def existing_bodies(data_root, own):
    out = {}
    for f in sorted(data_root.glob("*/bodies.csv")):
        if f.parent.name == own:
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                out.setdefault((row["country"], norm(row["name"])), (f.parent.name, row))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[])
    a = ap.parse_args()

    raw = json.loads((a.scrape / "raw" / "jasanz_cabs.json").read_text(encoding="utf-8"))
    X = raw["X"]
    known = existing_bodies(a.out.parent, a.out.name)
    bodies, accs, scopes, review, notes_md, names = [], [], [], [], [], set()
    for b in raw["B"]:
        name, _, accno, issue, exp, url, ph, email, loc, sc, xi = b
        base = (accno or "").split("/")[0].strip()
        kept, skipped = [(scheme(std), ea) for std, ea in sc], []
        for i in xi:
            s = scheme(X[i])
            if s:
                kept.append((s, ""))
            else:
                skipped.append(X[i])
        if base in a.debug:
            print(base, name, "\n  kept:", [(k[0][1], k[1]) for k in kept], "\n  skipped:", skipped)
        if not kept:
            review.append(f"| {name} | {base} | body excluded: no ISO/IEC 17021 MS scheme | {'; '.join(skipped)} |")
            continue
        if skipped:
            review.append(f"| {name} | {base} | schemes skipped | {'; '.join(skipped)} |")
        country = COUNTRY.get(loc[6], loc[6]) if loc else ""
        notes = []
        hit = known.get((country, norm(name)))
        if hit:
            body = dict(hit[1])
            notes.append(f"reuses body row `{body['name']}` from `{hit[0]}`")
        else:
            body = dict(name=name, country=country, registration_no=base, phone=phone(ph, country, base, notes),
                        email=(email or "").rstrip("."), website=web(url), address=address(loc, name),
                        source_url=REG, verified_at="")
        if body["name"] in names:
            raise SystemExit(f"duplicate body name {body['name']}")
        names.add(body["name"])
        bodies.append(body)
        if notes:
            notes_md.append(f"- {name} ({base}): " + "; ".join(notes))

        def acc(cert, acc_std):
            return dict(ab_code="JASANZ", certificate_number=cert, body_name=body["name"],
                        accreditation_standard=acc_std, status="ACTIVE", issue_date=iso(issue),
                        expiry_date=iso(exp), proof_url=REG)

        rows, seen = {base: acc(base, "ISO/IEC 17021-1")}, set()  # search requires a 17021-1 row
        for (_, std, suffix, acc_std), ea in kept:
            if std in seen:
                continue   # e.g. "ISO/IEC 27001:2022 (DEWR)" next to the plain 27001 entry
            seen.add(std)
            cert = base + suffix
            rows.setdefault(cert, acc(cert, acc_std))
            if not ea:
                ea, note = ALL_EA, NO_SECTORS
            elif "22000" in std:
                note = "Classified to EA from ISO 22003-1 food chain categories listed in the JASANZ register"
            elif std == "ISO 13485":
                note = "Classified to EA from IAF MD 8 technical areas listed in the JASANZ register"
            else:
                note = "IAF/EA codes from the JASANZ register technical sectors"
            scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea,
                               status="ACTIVE", scope_note=note))
        accs.extend(rows.values())

    write_certifind_csvs(a.out, bodies, accs, scopes)
    removed = prune(a.out, a.today)
    with open(HERE / "jasanz_review.md", "w", encoding="utf-8") as f:
        f.write("# JASANZ review log\n\nSource: " + REG + "\n\nKept: ISO 9001, 14001, 45001, 13485, 22000, FSSC 22000, "
                "50001, ISO/IEC 27001, 20000-1, plus the JASANZ AIMS scheme (ISO/IEC 42001) and Asset Management "
                "Systems Scheme of Australasia (ISO 55001). Everything else (national, product, personnel, private "
                "food/farm schemes) is listed below.\n\n"
                "| Body | Accreditation no. | Action | Skipped schemes |\n|---|---|---|---|\n")
        f.write("\n".join(review) + "\n\n## Body notes\n\n" + "\n".join(notes_md) + "\n")
        if removed:
            f.write("\n## Removed by prune_inactive\n\n" + "\n".join(f"- {r}" for r in removed) + "\n")
    print(f"Bodies: {len(bodies)}  Accreditations: {len(accs)}  Scopes: {len(scopes)}  "
          f"Excluded: {sum('body excluded' in r for r in review)}  Pruned: {len(removed)}")


if __name__ == "__main__":
    main()
