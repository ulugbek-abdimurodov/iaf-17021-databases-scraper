"""SANAS (South Africa) - Product Certification Bodies, ISO/IEC 17065.

Same SharePoint REST register as the MS scraper (database/south-africa/scrape_za_sanas.py):
  Legal Entity (Published):  Field_x0020_Of_x0020_AccreditatiId eq 3 (Certification Body)
                             and Discipline(s) containing "17065"  -> product certification
  Certificate (Published):   latest file per Legal_x0020_EntityId -> /Certificate Published/<FileLeafRef>
                             (the accreditation certificate + schedule/annex PDF)

Outputs (default sanas_17065/):
  sanas_17065_raw.json  one record per accreditation (facility number)
  scope_lines.csv       registration_no,source,row_index,product_text_raw
  bodies.csv            flat register rows
  pdf/<file>.pdf        latest certificate/schedule per accreditation
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

BASE = "https://www.sanas.co.za"
API = BASE + "/_api/web/lists/getbytitle('{}')/items"
HEADERS = {"Accept": "application/json;odata=nometadata", "User-Agent": "Mozilla/5.0 (CertiFind scraper)"}
CB_FIELD_ID = 3          # 'Field of Accreditation (Published)': 3 = Certification Body
PRODUCT_RE = re.compile(r"17065")

S = requests.Session()
S.headers.update(HEADERS)


def get(url, params=None, tries=4, **kw):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=90, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def list_items(title, params):
    url, out = API.format(title), []
    params = dict(params, **{"$top": 1000})
    while url:
        d = get(url, params).json()
        out += d["value"]
        url, params = d.get("odata.nextLink"), None
    return out


def sa_date(s):
    """SharePoint stores SAST midnight as 22:00Z the day before -> shift +2h."""
    if not s:
        return ""
    from datetime import datetime, timedelta
    return (datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=2)).date().isoformat()


def fetch_entities():
    rows = list_items("Legal Entity (Published)", {"$filter": f"Field_x0020_Of_x0020_AccreditatiId eq {CB_FIELD_ID}"})
    return [r for r in rows if PRODUCT_RE.search(r.get("Discipline_x0028_s_x0029_") or "")]


def fetch_certificates(entity_ids):
    certs = list_items("Certificate (Published)", {"$select": "Id,Title,FileLeafRef,FileRef,Legal_x0020_EntityId,Modified"})
    latest = {}
    for c in certs:
        eid = c.get("Legal_x0020_EntityId")
        if eid in entity_ids and (eid not in latest or c["Modified"] > latest[eid]["Modified"]):
            latest[eid] = c
    return latest


def pdf_lines(path):
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return None
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser(description="SANAS ISO/IEC 17065 product certification body scraper")
    ap.add_argument("--out", default=str(Path(__file__).parent / "sanas_17065"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)

    ents = fetch_entities()
    if a.limit:
        ents = ents[: a.limit]
    certs = fetch_certificates({e["Id"] for e in ents})

    records, scope_rows, ok, fail, text_layer = [], [], 0, 0, 0
    for e in ents:
        reg = e["Title"]
        c = certs.get(e["Id"])
        annex_url = BASE + quote(c["FileRef"]) if c else ""
        addr = ", ".join(x for x in [e.get("Address_x0020__x0028_Physical_x0"), e.get("City_x0020__x0028_Physical_x0029"),
                                      e.get("State_x002f_Province_x0020__x002"), e.get("ZIP_x002f_Postal_x0020_Code_x002")] if x)
        rec = {
            "registration_no": reg, "id": e["Id"], "name": (e.get("Name") or "").strip(), "address": addr,
            "phone": e.get("Business_x0020_Phone") or "", "email": e.get("Representative_x0020_Email") or "",
            "website": "", "issued": sa_date(e.get("Initial_x0020_Date_x0020_of_x002")),
            "expiry": sa_date(e.get("Expiry_x0020_Date")), "annex_urls": [annex_url] if annex_url else [],
            "status": e.get("Accreditation_x0020_Status") or "", "discipline": e.get("Discipline_x0028_s_x0029_") or "",
            "schedule": e.get("Schedule") or "", "representative": e.get("Nominated_x0020_Representative") or "",
            "office": e.get("Head_x0020_Office") or "",
        }
        records.append(rec)
        scope_rows.append([reg, "register", 0, rec["discipline"].strip()])
        if annex_url and not a.no_files:
            p = out / "pdf" / c["FileLeafRef"]
            try:
                if not p.exists() or p.stat().st_size == 0:
                    p.write_bytes(get(annex_url).content)
                ok += 1
                lines = pdf_lines(p)
                if lines:
                    text_layer += 1
                    scope_rows += [[reg, "annex", i + 1, ln] for i, ln in enumerate(lines)]
            except Exception as ex:
                fail += 1
                print(f"  PDF fail {reg}: {ex}", file=sys.stderr)

    (out / "sanas_17065_raw.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(scope_rows)
    cols = ["registration_no", "name", "status", "issued", "expiry", "address", "phone", "email", "representative", "discipline"]
    with open(out / "bodies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    print(f"bodies: {len({r['name'] for r in records})}  accreditations: {len(records)}  "
          f"scope lines: {len(scope_rows)}  PDFs ok/failed: {ok}/{fail}  with text layer: {text_layer}")


if __name__ == "__main__":
    main()
