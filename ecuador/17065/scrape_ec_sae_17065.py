"""Scrape SAE (Servicio de Acreditación Ecuatoriano) ISO/IEC 17065 product certification bodies.

Same register and endpoints as ../database/ecuador/scrape_ec_sae.py (the MS scraper); only the activity
differs: area 2 = CERTIFICACIÓN, activity 6 = products (ISO/IEC 17065). MS uses 4, 9, 10, 11, 24, 27, 28.

  /accreditations/get-oec/<activity_id>?per_page=200&page=N&search=&orderBy=desc
  /qualityMng/updateInformations/scopes_active?accAppId=<id>&per_page=50&page=N&search=&orderBy=desc

The host answers 403 to non-browser clients and puts a "Confirm You Are Human" check in front of the
browser. When a direct fetch fails, collect the same JSON in a browser session (after passing the check)
as {"rows": [...], "scopes": [...]} and pass it with --input; the outputs are then built from that dump.

Outputs (in --out, default ./sae_17065/):
  raw/sae_17065_raw.json   untouched rows + scopes
  sae_17065_raw.json       one record per accreditation (CertiFind shape)
  scope_lines.csv          registration_no,source,row_index,product_text_raw
  pdfs/<acc>.pdf           accreditation resolution PDFs (unless --no-files)
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import requests

BASE = "https://sistema.acreditacion.gob.ec"
ACTIVITIES = [6]  # 6 = products (ISO/IEC 17065)
H = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
HERE = Path(__file__).parent


def paged(url: str):
    page, last = 1, 1
    while page <= last:
        j = requests.get(f"{url}&page={page}&search=&orderBy=desc", headers=H, timeout=180).json()
        last = j.get("last_page", 1)
        yield from j["data"]
        page += 1


def v(x):
    return x.get("value") if isinstance(x, dict) else None


def fetch(limit: int | None) -> dict:
    rows, apps = [], {}
    for act in ACTIVITIES:
        for d in paged(f"{BASE}/accreditations/get-oec/{act}?per_page=200"):
            a = d.get("accreditation_application") or {}
            o = a.get("organization") or {}
            res = a.get("subscribed_accreditation_resolution") or {}
            apps[d["acc_app_id"]] = a.get("acc_number")
            rows.append({
                "act": act, "app_id": d["acc_app_id"], "acc": a.get("acc_number"),
                "st": a.get("accreditation_state"), "init": a.get("acc_init_date"), "res": a.get("resolution_date"),
                "name": o.get("business_name") or o.get("name"), "trade": o.get("name"),
                "ph": o.get("phone"), "em": o.get("email"), "web": o.get("web"),
                "addr": o.get("address"), "city": (o.get("canton") or {}).get("name"),
                "country": (o.get("country") or {}).get("name"), "pdf": res.get("full_url"),
            })
            if limit and len(rows) >= limit:
                break
    scopes = []
    for app_id, acc in apps.items():
        for d in paged(f"{BASE}/qualityMng/updateInformations/scopes_active?accAppId={app_id}&per_page=50"):
            scopes.append({"acc": acc, "l4": v(d.get("level_4")), "l5": v(d.get("level_5")),
                           "l6": v(d.get("level_6"))})
    return {"rows": rows, "scopes": scopes}


def safe(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s or "x")


def pdf_text_layer(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        return [ln.strip() for p in PdfReader(path).pages for ln in (p.extract_text() or "").splitlines() if ln.strip()]
    except Exception:
        return []


def build(dump: dict, out: Path, limit: int | None, files: bool) -> None:
    rows = dump["rows"][:limit] if limit else dump["rows"]
    accs = {r["acc"] for r in rows}
    records, lines = [], []
    ok = failed = scanned = 0
    for r in rows:
        records.append({
            "registration_no": r["acc"], "id": r.get("app_id"), "name": r["name"],
            "address": ", ".join(x for x in (r.get("addr"), r.get("city"), r.get("country")) if x),
            "phone": r.get("ph"), "email": r.get("em"), "website": r.get("web"),
            "issued": r.get("init"), "expiry": None, "status": r.get("st"),
            "annex_urls": [r["pdf"]] if r.get("pdf") else [],
        })
    for i, s in enumerate(x for x in dump["scopes"] if x["acc"] in accs):
        text = " | ".join(x for x in (s.get("l4"), s.get("l5"), s.get("l6")) if x)
        if text:
            lines.append((s["acc"], "register", i, text))
    if files:
        (out / "pdfs").mkdir(parents=True, exist_ok=True)
        for r in rows:
            if not r.get("pdf"):
                continue
            p = out / "pdfs" / f"{safe(r['acc'])}.pdf"
            if not p.exists():
                try:
                    resp = requests.get(r["pdf"], headers=H, timeout=180)
                    resp.raise_for_status()
                    if not resp.content.startswith(b"%PDF"):
                        raise ValueError("not a PDF")
                    p.write_bytes(resp.content)
                except Exception as e:
                    failed += 1
                    print(f"pdf failed {r['acc']}: {e}", file=sys.stderr)
                    continue
            ok += 1
            tl = pdf_text_layer(p)
            if not tl:
                scanned += 1
            lines += [(r["acc"], "annex", j, t) for j, t in enumerate(tl)]
    (out / "sae_17065_raw.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        w.writerows(lines)
    print(f"bodies={len({r['name'] for r in rows})} accreditations={len(rows)} "
          f"scope_lines={len(lines)} pdfs_ok={ok} pdfs_failed={failed} pdfs_without_text={scanned}")


def main() -> None:
    ap = argparse.ArgumentParser(description="SAE Ecuador — Product Certification Bodies (ISO/IEC 17065)")
    ap.add_argument("--out", type=Path, default=HERE / "sae_17065")
    ap.add_argument("--input", type=Path, help="browser dump {rows, scopes} to use instead of fetching")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    raw = a.out / "raw" / "sae_17065_raw.json"
    if a.input:
        dump = json.loads(a.input.read_text(encoding="utf-8"))
    else:
        dump = fetch(a.limit)
    raw.parent.mkdir(exist_ok=True)
    raw.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    build(dump, a.out, a.limit, not a.no_files)


if __name__ == "__main__":
    main()
