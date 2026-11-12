"""UAF (United Accreditation Foundation) MS-CAB scraper.

The UAF API/S3 hosts are not reachable from the build workspace, so the scrape runs
in the browser (page context of www.uafaccreditation.org) with the JS below and the
compact result is saved to raw/uaf.json. This file keeps the exact procedure.

API (programme 'Management Systems' = 26a769cf-d505-4347-8fff-0317a5328951):
  list:    https://newprodapi.uafaccreditation.org/api/account/cab/home/list/data/pagination/
           ?user_programmes=<MS>&is_cab_visible=true&is_cab_active=true&page_size=500
  detail:  .../api/account/cab/details/filter/?id=<user_id>
  docs:    .../api/cab/filter/documents/?cab=<user_id>   -> certificate & schedule PDFs (S3)
PDFs are text-extracted with pdf.js 4.0.379 and parsed in-page:
  * accreditation table after 'Valid Date': <scheme name> <acc no> <MM/DD/YYYY from> <MM/DD/YYYY to>
  * 'SCOPE OF ACCREDITATION' sections headed '... (QMS|EMS|OHSMS|ISMS|PIMS|BCMS|FSMS|MDQMS|IVD|EOG|ENMS|ITSMS)'
    -> IAF codes (leading 1-39), ISO 22003-1 category letters, IAF MD 8 main technical areas.
Output record: {n,sc,w,e,p,co,ci,st,z,a,id,docs:[{u,s:[[std,no,from,to,iaf,cats,mdIdx]]}],x:[excluded scheme names]}
"""
import json, sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "raw" / "uaf.json"

if __name__ == "__main__":
    d = json.loads(RAW.read_text())
    print(f"CABs: {len(d)} | PDFs: {sum(len(c['docs']) for c in d)}")
