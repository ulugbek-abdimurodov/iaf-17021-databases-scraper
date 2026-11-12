"""Convert raw EMA register data into CertiFind CSVs (data/ema-mexico)."""
import json
import re
from pathlib import Path

from certifind_common import resolve_cert_number, write_certifind_csvs

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
OUT = ROOT / "data" / "ema-mexico"
SOURCE_URL = "https://catalogo.consultaema.mx:75/busqueda-organismos-certificacion"

# EMA scope code -> certification standard
SCHEME = {
    "SGC": "ISO 9001", "SGA": "ISO 14001", "SASST": "ISO 45001", "SGSST": "ISO 45001",
    "SGSI": "ISO/IEC 27001", "SGTI": "ISO/IEC 20000-1", "SGCN": "ISO 22301",
    "SGIA": "ISO 22000", "SGDM": "ISO 13485", "SGE": "ISO 50001",
}
COUNTRIES = {"USA": "United States", "ESTADOS UNIDOS": "United States", "ESPAÑA": "Spain", "SPAIN": "Spain",
             "COLOMBIA": "Colombia", "PERÚ": "Peru", "PERU": "Peru", "CHILE": "Chile", "ARGENTINA": "Argentina",
             "GUATEMALA": "Guatemala", "COSTA RICA": "Costa Rica", "ECUADOR": "Ecuador", "CANADA": "Canada",
             "CANADÁ": "Canada", "ITALIA": "Italy", "ALEMANIA": "Germany", "INDIA": "India", "CHINA": "China",
             "REINO UNIDO": "United Kingdom", "FRANCIA": "France", "BRASIL": "Brazil"}


def clean_id(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .")


def country_of(addr: str) -> str:
    up = addr.upper()
    for k, v in COUNTRIES.items():
        if re.search(r"\b" + re.escape(k) + r"\b", up):
            return v
    return "Mexico"


SCOPE_NAMES = {
    "SGC": "Sistema de Gestión de la Calidad", "SGA": "Sistema de Gestión Ambiental",
    "SASST": "Sistema de Administración de Seguridad y Salud en el Trabajo", "SGSST": "Sistema de Gestión de Seguridad y Salud en el Trabajo",
    "SGSI": "Sistema de Gestión de Seguridad de la Información", "SGTI": "Sistemas de Gestión de Tecnologías de la Información",
    "SGCN": "Sistemas de Gestión de Continuidad de Negocio", "SGIA": "Sistema de Gestión de la Inocuidad Alimentaria",
    "SGDM": "Sistemas de Gestión de Calidad de Dispositivos Médicos", "SGE": "Sistemas de Gestión de la Energía",
    "SGAS": "Sistemas de Gestión Anti Soborno (ISO 37001)", "SGCM": "Sistema de Gestión de Compliance (ISO 37301)",
    "SGOE": "Sistema de Gestión para Organizaciones Educativas (ISO 21001)", "SGS": "Sistemas de Gestión de Seguridad (ISO 28000)",
    "SGSP": "Sistemas de Gestión de Operaciones de Seguridad Privada (ISO 18788)",
}


def title_caps(addr: str) -> str:
    return ", ".join(p.strip().title() if p.strip().isupper() and len(p.strip()) > 3 else p.strip()
                     for p in addr.split(","))


NAME_COUNTRY = {
    "INSTITUTO BOLIVIANO DE NORMALIZACION Y CALIDAD": "Bolivia",
    "Instituto Dominicano para la Calidad (INDOCAL)": "Dominican Republic",
    "BSI Group America Inc.": "United States",
    "Perry Johnson Registrars, Inc.": "United States",
    "American Registrar of Management Systems, LLC": "United States",
    "AMERICAN BIG CERTIFICATIONS, S.A DE C.V.": "Mexico",
}


def load():
    names, rows, cl = (blk.strip("\n").split("\n") for blk in
                       (HERE / "raw" / "ema_register.txt").read_text(encoding="utf-8").split("\n#\n"))
    out = []
    for line in rows:
        acc, ni, d, st, codes = line.split("~")
        for code in codes.split(","):
            out.append((acc, code, f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else "", st or "Acreditado", names[int(ni)]))
    clients, acc_exp = {}, {}
    for line in cl:
        acc, name, exp, email, url, addr = line.split("~")
        clients.setdefault(name.strip().upper(), {"e": email, "u": url, "a": addr})
        acc_exp[acc] = exp
    return out, clients, acc_exp


def clean_addr(a: str) -> str:
    a = re.sub(r",\s*,?\s*Extranjero, CP\. 99999, Extranjero", "", a)
    return title_caps(a)


def main() -> None:
    rows, clients, acc_exp = load()
    bodies, accs, scopes, excluded = {}, {}, {}, []
    for acc_id, scope_code, start, status, cname in rows:
        scope_name = SCOPE_NAMES.get(scope_code, scope_code)
        std = SCHEME.get(scope_code)
        if not std:
            excluded.append((cname, acc_id, scope_code, scope_name))
            continue
        expiry = acc_exp.get(acc_id, "")
        c = clients.get(cname.strip().upper(), {})
        name = re.sub(r"\s+,", ",", cname.strip())
        base = clean_id(acc_id)
        cert, acc_std = resolve_cert_number(base, std)
        b = bodies.setdefault(name, {
            "name": name, "country": NAME_COUNTRY.get(cname.strip(), country_of(c.get("a", ""))), "registration_no": "",
            "phone": "", "email": c.get("e", ""), "website": c.get("u", ""),
            "address": clean_addr(c.get("a", "")), "source_url": SOURCE_URL, "verified_at": ""})
        if re.fullmatch(r"\d+/\d+", base) and not b["registration_no"]:
            b["registration_no"] = base
        accs.setdefault(cert, {
            "ab_code": "EMA", "certificate_number": cert, "body_name": name,
            "accreditation_standard": acc_std, "status": "active" if status == "Acreditado" else status.lower(),
            "issue_date": start or "", "expiry_date": expiry or "", "proof_url": SOURCE_URL})
        scopes[(cert, std)] = {
            "certificate_number": cert, "certification_standard": std, "ea_codes": "",
            "status": "active", "scope_note": f"EMA scope {scope_code} ({scope_name}); register publishes no EA/IAF codes"}
    for b in bodies.values():
        if not b["registration_no"]:
            b["registration_no"] = next(a["certificate_number"].split(" (")[0] for a in accs.values() if a["body_name"] == b["name"])

    with open(HERE / "ema_review.md", "w", encoding="utf-8") as f:
        f.write("# EMA review — skipped schemes\n\nRows under ISO/IEC 17021-1 whose scheme is outside the CertiFind map, "
                "plus all non-17021 programmes (17065 product, 17024 persons, 17029 validation/verification).\n\n"
                "| Body | Accreditation | Scheme code | Scheme |\n|---|---|---|---|\n")
        for e in sorted(excluded):
            f.write("| " + " | ".join(e) + " |\n")
        only = sorted({e[0] for e in excluded} - {a["body_name"] for a in accs.values()})
        f.write("\n## Bodies excluded entirely (only out-of-scope schemes)\n\n" + "\n".join(f"- {n}" for n in only) + "\n")

    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        write_certifind_csvs(OUT, list(bodies.values()), list(accs.values()), list(scopes.values()))
    print(f"Bodies: {len(bodies)}\nAccreditations: {len(accs)}\nScopes: {len(scopes)}\nExcluded: {len(excluded)}")


if __name__ == "__main__":
    main()
