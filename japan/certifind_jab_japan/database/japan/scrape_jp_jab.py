"""Scrape JAB (Japan) management system CABs (cert_num CM*) from the Strapi API behind
https://www.jab.or.jp/en/certification_institutions and write jab_raw.txt.
Scope restrictions ("Limited to" / "Except") per IAF code are kept in the last column."""
import re, sys, requests
API = "https://www.jab.or.jp/cms/api/certifications"
PARAMS = {"pagination[pageSize]": 200, "populate": "*", "filters[cert_num][$startsWith]": "CM"}

def sections(text):
    sec, cur, rest = {}, None, {}
    for l in (text or "").splitlines():
        l = l.strip()
        m = re.match(r"^=== (.+) ===$", l)
        if m:
            cur = m.group(1); sec[cur] = []; continue
        c = cur and re.match(r"^(\d+|[A-Z]{1,3})\s+(.{0,45})", l)
        if c:
            r = re.search(r"\(\s*(Limited to|Except)", l)
            if r:
                rest.setdefault(cur, []).append(f"{c[1]} {r.group(1).lower()}")
            sec[cur].append(c[1] + ("~" + c[2].split("(")[0].strip() if cur == "MD-QMS" else ""))
    return sec, rest

def main():
    data = requests.get(API, params=PARAMS, timeout=60).json()["data"]
    with open("jab_raw.txt", "w", encoding="utf-8") as f:
        for r in data:
            x = r["attributes"]
            pdf = ((x.get("en_file") or {}).get("data") or {}).get("attributes", {}).get("url", "")
            secd, rest = sections(x.get("en_cert_scope"))
            sec = ";".join(f"{k}:{','.join(v)}" for k, v in secd.items())
            rst = ";".join(f"{k}:{','.join(v)}" for k, v in rest.items())
            row = [x["cert_num"], x.get("en_name") or "", x.get("en_location") or "", x.get("en_contact_tel") or "",
                   x.get("url") or "", x["init_cert_date"], x["renew_date"], x["exp_date"], pdf.replace("/uploads/", ""), sec, rst]
            f.write("|".join(re.sub(r"\s+", " ", str(v)).strip() for v in row) + "\n")
    print(f"Registrations: {len(data)}", file=sys.stderr)

if __name__ == "__main__":
    main()
