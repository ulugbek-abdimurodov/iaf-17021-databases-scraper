"""Convert the TISI (Thailand) scrape (v3/tisi_raw.json) into a CertiFind dataset.

usage: python prepare_certifind.py <scrape-dir> <dataset-dir> [--today YYYY-MM-DD]
"""
import csv, json, re, sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prune_inactive  # noqa: E402

SRC = "https://center.tisi.go.th/report/certificate?sort=CB"
SCHEME = {"QMS": "ISO 9001", "EMS": "ISO 14001", "OHS": "ISO 45001", "OHSMS": "ISO 45001", "EnMS": "ISO 50001"}
SCHEME_ROWS = {"ISO 50001": ("ISO 50003", "50003")}
ALL_EA = "1-39"
BODY = {  # name: (phone as in register, email, address) - from the English detail pages
    "TUV NORD (Thailand) Ltd.": ("0867129350", "Thitiporn@tuv-nord.com", "1858/103-104, 23rd Floor Interlink Tower, Debaratna Road, Bangna Tai, Bangna, Bangkok 10260"),
    "Global Certification Service Co., Ltd.": ("089-501-6468", "info@thaigcs.com", "3 Soi Rattanathibet 30, Bang Krasor, Mueang Nonthaburi, Nonthaburi 11000"),
    "Management System Certification Institute (Thailand)": ("085-1166571", "cb&IB@masci.or.th", "1025 Yakult Building, Phaholyothin Road, Phayathai, Bangkok 10400"),
    "Bureau Veritas Certification (Thailand) Ltd.": ("026704800", "thanakorn.wainiyom@bureauveritas.com", "2170 Bangkok Tower, 16th Floor, New Petchburi Road, Bangkapi, Huaykwang, Bangkok 10310"),
    "Thai International Certification Co., Ltd.": ("02-678-5154", "ticacert@gmail.com", "2/10 Soi 28/1 Rama 3 Road, Bang Phong Phang, Yan Nawa, Bangkok 10120"),
    "Thailand Institute of Scientific and Technological Research (TISTR)": ("025779374", "kanrawee_t@tistr.or.th", "35 Moo 3 Technopolis, Khlong 5, Khlong Luang, Pathum Thani 12120"),
    "International Certification & Compliance Co., Ltd.": ("", "office@intcertthai.com", "8/11 Soi Ramintra 4/2A, Anusawari, Bang Khen, Bangkok 10220"),
    "SGS (Thailand) Limited": ("0881515514", "SGSTHTISI@sgs.com", "238 TRR Tower, 19th-21st Floor, Naradhiwas Rajanagarindra Road, Chong Nonsi, Yannawa, Bangkok 10120"),
}
FIELDS = {
    "bodies": ["name", "country", "registration_no", "phone", "email", "website", "address", "source_url", "verified_at"],
    "accreditations": ["ab_code", "certificate_number", "body_name", "accreditation_standard", "status", "issue_date", "expiry_date", "proof_url"],
    "scopes": ["certificate_number", "certification_standard", "ea_codes", "status", "scope_note"],
}


def phone(raw, review, name):
    d = re.sub(r"\D", "", raw)
    if not d:
        return ""
    if not (d.startswith("0") and len(d) in (9, 10)):
        review.append(f"- {name}: phone '{raw}' not a Thai number; left empty")
        return ""
    d = d[1:]
    if d.startswith("2"):  # Bangkok landline: 2 xxx xxxx
        return f"+66 2 {d[1:4]} {d[4:]}"
    return f"+66 {d[:2]} {d[2:5]} {d[5:]}"


def iso(s):
    return datetime.strptime(s, "%d %B %Y").date().isoformat() if s else ""


def main():
    args = sys.argv[1:]
    today = date.today()
    if "--today" in args:
        i = args.index("--today")
        today = date.fromisoformat(args[i + 1])
        del args[i:i + 2]
    scrape, out = Path(args[0]), Path(args[1])
    raw = json.load(open(scrape / "tisi_raw.json", encoding="utf-8"))
    review = [f"# TISI review ({today})", f"Register: {SRC}", "", "## Skipped"]
    accs, scopes = {}, {}  # (body, acc std) -> acc row ; (cert no, cert std) -> scope row
    order, first_cert = [], {}
    for cert, acc, body, f, t, note in raw:
        pref = acc.split()[0]
        if pref not in SCHEME:
            review.append(f"- {cert} {acc} ({body}): scheme not in standards table / national scheme")
            continue
        if note:
            review.append(f"- {cert} {acc} ({body}): {note}")
            continue
        exp = iso(t)
        if exp and exp < today.isoformat():
            review.append(f"- {cert} {acc} ({body}): scope expired {exp}")
            continue
        std = SCHEME[pref]
        acc_std, suffix = SCHEME_ROWS.get(std, ("ISO/IEC 17021-1", None))
        key = (body, acc_std)
        if key not in accs:
            num = f"{acc} ({suffix})" if suffix else acc
            accs[key] = {"ab_code": "TISI", "certificate_number": num, "body_name": body, "accreditation_standard": acc_std,
                         "status": "ACTIVE", "issue_date": iso(f), "expiry_date": exp, "proof_url": SRC}
            order.append(key)
        else:
            a = accs[key]
            review.append(f"- {acc} ({body}) merged into {a['certificate_number']} (uq_cb_ab_standard)")
            if iso(f) and (not a["issue_date"] or iso(f) < a["issue_date"]):
                a["issue_date"] = iso(f)
            if exp and (not a["expiry_date"] or exp > a["expiry_date"]):
                a["expiry_date"] = exp
        first_cert.setdefault(key, cert)
        num = accs[key]["certificate_number"]
        sk = (num, std)
        if sk in scopes:
            scopes[sk]["scope_note"] += f"; also {cert} ({acc})"
            continue
        scopes[sk] = {"certificate_number": num, "certification_standard": std, "ea_codes": ALL_EA, "status": "ACTIVE",
                      "scope_note": f"TISI {acc}, certificate {cert}. No sector list in the TISI register (scope annex is a scanned PDF); recorded for all EA sectors"}

    review += ["", "## Notes"]
    for k in order:
        if not accs[k]["issue_date"]:
            accs[k]["issue_date"] = f"20{first_cert[k][:2]}-01-01"
            review.append(f"- {accs[k]['certificate_number']} ({k[0]}): no dates in register; issue_date set to "
                          f"{accs[k]['issue_date']} from certificate {first_cert[k]} year")
    bodies = []
    for name in dict.fromkeys(b for b, _ in order):
        ph, em, ad = BODY[name]
        reg = next(accs[k]["certificate_number"] for k in order if k[0] == name)
        bodies.append({"name": name, "country": "Thailand", "registration_no": reg, "phone": phone(ph, review, name),
                       "email": em, "website": "", "address": ad, "source_url": SRC, "verified_at": ""})
        if not ph:
            review.append(f"- {name}: no phone in register")

    out.mkdir(parents=True, exist_ok=True)
    rows = {"bodies": bodies, "accreditations": [accs[k] for k in order], "scopes": list(scopes.values())}
    for n, data in rows.items():
        with open(out / f"{n}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, FIELDS[n])
            w.writeheader()
            w.writerows(data)
    removed = prune_inactive.prune(out, today)
    review += [f"- pruned: {r}" for r in removed]
    review.append(f"\n{len(bodies)} bodies, {len(rows['accreditations'])} accreditations, {len(rows['scopes'])} scopes")
    (Path(__file__).parent / "tisi_review.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    print(review[-1])


if __name__ == "__main__":
    main()
