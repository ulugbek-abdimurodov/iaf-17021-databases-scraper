#!/usr/bin/env python3
"""Scrape ENAC (Spain) Management System Certification bodies into raw files.

ENAC publishes its register through a Liferay portlet. Two resource views of the
same search drive this scraper (scheme idLista=46 = Management System
Certification, idPais=10 = default country filter returning all bodies):

  destino=listado    detailed cards: body name, address, phone, email and the
                     Technical Annex PDF link (/documents/7020/<uuid>). Request
                     delta=500 to get every result on one page (no pagination).
  destino=impresion  print view: the same rows in the same order, each ending
                     with the ENAC accreditation number + Spanish scope title.

The two views are index-aligned, so they zip into one record per accreditation.
Each Technical Annex PDF then yields the entry-into-force date and the sector
scope (IAF/EA codes, or food-chain categories / IAF MD 8 areas for ISO 22000 /
ISO 13485, or none for ISO/IEC 27001 and 20000 which are not sector-restricted).

Outputs raw_records.json and raw_ea.txt, consumed by prepare_certifind.py.

NOTE: run this from a network that can reach www.enac.es. In the Cowork sandbox
the egress proxy blocks enac.es (HTTP 403), so the production run was performed
through the browser (Claude in Chrome) using the identical endpoints and parsing
logic; see ../../data/enac-spain/SOURCES.md.
"""
import json
import re
import io
from pathlib import Path

import requests
import pdfplumber

HERE = Path(__file__).parent
BASE = "https://www.enac.es/web/english/accredited-bodies/products-and-services-searchs"
DOC = "https://www.enac.es/documents/7020/"
P = "_BuscadorProductoServicioUnificado_WAR_BuscadorProductoServicioUnificadoportlet_"
PID = "BuscadorProductoServicioUnificado_WAR_BuscadorProductoServicioUnificadoportlet"

ISO22 = {"A": [1], "B": [1], "C": [3], "D": [3], "E": [30], "F": [29],
         "G": [31], "H": [35], "I": [7, 14], "J": [18], "K": [12]}
MD8 = [(r"Non-active|no activos", [14, 17, 19, 34]),
       (r"non-implantable|no implantables", [19, 34]),
       (r"implantable|implantables", [19, 34]),
       (r"In vitro|in vitro", [12, 13, 19]),
       (r"Steriliz|esteriliz", [12, 35]),
       (r"incorporating|incorporan", [12, 13, 19]),
       (r"Parts or services|servicios", [14, 17, 18, 19, 29, 31, 34, 35])]


def _common_params():
    q = {"p_p_id": PID, "p_p_lifecycle": "2", "p_p_state": "normal",
         "p_p_mode": "view", "p_p_cacheability": "cacheLevelPage",
         "p_p_resource_id": "irA", P + "idLista": "46", P + "idPais": "10"}
    for k in ("idNivel1", "idNivel2", "idNivel2b", "idNivel3", "idNivel3b",
              "idNivel4", "idCategoria", "idEnsayo", "idComunidad", "idProvincia"):
        q[P + k] = "-1"
    return q


def fetch_records(sess):
    from bs4 import BeautifulSoup
    # detailed list (delta=500 -> everything on one page)
    q = _common_params()
    q[P + "destino"] = "listado"
    q[P + "delta"] = "500"
    q[P + "andOperator"] = "true"
    q[P + "cur"] = "1"
    lst = BeautifulSoup(sess.get(BASE, params=q).text, "html.parser")
    cards = lst.select("div.search-result")
    # print view (numbers + scope, same order)
    q2 = _common_params()
    q2[P + "destino"] = "impresion"
    imp_text = re.sub(r"\t", "", BeautifulSoup(sess.get(BASE, params=q2).text,
                                               "html.parser").get_text("\n"))
    num_re = re.compile(r"^(\d{1,4}/C-[A-Z]{1,3}\d{2,4})\s*-\s*(.*)$")
    imp = []
    name = ""
    for L in (x.strip() for x in imp_text.split("\n") if x.strip()):
        m = num_re.match(L)
        if m:
            imp.append((name, m.group(1), m.group(2).strip()))
        elif not re.match(r"^(Phone Number:|Email:)", L) and not re.search(
                r"\d{5}\s*-|nº|C/|Avda|Calle|Plaza|Polígono|Carretera", L):
            if len(L) > 3:
                name = L
    assert len(cards) == len(imp), f"misaligned {len(cards)} vs {len(imp)}"
    recs = []
    for i, (c, (nm, num, scope)) in enumerate(zip(cards, imp)):
        a = c.select_one('a[href*="/documents/7020/"]')
        tel = c.select_one('a[href^="tel:"]')
        mail = c.select_one('a[href^="mailto:"]')
        span = c.select_one("span")
        recs.append({
            "i": i,
            "name": (c.select_one(".title").get_text().strip()
                     if c.select_one(".title") else nm),
            "addr": span.get_text().strip() if span else "",
            "phone": tel["href"][4:] if tel else "",
            "email": mail["href"][7:] if mail else "",
            "annex": a["href"].split("/documents/7020/")[1].split("?")[0] if a else "",
            "num": num,
            "scope": scope,
        })
    return recs


def parse_annex(text, std):
    issue = rev = ""
    m = re.search(r"Coming into effect:?\s*(\d{2}/\d{2}/\d{4})", text)
    if m:
        issue = m.group(1)
    m = re.search(r"Rev\.?\s*\d+\s*fecha/date\s*(\d{2}/\d{2}/\d{4})", text, re.I)
    if m:
        rev = m.group(1)
    ea, note = set(), "iaf"
    if std in ("ISO/IEC 27001", "ISO/IEC 20000-1"):
        note = "not-sector-restricted"
    elif std == "ISO 22000":
        letters = [l for l in {ln.strip() for ln in text.split("\n")} if re.fullmatch(r"[A-K]", l)]
        for l in letters:
            ea.update(ISO22.get(l, []))
        note = "food-cat:" + "".join(sorted(letters))
    elif std == "ISO 13485":
        for pat, codes in MD8:
            if re.search(pat, text):
                ea.update(codes)
        note = "md8-areas"
    else:
        in_t = False
        for ln in (x.strip() for x in text.split("\n")):
            if re.search(r"Descripci.n\s*Description|SECTOR|IAF", ln):
                in_t = True
            if in_t and re.search(r"ENAC (is |es firmante)|Recognition", ln):
                in_t = False
            if in_t:
                mm = re.match(r"^(\d{1,2})(\s|$)", ln)
                if mm and 1 <= int(mm.group(1)) <= 39:
                    ea.add(int(mm.group(1)))
    return issue, rev, sorted(ea), note


# scope classifier shared with prepare_certifind.classify (standard only)
def std_of(scope):
    from prepare_certifind import classify
    return classify(scope)[0]


def main():
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (CertiFind scraper)"
    recs = fetch_records(sess)
    (HERE / "raw_records.json").write_text(
        json.dumps(recs, ensure_ascii=False, indent=0), encoding="utf-8")

    ea_lines = []
    for r in recs:
        std = std_of(r["scope"])
        if not std:
            continue
        pdf = sess.get(DOC + r["annex"]).content
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            text = "\n".join(p.extract_text() or "" for p in doc.pages)
        issue, rev, ea, note = parse_annex(text, std)
        ea_lines.append(f"{r['annex']}|{issue}|{rev}|{';'.join(map(str, ea))}|{note}")
    (HERE / "raw_ea.txt").write_text("\n".join(ea_lines) + "\n", encoding="utf-8")
    print(f"Records: {len(recs)} | Annexes parsed: {len(ea_lines)}")


if __name__ == "__main__":
    main()
