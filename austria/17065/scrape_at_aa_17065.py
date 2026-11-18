"""Scrape Akkreditierung Austria ISO/IEC 17065 bodies (program 929, Produktzertifizierungsstellen).
Writes raw/aa_17065_raw.json for prepare_certifind_17065.py. Standard library only.
Note: the 2026-11-17 run used the same API calls in-browser (akkreditierung-austria.gv.at page context),
because the register host is not reachable from the workspace."""
import json, ssl, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://akkreditierung-austria.gv.at"
PROGRAM = 929
STATUSES = "VALID,REVOKED,SUSPENDED"


def ctx():
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


CTX = ctx()


def get(path, params=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=60, context=CTX) as r:
                return json.load(r)
        except Exception:
            if i == 2:
                raise


def main():
    listed, page = {}, 0
    while True:
        batch = get("/api/accreditationCabRevisions", {"statusList": STATUSES, "sort": "documentNumber,asc",
                                                       "size": 100, "page": page, "programId": PROGRAM})
        new = [r for r in batch if r["cabScopeRevisionId"] not in listed]
        listed.update((r["cabScopeRevisionId"], r) for r in new)
        if len(batch) < 100 or not new:
            break
        page += 1

    def detail(sid):
        try:
            return get(f"/api/accreditationCabRevisions/{sid}")
        except Exception:
            return listed[sid]

    with ThreadPoolExecutor(8) as ex:
        details = list(ex.map(detail, listed))
    bodies, scopes = {}, []
    for d in details:
        pub = [t for t in d.get("attributeTypes") or [] if t.get("publicVisibility")]
        attr = {t["nameEn"]: v for t in pub if (v := (d.get("attributeMap") or {}).get(str(t["id"]))) not in (None, "")}
        bodies.setdefault(d["cabPsid"], {
            "id": d["cabPsid"], "name": d.get("cabName"), "start": d.get("cabStartDate"), "last": d.get("lastDecisionDate"),
            "std": d.get("programStandard"),
            "org": [d.get(k) for k in ("orgName", "orgBusinessStreetAndNr", "orgBusinessPostCode", "orgBusinessCity",
                                       "orgBusinessCountry", "orgBusinessWebsite")],
            "contacts": [[c.get("type"), c.get("value")] for c in d.get("contacts") or [] if c.get("publicVisibility")],
            "addresses": [[a.get("type"), a.get("street"), a.get("postalCode"), a.get("city"), a.get("country")]
                          for a in d.get("addresses") or [] if a.get("publicVisibility")]})
        scopes.append({"id": d["cabScopeRevisionId"], "b": d["cabPsid"], "doc": d.get("docNr"), "title": d.get("docTitle"),
                       "type": d.get("type"), "status": d.get("status"), "issue": d.get("issueDate"),
                       "ics": [[f.get("icsNumber"), f.get("titleEn"), f.get("titleDe"), f.get("notifiedBody")]
                               for f in d.get("icsDTOs") or []], "attr": attr})
    out = Path(__file__).parent / "raw" / "aa_17065_raw.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"bodies": list(bodies.values()), "scopes": scopes}, ensure_ascii=False), encoding="utf-8")
    print(f"Bodies: {len(bodies)}, scope rows: {len(scopes)}")


if __name__ == "__main__":
    main()
