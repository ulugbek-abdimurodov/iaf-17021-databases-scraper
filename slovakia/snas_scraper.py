#!/usr/bin/env python3
"""
Scraper for the SNAS register of accredited bodies (https://ais.snas.sk/web-report).

By default it downloads every management system certification body:
  * list data and certificate details (SK / EN / RU texts, validity, status, notes)
  * body data (name, address, company ID, website, SNAS member number)
  * conformity assessment body units / branches
  * the published files (scope of accreditation annexes) in every language

Expired certificates appear in the output with list data only, because the site
publishes no detail page or files for them.

Needs Python 3.8+ and nothing else. If openpyxl is installed, it also writes an
Excel workbook. Re-running resumes: finished files are not downloaded again.

Usage:
    python snas_scraper.py                         # all MS bodies, all statuses
    python snas_scraper.py --types valid           # currently valid only
    python snas_scraper.py --no-files              # data only, no PDFs
    python snas_scraper.py --all-fields            # every accreditation field
    python snas_scraper.py --fields 12,16,17       # chosen field IDs
    python snas_scraper.py --list-fields           # show field IDs and exit
    python snas_scraper.py --limit 5               # small trial run
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://ais.snas.sk"
USER_AGENT = "snas-register-scraper/1.0 (python)"
LIST_TYPES = ("valid", "suspended", "expired")
LANGS = ("sk", "en", "ru")

# accreditationFieldId values of the management system fields.
# Run --list-fields to see them all with their names.
MS_FIELD_IDS = {7, 12, 13, 14, 15, 16, 17, 18, 19, 20, 32, 33, 34, 35, 36, 37, 53, 54}


class Client:
    def __init__(self, base_url, delay, retries=4, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0

    def _get(self, path, params=None):
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"}
        )
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read()
                self._last = time.monotonic()
                return data
            except urllib.error.HTTPError as exc:
                self._last = time.monotonic()
                if exc.code < 500 and exc.code != 429:
                    raise
                error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                self._last = time.monotonic()
                error = exc
            if attempt < self.retries:
                pause = 2 ** (attempt + 1)
                print(f"  retry in {pause}s ({error}): {url}", file=sys.stderr)
                time.sleep(pause)
        raise error

    def api(self, path, params=None):
        payload = json.loads(self._get(path, params).decode("utf-8"))
        if not payload.get("success"):
            raise RuntimeError(f"API error for {path}: {payload.get('responseMessage')}")
        return payload["responseData"]

    def download(self, file_id):
        return self._get(f"/api/web/download/{file_id}")


def safe_name(value, max_len=70):
    """Make a server-supplied string safe to use as one path component."""
    value = str(value or "").replace("\\", "/").split("/")[-1]
    value = re.sub(r'[<>:"|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if len(value) > max_len:
        stem, dot, ext = value.rpartition(".")
        if dot and len(ext) <= 5:
            value = stem[: max_len - len(ext) - 1].rstrip(" .") + "." + ext
        else:
            value = value[:max_len].rstrip(" .")
    return value or "unnamed"


def day(value):
    return (value or "")[:10]


def text(value):
    """Convert a value for a CSV/Excel cell; lists become '; '-joined text."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(v) for v in value)
    return value


def write_csv(path, rows, columns):
    # utf-8-sig so that Excel shows Slovak and Cyrillic characters correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: text(row.get(c)) for c in columns})


def write_xlsx(path, sheets):
    try:
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl not installed: skipping Excel file (CSV files were written).")
        return False
    illegal = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    book = Workbook()
    book.remove(book.active)
    for name, rows, columns in sheets:
        sheet = book.create_sheet(name)
        sheet.append(columns)
        for row in rows:
            cells = [text(row.get(c)) for c in columns]
            sheet.append([illegal.sub("", c) if isinstance(c, str) else c for c in cells])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    book.save(path)
    return True


def load_fields(client):
    rows = client.api("/api/web/accreditation-field", {"forEnum": "true"})
    names = {}
    for row in rows:
        entry = names.setdefault(row["accreditationFieldId"], {})
        entry[row["languageId"]] = (row.get("accreditationFieldName") or "").strip()
    return names


def number_prefix(certificate_no):
    """Letter prefix of a certificate number: 'Q-003' gives Q, 'R105' gives R."""
    match = re.match(r"[A-Za-z]+", certificate_no or "")
    return match.group(0).upper() if match else ""


def merge_row(existing, row, list_type):
    """Combine rows describing the same certificate, keeping any data either one has."""
    if list_type not in existing["list_types"]:
        existing["list_types"].append(list_type)
    for key, value in row.items():
        if value in (None, ""):
            continue
        if existing.get(key) in (None, ""):
            existing[key] = value
    if row.get("certificateStatus"):
        existing["certificateStatus"] = row["certificateStatus"]


def fetch_rows(client, types, wanted):
    """Return list rows for the wanted fields, one per certificate.

    The valid list carries accreditationFieldId; the suspended and expired lists do not.
    Those rows are matched through the certificate number prefix, which the valid list
    ties to the fields (Q and R are the management system fields). Expired rows also
    have no certificateId, so the site offers no detail page or files for them.
    """
    listed = {t: client.api("/api/web/list", {"type": t}) or [] for t in dict.fromkeys(["valid", *types])}
    prefix_fields = {}
    for row in listed["valid"]:
        prefix_fields.setdefault(number_prefix(row.get("certificateNumber")), set()).add(
            row.get("accreditationFieldId"))

    def selected(row):
        if wanted is None:
            return True
        if row.get("accreditationFieldId") is not None:
            return row["accreditationFieldId"] in wanted
        return bool(prefix_fields.get(number_prefix(row.get("certificateNumber")), set()) & wanted)

    rows = {}
    for list_type in types:
        kept = [r for r in listed[list_type] if selected(r)]
        print(f"List '{list_type}': {len(listed[list_type])} rows, {len(kept)} selected")
        for row in kept:
            if row.get("certificateId") is not None:
                key = ("certificate", row["certificateId"])
            else:
                key = ("row", list_type, row.get("id"))
            if key in rows:
                merge_row(rows[key], row, list_type)
            else:
                rows[key] = {**row, "list_types": [list_type]}
                if list_type == "expired" and not row.get("certificateStatus"):
                    rows[key]["certificateStatus"] = "expired"
    return list(rows.values())


def fetch_detail(client, certificate_id, raw_dir, refresh):
    cache = raw_dir / f"detail_{certificate_id}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    detail = client.api("/api/web/detail", {"certificateId": certificate_id, "lang": "en"})
    cache.write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    return detail


def fetch_file(client, file_id, target, refresh):
    """Download one file. Returns (status, size, sha256). Finished files are kept."""
    if target.exists() and target.stat().st_size > 0 and not refresh:
        data = target.read_bytes()
        return "already_present", len(data), hashlib.sha256(data).hexdigest()
    data = client.download(file_id)
    # The server labels PDFs as application/json, so check the bytes themselves.
    if not data or data.lstrip()[:1] in (b"{", b"<"):
        raise ValueError(f"not a document: {data[:120]!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(data)
    partial.replace(target)
    return "downloaded", len(data), hashlib.sha256(data).hexdigest()


def flatten(row, detail, fields):
    """Build one certificate record from a list row and its detail response."""
    # A certificate can have several entries per language (e.g. two annexes).
    headers = {}
    for header in detail.get("header") or []:
        headers.setdefault(header.get("langSpec"), []).append(header)
    first = next(iter(detail.get("header") or []), {})
    field = fields.get(row.get("accreditationFieldId"), {})
    record = {
        "certificate_id": row.get("certificateId"),
        "certificate_no": row.get("certificateNumber"),
        "status": row.get("certificateStatus"),
        "list_types": row["list_types"],
        "field_id": row.get("accreditationFieldId"),
        "field_en": field.get("en") or first.get("accreditationField"),
        "field_sk": field.get("sk"),
        "member_no": row.get("registeredMemberNumber"),
        "body": row.get("subjectTitle") or first.get("subjectTitle"),
        "company_id": first.get("subjectNumber"),
        "address": first.get("subjectAddress"),
        "web": first.get("subjectWeb"),
        "conformity_assessment_body": (row.get("subjectBranchList") or "").strip(),
        "valid_from": day(row.get("validFrom") or first.get("validFrom")),
        "valid_to": day(row.get("validTo") or first.get("validTo")),
        "effective_date": day(row.get("effectiveDate")),
        "suspension_decision_no": row.get("suspensionDecisionNumber"),
        "suspension_effective": day(row.get("suspensionEffectiveDate")),
        "withdrawal_decision_no": row.get("withdrawalDecisionNumber"),
        "withdrawal_effective": day(row.get("withdrawalEffectiveDate")),
        "list_comment": row.get("comment"),
    }
    for lang in LANGS:
        entries = headers.get(lang, [])
        for column, key in (("accredited_for", "accreditedFor"), ("notes", "comment"),
                            ("annex_file", "relatedFileName")):
            values = list(dict.fromkeys(e.get(key) for e in entries if e.get(key)))
            record[f"{column}_{lang}"] = "\n".join(values)
    return record


def build_bodies(certificates, branches):
    bodies = {}
    for cert in certificates:
        body = bodies.setdefault(cert["member_no"], {
            "company_id": cert["company_id"],
            "member_no": cert["member_no"],
            "body": cert["body"],
            "address": cert["address"],
            "web": cert["web"],
            "certificates": [],
            "valid_certificates": [],
            "fields": [],
            "units": [],
        })
        # expired rows have no contact data, so fill it from whichever row has it
        for key in ("company_id", "address", "web"):
            body[key] = body[key] or cert[key]
        if cert["certificate_no"] not in body["certificates"]:
            body["certificates"].append(cert["certificate_no"])
        if cert["status"] != "expired" and "expired" not in cert["list_types"]:
            body["valid_certificates"].append(cert["certificate_no"])
        if cert["field_en"] and cert["field_en"] not in body["fields"]:
            body["fields"].append(cert["field_en"])
    members = {c["certificate_id"]: c["member_no"] for c in certificates}
    for branch in branches:
        body = bodies.get(members.get(branch["certificate_id"]))
        title = branch.get("unit")
        if body and title and title not in body["units"]:
            body["units"].append(title)
    return sorted(bodies.values(), key=lambda b: str(b["member_no"]))


CERT_COLUMNS = [
    "certificate_id", "certificate_no", "status", "list_types", "field_id", "field_en", "field_sk",
    "member_no", "body", "company_id", "address", "web", "conformity_assessment_body",
    "valid_from", "valid_to", "effective_date", "suspension_decision_no", "suspension_effective",
    "withdrawal_decision_no", "withdrawal_effective", "list_comment",
    "accredited_for_sk", "accredited_for_en", "accredited_for_ru",
    "notes_sk", "notes_en", "notes_ru",
    "annex_file_sk", "annex_file_en", "annex_file_ru",
]
BODY_COLUMNS = ["member_no", "body", "company_id", "address", "web", "fields",
                "valid_certificates", "certificates", "units"]
BRANCH_COLUMNS = ["certificate_no", "certificate_id", "body", "unit", "unit_address",
                  "branch_id", "parent_branch_id", "is_parent_branch"]
FILE_COLUMNS = ["certificate_no", "certificate_id", "body", "language", "file_id", "file_name",
                "path", "status", "size_bytes", "sha256", "error"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Download management system certification bodies from the SNAS register."
    )
    parser.add_argument("--out", default="snas_output", help="output folder (default: snas_output)")
    parser.add_argument("--types", default=",".join(LIST_TYPES),
                        help="lists to read, comma separated (default: valid,suspended,expired)")
    parser.add_argument("--fields", help="accreditation field IDs, comma separated")
    parser.add_argument("--all-fields", action="store_true", help="scrape every accreditation field")
    parser.add_argument("--list-fields", action="store_true", help="print field IDs and exit")
    parser.add_argument("--no-files", action="store_true", help="skip the PDF downloads")
    parser.add_argument("--refresh", action="store_true", help="fetch everything again")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="seconds between requests (default: 0.3)")
    parser.add_argument("--limit", type=int, help="process only the first N certificates")
    parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = Client(args.base_url, args.delay)
    fields = load_fields(client)

    if args.list_fields:
        for field_id in sorted(fields):
            mark = "MS" if field_id in MS_FIELD_IDS else "  "
            print(f"{field_id:>4} {mark} {fields[field_id].get('en', '')}")
        return 0

    # Flag new fields the site may add, so they are not silently left out.
    for field_id, names in sorted(fields.items()):
        name = names.get("en", "").lower()
        if field_id not in MS_FIELD_IDS and "management" in name:
            print(f"Note: field {field_id} '{names.get('en')}' looks like a management "
                  f"system field but is not selected. Add it with --fields if needed.")

    if args.all_fields:
        wanted = None
    elif args.fields:
        wanted = {int(v) for v in args.fields.split(",") if v.strip()}
    else:
        wanted = MS_FIELD_IDS

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "accreditation_fields.json").write_text(
        json.dumps(fields, ensure_ascii=False, indent=1), encoding="utf-8")

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    rows = fetch_rows(client, types, wanted)
    rows.sort(key=lambda r: (str(r.get("registeredMemberNumber")), str(r.get("certificateNumber"))))
    if args.limit:
        rows = rows[: args.limit]
    print(f"Processing {len(rows)} certificates")

    certificates, branches, files, full, failures = [], [], [], [], 0
    used_paths = set()
    for index, row in enumerate(rows, 1):
        certificate_no = row.get("certificateNumber")
        body = row.get("subjectTitle")
        print(f"[{index}/{len(rows)}] {certificate_no}  {body}")
        try:
            detail = {}
            if row.get("certificateId") is not None:
                detail = fetch_detail(client, row["certificateId"], raw_dir, args.refresh)
        except Exception as exc:  # keep going: one bad record must not end a long run
            print(f"  FAILED detail: {exc}", file=sys.stderr)
            failures += 1
            files.append({"certificate_no": certificate_no, "certificate_id": row["certificateId"],
                          "body": body, "status": "detail_failed", "error": str(exc)})
            continue

        certificates.append(flatten(row, detail, fields))
        full.append({"list": row, "detail": detail})
        for branch in detail.get("data") or []:
            branches.append({
                "certificate_no": certificate_no,
                "certificate_id": row["certificateId"],
                "body": body,
                "unit": branch.get("subjectBranchTitle"),
                "unit_address": branch.get("subjectBranchAddress"),
                "branch_id": branch.get("subjectBranchId"),
                "parent_branch_id": branch.get("parentBranchId"),
                "is_parent_branch": branch.get("isParentBranch"),
            })

        folder = (out / "files" / safe_name(row["list_types"][0])
                  / safe_name(f"{row.get('registeredMemberNumber')}_{body}")
                  / safe_name(certificate_no))
        for header in detail.get("header") or []:
            file_id = header.get("relatedFileId")
            if not file_id:
                continue
            language = header.get("langSpec") or "xx"
            name = safe_name(f"{language}_{header.get('relatedFileName') or file_id}")
            target = folder / name
            if target in used_paths:
                target = folder / safe_name(f"{file_id}_{name}")
            used_paths.add(target)
            entry = {"certificate_no": certificate_no, "certificate_id": row["certificateId"],
                     "body": body, "language": language, "file_id": file_id,
                     "file_name": header.get("relatedFileName"),
                     "path": target.relative_to(out).as_posix(), "status": "skipped"}
            if not args.no_files:
                try:
                    entry["status"], entry["size_bytes"], entry["sha256"] = fetch_file(
                        client, file_id, target, args.refresh)
                except Exception as exc:
                    print(f"  FAILED file {file_id}: {exc}", file=sys.stderr)
                    entry["status"], entry["error"] = "failed", str(exc)
                    failures += 1
            files.append(entry)

    bodies = build_bodies(certificates, branches)
    write_csv(out / "bodies.csv", bodies, BODY_COLUMNS)
    write_csv(out / "certificates.csv", certificates, CERT_COLUMNS)
    write_csv(out / "units.csv", branches, BRANCH_COLUMNS)
    write_csv(out / "files.csv", files, FILE_COLUMNS)
    (out / "data.json").write_text(json.dumps(
        {"source": args.base_url + "/web-report", "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
         "lists": types, "certificates": full}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_xlsx(out / "snas_bodies.xlsx", [
        ("Bodies", bodies, BODY_COLUMNS),
        ("Certificates", certificates, CERT_COLUMNS),
        ("Units", branches, BRANCH_COLUMNS),
        ("Files", files, FILE_COLUMNS),
    ])

    saved = sum(1 for f in files if f["status"] in ("downloaded", "already_present"))
    print(f"\nDone: {len(bodies)} bodies, {len(certificates)} certificates, "
          f"{len(branches)} units, {saved} files in {out.resolve()}")
    if failures:
        print(f"{failures} items failed. Run the same command again to retry them "
              f"(see files.csv).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
