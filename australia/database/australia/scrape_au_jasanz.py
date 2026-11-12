"""Scrape JASANZ register (https://register.jasanz.org/accredited-bodies) via its public JSON API.
Writes raw/jasanz_cabs.json in the compact format consumed by prepare_certifind.py.
Note: this run was executed in-browser (same endpoints) because the workspace proxy blocks the API host."""
import json, re, requests
from pathlib import Path

API = "https://jasanzcupr-api.azurewebsites.net/api/V1/RegisterCertificate/"
STD = re.compile(r"^(ISO 9001|ISO 14001|ISO 45001|ISO 13485|ISO 3834|EN 15224|ISO 22000|FSSC 22000|ISO 50001|ISO/IEC 27001|ISO/IEC 27701|ISO/IEC 20000-1|ISO 22301)")
FOOD = {"A": [1], "B": [1], "C": [3], "D": [3], "E": [30], "F": [29], "G": [31], "H": [35], "I": [7, 14], "J": [18], "K": [12]}

def md8(v):
    v = v.lower()
    if re.search(r"steril|aseptic|formaldehyde|steam|ethylene|irradiat", v): return [12, 35]
    if re.search(r"in vitro|ivd", v): return [12, 13, 19]
    if re.search(r"substance|incorporat|utiliz|biological|nano|micromech", v): return [12, 13, 19]
    if re.search(r"part|service|component|distribut|mainten|raw mat|assembl", v): return [14, 17, 18, 19, 29, 31, 34, 35]
    if re.search(r"active|imaging|radiation|monitor|electro|software", v) and "non-active" not in v: return [19, 34]
    return [14, 17, 19, 34]

def ea_for(std, sectors):
    from certifind_common import compress_ea_codes
    ea = []
    for s in sectors:
        s = s.strip()
        m = re.match(r"^(\d{1,2})", s)
        if m: ea.append(int(m.group(1)))
        elif "13485" in std: ea += md8(s)
        elif "22000" in std and s[:1] in FOOD: ea += FOOD[s[:1]]
    return compress_ea_codes(ea)

def get(path):
    return requests.get(API + path, timeout=60).json().get("data")

def main():
    X, B = [], []
    for c in get("GetFilteredCABRegister"):
        i, s = get(f"GetCABsInformation?Id={c['id']}") or {}, get(f"CabSchemeScopeDetails?Id={c['id']}") or {}
        acc = (i.get("accreditations") or [{}])[0]
        loc = next((l for l in i.get("locations") or [] if l.get("isHeadOffice")), None)
        sc, xs = [], []
        for d in s.get("schemeDetailList") or []:
            std = next((x["name"] for x in d.get("certificationStandard") or [] if STD.match(x["name"])), None)
            if std: sc.append([re.sub(r",.*$", "", std), ea_for(std, [t["name"] for t in d.get("technicalSector") or []])])
            elif d["schemeName"] not in xs: xs.append(d["schemeName"])
        B.append([i.get("name") or c["name"], i.get("abbreviation"), acc.get("accreditaionNumber"),
                  i.get("lastAccreditationIssued") or acc.get("accreditaionDate"), i.get("accreditationExpiryDate"),
                  i.get("webContactUrl"), i.get("webContactPhone"), i.get("webContactEmail"),
                  [loc.get(k) or "" for k in ("line1", "line2", "line3", "city", "state", "postalCode", "country")] if loc else [],
                  sc, [X.index(x) if x in X else (X.append(x) or len(X) - 1) for x in xs]])
    out = Path(__file__).parent / "raw" / "jasanz_cabs.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"X": X, "B": B}, ensure_ascii=False), encoding="utf-8")
    print(f"Bodies scraped: {len(B)}")

if __name__ == "__main__":
    main()
