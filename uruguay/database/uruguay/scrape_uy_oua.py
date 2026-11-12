"""Scrape OUA (Uruguay) ISO/IEC 17021-1 register + scope PDFs into raw_oua.json.
Scope tables: rows start with IAF/EA code; 'X' marks are mapped to the nearest standard column by x-position.
Note: workspace egress blocked this host on 2026-11-10; raw_oua.json was captured in-browser with the same logic (pdf.js)."""
import io, json, re, requests, pdfplumber
BASE = "https://www.organismouruguayodeacreditacion.org"
PAGE = BASE + "/organismos-de-certificacion-de-sistemas-de-gestion-ocs/"

def parse_scope(pdf_bytes):
    res = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        H = None
        for p in pdf.pages:
            rows = {}
            for w in p.extract_words():
                rows.setdefault(round(w["top"] / 3), []).append((w["x0"], w["text"]))
            for _, r in sorted(rows.items()):
                r.sort()
                hs = [(x, re.search(r"\d{4,5}", t).group()) for x, t in r if re.search(r"(9001|14001|45001|22000)", t)]
                if hs and any(re.search(r"IAF|Categor|Grupo", t) for _, t in r):
                    H = hs; continue
                if H and r and r[0][0] < 90 and re.fullmatch(r"\d{1,2}|[A-K][IV0]*", r[0][1]):
                    for x, t in r:
                        if t == "X":
                            std = min(H, key=lambda h: abs(h[0] - x))[1]
                            res.setdefault(std, []).append(r[0][1])
    return res

if __name__ == "__main__":
    html = requests.get(PAGE, timeout=60).text
    pdfs = re.findall(r'href="([^"]*OUAIMP034[^"]*\.pdf)"', html)
    out = {u: parse_scope(requests.get(u, timeout=60).content) for u in pdfs}
    json.dump(out, open("raw_oua.json", "w"), indent=1)
