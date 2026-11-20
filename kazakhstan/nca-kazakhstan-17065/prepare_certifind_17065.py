"""Convert the NCA (Kazakhstan) ISO/IEC 17065 scrape into certifind/data/nca-kazakhstan-17065/.

Usage: python prepare_certifind_17065.py [scrape dir] [--today YYYY-MM-DD]
Input:  nca_17065/nca_17065_raw.json (register rows), nca_17065/annex_records.json (extract_annex_tables.py: one record
        per annex table entry, columns kept apart) and annex_transcription.csv (build_transcription.py: annexes the
        table reader cannot use).
Rules:  one body per register number (the NaCEkS regional branches and the Caspian centre's Almaty branch share one
        certificate: their lines are merged into the main row's accreditation). product_text = object name,
        normative_docs = standards column, scheme_text = the technical regulations (TR TS / TR EAEU nnn/yyyy) cited
        in it. TNVED/KPVED codes and the conformity-assessment scheme number (ISO/IEC 17067 type) have no column and
        are not imported. Technical regulations of the Customs Union / EAEU are regional schemes: text only.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import certifind_17065_common as cf  # noqa: E402

AB, FOLDER, MS = "NCA", "nca-kazakhstan-17065", "nca-kazakhstan"
URL = "http://77.245.104.163/index.php?do=web_search"

# English names (register names are Russian; the MS dataset uses transliterated / translated Latin names).
NAMES = {
    "KZ.O.01.0317": "National Center of Expertise and Certification JSC (NaCEkS)",
    "KZ.O.03.E1311": "Product Safety LLP", "KZ.O.03.0033": "Palata LLP", "KZ.O.05.E1030": "AlemSert LLP",
    "KZ.O.08.0309": "Zhambyl Standart Group for Standardization, Certification and Metrology LLP",
    "KZ.O.10.0562": "Research Centre Ugol LLP", "KZ.O.10.0495": "GIO TRADE LLP",
    "KZ.O.13.0193": "Caspian Certification Centre LLP", "KZ.O.19.0073": "Certification Centre Sapa Standart KZ LLP",
    "KZ.O.02.2917": "TelSet LLP", "KZ.O.02.0995": "Cosmomed LLP", "KZ.O.02.0774": "KAZ-Certificate LLP",
    "KZ.O.02.0802": "QS Azia Sertik LLP", "KZ.O.02.0683": "STD products LLP", "KZ.O.02.0410": "Kranenergo LTD LLP",
    "KZ.O.02.0042": "Nutritest LLP", "KZ.O.02.0972": "NurAs-PRO LLP", "KZ.O.02.0507": "OTAN-SECURITY LLP",
    "KZ.O.02.0139": "Sapa Intersystem LLP", "KZ.O.02.0525": "T-Standart LLP", "KZ.O.02.0986": "TDA SERVICE LLP",
    "KZ.O.02.0651": "TEKS LLP", "KZ.O.02.0851": "Product Quality Testing Centre LLP",
    "KZ.O.02.0551": "Product Conformity Confirmation Centre LLP",
    "KZ.O.02.0937": "Centre of Standardization and Certification LLP", "KZ.O.02.E1186": "Infocert LLP",
    "KZ.O.02.0985": "KazSertik-A LLP", "KZ.O.02.E0890": "Scientific and Technical Engineering Centre LLP",
    "KZ.O.02.E1097": "Certification and Inspection CERINS LLP", "KZ.O.02.0441": "Oilsert International LLP",
    "KZ.O.02.0361": "KAZEXPOAUDIT LLP",
    "KZ.O.02.0610": "Independent Centre for Examination of Petroleum Products ORGANIC LLP",
    "KZ.O.02.0973": "Centre of Quality in Transport LLP", "KZ.O.02.E0533": "KAZAUTOCERT LLP",
    "KZ.O.02.E0968": "SertSoft LLP", "KZ.O.02.E0578": "Erkin Talgam LLP",
    "KZ.O.02.2969": "Scientific and Engineering Centre for Industrial Safety LLP",
    "KZ.O.02.E0545": "Centre for Certification of Products and Services LLP",
    "KZ.O.02.E0446": "Centre for Examination, Testing and Certification of Pyrotechnic Products (CEkSPI) LLP",
    "KZ.O.02.E0964": "Expert and Certification Centre of Explosive Materials (ESCVM) LLP",
    "KZ.O.02.E1430": "Elesar LLP", "KZ.O.01.2941": "Nuralem-Kurylys LLP",
    "KZ.O.01.0922": "Kazakhstan Agrarian Expertise JSC",
    "KZ.O.01.0990": "Kazakhstan Centre for Certification in Railway Transport (KazCSZhT) LLP",
    "KZ.O.01.0984": "Centre for Certification and Expertise TEST LLP", "KZ.O.01.0628": "Firma Zhanabet LLP",
    "KZ.O.01.0934": "Analytik AF LLP", "KZ.O.01.0841": "Firma Torgovaya Palata LLP",
    "KZ.O.01.E0959": "Baltic Control KZ Certification LLP", "KZ.O.01.E1015": "QAZAQ BIO CONTROL LLP",
    "KZ.O.01.E0937": "Kazliftconsulting LLP",
    "KZ.O.02.2841": "Sertifikacijas un testesanas centrs LLC, branch in Kazakhstan",
    "KZ.O.01.3071": "Eurasian Voluntary Certification System for Accessibility of Infrastructure LLP",
    "KZ.O.16.0730": "Turan Business Group LLP",
}
MAIN_ROW = {"KZ.O.01.0317": "68", "KZ.O.13.0193": "18"}  # register row that carries the body's own contacts

# ------------------------------------------------------------------ industries (Russian annex text)
TR_INDUSTRY = {"001": "transport_equipment", "002": "transport_equipment", "003": "transport_equipment",
               "004": "electrical", "005": "rubber_plastics", "007": "other_manufacturing", "008": "other_manufacturing",
               "009": "chemicals", "010": "machinery", "011": "machinery", "012": "electrical", "013": "energy",
               "014": "construction", "015": "agriculture", "016": "energy", "017": "textiles",
               "018": "transport_equipment", "019": "other_manufacturing", "020": "electrical", "021": "food",
               "022": "food", "023": "food", "024": "food", "025": "other_manufacturing",
               "027": "food", "028": "chemicals", "029": "food", "030": "chemicals", "031": "machinery",
               "032": "machinery", "033": "food", "034": "food", "035": "other_manufacturing"}
RU_WORDS = [(re.compile(p, re.I), ind) for p, ind in [
    (r"туристск|гостиниц", "tourism"),
    (r"медицинск|лекарств|фармац|вакцин", "health"),
    (r"экспедитор|логистик|складск|перевозк|грузов", "trade_logistics"),
    (r"программн|телекоммуник|коммутацион|радиоэлектронн|информационн\w* (систем|безопасност)|связи\b|сетей", "ict"),
    (r"органическ", "agriculture"),
    (r"косметик|парфюмер|моющ|удобрен|пестицид|лакокрасоч|краск|химическ|реагент|смазоч|смазк|взрывчат|пиротехн|"
     r"кислот|клей|растворител", "chemicals"),
    (r"пластмасс|полимерн|резин|упаковк|\bтара\b|пластик|пленк|полиэтилен", "rubber_plastics"),
    (r"бензин|дизельн|топлив|нефт|мазут|газ горюч|газов|сжиженн|уголь|энерг", "energy"),
    (r"колесн|автотранспорт|транспортн\w* средств|вагон|локомотив|железнодорожн|автомобил|прицеп|мотоцикл|"
     r"судн|воздушн|подвижн\w* состав|шин[аы]\b|покрышк|автобус", "transport_equipment"),
    (r"трактор|станк|оборудовани|машин|лифт|кран|подъемн|котел|котл|сосуд|давлен|аттракцион|насос|компрессор|"
     r"двигател|клапан|арматур", "machinery"),
    (r"электр|кабел|провод|светильник|лампа|лампы|аккумулятор|батаре|трансформатор|бытов\w* прибор|"
     r"низковольтн|электромагнитн|выключател|розетк", "electrical"),
    (r"металл|сталь|стальн|чугун|прокат|\bтрубы\b|проволок|швеллер|балк", "metals"),
    (r"строительн|бетон|цемент|кирпич|плитк|стекл|\bокн|двер|кровельн|утеплител|трубопровод|песок|щебень|гипс|"
     r"асфальт|битум|дорожн|керамическ|известь|цеолит|смес[иь]|раствор", "construction"),
    (r"древес|лесоматериал|бумаг|картон|пиломатериал|фанер|\bдсп\b|\bдвп\b", "wood_paper"),
    (r"текстил|одежд|обув|кожа|кожев|трикотаж|ткан|швейн|мех\b|белье|чулочн|носк", "textiles"),
    (r"игруш|мебел|детск|индивидуальной защиты|табак|ювелир|посуд|изделия бытов", "other_manufacturing"),
    (r"пищев|мясо|мясн|молок|молоч|рыб|масл[оаи]|сыр\b|сыры|хлеб|сахар|мука|муки|круп|напит|вода|воды|\bсок|"
     r"кондитерск|консерв|яйц|\bмед\b|чай|кофе|соль|специи|продукт\w* питания|корм|колбас|мясопродукт|"
     r"птицы|плод|овощ|фрукт|макарон|шоколад|какао|вино|водка|пиво|алкогол|минеральн", "food"),
    (r"зерно|зерна|семен|растени|животн|сельскохозяйствен|удобрени|скот|посадочн", "agriculture"),
    (r"услуг", "professional"),
    # broad rules appended last so they do not override the specific ones above
    (r"ферро|концентрат|жесть|болт|гайк|шайб|графит|алюмини|сплав|руд[аы]", "metals"),
    (r"натри|кали[яй]|ацетон|хлор|карбид|кальци|сода|перекис|ванилин|красител|эмульгатор|стабилизатор|усилител|"
     r"грунтовк|герметик|мыло|бытовой химии|духи|казеин|альбумин|декстрин|фосфат|магнез|кислот|спирт", "chemicals"),
    (r"головн\w* убор|кожгалантере|портфел|ранц|рюкзак|сумк|перчатк|шапк", "textiles"),
    (r"пшениц|ячмен|тритикале|хлопчатник|рожь|овес|нут|чечевиц|горох|подсолнечник|кукуруз|рис|лён|лен|"
     r"сорго|просо|гречих", "agriculture"),
    (r"завтраки|воск|крахмал|патока|шоколад|ароматизатор|подсластител|загуститель", "food"),
    (r"шпал|брус|деревян", "wood_paper"),
    (r"камни|камень|доломит|известняк|вермикулит|бортов|плит|блок", "construction"),
    (r"велосипед", "transport_equipment"),
]]
TR = re.compile(r"ТР\s*(ТС|ЕАЭС)\s*(\d{3})\s*/\s*(\d{4})")


def industry(product, norm, tr_nums):
    for rx, ind in RU_WORDS:
        if rx.search(product):
            return ind
    for n in tr_nums:
        if n in TR_INDUSTRY:
            return TR_INDUSTRY[n]
    for rx, ind in RU_WORDS:
        if rx.search(norm):
            return ind
    return ""


# ------------------------------------------------------------------ contacts
def first_phone(raw):
    for seg in re.split(r"[,;]", raw or ""):
        seg = re.sub(r"\s\((?:вн\.?|доб\.?)?\s*\d{1,5}\)\s*$|вн\.?\s*\d+|факс.*", "", seg, flags=re.I)
        d = re.sub(r"\D", "", seg)
        if len(d) == 11 and d[0] in "78":
            d = d[1:]
        if len(d) == 10:
            return f"+7 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}"
    return ""


def address_of(block):
    a = re.split(r"\s+(?:тел\b|тел\.|Телефон|тел/)", block)[0]
    a = re.sub(r"[\w.+-]+@[\w.-]+.*$", "", a)
    m = re.search(r"[Фф]актический адрес:\s*(.+)$", a)
    if m:
        a = m.group(1)
    else:
        a = re.sub(r"^(Юридический[^:]*:)\s*", "", a)
    a = re.split(r",?\s*юр\. адрес:", a)[0]
    return cf.clean(a).strip(" ,;")


def main():
    scrape, today = cf.cli(HERE / "nca_17065")
    raw = json.load(open(scrape / "nca_17065_raw.json", encoding="utf-8"))
    recs = json.load(open(scrape / "annex_records.json", encoding="utf-8"))
    manual = {}
    for r in cf.rd(HERE / "annex_transcription.csv"):
        manual.setdefault(r["reg"], []).append(r)
    notes, bodies, noprod = [], {}, {}
    by_reg = {}
    for r in raw:
        by_reg.setdefault(r["registration_no"], []).append(r)
    unread = recs.pop("_unread")
    for reg, rows in by_reg.items():
        main_id = MAIN_ROW.get(reg)
        rows.sort(key=lambda x: (x["id"] != main_id, int(x["id"])))
        m = rows[0]
        if m["status"] != "Active":
            notes.append(f"{reg}: register status {m['status']}; left out")
            continue
        block = m["address"]
        phone = first_phone(m["phone"]) or first_phone(" ".join(re.findall(r"(?:Телефон|тел\.?)[^@]*", block)))
        em = next((e for e in re.split(r"[;,]\s*", m["email"]) if e and e.isascii()), "")
        if m["email"] and not em:
            notes.append(f"{reg}: e-mail '{m['email']}' has garbled characters in the register; left empty")
        if m["email"] and not m["email"].isascii():
            em = ""
        web = cf.website(next(iter(re.split(r"[;,\s]+", m["website"])), ""))
        b = cf.Body(reg=reg, name=NAMES[reg], country="Kazakhstan", phone=phone, email=em, website=web,
                    address=address_of(block), issued=cf.iso_date(m["issued"]), expiry=cf.iso_date(m["expiry"]),
                    proof_url=m["annex_urls"][0] if m["annex_urls"] else URL, source_url=URL)
        if not phone:
            notes.append(f"{reg} {NAMES[reg]}: no usable phone number; left empty")
        if len(rows) > 1:
            notes.append(f"{reg}: {len(rows)} register rows (main row + branches) merged into one body and accreditation; "
                         f"contacts of row {m['id']}")
        for row in rows:
            for fid, name in zip([u.rsplit("=", 1)[1] for u in row["annex_urls"]], row["annex_names"]):
                src = f"annex:{row['id']}:{fid}:{name[:80]}"
                for rec in recs.get(src, []):
                    prod, norm, svc = cf.clean(rec["product"]), cf.clean(rec["norm"]), cf.clean(rec["service"])
                    if svc and prod:
                        prod = f"{prod}; {svc}"
                    prod = prod or svc
                    trs = []
                    for kind, num, yr in TR.findall(norm):
                        t = f"ТР {kind} {num}/{yr}"
                        if t not in trs:
                            trs.append(t)
                    if not prod or re.fullmatch(r"[\d\sдДсСcC,;.\-–]*", prod):
                        noprod[reg] = noprod.get(reg, 0) + 1  # column shifted / blank cells: no product text
                        continue
                    nums = [re.search(r"(\d{3})", t).group(1) for t in trs]
                    b.lines.append(cf.Line(product_text=prod, normative_docs=norm, scheme_text="; ".join(trs), scheme="",
                                           industry=industry(prod, norm, nums)))
        for r in manual.get(reg, []):
            sch = "" if re.match(r"(?i)^(сх\.|схема)", r["scheme_text"]) else r["scheme_text"]
            b.lines.append(cf.Line(product_text=r["product_text"], scheme_text=sch, normative_docs=r["normative_docs"],
                                   scheme="", industry=r["industry"]))
        if reg in manual:
            notes.append(f"{reg} {NAMES[reg]}: {len(manual[reg])} lines from annex_transcription.csv "
                         f"({manual[reg][0]['source'][:60]})")
        bodies[reg] = b
    notes.append("KZ.O.01.0317: the register row of the central NaCEkS office says the part of the scope for construction "
                 "products is temporarily invalid since 2024-07-31; the lines are imported as ACTIVE, not flagged one by one")
    for reg, n in sorted(noprod.items()):
        notes.append(f"{reg}: {n} annex table entries without product text (blank or shifted cells) left out")
    # unreadable annexes
    per = {}
    for s in unread:
        per.setdefault(s.split(":")[1], []).append(s)
    id2reg = {r["id"]: r["registration_no"] for r in raw}
    cnt = {}
    for i, l in per.items():
        cnt.setdefault(id2reg[i], [0, 0])
        cnt[id2reg[i]][0] += sum(1 for s in l if s.endswith(".pdf"))
        cnt[id2reg[i]][1] += sum(1 for s in l if not s.endswith(".pdf"))
    for reg, (p, w) in sorted(cnt.items()):
        notes.append(f"{reg}: annexes not imported (no readable table): {p} PDF (broken font encoding), {w} Word")
    cf.run(AB, FOLDER, MS, URL, list(bodies.values()), HERE / "nca_17065_review.md", today,
           sources_extra="NCA register of accredited bodies (activity filter 1 = OPS P / OPS PiU, ISO/IEC 17065), "
                         "retrieved from the Word annexes of each accreditation. 70 register rows = 54 accreditation "
                         "numbers (NaCEkS has 16 branch rows, the Caspian Certification Centre 2). Technical "
                         "regulations of the Customs Union / EAEU are regional schemes and stay text "
                         "(scheme_text lists the regulations cited in each line). TNVED codes and the conformity "
                         "assessment scheme number are not imported (no column). Not imported: 83 PDF annexes (text layer with a broken "
                         "font encoding) and about 97 Word annexes without a readable table (see nca_17065_review.md); two "
                         "scanned annexes were read from the page images (annex_transcription.csv).", pre_notes=notes)


if __name__ == "__main__":
    main()
