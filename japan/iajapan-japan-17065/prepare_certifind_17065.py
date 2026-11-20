"""Convert the IAJapan (NITE, ASNITE) ISO/IEC 17065 scrape into certifind/data/iajapan-japan-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_jp_iajapan_17065.py): iajapan_17065/iajapan_17065_raw.json and the 7 English annex PDFs in
iajapan_17065/annexes/. The annexes are short multi-column tables whose text layer interleaves the columns, so the
"Scope of Accreditation" tables are transcribed below (LINES, read 2026-11-20): one line per scope row,
product_text = scope (product / process), normative_docs = the standard column. Expiry dates come from the annexes.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER = "IAJapan", "iajapan-japan-17065"
URL = "https://www.nite.go.jp/en/iajapan/asnite/lab/index_asnite_product_e.html"
EXPIRY = {"ASNITE 0001": "2027-04-02", "ASNITE 0011": "2028-01-22", "ASNITE 0045": "2029-03-18",
          "ASNITE 0064": "2028-10-26", "ASNITE 0131": "2029-09-18", "ASNITE 0135": "2027-03-02",
          "ASNITE 0142": "2028-08-20"}
# "Effective Date of Accreditation" of the field in each annex (the register publishes no dates).
ISSUED = {"ASNITE 0001": "2023-04-03", "ASNITE 0011": "2025-01-23", "ASNITE 0045": "2025-03-19",
          "ASNITE 0064": "2024-10-27", "ASNITE 0131": "2025-09-19", "ASNITE 0135": "2023-03-03",
          "ASNITE 0142": "2024-08-21"}
OIML, IECEX, RAIL = "OIML-CS", "IECEx Certified Equipment Scheme", "EN 50126 / 50128 / 50129"
RAMS = ("Specification and demonstration of reliability, availability, maintainability and safety (RAMS): design "
        "document and/or product according to RAMS Life Cycle Process on railway system, rolling stock (train and "
        "complete vehicle), rolling stock (equipment), signalling, communication and processing systems, fixed power "
        "supply installations and equipment (IEC 62278:2002 6.1~6.7 and IEC 62278-1:2025 7.2~7.8, Phase 1 to 7)")
EX = [("Flameproof enclosures \"d\"", "IEC 60079-0, IEC 60079-1"),
      ("Pressurized enclosure \"p\"", "IEC 60079-0, IEC 60079-2"),
      ("Liquid immersion \"o\"", "IEC 60079-0, IEC 60079-6"),
      ("Increased safety \"e\"", "IEC 60079-0, IEC 60079-7"),
      ("Intrinsic safety \"i\"", "IEC 60079-0, IEC 60079-11"),
      ("Type of protection \"n\"", "IEC 60079-0, IEC 60079-15"),
      ("Encapsulation \"m\"", "IEC 60079-0, IEC 60079-18"),
      ("Intrinsically safe electrical systems", "IEC 60079-0, IEC 60079-11, IEC 60079-25"),
      ("Equipment with Separation Elements or combined Levels of Protection", "IEC 60079-26"),
      ("Protection of equipment and transmission systems using optical radiation", "IEC 60079-0, IEC 60079-28"),
      ("Dust ignition Protection by enclosure \"t\"", "IEC 60079-0, IEC 60079-31"),
      ("Electrical resistance trace heating", "IEC 60079-0, IEC/IEEE 60079-30-1"),
      ("Vacuum cleaners and dust extractors providing equipment protection level Dc for the collection of "
       "combustible dusts", "IEC 60079-0, IEC 62784"),
      ("Powder filling \"q\"", "IEC 60079-0, IEC 60079-5"),
      ("Pressurized room \"p\" and artificially ventilated room \"v\"", "IEC 60079-0, IEC 60079-13"),
      ("Special protection \"s\"", "IEC 60079-0, IEC 60079-33"),
      ("Equipment assemblies", "IEC 60079-0, ISO 80079-36, IEC/TS 60079-46"),
      ("Non-electrical type of protection constructional safety \"c\", control of ignition source \"b\", liquid "
       "immersion \"k\"", "ISO 80079-36, ISO 80079-37")]
ECO = "Certification criteria for each product category stipulated by the Eco Mark Office"
# registration_no -> [(product_text, normative_docs, scheme, industry)]
LINES = {
    "ASNITE 0001": [
        ("Load cells (Class: C, D; maximum load 20 t)", "OIML R 60:2000; OIML R 60:2017; OIML R 60:2021", OIML, ""),
        ("Non-automatic weighing instruments (Class: I - IIII; maximum test capacity 300 kg)",
         "OIML R 76:1992; OIML R 76:2006", OIML, ""),
        ("Dynamic measuring systems for liquids other than water (fuel dispenser)",
         "OIML R 117:1995; OIML R 117:2007; OIML R 117:2019", OIML, "")],
    "ASNITE 0011": [
        ("Gas valves (L.P. Gas valves)", "Ministerial Ordinance on Technical Standards for Liquefied Petroleum Gas "
         "Equipment (Ministerial Ordinance No. 23 of March 27, 1968) Appendix 3", "", "energy")],
    "ASNITE 0045": [
        ("Recycled Claim Standard (RCS) - material recycler (primary scope)",
         "Textile Exchange - Recycled Claim Standard 2.0 (2017)", "Recycled Claim Standard", ""),
        ("Global Recycled Standard (GRS) - material recycler (primary scope)",
         "Textile Exchange - Global Recycled Standard 4.0 (2017)", "Global Recycled Standard", ""),
        ("Content Claim Standard (CCS), including claims related to the Organic Content Standard (OCS), Recycled Claim "
         "Standard (RCS), Responsible Down Standard (RDS) and Responsible Animal Fiber (RAF)",
         "Textile Exchange - Content Claim Standard 3.1 (2022)", "Content Claim Standard", ""),
        ("Global Recycled Standard (GRS) - excluding material recycler (primary scope)",
         "Textile Exchange - Global Recycled Standard 4.0 (2017)", "Global Recycled Standard", "")],
    "ASNITE 0064": [
        (RAMS, "IEC 62278:2002; IEC 62278-1:2025; IEC 62425:2007; IEC 62425:2025 Railway applications - "
         "Communication, signalling and processing systems - Safety related electronic systems for signalling",
         RAIL, ""),
        (RAMS, "IEC 62279:2002; IEC 62279:2015 Railway applications - Software for railway control and protection "
         "systems; IEC 62280-1:2002; IEC 62280-2:2002 Safety-related communication in closed / open transmission "
         "systems", RAIL, ""),
        (RAMS, "IEC 62280:2014 Railway applications - Communication, signalling and processing systems - Safety "
         "related communication in transmission systems", RAIL, "")],
    "ASNITE 0131": [(f"Ex Equipment: {p}", n, IECEX, "") for p, n in EX],
    "ASNITE 0135": [
        ("Eco Mark: Household commodity / Fashion, accessories", ECO, "", "other_manufacturing"),
        ("Eco Mark: OA equipment and its supplies / Stationery, office supplies", ECO, "", "other_manufacturing"),
        ("Eco Mark: Home appliances / Furniture, interior", ECO, "", "electrical"),
        ("Eco Mark: Products and equipment for civil engineering", ECO, "", "construction"),
        ("Eco Mark: Materials for commercial use and DIY / Containers and Packaging / Others", ECO, "",
         "rubber_plastics")],
    "ASNITE 0142": [
        ("PKS (Palm Kernel Shell) Supply Chain Certification (CPO Mills, PKS Collectors, Traders, etc.)",
         "PKS Certification System: Policy (P01); Organizational Requirements (ST01); PKS Due Diligence System "
         "Requirements (ST02)", "", "energy")],
}


def main():
    scrape, today = cf.cli(HERE / "iajapan_17065")
    raw = json.load(open(scrape / "iajapan_17065_raw.json", encoding="utf-8"))
    bodies = []
    for r in raw:
        reg = r["registration_no"]
        b = cf.Body(reg=reg, name=r["name"], country="Japan", phone=r["phone"], email=r["email"],
                    website=r["website"], address=r["address"], issued=r["issued"] or ISSUED.get(reg, ""), expiry=EXPIRY.get(reg, ""),
                    proof_url=(r["annex_urls"] or [URL])[0], source_url=URL)
        for prod, norm, sch, ind in LINES.get(reg, []):
            b.lines.append(cf.Line(product_text=prod, normative_docs=norm, scheme=sch if sch in cf.CATALOGUE else "",
                                   industry=None if sch in cf.CATALOGUE else (ind or None)))
        bodies.append(b)
    cf.run(AB, FOLDER, None, URL, bodies, HERE / "iajapan_17065_review.md", today,
           sources_extra="Register: NITE ASNITE product certification list. Scope lines transcribed from the 7 English "
                         "annexes (LINES in the converter); expiry dates from the annexes.")


if __name__ == "__main__":
    main()
