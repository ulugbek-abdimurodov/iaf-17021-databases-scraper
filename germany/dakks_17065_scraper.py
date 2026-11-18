#!/usr/bin/env python3
"""Scrape DAkkS product certification bodies (ISO/IEC 17065) and their scope lines.

DAkkS files every ISO/IEC 17065 body under body type "ZE" (Zertifizierungsstelle
für Produkte, Prozesse und Dienstleistungen); accreditation numbers look like
D-ZE-11024-01-01. The annex (Anlage, suffix -01, -02, ...) states the standard
on page 1 ("nach DIN EN ISO/IEC 17065:2013"), which this script checks per annex.

    pip install requests beautifulsoup4 openpyxl pypdf pdfplumber
    python dakks_17065_scraper.py               # crawl + parse
    python dakks_17065_scraper.py --parse-only  # re-parse files already on disk

The crawl, the body/accreditation/document files and the PDF folder layout are
those of dakks_scraper.py (imported, not copied), written to ./dakks_ZE.
This script adds:
    scope_lines.csv        one row per scope line, text verbatim (German as published)
    scope_report.json      scope lines per body, bodies with zero lines, parse issues
    scope_parse.log        the same issues as log lines

Scope line columns:
    registration_no      accreditation number of the annex (D-ZE-11024-01-01)
    page                 PDF page the line starts on
    row_index            running number within the annex
    product_text_raw     table column whose header names products / objects
    scheme_text_raw      column naming the programme / scheme / legal act
    normative_docs_raw   column naming standards / normative documents
    scheme_type_raw      ISO/IEC 17067 scheme type, only when stated
    other_columns_raw    JSON {original header: text}; "Abschnitt" holds the numbered
                         section heading the line sits under, "Spalte N" a column of a
                         table that has no header, "Text" a free-text line,
                         "Bereich" an entry of the page-1 summary list
    source               local PDF path and its URL
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dakks_scraper as ds  # noqa: E402

log = logging.getLogger("dakks17065")

TYPE = "ZE"
SCOPE_COLS = ["registration_no", "page", "row_index", "product_text_raw", "scheme_text_raw",
              "normative_docs_raw", "scheme_type_raw", "other_columns_raw", "source"]

# ------------------------------------------------------------ page cleanup
# Lines DAkkS prints on every annex that are not scope (header, footer, disclaimer).
BOILER_RE = re.compile("|".join([
    r"^Anlage zur Akkreditierungsurkunde\b", r"^Annex to the [Aa]ccreditation [Cc]ertificate\b",
    r"^Gültig ab\s*:", r"^Valid from\s*:", r"^Ausstellungsdatum\s*:", r"^Date of issue\s*:",
    r"\bSeite \d+ von \d+\s*$", r"\bPage \d+ of \d+\s*$",
    r"^Diese Urkundenanlage wurde ausgestellt", r"^Sie gilt nur zusammen mit",
    r"^Der jeweils aktuelle Stand der gültigen", r"^Deutschen Akkreditierungsstelle zu entnehmen",
    r"^This annex .*(issued|digitally sealed)", r"^It is only valid together with",
    r"^The current status of the valid", r"^Deutsche Akkreditierungsstelle\s*$",
    r"^-?\s*Zweitschrift\s*-?$",
    # older layout (until about 2022)
    r"^Diese Urkundenanlage gilt nur zusammen", r"^Ausstellungsdatums wieder\. Der jeweils aktuelle",
    r"^akkreditierter Stellen der Deutschen Akkreditierungsstelle zu entnehmen",
    r"^Gültigkeitsdauer\s*:", r"Abkürzungen\s*:\s*siehe letzte Seite", r"^Die Urkunde samt Urkundenanlage",
    r"^des Geltungsbereiches der Akkreditierung ist", r"^Geltungsbereiches der Akkreditierung ist der Datenbank",
    r"^\(DAkkS\) zu entnehmen", r"^entnehmen\. https?://", r"^Deutsche Akkreditierungsstelle GmbH\s*$",
]))
# End of the page-1 preamble; scope starts after it.
PREAMBLE_END_RE = re.compile(r"Prinzipien der DIN EN ISO 9001\.?\s*$|principles of (DIN EN )?ISO 9001\.?\s*$", re.I)
PREAMBLE_END_FALLBACK_RE = re.compile(r"ausdrücklich bestätigt werden\.?\s*$|explicitly confirmed below\.?\s*$", re.I)
# Older layout: no 9001 sentence before the scope; the scope starts at this line.
SCOPE_START_RE = re.compile(r"^Zertifizierung(en)? von Produkten.*\b(Bereich|Bereichen)\s*:", re.I)
# The ISO 9001 statement paragraph, which the older layout prints after the scope.
STMT_START_RE = re.compile(r"^Die Anforderungen an das Managementsystem in der (DIN EN )?ISO/IEC 17065")
STMT_END_RE = re.compile(r"ISO 9001\.?\s*$")
# Start of the abbreviation list: scope ends there.
TOC_RE = re.compile(r"^(Inhaltsverzeichnis|Table of contents)\s*$", re.I)
TOC_LEADER_RE = re.compile(r"\.{6,}\s*\d+\s*$")
ABBREV_RE = re.compile(r"^(Verwendete|verwendete) Abkürzung|^Abbreviations used", re.I)
STANDARD_RE = re.compile(r"(?:nach|according to)\s+(DIN EN ISO/IEC \d{5}(?::\d{4})?|ISO/IEC \d{5}(?::\d{4})?)")
SECTION_NO_RE = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,4}\.)$")
BULLET_RE = re.compile(r"^[-–•▪●·]$")
SCHEME_TYPE_RE = re.compile(r"\b(?:Programmtyp|Zertifizierungsprogrammtyp|Typ|Type)\s+(1a|1b|2|3|4|5|6)\b")

# Header keyword -> target column. Checked in this order; first hit wins.
HEADER_MAP = [
    ("scheme_type_raw", ("17067", "programmtyp", "schematyp", "scheme type", "programm-typ")),
    ("normative_docs_raw", ("norm", "spezifikation", "prüfgrundlage", "grundlage", "anforderung",
                            "standard", "regelwerk", "specification", "requirement")),
    ("scheme_text_raw", ("programm", "zertifizierungsverfahren", "verfahren", "scheme",
                         "richtlinie", "verordnung", "entscheidung", "beschluss", "rechtsgrundlage",
                         "directive", "regulation", "program")),
    ("product_text_raw", ("produkt", "erzeugnis", "gegenstand", "objekt", "dienstleistung",
                          "prozess", "product", "service", "process", "bereich", "kategorie")),
]

ROW_GAP = 20.0      # vertical gap (pt, top to top) that starts a new borderless record
ROW_PITCH_SPLIT = 17.0  # line pitch is ~13.4 pt; a larger step before a left-column entry starts a row
RUN_GAP = 8.0      # horizontal gap (pt) that separates two columns on one line
COL_TOL = 12.0      # x tolerance (pt) when snapping a run to a column


def is_grey(color) -> bool:
    """Light grey fill, the shading DAkkS puts behind table headers."""
    if color is None:
        return False
    vals = list(color) if isinstance(color, (list, tuple)) else [color]
    if len(vals) == 1:
        vals = vals * 3
    if len(vals) != 3:
        return False
    return max(vals) - min(vals) < 0.05 and 0.6 <= vals[0] <= 0.95


def is_white(rect) -> bool:
    def white(c):
        if c is None:
            return True
        vals = list(c) if isinstance(c, (list, tuple)) else [c]
        return len(vals) in (1, 3) and min(vals) >= 0.97 or (len(vals) == 4 and max(vals) <= 0.03)
    filled_white = rect.get("fill") and white(rect.get("non_stroking_color"))
    stroked_white = not rect.get("stroke") or white(rect.get("stroking_color"))
    return bool(filled_white and stroked_white) or bool(not rect.get("fill") and not rect.get("stroke"))


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def join_wrapped(parts: list[str]) -> str:
    """Join lines of one cell: whitespace collapsed, nothing else changed."""
    return squash(" ".join(p for p in parts if p))


def map_header(h: str) -> str | None:
    low = h.lower()
    for field, keys in HEADER_MAP:
        if any(k in low for k in keys):
            return field
    return None


# --------------------------------------------------------- layout primitives
class Line:
    __slots__ = ("top", "bottom", "runs", "page")

    def __init__(self, words, page):
        words.sort(key=lambda w: w["x0"])
        self.page = page
        self.top = min(w["top"] for w in words)
        self.bottom = max(w["bottom"] for w in words)
        runs, cur = [], [words[0]]
        for w in words[1:]:
            if w["x0"] - cur[-1]["x1"] > RUN_GAP:
                runs.append(cur)
                cur = [w]
            else:
                cur.append(w)
        runs.append(cur)
        # Justified text spreads words with wide gaps; that is one run, not columns.
        if len(runs) >= 4 and sorted(len(r) for r in runs)[len(runs) // 2] <= 2:
            runs = [words]
        self.runs = [{"x0": r[0]["x0"], "text": " ".join(w["text"] for w in r),
                      "bold": all("Bold" in w["fontname"] for w in r)} for r in runs]
        # a bullet belongs to the text after it, not to a column of its own
        if len(self.runs) >= 2 and BULLET_RE.match(self.runs[0]["text"]):
            b = self.runs.pop(0)
            self.runs[0] = {**self.runs[0], "text": b["text"] + " " + self.runs[0]["text"],
                            "bullet_x0": b["x0"]}

    @property
    def text(self) -> str:
        return " ".join(r["text"] for r in self.runs)

    @property
    def bold(self) -> bool:
        return all(r["bold"] for r in self.runs)

    @property
    def x0(self) -> float:
        return self.runs[0]["x0"]


def page_lines(page, pno) -> list[Line]:
    words = page.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["fontname"])
    words.sort(key=lambda w: (w["top"], w["x0"]))
    groups: list[list[dict]] = []
    for w in words:
        if groups and abs(groups[-1][0]["top"] - w["top"]) < 2.5:
            groups[-1].append(w)
        else:
            groups.append([w])
    return [Line(g, pno) for g in groups]


def inside(line: Line, bbox) -> bool:
    x0, top, x1, bottom = bbox
    mid = (line.top + line.bottom) / 2
    return top - 1 <= mid <= bottom + 1


# ------------------------------------------------------------ annex parser
class AnnexParser:
    """Turns one annex PDF into scope rows. Issues are collected in self.issues."""

    def __init__(self, path: Path, reg_no: str, source: str):
        self.path, self.reg_no, self.source = path, reg_no, source
        self.rows: list[dict] = []
        self.issues: list[str] = []
        self.standard = ""
        self.section = ""
        # borderless table state, per section
        self.headers: list[tuple[float, str]] = []    # (x0, header text)
        # ruled table state: header of the last ruled table, for continuation pages
        self.ruled_header: list[str] | None = None
        self.in_toc = False   # inside a table of contents (not scope)
        self.in_preamble = True
        self.last_text = None  # (row position, key, bold, last line) of the last text row

    # ---- output
    def emit(self, page: int, cols: dict[str, str]) -> None:
        cols = {k: squash(v) for k, v in cols.items() if squash(v)}
        if not cols:
            return
        row = {"registration_no": self.reg_no, "page": page, "row_index": len(self.rows) + 1,
               "product_text_raw": "", "scheme_text_raw": "", "normative_docs_raw": "",
               "scheme_type_raw": "", "source": self.source}
        other: dict[str, str] = {}
        if self.section:
            other["Abschnitt"] = self.section
        for header, text in cols.items():
            field = map_header(header) if not header.startswith(("Spalte ", "Text", "Bereich")) else None
            if field and not row[field]:
                row[field] = text
            else:
                other[header] = text
        if not row["scheme_type_raw"]:
            m = SCHEME_TYPE_RE.search(" ".join(cols.values()))
            if m:
                row["scheme_type_raw"] = m.group(1)
        row["other_columns_raw"] = json.dumps(other, ensure_ascii=False) if other else ""
        self.rows.append(row)
        self.last_text = None

    # ---- driver
    def parse(self) -> list[dict]:
        import pdfplumber
        with pdfplumber.open(str(self.path)) as pdf:
            if not pdf.pages:
                self.issues.append("PDF has no pages")
                return self.rows
            first_text = pdf.pages[0].extract_text() or ""
            m = STANDARD_RE.search(first_text)
            self.standard = m.group(1) if m else ""
            if not first_text.strip():
                self.issues.append("no text layer on page 1 (scanned PDF?)")
            stop = False
            for pno, page in enumerate(pdf.pages, 1):
                if stop:
                    break
                stop = self.parse_page(page, pno)
        return self.rows

    def parse_page(self, page, pno: int) -> bool:
        lines = [ln for ln in page_lines(page, pno) if not BOILER_RE.search(ln.text)]
        start_y, stop_y = 0.0, float("inf")   # scope region of this page
        if self.in_preamble:
            # The preamble (holder, sites, 17065 statement) can run onto page 2.
            end = next((i for i, ln in enumerate(lines) if PREAMBLE_END_RE.search(ln.text)), None)
            begin = next((i for i, ln in enumerate(lines) if SCOPE_START_RE.search(ln.text)), None)
            if begin is not None and (end is None or begin < end):
                end = begin - 1             # older layout: keep the "in den Bereichen:" line
            if end is None:
                end = next((i for i, ln in enumerate(lines) if PREAMBLE_END_FALLBACK_RE.search(ln.text)), None)
                if end is not None:
                    self.issues.append(f"page {pno}: preamble ended by fallback pattern")
            if end is None:
                if pno == 1:
                    return False            # look for the end on page 2
                self.issues.append("end of preamble not found on pages 1-2, page 1 skipped")
                self.in_preamble = False
            else:
                start_y = lines[end].bottom if end >= 0 else 0.0
                lines = lines[end + 1:]
                self.in_preamble = False
        stop = False
        for i, ln in enumerate(lines):
            if ABBREV_RE.search(ln.text):
                stop_y = ln.top
                lines, stop = lines[:i], True
                break

        # table of contents: from its title to the first bold numbered heading;
        # and the ISO 9001 statement where the older layout prints it after the scope
        kept = []
        in_stmt = False
        for ln in lines:
            if STMT_START_RE.search(ln.text):
                in_stmt = True
            if in_stmt:
                in_stmt = not STMT_END_RE.search(ln.text)
                continue
            if TOC_RE.match(ln.text):
                self.in_toc = True
                continue
            if self.in_toc and ln.bold and SECTION_NO_RE.match(ln.runs[0]["text"]) and len(ln.runs) >= 2:
                self.in_toc = False
            if self.in_toc or TOC_LEADER_RE.search(ln.text):
                continue
            kept.append(ln)
        lines = kept

        # White background boxes are invisible and are not table borders.
        visible = page.filter(lambda o: not (o.get("object_type") == "rect" and is_white(o)))
        tables = [t for t in visible.find_tables() if t.bbox[3] - t.bbox[1] > 10]
        # Interleave ruled tables and free lines in reading order.
        items: list[tuple[float, str, object]] = []
        used = set()
        for t in tables:
            if not (start_y <= t.bbox[1] < stop_y):
                continue
            items.append((t.bbox[1], "table", t))
            used.update(id(ln) for ln in lines if inside(ln, t.bbox))
        for ln in lines:
            if id(ln) not in used:
                items.append((ln.top, "line", ln))
        items.sort(key=lambda it: it[0])

        pending: list[Line] = []
        for _, kind, obj in items:
            if kind == "line":
                pending.append(obj)
            else:
                self.flow(pending, pno)
                pending = []
                self.ruled(page, obj, pno)
        self.flow(pending, pno)
        return stop

    # ---- free-flowing lines (headings, borderless tables, text)
    def flow(self, lines: list[Line], pno: int) -> None:
        if not lines:
            return
        lt = self.last_text
        if (lt and self.rows and lt[0] == len(self.rows) - 1 and self.rows[-1]["page"] == pno - 1
                and len(lines[0].runs) == 1 and lines[0].bold == lt[2]
                and not SECTION_NO_RE.match(lines[0].runs[0]["text"])
                and not re.search(r"[.;:]\s*$", lt[3])):
            # paragraph wrapped onto this page: append its first block to that row
            first_block = [lines[0]]
            for ln in lines[1:]:
                if ln.top - first_block[-1].top > ROW_GAP or len(ln.runs) > 1 or ln.bold != lt[2]:
                    break
                first_block.append(ln)
            row = self.rows[-1]
            other = json.loads(row["other_columns_raw"])
            other[lt[1]] = join_wrapped([other[lt[1]]] + [ln.text for ln in first_block])
            row["other_columns_raw"] = json.dumps(other, ensure_ascii=False)
            self.last_text = (lt[0], lt[1], lt[2], first_block[-1].text)
            lines = lines[len(first_block):]
            if not lines:
                return
        blocks: list[list[Line]] = []
        for ln in lines:
            first = ln.runs[0]
            is_heading = (len(ln.runs) >= 2 and ln.bold and SECTION_NO_RE.match(first["text"]))
            starts = (not blocks or is_heading or ln.top - blocks[-1][-1].top > ROW_GAP
                      or BULLET_RE.match(first["text"].split(" ", 1)[0])
                      or (blocks[-1][-1].bold != ln.bold and len(ln.runs) == 1
                          and len(blocks[-1][-1].runs) == 1
                          and re.search(r"[:;.]\s*$", blocks[-1][-1].text)))
            if not starts and len(ln.runs) >= 2:
                # Table rows printed without a blank line between them: a line with
                # text in the leftmost column, after a line without, starts a row.
                left = min(l.x0 for l in blocks[-1])
                if (abs(ln.x0 - left) <= COL_TOL and any(len(l.runs) >= 2 for l in blocks[-1])
                        and (blocks[-1][-1].x0 > left + COL_TOL
                             or ln.top - blocks[-1][-1].top > ROW_PITCH_SPLIT)):
                    starts = True
            if starts:
                blocks.append([ln])
            else:
                blocks[-1].append(ln)
        for i, b in enumerate(blocks):
            self.block(b, pno, blocks[i + 1] if i + 1 < len(blocks) else None)

    @staticmethod
    def is_multi(b: list[Line]) -> bool:
        xs = sorted(r["x0"] for ln in b for r in ln.runs)
        return any(len(ln.runs) >= 2 for ln in b) or bool(xs and xs[-1] - xs[0] > 40)

    def block(self, b: list[Line], pno: int, nxt: list[Line] | None = None) -> None:
        head = b[0]
        first = head.runs[0]["text"]
        # numbered bold section heading, possibly wrapping onto further bold lines
        if len(head.runs) >= 2 and head.bold and SECTION_NO_RE.match(first) and "bullet_x0" not in head.runs[0]:
            text = join_wrapped([ln.text for ln in b if ln.bold])
            self.section = text
            self.headers = []
            self.ruled_header = None
            self.emit(pno, {"Abschnitt_heading": text})
            rest = [ln for ln in b if not ln.bold]
            if rest:
                self.block(rest, pno)
            return
        multi = self.is_multi(b)
        if (multi and all(ln.bold for ln in b) and nxt is not None and self.is_multi(nxt)
                and not all(ln.bold for ln in nxt)):
            # bold header row of a borderless table (only if a data row follows)
            cols = self.columns(b)
            self.headers = [(x, join_wrapped(parts)) for x, parts in cols]
            return
        if multi:
            cols = self.columns(b)
            out: dict[str, str] = {}
            for x, parts in cols:
                name = self.header_for(x) or f"Spalte {self.col_no(x, cols)}"
                out[name] = (out.get(name, "") + " " + join_wrapped(parts)).strip()
            if not any(self.header_for(x) for x, _ in cols):
                self.note_once(f"page {pno}: borderless table without header")
            self.emit(pno, out)
            return
        # Bold text before the first numbered section is the summary of scope areas.
        key = "Bereich" if not self.section and head.bold else "Text"
        texts = [ln.text for ln in b]
        if len(texts) > 1 and all(t.rstrip().endswith(";") for t in texts[:-1]):
            items = [[t] for t in texts]          # a list: one item per line
        else:
            items = [texts]                       # a paragraph: lines are wrapping
        for it in items:
            self.emit(pno, {key: join_wrapped(it)})
            self.last_text = (len(self.rows) - 1, key, head.bold, it[-1])

    def columns(self, b: list[Line]) -> list[tuple[float, list[str]]]:
        cols: list[tuple[float, list[str]]] = []
        for ln in b:
            for r in ln.runs:
                hit = next((c for c in cols if abs(c[0] - r["x0"]) <= COL_TOL), None)
                if hit is None:
                    # snap to a known header column if possible
                    cols.append((r["x0"], [r["text"]]))
                else:
                    hit[1].append(r["text"])
        cols.sort(key=lambda c: c[0])
        return cols

    def header_for(self, x: float) -> str | None:
        if not self.headers:
            return None
        best = min(self.headers, key=lambda h: abs(h[0] - x))
        return best[1] if abs(best[0] - x) <= 40 else None

    @staticmethod
    def col_no(x: float, cols) -> int:
        return [c[0] for c in cols].index(x) + 1

    def note_once(self, msg: str) -> None:
        if msg not in self.issues:
            self.issues.append(msg)

    # ---- ruled tables
    def ruled(self, page, table, pno: int) -> None:
        grid = []
        above: dict[int, tuple] = {}     # last real cell seen in each grid column
        for row in table.rows:
            seen, vals = set(), []
            rowy = (row.bbox[1] + row.bbox[3]) / 2
            for ci, cell in enumerate(row.cells):
                bbox = cell
                if bbox is None:
                    # Empty slot: part of a cell merged downwards from above (its
                    # text belongs to this row too), or of one merged sideways (empty).
                    prev = above.get(ci)
                    bbox = prev if prev and prev[1] - 1 <= rowy <= prev[3] + 1 else None
                else:
                    above[ci] = tuple(bbox)
                if bbox is None or tuple(bbox) in seen:
                    vals.append(("", False))
                    continue
                seen.add(tuple(bbox))
                x0, top, x1, bottom = bbox
                crop = page.filter(lambda o, x0=x0, top=top, x1=x1, bottom=bottom:
                                   o.get("object_type") != "char"
                                   or (x0 <= (o["x0"] + o["x1"]) / 2 <= x1
                                       and top <= (o["top"] + o["bottom"]) / 2 <= bottom))
                words = crop.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["fontname"])
                text = squash(crop.extract_text(x_tolerance=1.5, y_tolerance=2) or "")
                bold = bool(words) and all("Bold" in w["fontname"] for w in words)
                vals.append((text, bold))
            grid.append(vals)
        if not grid:
            return
        # header band: leading rows that are shaded grey (the DAkkS table style)
        # or whose filled cells are all bold. DAkkS often draws a header as several
        # thin sub-rows with one filled cell each.
        tx0, ttop, tx1, tbottom = table.bbox
        greys = [r for r in page.rects if r.get("fill") and is_grey(r.get("non_stroking_color"))
                 and r["x0"] < tx1 and r["x1"] > tx0 and r["top"] < tbottom and r["bottom"] > ttop]
        hdr_rows = 0
        for row, vals in zip(table.rows, grid):
            filled = [v for v in vals if v[0]]
            mid = (row.bbox[1] + row.bbox[3]) / 2
            shaded = any(g["top"] - 1 <= mid <= g["bottom"] + 1 for g in greys)
            # With shading, only shaded rows are header; bold rows below it are
            # sub-headings inside the table and stay data.
            if shaded or (not greys and all(b for _, b in filled)):
                hdr_rows += 1
            else:
                break
        hdr_cols = {c for r in grid[:hdr_rows] for c, v in enumerate(r) if v[0]}
        if len(hdr_cols) < 2 or hdr_rows == len(grid):
            hdr_rows = 0
        data = grid[hdr_rows:]
        if hdr_rows:
            ncol = len(grid[0])
            header = []
            for c in range(ncol):
                parts = []
                for r in range(hdr_rows):
                    if grid[r][c][0] and grid[r][c][0] not in parts:
                        parts.append(grid[r][c][0])
                header.append(join_wrapped(parts))
            self.ruled_header = header
        elif self.ruled_header and len(self.ruled_header) == len(grid[0]):
            header = self.ruled_header      # continuation of a table from the previous page
        else:
            header = [f"Spalte {i + 1}" for i in range(len(grid[0]))]
            if any(v[0] for vals in grid for v in vals):
                self.note_once(f"page {pno}: ruled table without header")
        for vals in data:
            out: dict[str, str] = {}
            for ci, (name, (text, _)) in enumerate(zip(header, vals)):
                name = name or f"Spalte {ci + 1}"
                if text:
                    out[name] = (out.get(name, "") + " " + text).strip()
            self.emit(pno, out)

    @staticmethod
    def col_mid(table, ci: int) -> float:
        xs = sorted({round(c[0], 1) for c in table.cells} | {round(c[2], 1) for c in table.cells})
        edges = []
        for x in xs:
            if not edges or x - edges[-1] > 2:
                edges.append(x)
        if ci + 1 < len(edges):
            return (edges[ci] + edges[ci + 1]) / 2
        return edges[-1]

    @staticmethod
    def clip(bbox, page):
        x0, top, x1, bottom = bbox
        return (max(x0, page.bbox[0]), max(top, page.bbox[1]),
                min(x1, page.bbox[2]), min(bottom, page.bbox[3]))


def fix_heading_rows(rows: list[dict]) -> None:
    """Section-heading rows carry their own text under 'Abschnitt' only."""
    for r in rows:
        if r["other_columns_raw"]:
            d = json.loads(r["other_columns_raw"])
            if "Abschnitt_heading" in d:
                d = {"Abschnitt": d.pop("Abschnitt_heading")}
                r["other_columns_raw"] = json.dumps(d, ensure_ascii=False)


# ------------------------------------------------------------------- driver
def pick_annexes(records: list[dict]) -> list[dict]:
    """German annexes (the original); the English one only if no German one exists.

    Older DAkkS accreditations publish a single -00 file that is certificate and
    annex in one ("Anlage zur Akkreditierungsurkunde D-ZE-11086-01-00"); the old
    scraper types it "certificate" by its suffix. When an accreditation has no
    separate annex, its -00 file is parsed instead.
    """
    base = lambda aid: aid.rsplit("-", 1)[0]          # D-ZE-11020-01-01 -> D-ZE-11020-01
    all_docs = [(rec, d) for rec in records for d in rec.get("documents", [])]
    has_annex = {base(d["accreditation_id"]) for _, d in all_docs if d.get("document_type") == "annex"}
    by_id: dict[str, list[tuple[dict, dict]]] = {}
    for rec, d in all_docs:
        kind = d.get("document_type")
        if kind == "annex" or (kind == "certificate" and base(d["accreditation_id"]) not in has_annex):
            by_id.setdefault(d["accreditation_id"], []).append((rec, d))
    docs = []
    for aid, pairs in by_id.items():
        de = [p for p in pairs if p[1]["language"] == "DE"]
        rec, d = (de or pairs)[0]
        docs.append({**d, "body_id": ds.body_id(aid), "name": rec["name"],
                     "status": rec.get("status", "")})
    return docs


def parse_scopes(out: Path, records: list[dict]) -> tuple[list[dict], dict]:
    all_rows: list[dict] = []
    per_annex: dict[str, int] = {}
    issues: dict[str, list[str]] = {}
    standards: Counter = Counter()
    for doc in pick_annexes(records):
        aid = doc["accreditation_id"]
        if not doc.get("local_path") or not (out / doc["local_path"]).exists():
            issues.setdefault(aid, []).append("annex PDF not on disk")
            per_annex[aid] = 0
            continue
        p = AnnexParser(out / doc["local_path"], aid, f'{doc["local_path"]} | {doc["url"]}')
        try:
            rows = p.parse()
        except Exception as e:  # one bad PDF must not stop the run
            rows = []
            p.issues.append(f"parser error: {e!r}")
        fix_heading_rows(rows)
        standards[p.standard or "(not found)"] += 1
        # DAkkS sometimes prints "nach DIN EN ISO/IEC 17025" on a ZE annex whose text certifies to 17065
        text_file = out / doc["text_path"] if doc.get("text_path") else None
        says_17065 = bool(text_file and text_file.exists()
                          and re.search(r"erfüllt die Anforderungen gemäß DIN EN ISO/IEC 17065|"
                                        r"meets the requirements (of|according to) DIN EN ISO/IEC 17065",
                                        text_file.read_text(encoding="utf-8", errors="replace")))
        if says_17065 and (not p.standard or "17065" not in p.standard):
            p.issues.append(f"annex header says {p.standard or '(none)'} but the text certifies to ISO/IEC 17065: kept")
            p.standard = "DIN EN ISO/IEC 17065:2013"
        if p.standard and "17065" not in p.standard:
            # e.g. an ISO/IEC 17025 testing-lab annex filed under the ZE number
            p.issues.append(f"annex is {p.standard}, not ISO/IEC 17065: its {len(rows)} lines are left out")
            rows = []
        if not p.standard:
            p.issues.append("standard ('nach DIN EN ISO/IEC 17065') not found on page 1"
                            + (f": its {len(rows)} lines are left out" if rows else ""))
            rows = []
        if doc["language"] != "DE":
            p.issues.append("no German annex; English annex parsed")
        per_annex[aid] = len(rows)
        if p.issues:
            issues[aid] = p.issues
        all_rows.extend(rows)
    return all_rows, {"per_annex": per_annex, "issues": issues, "standards": dict(standards)}


def run(args: argparse.Namespace) -> int:
    out = Path(args.out or f"dakks_{TYPE}")
    out.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(out / "scope_parse.log", mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(fh)

    rc = 0
    if not args.parse_only:
        # Crawl with the old scraper: same search, cache, PDFs and body/document files.
        args.type = TYPE
        rc = ds.run(args)
        if rc == 2:
            return rc
    acc = out / "accreditations.json"
    if not acc.exists():
        log.error("%s missing: run without --parse-only first", acc)
        return 2
    records = json.loads(acc.read_text(encoding="utf-8"))
    rows, rep = parse_scopes(out, records)

    with (out / "scope_lines.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SCOPE_COLS)
        w.writeheader()
        w.writerows(rows)

    # per body counts (all of the body's annexes)
    per_body: Counter = Counter()
    bodies = {ds.body_id(r["accreditation_id"]): r["name"] for r in records}
    for aid, n in rep["per_annex"].items():
        per_body[ds.body_id(aid)] += n
    no_annex = sorted(b for b in bodies if b not in {ds.body_id(a) for a in rep["per_annex"]})
    for bid in sorted(bodies):
        n = per_body.get(bid, 0)
        if n:
            log.info("%s scope lines: %d  %s", bid, n, bodies[bid][:60])
        else:
            why = "no annex published" if bid in no_annex else "annex parsed to 0 lines"
            sts = sorted({r.get("status", "") for r in records if ds.body_id(r["accreditation_id"]) == bid})
            why += f"; status: {', '.join(sts)}"
            log.warning("%s scope lines: 0 (%s)  %s", bid, why, bodies[bid][:60])
    for aid, msgs in sorted(rep["issues"].items()):
        for m in msgs:
            log.warning("%s: %s", aid, m)

    filled = {c: sum(bool(r[c]) for r in rows) for c in SCOPE_COLS[3:8]}
    report = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bodies": len(bodies), "annexes_parsed": len(rep["per_annex"]),
        "scope_lines": len(rows), "lines_with_value": filled,
        "standards_on_annexes": rep["standards"],
        "bodies_with_zero_lines": [b for b in sorted(bodies) if not per_body.get(b)],
        "bodies_without_annex": no_annex,
        "scope_lines_per_body": {b: per_body.get(b, 0) for b in sorted(bodies)},
        "scope_lines_per_annex": rep["per_annex"],
        "other_column_headers": Counter(k for r in rows if r["other_columns_raw"]
                                        for k in json.loads(r["other_columns_raw"])).most_common(),
        "issues": rep["issues"],
    }
    ds.write_atomic(out / "scope_report.json",
                    json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    log.info("Scope: %d lines from %d annexes, %d bodies (%d with zero lines) -> %s",
             len(rows), len(rep["per_annex"]), len(bodies),
             len(report["bodies_with_zero_lines"]), out / "scope_lines.csv")
    return rc


def main() -> int:
    p = argparse.ArgumentParser(description="Scrape DAkkS ISO/IEC 17065 bodies (type ZE) and their scope lines.")
    p.add_argument("--status", default="all", choices=ds.STATUSES, help="A, T, R, Z or all (default)")
    p.add_argument("--out", help=f"output folder (default dakks_{TYPE})")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1)")
    p.add_argument("--limit", type=int, help="only the first N records, for a test run")
    p.add_argument("--no-pdfs", action="store_true", help="metadata only")
    p.add_argument("--no-text", action="store_true", help="no PDF text extraction")
    p.add_argument("--related-pdfs", action="store_true",
                   help="also download PDFs of the body's other accreditations (labs, etc.)")
    p.add_argument("--refresh", action="store_true", help="ignore cached pages and PDFs")
    p.add_argument("--parse-only", action="store_true",
                   help="no network: parse the scopes of the PDFs already in --out")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    try:
        return run(args)
    except KeyboardInterrupt:
        log.warning("Interrupted. Run the same command again to continue.")
        return 130
    except Exception as e:
        log.exception("%s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
