"""KENAS ISO/IEC 17065 dataset. The schedules are scanned images (no text layer, no OCR), so every
line below was transcribed by eye from pages rendered with pymupdf. KEBS (CB/023) is recorded per IAF code
(about 900 standards are NOT transcribed one by one). Usage: python prepare_certifind_17065.py [dataset dir]"""
import csv, json, sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[2] / "certifind" / "data" / "kenas-kenya-17065"
OUT.mkdir(parents=True, exist_ok=True)
raw = {r["id"]: r for r in json.loads((HERE / "kenas_17065_raw.json").read_text(encoding="utf8"))}
MS = HERE.parents[2] / "certifind" / "data" / "kenas-kenya" / "bodies.csv"
ms = {r["name"]: r for r in csv.DictReader(open(MS, encoding="utf8"))}
SRC = "https://kenas.go.ke/status"
KEBS_NAME = "Kenya Bureau of Standards (KEBS) Product Certification Body"

# id -> (name, (country, phone, email, website, address) or None to reuse the MS row, issue, expiry)
B = {
    "KENAS/CB/020": ("Bureau Veritas Certification Kenya Limited", None, "2026-08-12", "2030-06-29"),
    "KENAS/CB/026": ("Achelab Laboratory Services Limited", ("Somalia", "+252 61 983 2182", "info@achelablaboratoryservices.so",
                     "https://www.achelablaboratoryservices.so", "Abdi Aziz District, Mogadishu"), "2023-11-30", "2027-11-29"),
    "KENAS/CB/029": ("Bureau Burundais De Normalisation Et Controle De La Qualite (BBN)", ("Burundi", "+257 22 22 18 15",
                     "info@bbnburundi.org", "", "Boulevard de Tanzanie, No. 500, B.P. 3535, Bujumbura"), "2024-02-15", "2028-02-14"),
    "KENAS/CB/032": ("Zambia Bureau of Standards (ZABS)", ("Zambia", "+260 211 231385", "info@zabs.org.zm", "",
                     "Plot No. 4526, Lechwe House, Freedom Way, South End, Lusaka"), "2024-10-24", "2028-10-23"),
    "KENAS/CB/023": (KEBS_NAME, ("Kenya", "+254 20 6005480", "info@kebs.org", "https://www.kebs.org",
                     "Popo Road, off Mombasa Road, P.O. Box 54974-00200, Nairobi"), "2025-06-27", "2029-06-26"),
    "KENAS/CB/036": ("Standards and Quality Agency (ANOR) Product Certification Body", ("Cameroon", "+237 691 12 78 07",
                     "contact@anor.cm", "https://www.anor.cm", "Bastos, Former Elecam Avenue, 14966 Yaounde"), "2025-07-25", "2029-07-24"),
    "KENAS/CB/035": ("Inspectorate (East Africa) Limited Process Certification Body", ("Kenya", "+254 41 2317318",
                     "admin@inspectorate-ea.com", "", "Rothmans Building, Kizingo, P.O. Box 42327-80100, Mombasa"), "2025-09-05", "2029-09-04"),
    "KENAS/CB/040": ("Key-Cert Services Limited (Product Certification Body)", ("Kenya", "+254 793 601626",
                     "info@key-cert.com", "", "25 Parklands Road, 3rd Floor Left Wing, P.O. Box 1781-00606 Sarit, Nairobi"), "2026-07-14", "2030-07-13"),
}
SM = "Scheme Rules for the Certification of products under Standardization Mark (SM) and Diamond mark (DM)"
ACAP_D = "ACAP Certification Scheme D: Sustainability certification programme"
ACAP_B = "ACAP Certification Scheme B: Processing and handling / packing of food and fresh produce"
KEBS_IAF = [
    ("IAF Code 3 Food products, beverages and tobacco", "food"),
    ("IAF Code 4 Textiles and textile products", "textiles"),
    ("IAF Code 7 Pulp, Paper and paper products", "wood_paper"),
    ("IAF Code 10 Manufacture of coke and refined petroleum products", "energy"),
    ("IAF Code 12 Chemicals, chemical products and fibres", "chemicals"),
    ("IAF Code 14 Rubber and Plastic Products", "rubber_plastics"),
    ("IAF Code 16 Concrete, cement, lime, plaster, etc.", "construction"),
    ("IAF Code 17 Basic metals and fabricated metal products", "metals"),
    ("IAF Code 18 Machinery and equipment", "machinery"),
    ("IAF Code 19 Electrical and optical equipment", "electrical"),
    ("IAF Code 23 Manufacturing not elsewhere classified", "other_manufacturing"),
]
BBN = "Bureau Burundais de Normalisation et Contrôle de la Qualité (BBN) Scheme (IAF 3: Food Products and Beverages)"
# line = (scheme, industry, product, scheme_text, normative_docs, standard_refs)
L = {
    "KENAS/CB/020": [("", "agriculture", "Flowers & Ornamentals", "Scheme Rules for Product Certification KS 1758 Certification scheme",
                      "KS 1758-1 Horticulture industry code of practice floriculture", "KS 1758-1")],
    "KENAS/CB/026": [("", "agriculture", "Fruits and vegetables", "Product Certification KS 1758 Certification Scheme",
                      "KS 1758-2:2016 Horticulture industry- Code of practice - Part 2: Fruits and vegetables.", "KS 1758-2")],
    "KENAS/CB/029": [
        ("", "food", "Tea", BBN, "EAS 28:2019 Black tea-Specification", "EAS 28"),
        ("", "food", "Coffee", BBN, "EAS 105:2020 Roasted coffee beans and roasted ground coffee - Specification", "EAS 105"),
        ("", "food", "Wheat flour", BBN, "EAS 1:2019 Wheat flour- Specification", "EAS 1"),
        ("", "food", "Mineral Water", BBN, "EAS 13:2023 Packaged mineral waters- Specification.", "EAS 13")],
    "KENAS/CB/032": [
        ("", "agriculture", "Agricultural crops", ACAP_D,
         "ARS/AES 01:2014 Agriculture- Sustainability and eco-labelling- Requirements; ZS 652:2005 Black Tea Specification", "ARS/AES 01"),
        ("", "agriculture", "Tilapia", ACAP_D,
         "ARS/AES 6:2018, Aquaculture - Tilapia - Sustainability and eco-labelling - Requirements; ZS972: 2016 Broodstock specifications; ZS 973: 2016 Fingerling specifications",
         "ARS/AES 6")],
    "KENAS/CB/023": [("", "agriculture", "Organic fertilizer-Specification; Biofertilizers-Specification", SM,
                      "KS EAS 1167:2024; KS EAS 1176:2024", "KS EAS 1167;KS EAS 1176")]
                    + [("", ind, h, SM, "", "") for h, ind in KEBS_IAF]
                    + [("", "agriculture", "Agricultural Crops", ACAP_D,
                        "ARS/AES 1:2014, Agriculture - Sustainability and eco-labelling -Requirements", "ARS/AES 1")],
    "KENAS/CB/036": [
        ("", "food", "Edible cassava flour", ACAP_B, "ARS 838:2016(E), Cassava flour- Specification", "ARS 838"),
        ("", "food", "Portable Water for human consumption", ACAP_B,
         "NC 207:2018 Standard for Drinking Water Intended for Human Consumption; NC 04:2019 General Labelling Standard for Prepackaged Food Packaging",
         "NC 207;NC 04")],
    "KENAS/CB/035": [
        ("", "energy", "Bulk Liquid Petroleum Products",
         "Process certification scheme for secure and safe receipt, storage, handling and distribution of bulk liquid petroleum products in petroleum depots.",
         "In-house scheme; \"Insp-Cert-PCS-SC-01\"; KS 1938-Code of Practice for handling, Storage and Distribution of Petroleum product; KS 2207-Specification for design and construction of petroleum tanks; KS 2460-Guidelines for Safety in petroleum.",
         "KS 1938;KS 2207;KS 2460"),
        ("", "energy", "Liquid petroleum Gas in Bulk",
         "Process certification scheme for secure and safe receipt, storage, handling and distribution of Liquid petroleum Gas in Bulk at Liquid Petroleum Gas (LPG) depots.",
         "In-house scheme; \"Insp-Cert-PCS-SC-02\"; KS EAS 924-2; KS EAS 924-3:2020; KS 2024:2006 Gas cylinders - Refillable welded steel cylinders for LPG; KS 1938; KS 2207; KS 2460; KS 233 Part 1-Code of practice for installation of oil storage tanks; NFPA Codes",
         "KS EAS 924-2;KS EAS 924-3;KS 2024;KS 1938;KS 2207;KS 2460;KS 233-1")],
    "KENAS/CB/040": [("GLOBALG.A.P. IFA", "", "All Farm and Crop Base Modules; Fruit and Vegetables Module",
                      "GLOBALG.A.P. General Regulations Version 6 Includes Smart plant",
                      "GLOBALG.A.P Integrated Farm Assurance (IFA) v6; GLOBALG.A.P. General IFA SMART; Principles and Criteria Fruit and Vegetables Standard Regulations Version 6", "")],
}


def w(n, h, rows):
    with open(OUT / n, "w", encoding="utf8", newline="") as f:
        c = csv.writer(f, lineterminator="\n")
        c.writerow(h)
        c.writerows(rows)


bodies, accs, lines = [], [], []
for rid, (name, d, issue, exp) in B.items():
    if d is None:
        bodies.append(list(ms[name].values()))
    else:
        bodies.append([name, d[0], rid, d[1], d[2], d[3], d[4], SRC, ""])
    accs.append(["KENAS", rid, name, "ISO/IEC 17065", "ACTIVE", issue, exp, raw[rid]["certificate_url"]])
    for i, l in enumerate(L[rid], 1):
        lines.append([rid, i, l[0], l[1], l[2], "", l[3], l[4], l[5], "ACTIVE"])
w("bodies.csv", "name,country,registration_no,phone,email,website,address,source_url,verified_at".split(","), bodies)
w("accreditations.csv", "ab_code,certificate_number,body_name,accreditation_standard,status,issue_date,expiry_date,proof_url".split(","), accs)
w("scopes.csv", "certificate_number,certification_standard,ea_codes,status,scope_note".split(","), [])
w("product_scopes.csv", "certificate_number,line_no,scheme,industry,product_text,product_text_en,scheme_text,normative_docs,standard_refs,status".split(","), lines)
print(len(bodies), "bodies,", len(accs), "accreditations,", len(lines), "lines")
