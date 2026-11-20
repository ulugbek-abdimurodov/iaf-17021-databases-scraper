import csv
from pathlib import Path
from typing import Iterable

# Certification standard -> (certificate_number suffix, accreditation_standard)
SCHEME_ACCREDITATION_MAP: dict[str, tuple[str, str]] = {
    "ISO 9001": ("", "ISO/IEC 17021-1"),
    "ISO 14001": ("", "ISO/IEC 17021-1"),
    "ISO 45001": ("", "ISO/IEC 17021-1"),
    "ISO 13485": ("", "ISO/IEC 17021-1"),
    "ISO 3834": ("", "ISO/IEC 17021-1"),
    "EN 15224": ("", "ISO/IEC 17021-1"),
    "ISO 22000": (" (22000)", "ISO 22003-1"),
    "FSSC 22000": (" (22000)", "ISO 22003-1"),
    "ISO 50001": (" (50003)", "ISO 50003"),
    "ISO/IEC 27001": (" (27006)", "ISO/IEC 27006"),
    "ISO/IEC 27701": (" (27006)", "ISO/IEC 27006"),
    "ISO/IEC 20000-1": (" (20000)", "ISO/IEC 20000-6"),
    "ISO 22301": (" (22301)", "ISO/IEC 17021-6"),
}

# ISO 22003-1 Food Chain Categories -> EA codes
ISO22003_TO_EA: dict[str, list[int]] = {
    "A": [1],
    "B": [1],
    "C": [3],
    "D": [3],
    "E": [30],
    "F": [29],
    "G": [31],
    "H": [35],
    "I": [7, 14],
    "J": [18],
    "K": [12],
}

# ISO 50003 Technical Areas -> EA codes
ISO50003_TO_EA: dict[str, list[int]] = {
    "A": [3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
    "B": [28, 32, 34, 36, 37, 38, 39],
    "C": [1],
    "D": [25, 26, 27],
    "E": [31],
    "F": [2],
    "G": [1],
    "H": [10, 30],
}

# IAF MD 8 (ISO 13485) Main Technical Areas -> EA codes
MD8_TO_EA: dict[str, list[int]] = {
    "Non-active medical devices": [14, 17, 19, 34],
    "Active (non-implantable) medical devices": [19, 34],
    "Active implantable medical devices": [19, 34],
    "In vitro diagnostic medical devices": [12, 13, 19],
    "Sterilization methods": [12, 35],
    "Devices incorporating specific substances / technologies": [12, 13, 19],
    "Parts or services": [14, 17, 18, 19, 29, 31, 34, 35],
}

# NACE Rev. 2 Division (2-digit prefix) -> EA code (ESYD mapping)
NACE_DIV_TO_EA: dict[str, list[int]] = {
    "01": [1], "02": [1], "03": [1],
    "05": [2], "06": [2], "07": [2], "08": [2], "09": [2],
    "10": [3], "11": [3], "12": [3],
    "13": [4], "14": [4], "15": [5], "16": [6], "17": [7],
    "18": [8, 9], "19": [10], "20": [12], "21": [13], "22": [14], "23": [15, 16],
    "24": [17], "25": [17], "26": [19], "27": [19], "28": [18],
    "29": [22], "30": [20, 21, 22], "31": [23], "32": [23], "33": [17, 18, 19, 20, 21, 22],
    "35": [25, 26], "36": [27], "37": [39], "38": [24, 39], "39": [39],
    "41": [28], "42": [28], "43": [28],
    "45": [29], "46": [29], "47": [29],
    "49": [31], "50": [31], "51": [31], "52": [31], "53": [31],
    "55": [30], "56": [30],
    "58": [8, 33], "59": [39], "60": [39], "61": [31, 33], "62": [33], "63": [33],
    "64": [32], "65": [32], "66": [32], "68": [32],
    "69": [35], "70": [35], "71": [34], "72": [34], "73": [35], "74": [34, 35], "75": [38],
    "77": [32], "78": [35], "79": [31], "80": [35], "81": [35], "82": [35],
    "84": [36], "85": [37], "86": [38], "87": [38], "88": [38],
    "90": [39], "91": [39], "92": [39], "93": [39], "94": [39], "95": [29], "96": [39],
}


def compress_ea_codes(codes: Iterable[int]) -> str:
    """Format integer EA codes into sorted semicolon ranges: [1,2,3,7] -> '1-3;7'."""
    nums = sorted({int(c) for c in codes if 1 <= int(c) <= 39})
    if not nums:
        return ""
    ranges: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = n
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ";".join(ranges)


def resolve_cert_number(base_id: str, certification_standard: str) -> tuple[str, str]:
    """Return (certificate_number, accreditation_standard) for a certification scheme."""
    suffix, acc_std = SCHEME_ACCREDITATION_MAP[certification_standard]
    return f"{base_id}{suffix}", acc_std


def classify_nace_to_ea(nace_codes: list[str]) -> tuple[str, str]:
    """Convert NACE codes to compressed EA string and standard scope_note."""
    ea_set: set[int] = set()
    for code in nace_codes:
        div = code.strip().split(".")[0].zfill(2)
        ea_set.update(NACE_DIV_TO_EA.get(div, []))
    note = f"Classified to EA from the NACE codes listed (NACE {', '.join(nace_codes)})"
    return compress_ea_codes(ea_set), note


def write_certifind_csvs(
    out_dir: str | Path,
    bodies: list[dict],
    accreditations: list[dict],
    scopes: list[dict],
) -> None:
    """Write bodies.csv, accreditations.csv, and scopes.csv with exact column order."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    specs = [
        ("bodies.csv", ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"], bodies),
        ("accreditations.csv", ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"], accreditations),
        ("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"], scopes),
    ]
    for filename, fieldnames, rows in specs:
        with open(out / filename, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    print(f"Bodies: {len(bodies)} | Accreditations: {len(accreditations)} | Scopes: {len(scopes)}")