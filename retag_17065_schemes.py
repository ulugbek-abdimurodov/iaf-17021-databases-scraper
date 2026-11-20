"""Tag existing 17065 product lines with schemes added to the catalogue after their dataset was converted.

Usage: python retag_17065_schemes.py <certifind/data> [--write]
For every data/*-17065/product_scopes.csv row WITHOUT a scheme, run the common scheme patterns on
product_text + scheme_text + normative_docs; when the match is one of NEW_SCHEMES, set `scheme` and clear `industry`
(a scheme carries its industries through scheme_industries). Rows that already have a scheme are never changed.
The converters use the same patterns (certifind_17065_common.PRIVATE_SCHEMES), so re-running a converter later gives
the same tags. Without --write it only reports what would change.
"""
import csv
import io
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import certifind_17065_common as cf  # noqa: E402

NEW_SCHEMES = {"Global Recycled Standard", "Recycled Claim Standard", "Content Claim Standard",
               "Organic Content Standard", "IECEx Certified Equipment Scheme", "OIML-CS", "GOTS", "Halal"}


def main():
    data, write = Path(sys.argv[1]), "--write" in sys.argv
    missing = NEW_SCHEMES - cf.CATALOGUE
    if missing:
        sys.exit(f"not in the schemes table yet (run the migrations first): {sorted(missing)}")
    total = Counter()
    for f in sorted(data.glob("*-17065/product_scopes.csv")):
        raw = f.read_bytes().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(raw)))
        fields = list(rows[0].keys()) if rows else []
        changed = Counter()
        for r in rows:
            if r["scheme"]:
                continue
            sch = cf.scheme_of(" ".join((r["product_text"], r["scheme_text"], r["normative_docs"])))
            if sch in NEW_SCHEMES:
                r["scheme"], r["industry"] = sch, ""
                changed[sch] += 1
        if changed:
            print(f"{f.parent.name}: {dict(changed)}")
            total.update(changed)
            if write:
                out = io.StringIO()
                w = csv.DictWriter(out, fieldnames=fields, lineterminator="\r\n" if "\r\n" in raw else "\n")
                w.writeheader()
                w.writerows(rows)
                f.write_bytes(out.getvalue().encode("utf-8"))
    print(f"total: {dict(total)}{'' if write else '  (dry run, nothing written)'}")


if __name__ == "__main__":
    main()
