import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from certifind_common import (resolve_cert_number, compress_ea_codes, write_certifind_csvs,
                              ISO22003_TO_EA, MD8_TO_EA)

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "kab-south-korea"
SRC = "https://eng.kab.or.kr/eng/kcn/kcn/list.do"
VIEW = "https://eng.kab.or.kr/eng/kcn/kcn/view.do?orgIdx={}&menuNo=500044"
STD = {"9001": "ISO 9001", "14001": "ISO 14001", "45001": "ISO 45001", "13485": "ISO 13485",
       "22000": "ISO 22000", "FSSC 22000": "FSSC 22000", "50001": "ISO 50001",
       "27001": "ISO/IEC 27001", "27701": "ISO/IEC 27701", "22301": "ISO 22301"}
MD8_KEYS = list(MD8_TO_EA)  # KAB letters A-G follow IAF MD 8 main technical area order
MD8_LET = dict(zip("ABCDEFG", [MD8_KEYS[0], MD8_KEYS[1], MD8_KEYS[2], MD8_KEYS[3], MD8_KEYS[4], MD8_KEYS[5], MD8_KEYS[6]]))


def ea_from(std, raw):
    if raw.startswith("#"):
        nums = []
        for part in raw[1:].split(";"):
            a, _, b = part.partition("-")
            nums += range(int(a), int(b or a) + 1)
        return compress_ea_codes(nums), "EA codes as listed in the KAB register"
    if not raw:
        return "", "No sector restriction listed in the KAB register"
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted(set(re.findall(r"\(([A-K])", raw)))
        ea = [e for c in cats for e in ISO22003_TO_EA[c]]
        return compress_ea_codes(ea), f"Classified to EA from ISO 22003-1 categories {', '.join(cats)} ({raw})"
    if std == "ISO 13485":
        lets = sorted(set(re.findall(r"(?:^|,)([A-G])\(", raw)))
        ea = [e for l in lets for e in MD8_TO_EA[MD8_LET[l]]]
        return compress_ea_codes(ea), f"Classified to EA from IAF MD 8 main technical areas {', '.join(lets)}"
    if std == "ISO 22301":
        nums = [int(n) for n in re.findall(r"\d+", raw)]
        note = f"KAB ISO 22301 sector groups {raw}"
        return compress_ea_codes(nums), note
    return "", raw


def main():
    bodies, accs, scopes, excl = [], [], [], []
    body = None
    for line in (HERE / "kab_raw.txt").read_text(encoding="utf-8").splitlines():
        f = line.split("|")
        if f[0] == "B":
            _, oid, name, abbr, ph, web, addr = f
            web = web.replace("w:", "https://www.")
            body = dict(name=name, country="South Korea", registration_no="", phone=ph, email="",
                        website=web, address=addr, source_url=VIEW.format(oid), verified_at="", _n=0)
            bodies.append(body)
            continue
        key, accno, date, _, raw = f
        accno = "KAB-" + accno
        if key == "9001":
            body["registration_no"] = accno
        std = STD.get(key)
        if not std:
            excl.append((body["name"], key if not key.isdigit() else "ISO " + key, accno))
            continue
        cert, acc_std = resolve_cert_number(accno, std)
        accs.append(dict(ab_code="KAB", certificate_number=cert, body_name=body["name"],
                         accreditation_standard=acc_std, status="active", issue_date=date,
                         expiry_date="", proof_url=body["source_url"]))
        ea, note = ea_from(std, raw)
        scopes.append(dict(certificate_number=cert, certification_standard=std, ea_codes=ea,
                           status="active", scope_note=note))
        body["_n"] += 1
    kept = [b for b in bodies if b["_n"]]
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        write_certifind_csvs(OUT, kept, accs, scopes)
    rv = ["# KAB review log", "", "Skipped schemes (out of CertiFind scope):", ""]
    rv += [f"- {n}: {s} ({a})" for n, s, a in excl]
    rv += ["", "Bodies excluded (only out-of-scope schemes): " + (", ".join(b["name"] for b in bodies if not b["_n"]) or "none")]
    (HERE / "kab_review.md").write_text("\n".join(rv) + "\n", encoding="utf-8")
    print(f"Bodies: {len(kept)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excl)} schemes, {len(bodies)-len(kept)} bodies")


if __name__ == "__main__":
    main()
