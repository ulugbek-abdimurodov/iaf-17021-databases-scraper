"""Scrape JAS-ANZ ISO/IEC 17065 (Product Certification) CABs via the register's public JSON API.
Writes raw/jasanz_17065_raw.json for prepare_certifind_17065.py.
Note: the API host is blocked from the workspace proxy, so the 2026-11-17 run used the same code in-browser
(register.jasanz.org page context) and saved the JSON by download."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/"
PROGRAM = "Product Certification"


def get(path):
    for _ in range(3):
        try:
            return requests.get(API + path, timeout=60).json().get("data")
        except Exception:
            pass
    return None


def record(c):
    s, i = get(f"CabSchemeScopeDetails?Id={c['id']}") or {}, get(f"GetCABsInformation?Id={c['id']}") or {}
    pc = [d for d in s.get("schemeDetailList") or [] if any(x.get("program") == PROGRAM for x in d.get("certificationStandard") or [])]
    if not pc:
        return None
    locs = i.get("locations") or []
    loc = next((l for l in locs if l.get("isHeadOffice")), locs[0] if locs else None)
    return {"id": c["id"], "name": i.get("name") or c["name"], "abbr": i.get("abbreviation"),
            "acc": [[a.get("accreditaionNumber"), a.get("accreditaionDate")] for a in i.get("accreditations") or []],
            "issued": i.get("lastAccreditationIssued"), "expiry": i.get("accreditationExpiryDate"),
            "web": i.get("webContactUrl"), "phone": i.get("webContactPhone"), "email": i.get("webContactEmail"),
            "addr": [loc.get(k) or "" for k in ("line1", "line2", "line3", "city", "state", "postalCode", "country")] if loc else [],
            "schemes": [{"s": d["schemeName"], "acc": [x.get("name", x) if isinstance(x, dict) else x for x in d.get("accreditationStandard") or []],
                         "t": [t["name"] for t in d.get("technicalSector") or []],
                         "c": [[x["name"], x.get("description") or ""] for x in d["certificationStandard"] if x.get("program") == PROGRAM]}
                        for d in pc]}


def main():
    with ThreadPoolExecutor(8) as ex:
        R = [r for r in ex.map(record, get("GetFilteredCABRegister") or []) if r]
    out = Path(__file__).parent / "raw" / "jasanz_17065_raw.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(R, ensure_ascii=False), encoding="utf-8")
    print(f"Product certification CABs scraped: {len(R)}")


if __name__ == "__main__":
    main()
