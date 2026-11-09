#!/usr/bin/env python3
"""
Parse DPA (Albania) accreditation PDFs of management-system certification
bodies (CS xxx) into structured rows.

Input : one PDF per body = certificate page + one annex ("Programi i
        AKREDITIMIT") per ISO standard, as published by DPA.
Output: out/certificates.csv  one row per body (authoritative validity dates)
        out/scope_rows.csv    one row per body x ISO standard
        out/scope_items.csv   one row per body x ISO standard x EA code/category
        out/parsed.json       everything, nested
        out/review_queue.csv  annexes with flags that need a human look

Usage:
    pip install pypdf          # only needed if pdftotext (poppler) is missing
    python parse_scope_pdf.py documents/ --out out        # whole folder
    python parse_scope_pdf.py CS006.pdf CS007.pdf --out out
    python parse_scope_pdf.py pdfs/*.pdf --include-contacts   # off by default (GDPR)

Rules: deterministic regex only; nothing is inferred. If something is not
printed in the PDF it stays empty and the annex gets a flag.
"""
import argparse, csv, json, re, shutil, subprocess, sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------- constants
# Expected supporting standard per ISO standard (used only to raise a flag,
# values always come from the PDF).
EXPECTED_SUPPORT = {
    "9001": "17021-3", "14001": "17021-2", "45001": "17021-10",
    "27001": "27006", "50001": "50003", "22000": "22003-1",
    "20000-1": "20000-6", "39001": "17021-7", "37001": "17021-9",
    "22301": "17021-6", "20121": "17021-4",
}
STD_NAMES = {
    "9001": "Quality", "14001": "Environment", "45001": "Occupational health and safety",
    "27001": "Information security", "27701": "Privacy information management",
    "50001": "Energy", "22000": "Food safety", "20000-1": "IT service management",
    "39001": "Road traffic safety", "37001": "Anti-bribery", "22301": "Business continuity",
    "13485": "Medical devices", "20121": "Sustainable events",
}
EXTENSION_NUMBERS = {"27017", "27018"}          # guidance added on top of 27001
CATEGORY_STANDARDS = {"50001", "22000", "22301", "13485"}

DATE = r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})"
STD_RE = re.compile(
    r"(?:ISO\s*/\s*IEC|ISO)\s*(\d{4,6}(?:-\d+)?)\s*:\s*(\d{4})", re.I)
AMD_RE = re.compile(r"^\s*/?\s*(?:Amd|AMD)\s*(\d)\s*:\s*(\d{4})")


def iso(d, m, y):
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def find_date(pattern, text):
    m = re.search(pattern + r"\s*:?\s*" + DATE, text, re.I)
    return iso(*m.groups()) if m else None


# ---------------------------------------------------------------- PDF text
def pdf_pages(path):
    """Return list of page texts (layout preserved)."""
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                             capture_output=True, text=True, check=True).stdout
        pages = out.split("\f")
        if pages and not pages[-1].strip():
            pages = pages[:-1]
        return pages
    from pypdf import PdfReader  # fallback
    return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]


# ---------------------------------------------------------------- certificate page
def parse_certificate(text, include_contacts):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rec = {"body_name": None, "address": None, "registration_no": None,
           "accreditation_standard": None}
    for i, l in enumerate(lines):
        if re.search(r"ÇERTIFIKAT[ËE]\s+AKREDITIMI", l, re.I):
            rec["body_name"] = lines[i + 1] if i + 1 < len(lines) else None
            addr = []
            for l2 in lines[i + 2:i + 5]:
                if re.search(r"Numri\s+i", l2, re.I):
                    break
                addr.append(l2)
            rec["address"] = " ".join(addr) or None
            break
    m = re.search(r"Numri\s+i\s+Akreditimit\s*\n?\s*([A-Z]{2})\s*0*(\d{1,3})", text, re.I)
    if m:
        rec["registration_no"] = f"{m.group(1).upper()}{int(m.group(2)):03d}"
    m = STD_RE.search(text)
    if m:
        rec["accreditation_standard"] = f"ISO/IEC {m.group(1)}:{m.group(2)}"
    rec["initial_accreditation_date"] = find_date(r"akreditimit\s+fillestar", text)
    rec["last_accreditation_date"] = find_date(r"akreditimit\s+t[ëe]\s+fundit", text)
    rec["valid_until"] = find_date(r"vlefshme\s+deri\s+m[ëe]\s+dat[ëe]", text)
    rec["issued_on"] = find_date(r"L[ëe]shuar\s+m[ëe]", text)
    m = re.search(r"Rishikimi\s*:\s*(\d+)", text, re.I)
    rec["certificate_revision"] = int(m.group(1)) if m else None
    rec["status"] = ("unknown" if not rec["valid_until"] else
                     "active" if rec["valid_until"] >= date.today().isoformat() else "expired")
    return rec


# ---------------------------------------------------------------- annex splitting
def split_annexes(pages):
    """Annex starts on a page containing 'Programi i AKREDITIMIT'; following
    pages without that header are continuations of the same annex."""
    annexes, cert_text = [], ""
    for idx, t in enumerate(pages, start=1):
        if re.search(r"programi\s+i\s+akreditimit", t, re.I):
            annexes.append({"pages": [idx], "text": t})
        elif re.search(r"[ÇC]ERTIFIKAT[ËE]\s+AKREDITIMI", t, re.I) and not annexes:
            cert_text += t
        elif annexes:
            annexes[-1]["pages"].append(idx)
            annexes[-1]["text"] += "\n" + t
        else:
            cert_text += t
    return cert_text, annexes


# ---------------------------------------------------------------- annex parsing
def norm_name(s):
    s = re.sub(r"sh\.?\s*p\.?\s*k\.?", "", s or "", flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_annex(block, body_name, include_contacts):
    text, flags = block["text"], []
    head_end = re.search(r"\bAdresa\b", text)
    header = text[:head_end.start()] if head_end else text[:1500]

    # supporting standards from header (everything except the base 17021-1)
    header_stds = [(m.group(1), m.group(2)) for m in STD_RE.finditer(header)]
    supporting = [f"{n}:{y}" for n, y in header_stds if n != "17021-1"]
    base_present = any(n == "17021-1" for n, _ in header_stds)
    if not base_present:
        flags.append("no_17021-1_in_header")
    support_numbers = {n for n, _ in header_stds}

    # annex company name (detects copy/paste errors, e.g. wrong company name)
    h = re.sub(r"Aneks\s+i\s+[ÇC]ertifikat[ëe]s\s+s[ëe]\s+Akreditimit", "", header, flags=re.I)
    m = re.search(r"([^\n]*?)\s*(sh\.?\s*p\.?\s*k\.?)", h, re.I)
    annex_name = m.group(0).strip() if m else None
    if annex_name and body_name:
        a, b = norm_name(annex_name), norm_name(body_name)
        if a and b and a not in b and b not in a:
            flags.append(f"annex_name_mismatch:{annex_name!r}")

    # scope part
    m = re.search(r"Akreditohet", text, re.I) or re.search(r"Fusha\s+e\s+Akredit", text, re.I)
    scope_text = text[m.start():] if m else text
    scope_text_nofooter = re.sub(r"Rishikimi\s*\d?\s*[:.]?.*?(?:\n|$)|E\s+vlefshme.*?(?:\n|$)",
                                 "\n", scope_text, flags=re.I)

    # scope standards (skip the supporting ones listed in the header)
    found, order = {}, []
    for sm in STD_RE.finditer(scope_text):
        n, y = sm.group(1), sm.group(2)
        if n in support_numbers or n.startswith("17021"):
            continue
        if n not in found:
            found[n] = {"version": y, "amendment": None}
            order.append(n)
            am = AMD_RE.match(scope_text[sm.end():sm.end() + 25])
            if am:
                found[n]["amendment"] = f"Amd {am.group(1)}:{am.group(2)}"
    extensions = [f"{n}:{found[n]['version']}" for n in order if n in EXTENSION_NUMBERS]
    main = [n for n in order if n not in EXTENSION_NUMBERS]
    if not main:
        flags.append("no_scope_standard_found")

    # sector scope
    all_codes = bool(re.search(r"gjitha\s+kodet", scope_text, re.I))
    ea = sorted({f"{int(c):02d}" for c in re.findall(r"\bEA\s*0?(\d{1,2})\b", scope_text_nofooter)
                 if 1 <= int(c) <= 39})
    if not ea and not all_codes:
        # CERTIS style table: rows are 'rev  code  description', no 'EA' prefix
        zi = re.search(r"P[ëe]rshkrimi\s+i\s+sektorit", scope_text)
        if zi:
            for line in scope_text[zi.end():].splitlines():
                mm = re.match(r"^\s*(?:0\s+)?(\d{1,2})(?:\s{2,}\S.*)?$", line)
                if mm and 1 <= int(mm.group(1)) <= 39:
                    ea.append(f"{int(mm.group(1)):02d}")
            ea = sorted(set(ea))

    cats, labels = [], []
    # lettered categories: "A - Industri ..." (50001, 22301)
    for mm in re.finditer(r"^\s*([A-K])\s*[-–.]\s+(.+?)\s*$", scope_text, re.M):
        cats.append(mm.group(1)); labels.append(mm.group(2).rstrip(".;"))
    # 22000 sub-categories (AI, AII, BI..BIII, C0, CI..CIV, FI, FII) and single letters
    if "22000" in main:
        subs = ["".join(m) for m in re.findall(
            r"(?<![A-Za-z0-9])([ABCFG])\s?(IV|III|II|I|0)(?![A-Za-z0-9])", scope_text)]
        singles = re.findall(r"^\s*(?:\S.*?\s{2,})?([D-K])\s{2,}\S", scope_text, re.M)
        subs = [c for c in subs if not (c.endswith("0") and c[0] != "C")]
        cats_all = set(subs) | set(singles)
        singles = [c for c in singles if not any(x != c and x.startswith(c) for x in cats_all)]
        roman = {"": 0, "0": 0, "I": 1, "II": 2, "III": 3, "IV": 4}
        cats = sorted(set(subs) | set(singles), key=lambda c: (c[0], roman.get(c[1:], 9)))
        flags.append("review_22000_categories")
    # 13485 technical areas, e.g. 1.1, 1.2, 1.4, A.1.7
    if "13485" in main:
        cats = sorted(set(re.findall(r"^\s*(A\.\d+\.\d+|\d\.\d)\.?\s", scope_text, re.M)))
        flags.append("review_13485_technical_areas")
    # label-only categories (CERTIS 50001: no letters)
    if not cats and "50001" in main and not all_codes:
        z = re.search(r"[Kk]ategorit[ëe]|P[ëe]rshkrimi\s+i\s+sektorit", scope_text)
        if z:
            for line in scope_text[z.end():].splitlines():
                if re.search(r"DREJTOR|Rishikimi\s*\d?\s*[:.]|E\s+vlefshme", line):
                    if labels:
                        break
                    continue
                s = re.sub(r"^\s*0\s+", "", line).strip(" ,.:\t")
                if s and not re.search(r"Rishikimi|P[ëe]rshkrimi", s):
                    labels.append(s)
    cats = list(dict.fromkeys(cats))

    # annex validity
    revs = re.findall(r"Rishikimi\s*(\d+)\s*[:.]\s*(?:L[ëe]shuar\s+m[ëe]\s*:?\s*)?" + DATE, text, re.I)
    valid = re.findall(r"vlefshme\s+deri\s+(?:n[ëe]|ne)\s+dat[ëe]n\s*:?\s*" + DATE, text, re.I)
    rev_no = int(revs[-1][0]) if revs else None
    rev_date = iso(*revs[-1][1:]) if revs else None
    valid_until = iso(*valid[-1]) if valid else None

    contacts = {}
    if include_contacts:
        em = re.search(r"[\w.\-]+@[\w.\-]+\.\w+", text)
        ph = re.search(r"\+\s*355[\d\s]{8,}", text)
        contacts = {"email": em.group(0) if em else None,
                    "phone": re.sub(r"\s+", " ", ph.group(0)).strip() if ph else None}

    rows = []
    for n in main:
        sup_expected = EXPECTED_SUPPORT.get(n)
        row_flags = list(flags)
        if sup_expected and not any(s.startswith(sup_expected) for s in supporting):
            row_flags.append(f"unexpected_supporting_standard(expected {sup_expected})")
        if all_codes:
            stype = "iaf_all"
        elif ea:
            stype = "ea_codes"
        elif n in CATEGORY_STANDARDS and (cats or labels):
            stype = "technical_areas" if n == "13485" else "categories"
        else:
            stype = "none"
            if n not in {"27001", "27701", "20000-1", "37001", "39001", "20121"}:
                row_flags.append("no_sector_scope_found")
        rows.append({
            "iso_standard": f"ISO {n}", "iso_number": n, "topic": STD_NAMES.get(n),
            "iso_version": found[n]["version"], "amendment": found[n]["amendment"],
            "supporting_standards": supporting,
            "extensions": extensions if n == "27001" else [],
            "scope_type": stype,
            "ea_codes": ea if stype == "ea_codes" else [],
            "categories": cats if stype in ("categories", "technical_areas") else [],
            "category_labels": labels if stype in ("categories", "technical_areas") else [],
            "annex_revision": rev_no, "annex_revision_date": rev_date,
            "annex_valid_until": valid_until, "source_pages": block["pages"],
            "annex_company_name": annex_name, "contacts": contacts, "flags": row_flags,
        })
    return rows


# ---------------------------------------------------------------- driver
def rows_from_annexes(annexes, cert, include_contacts, source_name):
    rows = []
    for a in annexes:
        for r in parse_annex(a, cert.get("body_name"), include_contacts):
            r.update({"registration_no": cert["registration_no"], "body_name": cert["body_name"],
                      "source_pdf": source_name})
            if cert["valid_until"] and r["annex_valid_until"] and r["annex_valid_until"] != cert["valid_until"]:
                r["flags"].append("annex_validity_differs_from_certificate")
            rows.append(r)
    return rows


def has_text(pages):
    return sum(len(p.strip()) for p in pages) >= 200


def scope_signature(rows):
    return {r["iso_standard"]: (r["annex_revision"], tuple(r["ea_codes"]), tuple(r["categories"]))
            for r in rows}


def process(pdf, include_contacts, scope_pdf=None, expected_code=None):
    """pdf = certificate PDF (may also contain annexes); scope_pdf = separate
    scope PDF (preferred source of scope if present)."""
    pages = pdf_pages(pdf)
    if not has_text(pages):
        return {"file": pdf.name, "certificate": {}, "scope": [],
                "flags": ["no_text_layer: run OCR (ocrmypdf -l sqi+eng) and retry"]}
    cert_text, annexes = split_annexes(pages)
    cert = parse_certificate(cert_text, include_contacts)
    cert["source_pdf"] = pdf.name
    flags = []
    if expected_code and cert.get("registration_no") and cert["registration_no"] != expected_code:
        flags.append(f"registration_no_differs_from_filename({cert['registration_no']} vs {expected_code})")
    if not cert.get("registration_no") and expected_code:
        cert["registration_no"] = expected_code

    rows = rows_from_annexes(annexes, cert, include_contacts, pdf.name) if annexes else []
    if scope_pdf:
        sp = pdf_pages(scope_pdf)
        if not has_text(sp):
            flags.append(f"scope_pdf_no_text_layer:{scope_pdf.name}")
        else:
            _, s_annexes = split_annexes(sp)
            s_rows = rows_from_annexes(s_annexes, cert, include_contacts, scope_pdf.name)
            if s_rows:
                if rows and scope_signature(rows) != scope_signature(s_rows):
                    flags.append("scope_pdf_differs_from_certificate_pdf (scope_pdf used)")
                rows = s_rows
            else:
                flags.append(f"no_annexes_in_scope_pdf:{scope_pdf.name}")

    seen, unique = {}, []
    for r in rows:
        k = (r["registration_no"], r["iso_standard"])
        if k in seen:
            seen[k]["flags"].append(f"duplicate_annex_ignored(pages {r['source_pages']})")
            if (r["ea_codes"], r["categories"]) != (seen[k]["ea_codes"], seen[k]["categories"]):
                seen[k]["flags"].append("duplicate_annex_has_different_scope")
        else:
            seen[k] = r; unique.append(r)
    rows = unique
    if not cert.get("registration_no"):
        flags.append("registration_no_not_found")
    if not rows:
        flags.append("no_annexes_found")
    return {"file": pdf.name, "certificate": cert, "scope": rows, "flags": flags}


FILE_RE = re.compile(r"^([A-Za-z]{2})\s*0*(\d+)_(certificate|scope)_rev(\d+)\.pdf$", re.I)


def collect_jobs(inputs):
    """Folders/files -> jobs. Groups '<CODE>_certificate_revN.pdf' and
    '<CODE>_scope_revM.pdf' per body and keeps the highest revision of each."""
    files = []
    for i in inputs:
        p = Path(i)
        files += sorted(p.glob("*.pdf")) if p.is_dir() else [p]
    groups, standalone = {}, []
    for f in files:
        m = FILE_RE.match(f.name)
        if not m:
            standalone.append(f); continue
        code = f"{m.group(1).upper()}{int(m.group(2)):03d}"
        kind, rev = m.group(3).lower(), int(m.group(4))
        g = groups.setdefault(code, {})
        if kind not in g or rev > g[kind][0]:
            g[kind] = (rev, f)
    jobs = []
    for code, g in sorted(groups.items()):
        cert = g.get("certificate", (None, None))[1]
        scope = g.get("scope", (None, None))[1]
        if cert is None:                       # only a scope PDF exists
            jobs.append({"pdf": scope, "scope_pdf": None, "code": code, "note": "no_certificate_pdf"})
        else:
            jobs.append({"pdf": cert, "scope_pdf": scope, "code": code, "note": None})
    jobs += [{"pdf": f, "scope_pdf": None, "code": None, "note": None} for f in standalone]
    return jobs


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ";".join(map(str, v)) if isinstance(v, list) else v for k, v in r.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+", help="PDF files and/or folders")
    ap.add_argument("--out", default="out")
    ap.add_argument("--include-contacts", action="store_true",
                    help="also extract company email/phone (never person names)")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(exist_ok=True)

    results = []
    for j in collect_jobs(a.pdfs):
        try:
            r = process(j["pdf"], a.include_contacts, j["scope_pdf"], j["code"])
            if j["note"]:
                r["flags"].append(j["note"])
        except Exception as e:  # one broken PDF must not stop the batch
            r = {"file": j["pdf"].name, "certificate": {}, "scope": [], "flags": [f"error:{e!r}"]}
        results.append(r)
        n = len(r["scope"])
        print(f"{j['pdf'].name:40s} {n:3d} scope rows  {'; '.join(r['flags'])[:70]}")
    certs = [r["certificate"] for r in results if r["certificate"]]
    scope = [s for r in results for s in r["scope"]]
    items = []
    for s in scope:
        base = {k: s[k] for k in ("registration_no", "iso_standard", "iso_version", "scope_type")}
        for c in s["ea_codes"]:
            items.append({**base, "code_type": "EA", "code": c})
        for c in s["categories"]:
            items.append({**base, "code_type": "category", "code": c})
        if s["scope_type"] == "iaf_all":
            items.append({**base, "code_type": "ALL", "code": "ALL"})
        if s["scope_type"] == "categories" and not s["categories"]:
            for lab in s["category_labels"]:
                items.append({**base, "code_type": "label", "code": lab})
    review = [{"file": s["source_pdf"], "registration_no": s["registration_no"],
               "iso_standard": s["iso_standard"], "pages": s["source_pages"], "flags": s["flags"]}
              for s in scope if s["flags"]]
    review += [{"file": r["file"], "flags": r["flags"]} for r in results if r["flags"]]

    write_csv(out / "certificates.csv", certs,
              ["registration_no", "body_name", "address", "accreditation_standard", "status",
               "initial_accreditation_date", "last_accreditation_date", "issued_on",
               "valid_until", "certificate_revision", "source_pdf"])
    write_csv(out / "scope_rows.csv", scope,
              ["registration_no", "body_name", "iso_standard", "topic", "iso_version", "amendment",
               "supporting_standards", "extensions", "scope_type", "ea_codes", "categories",
               "category_labels", "annex_revision", "annex_revision_date", "annex_valid_until",
               "source_pdf", "source_pages", "flags"])
    write_csv(out / "scope_items.csv", items,
              ["registration_no", "iso_standard", "iso_version", "scope_type", "code_type", "code"])
    write_csv(out / "review_queue.csv", review, ["file", "registration_no", "iso_standard", "pages", "flags"])
    (out / "parsed.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{len(certs)} certificates, {len(scope)} scope rows, {len(items)} scope items, "
          f"{len(review)} flagged -> {out}/")
    for c in certs:
        print(f"  {c.get('registration_no')} {c.get('body_name')}: {c['status']} until {c.get('valid_until')}")


if __name__ == "__main__":
    main()