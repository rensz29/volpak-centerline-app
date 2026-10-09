"""OCAP files read into sections with their pages (ADR-0031): PDF with pdfplumber, Word (.docx) with python-docx,
Excel (.xlsx) with the standard library (ADR-0039).

A PDF has no structure, so its headings are found from how they look:
- larger than the body, or bold;
- short, and not ending like a sentence;
- or numbered ("3.2 Heater fault") and set larger or bold.

Lines repeated on most pages (headers, footers) and page numbers are dropped. A Word file has its headings in its
styles (Heading 1…6, Title, or an outline level). Its pages come from the breaks Word recorded when it last laid the
document out: approximate, and unknown when there are none. A PDF without text (a scan) can't be read: it would need
OCR first.

An Excel workbook has its structure in its cells. Each visible sheet holds a table under a header row: each row, or
each block of rows merged in the first column, is a section found by its sheet and rows. Its "phenomenon" column, if
it has one, names the reason an operator can pick (ADR-0039). Title lines above the header and notes below the table
are sections of their own.
"""

from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TEXT = "text/plain"
MAX_BYTES = 20 * 1024 * 1024
WRITTEN = "Written in Centerline"

PAGE_NUMBER = re.compile(r"^(page|pahina)?\s*\d+\s*((of|/|ng)\s*\d+)?$", re.I)
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
BOLD = re.compile(r"bold|black|heavy|semibold", re.I)
BULLET = re.compile(r"^([•▪●◦‣\-–*]|\d+[.)]|[a-z][.)])\s")


class Unreadable(Exception):
    """The file isn't a PDF or Word document Centerline can read; the message says why."""


@dataclass
class Section:
    heading: str | None  # None: the text before the first heading
    level: int
    page_from: int | None
    page_to: int | None
    body: str
    # An Excel section: where it is, and the reason it offers (ADR-0039)
    sheet: str | None = None
    row_from: int | None = None
    row_to: int | None = None
    phenomenon: str | None = None
    area: str | None = None  # what its sealer, area or Centerline name columns say: which parameters it's for
    cause: str | None = None  # what its cause column says: whether a raised or a lowered setpoint fits it


@dataclass
class Parsed:
    sections: list[Section]
    pages: int | None


KINDS = {PDF: "PDF", DOCX: "Word (.docx)", XLSX: "Excel (.xlsx)"}
ZIPPED = {DOCX: "a Word document (.docx)", XLSX: "an Excel workbook (.xlsx)"}


def sniff(data: bytes, kinds: tuple[str, ...] = (PDF, DOCX)) -> str:
    """The file's type from its first bytes, whatever its name says; refused unless it's one of `kinds`."""
    found = None
    if data.startswith(b"%PDF-"):
        found = PDF
    elif data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
            found = DOCX if "word/document.xml" in names else XLSX if "xl/workbook.xml" in names else None
        except zipfile.BadZipFile:
            pass
        if found not in kinds:
            raise Unreadable("It's a zip file, but not " + " or ".join(ZIPPED[k] for k in kinds if k in ZIPPED))
    elif data.startswith(b"\xd0\xcf\x11\xe0"):
        raise Unreadable("Word or Excel 97–2003 files (.doc, .xls) can't be read: open it and save it as .docx or .xlsx")
    if found not in kinds:
        raise Unreadable(f"Only {' and '.join(', '.join(KINDS[k] for k in kinds).rsplit(', ', 1))} files can be uploaded")
    return found


def parse(data: bytes, media_type: str) -> Parsed:
    try:
        sections, pages = {PDF: _pdf, DOCX: _docx, XLSX: _xlsx}[media_type](data)
    except Unreadable:
        raise
    except Exception as e:  # a damaged or encrypted file: say so rather than fail
        raise Unreadable(f"The file can't be read ({type(e).__name__}): is it damaged or password-protected?") from None
    sections = [s for s in sections if s.body.strip() or s.heading]
    if not any(s.body.strip() for s in sections):
        raise Unreadable("No text was found in the PDF: a scanned document needs OCR first. Upload the original, "
                         "or a PDF with text" if media_type == PDF else "The document has no text")
    if media_type == XLSX and len(sections) > 2000:
        raise Unreadable(f"The workbook has {len(sections)} rows of text: 2000 at most")
    return Parsed(sections, pages)


def from_text(title: str, text: str) -> Parsed:
    """A version written in Centerline: lines starting with # are headings; without any, one section under the title."""
    sections: list[Section] = []
    heading, level, lines = title.strip(), 1, []
    for raw in text.strip().splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)$", raw.strip())
        if m:
            if lines:
                sections.append(Section(heading, level, None, None, "\n".join(lines).strip()))
            heading, level, lines = m.group(2).strip(), len(m.group(1)), []
        else:
            lines.append(raw.rstrip())
    if lines or not sections:
        sections.append(Section(heading, level, None, None, "\n".join(lines).strip()))
    return Parsed(sections, None)


# -- PDF ------------------------------------------------------------------------------------------------------------

@dataclass
class _Line:
    text: str
    size: float
    bold: bool
    top: float
    page: int


def _page_lines(page, number: int) -> list[_Line]:
    words = page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False)
    words.sort(key=lambda w: (w["top"], w["x0"]))
    rows: list[list[dict]] = []
    for w in words:
        if rows and abs(rows[-1][-1]["top"] - w["top"]) <= 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    out = []
    for r in rows:
        r.sort(key=lambda w: w["x0"])
        text = re.sub(r"\s+", " ", " ".join(w["text"] for w in r)).strip()
        if text:
            out.append(_Line(text, round(max(w["size"] for w in r), 1), all(BOLD.search(w["fontname"]) for w in r),
                             min(w["top"] for w in r), number))
    return out


def _pdf(data: bytes) -> tuple[list[Section], int]:
    import pdfplumber  # loaded on first use: the api starts without it

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [_page_lines(p, i + 1) for i, p in enumerate(pdf.pages)]
    n = len(pages)
    # Headers and footers: the same line, numbers aside, on most pages
    keys = [{re.sub(r"\d+", "#", line.text.lower()) for line in page} for page in pages]
    counts = Counter(k for page_keys in keys for k in page_keys)
    repeated = {k for k, c in counts.items() if n >= 2 and c >= max(2, math.ceil(n * 0.6))}
    lines = [line for page in pages for line in page
             if not PAGE_NUMBER.match(line.text) and re.sub(r"\d+", "#", line.text.lower()) not in repeated]
    if not lines:
        return [], n
    sizes = Counter()
    for line in lines:
        sizes[line.size] += len(line.text)
    body = sizes.most_common(1)[0][0]

    def heading(line: _Line) -> bool:
        t = line.text
        bigger = line.size >= body * 1.12 and line.size - body >= 1.0
        if len(t) > 120 or len(t.split()) > 15 or t.endswith((".", ",", ";")) or BULLET.match(t) and not NUMBERED.match(t):
            return False
        if NUMBERED.match(t):
            return bigger or line.bold
        return bigger or (line.bold and len(t) <= 90)

    ranks = sorted({l.size for l in lines if heading(l) and l.size >= body * 1.12}, reverse=True)

    def level(line: _Line) -> int:
        m = NUMBERED.match(line.text)
        if m:
            return min(6, m.group(1).count(".") + 1)
        return min(6, ranks.index(line.size) + 1) if line.size in ranks else min(6, len(ranks) + 1)

    sections: list[Section] = []
    cur = Section(None, 1, lines[0].page, lines[0].page, "")
    parts: list[str] = []
    prev: _Line | None = None
    since_heading = False  # body text seen since the current heading

    def flush():
        cur.body = "".join(parts).strip()
        if cur.body or cur.heading:
            sections.append(cur)

    for line in lines:
        if heading(line):
            if (prev is not None and cur.heading and not since_heading and heading(prev) and prev.size == line.size
                    and prev.bold == line.bold and prev.page == line.page):
                cur.heading += " " + line.text  # a heading on two lines
            else:
                flush()
                cur, parts, since_heading = Section(line.text.rstrip(":").strip(), level(line), line.page, line.page, ""), [], False
        else:
            if parts:
                gap = line.top - prev.top if prev is not None and prev.page == line.page else None
                new_paragraph = gap is None or gap > line.size * 1.75 or BULLET.match(line.text)
                parts.append("\n" if new_paragraph else " ")
            parts.append(line.text)
            cur.page_to, since_heading = line.page, True
        prev = line
    flush()
    return sections, n


# -- Word -----------------------------------------------------------------------------------------------------------

def _docx(data: bytes) -> tuple[list[Section], int | None]:
    from docx import Document  # loaded on first use
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    page, paged = 1, False
    sections: list[Section] = []
    cur = Section(None, 1, 1, 1, "")
    parts: list[str] = []

    def flush():
        cur.body = "\n".join(p for p in parts if p).strip()
        if cur.body or cur.heading:
            sections.append(cur)

    def heading_level(p: Paragraph) -> int | None:
        style = p.style
        while style is not None:
            sid = (style.style_id or "").lower()
            if sid == "title":
                return 1
            m = re.match(r"heading(\d)$", sid)
            if m:
                return int(m.group(1))
            style = style.base_style
        lvl = p._p.find(f"{qn('w:pPr')}/{qn('w:outlineLvl')}")
        if lvl is not None and lvl.get(qn("w:val"), "").isdigit() and int(lvl.get(qn("w:val"))) < 9:
            return min(6, int(lvl.get(qn("w:val"))) + 1)
        return None

    for el in doc.element.body.iterchildren():
        if el.tag == qn("w:p"):
            breaks = len(el.findall(f".//{qn('w:lastRenderedPageBreak')}"))
            breaks += sum(1 for b in el.findall(f".//{qn('w:br')}") if b.get(qn("w:type")) == "page")
            if breaks:
                page, paged = page + breaks, True
            p = Paragraph(el, doc)
            text = re.sub(r"[ \t]+", " ", p.text).strip()
            if not text:
                continue
            lvl = heading_level(p)
            if lvl is not None:
                flush()
                cur, parts = Section(text.rstrip(":").strip(), min(6, lvl), page, page, ""), []
            else:
                parts.append(text)
                cur.page_to = page
        elif el.tag == qn("w:tbl"):
            for row in Table(el, doc).rows:
                cells = list(dict.fromkeys(c.text.strip() for c in row.cells if c.text.strip()))  # merged cells repeat
                if cells:
                    parts.append(" | ".join(cells))
            cur.page_to = page
    flush()
    if not paged:
        for s in sections:
            s.page_from = s.page_to = None
    return sections, page if paged else None


# -- Excel ----------------------------------------------------------------------------------------------------------

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
UNPACKED_MAX = 100 * 1024 * 1024  # a 20 MB workbook that unpacks to more is refused, not read
HEADER_SEARCH = 10  # the header row is among the first rows: the one with the most cells
PHENOMENON = (re.compile(r"phenomen", re.I), re.compile(r"symptom|problem|defect", re.I), re.compile(r"\bissue", re.I))
AREA = re.compile(r"centerline name|sealer|\barea\b|assembly|\bzone", re.I)
CAUSE = re.compile(r"\bcause", re.I)


def _cell_ref(ref: str) -> tuple[int, int]:
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    if m is None:
        raise Unreadable(f"A cell reference the workbook shouldn't have: {ref!r}")
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


def _number(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return v
    return str(int(f)) if f.is_integer() and abs(f) < 1e15 else format(f, ".10g")


def _clean(text: str) -> str:
    return "\n".join(re.sub(r"[ \t ]+", " ", line).strip() for line in text.replace("\r", "").split("\n")).strip()


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    # ElementTree resolves no external entities, and expat refuses entity expansion bombs
    return ET.fromstring(z.read(name))


def _xlsx(data: bytes) -> tuple[list[Section], None]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > UNPACKED_MAX:
            raise Unreadable("The workbook unpacks to more than 100 MB: save it without pictures or unused sheets")
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in _xml(z, "xl/sharedStrings.xml").findall(f"{_M}si"):
                # The text itself, or its runs (rich text); not the phonetic guide
                parts = [t.text or "" for t in si.findall(f"{_M}t")] + [t.text or "" for t in si.findall(f"{_M}r/{_M}t")]
                shared.append("".join(parts))
        rels = {r.get("Id"): r.get("Target") for r in _xml(z, "xl/_rels/workbook.xml.rels").findall(f"{_PR}Relationship")}
        sections: list[Section] = []
        for sheet in _xml(z, "xl/workbook.xml").iterfind(f"{_M}sheets/{_M}sheet"):
            if sheet.get("state") in ("hidden", "veryHidden"):
                continue  # lookup lists and the like: not what the operator reads
            target = rels.get(sheet.get(_R), "")
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            if path not in names:
                continue  # a chart sheet, or a sheet the package doesn't have
            sections += _sheet(sheet.get("name") or "Sheet", _xml(z, path), shared)
    return sections, None


def _sheet(name: str, root: ET.Element, shared: list[str]) -> list[Section]:
    cells: dict[tuple[int, int], str] = {}
    for c in root.iter(f"{_M}c"):
        kind, v = c.get("t"), c.find(f"{_M}v")
        if kind == "inlineStr":
            text = "".join(t.text or "" for t in c.iter(f"{_M}t"))
        elif v is None or v.text is None or kind == "e":
            continue
        elif kind == "s":
            text = shared[int(v.text)] if int(v.text) < len(shared) else ""
        elif kind == "b":
            text = "TRUE" if v.text == "1" else "FALSE"
        elif kind == "str":
            text = v.text
        else:
            text = _number(v.text)  # a date shows as Excel's day number: OCAPs rarely hold one
        text = _clean(text)
        if text:
            cells[_cell_ref(c.get("r", ""))] = text
    if not cells:
        return []
    merged = []
    for m in root.iter(f"{_M}mergeCell"):
        first, _, last = (m.get("ref") or "").partition(":")
        if last:
            (r1, c1), (r2, c2) = _cell_ref(first), _cell_ref(last)
            merged.append((r1, c1, r2, c2))
    rows = sorted({r for r, _ in cells})
    last_row = max(rows[-1], max((m[2] for m in merged), default=0))

    def row_cells(r: int) -> list[tuple[int, str]]:
        return sorted((c, t) for (rr, c), t in cells.items() if rr == r)

    # The header: among the first rows, the one with the most cells (two at least)
    candidates = [r for r in rows if r < rows[0] + HEADER_SEARCH]
    header = max(candidates, key=lambda r: (len(row_cells(r)), -r))
    if len(row_cells(header)) < 2:  # no table: the sheet as one section
        lines = [" | ".join(t for _, t in row_cells(r)) for r in rows]
        return [Section(name, 1, None, None, "\n".join(lines), sheet=name, row_from=rows[0], row_to=rows[-1])]
    titles = {c: _clean(t).replace("\n", " ") for c, t in row_cells(header)}
    key = min(titles)

    def pick(*patterns: re.Pattern) -> int | None:
        for pattern in patterns:
            for c in sorted(titles):
                if c != key and pattern.search(titles[c]):
                    return c
        return None

    phenomenon_col = pick(*PHENOMENON)
    area_cols = [c for c in sorted(titles) if c != key and AREA.search(titles[c])]
    cause_col = pick(CAUSE)

    def merged_from_above(r: int) -> bool:
        return any(r1 < r <= r2 for r1, _, r2, _ in merged)

    sections: list[Section] = []
    # Title lines above the header (a group-header row with several cells is left out)
    above = [r for r in rows if r < header and len(row_cells(r)) == 1]
    if above:
        lines = [row_cells(r)[0][1] for r in above]
        if len(lines) > 1:
            sections.append(Section(lines[0], 1, None, None, "\n".join(lines[1:]), sheet=name, row_from=above[0],
                                    row_to=above[-1]))
    # The table: from below the header to the first empty row
    table = []
    r = header + 1
    while r <= last_row and (row_cells(r) or merged_from_above(r)):
        table.append(r)
        r += 1
    keyed = [r for r in table if (r, key) in cells]
    blocks: list[list[int]] = []
    for r in table:
        if not blocks or (len(keyed) >= 2 and (r, key) in cells) or len(keyed) < 2:
            blocks.append([r])  # a new row, or each row on its own when the first column doesn't number them
        else:
            blocks[-1].append(r)
    for block in blocks:
        def text(col: int) -> str:
            return "\n".join(cells[(r, col)] for r in block if (r, col) in cells)

        number = text(key)
        phenomenon = text(phenomenon_col) if phenomenon_col else ""
        lines = []
        for c in sorted(titles) + sorted({c for r in block for (rr, c) in cells if rr == r and c not in titles}):
            value = text(c)
            if c == key or not value:
                continue
            label = titles.get(c) or f"Column {c}"
            lines.append(f"{label}:\n{value}" if "\n" in value else f"{label}: {value}")
        if not lines and not number:
            continue
        flat = phenomenon.replace("\n", " ")
        heading = f"{number}. {flat}" if number and flat else flat or f"{titles[key]} {number}".strip()
        sections.append(Section(heading, 2, None, None, "\n".join(lines), sheet=name, row_from=block[0], row_to=block[-1],
                                phenomenon=flat or None, area=" ".join(text(c) for c in area_cols) or None,
                                cause=text(cause_col) if cause_col else None))
    # Notes below the table
    after = [r for r in rows if r > (table[-1] if table else header)]
    if after:
        lines = [" | ".join(t for _, t in row_cells(r)) for r in after]
        sections.append(Section("Notes", 2, None, None, "\n".join(lines), sheet=name, row_from=after[0], row_to=after[-1]))
    return sections
