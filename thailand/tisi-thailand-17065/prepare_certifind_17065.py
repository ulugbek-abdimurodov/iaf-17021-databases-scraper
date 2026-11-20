"""Convert the TISI / NSC (Thailand) ISO/IEC 17065 scrape into certifind/data/tisi-thailand-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input (scrape_th_tisi_17065.py): tisi_17065/tisi_17065_raw.json (11 register records, certify CB, 17065) and
tisi_17065/pdfs/<cert>_{cert,scope}.pdf. The scope annexes are short bilingual tables (Thai, English in brackets),
transcribed below (LINES, read 2026-11-20): product_text = Thai, product_text_en = the annex's English,
normative_docs = the standards of the entry. Validity comes from the annexes (VALID); the register's English page
has no or wrong dates (23-CB0019 "12 September 1485" is B.E. 2571 = 2028 misread).

Left out: expired 21-CB0002 (TISTR tourism attractions, until 2026-07-18), 21-CB0003 (ISEM, until 2026-08-30),
22-CB0020 (EEI electrical products, until 2026-10-21); 23-CB0010 (DSS, PRODUCT 008) is the earlier issue of the
same accreditation as 25-CB0010; 23-CB0012 (NSTDA PTEC, PRODUCT 004) has no published scope annex or validity.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "TISI", "tisi-thailand-17065", "tisi-thailand"
URL = "https://center.tisi.go.th/report/certificate"
# certificate -> (valid from, until) from the annex; None = not imported (reason in docstring)
VALID = {
    "21-CB0002": None, "21-CB0003": None, "22-CB0020": None, "23-CB0010": None, "23-CB0012": None,
    "22-CB0018": ("2022-02-18", "2027-02-17"),
    "22-CB0021": ("2024-05-15", "2026-12-20"),
    "23-CB0005": ("2022-09-26", "2027-09-25"),
    "23-CB0019": ("2023-09-13", "2028-09-12"),
    "24-CB0019": ("2024-05-15", "2029-03-04"),
    "25-CB0010": ("2025-06-20", "2028-03-15"),
}
NAMES = {
    "22-CB0018": "King Mongkut's University of Technology Thonburi, International Standard Certification Center",
    "22-CB0021": "National Electronics and Computer Technology Center (NECTEC), Digital Technology Evaluation and "
                 "Certification Institute",
    "23-CB0005": "Thailand Institute of Scientific and Technological Research (TISTR)",  # data/tisi-thailand row
    "23-CB0019": "Thailand Environment Institute Foundation",
    "24-CB0019": "Office of the National Broadcasting and Telecommunications Commission (NBTC)",
    "25-CB0010": "Department of Science Service (DSS)",
}
ADDRESSES = {
    "22-CB0018": "126 Pracha Uthit Rd., Bang Mod, Thung Khru, Bangkok 10140, Thailand",
    "22-CB0021": "112 Thailand Science Park, Phahonyothin Road, Klong Nueng, Klong Luang, Pathumthani",
    "23-CB0019": "16/151 Muang Thong Thani, Bond Street Road, Bangpood, Pakkred, Nonthaburi",
    "24-CB0019": "87 Phaholyothin 8 (Soi Sailom), Samsen Nai, Phayathai, Bangkok 10400",
    "25-CB0010": "75/7 Rama VI Road, Thung Phayathai, Ratchathewi, Bangkok",
}
TTS = "Thailand Tourism Standard (มทท / TTS)"
CERAMIC_TEST = ("มอก. 32-2546 (TIS 32-2546 (2003)) Test Method for the Release of Lead and Cadmium from Ceramic Ware, "
                "Glass-Ceramic Ware and Glassware in Contact with Food; ISO 6486-1:1999")
# certificate -> [(product_text Thai, product_text_en, normative_docs, scheme_text, industry)]
LINES = {
    "22-CB0018": [
        ("บริการท่องเที่ยว: มาตรฐานการให้บริการในสถานที่จำหน่ายของที่ระลึก (สินค้าทั่วไป)",
         "Tourism Services: Souvenirs Shop Service Standard for Tourism", "มทท 306 : 2552 (TTS 306 : 2009)", TTS,
         "tourism"),
        ("บริการท่องเที่ยว: มาตรฐานการให้บริการในสถานที่จำหน่ายของที่ระลึก (สินค้าอัญมณี)",
         "Tourism Services: Souvenirs Shop (Gem Stone Products) Service Standard", "มทท 307 : 2554 (TTS 307 : 2011)",
         TTS, "tourism"),
        ("บริการท่องเที่ยว: มาตรฐานการบริการรถตู้ปรับอากาศสำหรับนักท่องเที่ยว",
         "Tourism Services: Van Service Standard for Tourism", "มทท 311 : 2557 (TTS 311 : 2014)", TTS, "tourism"),
        ("บริการท่องเที่ยว: มาตรฐานการให้บริการและความปลอดภัยในศูนย์การค้าเพื่อการท่องเที่ยว",
         "Tourism Services: Service and Safety Standard in Shopping Center for Tourism",
         "มทท 312 : 2557 (TTS 312 : 2014)", TTS, "tourism"),
        ("บริการท่องเที่ยว: มาตรฐานการบริการรถโดยสารเพื่อการท่องเที่ยว",
         "Tourism Services: Tourist Bus Standard for Tourism", "มทท 314 : 2558 (TTS 314 : 2015)", TTS, "tourism")],
    "22-CB0021": [
        ("บริภัณฑ์เทคโนโลยีสารสนเทศ", "Information Technology Equipment",
         "มอก. 1561-2548 (TIS 1561-2548 (2005)); มอก. 1561-2556 (TIS 1561-2556 (2013)); TIS 1956-2553 (2010); "
         "TIS 1448-2540 (1997); TIS 1448-2553 (2010); IEC 60950-1 Ed. 1.0 / 2.0 / 2.1; CISPR 22 Ed. 4.0-6.0; "
         "CISPR 13 Ed. 4.2-5.1; IEC 61000-3-2 Ed. 2.1-4.0", "ISO/IEC 17067:2013 Type 1a, 1b", "electrical"),
        ("ซอฟต์แวร์เก็บรักษาข้อมูลจราจรทางคอมพิวเตอร์", "Computer Log Systems",
         "NTS 4003.1-2560 (2017) Computer Log Systems Part 1 Requirements; TIS 1561-2556 (2013); "
         "IEC 60950 Ed 2.1:2009; TIS 1956-2553 (2010); TIS 1448-2553 (2010); CISPR 22 Ed 6.0:2008; "
         "IEC 61000-3-2 Ed 4.0; NECTEC 2001.2-2553; NECTEC 2002.2-2558; NECTEC 2005.2.1-2558; NECTEC 2006.2.1-2558; "
         "NECTEC 2005.3-2558; NECTEC 2006.3-2558", "ISO/IEC 17067:2013 Type 1a, 1b, 3", "ict"),
        ("การออกแบบศูนย์ข้อมูล", "Data Center Design",
         "EIT Standard 022012-16 Thailand Data Center Standard (March B.E. 2559); EIT Standard 022012-22 Thailand "
         "Data Center Standard Addendum 1 (June B.E. 2565)", "R-NT-DTEC-12; ISO/IEC 17067:2013 Type N1", "ict")],
    "23-CB0005": [
        ("พลาสติกสลายตัวทางชีวภาพ", "Compostable Plastics", "ISO 17088:2012 Specifications for compostable plastics",
         "GR.PCB.11 General term and conditions for the Certification of Specifications for compostable plastics "
         "ISO 17088:2012", "rubber_plastics")],
    "23-CB0019": [
        ("กระดาษ", "Paper", "TGL-8-R2-11", "Green Label (Thailand Environment Institute); ISO/IEC 17067:2013 Type 3",
         "wood_paper"),
        ("กระดาษพิมพ์และเขียน (ยกเว้นกระดาษพิมพ์และกระดาษเขียนแบบเคลือบผิว)",
         "Printing and Writing paper (Except Coated Printing and Writing Paper)", "TGL-8/1-15",
         "Green Label (Thailand Environment Institute); ISO/IEC 17067:2013 Type 3", "wood_paper"),
        ("กระดาษอนามัย", "Sanitary Paper", "TGL-8/2-19",
         "Green Label (Thailand Environment Institute); ISO/IEC 17067:2013 Type 3", "wood_paper")],
    "24-CB0019": [
        ("เครื่องโทรคมนาคมและอุปกรณ์: เครื่องวิทยุคมนาคมในกิจการเคลื่อนที่ทางบก ย่านความถี่ VHF/UHF",
         "Telecommunications equipment to be used in land mobile service within the VHF/UHF frequency band for "
         "analogue speech communications", "กสทช. มท. 1001-2564 (NBTC TS 1001-2564)",
         "ISO/IEC 17067:2013 Type 1a", "ict"),
        ("เครื่องโทรคมนาคมและอุปกรณ์: เครื่องวิทยุคมนาคม สำหรับคลื่นความถี่ภาคประชาชน",
         "Telecommunications equipment to be used in Citizen Band on frequency ranges 78-79 MHz or 245-247 MHz",
         "กสทช. มท. 1002-2561 (NBTC TS 1002-2561)", "ISO/IEC 17067:2013 Type 1a", "ict")],
    "25-CB0010": [
        ("พอร์ซเลน", "Porcelain (Ceramic Ware in Contact with Food)",
         "มอก. 564-2546 (TIS 564-2546 (2003)); " + CERAMIC_TEST, "R-CB0-01; ISO/IEC 17067:2013 Type 1a",
         "other_manufacturing"),
        ("เออร์เทนแวร์", "Earthenware (Ceramic Ware in Contact with Food)",
         "มอก. 601-2546 (TIS 601-2546 (2003)); " + CERAMIC_TEST, "R-CB0-01; ISO/IEC 17067:2013 Type 1a",
         "other_manufacturing"),
        ("สโตนแวร์", "Stoneware (Ceramic Ware in Contact with Food)", CERAMIC_TEST,
         "R-CB0-01; ISO/IEC 17067:2013 Type 1a", "other_manufacturing")],
}


def main():
    scrape, today = cf.cli(HERE / "tisi_17065")
    raw = json.load(open(scrape / "tisi_17065_raw.json", encoding="utf-8"))
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        valid = VALID.get(reg)
        if valid is None:
            notes.append(f"{reg} ({r['accreditation_no']}) {r['name']}: left out (expired, superseded or no scope; "
                         "see converter docstring)")
            continue
        issued, expiry = valid
        if expiry < today:
            notes.append(f"{reg}: expired {expiry}; left out")
            continue
        b = cf.Body(reg=reg, name=NAMES[reg], country="Thailand", phone=r.get("phone") or "",
                    email=r.get("email") or "", website=r.get("website") or "",
                    address=ADDRESSES.get(reg, r.get("address") or ""), issued=issued, expiry=expiry,
                    proof_url=r["detail_url"], source_url=URL)
        for th, en, norm, sch_text, ind in LINES[reg]:
            sch = cf.scheme_of(f"{en} {norm}")
            # the ISO/IEC 17067 scheme type is not imported (and the common module drops lines that only cite it)
            sch_text = re.sub(r";?\s*ISO/IEC 17067:2013 Type [\w ,]+", "", sch_text).strip("; ")
            b.lines.append(cf.Line(product_text=th, product_text_en=en, normative_docs=norm, scheme_text=sch_text,
                                   scheme=sch, industry=None if sch else ind))
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "tisi_17065_review.md", today,
           sources_extra="TISI / NSC register (certify CB, standard ISO/IEC 17065). Bilingual scope annexes transcribed "
                         "(Thai product_text, the annex's English in product_text_en); validity from the annexes.",
           pre_notes=notes)


if __name__ == "__main__":
    main()
