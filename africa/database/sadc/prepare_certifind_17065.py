"""SADCAS ISO/IEC 17065 dataset (3 bodies). Annex tables have merged cells, so the lines were paired by hand
from the rendered pages of sadcas_17065/pdfs. Usage: python prepare_certifind_17065.py [dataset dir]"""
import csv, json, sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[3]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "certifind" / "data" / "sadcas-botswana-17065"
OUT.mkdir(parents=True, exist_ok=True)
raw = {r["id"]: r for r in json.loads((HERE / "sadcas_17065" / "sadcas_17065_raw.json").read_text(encoding="utf8"))}
ms = {r["name"]: r for r in csv.DictReader(open(ROOT / "certifind" / "data" / "sadcas-botswana" / "bodies.csv", encoding="utf8"))}

# id -> (MS body name to reuse, issue, expiry)
B = {
    "PROD-CERT 001": ("Zambia Bureau of Standards - Certification Services", "2026-07-09", "2027-12-27"),
    "PROD-CERT 002": ("Standards Association of Zimbabwe - Certification Services", "2024-12-18", "2028-08-17"),
    "PROD-CERT 003": ("Tanzania Bureau of Standards - Management System Certification Services", "2024-09-16", "2029-09-15"),
}
F3, C12, K16 = "IAF 3 Food Products, Beverages and Tobacco", "IAF 12 Chemicals, Chemical Products and Fibers", "IAF 16 Concrete, Cement, Lime, Plaster, etc."
L = {}
# (industry, product, scheme_text, normative_docs, standard_refs)
z = []
def Z(ind, st, rule, std, prod, ref):
    z.append((ind, prod, f"{st}; {rule}", std, ref))
r1, r2, r9, r3 = ("R3400-1: - Specific Scheme Rules for the Certification of Bottled Water", "R3400-2: - Specific Scheme Rules for the Certification of Soft Drinks",
                  "R3400-9: - Specific Scheme Rules for the Certification of Wheat Flour", "R3400-3: - Specific Scheme Rules for the Certification of Dairy Products")
Z("food", F3, r1, "ZS 388: 2000", "Bottled Drinking Water", "ZS 388")
Z("food", F3, r2, "ZS 203:2012", "The Manufacture of Soft Drinks and Soft Drink Concentrates", "ZS 203")
Z("food", F3, r2, "ZS554: 2012", "Fruit flavored drinks - Specifications", "ZS 554")
Z("food", F3, r2, "ZS 1134: 2018", "Energy Drinks", "ZS 1134")
Z("food", F3, r9, "ZS 435:2017", "Wheat Flour Specification", "ZS 435")
for s, p in [("ZS 1060:2017", "Milk Blended Drinks"), ("ZS 730:2018", "Pasteurized Milk,"), ("ZS 735:2017", "Sterilized Milk (UHT)"),
             ("ZS 731:2018", "Yoghurt"), ("CXS 243: 2003", "Fermented Milk"), ("ZS 733:2010", "Butter"), ("CXS 288:1976", "Cream and Prepared Creams")]:
    Z("food", F3, r3, s, p, s.split(":")[0].replace("  ", " "))
r5 = "R3400-5: - Specific Scheme Rules for The Certification of Poultry Products"
Z("food", F3, r5, "ZS 1246:2023", "Dressed Chicken", "ZS 1246")
Z("food", F3, r5, "ZS 1247:2023", "Chicken Carcasses and Cuts - Specification", "ZS 1247")
rc = "R 3300-1: - Specific Scheme Rules for the Certification of Detergents and Household Care Products"
for s, p in [("ZS 056: 2009", "Toilet Soap"), ("ZS 058: 2009", "Laundry Soap"), ("ZS 062: 2017", "Synthetic Detergents"),
             ("ZS 247: 2017", "Household Hand Dishwashing Liquid Detergent"), ("ZS 818: 2014", "Disinfectants"),
             ("ZS 1033:2017", "Liquid Antiseptics containing Substituted Phenolics"), ("ZS 1035:2017", "Detergents for Industrial Dishwashing Equipment"),
             ("ZS 1036:2017", "Liquid toilet soap"), ("ZS 1038:2017", "Antibacterial Liquid Toilet Soap for Medical use"),
             ("ZS 1039:2020", "Disinfectant Alcohol-based Hand Rub"), ("ZS 1041:2017", "Industrial Laundry Detergent"),
             ("ZS 1043:2017", "Detergent for Domestic Dishwashing Machines"), ("ZS 1045:2017", "Oven Cleaner and Grease Remover"),
             ("ZS 1136: - 2018", "Sodium Hypochlorite Solutions - Specifications")]:
    Z("chemicals", C12, rc, s, p, "ZS " + s.split("ZS")[1].split(":")[0].strip())
rcem = "R3400-3: Specific Scheme Rules for the Certification of Cement"
Z("construction", K16, rcem, "ZS EN 197:2020 Part 1", "Composition, Specification and Conformity Criteria for Common Cements", "EN 197-1")
Z("construction", K16, rcem, "ZS EN 197:2020 Part 2", "Conformity Evaluation", "EN 197-2")
L["PROD-CERT 001"] = z

sch = "IAF 6 Wood and Wood Products; PM/MRE 01 Revision 6"
L["PROD-CERT 002"] = [
    ("wood_paper", "Eucalyptus poles, cross-arms and spacers for power distribution and communications systems", sch, "ZWS 120:2022", "ZWS 120"),
    ("wood_paper", "Hardwood poles, droppers and guardrail posts", sch, "ZWS 553:2023", "ZWS 553")]

T3, T6 = "IAF 3 Food Products, Beverages and Tobacco; Factory Assessment Checklist for Food Products, Beverages and Tobacco", "IAF 6 Wood and wood products; Factory Assessment Checklist for Wood and Wood Products"
L["PROD-CERT 003"] = [
    ("food", "Carbonated soft drinks - Specification", T3, "TZS 390:2004 (2nd Ed)", "TZS 390"),
    ("food", "Packaged/bottled drinking water - Specification", T3, "TZS 574:2019 (3rd Ed); EAS 153: 2018", "TZS 574;EAS 153"),
    ("food", "Beer - Specification", T3, "TZS 56:2015 (3rd Ed); EAS 63:2014", "TZS 56;EAS 63"),
    ("food", "Ready to drink non-carbonated non-alcoholic beverage - Specification", T3, "TZS 585:2011 (2nd Ed)", "TZS 585"),
    ("wood_paper", "Preservative treated timber - Specification", T6, "TZS 1347:2009", "TZS 1347"),
    ("wood_paper", "Wood poles and blocks for power and telecommunication lines - Specification", T6, "TZS 686:2011", "TZS 686"),
    ("chemicals", "Petroleum jelly for cosmetic industry - Part 2: Marketed petroleum jelly products ready for use as body ointment - Specification",
     "IAF 12 Chemicals, chemical products and fibers; Factory Assessment Checklist for Cosmetic Products", "TZS 318 (Part 2): 2017 (2nd Ed)", "TZS 318-2"),
    ("chemicals", "Skin care creams, lotions and gels - Specification",
     "IAF 12 Chemicals, chemical products and fibers; Factory Assessment Checklist for Cosmetic Products", "TZS 313: 2014 (3rd Ed); EAS 786:2013", "TZS 313;EAS 786"),
    ("construction", "Cement - Composition, specifications, and conformity criteria for common cements",
     "IAF 16 Concrete, cement, lime plaster etc.; Factory Assessment Checklist for Cement Products", "TZS 727 (Part 1): 2018; EAS 18-1:2017(E)", "TZS 727-1;EAS 18-1"),
    ("metals", "Steel for the reinforcement of concrete - Part 2: Ribbed bars",
     "IAF 17 Basic metals and fabricated metal products; Factory Assessment Checklist of Steels for the Reinforcement and pre-stressing of concrete - steel bars", "TZS 142-2: 2020; EAS 412-2: 2019", "TZS 142-2;EAS 412-2"),
    ("metals", "Steel for the reinforcement of concrete - Part 4: Ribbed bars - Low grade steel (300 MPa - 450 MPa)",
     "IAF 17 Basic metals and fabricated metal products; Factory Assessment Checklist of Steels for the Reinforcement and pre-stressing of concrete - steel bars", "TZS 142-4:2021", "TZS 142-4"),
    ("electrical", "Polyvinyl chloride insulated cables of rated voltages up to and including 450/750 V - Part 8: Single core, flat twin and 3-core sheathed cables for fixed wiring.",
     "IAF 19 Electrical and Optical Equipment; Factory Assessment Checklist for PVC insulated Cables", "TZS 1518 - 8:2015(E)", "TZS 1518-8"),
]


def w(n, h, rows):
    with open(OUT / n, "w", encoding="utf8", newline="") as f:
        c = csv.writer(f, lineterminator="\n")
        c.writerow(h)
        c.writerows(rows)


bodies, accs, lines = [], [], []
for rid, (msname, issue, exp) in B.items():
    bodies.append(list(ms[msname].values()))
    accs.append(["SADCAS", rid, msname, "ISO/IEC 17065", "ACTIVE", issue, exp, raw[rid]["annex_urls"][0]])
    for i, (ind, prod, st, std, ref) in enumerate(L[rid], 1):
        lines.append([rid, i, "", ind, prod, "", st, std, ref, "ACTIVE"])
w("bodies.csv", "name,country,registration_no,phone,email,website,address,source_url,verified_at".split(","), bodies)
w("accreditations.csv", "ab_code,certificate_number,body_name,accreditation_standard,status,issue_date,expiry_date,proof_url".split(","), accs)
w("scopes.csv", "certificate_number,certification_standard,ea_codes,status,scope_note".split(","), [])
w("product_scopes.csv", "certificate_number,line_no,scheme,industry,product_text,product_text_en,scheme_text,normative_docs,standard_refs,status".split(","), lines)
print(len(bodies), "bodies,", len(accs), "accreditations,", len(lines), "lines")
