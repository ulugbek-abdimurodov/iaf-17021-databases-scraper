"""Scrape Kazakhstan NCA register (techreg.kezekte.kz) for management system
certification bodies (ISO/IEC 17021-1): list, accreditation scope tables,
attestat PDFs (RU/KZ) and scope annex PDFs.

Usage:  python scrape_kz_nca.py [--out raw] [--no-pdf]
Output: <out>/subjects_full.json  (all list fields + every scope table, verbatim)
        <out>/kz_nca_ms_bodies.json (compact input for prepare_certifind.py)
        <out>/pdf/<id>_attestat_ru.pdf, <id>_attestat_kz.pdf, <id>_scope.pdf
"""
import argparse
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://techreg.kezekte.kz"
LIST_URL = BASE + "/ru/acc/subjects"
VIEW_URL = BASE + "/ru/acc/subjects/verifications/view/{id}"
FILES = {
    "attestat_ru": "/ru/acc/subjects/verifications/attestat-download/{id}",
    "attestat_kz": "/ru/acc/subjects/verifications/attestat-kz-download/{id}",
    "scope": "/ru/acc/subjects/verifications/download/{id}",
}
MS_TYPE = "ОрганПоПодтверждениюСоответствияСистемыМенеджментаКачества"
STD_RE = re.compile(r"(ISO/IEC 27001|ISO/IEC 20000-1|ISO 9001|ISO 14001|ISO 45001|ISO 50001|22000|OHSAS 18001|29001|1179|1352|12\.0\.\d+)")

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (registry-scraper)"


def get(url, **kw):
    for attempt in range(4):
        try:
            r = S.get(url, timeout=60, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ")).strip()


def scrape_list():
    rows, page = [], 1
    while True:
        soup = BeautifulSoup(get(LIST_URL, params={"flApplicantType": MS_TYPE, "p": page}).text, "html.parser")
        hdr = [txt(th) for th in soup.select("table thead th")]
        trs = [tr for tr in soup.select("table tbody tr") if tr.find("a", href=re.compile(r"/view/\d+"))]
        if not trs:
            break
        for tr in trs:
            cells = [c.get_text("\n").strip() for c in tr.find_all("td")]
            cells = [re.sub(r"[ \t]*\n\s*", "\n", c) for c in cells]
            rec = dict(zip(hdr, cells))
            rec["_id"] = re.search(r"/view/(\d+)", tr.find("a", href=re.compile(r"/view/\d+"))["href"]).group(1)
            rows.append(rec)
        page += 1
    return rows


def heading(table):
    """Nearest preceding non-empty text = scheme/standard title of a scope table."""
    el = table
    for _ in range(6):
        sib = el.find_previous_sibling()
        while sib is not None:
            t = txt(sib)
            if t:
                return t[-200:]
            sib = sib.find_previous_sibling()
        el = el.parent
        if el is None:
            break
    return ""


def scrape_view(vid):
    soup = BeautifulSoup(get(VIEW_URL.format(id=vid)).text, "html.parser")
    tables = []
    for t in soup.find_all("table"):
        rows = [[txt(c) for c in tr.find_all(["td", "th"])] for tr in t.find_all("tr")]
        if rows:
            tables.append({"std": heading(t), "hdr": rows[0], "rows": rows[1:]})
    return tables


def compress(nums):
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ";".join(out)


def compact(rec, tables):
    """Per scheme: [IAF/EA ranges, ISO 22003 categories, ISO 50003 areas, NACE divisions]."""
    sc = {}
    for t in tables:
        m = STD_RE.search(t["std"])
        k = m.group(1) if m else "LEGACY"
        s = sc.setdefault(k, {"iaf": set(), "c": [], "z": [], "kp": set()})
        for row in t["rows"]:
            line = " | ".join(row)
            s["iaf"].update(int(x) for x in re.findall(r"IAF\s*(\d+)", line))
            s["kp"].update(re.findall(r"(?:^|[ ;,(])(\d\d)\.\d\d(?:\.\d)?", line))
            if re.search(r"22000|1179", k) and len(row) > 1 and row[1][:22] not in s["c"]:
                s["c"].append(row[1][:22])
            if k == "ISO 50001" and row and row[0][:8] not in s["z"]:
                s["z"].append(row[0][:8])
    out = {}
    for k, v in sc.items():
        kp = [] if (v["iaf"] or v["c"]) else sorted(v["kp"])
        out[k] = [compress(v["iaf"]), "/".join(v["c"]), "/".join(v["z"]), " ".join(kp)]
    g = lambda key: next((val for h, val in rec.items() if h.startswith(key)), "")
    contacts = re.sub(r"Республика Казахстан,?\s*", "", g("Контактные"))
    return [rec["_id"], g("Номер Аттестата"), g("Дата начала"), g("Дата окончания"), g("Статус"),
            g("БИН"), g("Наименование субъекта"), contacts, out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="raw")
    ap.add_argument("--no-pdf", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)

    rows = scrape_list()
    full, comp, seen = [], [], {}
    for rec in rows:
        vid = rec["_id"]
        if vid not in seen:
            seen[vid] = scrape_view(vid)
            time.sleep(0.5)
        full.append({**rec, "scope_tables": seen[vid], "view_url": VIEW_URL.format(id=vid),
                     "files": {k: BASE + v.format(id=vid) for k, v in FILES.items()}})
        comp.append(compact(rec, seen[vid]))
        if not a.no_pdf:
            for k, path in FILES.items():
                dest = out / "pdf" / f"{vid}_{k}.pdf"
                if not dest.exists():
                    r = get(BASE + path.format(id=vid))
                    if r.content[:4] == b"%PDF":
                        dest.write_bytes(r.content)
                    time.sleep(0.3)

    (out / "subjects_full.json").write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "kz_nca_ms_bodies.json").write_text(json.dumps(comp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Registrations: {len(rows)} | Scope pages: {len(seen)} | PDFs: {len(list((out / 'pdf').glob('*.pdf')))}")


if __name__ == "__main__":
    main()
