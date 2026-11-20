"""Scrape EMA (Entidad Mexicana de Acreditación) Product Certification Bodies, ISO/IEC 17065.

Same register as the MS scraper (../database/mexico/scrape_mx_ema.py):
https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion
Rows mix "ISO/IEC 17021-1: 2015" and "NMX-EC-17065-IMNC-2014 ISO/IEC 17065:2012" in `normaAcreditacion`;
this script keeps only rows whose norm contains "17065". Each row is one accreditation x scope
(id "84/12|PROD", alcance "PROD", alcance__nombre "PRODUCTO").

The site sits behind an Azure Application Gateway that answers 403 to headless Chromium, so we drive the
installed Chrome headed (default) or attach to a running Chrome via --cdp http://localhost:9222.
EMA publishes no annex PDFs for this register; scope lines come from the register rows.

Outputs (ema_17065/): ema_rows_17065.json, ema_clients_17065.json, ema_17065_raw.json, scope_lines.csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

MS_DIR = Path(__file__).resolve().parent.parent / "database" / "mexico"
sys.path.insert(0, str(MS_DIR))
import scrape_mx_ema as ms  # noqa: E402  (no import-time side effects)

NORM_FILTER = "17065"
HERE = Path(__file__).resolve().parent
CLIENT_WAIT = ("id => { const s=window.__s.getState(); const c=(s.toJS?s.toJS():s).certificationBodies.client;"
               " return c && c.id===id }")

CLICK_JS = ("id => { const b=[...document.querySelectorAll('td button')].find(x=>x.innerText.trim()===id);"
            " if(b){b.click(); return true} return false }")
CLOSE_JS = "() => document.querySelectorAll('button').forEach(b=>{ if(/cerrar/i.test(b.innerText)) b.click() })"


def open_page(p, args):
    if args.cdp:
        browser = p.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    else:
        browser = p.chromium.launch(channel="chrome", headless=args.headless)
        ctx = browser.new_context()
    page = ctx.new_page()
    resp = page.goto(ms.URL, timeout=90000)
    if resp and resp.status == 403:
        sys.exit("403 from EMA gateway: rerun headed (default) or with --cdp against your own Chrome")
    return page


def scrape(args):
    rows, clients = {}, {}
    with sync_playwright() as p:
        page = open_page(p, args)
        page.click("text=MOSTRAR TODOS")
        page.wait_for_selector("td button")
        page.evaluate(ms.STORE_JS)
        seen_pages = 0
        while True:
            page.wait_for_timeout(1500)
            data = page.evaluate(ms.STATE)["tableConnected"]["data"]
            seen_pages += 1
            for r in data["results"]:
                if NORM_FILTER not in (r.get("normaAcreditacion") or ""):
                    continue
                rows[r["id"] + "#" + r["acreditacion__cliente__nombre"]] = r
                acc = r["acreditacion"]
                if acc in clients or (args.limit and len(clients) >= args.limit):
                    continue
                try:
                    if not page.evaluate(CLICK_JS, r["id"]):
                        raise RuntimeError("row button not found")
                    page.wait_for_function(CLIENT_WAIT, arg=acc, timeout=20000)
                    clients[acc] = page.evaluate(ms.STATE)["certificationBodies"]["client"]
                except Exception as e:  # keep going; record is still in rows
                    print(f"  client {acc} failed: {str(e).splitlines()[0][:120]}")
                page.evaluate(CLOSE_JS)
                page.wait_for_timeout(300)
            if args.limit and len(clients) >= args.limit:
                break
            nxt = page.locator("button[aria-label='Siguiente página']")
            if not data.get("next") or nxt.is_disabled():
                break
            nxt.click()
    if args.limit:  # trial run: keep only rows of sampled accreditations
        rows = {k: v for k, v in rows.items() if v["acreditacion"] in clients}
    return list(rows.values()), clients, seen_pages


def write(out: Path, rows, clients):
    out.mkdir(parents=True, exist_ok=True)
    (out / "ema_rows_17065.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "ema_clients_17065.json").write_text(json.dumps(clients, ensure_ascii=False, indent=1), encoding="utf-8")
    by_acc = {}
    for r in rows:
        by_acc.setdefault(r["acreditacion"], []).append(r)
    raw, lines = [], []
    for acc, rs in sorted(by_acc.items()):
        c = clients.get(acc, {})
        raw.append({
            "registration_no": acc, "id": c.get("cliente__id") or rs[0].get("acreditacion__id"),
            "name": (c.get("nombre") or rs[0]["acreditacion__cliente__nombre"]).strip(),
            "address": c.get("domicilioCompleto", ""), "phone": c.get("telefono", "") or "",
            "email": c.get("email", "") or "", "website": c.get("url", "") or "",
            "issued": min((r.get("fechaInicio") or "") for r in rs), "expiry": c.get("fechaFinal") or "",
            "status": rs[0].get("acreditacion__status__nombre", ""),
            "norm": rs[0].get("normaAcreditacion", ""), "annex_urls": [],
        })
        for i, r in enumerate(sorted(rs, key=lambda x: x["id"]), 1):
            text = " - ".join(x for x in (r.get("alcance"), r.get("alcance__nombre"), r.get("normaAplicable")) if x)
            lines.append({"registration_no": acc, "source": "register", "row_index": i, "product_text_raw": text})
    (out / "ema_17065_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(lines)
    return raw, lines


def main():
    ap = argparse.ArgumentParser(description="EMA Mexico Product Certification Bodies (ISO/IEC 17065) scraper")
    ap.add_argument("--out", default=str(HERE / "ema_17065"))
    ap.add_argument("--limit", type=int, default=0, help="stop after N accreditations (trial run)")
    ap.add_argument("--cdp", help="attach to running Chrome, e.g. http://localhost:9222")
    ap.add_argument("--headless", action="store_true", help="headless Chrome (usually 403)")
    ap.add_argument("--no-files", action="store_true", help="accepted for parity; EMA has no annex PDFs")
    args = ap.parse_args()
    rows, clients, pages = scrape(args)
    raw, lines = write(Path(args.out), rows, clients)
    print(f"Pages scanned: {pages}\nBodies: {len({r['name'] for r in raw})}\nAccreditations: {len(raw)}\n"
          f"Clients fetched: {len(clients)}\nScope lines: {len(lines)}\nPDFs: 0 (register has none)")


if __name__ == "__main__":
    main()
