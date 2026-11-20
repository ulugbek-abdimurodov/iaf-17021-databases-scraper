"""Read the Word-made .htm of each NCA 17065 annex into records using the real table grid (rowspan/colspan), so the
columns (№ | TNVED code | object name | scheme no. | KPVED code | service name | normative documents) stay apart.
Output: nca_17065/annex_records.json  {source: [ {n, tnved, product, scheme_no, service_code, service, norm}, ... ]}
Files without a table grid (PDF annexes, no .htm) are listed under "_unread"."""
import json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / "nca_17065"
WS = re.compile(r"\s+")


def clean(t):
    return WS.sub(" ", (t or "").replace("\xa0", " ")).strip()


def grid(table):
    rows, occ = [], {}
    for ri, tr in enumerate(table.find_all("tr", recursive=False) or [t for t in table.find_all("tr") if t.find_parent("table") is table]):
        cells, col = {}, 0
        for td in tr.find_all(["td", "th"], recursive=False):
            while occ.get((ri, col)):
                col += 1
            cs, rs = int(re.sub(r"\D", "", td.get("colspan", "1")) or 1), int(re.sub(r"\D", "", td.get("rowspan", "1")) or 1)
            cells[col] = (clean(td.get_text(" ")), cs, rs)
            for r in range(ri, ri + rs):
                for c in range(col, col + cs):
                    occ[(r, c)] = True
            col += cs
        rows.append(cells)
    return rows


HDR = {"tnved": r"кодтоварной|кодпродукции|тнвэд", "product": r"наименованиеобъекта|объектаоценки",
       "scheme_no": r"номерсхем|номерсхе", "service_code": r"кодуслуги", "service": r"наименованиеуслуги",
       "norm": r"обозначениенормативн|обозначение(?:нпа|документ)"}


def join_frag(parts):
    out = ""
    for p in parts:
        out = out + p if out.endswith("-") and not out.endswith(" -") else (out + " " + p if out else p)
    return out


def is_numbering(r):
    t = [v[0] for v in r.values() if v[0]]
    if len(t) < 4 or not all(re.fullmatch(r"\d{1,2}", x) for x in t):
        return False
    n = [int(x) for x in t]
    return sum(1 for a, b in zip(n, n[1:]) if b == a + 1) >= (len(n) - 1) / 2


def is_data_start(r, nc=0):
    f = r.get(nc)
    if is_numbering(r) or not f or not re.fullmatch(r"\d{1,5}\.?", f[0]) or len(r) <= 2:
        return False
    return not (r.get(nc + 1) and r[nc + 1][0] == "2" and f[0] == "1")


def number_col(rows):
    best, bc = 0, 0
    for c in range(0, 4):
        ints = [int(v[0].rstrip(".")) for r in rows if not is_numbering(r) for cc, v in r.items() if cc == c and re.fullmatch(r"\d{1,4}\.?", v[0].rstrip("."))]
        inc = sum(1 for x, y in zip(ints, ints[1:]) if y == x + 1)
        if inc > best:
            best, bc = inc, c
    return bc


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    recs, cols, cols_n, ncol, cur = [], None, None, 0, None
    for table in soup.find_all("table"):
        if table.find_parent("table"):
            continue
        rows = grid(table)
        nc = number_col(rows)
        fd = next((i for i, r in enumerate(rows) if is_data_start(r, nc)), None)
        head = rows[:fd] if fd is not None else rows[:12]
        colt = {}
        for r in head:
            for c, (t, cs, rs) in r.items():
                colt.setdefault(c, []).append(t)
        m = {}
        for c, ts in colt.items():
            comp = re.sub(r"[-\s]+", "", " ".join(ts)).lower()
            for k, rx in HDR.items():
                if k not in m.values() and re.search(rx, comp):
                    m[c] = k
                    break
        tn = max((c + v[1] for r in rows for c, v in r.items()), default=0)
        if "product" in m.values() and "norm" in m.values():
            cols, cols_n, ncol = m, tn, nc
        elif not cols and tn == 7 and fd is not None and len(rows[fd]) >= 6 and re.fullmatch(r"[\d ;,]{4,}", rows[fd].get(1, ("",))[0] or "x")                 and any(len(r) == 7 and r.get(0, ("",))[0] == "1" and r.get(1, ("",))[0] == "2" for r in rows[:fd + 1]):
            cols, cols_n, ncol = {1: "tnved", 2: "product", 3: "scheme_no", 6: "norm"}, 7, 0  # 7-column form, header outside any table
        if fd is None or not cols or tn != cols_n:
            continue
        for r in rows[fd:]:
            if is_numbering(r):
                continue
            if is_data_start(r, ncol):
                cur = {"n": r[ncol][0].rstrip("."), "tnved": [], "product": [], "scheme_no": [], "service_code": [], "service": [], "norm": []}
                recs.append(cur)
            if cur is None:
                continue
            for c, (t, cs, rs) in r.items():
                k = cols.get(c)
                if k and t:
                    cur[k].append(t)
    return [{k: (v if k == "n" else join_frag(v)) for k, v in x.items()} for x in recs]


def work(args):
    src, path = args
    b = Path(path).read_bytes()
    m = re.search(rb"charset=([\w-]+)", b[:3000])
    return src, parse(b.decode(m.group(1).decode() if m else "utf-8", "ignore"))


def main():
    from multiprocessing import Pool
    raw = json.load(open(OUT / "nca_17065_raw.json", encoding="utf-8"))
    jobs, unread = [], []
    for r in raw:
        d = OUT / "files" / r["id"].zfill(3)
        for fid, name in zip([u.rsplit("=", 1)[1] for u in r["annex_urls"]], r["annex_names"]):
            src = f"annex:{r['id']}:{fid}:{name[:80]}"
            if (d / f"{fid}.htm").exists():
                jobs.append((src, str(d / f"{fid}.htm")))
            else:
                unread.append(src)
    with Pool(6) as p:
        res = dict(p.imap_unordered(work, jobs, chunksize=4))
    unread += [k for k, v in res.items() if not v]
    res["_unread"] = sorted(unread)
    json.dump(res, open(OUT / "annex_records.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("files", len(res) - 1, "records", sum(len(v) for k, v in res.items() if k != "_unread"), "unread", len(unread))


if __name__ == "__main__":
    main()
