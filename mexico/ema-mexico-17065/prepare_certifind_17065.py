"""Convert the EMA (Mexico) ISO/IEC 17065 scrape into the CertiFind dataset certifind/data/ema-mexico-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_mx_ema_17065.py): ema_17065_raw.json + scope_lines.csv. EMA publishes no annex PDFs: each register row
is one accreditation x scope code (e.g. "PROD - PRODUCTO"), so lines are the scope codes with the applicable norm.
Body rows are reused from ema-mexico (MS) or any other dataset when the name matches (handled by the common module).
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "EMA", "ema-mexico-17065", "ema-mexico"
URL = "https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion"


# EMA programme by certificate-number prefix: (label for scheme_text, catalogue scheme or "", industry).
# The register gives no product list, so the programme is the only sector information for these lines.
PROGRAMMES = {
    "PRIMUS": ("PrimusGFS", "PrimusGFS", "food"),
    "GAP": ("Buenas Prácticas Agrícolas", "", "agriculture"),
    "LPO": ("Ley de Productos Orgánicos", "", "agriculture"),
    "PLAG": ("Plaguicidas", "", "agriculture"),
    "SSP": ("Símbolo de Pequeños Productores", "", "agriculture"),
    "IFT": ("Instituto Federal de Telecomunicaciones", "", "ict"),
}


def clean_reg(s: str) -> str:
    return re.sub(r"[\s.]+$", "", s.strip())


# Spanish country names in EMA's foreign addresses -> the English names used in data/*/bodies.csv.
SPANISH = {"estados unidos": "United States", "usa": "United States", "el salvador": "El Salvador",
           "república dominicana": "Dominican Republic", "republica dominicana": "Dominican Republic",
           "colombia": "Colombia", "canada": "Canada", "canadá": "Canada", "guatemala": "Guatemala",
           "honduras": "Honduras", "costa rica": "Costa Rica", "panamá": "Panama", "perú": "Peru"}


def address(a: str) -> str:
    """EMA pads foreign addresses with ', Extranjero, CP. 99999, Extranjero' and marks countries with '#'."""
    if "Extranjero" not in (a or ""):
        return (a or "").strip(" ,")
    a = re.sub(r"(,\s*)*(Extranjero\s*,?\s*)+(CP\. 99999,\s*Extranjero)?\s*$", "", a)
    a = re.sub(r"\.?\s*#\s*(?=,|$)", "", a)  # "EL SALVADOR. #" -> "EL SALVADOR" (house numbers keep their #)
    return re.sub(r"(,\s*)+$", "", a).strip(" ,")


def country(a: str) -> str:
    if "Extranjero" not in (a or ""):
        return "Mexico"
    parts = [p.strip(" .").casefold() for p in address(a).split(",") if p.strip(" .")]
    for p in reversed(parts):  # the country is the last part that names one ("... TORONTO CANADA")
        hit = SPANISH.get(p) or next((v for k, v in SPANISH.items() if re.search(rf"\b{re.escape(k)}$", p)), "")
        if hit:
            return hit
        named = cf.country_name(p, "")
        if named in cf.DIAL:  # country_name returns unknown text unchanged; accept known countries only
            return named
    return ""


def main():
    scrape, today = cf.cli(HERE / "ema_17065")
    raw = json.load(open(scrape / "ema_17065_raw.json", encoding="utf-8"))
    lines = defaultdict(list)
    for r in cf.rd(scrape / "scope_lines.csv"):
        lines[r["registration_no"]].append(r)
    notes, bodies = [], []
    for r in raw:
        reg = clean_reg(r["registration_no"])
        ctry = country(r["address"])
        if not ctry:
            notes.append(f"{reg} {r['name']}: foreign address without a readable country: {r['address']!r}")
            ctry = "Mexico"
        issued, expiry = cf.iso_date(r["issued"]), cf.iso_date(r["expiry"] or "")
        # EMA's fechaFinal is stale for some bodies still listed "Acreditado" (old cycle end, placeholder
        # 0001-01-01, or a date before the start): the register status wins and the expiry is left empty.
        if expiry and (expiry < today or expiry < issued):
            notes.append(f"{reg} {r['name']}: register expiry {r['expiry']} is past or before issue {issued} "
                         f"but status is {r.get('status')}; expiry left empty")
            expiry = ""
        b = cf.Body(reg=reg, name=r["name"], country=ctry, phone=r.get("phone", ""), email=r["email"],
                    website=r["website"], address=address(r["address"]), issued=issued,
                    expiry=expiry, proof_url=URL, source_url=URL,
                    active=(r.get("status") or "Acreditado") == "Acreditado", status_note=r.get("status", ""))
        for ln in sorted(lines[r["registration_no"]], key=lambda x: int(x["row_index"])):
            code, _, rest = ln["product_text_raw"].partition(" - ")
            name, _, norm = rest.partition(" - ")
            if "17065" in norm:  # the accreditation norm itself, not a product norm
                norm = ""
            prog = PROGRAMMES.get(re.match(r"[A-Z]*", reg).group(0))
            scheme_text = f"EMA scope {code}" + (f" ({prog[0]})" if prog else "")
            line = cf.Line(product_text=cf.clean(name or code), scheme_text=scheme_text,
                           normative_docs=cf.clean(norm))
            if code == "PDPPP":  # personal data protection
                line.scheme, line.industry = "", "ict"
            elif prog:
                sch = prog[1] if prog[1] in cf.CATALOGUE else ""
                line.scheme, line.industry = sch, (None if sch else prog[2])
            b.lines.append(line)
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "ema_17065_review.md", today,
           sources_extra="EMA register rows (no annex PDFs); one line per EMA scope code.", pre_notes=notes)


if __name__ == "__main__":
    main()
