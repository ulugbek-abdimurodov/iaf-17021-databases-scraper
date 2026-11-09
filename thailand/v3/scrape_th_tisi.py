"""TISI (Thailand) CB register scraper.
center.tisi.go.th is not reachable from the workspace proxy, so collection ran in the
browser against the same endpoints this script documents:
  list:   GET /report/certificate/data_list?draw=1&start=0&length=-1&sort=CB  (JSON, DataTables)
  detail: GET /report/certificate-en?id=<b64 id>&certify=Q0I  (address, phone, email, scope dates)
Rows kept: certify == 'CB' and accreditation no. prefix QMS|EMS|OHS|OHSMS|EnMS|SFMS.
Output: tisi_raw.json  [cert_no, accreditation_no, body, scope_from, scope_to, note]
"""
import json, re, sys, requests
BASE = "https://center.tisi.go.th"
MS = re.compile(r"^(QMS|EMS|OHSMS|OHS|EnMS|SFMS)\s*\d+")

def main():
    s = requests.Session()
    data = s.get(f"{BASE}/report/certificate/data_list", params={"draw": 1, "start": 0, "length": -1, "sort": "CB"}, timeout=60).json()["data"]
    out = []
    for r in data:
        acc = r["accereditatio_no"].replace("หน่วยรับรอง", "").strip()
        if r["certify"] != "CB" or not MS.match(acc):
            continue
        url = re.search(r'href="([^"]+)"', r["action"]).group(1).replace("certificate-th", "certificate-en")
        txt = re.sub(r"<[^>]+>", "|", s.get(url, timeout=60).text)
        m = re.search(r"scope from :\|+\s*([^|]*)\|+to\s*\|+\s*([^|]*)", txt)
        out.append([r["certificate_no"], acc, r["name"], *(m.groups() if m else ("", "")), ""])
    json.dump(out, open("tisi_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(f"Registrations: {len(out)}")

if __name__ == "__main__":
    sys.exit(main())
