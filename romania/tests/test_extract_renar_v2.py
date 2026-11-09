"""Acceptance test for extract_renar_v2.py on real RENAR PDFs in tests/samples/:
SM 112 (Certificat + Anexa nr. 1, ISO 9001) and SM 111 (Certificat + Anexa nr. 5, ISO/IEC 27001)."""
import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extract_renar_v2 as ex  # noqa: E402

SAMPLES = ROOT / "tests" / "samples"


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("db")
    assert ex.main([str(SAMPLES), "--out", str(out_dir)]) == 0
    return {name: read(out_dir / f"{name}.csv")
            for name in ("certification_bodies", "accreditations", "accredited_scopes", "review")} | {
        "sql": (out_dir / "seed_romania.sql").read_text(encoding="utf-8")}


def rows(table, **match):
    return [r for r in table if all(r[k] == v for k, v in match.items())]


@pytest.mark.parametrize("raw, expected", [
    ("SR EN ISO/CEI 17021-1:2015", "ISO/IEC 17021-1"),
    ("SR EN ISO 9001:2015", "ISO 9001"),
    ("SR EN ISO/IEC 27001:2023", "ISO/IEC 27001"),
    ("SR EN ISO/IEC 27006-1:2024", "ISO/IEC 27006"),
    ("SR ISO/IEC TS 17021-10:2018", "ISO/IEC 17021-10"),
])
def test_normalize_standard(raw, expected):
    assert ex.normalize_standard(raw) == expected


# --------------------------------------------------------------------------- SM 112
def test_sm112_body(out):
    [body] = rows(out["certification_bodies"], name="TÜV AUSTRIA ROMÂNIA SRL (TAR CERT)")
    assert body["address"] == "București, Calea Plevnei nr. 139 B, corp A, sector 6"
    assert body["country"] == "Romania"
    assert body["phone"] == body["email"] == body["website"] == ""


def test_sm112_accreditation(out):
    accs = rows(out["accreditations"], company_name="TÜV AUSTRIA ROMÂNIA SRL (TAR CERT)")
    assert [(a["accreditation_standard"], a["certificate_number"]) for a in accs] == [("ISO/IEC 17021-1", "SM 112")]
    assert (accs[0]["issue_date"], accs[0]["expiry_date"], accs[0]["status"]) == ("2025-02-06", "2029-01-26", "ACTIVE")


def test_sm112_scope(out):
    [scope] = rows(out["accredited_scopes"], certificate_number="SM 112")
    assert scope["certification_standard"] == "ISO 9001"
    ea = [int(x) for x in scope["ea_codes"].split(",")]
    assert ea == [7, 12, 13, 14, 17, 18, 19, 24, 28, 29, 30, 31, 33, 34, 35, 37, 38, 39]
    assert len(ea) == 18  # CAEN codes (241, 3311, 951, 3821, ...) are not IAF sectors
    assert "('SM 112', 'ISO 9001', ARRAY[7, 12, 13, 14, 17, 18, 19, 24, 28, 29, 30, 31, 33, 34, 35, 37, 38, 39])" \
        in out["sql"]


def test_sm112_missing_annexes_reviewed(out):
    problems = " | ".join(r["problem"] for r in rows(out["review"], certificate_number="SM 112", field="annex"))
    for n in (2, 3, 4):
        assert re.search(rf"annex nr\. {n} \(.*\) is listed on the certificate but was not found", problems)


# --------------------------------------------------------------------------- SM 111
def test_sm111_body(out):
    [body] = rows(out["certification_bodies"], name="PROCERT LABORATORY SRL")
    assert body["address"] == "Bucureşti, Str. Soldat Spiridon Matei nr. 2, bl. 12, sc. B, et. 4, ap. 62, sector 3"


def test_sm111_accreditations(out):
    accs = rows(out["accreditations"], company_name="PROCERT LABORATORY SRL")
    assert [(a["accreditation_standard"], a["certificate_number"]) for a in accs] == [
        ("ISO/IEC 17021-1", "SM 111"), ("ISO/IEC 27006", "SM 111 (27006)")]
    for a in accs:
        assert (a["issue_date"], a["expiry_date"]) == ("2024-02-13", "2028-02-12")


def test_sm111_scope(out):
    [scope] = rows(out["accredited_scopes"], certificate_number="SM 111 (27006)")
    assert scope["certification_standard"] == "ISO/IEC 27001"
    assert scope["ea_codes"] == ",".join(map(str, range(1, 40)))
    assert scope["note"] == "no sector table in annex"
    assert scope["annex_number"] == "5"
    assert "('SM 111 (27006)', 'ISO/IEC 27001', ARRAY(SELECT generate_series(1, 39)))" in out["sql"]


def test_sm111_annex_address_reviewed(out):
    assert rows(out["review"], certificate_number="SM 111", field="address")
    assert any("annex address differs" in r["problem"]
               for r in rows(out["review"], certificate_number="SM 111", field="address"))


def test_sql_shape(out):
    sql = out["sql"]
    assert "-- source: SM 112" in sql and "-- source: SM 111" in sql
    assert "('TÜV AUSTRIA ROMÂNIA SRL (TAR CERT)', 'Romania', NULL, NULL, NULL, " \
           "'București, Calea Plevnei nr. 139 B, corp A, sector 6')" in sql
    assert "('TÜV AUSTRIA ROMÂNIA SRL (TAR CERT)', 'ISO/IEC 17021-1', 'SM 112', '2025-02-06', '2029-01-26')" in sql
    assert "JOIN accreditation_bodies ab ON ab.code = 'RENAR';" in sql
