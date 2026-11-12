"""Scrape EMA (Entidad Mexicana de Acreditación) certification-body register.

Register UI: https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion
The React app keeps results in its redux store; we drive the public UI with Playwright
("Mostrar todos", page size 100, paginate) and read the store, then open each
accreditation dialog to read the client record (address, email, expiry).
Outputs raw JSON; the 2026-11-10 run was executed in-browser and exported as raw/ema_register.txt
(names / accreditation~nameIdx~yyyymmdd~status~scopes / acc~name~expiry~email~url~address).
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion"
RAW = Path(__file__).parent / "raw"

STORE_JS = """() => { const r=document.getElementById('app')._reactRootContainer._internalRoot.current;
 let st=null; (function w(n,d){ if(!n||st||d>40) return; if(n.memoizedProps&&n.memoizedProps.store){st=n.memoizedProps.store;return}
 w(n.child,d+1); w(n.sibling,d)})(r,0); window.__s=st; return true }"""
STATE = "() => { const s=window.__s.getState(); return s.toJS ? s.toJS() : s }"


def main() -> None:
    RAW.mkdir(exist_ok=True)
    rows, clients = {}, {}
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        page.goto(URL)
        page.click("text=MOSTRAR TODOS")
        page.wait_for_selector("td button")
        page.evaluate(STORE_JS)
        while True:
            page.wait_for_timeout(1500)
            data = page.evaluate(STATE)["tableConnected"]["data"]
            for r in data["results"]:
                rows[r["id"] + "#" + r["acreditacion__cliente__nombre"]] = r
                if "17021" not in (r.get("normaAcreditacion") or "") or r["acreditacion"] in clients:
                    continue
                page.locator("td button", has_text=r["id"]).first.click()
                page.wait_for_function(
                    "id => { const s=window.__s.getState(); const c=(s.toJS?s.toJS():s).certificationBodies.client; return c && c.id===id }",
                    arg=r["acreditacion"])
                clients[r["acreditacion"]] = page.evaluate(STATE)["certificationBodies"]["client"]
                page.click("text=CERRAR")
            nxt = page.locator("button[aria-label='Siguiente página']")
            if not data.get("next") or nxt.is_disabled():
                break
            nxt.click()
    (RAW / "ema_rows.json").write_text(json.dumps(list(rows.values()), ensure_ascii=False))
    (RAW / "ema_clients.json").write_text(json.dumps(clients, ensure_ascii=False))
    print(f"Rows: {len(rows)}\nClients: {len(clients)}")


if __name__ == "__main__":
    main()
