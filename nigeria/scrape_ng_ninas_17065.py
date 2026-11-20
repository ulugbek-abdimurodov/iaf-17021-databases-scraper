"""Scrape NiNAS (Nigeria) accredited Product Certification Bodies, ISO/IEC 17065:: register rows + accreditation schedule PDFs."""
import html, json, re, subprocess, urllib.request
from pathlib import Path

URL = "https://ninas.ng/accreditation/accredited-product-bodies/"
OUT = Path(__file__).parent / "_raw_17065"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    page = get(URL).decode("utf8")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        pdf = re.search(r'href="([^"]+\.pdf)"', tr)
        if not pdf:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        name = clean(re.split(r"<br|Address", tds[0], flags=re.I)[0]) if tds else ""
        txt = clean(tds[1]) if len(tds) > 1 else ""
        g = lambda k, nxt: (re.search(rf"{k}:\s*(.*?)\s*(?:{nxt}|$)", txt) or [None, ""])[1].strip()
        rows.append({
            "name": name,
            "address": g("Address", "Email:"),
            "email": g("Email", "Phone:"),
            "phone": g("Phone", "$^"),
            "type": clean(tds[2]) if len(tds) > 2 else "",
            "status": clean(tds[-1]),
            "pdf": pdf.group(1),
        })
    for r in rows:
        f = OUT / Path(r["pdf"]).name
        f.write_bytes(get(r["pdf"]))
        subprocess.run(["pdftotext", "-layout", str(f), str(f.with_suffix(".txt"))], check=True)
        r["txt"] = f.with_suffix(".txt").name
    (OUT / "ninas_17065_raw.json").write_text(json.dumps(rows, indent=1), encoding="utf8")
    import csv
    with open(OUT / "scope_lines.csv", "w", encoding="utf8", newline="") as fh:
        w = csv.writer(fh); w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        n = 0
        for r in rows:
            lines = [l.strip() for l in (OUT / r["txt"]).read_text(encoding="utf8").splitlines() if l.strip()]
            for i, l in enumerate(lines):
                if re.search(r"IAF CODE|TYPE:|TGSB|GAMS|ECOSTAND|ISO|Standard", l):
                    w.writerow([re.search(r"No\.?\s*(PR\d+)", " ".join(lines)).group(1), "annex", i, l]); n += 1
    print(f"Scope lines: {n}")
    print(f"Register rows: {len(rows)} | PDFs: {len(rows)}")


if __name__ == "__main__":
    main()
