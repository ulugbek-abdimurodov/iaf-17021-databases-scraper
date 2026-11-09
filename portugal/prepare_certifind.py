#!/usr/bin/env python3
"""Convert the IPAC scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by ipac_scraper.py (ipac_data/: bodies.json or bodies.csv + scope.csv).
Each body's HTML profile page (ficha_ocf.asp) holds the current technical annex in force across
all accredited sites.

    python prepare_certifind.py [scrape folder] [dataset folder] [--today YYYY-MM-DD] [--debug IDs]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


esyd = _load("esyd_prepare", HERE.parent / "greece" / "prepare_certifind.py")
ea_spec, expand = esyd.ea_spec, esyd.expand

AB_CODE = "IPAC"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL = set(range(1, 40))
ALL_NOTE = "No sector list in the IPAC scope; recorded for all EA sectors"

STANDARDS = {
    "ISO 9001": "ISO 9001",
    "ISO 14001": "ISO 14001",
    "ISO 45001": "ISO 45001",
    "ISO 50001": "ISO 50001",
    "ISO 22000": "ISO 22000",
    "ISO/IEC 27001": "ISO/IEC 27001",
    "ISO/IEC 20000-1": "ISO/IEC 20000-1",
    "ISO 22301": "ISO 22301",
    "ISO 55001": "ISO 55001",
    "ISO 56001": "ISO 56001",
    "ISO 39001": "ISO 39001",
}
SCHEME_ROWS = {
    "ISO 22000": ("ISO 22003-1", " (22000)"),
    "ISO 50001": ("ISO 50003", " (50003)"),
    "ISO/IEC 27001": ("ISO/IEC 27006", " (27006)"),
    "ISO/IEC 20000-1": ("ISO/IEC 20000-6", " (20000)"),
    "ISO 22301": ("ISO/IEC 17021-6", " (22301)"),
    "ISO 55001": ("ISO/IEC 17021-5", " (55001)"),
    "ISO 39001": ("ISO/IEC 17021-7", " (39001)"),
}
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001", "ISO 55001", "ISO 56001"}
ENERGY_EA = {letter: spec for letter, _, spec in esyd.ENERGY_AREAS}
SUSPENDED_RE = re.compile(r"\bsuspens[aã]o(?:\s+desde\s+([\d-]+))?", re.I)

NAMES = {
    "CERTIS - Controlo e Certificação, Lda. - CERTIS - Controlo e Certificação":
        "CERTIS - Controlo e Certificação, Lda.",
    "NATURALFA - Controlo e Certificação Lda. - Organismo de Certificação":
        "NATURALFA - Controlo e Certificação, Lda.",
    "INNOQ - Instituto Nacional de Normalização e Qualidade, IP - Organismo de Certificação":
        "INNOQ - Instituto Nacional de Normalização e Qualidade, IP",
    "SGS Portugal - Sociedade Geral de Superintendência, S.A. - Industrial":
        "SGS Portugal - Sociedade Geral de Superintendência, S.A.",
}


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def phone(raw: str) -> str:
    """Normalize 9-digit Portuguese numbers ('229 993 600' / '217104200') to '+351 XXX XXX XXX'."""
    p = raw.strip()
    if not p:
        return ""
    if p.startswith(("+", "(+")):
        digits = re.sub(r"\D", "", p)
        if digits.startswith("351") and len(digits) == 12:
            d = digits[3:]
            return f"+351 {d[:3]} {d[3:6]} {d[6:]}"
        return "+" + re.sub(r"\s+", " ", re.sub(r"[^\d\s]", " ", p)).strip()
    digits = re.sub(r"\D", "", p)
    if len(digits) == 9:
        return f"+351 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return ""


def clean_extent(raw: str) -> str:
    """Remove trailing '(completo)' and outer parentheses from a scope restriction."""
    ext = re.sub(r"\s*\(completo\)\s*$", "", (raw or "").strip(), flags=re.I).strip()
    if ext.startswith("(") and ext.endswith(")"):
        ext = ext[1:-1].strip()
    return "" if ext.lower() in ("", "completo") or re.fullmatch(r"-+", ext) else ext


def scope_codes(std: str, items: list[dict]) -> tuple[set[int], list[str], list[str]]:
    """Return (active_ea_codes, scope_notes, suspended_labels) for a (body, standard) group."""
    active_items, suspended_labels = [], []
    for item in items:
        text = " ".join([item.get("description", ""), item.get("extent", ""),
                         " ".join(item.get("cells", [])) if isinstance(item.get("cells"), list)
                         else str(item.get("cells", ""))])
        m = SUSPENDED_RE.search(text)
        if m:
            label = item.get("code") or item.get("description", "").split("Suspens")[0].strip()
            since = f" (since {m.group(1)})" if m.group(1) else ""
            entry = f"{label}{since}"
            if entry not in suspended_labels:
                suspended_labels.append(entry)
            continue
        active_items.append(item)

    if not active_items:
        return set(), [], suspended_labels

    if std == "ISO 3834":
        codes = {int(i["iaf_code"]) for i in active_items
                 if str(i.get("iaf_code", "")).isdigit() and 1 <= int(i["iaf_code"]) <= 39}
        return codes or {17}, ["ISO 3834-2, 3, 4 in conjunction with ISO 9001"], suspended_labels

    if std in IAF_STANDARDS:
        codes: set[int] = set()
        full_codes: set[int] = set()
        limits: dict[int, list[str]] = defaultdict(list)
        for i in active_items:
            raw_iaf = i.get("iaf_code")
            if not str(raw_iaf).isdigit():
                m = re.match(r"^IAF\s*(\d{1,2})\b", str(i.get("code", "")))
                raw_iaf = int(m.group(1)) if m else None
            else:
                raw_iaf = int(raw_iaf)
            if not raw_iaf or not (1 <= raw_iaf <= 39):
                continue
            codes.add(raw_iaf)
            ext = clean_extent(i.get("extent", ""))
            if not ext:
                full_codes.add(raw_iaf)
            elif ext not in limits[raw_iaf]:
                limits[raw_iaf].append(ext)
        notes = []
        if std == "ISO 55001":
            notes.append("IAF codes listed in the IPAC scope")
        for c in sorted(limits):
            if c not in full_codes:
                notes.append(f"Limited scope: EA {c} ({'; '.join(limits[c])})")
        if suspended_labels:
            notes.append(f"Excludes suspended {', '.join(suspended_labels)}")
        return codes, notes, suspended_labels

    if std == "ISO 22000":
        cats = sorted({i["code"].strip().upper() for i in active_items
                       if i.get("code", "").strip().upper() in esyd.FOOD_CATEGORIES})
        if not cats:
            return set(), [], suspended_labels
        codes = set().union(*(expand(esyd.FOOD_CATEGORIES[c]) for c in cats))
        return codes, [f"ISO 22003-1 categories {', '.join(cats)} (classified to EA by sector)"], suspended_labels

    if std == "ISO 50001":
        areas = sorted({"ABCDEFGH"[int(i["code"].strip()) - 1] for i in active_items
                        if i.get("code", "").strip().isdigit() and 1 <= int(i["code"].strip()) <= 8})
        if not areas:
            return set(), [], suspended_labels
        codes = set().union(*(expand(ENERGY_EA[a]) for a in areas))
        return codes, [f"ISO 50003 technical areas {', '.join(areas)} (classified to EA by sector)"], suspended_labels

    if std == "ISO 22301":
        cats = []
        for i in active_items:
            c = i.get("code", "").strip()
            if c and c not in cats:
                cats.append(c)
        note = (f"Scope lists activity categories ({', '.join(cats)}), not EA sectors; recorded for all EA sectors"
                if cats else ALL_NOTE)
        return set(ALL), [note], suspended_labels

    if std == "ISO 39001":
        acts = []
        for i in active_items:
            d = i.get("description", "").strip()
            if d and d not in acts:
                acts.append(d)
        note = (f"Scope lists road-traffic activities ({'; '.join(acts)}), not EA sectors; recorded for all EA sectors"
                if acts else ALL_NOTE)
        return set(ALL), [note], suspended_labels

    return set(ALL), [ALL_NOTE], suspended_labels


def load_scrape(src: Path) -> list[dict]:
    json_path = src / "bodies.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))
    with open(src / "bodies.csv", encoding="utf-8-sig", newline="") as f:
        bodies = list(csv.DictReader(f))
    with open(src / "scope.csv", encoding="utf-8-sig", newline="") as f:
        scopes = list(csv.DictReader(f))
    by_id = defaultdict(list)
    for s in scopes:
        by_id[s["accreditation_no"]].append(s)
    for b in bodies:
        b["sites"] = [{"address": b.get("address", ""), "phone": b.get("phone", ""),
                       "email": b.get("email", ""), "district": b.get("district", "")}]
        b["scope"] = by_id[b["accreditation_no"]]
    return bodies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", nargs="?", type=Path, default=HERE / "ipac_data")
    ap.add_argument("out", nargs="?", type=Path,
                    default=HERE.parent.parent / "certifind" / "data" / "ipac-portugal")
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--debug", nargs="*", default=[])
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    records = sorted(load_scrape(args.scrape), key=lambda r: r["accreditation_no"])
    review, skipped = [], defaultdict(list)
    body_rows, accreditations, scope_rows = {}, [], []

    for body in records:
        rid = body["accreditation_no"].strip()
        raw_name = (body.get("legal_name") or body.get("name") or body.get("acronym") or "").strip()
        name = NAMES.get(raw_name, raw_name)

        by_std: dict[str, list[dict]] = defaultdict(list)
        for s in body.get("scope", []):
            grp = (s.get("group") or "").strip()
            raw_std = (s.get("standard") or "").strip()
            ext = (s.get("extent") or "").strip()
            if raw_std == "ISO 9001" and re.match(r"^ISO\s*3834\b", ext, re.I):
                by_std["ISO 3834"].append(s)
                continue
            std = STANDARDS.get(raw_std)
            if std is None:
                label = grp or s.get("description") or raw_std or "Unlabelled scope"
                skipped[label].append(rid)
                continue
            by_std[std].append(s)

        found: dict[str, tuple[set[int], list[str], str]] = {}
        for std, items in by_std.items():
            codes, notes, susp = scope_codes(std, items)
            if args.debug and rid in args.debug:
                print(f"## {rid} [{std}] active={sorted(codes)} susp={susp} notes={notes}")
            if codes:
                found[std] = (codes, notes, "ACTIVE")
                if susp:
                    review.append(f"{rid} {name}: {std} excludes suspended {', '.join(susp)}")
            elif susp:
                # All sectors under this standard are suspended; emit SUSPENDED so prune_inactive logs & drops it.
                susp_iaf = {int(m.group(1)) for lbl in susp if (m := re.match(r"^IAF\s*(\d+)", lbl))}
                found[std] = (susp_iaf or ALL, [f"Suspended: {', '.join(susp)}"], "SUSPENDED")
                review.append(f"{rid} {name}: {std} has all {len(susp)} sector(s) suspended")
            else:
                review.append(f"{rid} {name}: {std} found but no sectors read — check {body.get('profile_url')}")

        if not found:
            schemes_str = ", ".join(sorted({(s.get("group") or s.get("description") or "").strip()
                                            for s in body.get("scope", []) if (s.get("group") or s.get("description"))}))
            review.append(f"{rid} {name}: no importable standard (only national / regulatory schemes: "
                          f"{schemes_str or 'none'}); not imported")
            continue

        s0 = body["sites"][0] if body.get("sites") else {}
        addr = (s0.get("address") or body.get("address") or "").strip()
        country = "Mozambique" if "moçambique" in addr.lower() else "Portugal"
        raw_phone = (s0.get("phone") or body.get("phone") or "").strip()
        tel = phone(raw_phone)
        if raw_phone and not tel:
            review.append(f"{rid} {name}: phone '{raw_phone}' is not a valid number; left empty")
        email = (s0.get("email") or body.get("email") or "").strip()
        url = (body.get("profile_url") or "").strip()

        body_rows[name] = {
            "name": name,
            "country": country,
            "registration_no": rid,
            "phone": tel,
            "email": email,
            "website": "",
            "address": addr,
            "source_url": url,
            "verified_at": "",
        }

        issue = (body.get("certificate_date") or body.get("granted") or today).strip()
        expiry = (body.get("certificate_valid_until") or "").strip()
        rows_needed = {BASE: rid}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], rid + SCHEME_ROWS[std][1])
        has_active = any(status == "ACTIVE" for _, _, status in found.values())
        acc_status = "ACTIVE" if has_active else "SUSPENDED"
        for acc_std, number in rows_needed.items():
            accreditations.append({
                "ab_code": AB_CODE,
                "certificate_number": number,
                "body_name": name,
                "accreditation_standard": acc_std,
                "status": acc_status,
                "issue_date": issue,
                "expiry_date": expiry,
                "proof_url": url,
            })
        for std, (codes, notes, status) in found.items():
            number = rid + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else rid
            scope_rows.append({
                "certificate_number": number,
                "certification_standard": std,
                "ea_codes": ea_spec(codes),
                "status": status,
                "scope_note": "; ".join(notes),
            })
        if all(std in SCHEME_ROWS for std in found):
            review.append(f"{rid} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")

    # Deduplicate against existing CertiFind datasets for the same (country, name)
    for path in args.out.parent.glob("*/bodies.csv"):
        if path.parent.resolve() == args.out.resolve():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r["name"] in body_rows and r["country"] == body_rows[r["name"]]["country"]:
                    body_rows[r["name"]] = {k: r[k] for k in BODY_COLUMNS}
                    review.append(f"{r['name']}: already in {path.parent.name}; that dataset's body row is used")

    write(args.out / "bodies.csv", BODY_COLUMNS, sorted(body_rows.values(), key=lambda r: r["name"].casefold()))
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today or date.today())
    with open(HERE / "ipac_review.md", "w", encoding="utf-8") as f:
        f.write(f"# IPAC conversion review\n\nGenerated {today}: {counts[0]} bodies, "
                f"{counts[1]} accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Schemes not imported (scheme: registrations)\n\n")
        for title, ids in sorted(skipped.items(), key=lambda kv: kv[0].casefold()):
            f.write(f"- {title}: {', '.join(sorted(set(ids)))}\n")
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'ipac_review.md'}")


if __name__ == "__main__":
    main()