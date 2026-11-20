"""Scrape NiNAS (Nigeria) accredited management system CBs: register rows + accreditation schedule PDFs."""
import html, json, re, subprocess, urllib.request
from pathlib import Path

URL = "https://ninas.ng/accreditation/accredited-management-system-bodies/"
OUT = Path(__file__).parent / "_raw"
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
    (OUT / "register.json").write_text(json.dumps(rows, indent=1), encoding="utf8")
    print(f"Register rows: {len(rows)} | PDFs: {len(rows)}")


if __name__ == "__main__":
    main()
