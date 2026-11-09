"""End-to-end tests against a local mock with the live site's HTML structure,
including its malformed rows ("</tr> <td>" with no opening <tr>)."""
import csv
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import esyd_scraper as es  # noqa: E402


def doc_cell(doc_id):
    return (f'<td valign="middle"> <div align="center"> '
            f'<a href="/eped/1.{doc_id}_el.doc" target="_blank" title="In Greek"><img alt="In Greek"></a> '
            f'<a href="/eped/1.{doc_id}_en.doc" target="_blank" title="In English"><img alt="In English"></a> '
            f'</div> </td>')


def value(text):
    return f'<td valign="middle"><div align="center">{text}&nbsp;</div></td>'


def group(standard, rows):
    """One standard group, malformed as on the live site: only the first row opens <tr>."""
    html = ""
    for index, (name, cert, since, doc_id) in enumerate(rows):
        head = (f'<tr valign="top"> <td rowspan="{len(rows)}" class="bold-blue"> {standard} </td> '
                if index == 0 else "")
        html += f"{head}<td>{name}&nbsp;</td> {value(cert)} {value(since)} {doc_cell(doc_id)} </tr> "
    return html


def org_page(name, contact, groups, headers=None):
    headers = headers or ["Accreditation Standard", "Accreditation Field", "Certificate Number",
                          "Valid Since", "Scope of Accreditation"]
    rows = "".join(
        f'<tr> <td class="bold-blue" valign="top" width="20%"> {k}</td> <td>{v}&nbsp;</td> </tr>'
        for k, v in contact.items())
    head = "".join(f'<td class="bold-blue"><div align="center">{h}</div></td>' for h in headers)
    return f"""<html><body><table><tr><td><table><tr><td>menu</td></tr></table></td>
<td><table width="100%" border="1"> <tr> <td class="title3" colspan="2" valign="top">{name}</td> </tr> {rows} </table>
<br/><table border="0"> <tr> <td class="title2">Body Accreditations</td> </tr></table>
<table width="100%" border="1"> <tr> {head} </tr> {"".join(groups)} </table>
</td></tr></table></body></html>"""


CONTACT = dict(Address="19 Maiou Str. 52, 57001 Thessaloniki, Greece", City="Thessaloniki", Region="",
               Telephone="2310 210777", FAX="2310 210417", Email="info@example.gr", Website="")
GREEK_HEADERS = ["Πρότυπο Διαπίστευσης", "Πεδίο Διαπίστευσης", "Αριθμός Πιστοποιητικού",
                 "Ημ. Έναρξης Ισχύος Πιστοποιητικού", "ΕΠΕΔ"]

ORGS = {
    # 17021 first, then another standard that must not leak in.
    "1": org_page("A CERT S.A.", CONTACT, [
        group("ELOT ΕΝ ISO/IEC 17021", [("ENVIRONMENTAL ISO 14001", "", "", 11),
                                        ("QUALITY ISO 9001", "396-7", "24.7.2008", 12),
                                        ("ISO 22000 &amp; ISO/TS 22002-1:2009", "396-7", "27.4.2015", 13)]),
        group("ELOT ΕΝ 45011", [("ORGANIC PRODUCTS", "307-7", "6.11.2006", 14)]),
    ]),
    # 17021 after another standard, with a blank English field name.
    "2": org_page("TÜV HELLAS (TÜV NORD) S.A.", CONTACT, [
        group("ELOT ΕΝ ISO/IEC 17020", [("VEHICLES", "33-8", "26.9.2001", 21)]),
        group("ELOT ΕΝ ISO/IEC 17021", [("FACILITY ISO 41001", "185-10", "16.6.2021", 22),
                                        ("", "185-10", "16.1.2026", 23)]),
    ]),
    # Search hit with no 17021 row on the detail page (as seen live for one body).
    "3": org_page("IQC", CONTACT, [group("ELOT ΕΝ 45011", [("", "1006-2", "26.10.2015", 31)])]),
    "4": org_page("PERSONNEL ONLY", CONTACT, [group("ELOT ΕΝ ISO/IEC 17024", [("P", "1", "1.1.2020", 41)])]),
    "5": org_page("PART THREE ONLY", CONTACT, [group("ISO/IEC 17021-3", [("Q", "2", "1.1.2020", 51)])]),
    "6": org_page("EXPLICIT PART ONE", CONTACT, [group("ISO/IEC 17021-1", [("Q", "3", "1.1.2020", 61)])]),
}
GREEK_ORGS = {
    "2": org_page("TÜV", {}, [
        group("ΕΛΟΤ ΕΝ ISO/IEC 17020", [("ΕΛΕΓΧΟΣ", "33-8", "26.9.2001", 21)]),
        group("ΕΛΟΤ EN ISO/IEC 17021", [("ΣΥΣΤΗΜΑΤΑ ISO 41001", "185-10", "16.6.2021", 22),
                                        ("ΣΥΣΤΗΜΑΤΑ ΔΙΑΧΕΙΡΙΣΗΣ ΠΑΓΙΩΝ ΚΑΤΑ ΕΛΟΤ ISO 55001", "185-10", "16.1.2026", 23)]),
    ], GREEK_HEADERS),
}


def listing(ids):
    entries = "".join(f'<img src="/b.gif"> <span class="bold-blue">Body {i}</span><br /> '
                      f'<a href="showOrgInfo.jsp?id={i}">More information...</a><br /><br />' for i in ids)
    return f'<html><body><p>{entries}<DIV align="center">previous | 1 | next</DIV></body></html>'


CATALOGUE = {1: ["1", "2", "3"], 2: ["4", "5", "6"]}
SEARCH = {1: ["1", "2", "3", "6"]}
BROKEN_ORG = "<html><body><table><tr><td>Maintenance</td></tr></table></body></html>"


class Site(BaseHTTPRequestHandler):
    broken = False
    missing_doc = False

    def log_message(self, *args):
        pass

    def _send(self, body, ctype="text/html;charset=UTF-8", status=200):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path.endswith("/en/showCatalogue.jsp"):
            return self._send(listing(CATALOGUE.get(int(query["page"][0]), [])))
        if url.path.endswith("/showOrgInfo.jsp"):
            body_id = query["id"][0]
            if Site.broken and body_id == "4":
                return self._send(BROKEN_ORG)
            source = GREEK_ORGS if "/el/" in url.path else ORGS
            return self._send(source[body_id])
        if url.path.startswith("/eped/"):
            if Site.missing_doc and "12_en" in url.path:
                return self._send("gone", status=404)
            return self._send(b"DOC:" + url.path.encode(), "application/msword")
        return self._send("not found", status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        assert form["protypoDiap"] == ["accStd:17021"]
        return self._send(listing(SEARCH.get(int(form["page"][0]), [])))


@pytest.fixture()
def site():
    Site.broken = Site.missing_doc = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/portal/p/esyd/"
    server.shutdown()


def run(site, tmp_path, *extra):
    return es.main(["--base-url", site, "--delay", "0", "-o", str(tmp_path), *extra])


def rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_only_17021_bodies_are_kept(site, tmp_path):
    assert run(site, tmp_path) == 0
    assert [b["body_id"] for b in rows(tmp_path / "bodies.csv")] == ["1", "2", "6"]


def test_only_17021_rows_are_kept_including_malformed_ones(site, tmp_path):
    run(site, tmp_path)
    acc = rows(tmp_path / "accreditations.csv")
    assert [a["field"] for a in acc if a["body_id"] == "1"] == [
        "ENVIRONMENTAL ISO 14001", "QUALITY ISO 9001", "ISO 22000 & ISO/TS 22002-1:2009"]
    assert all("17021" in a["standard"] for a in acc)
    assert not {"ORGANIC PRODUCTS", "VEHICLES", "P"} & {a["field"] for a in acc}


def test_row_values_and_doc_links(site, tmp_path):
    run(site, tmp_path)
    row = rows(tmp_path / "accreditations.csv")[1]
    assert row["certificate_number"] == "396-7" and row["valid_since"] == "24.7.2008"
    assert row["scope_doc_en"].endswith("/eped/1.12_en.doc")
    assert row["scope_doc_el"].endswith("/eped/1.12_el.doc")


def test_contact_details(site, tmp_path):
    run(site, tmp_path)
    body = rows(tmp_path / "bodies.csv")[0]
    assert body["name"] == "A CERT S.A." and body["email"] == "info@example.gr"
    assert body["fax"] == "2310 210417" and body["region"] == ""
    assert body["certificate_numbers"] == "396-7" and body["scope_count"] == "3"


def test_blank_field_is_filled_from_greek_by_scope_id(site, tmp_path):
    run(site, tmp_path)
    acc = [a for a in rows(tmp_path / "accreditations.csv") if a["body_id"] == "2"]
    assert (acc[0]["field"], acc[0]["field_language"]) == ("FACILITY ISO 41001", "en")
    assert (acc[1]["field"], acc[1]["field_language"]) == (
        "ΣΥΣΤΗΜΑΤΑ ΔΙΑΧΕΙΡΙΣΗΣ ΠΑΓΙΩΝ ΚΑΤΑ ΕΛΟΤ ISO 55001", "el")


def test_search_disagreement_is_reported_and_excluded(site, tmp_path):
    run(site, tmp_path)
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["bodies_17021"] == 3 and report["catalogue_bodies_checked"] == 6
    assert report["search_cross_check"]["in_search_but_no_17021_on_detail_page"] == ["3"]
    assert report["search_cross_check"]["has_17021_but_not_in_search"] == []


def test_layout_change_is_an_error_not_a_silent_exclusion(site, tmp_path):
    Site.broken = True
    assert run(site, tmp_path) == 1
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert [e["body_id"] for e in report["errors"]] == ["4"]


def test_docs_download_and_resume(site, tmp_path):
    assert run(site, tmp_path, "--download-docs", "en") == 0
    files = sorted(p.name for p in (tmp_path / "scope_documents").rglob("*.doc"))
    assert "1.12_en.doc" in files and "1.14_en.doc" not in files
    assert not [f for f in files if f.endswith("_el.doc")]
    Site.missing_doc = True  # an already-downloaded file must not be requested again
    assert run(site, tmp_path, "--download-docs", "en") == 0


def test_failed_download_is_reported(site, tmp_path):
    Site.missing_doc = True
    assert run(site, tmp_path, "--download-docs", "en") == 1
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert len(report["download_failures"]) == 1


@pytest.mark.parametrize("label,expected", [
    ("ELOT ΕΝ ISO/IEC 17021", True), ("ΕΛΟΤ EN ISO/IEC 17021", True), ("ISO/IEC 17021-1", True),
    ("ISO/IEC 17021-1:2015", True), ("ISO/IEC 17021-2", False), ("ISO/IEC 17021 - 3", False),
    ("ELOT ΕΝ ISO/IEC 17020", False), ("ELOT ΕΝ 45011", False), ("170210", False),
])
def test_standard_filter(label, expected):
    assert es.is_target_standard(label) is expected


def test_real_page_markup():
    """Live-site markup for body 17902 (rows shortened, repeated structure kept)."""
    html = (Path(__file__).parent / "fixtures" / "org_17902_en.html").read_text(encoding="utf-8")
    soup = es.soupify(html)
    contact = es.parse_contact(soup)
    assert contact["name"] == "THEODYNAMICS LTD"
    assert contact["email"] == "tdltd@otenet.gr, p631@otenet.gr" and contact["region"] == ""
    all_rows = es.parse_accreditation_rows(soup, "http://www.esydops.gr/")
    assert len(all_rows) == 5
    target = [r for r in all_rows if es.is_target_standard(r["standard"])]
    assert [r["certificate_number"] for r in target] == ["656-8"] * 4
    assert target[-1]["valid_since"] == "16.12.2024"
    assert target[0]["docs"]["en"] == "http://www.esydops.gr/eped/1.21307_en.doc"
    assert all_rows[-1]["standard"] == "ELOT ΕΝ 45011"
