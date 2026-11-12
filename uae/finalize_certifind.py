"""Turn the prepared EIAC CSVs (database/uae/data/eiac-uae) into a CertiFind-compliant dataset.

Fixes: one accreditation per body + accreditation standard (uq_cb_ab_standard), ACTIVE status,
international phones without trunk 0, reuse of bodies already in other datasets, and pruning
(expired rows; bodies without an active ISO/IEC 17021-1 row).

usage: python finalize_certifind.py <certifind/data dir> --today YYYY-MM-DD
"""
import argparse, csv, glob, re
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "data" / "eiac-uae"
ALIASES = {"BSCIC Certifications PVT. LTD.": ("India", "BSCIC Certifications Pvt. Ltd.")}

def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f); return r.fieldnames, list(r)

def write(p, fields, rows):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(rows)

def fix_phone(p):
    m = re.match(r"^\+(\d{1,3}) 0(\d.*)$", p.strip())
    return f"+{m[1]} {m[2]}" if m else p.strip()

def merge_codes(a, b):
    s = set()
    for part in (a + ";" + b).split(";"):
        if not part: continue
        x, _, y = part.partition("-"); s.update(range(int(x), int(y or x) + 1))
    out, n = [], sorted(s)
    i = 0
    while i < len(n):
        j = i
        while j + 1 < len(n) and n[j + 1] == n[j] + 1: j += 1
        out.append(str(n[i]) if i == j else f"{n[i]}-{n[j]}"); i = j + 1
    return ";".join(out)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("data"); ap.add_argument("--today", required=True)
    a = ap.parse_args(); data = Path(a.data); out = data / "eiac-uae"; out.mkdir(exist_ok=True)
    log = []
    bf, bodies = read(SRC / "bodies.csv"); af, accs = read(SRC / "accreditations.csv"); sf, scopes = read(SRC / "scopes.csv")

    existing = {}
    for f in glob.glob(str(data / "*" / "bodies.csv")):
        if "eiac-uae" in f: continue
        for r in read(f)[1]: existing.setdefault((r["country"], r["name"]), r)

    rename = {}
    for b in bodies:
        b["phone"] = fix_phone(b["phone"])
        key = ALIASES.get(b["name"], (b["country"], b["name"]))
        if key in existing:
            new = dict(existing[key]); rename[b["name"]] = new["name"]
            log.append(f"- {b['name']}: reuses existing body row '{new['name']}' ({key[0]})."); b.clear(); b.update(new)
    for x in accs: x["body_name"] = rename.get(x["body_name"], x["body_name"])

    # prune expired
    for x in accs:
        if x["status"].lower() != "active" or (x["expiry_date"] and x["expiry_date"] < a.today):
            log.append(f"- {x['certificate_number']} ({x['body_name']}): expired {x['expiry_date']} — dropped.")
    live = [x for x in accs if x["status"].lower() == "active" and not (x["expiry_date"] and x["expiry_date"] < a.today)]

    # merge per body + standard
    first, cert_map = {}, {}
    for x in live:
        k = (x["body_name"], x["accreditation_standard"])
        if k not in first:
            x["status"] = "ACTIVE"; first[k] = x
        else:
            m = first[k]; cert_map[x["certificate_number"]] = m["certificate_number"]
            if x["issue_date"] and (not m["issue_date"] or x["issue_date"] < m["issue_date"]): m["issue_date"] = x["issue_date"]
            if x["expiry_date"] and x["expiry_date"] > m["expiry_date"]: m["expiry_date"] = x["expiry_date"]
        cert_map.setdefault(x["certificate_number"], x["certificate_number"])
    merged = list(first.values())
    if len(merged) < len(live): log.append(f"- Merged {len(live) - len(merged)} per-scheme registrations into the body's first registration per accreditation standard (uq_cb_ab_standard); merged rows keep earliest issue / latest expiry date.")

    # bodies need active 17021-1
    ok = {x["body_name"] for x in merged if x["accreditation_standard"] == "ISO/IEC 17021-1"}
    for b in bodies:
        if b["name"] not in ok: log.append(f"- {b['name']}: no ISO/IEC 17021-1 accreditation (only {sorted({x['accreditation_standard'] for x in merged if x['body_name']==b['name']})}) — body dropped.")
    bodies = [b for b in bodies if b["name"] in ok]
    merged = [x for x in merged if x["body_name"] in ok]
    keep = {x["certificate_number"] for x in merged}

    sc = {}
    for s in scopes:
        c = cert_map.get(s["certificate_number"])
        if c not in keep: continue
        k = (c, s["certification_standard"])
        if k in sc: sc[k]["ea_codes"] = merge_codes(sc[k]["ea_codes"], s["ea_codes"])
        else: sc[k] = dict(s, certificate_number=c, status="ACTIVE")
    scopes = list(sc.values())
    for s in scopes:
        if not s["ea_codes"]:
            s["ea_codes"] = "1-39"; s["scope_note"] = "No sector list readable in the EIAC scope annex; recorded for all EA sectors"
            log.append(f"- {s['certificate_number']} {s['certification_standard']}: no codes in annex — recorded for EA 1-39.")

    write(out / "bodies.csv", bf, bodies); write(out / "accreditations.csv", af, merged); write(out / "scopes.csv", sf, scopes)
    review = (HERE / "database" / "uae" / "eiac_review.md").read_text(encoding="utf-8")
    (HERE / "eiac_review.md").write_text(review + "\n## Finalize (finalize_certifind.py)\n\n" + "\n".join(log) + "\n", encoding="utf-8")
    print(f"{len(bodies)} bodies, {len(merged)} accreditations, {len(scopes)} scopes")

main()
