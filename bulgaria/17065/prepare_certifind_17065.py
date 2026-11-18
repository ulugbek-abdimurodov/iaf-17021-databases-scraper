"""BAS (Bulgaria, nab-bas.bg) ISO/IEC 17065 register -> CertiFind dataset data/bas-bulgaria-17065/.

Input: nab_product_bodies/bodies.json written by nab_prod_scraper.py. Lines come from the register's scope text
(English when given, else Bulgarian), one line per scope row; a row ending in ':' is a heading and becomes the
scheme_text of the rows under it. Rules: .claude/skills/add-country-17065/SKILL.md in the certifind repo.

    python prepare_certifind_17065.py [--today YYYY-MM-DD]
"""
import argparse, collections, csv, importlib.util, json, re, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent.parent
DATA = DB.parent / "certifind" / "data"


def _load(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


it = _load("accredia_17065", DB / "italy" / "accredia-italy-17065" / "prepare_certifind_17065.py")
de = _load("dakks_17065", DB / "germany" / "prepare_certifind_17065.py")
clean = it.clean

AB_CODE = "BAS"
STD = "ISO/IEC 17065"
ACTIVE = "Валиден сертификат"
BOILER = re.compile(r"^(Scope of Accreditation|To perform (product )?certification|Да извършва сертификация|"
                    r"Обхват на акредитация)", re.I)
BG_WORDS = [(re.compile(p, re.I), i) for p, i in [
    (r"горск|дървесн", "wood_paper"), (r"строителн|бетон|цимент", "construction"),
    (r"храни|храна|фураж|мляко|месо|вино", "food"), (r"селскостопан|растени|животн|пчел", "agriculture"),
    (r"електр", "electrical"), (r"машин|асансьор", "machinery"), (r"играчк", "other_manufacturing"),
]]
# Bulgarian -> Latin (Bulgarian Streamlined System, as on Bulgarian passports)
TR = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюя",
              ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
               "f", "h", "ts", "ch", "sh", "sht", "a", "y", "yu", "ya"]))
FORMS = {"EOOD", "OOD", "AD", "EAD", "ET", "SD", "KD"}
CITIES = {"София": "Sofia", "Пловдив": "Plovdiv", "Варна": "Varna", "Бургас": "Burgas", "Шумен": "Shumen",
          "Русе": "Ruse", "Стара Загора": "Stara Zagora", "Плевен": "Pleven", "Велико Търново": "Veliko Tarnovo",
          "Благоевград": "Blagoevgrad", "Хасково": "Haskovo", "Добрич": "Dobrich", "Сливен": "Sliven"}


def translit(s):
    low = "".join(TR.get(ch, ch) for ch in s.lower())
    return " ".join(w.upper() if w.upper() in FORMS else w[:1].upper() + w[1:] for w in low.split(" "))


def phone(raw):
    t = clean(re.split(r"вътр|,|;", raw or "")[0]).replace("/", " ")
    digits = re.sub(r"\D", "", t)
    if not digits:
        return ""
    if t.startswith("+"):
        return "+" + clean(t[1:])
    if digits.startswith("00359"):
        digits = digits[5:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if digits.startswith("8") or digits.startswith("9"):  # mobile 8x/9x xxx xxxx
        return f"+359 {digits[:3]} {digits[3:6]} {digits[6:]}".strip()
    if digits.startswith("2"):  # Sofia
        return f"+359 2 {digits[1:4]} {digits[4:]}".strip()
    return f"+359 {digits[:2]} {digits[2:]}".strip()


def make(prod, sch_t):
    own = f"{prod} {sch_t}"
    sc = de.scheme_of(own)
    ind = "" if sc else (de.industry_of(own) or next((i for rx, i in BG_WORDS if rx.search(own)), ""))
    return {"scheme": sc or "", "industry": ind, "product_text": prod, "product_text_en": "", "scheme_text": sch_t,
            "normative_docs": "", "standard_refs": it.refs(own), "status": "ACTIVE"}


def lines_of(text, dropped):
    out, head, children = [], "", 0
    for raw in (text or "").split("\n"):
        t = clean(raw).rstrip(";,.").strip()
        if not t:
            continue
        if BOILER.match(t) and ":" in t and t.split(":", 1)[1].strip():
            t = t.split(":", 1)[1].strip()  # "To perform certification of products: <scope>" on one line
        elif BOILER.match(t) or t.startswith("*"):
            dropped["boilerplate / footnote"] += 1
            continue
        if t.endswith(":"):
            if head and children == 0:
                out.append(make(head.rstrip(":"), ""))
            head, children = t, 0
            continue
        out.append(make(t, head.rstrip(":")))
        children += 1
    if head and children == 0:
        out.append(make(head.rstrip(":"), ""))
    return out


def ukey(s):
    s = re.sub(r"\b(ЕООД|ООД|ЕАД|АД|EOOD|OOD|EAD|AD)\b", "", (s or "").upper())
    return re.sub(r"[\W_]+", "", s.casefold())


def read(p):
    return list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()
    out = DATA / "bas-bulgaria-17065"
    out.mkdir(parents=True, exist_ok=True)

    # bas-bulgaria rows by the Bulgarian legal-entity name in brackets
    ms = {}
    for r in read(DATA / "bas-bulgaria" / "bodies.csv"):
        m = re.search(r"\(([^)]*)\)\s*$", r["name"])
        if m:
            ms[ukey(m.group(1))] = r

    recs = json.load(open(HERE / "nab_product_bodies" / "bodies.json", encoding="utf-8"))
    # one record per certificate number: the newest valid one
    best = {}
    review, dropped = [], collections.Counter()
    for e in recs:
        if e["status"] != ACTIVE:
            review.append(f"{e['certificate_number']} {e['legal_entity']}: {e['status']} - left out")
            continue
        k = e["certificate_number"]
        if k in best:
            review.append(f"{k}: several register records, newest (valid from {e['valid_from'] if e['valid_from'] > best[k]['valid_from'] else best[k]['valid_from']}) used")
        if k not in best or iso(e["valid_from"]) > iso(best[k]["valid_from"]):
            best[k] = e

    bodies, accs, ps, reused = [], [], [], []
    for cert, e in sorted(best.items(), key=lambda kv: int(kv[0].split()[0])):
        legal = clean(e["legal_entity"])
        off = (e.get("offices") or [{}])[0]
        if ukey(legal) and ukey(legal) in ms:
            body = dict(ms[ukey(legal)])
            reused.append(f"{cert} {legal} -> bas-bulgaria row '{body['name']}'")
        else:
            body = {"name": f"{translit(legal)} ({legal})", "country": "Bulgaria", "registration_no": "",
                    "phone": phone((off.get("contacts") or {}).get("Телефон", "")),
                    "email": (off.get("emails") or [""])[0], "website": "",
                    "address": CITIES.get(off.get("city", ""), translit(off.get("city", ""))),
                    "source_url": e["url_en"], "verified_at": ""}
        lines = lines_of(e["scope_en"] if clean(e["scope_en"]) else e["scope"], dropped)
        seen, uniq = set(), []
        for l in lines:
            k = (l["product_text"], l["scheme_text"])
            if k not in seen:
                seen.add(k)
                uniq.append(l)
        if not uniq:
            review.append(f"{cert} {legal}: no scope text; left out")
            continue
        if not clean(e["scope_en"]):
            review.append(f"{cert} {legal}: no English scope; Bulgarian text imported")
        bodies.append(body)
        accs.append({"ab_code": AB_CODE, "certificate_number": cert, "body_name": body["name"],
                     "accreditation_standard": STD, "status": "ACTIVE",
                     "issue_date": iso(e["initial_accreditation_date"]) or iso(e["valid_from"]),
                     "expiry_date": iso(e["valid_to"]), "proof_url": e["url_en"]})
        for n, l in enumerate(uniq, 1):
            ps.append({"certificate_number": cert, "line_no": n, **l})

    for nm, c in collections.Counter(b["name"] for b in bodies).items():
        if c > 1:
            review.append(f"DUPLICATE body name {nm} x{c}")
    it.write(out / "bodies.csv", it.ms.BODY_COLUMNS, sorted({b["name"]: b for b in bodies}.values(), key=lambda b: b["name"].casefold()))
    it.write(out / "accreditations.csv", it.ms.ACCREDITATION_COLUMNS, sorted(accs, key=lambda r: r["certificate_number"]))
    it.write(out / "scopes.csv", it.ms.SCOPE_COLUMNS, [])
    it.write(out / "product_scopes.csv", it.PS_COLUMNS, ps)
    with open(HERE / "bas_17065_review.md", "w", encoding="utf-8") as fh:
        fh.write(f"# BAS ISO/IEC 17065 conversion review\n\nGenerated {args.today}: {len(bodies)} bodies, {len(accs)} "
                 f"accreditations, {len(ps)} product lines ({sum(1 for p in ps if p['scheme'])} with a scheme).\n\n")
        fh.write("## Lines left out\n\n" + "".join(f"- {k}: {v}\n" for k, v in dropped.items()))
        fh.write("\n## Body rows reused\n\n" + "".join(f"- {r}\n" for r in reused))
        fh.write("\n## Notes\n\n" + "".join(f"- {r}\n" for r in review))
    print(f"bodies {len(bodies)}, accreditations {len(accs)}, lines {len(ps)} ({sum(1 for p in ps if p['scheme'])} with scheme)")


def iso(d):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


if __name__ == "__main__":
    main()
