"""Plain-text reader for ESYD's scope annexes: Word 97-2003 (.doc) files, and the few that are
really Word 2007+ (.docx) despite the .doc name.

.doc text is read through the piece table (the CLX structure in the table stream), so
characters come out in document order. In both formats table cells end with "\\x07" and
paragraphs with "\\r", and only the main document text is returned (no headers or footers).
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import olefile

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Characters Word stores in "compressed" (8-bit) pieces that differ from cp1252.
_COMPRESSED_SPECIAL = {
    0x82: "‚", 0x83: "ƒ", 0x84: "„", 0x85: "…", 0x86: "†", 0x87: "‡",
    0x88: "ˆ", 0x89: "‰", 0x8A: "Š", 0x8B: "‹", 0x8C: "Œ", 0x91: "‘",
    0x92: "’", 0x93: "“", 0x94: "”", 0x95: "•", 0x96: "–", 0x97: "—",
    0x98: "˜", 0x99: "™", 0x9A: "š", 0x9B: "›", 0x9C: "œ", 0x9F: "Ÿ",
}


def _decode_compressed(data: bytes) -> str:
    return "".join(_COMPRESSED_SPECIAL.get(b) or chr(b) for b in data)


def read_text(path: Path) -> str:
    # zipfile.is_zipfile() also accepts .doc files that embed a zip (e.g. a chart), so check
    # the signature at the start of the file instead.
    with open(path, "rb") as fh:
        if fh.read(4) == b"PK\x03\x04":
            return _read_docx(path)
    return _read_doc(path)


def _read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    out: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        tag = node.tag
        if tag == _W + "t":
            out.append(node.text or "")
        elif tag == _W + "tab":
            out.append("\t")
        elif tag in (_W + "br", _W + "cr"):
            out.append("\n")
        for child in node:
            walk(child)
        if tag == _W + "p":
            out.append("\r")
        elif tag == _W + "tc":
            out.append("\x07")
        elif tag == _W + "tr":
            out.append("\x07")

    walk(root)
    return "".join(out)


def _read_doc(path: Path) -> str:
    with olefile.OleFileIO(str(path)) as ole:
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, 0x000A)[0]
        table_name = "1Table" if flags & 0x0200 else "0Table"
        table = ole.openstream(table_name).read()

    ccp_text = struct.unpack_from("<i", word, 0x004C)[0]   # length of the main document text
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x01A2)
    clx = table[fc_clx:fc_clx + lcb_clx]

    pos = 0
    while clx[pos] == 0x01:                                 # skip Prc (property) entries
        pos += 3 + struct.unpack_from("<H", clx, pos + 1)[0]
    if clx[pos] != 0x02:
        raise ValueError(f"{path.name}: no piece table")
    lcb = struct.unpack_from("<I", clx, pos + 1)[0]
    plc = clx[pos + 5:pos + 5 + lcb]
    pieces = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{pieces + 1}i", plc, 0)

    out: list[str] = []
    for i in range(pieces):
        start, end = cps[i], min(cps[i + 1], ccp_text)
        if start >= end:
            break
        fc = struct.unpack_from("<I", plc, (pieces + 1) * 4 + i * 8 + 2)[0]
        count = end - start
        if fc & 0x40000000:
            offset = (fc & ~0x40000000) // 2
            out.append(_decode_compressed(word[offset:offset + count]))
        else:
            out.append(word[fc:fc + 2 * count].decode("utf-16-le", errors="replace"))
    return "".join(out)
