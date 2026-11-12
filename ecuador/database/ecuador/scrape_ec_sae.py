"""Scrape SAE (Servicio de Acreditación Ecuatoriano) management-system CABs.

Public JSON endpoints behind https://sistema.acreditacion.gob.ec/accreditations/scopes-public:
  /accreditations/get-oec/<activity_id>?per_page=200&page=N&search=&orderBy=desc
  /qualityMng/updateInformations/scopes_active?accAppId=<id>&per_page=50&page=N&search=&orderBy=desc
Area 2 = CERTIFICACIÓN. Management-system activities: 4 QMS, 9 food safety, 10 EMS,
11 anti-bribery, 24 medical devices QMS, 27 OH&S, 28 energy. (5 persons, 6 products skipped.)

The host is not reachable from every network; the dump used for this dataset was collected
in a browser session with the same requests and saved as raw/sae_raw.json
({"rows": [...], "scopes": [...]}). Run this script where the host is reachable to refresh it.
"""
import json
import sys
from pathlib import Path

import requests

BASE = "https://sistema.acreditacion.gob.ec"
ACTIVITIES = [4, 9, 10, 11, 24, 27, 28]
H = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
OUT = Path(__file__).parent / "raw" / "sae_raw.json"


def paged(url: str):
    page, last = 1, 1
    while page <= last:
        j = requests.get(f"{url}&page={page}&search=&orderBy=desc", headers=H, timeout=180).json()
        last = j.get("last_page", 1)
        yield from j["data"]
        page += 1


def v(x):
    return x.get("value") if isinstance(x, dict) else None


def main() -> None:
    rows, apps = [], {}
    for act in ACTIVITIES:
        for d in paged(f"{BASE}/accreditations/get-oec/{act}?per_page=200"):
            a = d.get("accreditation_application") or {}
            o = a.get("organization") or {}
            res = a.get("subscribed_accreditation_resolution") or {}
            apps[d["acc_app_id"]] = a.get("acc_number")
            rows.append({
                "act": act, "acc": a.get("acc_number"), "st": a.get("accreditation_state"),
                "init": a.get("acc_init_date"), "res": a.get("resolution_date"),
                "name": o.get("business_name") or o.get("name"), "trade": o.get("name"),
                "ph": o.get("phone"), "em": o.get("email"), "web": o.get("web"),
                "addr": o.get("address"), "city": (o.get("canton") or {}).get("name"),
                "country": (o.get("country") or {}).get("name"), "pdf": res.get("full_url"),
            })
    scopes = []
    for app_id, acc in apps.items():
        for d in paged(f"{BASE}/qualityMng/updateInformations/scopes_active?accAppId={app_id}&per_page=50"):
            scopes.append({"acc": acc, "l4": v(d.get("level_4")), "l5": v(d.get("level_5")),
                           "l6": v(d.get("level_6"))})
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"rows": rows, "scopes": scopes}, ensure_ascii=False), encoding="utf-8")
    print(f"rows={len(rows)} scopes={len(scopes)}", file=sys.stderr)


if __name__ == "__main__":
    main()
