"""Build certifind/data/eak-estonia CSVs from eak_data (the EAK scrape).

Usage: python prepare_certifind.py eak_data ../../certifind/data/eak-estonia
"""
import csv, re, sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])

# NACE Rev. 2.1 -> EA (IAF ID 1), after the table in database/greece/prepare_certifind.py.
# Keys are a division ("25") or a group/class ("25.4"); a division key stands for the part of
# the division that no finer key claims. Rev. 2.1 moved materials recovery to 38.2 and motor
# vehicle repair to 95.3; nothing else used here changed.
NACE_TO_EA = {
    **{d: 1 for d in ("01", "02", "03")},
    **{d: 2 for d in ("05", "06", "07", "08", "09")},
    **{d: 3 for d in ("10", "11", "12")},
    "13": 4, "14": 4, "15": 5, "16": 6, "17": 7, "18": 9, "19": 10, "24.46": 11,
    "20": 12, "21": 13, "22": 14, "23": 15, "23.5": 16, "23.6": 16, "24": 17, "25": 17,
    "25.4": 18, "28": 18, "26": 19, "27": 19, "29": 22, "31": 23, "32": 23,
    "30.1": 20, "30.2": 22, "30.3": 21, "30.4": 18, "30.9": 22,
    "33.11": 17, "33.12": 18, "33.13": 19, "33.14": 19, "33.15": 20, "33.16": 21, "33.17": 22,
    "33.19": 23, "33.2": 18, "35.1": 25, "35.2": 26, "35.3": 27, "36": 27,
    "37": 39, "38.1": 39, "38.2": 24, "38.3": 39, "41": 28, "42": 28, "43": 28,
    "45": 29, "46": 29, "47": 29, "55": 30, "56": 30,
    **{d: 31 for d in ("49", "50", "51", "52", "53", "61")},
    **{d: 32 for d in ("64", "65", "66", "68", "77")},
    "62": 33, "63": 33, "71": 34, "72": 34,
    **{d: 35 for d in ("69", "70", "73", "74", "78", "79", "80", "81", "82")},
    "84": 36, "85": 37, "75": 38, "86": 38, "87": 38, "88": 38,
    **{d: 39 for d in ("39", "59", "60", "90", "91", "92", "93", "94", "95.2", "96")},
    "95.1": 19, "95.3": 29,
}
FOOD_CATEGORIES = {"A": "1", "B": "1", "C": "3", "D": "3", "E": "30", "F": "29", "G": "31",
                   "H": "35", "I": "7;14;15;17", "J": "18", "K": "12;13"}

def ea_of(code):
    while code not in NACE_TO_EA:
        code = code[:-1].rstrip(".")
    return NACE_TO_EA[code]

def classify(rows):
    """rows: (division, extent). Returns (EA sectors, those held only in part).

    An EA sector is held in full only when every NACE key IAF ID 1 assigns to it is held."""
    full, excluded, partial = set(), {}, set()
    for div, extent in rows:
        div, codes = div.strip(), re.findall(r"\d{2}\.\d{1,2}", extent)
        if "limited" in extent.lower():
            partial |= set(codes)
        else:
            full.add(div)
            excluded[div] = set(codes) if "except" in extent.lower() else set()

    def covered(key):
        if key in partial:
            return True
        div = key[:2]
        return div in full and not any(
            ea_of(x) == NACE_TO_EA[key] and (x.startswith(key) or key.startswith(x)) for x in excluded[div])

    ea = {ea_of(c) for c in partial}
    ea |= {e for k, e in NACE_TO_EA.items() if k[:2] in full and covered(k)}
    # A division key also stands for the parts of its EA left after an exclusion (25 except 25.3).
    ea |= {NACE_TO_EA[d] for d in full if d in NACE_TO_EA}
    limited = {e for e in ea if not all(covered(k) for k, v in NACE_TO_EA.items() if v == e)}
    return ea, limited

def fmt(nums):
    nums = sorted(nums); out = []; i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}"); i = j + 1
    return ";".join(out)

def note(limited):
    return f"Limited scope (part of the sector) for EA {fmt(limited).replace(';', ', ')}" if limited else ""

tables = list(csv.DictReader(open(SRC / "scope_tables.csv", encoding="utf-8-sig")))
def annex_rows(annex):
    return [(r["col3"], r["col4"]) for r in tables
            if r["annex"] == annex and re.fullmatch(r"\d{2}", r["col3"].strip())]

# KIWA's single annex holds three tables (1.1 ISO 9001, 1.2 ISO 14001, 1.3 ISO 45001), which
# split across pages; their rows are listed here from the annex text.
F, X253, L33 = "Full", "Except 25.3", "Limited to 33.11; 33.12; 33.13; 33.14; 33.17; 33.2"
kiwa_qms = [("16", F), ("20", F), ("22", F), ("25", X253), ("26", F), ("27", F), ("28", F), ("33", L33),
            ("35", F), ("41", F), ("42", F), ("43", F), ("46", F), ("47", F), ("71", F), ("77", F), ("78", F)]
kiwa_ohs = [("22", F), ("25", X253), ("27", F), ("28", F),
            ("33", "Limited to 33.11; 33.12; 33.13; 33.14; 33.2"),
            ("41", F), ("42", F), ("43", F), ("46", F), ("47", F), ("71", F)]

URL = "https://eak.ee/index_eng.php?pageCus=akr&id={}"
bodies = [  # name, registration_no, phone, email, address, register id, cert, issued, expires
    ("Bureau Veritas Eesti Ltd", "10459567", "+372 667 6610", "andres.martma@bureauveritas.com",
     "Liivalaia tn 36, Tallinn, 10132", 415, "MSC004", "2025-12-16", "2030-12-15"),
    ("KIWA Estonia OÜ", "10543517", "+372 6599470", "estonia@kiwa.com",
     "Telliskivi tn 59, Tallinn, 10412", 201, "MSC002", "2022-11-02", "2027-11-01"),
    ("Metrosert Ltd.", "10397748", "+372 5377 4690", "Kristiina.treter@metrosert.ee",
     "Teaduspargi 8, 12618 Tallinn", 469, "MSC001", "2024-02-06", "2029-02-05"),
]
accreditations = [  # cert, body, standard
    ("MSC004", bodies[0], "ISO/IEC 17021-1"), ("MSC004 (22000)", bodies[0], "ISO 22003-1"),
    ("MSC002", bodies[1], "ISO/IEC 17021-1"), ("MSC001", bodies[2], "ISO/IEC 17021-1"),
]
scopes = []
for std, annex in (("ISO 9001", "MSC004_I"), ("ISO 14001", "MSC004_II"), ("ISO 45001", "MSC004_III")):
    scopes.append(("MSC004", std, *classify(annex_rows(annex))))
food = set()
for letter in "CFGIK":
    food |= {int(x) for x in FOOD_CATEGORIES[letter].split(";")}
scopes.append(("MSC004 (22000)", "ISO 22000", food, "ISO 22003-1 categories C, F, G, I, K (classified to EA by sector)"))
scopes.append(("MSC002", "ISO 9001", *classify(kiwa_qms)))
scopes.append(("MSC002", "ISO 14001", *classify(kiwa_qms)))
scopes.append(("MSC002", "ISO 45001", *classify(kiwa_ohs)))

OUT.mkdir(parents=True, exist_ok=True)
def write(name, header, rows):
    with open(OUT / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n"); w.writerow(header); w.writerows(rows)

write("bodies.csv", ["name", "country", "registration_no", "phone", "email", "website", "address",
                     "source_url", "verified_at"],
      [(b[0], "Estonia", b[1], b[2], b[3], "", b[4], URL.format(b[5]), "") for b in bodies])
write("accreditations.csv", ["ab_code", "certificate_number", "body_name", "accreditation_standard",
                             "status", "issue_date", "expiry_date", "proof_url"],
      [("EAK", c, b[0], s, "ACTIVE", b[7], b[8], URL.format(b[5])) for c, b, s in accreditations])
write("scopes.csv", ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"],
      [(c, s, fmt(ea), "ACTIVE", lim if isinstance(lim, str) else note(lim)) for c, s, ea, lim in scopes])

# CertiFind keeps only bodies with a valid accreditation (database/prune_inactive.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from prune_inactive import prune  # noqa: E402
for line in prune(OUT):
    print(f"removed (not valid): {line}")
