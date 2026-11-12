"""Convert KENAS register + schedule PDFs to CertiFind CSVs."""
import json, re, subprocess
from pathlib import Path
from certifind_common import (resolve_cert_number, classify_nace_to_ea, compress_ea_codes,
                              ISO22003_TO_EA, write_certifind_csvs)

HERE = Path(__file__).parent
OUT = HERE.parents[1] / "data" / "kenas-kenya"
SRC = "https://kenas.go.ke/status"
STD_PAT = {"ISO 9001": r"ISO\s*9001", "ISO 14001": r"ISO\s*14001", "ISO 45001": r"ISO\s*45001",
           "ISO 13485": r"ISO\s*13485", "ISO 22000": r"(?<!FSSC )ISO\s*22000", "FSSC 22000": r"FSSC\s*22000",
           "ISO 50001": r"ISO\s*50001", "ISO/IEC 27001": r"27001", "ISO/IEC 27701": r"27701",
           "ISO/IEC 20000-1": r"20000-1", "ISO 22301": r"22301"}

def pdf_text(p):
    try:
        return subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True).stdout
    except Exception:
        return ""

def parse_scopes(text, std):
    m = re.search(STD_PAT[std], text)
    seg = text[m.start(): m.start() + 4000] if m else ""
    nace = re.findall(r"\b\d{2}\.\d{1,2}\b", seg)
    ea = [int(x) for x in re.findall(r"\bIAF\s*(?:code)?\s*:?\s*(\d{1,2})\b", seg)]
    if std in ("ISO 22000", "FSSC 22000"):
        cats = sorted(set(re.findall(r"\bCategory\s+([A-K])\b", seg)))
        codes = [c for k in cats for c in ISO22003_TO_EA[k]]
        return compress_ea_codes(codes), f"Food chain categories {', '.join(cats)}" if cats else ""
    if ea:
        return compress_ea_codes(ea), "IAF/EA codes as listed in the KENAS schedule"
    if nace:
        return classify_nace_to_ea(nace)
    return "", "Scope not parsed from schedule; see proof_url"

def main():
    reg = json.loads((HERE / "register.json").read_text())
    bodies, accs, scopes, excluded = [], [], [], 0
    for r in reg:
        bodies.append({"name": r["name"], "country": "Kenya", "registration_no": r["id"], "phone": r.get("phone", ""),
                       "email": r.get("email", ""), "website": "", "address": r["address"],
                       "source_url": SRC, "verified_at": ""})
        pdf = HERE / "pdfs" / (re.sub(r"\W", "_", r["id"]) + ".pdf")
        text = pdf_text(pdf) if pdf.exists() else ""
        stds = [s for s, p in STD_PAT.items() if re.search(p, text)] or ["ISO 9001"]
        seen = set()
        for s in stds:
            cert, acc = resolve_cert_number(r["id"], s)
            if cert not in seen:
                seen.add(cert)
                accs.append({"ab_code": "KENAS", "certificate_number": cert, "body_name": r["name"],
                             "accreditation_standard": acc, "status": "active", "issue_date": "",
                             "expiry_date": r["expiry"], "proof_url": r["schedule"]})
            ea, note = parse_scopes(text, s) if text else ("", "Schedule PDF not retrievable; scheme assumed from register category, to verify")
            scopes.append({"certificate_number": cert, "certification_standard": s, "ea_codes": ea,
                           "status": "active", "scope_note": note})
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        write_certifind_csvs(OUT, bodies, accs, scopes)
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {excluded}")

if __name__ == "__main__":
    main()
