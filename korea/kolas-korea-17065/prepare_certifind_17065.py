"""Convert the KOLAS (Korea) ISO/IEC 17065 scrape into certifind/data/kolas-south-korea-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD] [--debug REG...]
Input (scrape_kr_kolas_17065.py): kolas_17065/kolas_17065_raw.json (knab.go.kr product certification register,
25 bodies) and kolas_17065/certificates/<KPCxxx>_{kr,en}.pdf (accreditation certificate + scope annex).

Lines come from the ENGLISH certificate annex (KOLAS issues it alongside the Korean one; the Korean and English
tables cannot be paired row by row reliably, so product_text holds the English text and product_text_en is
left empty). Annex table: Group | Products | Category of product | Standard | (Site) | Scheme type.
One line per category row: product_text = "<products>: <category>", normative_docs = standard column (wrapped
continuation rows merged). The scheme column (ISO/IEC 17067 type) is dropped. scheme_text = the "Certification
Scheme:" heading in force on the page. Body names and addresses are the English ones printed on page 1 of the
English certificate (a scan, read by eye 2026-11-20: NAMES / ADDRESSES).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "KOLAS", "kolas-south-korea-17065", None
URL = "https://www.knab.go.kr/usr/inf/srh/InfoProductInsttSearchList.do"
NAMES = {
    "KPC002": "Korea Testing Certification Institute", "KPC004": "Korea Gas Safety Corporation",
    "KPC005": "Korea Testing and Research Institute", "KPC006": "Korea Electrotechnology Research Institute",
    "KPC010": "KATRI Testing & Research Institute", "KPC011": "FITI Testing & Research Institute",
    "KPC013": "Korea Testing Laboratory", "KPC017": "Korea Conformity Laboratories",
    "KPC020": "Korea Electrical Manufacturers Cooperative", "KPC025": "KOTITI Testing & Research Institute",
    "KPC027": "Korea Railroad Research Institute", "KPC028": "Korea Mechanical Engineering Association",
    "KPC029": "KIEL Institute", "KPC032": "Korean Register of Shipping",  # certificate: "Korean Register"
    "KPC033": "Busan Technopark", "KPC036": "Korea Rolling Stock Technical Corporation",
    "KPC037": "Korea Industrial Safety Association", "KPC038": "Konkuk Eco Certification Agency",
    "KPC039": "SZU Korea", "KPC041": "Dt&C Co., Ltd.", "KPC042": "DNV Business Assurance Korea",
    "KPC043": "Korean Foundation for Quality", "KPC044": "RST Co., Ltd",
    "KPC045": "Korea Eco-Friendly Agro-Fisheries Research Center",
    "KPC046": "Yangpyeong Environment-Friendly Certification Center",
}
ADDRESSES = {
    "KPC002": "22, Heungan-daero 27beon-gil, Gunpo-si, Gyeonggi-do, Republic of Korea",
    "KPC004": "1390, Wonjung-ro, Maengdong-myeon, Eumseong-gun, Chungcheongbuk-do, Rep. of Korea (27738)",
    "KPC005": "98, Gyoyukwon-ro, Gwacheon-si, Gyeonggi-do, Republic of Korea",
    "KPC006": "12, Jeongiui-gil, Seongsan-gu, Changwon-si, Gyeongsangnam-do, Republic of Korea",
    "KPC010": "51, Wangsan-ro, Dongdaemun-gu, Seoul, Republic of Korea",
    "KPC011": "79, Magokjungang8-ro, 3-gil, Gangseo-gu, Seoul, Republic of Korea",
    "KPC013": "87, Digital-ro 26-gil, Guro-gu, Seoul, Republic of Korea",
    "KPC017": "7, Nambusunhwan-ro 319-gil, Seocho-gu, Seoul, Republic of Korea",
    "KPC020": "338, Yatap-ro, Bundang-gu, Sungnam-city, Gyeonggi-do, Republic of Korea",
    "KPC025": "48, Gwacheon-daero 7na-gil, Gwacheon-si, Gyeonggi-do, Republic of Korea",
    "KPC027": "176, Cheoldo bangmulgwan-ro, Uiwang, Gyeonggi-do, Republic of Korea",
    "KPC028": "150 Yeongdeungpo-ro, Yeongdeungpo-gu, Seoul",
    "KPC029": "Netzero solution Center 8F, 487 Sosa-ro, Wonmi-gu, Bucheon-si, Gyeonggi-do, 14560 Republic of Korea",
    "KPC032": "36, Myeongji ocean city 9-ro, Gangseo-gu, Busan, Republic of Korea",
    "KPC033": "55 Noksansandan 382-ro 14 beon-gil, Gangseo-gu, Busan, Republic of Korea",
    "KPC036": "2174, Seobu-ro, Jangan-gu, Suwon-si, Gyeonggi-do, Republic of Korea",
    "KPC037": "4F Suite 405, 406, 63 Gongwon-ro, Guro-gu, Seoul, Republic of Korea",
    "KPC038": "K10 Konkuk University Glocal Campus 268, Chungwon-daero, Chungju-si, Chungcheongbuk-do, Republic of Korea",
    "KPC039": "20F DMC Ian Sangam Office B/D, 361, World Cup buk-ro, Mapo-gu, Seoul, Republic of Korea",
    "KPC041": "42, Yurim-ro 154beon-gil, Cheoin-gu, Yongin-si, Gyeonggi-do, Republic of Korea",
    "KPC042": "1 Jong-ro, Jongno-gu, Seoul, Republic of Korea",
    "KPC043": "78 Samjeon-ro, Songpa-gu, Seoul, Republic of Korea",
    "KPC044": "401 Yangcheon-ro, Gangseo-gu, Seoul, Republic of Korea",
    "KPC045": "205-1 Jungmajungang-ro, Gwangyang-si, Jeollanam-do, Republic of Korea",
    "KPC046": "3rd floor, 22 Nongeopgisulsenteo-gil, Yangpyeong-eup, Yangpyeong-gun, Gyeonggi-do",
}
GROUP = re.compile(r"^\d\d\.\d{3}\b")
# IT / audio-video hardware: the common keyword table reads "information ..." as education
TEXTILE = re.compile(r"textile|apparel|wearing|footwear|leather", re.I)  # group (KSIC) title
IT_EQUIPMENT = re.compile(r"information technology equipment|information and communication|office equipment|audio|"
                          r"video|telecommunication|communication equipment|electromagnetic|power supply", re.I)
SCHEME_HEAD = re.compile(r"Certification Scheme\s*:\s*(.+)", re.I)


def page_schemes(pdf: Path) -> list[str]:
    """The certification scheme heading in force on each page (carried over from earlier pages)."""
    import pymupdf
    out, cur = [], ""
    for page in pymupdf.open(pdf):
        heads = [cf.clean(m) for m in SCHEME_HEAD.findall(page.get_text())]
        if heads:
            cur = heads[0]
        out.append(cur)
        if heads:
            cur = heads[-1]
    return out


def annex_lines(pdf: Path) -> list[cf.Line]:
    import pdfplumber
    schemes = page_schemes(pdf)
    lines, group, products, last = [], "", "", None
    with pdfplumber.open(pdf) as doc:
        for pno, page in enumerate(doc.pages):
            for table in page.extract_tables():
                cols = None
                for row in table:
                    cells = [cf.clean(c) for c in row]
                    if any(c.lower().startswith("category of product") for c in cells):
                        low = [c.lower() for c in cells]
                        cols = {k: next((i for i, c in enumerate(low) if c.startswith(k)), None)
                                for k in ("group", "products", "category", "standard")}
                        continue
                    if not cols or cols["category"] is None:
                        continue
                    get = lambda k: cells[cols[k]] if cols[k] is not None and cols[k] < len(cells) else ""  # noqa
                    g, p, c, s = get("group"), get("products"), get("category"), get("standard")
                    if g:
                        group = g
                    if p:
                        products = p
                    if c:
                        text = f"{products}: {c}" if products and products != c else c
                        last = cf.Line(product_text=text, normative_docs=s, scheme_text=schemes[pno])
                        blob = f"{group} {products} {c}"
                        last.industry = ("electrical" if IT_EQUIPMENT.search(blob) else
                                         "textiles" if TEXTILE.search(group) else
                                         "rubber_plastics" if re.search(r"\bplastic", blob, re.I) else
                                         cf.industry_of(blob)) or None
                        lines.append(last)
                    elif last is not None:  # wrapped row: continues the previous line
                        if p and not s:
                            last.product_text = f"{last.product_text} {p}"
                        if s:
                            last.normative_docs = f"{last.normative_docs} {s}".strip()
    for ln in lines:
        sch = cf.scheme_of(f"{ln.product_text} {ln.normative_docs} {ln.scheme_text}")
        if sch:
            ln.scheme, ln.industry = sch, None
    return lines


def main():
    scrape, today = cf.cli(HERE / "kolas_17065")
    debug = sys.argv[sys.argv.index("--debug") + 1:] if "--debug" in sys.argv else []
    raw = json.load(open(scrape / "kolas_17065_raw.json", encoding="utf-8"))
    notes, bodies = [], []
    for r in raw:
        reg = r["registration_no"]
        b = cf.Body(reg=reg, name=NAMES.get(reg, r["name"]), country="South Korea", phone=r.get("phone") or "",
                    email=r.get("email") or "", website=r.get("website") or "",
                    address=ADDRESSES.get(reg, r.get("address") or ""), issued=r["issued"], expiry=r["expiry"],
                    proof_url=(r["annex_urls"] or [URL])[-1], source_url=URL)
        if reg not in NAMES:
            notes.append(f"{reg}: no English name read; Korean register name kept")
        pdf = scrape / "certificates" / f"{reg}_en.pdf"
        b.lines = annex_lines(pdf) if pdf.exists() else []
        if not b.lines:
            notes.append(f"{reg} {b.name}: no table rows read from the English annex")
        if reg in debug:
            for ln in b.lines:
                print(reg, "|", ln.scheme or ln.industry, "|", ln.product_text[:70], "|", ln.normative_docs[:60])
        bodies.append(b)
    cf.run(AB, FOLDER, MS, URL, bodies, HERE / "kolas_17065_review.md", today,
           sources_extra="Register knab.go.kr, product certification bodies (제품인증기관, code 07). Lines from the "
                         "English scope annex of each accreditation certificate (category rows; standard column in "
                         "normative_docs; scheme heading in scheme_text; ISO/IEC 17067 scheme type dropped). English "
                         "names and addresses read from page 1 of the English certificate.", pre_notes=notes)


if __name__ == "__main__":
    main()
