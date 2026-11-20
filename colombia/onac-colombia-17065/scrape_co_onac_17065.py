"""ONAC (Colombia) scraper - Product Certification Bodies (ISO/IEC 17065), scheme CPR.

Same register as the MS scraper (database/colombia/scrape_co_onac.py, esquema=CSG). The search
(directorio3/.../resultado_busqueda_empresa) only answers inside a browser session on
https://onac.org.co/directorio-de-acreditados/ (a bare POST returns the admin login page), so the listing is a
browser export: pick "Organismos de Certificación de Producto (CPR)" in #esquema, click Buscar, and save
code, name, city, status of every DataTable row to onac_17065_list.tsv. Detail pages and certificate PDFs are
plain GETs and are fetched here.

Per accreditation: detail page (NIT, address, phone, email, website, dates, "Detalle del Alcance" table =
IAF sector + NACE product category) and the certificate PDF (scope annex, text layer).
Outputs (default onac_17065/): onac_17065_raw.json, scope_lines.csv, pdf/<code>.pdf, details/<code>.html.
"""
import argparse, csv, json, re, sys, time
from pathlib import Path

import pdfplumber, requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BASE = "https://onac.org.co"
DETAIL = BASE + "/directorio3/index.php/acreditaciones/{}"
PDF = BASE + "/certificados/{}.pdf"
# annex boilerplate lines (headers/footers repeated on every page)
NOISE = re.compile(r"^(Página \d|ACREDITACIÓN ISO/IEC 17065|Alcance de la acreditaci|CAMPO (REGLAMENTARIO|VOLUNTARIO)|"
                   r"División Categoría|Documento Normativo$|NACE certificar|\d\d-CPR-\d+$)", re.I)


def get(s, url, tries=3):
    for i in range(tries):
        try:
            r = s.get(url, timeout=60)
            r.raise_for_status()
            return r
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    info = dict(nit="", address="", phone="", email="", website="", issued="", expiry="", scope=[])
    nit = soup.find(lambda t: t.name == "h5" and t.get_text(strip=True).startswith("Nit"))
    head = nit.find_previous_sibling("h3") or nit if nit else None
    if head:
        h5 = head.parent.find_all("h5")
        for h in h5:
            t = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
            icon = h.find("ion-icon")
            kind = icon.get("md", "") if icon else ""
            if t.startswith("Nit"):
                info["nit"] = t.replace("Nit.", "").strip()
            elif "navigate" in kind:
                info["address"] = t
            elif "call" in kind:
                info["phone"] = t
            elif "mail" in kind:
                info["email"] = "; ".join(e.strip() for e in t.split(";") if e.strip())
            elif "globe" in kind:
                a = h.find("a")
                href = (a.get("href") or "").strip() if a else ""
                info["website"] = href if re.search(r"\w\.\w", href) else ""
    m = re.search(r"Fecha de publicación del otorgamiento: (\d{4}-\d\d-\d\d)", txt)
    info["issued"] = m.group(1) if m else ""
    m = re.search(r"Fecha de vencimiento de la acreditación: (\d{4}-\d\d-\d\d)", txt)
    info["expiry"] = m.group(1) if m else ""
    for tr in soup.select("table tr"):
        c = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(c) >= 3 and c[0] and not c[0].startswith("SECTOR"):
            info["scope"].append({"iaf_sector": c[0], "category": c[1], "status": c[2]})
    return info


def annex_lines(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[1:]:  # page 1 is the certificate itself
            for ln in (page.extract_text() or "").splitlines():
                ln = ln.strip()
                if ln and not NOISE.search(ln) and not re.search(r"FR 3\.5\.3", ln):
                    out.append(ln)
    return out


def main():
    ap = argparse.ArgumentParser(description="ONAC Colombia product certification bodies (ISO/IEC 17065, CPR)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-files", action="store_true", help="skip certificate PDF downloads")
    ap.add_argument("--out", default=str(HERE / "onac_17065"))
    ap.add_argument("--refresh", action="store_true", help="re-download cached detail pages/PDFs")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    (out / "details").mkdir(exist_ok=True)

    rows = [r for r in csv.reader(open(HERE / "onac_17065_list.tsv", encoding="utf-8"), delimiter="\t") if r]
    rows = rows[: a.limit] if a.limit else rows
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (CertiFind register scraper)"

    recs, lines, ok, fail, scanned = [], [], 0, 0, []
    for code, name, city, status in rows:
        dpath = out / "details" / f"{code}.html"
        if a.refresh or not dpath.exists():
            dpath.write_bytes(get(s, DETAIL.format(code)).content)
        info = parse_detail(dpath.read_text(encoding="utf-8", errors="replace"))
        url = PDF.format(code)
        recs.append(dict(registration_no=code, id=code, name=name, nit=info["nit"], city=city,
                         address=info["address"], phone=info["phone"], email=info["email"],
                         website=info["website"], issued=info["issued"], expiry=info["expiry"], status=status,
                         scope=info["scope"], annex_urls=[url]))
        for i, sc in enumerate(info["scope"]):
            lines.append(dict(registration_no=code, source="register", row_index=i,
                              product_text_raw=f"{sc['iaf_sector']} | {sc['category']} | {sc['status']}"))
        if a.no_files:
            continue
        ppath = out / "pdf" / f"{code}.pdf"
        try:
            if a.refresh or not ppath.exists():
                ppath.write_bytes(get(s, url).content)
            ok += 1
            al = annex_lines(ppath)
            if not al:
                scanned.append(code)
            lines += [dict(registration_no=code, source=f"annex:{code}.pdf", row_index=i, product_text_raw=t)
                      for i, t in enumerate(al)]
        except Exception as e:
            fail += 1
            print(f"PDF fail {code}: {e}", file=sys.stderr)
        print(code, name[:60], f"scope={len(info['scope'])}", file=sys.stderr)

    json.dump(recs, open(out / "onac_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(lines)
    reg = sum(1 for l in lines if l["source"] == "register")
    print(f"Bodies: {len({r['name'] for r in recs})}  Accreditations: {len(recs)}  Scope lines: {len(lines)} "
          f"(register {reg}, annex {len(lines) - reg})  PDFs ok/failed: {ok}/{fail}  "
          f"No text layer: {', '.join(scanned) or 'none'}")


if __name__ == "__main__":
    main()
