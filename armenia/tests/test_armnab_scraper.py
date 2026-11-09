import csv
import json

import armnab_scraper as scraper
from tests.conftest import FIXTURES


def run(base, output, download_docs=False):
    instance = scraper.Scraper(base, output, 0, download_docs)
    return instance, instance.run()


def test_parse_list_reads_total_and_rows():
    total, rows = scraper.parse_list((FIXTURES / "list.html").read_text(encoding="utf-8"))
    assert total == 4
    assert [row["detail_id"] for row in rows] == ["MS00000016", "MS00000012", "MS00000003"]
    assert rows[0]["status"] == "Գործող"


def test_parse_detail_fields():
    html = (FIXTURES / "MS00000016.html").read_text(encoding="utf-8")
    record = scraper.parse_detail(html, "MS00000016", "http://x/MS00000016")
    assert record["certificate_numbers"] == ["006/M-012"]
    assert record["start_date"] == "2025-10-13"
    assert record["end_date"] == "2029-10-13"
    assert record["phone"] == "+37491-00-57-57"
    assert record["fax"] == ""
    assert record["email"] == "info@certification.am"
    assert {block["title"] for block in record["blocks"]} >= {"Հավատարմագրման ոլորտը", "Ոլորտի կրճատում"}


def test_not_found_page_with_http_200_is_none():
    html = (FIXTURES / "not_found.html").read_text(encoding="utf-8")
    assert scraper.parse_detail(html, "MS00000017", "u") is None


def test_multiple_certificate_numbers_are_split():
    html = (FIXTURES / "MS00000003.html").read_text(encoding="utf-8")
    record = scraper.parse_detail(html, "MS00000003", "u")
    assert record["certificate_numbers"] == ["003/Q-004", "003/E-004", "003/F-004", "002/L-002", "002/H-002"]


def test_walk_finds_record_missing_from_first_list_page(site, tmp_path):
    base, _ = site
    instance, records = run(base, tmp_path)
    ids = [record["detail_id"] for record in records]
    assert ids == ["MS00000001", "MS00000003", "MS00000012", "MS00000016"]
    assert instance.errors == []
    assert instance.counts["ids_not_found"] >= scraper.STOP_AFTER_MISSES


def test_user_agent_is_sent(site, tmp_path):
    base, handler = site
    run(base, tmp_path)
    assert set(handler.seen_agents) == {scraper.USER_AGENT}


def test_errors_are_listed_and_run_continues(site, tmp_path):
    base, handler = site
    handler.fail_paths = {"/management-systems/MS00000012"}
    instance, records = run(base, tmp_path)
    assert [record["detail_id"] for record in records] == ["MS00000001", "MS00000003", "MS00000016"]
    assert f"{base}/management-systems/MS00000012" in instance.failed_urls
    assert any("says 4 records" in error["error"] for error in instance.errors)


def test_download_docs_saves_pages_and_resumes(site, tmp_path):
    base, _ = site
    first, _ = run(base, tmp_path, True)
    assert first.counts["pages_saved"] == 4
    assert (tmp_path / "scope_documents" / "MS00000016.html").exists()
    second, _ = run(base, tmp_path, True)
    assert second.counts["pages_saved"] == 0
    assert second.counts["pages_already_saved"] == 4


def test_download_docs_fetches_linked_file(site, tmp_path):
    base, _ = site
    instance = scraper.Scraper(base, tmp_path, 0, True)
    record = {"detail_id": "MS00000016", "documents": [f"{base}/management-systems"]}
    instance.save_documents(record, "<html></html>")
    assert instance.counts["documents_downloaded"] == 1


def test_main_writes_all_outputs(site, tmp_path, monkeypatch):
    base, _ = site
    monkeypatch.setattr("sys.argv", ["x", "--output", str(tmp_path), "--base-url", base, "--delay", "0"])
    assert scraper.main() == 0
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["records"] == 4 and report["error_count"] == 0
    assert report["documents_linked_on_site"] == 0
    with (tmp_path / "accreditations.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert {row["certificate_number"] for row in rows} >= {"006/M-012", "002/H-002"}
    data = json.loads((tmp_path / "bodies.json").read_text(encoding="utf-8"))
    assert len(data["bodies"]) == 4
