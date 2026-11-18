#!/usr/bin/env python3
"""SAAC (Saudi Arabia) 17065 scrape (saac_17065_raw.txt) -> certifind/data/saac-saudi-arabia-17065.

#BODIES idx;;name;;email;;phone;;city;;website  /  #CERTS id;;body;;field;;status;;start;;end;;iaf;;foodcat;;md8;;other
One accreditation per certificate (several certificates of one body are merged into the first, see review).
Lines = the scope-table texts ('other', '|' separated, Arabic or English technical regulations), scheme_text =
the register's main field. Country: from the city column when it names a country, else Saudi Arabia for
Saudi cities, else from the website / e-mail domain ending; left Saudi Arabia with a note when unknown.
Usage: python prepare_certifind_17065.py [raw_file] [--today YYYY-MM-DD]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as c  # noqa: E402

RAW, TODAY = c.cli(HERE / "saac_17065_raw.txt")
URL = "https://saac.gov.sa/en/accredited-cabs/?searchType=AdvancedSearch&serviceSearch=Products+Certificates"
notes = []
section, body_info, bodies = None, {}, {}
physical, buf = [], ""
for line in RAW.read_text(encoding="utf-8").splitlines():  # a body name with line breaks spans several lines
    if line.startswith("#"):
        if buf:
            physical.append(buf)
        physical.append(line)
        buf = ""
        continue
    buf = f"{buf} {line}".strip() if buf else line
    in_bodies = "#CERTS" not in physical and any(p.startswith("#BODIES") for p in physical)
    if not in_bodies or buf.count(";;") >= 5:
        physical.append(buf)
        buf = ""
if buf:
    physical.append(buf)
for line in physical:
    if line.startswith("#BODIES"):
        section = "b"
        continue
    if line.startswith("#CERTS"):
        section = "c"
        continue
    f = line.split(";;")
    if section == "b" and len(f) >= 6:
        idx, name, mail, tel, city, web = f[:6]
        country = c.country_name(city, "")
        if country not in c.DIAL:
            tld = (re.search(r"\.([a-z]{2})(?:/|$)", web.lower()) or re.search(r"\.([a-z]{2})$", mail.lower()) or [None, ""])[1]
            country = c.COUNTRY_FIX.get(tld, "") if city.lower().startswith("outside") else "Saudi Arabia"
            if not country:
                country = "Saudi Arabia"
                notes.append(f"{name}: city '{city}', country not determinable; set to Saudi Arabia")
        body_info[idx] = dict(name=name, email=mail, phone=tel, website=web, country=country,
                              address="" if city.lower().startswith("outside") else city)
    elif section == "c" and len(f) >= 10:
        cid, bi, fld, status, start, end, *_rest = f
        if not re.match(r"^[A-Z]-[A-Z]-\d+$", cid) or bi not in body_info:
            notes.append(f"unreadable certificate row skipped: {line[:80]}")
            continue
        info = body_info[bi]
        b = c.Body(reg=cid, name=info["name"], country=info["country"], phone=info["phone"], email=info["email"],
                   website=info["website"], address=info["address"], issued=c.iso_date(start.replace("/", "-")) if False else "",
                   expiry="", proof_url=URL, source_url=URL, active=status == "Active", status_note=status)
        m1 = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", start)
        m2 = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", end)
        b.issued = f"{m1[3]}-{int(m1[1]):02d}-{int(m1[2]):02d}" if m1 else ""
        b.expiry = f"{m2[3]}-{int(m2[1]):02d}-{int(m2[2]):02d}" if m2 else ""
        for t in f[9].split("|"):
            # industry from the line itself: the register's main field lists several schemes at once
            b.lines.append(c.Line(product_text=t, scheme_text=fld, industry=c.industry_of(t)))
        bodies[cid] = b
c.run("SAAC", "saac-saudi-arabia-17065", "saac-saudi-arabia", URL, list(bodies.values()),
      HERE / "saac_17065_review.md", TODAY,
      "SAAC register, advanced search service type 'Products Certificates', each CAB's detail page (scope tables). "
      "Scraper `database/saudi-arabia/17065/scrape_sa_saac_17065.py`; converter `prepare_certifind_17065.py`. Dates "
      "on the register are month/day/year.", notes)
