"""ECA (Costa Rica) - Product Certification Bodies, ISO/IEC 17065 (OCP-xxx).

The MS scraper (database/costa_rica/scrape_cr_eca.py) is hand-collected data, written when eca.or.cr was
blocked; this one scrapes the live site. The product register is the sibling listing page
https://eca.or.cr/organismos-de-certificacion-de-productos/ (the MS page is .../organismos-de-certificacion-de-sistemas/).
Each /oec/<slug>/ detail page gives contacts, "Acreditacion Numero", "Acreditado a partir del" (no expiry:
indefinite) and the scope PDF links (descargas/196/acreditaciones/...).

Outputs (in --out, default eca_17065/): eca_17065_raw.json, scope_lines.csv, pdfs/.
"""
import argparse, csv, html, json, re, sys, time
from pathlib import Path

import requests

BASE = "https://eca.or.cr"
LIST_URL = BASE + "/organismos-de-certificacion-de-productos/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CertiFind-scraper"}
MONTHS = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
MONTHS["setiembre"] = 9

S = requests.Session(); S.headers.update(UA)


def get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            r = S.get(url, timeout=60); r.raise_for_status()
            return r.content if binary else r.text
        except requests.RequestException as e:
            if i == tries - 1: raise
            print(f"  retry {url}: {e}"); time.sleep(2 * (i + 1))


def text_lines(fragment):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", fragment, flags=re.S)
    s = html.unescape(re.sub(r"<[^>]+>", "\n", s))
    return [l.strip() for l in s.splitlines() if l.strip()]


def es_date(s):
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:del?\s+)?(\d{4})", s or "", re.I)
    if not m or m.group(2).lower() not in MONTHS: return ""
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def fetch_listing():
    t = get(LIST_URL); out, seen = [], set()
    for url, label in re.findall(r'<a [^>]*href="(https://eca\.or\.cr/oec/[^"]+)"[^>]*>(.*?)</a>', t, re.S):
        label = " ".join(text_lines(label))
        if url in seen or not label: continue
        seen.add(url); out.append({"url": url, "label": label})
    return out


def after(lines, key):
    for i, l in enumerate(lines):
        if l.lower().startswith(key.lower()):
            v = l.split(":", 1)[1].strip() if ":" in l else ""
            return v or (lines[i + 1] if i + 1 < len(lines) else "")
    return ""


def fetch_detail(url):
    t = get(url)
    body = re.search(r'Direcci[oó]n:.*', t, re.S)
    frag = body.group(0) if body else t
    lines = text_lines(frag)
    pdfs = []
    for u in re.findall(r'href="(https://eca\.or\.cr/descargas/[^"]+\.pdf)"', frag, re.I):
        if u not in pdfs: pdfs.append(u)
    regs = re.findall(r"Acreditaci[oó]n N[uú]mero:\s*\n?\s*([A-Z]{2,4}-\d+)", "\n".join(lines))
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    return {
        "address": after(lines, "Dirección"), "email": after(lines, "Email"),
        "phone": after(lines, "Teléfono"), "website": after(lines, "Sitio web"),
        "issued": es_date(after(lines, "Acreditado a partir del")),
        "regs": regs, "annex_urls": pdfs,
        "title": html.unescape(title.group(1)).split("|")[0].strip() if title else "",
    }


def pdf_lines(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        txt = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    except Exception:
        return None
    ls = [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines()]
    return [l for l in ls if l]


def main():
    ap = argparse.ArgumentParser(description="ECA Costa Rica - Product Certification Bodies (ISO/IEC 17065)")
    ap.add_argument("--out", default=str(Path(__file__).parent / "eca_17065"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-files", action="store_true", help="skip annex PDF downloads")
    a = ap.parse_args()
    out = Path(a.out); (out / "pdfs").mkdir(parents=True, exist_ok=True)

    listing = fetch_listing()
    print(f"listing: {len(listing)} bodies")
    if a.limit: listing = listing[: a.limit]

    raw, scope_rows, ok, fail, notext = [], [], 0, 0, []
    for it in listing:
        d = fetch_detail(it["url"])
        m = re.match(r"(OCP-\d+)\s*(.*)", it["label"])
        reg = (d["regs"][0] if d["regs"] else (m.group(1) if m else ""))
        name = (m.group(2) if m else it["label"]).strip() or d["title"]
        rec = {"registration_no": reg, "id": it["url"].rstrip("/").rsplit("/", 1)[-1], "name": name,
               "address": d["address"], "phone": d["phone"], "email": d["email"],
               "website": d["website"], "issued": d["issued"], "expiry": "",
               "annex_urls": d["annex_urls"], "source_url": it["url"]}
        raw.append(rec); print(f"  {reg} {name} ({len(d['annex_urls'])} pdf)")
        if a.no_files: continue
        for u in d["annex_urls"]:
            p = out / "pdfs" / u.rsplit("/", 1)[-1]
            if not p.exists():
                try: p.write_bytes(get(u, binary=True)); ok += 1
                except Exception as e: fail += 1; print(f"    PDF fail {u}: {e}"); continue
            ls = pdf_lines(p)
            if not ls: notext.append(p.name); continue
            for i, l in enumerate(ls):
                scope_rows.append({"registration_no": reg, "source": p.name, "row_index": i, "product_text_raw": l})

    json.dump(raw, open(out / "eca_17065_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["registration_no", "source", "row_index", "product_text_raw"])
        w.writeheader(); w.writerows(scope_rows)
    print(f"\nbodies {len(raw)}, accreditations {len({r['registration_no'] for r in raw})}, "
          f"scope lines {len(scope_rows)}, PDFs downloaded {ok}, failed {fail}, no text layer {len(notext)}")
    if notext: print("  no text:", ", ".join(notext))


if __name__ == "__main__":
    sys.exit(main())
