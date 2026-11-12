"""Scrape the ANAB management-systems CB directory (ISO/IEC 17021-1) into anab_raw.psv.

anabdirectory.remoteauditor.com and anab.jadian.com are not reachable from the build
sandbox, so the 2026-11-10 run was executed in a logged-out browser session with the same
logic (directory POST per standard + ShowPage paging, scope PDFs parsed with pdf.js).
This script reproduces it with requests + pypdf when run from an unrestricted network.
"""
import re, sys, io, requests
from pypdf import PdfReader

DIR = "https://anabdirectory.remoteauditor.com"
PDF = "https://anab.jadian.com/Certificate.mvc?PKey={}&useId=true&OrgId={}"
IN_SCOPE = ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 13485", "ISO 22000", "FSSC 22000", "ISO 50001",
            "ISO/IEC 27001", "ISO/IEC 27701", "ISO/IEC 20000-1", "ISO 22301"]
HDR = re.compile(r"^(ANAB SCOPE|Accreditation ID|Issue Date|To confirm|SCOPE OF ACCRED)")
END = re.compile(r"initial accreditation|^Accreditation (for|is scoped|in accordance)|Management System ?s?$|^IAF MLA|^Use in accordance|^Additional Office|^Based on|^\*")


def norm_std(s):
    s = re.sub(r"\s*-\s*", "-", s); s = re.sub(r"\s*/\s*", "/", s); s = re.sub(r"(\d) (?=\d)", r"\1", s)
    s = re.sub(r":\d{4}.*| V\d.*| Version.*", "", re.sub(r"\s+", " ", s)).strip()
    return {"S FI": "SFI", "A TFS": "ATFS"}.get(s, s)


def ndate(s):
    m = re.search(r"(\d{1,2})([A-Za-z]+)(\d{4})", re.sub(r"\s+", "", s or ""))
    return " ".join(m.groups()) if m else ""


def directory(sess):
    html = sess.get(DIR + "/").text
    stds = re.findall(r'<option value="([0-9A-F-]{36})">([^<]+)</option>', html)
    cbs = {}
    for sid, _name in stds:
        page = sess.post(DIR + "/Certificate/Browse", data={"StandardId": sid}).text
        pages = int((re.search(r"pageCount = (\d+)", page) or [0, 1])[1])
        for p in range(1, pages + 1):
            if p > 1:
                page = sess.post(DIR + "/Certificate/ShowPage", data={"pgNbr": p}).text
            for item in page.split('class="dirItem"')[1:]:
                t = re.search(r'<a href="([^"]*)" target="_blank">([^<]+)</a>', item)
                f = lambda lbl: (re.search(lbl + r'</span>\s*(?:<br />)?([^<]*)', item) or [0, ""])[1].strip()
                pk = re.search(r"PKey=([\w-]+).*?OrgId=([\w-]+)", item.replace("&amp;", "&"))
                em = re.search(r"EMail</span>\s*([^\s<]+)", item)
                cbs.setdefault(t[2], dict(title=t[2], web=t[1], phone=f("Phone"), country=f("Country"),
                                          email=em[1] if em else "", pkey=pk[1], org=pk[2]))
    return list(cbs.values())


def pdf_lines(sess, cb):
    data = sess.get(PDF.format(cb["pkey"], cb["org"])).content
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return [re.sub(r"\s+", " ", l).replace("scope d", "scoped").strip() for l in text.splitlines() if l.strip()]


def parse(lines):
    L = [l for l in lines if not HDR.match(l)]
    r = dict(since=ndate(next((l for l in L if "Accredited since" in l), "")),
             exp=ndate(next((l for l in L if "Accreditation expires" in l), "")), stds=[], sc={})
    hi = next((i for i, l in enumerate(L) if re.search(r"h ?as been( issued|$)", l)), 0)
    r["addr"] = " ~ ".join(L[:hi])
    pend = []
    for i, l in enumerate(L):
        m = re.match(r"(.+?) initial accreditation", l)
        if m:
            s = norm_std(m[1]); r["stds"] += [s] if s not in r["stds"] else []; pend.append(s); continue
        if re.match(r"Accreditation for .* scoped", l):
            j = re.sub(r"Rule (\d) (\d)", r"Rule \1\2", " ".join(L[i:i + 3]))
            rule = (re.search(r"Rule (\d+)", j) or [0, ""])[1]
            ex = re.match(r"Accreditation for (.+?) is scoped", l)
            if ex and not re.search(r"standards? above", ex[1]):
                tg = [norm_std(ex[1])]; pend = [p for p in pend if p != tg[0]]
            else:
                tg, pend = pend, []
            k = i + 1
            while k < len(L) and "following" not in L[k - 1] and k < i + 3: k += 1
            blk = []
            while k < len(L) and not END.search(L[k]): blk.append(L[k]); k += 1
            codes = []
            for b in blk:
                if rule in ("20", "21", "30"): codes += [m[1] for m in re.finditer(r"(?:^|\s)(\d{2})[a-z]?(?=\s+[A-Z“\"(])", b)]
                elif rule == "35": codes += re.findall(r"^(1\.\d)", b)
                elif rule in ("22", "50"): codes += re.findall(r"(?:^|\s)([A-K])(?=\s+[A-Za-z(])", b)
                elif rule == "23": codes += re.findall(r"^([A-K])(?:\s|$)", b)
            for s in tg:
                r["sc"][s] = sorted(set(r["sc"].get(s, []) + codes), key=lambda c: (len(c), c))
    return r


def main(out="anab_raw.psv"):
    sess = requests.Session()
    rows, exc = [], []
    for cb in directory(sess):
        lines = pdf_lines(sess, cb); r = parse(lines)
        rid = re.search(r"-MS-(\d+)", cb["title"])[1]; name = re.sub(r"^.*?-MS-\d+ - ", "", cb["title"])
        ins = [s for s in r["stds"] if s in IN_SCOPE]
        if not ins:
            exc.append(f"{rid}|{name}|{','.join(r['stds'])}"); continue
        sc = ";".join(f"{s}={','.join(map(str, r['sc'].get(s, [])))}" for s in ins)
        rows.append("|".join([rid, name, r["since"], r["exp"], r["addr"], cb["country"], cb["web"], cb["phone"],
                              cb["email"], cb["pkey"], cb["org"], sc, ",".join(s for s in r["stds"] if s not in IN_SCOPE)]))
    with open(out, "w", encoding="utf-8") as f:
        f.write("# id|title|since|expires|pdf_address|dir_country|website|phone|email|pkey|orgid|in_scope_schemes|other_schemes\n")
        f.write("\n".join(rows) + "\n#EXCLUDED id|name|schemes\n" + "\n".join(exc) + "\n")
    print(f"CBs: {len(rows) + len(exc)}\nIncluded: {len(rows)}\nExcluded: {len(exc)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
