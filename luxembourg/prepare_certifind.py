#!/usr/bin/env python3
"""Convert the OLAS scrape (ISO/IEC 17021-1 management system certification bodies) into a
CertiFind dataset folder (bodies.csv, accreditations.csv, scopes.csv).

Input: the folder written by olas_17021_scraper.py (bodies.json and, per body, the
"annexe technique" PDF). Each annex has one section per "Domaine général" naming the
certified standard, followed by IAF codes ("17 - métallurgie ...").

The register's accreditation_number (6/005, 4/007) is taken from the page URL and does not
match the certificates; the certificate number is read from the annex
("Annexe au certificat d'accréditation : N° 4/005") and checked against the certificate PDF.

    python prepare_certifind.py <scrape folder> <dataset folder> [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)
HERE = Path(__file__).resolve().parent

AB_CODE = "OLAS"
BASE = "ISO/IEC 17021-1"
BODY_COLUMNS = ["name", "country", "registration_no", "phone", "email", "website", "address",
                "source_url", "verified_at"]
ACCREDITATION_COLUMNS = ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                         "status", "issue_date", "expiry_date", "proof_url"]
SCOPE_COLUMNS = ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
ALL_NOTE = "No sector list in the annex; recorded for all EA sectors"
STANDARDS = [(r"ISO 9001", "ISO 9001"), (r"ISO 14001", "ISO 14001"), (r"ISO 45001", "ISO 45001"),
             (r"ISO/IEC 27001", "ISO/IEC 27001")]
IAF_STANDARDS = {"ISO 9001", "ISO 14001", "ISO 45001"}
SCHEME_ROWS = {"ISO/IEC 27001": ("ISO/IEC 27006", " (27006)")}
SKIPPED = [(r"PSDC|Dématérialisation", "SMQ6 PSDC (Luxembourg digitisation / archiving scheme, ILNAS 106)"),
           (r"Règlement \(UE\) 2018/858", "EU 2018/858 type-approval CoP audits (automotive regulation)")]
MONTHS = {m: i + 1 for i, m in enumerate(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split())}


def french_date(text: str) -> str:
    m = re.search(r"(\d{1,2}) (\w+) (\d{4})", text)
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" if m else ""


def ea_spec(codes: set[int]) -> str:
    parts, run = [], []
    for c in sorted(codes):
        if run and c == run[-1] + 1:
            run.append(c)
        else:
            if run:
                parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
            run = [c]
    if run:
        parts.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ";".join(parts)


def write(path: Path, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scrape", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args()
    today = (args.today or date.today()).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)

    data = json.loads((args.scrape / "bodies.json").read_text(encoding="utf-8"))
    entries = data["bodies"] if isinstance(data, dict) else data
    review, body_rows, accreditations, scope_rows = [], [], [], []
    for b in entries:
        folder = next((p for p in (args.scrape / "bodies").iterdir()
                       if p.name.endswith(b["accreditation_number"].replace("/", "-"))), None)
        annex = folder / "annexe-technique.pdf" if folder else None
        if not annex or not annex.exists():
            review.append(f"{b['name']}: no annex; not imported")
            continue
        with pdfplumber.open(annex) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        cert = re.search(r"certificat d.accréditation\s*:\s*N°\s*(\d+/\d+)", text).group(1)
        if cert != b["accreditation_number"]:
            review.append(f"{b['name']}: register page says {b['accreditation_number']}, annex and "
                          f"certificate say {cert}; certificate number used")
        name = re.search(r"Organisme accrédité\s*:\s*\n(.+)", text).group(1).strip()
        expiry = french_date(re.search(r"Valide jusqu.au ([^\n]+)", text).group(1))
        phone = re.search(r"Tél\. : (\+[\d ]+)", text)
        email = re.search(r"E-Mail : (\S+)", text)
        for rx, why in SKIPPED:
            if re.search(rx, text):
                review.append(f"{cert} {name}: {why} not imported")

        found: dict[str, set[int]] = {}
        sections = re.split(r"Domaine général\s*:", text)[1:]
        for sec in sections:
            head = sec.split("\n")[0] + " " + sec.split("\n")[1]
            if re.search(SKIPPED[0][0], head):
                continue
            std = next((s for rx, s in STANDARDS if re.search(rx, head)), None)
            if std is None:
                review.append(f"{cert} {name}: section '{head[:80]}' not recognised")
                continue
            if std in IAF_STANDARDS:
                body = sec.split("Annexe au certificat")[0]
                codes = {int(m.group(1)) for m in re.finditer(r"^(\d{1,2})\s*[-–]\s*\D", body, re.M)
                         if 1 <= int(m.group(1)) <= 39}
            else:
                codes = set(range(1, 40))
            found.setdefault(std, set()).update(codes)

        rows_needed = {BASE: cert}
        for std in found:
            if std in SCHEME_ROWS:
                rows_needed.setdefault(SCHEME_ROWS[std][0], cert + SCHEME_ROWS[std][1])
        annex_url = next(d["url"] for d in b["documents"] if "nnexe" in d["label"])
        for acc_std, number in rows_needed.items():
            accreditations.append({"ab_code": AB_CODE, "certificate_number": number, "body_name": name,
                                   "accreditation_standard": acc_std, "status": "ACTIVE",
                                   "issue_date": b["issued_on"], "expiry_date": expiry or b["valid_until"],
                                   "proof_url": annex_url})
        for std, codes in found.items():
            number = cert + SCHEME_ROWS[std][1] if std in SCHEME_ROWS else cert
            scope_rows.append({"certificate_number": number, "certification_standard": std,
                               "ea_codes": ea_spec(codes), "status": "ACTIVE",
                               "scope_note": "" if std in IAF_STANDARDS else ALL_NOTE})
        if not any(std not in SCHEME_ROWS for std in found):
            review.append(f"{cert} {name}: only schemes with their own accreditation standard; "
                          f"ISO/IEC 17021-1 row kept without scopes")
        addr = b["address"] if isinstance(b["address"], list) else b["address"].split("; ")
        if addr and addr[-1] == "Luxembourg":
            addr = addr[:-1]  # country line
        body_rows.append({"name": name, "country": "Luxembourg", "registration_no": cert,
                          "phone": phone.group(1).strip() if phone else "",
                          "email": email.group(1) if email else "", "website": "",
                          "address": ", ".join(addr),
                          "source_url": b["page_url"], "verified_at": ""})

    body_rows.sort(key=lambda r: r["name"].casefold())
    write(args.out / "bodies.csv", BODY_COLUMNS, body_rows)
    write(args.out / "accreditations.csv", ACCREDITATION_COLUMNS,
          sorted(accreditations, key=lambda r: r["certificate_number"]))
    write(args.out / "scopes.csv", SCOPE_COLUMNS,
          sorted(scope_rows, key=lambda r: (r["certificate_number"], r["certification_standard"])))
    counts = (len(body_rows), len(accreditations), len(scope_rows))

    sys.path.insert(0, str(HERE.parent))
    from prune_inactive import prune
    removed = prune(args.out, args.today)
    with open(HERE / "olas_review.md", "w", encoding="utf-8") as f:
        f.write(f"# OLAS conversion review\n\nGenerated {today}: {counts[0]} bodies, {counts[1]} "
                f"accreditations, {counts[2]} scope rows before pruning.\n\n## Notes\n\n")
        f.writelines(f"- {line}\n" for line in review)
        f.write("\n## Removed by prune_inactive\n\n")
        f.writelines(f"- {line}\n" for line in removed)
    print(f"before prune: {counts}; removed {len(removed)} rows; review: {HERE / 'olas_review.md'}")


if __name__ == "__main__":
    main()
