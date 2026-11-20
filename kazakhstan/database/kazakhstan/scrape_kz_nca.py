"""Scrape the Kazakhstan NCA register for management system certification bodies (ISO/IEC 17021-1, ОПС СМ):
register rows, contacts and scope annexes (.doc/.docx/.pdf).

Source: the NCA register linked from www.nca.kz (kz_nca_register.py), activity fldActivityType[] = 7.
techreg.kezekte.kz/ru/acc/subjects, used until Nov 2026, now only shows an archive (mostly "Inactive",
no detail pages, files answer 404), so this scraper no longer uses it.

The register gives no scope tables on the page: scope is in the annex files, one file per scheme in most cases
("32.2.6  9001 - 3896.doc"), sometimes one file for all schemes. Annexes are turned into text by Microsoft Word
(COM, filtered HTML; antiword fails on many of them), then split into per-scheme pseudo tables that the
unchanged compact() reduces to IAF ranges / ISO 22003 categories / ISO 50003 areas.

Usage:  python scrape_kz_nca.py [--out ../../raw] [--limit N] [--no-pdf]
Output: <out>/subjects_full.json    register rows + per-file scope tables
        <out>/kz_nca_ms_bodies.json  compact input for prepare_certifind.py (same shape as before; the first
                                     field is now the first annex file id instead of a kezekte view id, and the
                                     BIN field holds the certificate number because the register has no BIN)
        <out>/pdf/<row>/<file_id>.doc|.docx|.pdf (+ .htm made by Word)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import kz_nca_register as reg  # noqa: E402

STD_RE = re.compile(r"(ISO/IEC 27001|ISO/IEC 20000-1|ISO 9001|ISO 14001|ISO 45001|ISO 50001|22000|OHSAS 18001|29001|1179|1352|12\.0\.\d+)")
FILE_STD = [(r"(?<!\d)27001(?!\d)", "ISO/IEC 27001"), (r"(?<!\d)20000(?!\d)", "ISO/IEC 20000-1"),
            (r"(?<!\d)9001(?!\d)", "ISO 9001"), (r"(?<!\d)14001(?!\d)", "ISO 14001"),
            (r"(?<!\d)45001(?!\d)", "ISO 45001"), (r"(?<!\d)50001(?!\d)", "ISO 50001"),
            (r"(?<!\d)22000(?!\d)", "22000"), (r"(?<!\d)29001(?!\d)", "29001"), (r"(?<!\d)37001(?!\d)", "37001")]
# a line that names a scheme as a heading, e.g. "СТ РК ISO 9001-2016 Системы менеджмента качества. Требования"
HEAD_RE = re.compile(r"^(?:СТ\s*РК\s*|ГОСТ\s*(?:Р\s*)?)?(?:ISO(?:/IEC)?|ИСО)\s*(\d{4,5})", re.I)


def file_std(name: str) -> str:
    for pat, std in FILE_STD:
        if re.search(pat, name):
            return std
    return ""


def tables_for_file(fname: str, lines: list[str]) -> list[dict]:
    """Split annex text into pseudo scope tables, one per scheme heading; rows are '|' cells."""
    tables, cur = [], {"std": file_std(fname) or fname, "hdr": [], "rows": []}
    for ln in lines:
        m = HEAD_RE.match(ln) if len(ln) < 220 else None
        if m:
            std = file_std(m.group(1)) or ln[:200]
            if cur["rows"]:
                tables.append(cur)
            cur = {"std": std, "hdr": [], "rows": []}
            continue
        cur["rows"].append([c.strip() for c in ln.split("|")])
    if cur["rows"]:
        tables.append(cur)
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
    """Per scheme: [IAF/EA ranges, ISO 22003 categories, ISO 50003 areas, NACE divisions]. (unchanged)"""
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
    return out


def contacts_text(r):
    addr = re.split(r"\s*(?:тел\.?|телефон|факс)\s*[.:]", r["address_block"], maxsplit=1, flags=re.I)[0]
    return f"Email: {r['email']}\nТелефон: {r['phone']}\nФактический адрес: {addr.strip(' ,;')}"


def main():
    ap = argparse.ArgumentParser(description="Scrape NCA Kazakhstan management system certification bodies.")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "raw"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-pdf", "--no-files", dest="no_pdf", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = reg.fetch_list(reg.ACT_MS)
    print(f"register: {len(rows)} rows")
    if a.limit:
        rows = rows[:a.limit]
    paths, failed = {}, 0
    if not a.no_pdf:
        for r in rows:
            for f in r["files"]:
                try:
                    paths[f["id"]] = reg.download(f["id"], out / "pdf" / r["row_no"].zfill(3), f["name"])
                except Exception as e:
                    failed += 1
                    print(f"file failed {r['registration_no']} {f['name']}: {e}")
        reg.convert_with_word(out / "pdf")

    full, comp = [], []
    for r in rows:
        tables = []
        for f in r["files"]:
            p = paths.get(f["id"])
            if p:
                tables += tables_for_file(f["name"], reg.text_lines(p))
        full.append({**r, "scope_tables": tables, "files": {f["name"]: reg.file_url(f["id"]) for f in r["files"]}})
        vid = r["files"][0]["id"] if r["files"] else ""
        status = "Действует" if r["status"] == "Active" else r["status"]
        comp.append([vid, r["registration_no"], r["issued"], r["expiry"], status, r["registration_no"], r["name"],
                     contacts_text(r), compact(r, tables)])

    (out / "subjects_full.json").write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "kz_nca_ms_bodies.json").write_text(json.dumps(comp, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Registrations: {len(rows)} | bodies: {len({r['registration_no'] for r in rows})} | "
          f"files: {len(paths)} ok, {failed} failed | rows with schemes: {sum(1 for c in comp if c[-1])}")


if __name__ == "__main__":
    main()
