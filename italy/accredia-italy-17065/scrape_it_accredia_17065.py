"""Scrape ACCREDIA (Italy) ISO/IEC 17065 product certification bodies -> raw files + scope_lines.csv.

Companion to scrape_it_accredia.py (17021-1); reuses its BASE/DETAIL and the same raw-JSON layout.
How ACCREDIA marks 17065 bodies:
  * search filter PPSEARCH_ORG_SEARCH_MASK_STANDARDS=2 ("UNI CEI EN ISO/IEC 17065:2012 - Prodotti/Servizi/Processi")
  * detail page block <div class="certification"> "Schema di accreditamento: Prodotti/Servizi/Processi"
  * document code "PRD" in file names: <accr_no>PRDrev<NNN>_CERT / _ALL_SEDI / _ALL_<annex> (CSACI, CSAAR, CSAAG, CSACPR)
Scope = the annex PDFs (all _ALL_* except SEDI = sites). Lines are captured verbatim (no translation/classification).

Usage: python scrape_it_accredia_17065.py [out_dir]   (default accredia_17065; cached html/pdf are reused)
"""
import csv, html as htmlmod, json, logging, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pdfplumber, requests
from bs4 import BeautifulSoup

from scrape_it_accredia import BASE, DETAIL

HOST = "https://services.accredia.it"
COLS = ["registration_no", "page", "row_index", "product_text_raw", "scheme_text_raw",
        "normative_docs_raw", "scheme_type_raw", "other_columns_raw", "source"]
HEADER_MAP = [  # (target, regex on a table header cell)
    ("scheme_type_raw", r"(^|\s)(tipo|type)\s*\*?$"),
    ("product_text_raw", r"^(prodott|product|famiglia|family|categori|servizio|service|dispositivi|settore|sector)"),
    ("scheme_text_raw", r"^(mandat|marchi|marks|schema|scheme|certificazione$|certification$)"),
    ("normative_docs_raw", r"(specifica tecnica|technical specification|requisiti|requirements|^norm|(^|\s)standard|articoli|articles)"),
]
HEADER_WORDS = r"(decisione|decision|prodott|product|famiglia|family|categor|servizio|service|mandat|marchi|marks|schema|scheme|certific|specifica|specification|requisiti|requirement|norm|standard|tipo|type|avcp|sistema|system|procedur|articol|article|art\.)"
PAGE_NO = re.compile(r"^\d+\s*/\s*\d+$")
WS = re.compile(r"\s+")
log = logging.getLogger("accredia17065")


def clean(t):
    return WS.sub(" ", t or "").strip()


# ---------------------------------------------------------------- fetch
def fetch(out):
    (out / "html").mkdir(parents=True, exist_ok=True)
    (out / "pdf").mkdir(exist_ok=True)
    s = requests.Session()
    form = BeautifulSoup(s.get(BASE + "?ID_LINK=1733&area=310").text, "html.parser").find("form")
    data = {e.get("name"): "" for e in form.find_all(["input", "select"]) if e.get("name")}
    data.update(ID_LINK="1733", area="310", PPSEARCH_ORG_SEARCH_MASK_STANDARDS="2", submitBtn="Search")
    ids = sorted(set(re.findall(r"PPSEARCH_ORG_SEARCH_MASK_ORG=(\w+)", s.post(BASE, data=data).text)) - {""})

    def page(i):
        p = out / "html" / f"{i}.html"
        if not p.exists():
            p.write_text(s.get(DETAIL + i, timeout=60).text)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(page, ids))

    bodies, jobs = [], {}
    for i in ids:
        h = (out / "html" / f"{i}.html").read_text()
        soup = BeautifulSoup(h, "html.parser")
        blocks = [b for b in soup.select("div.certification") if "17065" in b.get_text()]
        if not blocks:
            log.warning("body %s: no 17065 block on detail page", i)
        text = soup.get_text("\n")
        head = text[: text.find("Schema di accreditamento")]
        docs = []
        for b in blocks:
            bt = b.get_text("\n")
            no = re.search(r"Accreditamento N\.:\s*(\S+)", bt)
            issued = re.search(r"Emesso il:\s*(\d\d/\d\d/\d{4})", bt)
            # documents follow the block: take PRD links of this accreditation number
            for href, fn in re.findall(r'href="([^"]*CERTFILENAME=(\w+PRDrev\d+_\w+))"', h):
                if no and fn.startswith(no.group(1) + "PRD") and fn not in [d["file"] for d in docs]:
                    docs.append({"file": fn, "url": HOST + htmlmod.unescape(href)})
            bodies.append({"id": i, "registration_no": no.group(1) if no else "",
                           "issued": issued.group(1) if issued else "", "text_head": head,
                           "block": clean(bt), "documents": docs})
            if not no:
                log.warning("body %s: accreditation number not found", i)
        for d in docs:
            if "_ALL_" in d["file"] and not d["file"].endswith("SEDI"):
                jobs[d["file"]] = d["url"]

    def pdf(fn):
        p = out / "pdf" / f"{fn}.pdf"
        if p.exists():
            return
        r = s.get(jobs[fn], timeout=120)
        if r.content[:4] == b"%PDF":
            p.write_bytes(r.content)
        else:
            log.warning("%s: not a PDF (%s)", fn, r.headers.get("content-type"))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(pdf, jobs))
    json.dump(bodies, open(out / "accredia_17065_raw.json", "w"), ensure_ascii=False, indent=1)
    return bodies


# ---------------------------------------------------------------- parse
def is_header_row(row, in_header=False):
    """True if the cells after the first all look like column titles (first cell may be a group title)."""
    cells = [clean(c) for c in row]
    filled = [c for c in cells[1:] if c]
    if len(filled) < (1 if in_header else 1) or (not in_header and len([c for c in cells if c]) < 2):
        return False
    if in_header and cells[0] and not re.search(HEADER_WORDS, cells[0], re.I):
        return False
    return all(len(c) <= 60 and re.search(HEADER_WORDS, c, re.I) for c in filled)


def merge_header(rows):
    """rows: list of [(x0, x1, text)]; stack cells that overlap horizontally into one column name."""
    cols = []
    for row in rows:
        for x0, x1, txt in row:
            if not txt:
                continue
            for c in cols:
                if min(x1, c[1]) - max(x0, c[0]) > 2:
                    c[0], c[1], c[2] = min(x0, c[0]), max(x1, c[1]), c[2] + " " + txt
                    break
            else:
                cols.append([x0, x1, txt])
    return sorted(cols)


def assign(header, cells):
    """cells: [(x0, x1, text)] -> list of (header name, text) by horizontal overlap with header columns."""
    out = []
    for x0, x1, txt in cells:
        if not txt:
            continue
        best = max(header, key=lambda c: min(x1, c[1]) - max(x0, c[0])) if header else None
        if best and min(x1, best[1]) - max(x0, best[0]) > 0:
            out.append((best[2], txt, best is header[0]))
        else:
            out.append((f"x{round(x0)}", txt, False))
    return out


def fits(header, cells):
    """A carried-over header applies only if every filled cell starts at a header column boundary."""
    return all(any(abs(x0 - c[0]) <= 6 for c in header) for x0, x1, t in cells if t)


def map_row(pairs):
    rec = {k: "" for k in COLS}
    other = {}
    for name, val, first in pairs:
        tgt = next((t for t, rx in HEADER_MAP if re.search(rx, name, re.I)), None)
        if not tgt and first:
            tgt = "product_text_raw"  # positional rule: first column holds the product (group) when untitled
        if tgt:
            rec[tgt] = (rec[tgt] + " " + val).strip()
        else:
            other[name] = (other.get(name, "") + " " + val).strip()
    rec["other_columns_raw"] = json.dumps(other, ensure_ascii=False) if other else ""
    return rec


def is_continuation(prev, line):
    if not prev:
        return False
    if re.match(r"^[a-zà-ü(\)\],;.:/&]|^e\s", line) and not re.match(r"^[a-z]\)\s", line):
        return True
    if prev.endswith((",", "-", "–", "/", "(", " e", " and", " of", " di", " del", " della", " per")) and not prev.startswith(("- ", "-\t")):
        return True
    return prev.count("(") > prev.count(")")


def parse_pdf(path):
    """Yield (page, kind, payload): kind 'text' (str) or 'row' (header, cells)."""
    header = None
    with pdfplumber.open(path) as pdf:
        for pno, p in enumerate(pdf.pages, 1):
            words = p.extract_words()
            top = next((w["bottom"] for w in words if w["text"] in ("Expiry", "Exipry")), None)
            if top is None:
                log.warning("%s p%d: header end ('Expiry date') not found, page parsed whole", path.name, pno)
                top = 0
            body = p.crop((0, top + 1, p.width, p.height))
            tables = [t for t in body.find_tables() if len(t.rows[0].cells) >= 2]
            items = []
            for t in tables:
                hdr_rows, own = [], False
                for row, texts in zip(t.rows, t.extract()):
                    cells = [(c[0], c[2], clean(x)) for c, x in zip(row.cells, texts) if c]
                    if is_header_row(texts, bool(hdr_rows)):
                        hdr_rows.append(cells)
                        if not hdr_rows[1:] and (len(clean(texts[0])) > 25 or (clean(texts[0]) and not re.search(HEADER_WORDS, clean(texts[0]), re.I))):
                            items.append((row.bbox[1], "text", clean(texts[0])))  # group title in header row
                        continue
                    if hdr_rows:
                        header, hdr_rows, own = merge_header(hdr_rows), [], True
                    if not any(c[2] for c in cells):
                        continue
                    if header and not own and not fits(header, cells):
                        header = None  # header of an earlier table does not match this table's columns
                    if header is None:
                        log.info("%s p%d: table row without header", path.name, pno)
                    items.append((row.bbox[1], "row", assign(header or [], cells)))
                if hdr_rows:
                    header = merge_header(hdr_rows)
                own = False
            outside = body
            for t in tables:
                outside = outside.filter(lambda o, b=t.bbox: not (b[0] - 1 <= o.get("x0", -9) and o.get("x1", 9e9) <= b[2] + 1
                                                                  and b[1] - 1 <= o.get("top", -9) and o.get("bottom", 9e9) <= b[3] + 1))
            for ln in outside.extract_text_lines():
                t = clean(ln["text"])
                if t and not PAGE_NO.match(t):
                    items.append((ln["top"], "text", t))
            for _, kind, payload in sorted(items, key=lambda x: x[0]):
                yield pno, kind, payload


def scope_lines(body, out):
    rows = []
    for d in body["documents"]:
        fn = d["file"]
        if "_ALL_" not in fn or fn.endswith("SEDI"):
            continue
        path = out / "pdf" / f"{fn}.pdf"
        if not path.exists():
            log.warning("body %s: missing PDF %s", body["id"], fn)
            continue
        pending = None
        for pno, kind, payload in parse_pdf(path):
            if kind == "text":
                if pending and pending["_kind"] == "text" and is_continuation(pending["product_text_raw"], payload):
                    pending["product_text_raw"] += " " + payload
                    continue
                if pending:
                    rows.append(pending)
                pending = {k: "" for k in COLS} | {"product_text_raw": payload, "page": pno, "_kind": "text", "source": fn}
            else:
                if pending:
                    rows.append(pending)
                pending = None
                rec = map_row(payload)
                rows.append(rec | {"page": pno, "_kind": "row", "source": fn})
        if pending:
            rows.append(pending)
    for i, r in enumerate(rows, 1):
        r["registration_no"], r["row_index"] = body["registration_no"], i
        r.pop("_kind", None)
        m = re.search(r"\b(?:tipo|type)\s*(1a|1b|[2-6])\b", r["product_text_raw"] + " " + r["scheme_text_raw"], re.I)
        if not r["scheme_type_raw"] and m:
            r["scheme_type_raw"] = m.group(1)
    return rows


def main(out_dir="accredia_17065"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=out / "scrape_17065.log", filemode="w", level=logging.INFO,
                        format="%(levelname)s %(message)s")
    bodies = fetch(out)
    total, zero = 0, []
    with open(out / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        for b in bodies:
            rows = scope_lines(b, out)
            w.writerows(rows)
            total += len(rows)
            log.info("body %s reg %s: %d scope lines", b["id"], b["registration_no"], len(rows))
            if not rows:
                zero.append(b["registration_no"])
                log.warning("body %s reg %s: ZERO scope lines", b["id"], b["registration_no"])
    print(f"Bodies: {len(bodies)}\nScope lines: {total}\nZero-line bodies: {len(zero)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
