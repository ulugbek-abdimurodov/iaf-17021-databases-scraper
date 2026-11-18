"""GAC (Georgia) ISO/IEC 17065 scraper.

API: GET https://gac.gov.ge/api/accredited-bodies?lang=en&bodyStatuses=ACTIVE&page=N&limit=100
Filter: evaluationStandard.en contains '17065' (cert prefix GAC-PRC-).
Scope: item.scope.en / item.scope.ge (HTML, numbered list) -> no PDF parsing needed.
Annex: item.files[].link.ge (scope PDF = files[0]).
Note: gac.gov.ge is not reachable from the cloud workspace; raw JSON was captured
via the browser and saved as gac_17065_raw.json. This script re-fetches when run
from a machine with access, else rebuilds scope_lines.csv from the saved JSON.
"""
import csv, json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
API = "https://gac.gov.ge/api/accredited-bodies"


def strip(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;", " ", h or "")).strip()


def fetch():
    import requests
    out, page = [], 1
    while True:
        r = requests.get(API, params={"lang": "en", "bodyStatuses": "ACTIVE", "page": page, "limit": 100}, timeout=60).json()
        out += r["items"]
        if len(r["items"]) < 100:
            break
        page += 1
    recs = []
    for b in out:
        if "17065" not in json.dumps(b.get("evaluationStandard") or ""):
            continue
        a = (b.get("addresses") or [{}])[0]
        grants = sorted(c["effectiveDate"][:10] for c in b.get("changelog") or [] if c.get("action") == "ACCREDITATION_GRANTED" and c.get("effectiveDate"))
        recs.append({
            "registration_no": b["certificateNumber"].strip(), "id": b["identifier"],
            "name": re.sub(r"\s+", " ", (b["organizationName"].get("en") or "")).strip(" “”"),
            "address": (a.get("title") or {}).get("en", "").strip(), "phone": (a.get("phone") or "").strip(),
            "email": (a.get("email") or "").strip(), "website": (a.get("website") or "").strip(),
            "issued": grants[0] if grants else "", "expiry": (b.get("computedExpireDate") or "")[:10],
            "annex_urls": [f["link"]["ge"] for f in b.get("files") or [] if f.get("link", {}).get("ge")][:1],
            "scope_en": strip((b.get("scope") or {}).get("en")), "scope_ge": strip((b.get("scope") or {}).get("ge")),
        })
    return recs


def split_scope(s):
    return [p.strip(" ;.") for p in re.split(r"(?:^|[;.]?\s*)\d+\s*\.\s*", s) if p.strip(" ;.")]


def main():
    raw = HERE / "gac_17065_raw.json"
    try:
        recs = fetch()
        raw.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        recs = json.loads(raw.read_text(encoding="utf-8"))
    n = 0
    with open(HERE / "scope_lines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["registration_no", "source", "row_index", "product_text_raw"])
        for r in recs:
            for src in ("en", "ge"):
                for i, line in enumerate(split_scope(r["scope_" + src]), 1):
                    w.writerow([r["registration_no"], "api_scope_" + src, i, line]); n += 1
    print(f"Bodies: {len(recs)}\nScope lines: {n}", file=sys.stderr)


if __name__ == "__main__":
    main()
