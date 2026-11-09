#!/usr/bin/env python3
"""Find website, phone and email for the DAkkS bodies from their own websites.

For each body in the dataset's bodies.csv: candidate domains are built from the name
(e.g. "AGQS GmbH" -> agqs.de, agqs.com), or taken from contacts_overrides.csv when known;
the homepage is accepted only if it names the body. Phone and email come from the site's
Impressum (German law requires one), else from the homepage. Output: contacts.csv
(registration_no, website, phone, email, how) next to this script; nothing is guessed when
no site matches.

    python find_contacts.py <dataset folder>
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests

HERE = Path(__file__).resolve().parent
# Fields checked by hand and found wrong (group or foreign site, data-protection officer,
# domain-holder page): registration_no -> fields to leave empty.
REJECT = {
    "D-ZM-16074": {"phone"}, "D-ZM-18402": {"phone"}, "D-ZM-16021": {"phone"},
    "D-ZM-19630": {"email"}, "D-ZM-16104": {"email"}, "D-ZM-17751": {"phone"},
    "D-ZM-14530": {"website", "phone", "email"}, "D-ZM-16012": {"website", "phone", "email"},
}
# Same certification centre (ccSec) as D-ZM-18926.
SAME_AS = {"D-ZM-23393": "D-ZM-18926"}
UA = {"User-Agent": "CertiFind contact lookup (one request per page)"}
LEGAL = {"gmbh", "mbh", "ag", "e", "v", "ev", "kg", "co", "gbr", "ltd", "sa", "und", "für", "fur",
         "der", "die", "des", "von", "zur", "gesellschaft", "deutsche", "deutschen", "mit",
         "beschränkter", "haftung", "zertifizierung", "zertifizierungsgesellschaft",
         "zertifizierungsstelle", "umweltgutachter", "umweltgutachterorganisation", "certification",
         "cert", "germany", "deutschland", "institut", "international", "services", "service"}
PHONE = re.compile(r"(?:Tel(?:efon)?\.?|Phone|Fon|T)\s*[:.]?\s*((?:\+|00)?[\d][\d\s()/.\-]{6,22}\d)", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)


def ascii_slug(s: str) -> str:
    s = s.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
    s = s.replace("Ü", "Ue").replace("Ö", "Oe").replace("Ä", "Ae")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def candidates(name: str) -> list[str]:
    words = [w for w in re.split(r"[^\w-]+", ascii_slug(name)) if w]
    core = [w for w in words if w.strip("-") not in LEGAL]
    if not core:
        core = words[:1]
    stems = []
    first = core[0].strip("-")
    stems += [first, first.replace("-", "")]
    if len(core) > 1:
        two = core[0] + core[1]
        stems += [two.replace("-", ""), f"{core[0]}-{core[1]}".strip("-")]
    # name words that stand for the brand, e.g. "TÜV NORD CERT" -> tuev-nord
    raw = [w for w in words]
    if len(raw) > 2:
        stems += [f"{raw[0]}-{raw[1]}", raw[0] + raw[1]]
    out = []
    for st in dict.fromkeys(stems):
        if len(st) >= 3:
            out += [f"https://www.{st}.de", f"https://www.{st}.com", f"https://www.{st}.eu"]
    return out


def fetch(url: str) -> tuple[str, str] | None:
    try:
        r = requests.get(url, headers=UA, timeout=12, allow_redirects=True)
        if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
            r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
            return r.url, r.text
    except requests.RequestException:
        pass
    return None


def text_of(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    t = re.sub(r"<[^>]+>", " ", html)
    t = t.replace("&nbsp;", " ").replace("&#64;", "@").replace("&amp;", "&")
    t = re.sub(r"\s*\[(?:at|ät)\]\s*|\s*\((?:at)\)\s*", "@", t, flags=re.I)
    return re.sub(r"[ \t]+", " ", t)


def names_body(text: str, name: str, loose: bool = False) -> bool:
    """The page must name the body: its first key word (brand) plus, unless `loose`, a second."""
    key = [w for w in re.split(r"[^\w]+", name.lower()) if len(w) > 2 and w not in LEGAL]
    low = ascii_slug(text)
    hits = [w for w in key[:3] if ascii_slug(w) in low]
    if not key:
        return loose and not re.search(r"domain (?:kaufen|for sale|parking)|domainname", low)
    if key[0] not in hits:
        return False
    return loose or len(hits) >= min(2, len(key[:3]))


def contacts(base: str, html: str) -> tuple[str, str, str]:
    links = re.findall(r'href="([^"]+)"', html)
    imp = next((l for l in links if re.search(r"impressum|imprint|legal-notice", l, re.I)), None)
    pages = []
    if imp and (p := fetch(urljoin(base, imp))):
        pages.append(("impressum", text_of(p[1]), p[1]))
    pages.append(("homepage", text_of(html), html))
    for how, t, raw in pages:
        mails = [m for m in EMAIL.findall(t) + re.findall(r"mailto:([^\"?]+)", raw)
                 if not re.search(r"\.(png|jpg|gif|svg|webp)$|example|sentry|wixpress|@2x", m, re.I)]
        phone = PHONE.search(t)
        if mails or phone:
            return (phone.group(1).strip() if phone else ""), (mails[0] if mails else ""), how
    return "", "", ""


def intl(phone: str) -> str:
    if len(re.sub(r"\D", "", phone)) < 8:
        return ""
    p = re.sub(r"[()/.\-]", " ", phone)
    p = re.sub(r"\s+", " ", p).strip()
    if not re.match(r"(\+|0)", p):
        return ""
    if p.startswith("00"):
        p = "+" + p[2:]
    elif p.startswith("0"):
        p = "+49 " + p[1:]
    return re.sub(r"^\+49 0", "+49 ", p)


def lookup(body: dict, override: str | None) -> dict:
    urls = override.split() if override else candidates(body["name"])
    for url in urls:
        got = fetch(url)
        if not got:
            continue
        final, html = got
        if not names_body(text_of(html), body["name"], loose=bool(override)):
            continue
        phone, email, how = contacts(final, html)
        site = re.match(r"https?://[^/]+", final).group(0)
        return {"registration_no": body["registration_no"], "website": site,
                "phone": intl(phone) if phone else "", "email": email, "how": how or "site only"}
    return {"registration_no": body["registration_no"], "website": "", "phone": "", "email": "",
            "how": "not found"}


def main() -> None:
    dataset = Path(sys.argv[1])
    with open(dataset / "bodies.csv", encoding="utf-8") as f:
        bodies = list(csv.DictReader(f))
    overrides = {}
    ov = HERE / "contacts_overrides.csv"
    if ov.exists():
        with open(ov, encoding="utf-8") as f:
            overrides = {r["registration_no"]: r["website"] for r in csv.DictReader(f)}
    todo = [b for b in bodies if b["country"] == "Germany"]
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda b: lookup(b, overrides.get(b["registration_no"])), todo))
    by_no = {r["registration_no"]: r for r in rows}
    for r in rows:
        if r["registration_no"] in SAME_AS and not r["website"]:
            src = by_no[SAME_AS[r["registration_no"]]]
            r.update({k: src[k] for k in ("website", "phone", "email")}, how="same centre")
        for field in REJECT.get(r["registration_no"], ()):
            r[field] = ""
        r["phone"] = re.sub(r"\s+", " ", r["phone"])
    with open(HERE / "contacts.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["registration_no", "website", "phone", "email", "how"],
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    found = sum(r["website"] != "" for r in rows)
    print(f"{found}/{len(rows)} websites found; {HERE / 'contacts.csv'}")


if __name__ == "__main__":
    main()
