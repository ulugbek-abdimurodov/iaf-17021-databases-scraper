"""Shared website check for the converters, next to prune_inactive.py.

    sys.path.insert(0, str(<path to this folder>))
    from contact_check import website

website() repairs what registers commonly get wrong and returns "" for anything that
still is not a usable link, printing a warning so it can go in the review file:

    "http://www.https://kompleye.com/" -> "https://kompleye.com/"   (doubled scheme)
    "www.example.org"                  -> "https://www.example.org"
    "https://www.C", "https://AQSRPL"  -> ""   (no domain)
    "https://www.ccs_c.com.cn"         -> ""   (underscore is not allowed in a host name)
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlsplit

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$")


def valid_host(host: str) -> bool:
    labels = host.lower().rstrip(".").split(".")
    return len(labels) >= 2 and all(_LABEL.match(l) for l in labels) and bool(_TLD.match(labels[-1]))


def website(value: str | None, *, context: str = "") -> str:
    v = (value or "").strip()
    if not v:
        return ""
    # A register prefix in front of a URL that already has a scheme.
    v = re.sub(r"^(?:https?://)?(?:www\.)?(?=https?://)", "", v, flags=re.I)
    v = re.sub(r"^(https?://)www\.www\.", r"\1www.", v, flags=re.I)
    if not re.match(r"^https?://", v, re.I):
        v = "https://" + v
    try:
        parts = urlsplit(v)
        host = parts.hostname or ""
        parts.port  # raises on a malformed port
    except ValueError:
        host = ""
    if not valid_host(host) or " " in v:
        print(f"contact_check: dropped website {value!r}{' (' + context + ')' if context else ''}: "
              "not a valid domain", file=sys.stderr)
        return ""
    return v
