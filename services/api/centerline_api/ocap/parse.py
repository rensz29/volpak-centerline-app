"""OCAP files read into sections with their pages (ADR-0031): PDF with pdfplumber, Word (.docx) with python-docx.

A PDF has no structure, so its headings are found from how they look:
- larger than the body, or bold;
- short, and not ending like a sentence;
- or numbered ("3.2 Heater fault") and set larger or bold.

Lines repeated on most pages (headers, footers) and page numbers are dropped. A Word file has its headings in its
styles (Heading 1…6, Title, or an outline level). Its pages come from the breaks Word recorded when it last laid the
document out: approximate, and unknown when there are none. A PDF without text (a scan) can't be read: it would need
OCR first.
"""

from __future__ import annotations

import io
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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


@dataclass
class Parsed:
    sections: list[Section]
    pages: int | None


def sniff(data: bytes) -> str:
    """The file's type from its first bytes, whatever its name says."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return DOCX
        except zipfile.BadZipFile:
            pass
        raise Unreadable("It's a zip file, but not a Word document (.docx)")
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise Unreadable("Word 97–2003 files (.doc) can't be read: open it in Word and save it as .docx")
    raise Unreadable("Only PDF and Word (.docx) files can be uploaded")


def parse(data: bytes, media_type: str) -> Parsed:
    try:
        sections, pages = (_pdf if media_type == PDF else _docx)(data)
    except Unreadable:
        raise
    except Exception as e:  # a damaged or encrypted file: say so rather than fail
        raise Unreadable(f"The file can't be read ({type(e).__name__}): is it damaged or password-protected?") from None
    sections = [s for s in sections if s.body.strip() or s.heading]
    if not any(s.body.strip() for s in sections):
        raise Unreadable("No text was found in the PDF: a scanned document needs OCR first. Upload the original, "
                         "or a PDF with text" if media_type == PDF else "The document has no text")
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
