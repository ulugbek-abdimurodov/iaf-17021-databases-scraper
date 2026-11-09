import csv
import re

import armnab_scraper as scraper
import prepare_certifind as prepare
from tests.conftest import FIXTURES

# What the CertiFind importer accepts in ea_codes (DatasetReader.parseEaCodes).
IMPORTER_EA = re.compile(r"ALL|\d{1,2}(-\d{1,2})?(;\d{1,2}(-\d{1,2})?)*")
NAREK = "Narek Scientific Research CJSC («ՆԱՐԵԿ» ԳԻՏԱՀԵՏԱԶՈՏԱԿԱՆ ՓԲԸ)"


def record(name):
    html = (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    return scraper.parse_detail(html, name, f"https://armnab.am/management-systems/{name}")


def dataset(tables, *names, active_only=False, **kwargs):
    """Withdrawn fixtures are included unless asked, so their parsing stays tested."""
    return prepare.convert({"records": [record(name) for name in names]}, tables, "2026-11-03",
                           active_only=active_only, **kwargs)


def scope(scopes, certificate, standard):
    return next(row for row in scopes if row["certificate_number"] == certificate
                and row["certification_standard"] == standard)


def codes_of(row):
    return prepare.expand_ea_spec(row["ea_codes"])


def test_reduction_ranges():
    codes, unread = prepare.expand_reduction("6, 8-ից մինչև 11, 15-17.2, 29/1-30, 34։")
    assert {"6", "8", "9", "10", "11", "15", "16", "17", "17.1", "17.2", "29/1", "29/2", "30", "34", "34/1", "34/2"} <= codes
    assert "7" not in codes and "29" not in codes and unread == []


def test_reduction_range_ending_on_parent_covers_sub_codes():
    codes, _ = prepare.expand_reduction("36-38")
    assert {"36", "37", "38", "38/1", "38/2", "38/3"} <= codes


def test_reduction_reads_section_letters_and_ascii_colon():
    assert prepare.expand_reduction("ԲԱԺԻՆՆԵՐ C, G, T։") == ({"C", "G", "T"}, [])
    assert prepare.expand_reduction("Բաժին T, Բաժին U։") == ({"T", "U"}, [])
    assert prepare.expand_reduction("17, 6, 17,31, 36:") == ({"6", "17", "17.1", "17.2", "31", "31/1", "31/2", "36"}, [])


def test_reduction_ending_with_ascii_colon_does_not_swallow_next_scheme():
    unread = []
    schemes = prepare.parse_scope([
        "6 Էներգետիկայի կառավարման համակարգ (EnMS)՝ ԳՕՍՏ ԻՍՕ 50001",
        "Տրանսպորտ E",
        "Գյուղատնտեսություն G",
        "Համաձայն ... որոշման՝ հավատարմագրման ոլորտը կրճատվել է հետևյալ բաժիններով՝ E, G:",
        "7 Բիզնեսի շարունակականության կառավարման համակարգեր՝ ՀՍՏ ԻՍՕ 22301",
        "Կրթություն - Բաժին P",
    ], unread)
    assert schemes["ISO 50001"]["removed"] == {"E", "G"}
    assert schemes["ISO 22301"]["sections"] == ["P"] and unread == []


def test_inline_reduction_removes_listed_codes(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000016")
    row = scope(scopes, "006/M-012", "ISO 9001")
    assert 14 not in codes_of(row) and 17 not in codes_of(row) and 1 in codes_of(row)
    assert "Scope reduced by ARMNAB: 14, 17, 18 removed" in row["scope_note"]


def test_reduction_block_removes_codes_too(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000016")
    row = scope(scopes, "006/M-012", "ISO 9001")
    assert row["ea_codes"] == "1;34"
    assert "EA 34 (34/2)" in row["scope_note"]


def test_sub_sectors_collapse_to_their_ea_sector():
    kept, dropped = prepare.apply_reduction(["29", "34/1", "34/2", "38/1"], {"29/2", "34/1"})
    assert kept == ["29/1", "34/2", "38/1"] and dropped == ["34/1"]
    codes, partial = prepare.to_ea(kept + ["17", "17.1", "17.2"])
    assert codes == {17, 29, 34, 38}
    assert partial == {29: ["29/1"], 34: ["34/2"], 38: ["38/1"]}


def test_per_scheme_reductions_stay_separate(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000012")
    assert scope(scopes, "002/M-008", "ISO 9001")["ea_codes"] == "1-2;7"
    assert scope(scopes, "002/M-008 (27006)", "ISO/IEC 27001")["ea_codes"] == "13;33"


def test_accreditation_split_by_accreditation_standard(tables):
    _, accreditations, _, _, _ = dataset(tables, "MS00000012")
    assert {(row["certificate_number"], row["accreditation_standard"]) for row in accreditations} == {
        ("002/M-008", "ISO/IEC 17021-1"), ("002/M-008 (27006)", "ISO/IEC 27006"),
        ("002/M-008 (22000)", "ISO 22003-1")}


def test_extension_block_adds_food_scheme(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000012")
    row = scope(scopes, "002/M-008 (22000)", "ISO 22000")
    assert row["ea_codes"] == "1;3"
    assert row["scope_note"] == "ISO 22003-1 categories A, C (classified to EA by sector)"


def test_food_row_reads_category_not_section(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000003")
    row = scope(scopes, "003/F-004", "ISO 22000")
    assert row["ea_codes"] == "12-13;30;35" and "categories E, H, K" in row["scope_note"]


def test_fssc_legacy_letters(tables):
    scheme = prepare.parse_scope(["4 Սննդամթերքի անվտանգության կառավարման համակարգ FSSC՝ ՀՍՏ ԻՍՕ 22000",
                                  "Շուտ փչացող կենդանական արտադրանքի վերամշակում C",
                                  "Քիմիական (Բիո) նյութերի արտադրություն L"])["FSSC 22000"]
    assert scheme["legacy_food"]
    spec, note = prepare.scheme_codes("X", scheme, prepare.Mapper(tables), prepare.Review())
    assert spec == "3;12-13" and "ISO/TS 22003:2007 letters) C, L" in note


def test_subtitle_line_keeps_scheme():
    schemes = prepare.parse_scope([
        "4. Սննդամթերքի անվտանգության կառավարման համակարգ FSSC՝ ՀՍՏ ԻՍՕ 22000",
        "Սննդամթերքի անվտանգության կառավարման համակարգեր. Պահանջներ",
        "Շուտ փչացող կենդանական արտադրանքի վերամշակում C",
    ])
    assert list(schemes) == ["FSSC 22000"] and schemes["FSSC 22000"]["food"] == ["C"]


def test_certificate_named_in_scope_heading(tables):
    _, accreditations, scopes, review, _ = dataset(tables, "MS00000003")
    assert [row["certificate_number"] for row in accreditations] == ["003/Q-004", "003/F-004", "002/L-002"]
    assert scope(scopes, "003/Q-004", "ISO 9001")["ea_codes"] == "1;3;32;35"
    assert any("OHSAS 18001 left out" in item for item in review.sections["Exclusions"])


def test_sector_scheme_without_rows_is_left_out(tables):
    _, _, scopes, review, _ = dataset(tables, "MS00000003")
    assert not any(row["certificate_number"] == "003/E-004" for row in scopes)
    assert any("inferred from its letter" in item for item in review.sections["Fallbacks"])
    assert any("003/E-004 has no scope" in item for item in review.sections["Exclusions"])
    # ISO/IEC 27001 is not a sector scheme: no sector list means ALL.
    assert scope(scopes, "002/L-002", "ISO/IEC 27001")["ea_codes"] == "ALL"


def test_nace_sections_are_mapped_with_tables(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000003")
    row = scope(scopes, "003/Q-004", "ISO 9001")
    assert {32, 35} <= codes_of(row) and "Register lists NACE N" in row["scope_note"]


def test_section_reduction_removes_sections(tables):
    scheme = prepare.parse_scope([
        "5 Տեղեկատվական անվտանգության կառավարման համակարգ՝ ՀՍՏ ԻՍՕ/ԻԷԿ 27001",
        "Շինարարություն - Բաժին F",
        "Կրթություն - Բաժին P",
        "Համաձայն ... որոշման՝ հավատարմագրման ոլորտը կրճատվել է հետևյալ ՏԳՏԴ ծածկագրերի մասերով՝ ԲԱԺԻՆՆԵՐ F։",
    ])["ISO/IEC 27001"]
    assert scheme["removed"] == {"F"}
    spec, note = prepare.scheme_codes("X", scheme, prepare.Mapper(tables), prepare.Review())
    assert spec == "37" and "NACE sections F removed" in note


def test_energy_keeps_technical_areas_only(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000016")
    row = scope(scopes, "006/M-012 (50003)", "ISO 50001")
    assert row["ea_codes"] == "3-9;12-14;18-19;22-24;31"
    assert row["scope_note"] == "ISO 50003 technical areas A, E (classified to EA by sector)"


def test_medical_areas(tables):
    _, _, scopes, _, _ = dataset(tables, "MS00000016")
    row = scope(scopes, "006/M-012", "ISO 13485")
    assert row["ea_codes"] == "13-14;17;19"
    assert "Non-active medical devices; Active implantable medical devices" in row["scope_note"]


def test_ea_codes_use_importer_format(tables):
    _, accreditations, scopes, _, _ = dataset(tables, "MS00000001", "MS00000003", "MS00000012", "MS00000016")
    assert scopes and all(IMPORTER_EA.fullmatch(row["ea_codes"]) for row in scopes)
    assert all(code <= 39 for row in scopes if row["ea_codes"] != "ALL" for code in codes_of(row))
    assert {row["status"] for row in accreditations + scopes} <= {"ACTIVE", "SUSPENDED", "WITHDRAWN"}


def test_additional_documents_are_logged_not_written(tables):
    _, _, scopes, review, _ = dataset(tables, "MS00000016")
    assert not any("31000" in row["certification_standard"] for row in scopes)
    assert any("31000" in item for item in review.sections["Additional documents named in scopes"])


def test_excluded_scheme(tables):
    custom = {**tables, "EXCLUDED_SCHEMES": {"ISO 22000": "test"}}
    _, _, scopes, review, _ = dataset(custom, "MS00000003")
    assert not any(row["certification_standard"] == "ISO 22000" for row in scopes)
    assert any("ISO 22000 is in EXCLUDED_SCHEMES" in item for item in review.sections["Exclusions"])


def test_withdrawn_records_left_out_by_default(tables):
    records = {"records": [record("MS00000003"), record("MS00000016")]}
    bodies, accreditations, _, review, _ = prepare.convert(records, tables, "2026-11-03")
    assert [body["name"] for body in bodies] == [NAREK]
    assert {row["certificate_number"] for row in accreditations} == {
        "006/M-012", "006/M-012 (27006)", "006/M-012 (50003)"}
    assert any("WITHDRAWN record 003/Q-004" in item for item in review.sections["Exclusions"])


def test_one_accreditation_per_body_and_standard(tables):
    """Mirrors the uq_cb_ab_standard constraint the importer enforces."""
    _, accreditations, _, _, _ = prepare.convert(
        {"records": [record(n) for n in ("MS00000001", "MS00000003", "MS00000012", "MS00000016")]},
        tables, "2026-11-03")
    keys = [(row["body_name"], row["accreditation_standard"]) for row in accreditations]
    assert len(keys) == len(set(keys))


def test_body_fields_and_phone_format(tables):
    bodies, accreditations, _, review, _ = dataset(tables, "MS00000001", "MS00000016")
    narek = next(body for body in bodies if body["name"] == NAREK)
    assert narek["phone"] == "+374 91 005757"
    assert narek["country"] == "Armenia"
    assert narek["registration_no"] == "" and narek["verified_at"] == ""
    institute = next(body for body in bodies if "ԻՆՍՏԻՏՈՒՏ" in body["name"])
    assert institute["name"].startswith("National Institute of Standards CJSC (")
    assert institute["phone"] == "+374 10 287020"
    assert any("Yerevan 10" in item for item in review.sections["Fallbacks"])
    assert accreditations[0]["ab_code"] == "ARMNAB"
    assert accreditations[0]["proof_url"].startswith("https://armnab.am/management-systems/")


def test_unknown_body_keeps_armenian_name_and_is_logged():
    review = prepare.Review()
    assert prepare.display_name("«ՆՈՐ» ՍՊԸ", review, "X") == "«ՆՈՐ» ՍՊԸ"
    assert any("ENGLISH_NAMES" in item for item in review.sections["Fallbacks"])


def test_numbered_section_names_without_letters():
    schemes = prepare.parse_scope(["1. Որակի կառավարման համակարգ", "1. Գյուղատնտեսություն, անտառային տնտեսություն և ձկնորսություն", "3. Մշակող արդյունաբերություն"])
    assert schemes["ISO 9001"]["sections"] == ["A", "C"]


def test_scheme_named_on_next_line_has_no_sector_list():
    unread = []
    schemes = prepare.parse_scope(["16 Հակակոռուպցիոն կառավարման համակարգեր", "Խարդախության հսկողության կառավարման համակարգեր - -",
                                   "ԻՍՕ 37001:2025", "ԻՍՕ 37003:2025", "15 Սոցիալական կառավարման համակարգեր - -",
                                   "ԻՍՕ 26000, FSSC 24000, SA8000 SOCIAL ACCOUNTABILITY"], unread)
    assert list(schemes) == ["ISO 37001"]
    assert schemes["ISO 37001"]["extras"] == ["ԻՍՕ 37003:2025"]
    assert any("26000" in line for line in unread) and any("Սոցիալական" in line for line in unread)


def test_unread_lines_reach_review(tables):
    unread = []
    prepare.parse_scope(["1 Որակի կառավարման համակարգ՝ ՀՍՏ ԻՍՕ 9001", "Այլ կատեգորիաներ"], unread)
    assert unread == ["ISO 9001: Այլ կատեգորիաներ"]


def test_wrapped_line_is_joined_not_unread():
    unread = []
    schemes = prepare.parse_scope(["1 Որակի կառավարման համակարգ՝ ՀՍՏ ԻՍՕ 9001", "Ճարտարագիտական ծառայություններ (ճարտարապետություն- և", "ճարտարագիտական գրասենյակներ) 34/2 Բաժին M"], unread)
    assert unread == [] and schemes["ISO 9001"]["codes"] == ["34/2"]


def test_end_to_end_writes_dataset_and_review(site, tmp_path, tables, monkeypatch):
    base, _ = site
    output = tmp_path / "output"
    monkeypatch.setattr("sys.argv", ["x", "--output", str(output), "--base-url", base, "--delay", "0"])
    scraper.main()
    monkeypatch.setattr(prepare, "load_tables", lambda path: tables)
    dataset_dir = tmp_path / "data"
    monkeypatch.setattr("sys.argv", ["x", "--input", str(output), "--dataset", str(dataset_dir)])
    assert prepare.main() == 0
    with (dataset_dir / "scopes.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"]
        assert all(IMPORTER_EA.fullmatch(row["ea_codes"]) for row in reader)
    with (dataset_dir / "bodies.csv").open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 2  # the two withdrawn fixtures are left out
    review = (output / "REVIEW.md").read_text(encoding="utf-8")
    assert "## Missing annexes (2)" in review and "## Mappings" in review


def test_load_tables_reports_missing_names(tmp_path):
    fake = tmp_path / "prepare_certifind.py"
    fake.write_text("NACE_TO_EA = {}\n", encoding="utf-8")
    try:
        prepare.load_tables(fake)
    except SystemExit as exc:
        assert "NACE_SPANS" in str(exc) and "SCHEMES" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
