"""OCAP files read into sections with their pages, and the malware scanner's protocol (ADR-0031)."""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from centerline_api.ocap import parse
from centerline_api.ocap.scan import ScannerUnavailable, scan
from centerline_api.ocap.store import _chunks, citation
from centerline_api.settings import ScannerSettings

from . import ocap_samples as samples
from .ocap_samples import FakeClamd


def headings(parsed) -> list[tuple]:
    return [(s.heading, s.level, s.page_from, s.page_to) for s in parsed.sections]


def test_a_pdf_is_read_into_its_numbered_sections_with_their_pages_and_without_headers_or_footers():
    parsed = parse.parse(samples.vertical_pdf(), parse.PDF)
    assert parsed.pages == 4
    assert headings(parsed) == [
        ("OCAP-017: Vertical sealing temperature off its centerline", 1, 1, 1), ("1 Purpose", 1, 1, 1), ("2 Safety", 1, 1, 1),
        ("3 Corrective actions", 1, 2, 2), ("3.1 HMI setpoint changed by mistake", 2, 2, 2),
        ("3.2 Heater element or thermocouple fault", 2, 3, 3), ("4 Escalation", 1, 4, 4)]
    text = " ".join(s.body for s in parsed.sections)
    assert "Volpak filler - OCAP-017" not in text and "Page 2 of 4" not in text  # repeated on every page
    fault = parsed.sections[5].body
    assert fault.startswith("If the actual temperature stays below the setpoint") and "test-seal ten sachets" in fault


def test_a_filipino_pdf_and_a_word_file_with_its_styles_and_page_break():
    nozzle = parse.parse(samples.nozzle_pdf(), parse.sniff(samples.nozzle_pdf()))
    assert [s.heading for s in nozzle.sections][1:] == ["1 Layunin", "2 Mga hakbang kapag barado ang nozzle"]
    word = parse.parse(samples.bottom_docx(), parse.sniff(samples.bottom_docx()))
    assert word.pages == 2
    assert headings(word) == [("OCAP-030: Bottom sealing temperature", 1, 1, 1), ("Purpose", 1, 1, 1),
                              ("Checks", 1, 1, 1), ("Bottom heater fault", 2, 2, 2)]
    assert "Rear bottom | 180 °C" in word.sections[2].body  # a table, row by row


def test_only_pdf_and_word_files_with_text_are_read():
    for data, why in ((b"\xd0\xcf\x11\xe0 an old .doc", "save it as .docx"), (b"plain text", "Only PDF and Word"),
                      (_zip({"x.txt": b"x"}), "not a Word document")):
        with pytest.raises(parse.Unreadable, match=why):
            parse.sniff(data)
    from fpdf import FPDF

    blank = FPDF()
    blank.add_page()
    with pytest.raises(parse.Unreadable, match="needs OCR"):
        parse.parse(bytes(blank.output()), parse.PDF)
    with pytest.raises(parse.Unreadable, match="damaged"):
        parse.parse(b"%PDF-1.4 not really a pdf", parse.PDF)


def test_text_written_in_centerline_is_one_section_or_split_at_its_headings():
    assert headings(parse.from_text("Guidance for V1", "Set V1 back to 220 °C.")) == [("Guidance for V1", 1, None, None)]
    two = parse.from_text("Film change", "# Before\nStop the line.\n## After\nCheck the seal.")
    assert [(s.heading, s.level, s.body) for s in two.sections] == [("Before", 1, "Stop the line."), ("After", 2, "Check the seal.")]


def test_long_sections_are_searched_in_pieces_and_cited_with_their_pages():
    body = "\n".join(f"Step {i}: " + "check the heater and the thermocouple. " * 8 for i in range(12))
    pieces = _chunks(body)
    assert len(pieces) > 3 and all(len(p) <= 1200 for p in pieces) and "".join(pieces).count("Step") == 12
    assert citation("OCAP-017", 2, "3.2 Heater fault", 3, 4) == "OCAP-017 v2 · 3.2 Heater fault · pp. 3–4"
    assert citation("OCAP-030", 1, None, None, None) == "OCAP-030 v1 · Opening text"


@pytest.fixture
def clamd():
    fake = FakeClamd()
    yield fake
    fake.close()


def test_the_scanner_streams_the_file_and_reads_clamds_verdict(clamd):
    data = samples.vertical_pdf()
    assert scan(data, clamd.settings) == ("clean", "stream: OK") and clamd.scanned[-1] == data  # in 64 KiB pieces
    assert scan(samples.infected_docx(), clamd.settings) == ("infected", "Eicar-Signature")
    clamd.reply = b"INSTREAM size limit exceeded. ERROR\0"
    with pytest.raises(ScannerUnavailable, match="size limit"):
        scan(data, clamd.settings)
    with pytest.raises(ScannerUnavailable):
        scan(data, ScannerSettings("clamd", "127.0.0.1", 9, 1))  # nothing listening
    assert scan(data, ScannerSettings())[0] == "not_scanned"  # a development PC


def _zip(files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


@pytest.mark.skipif(not os.environ.get("CENTERLINE_TEST_CLAMD"), reason="set CENTERLINE_TEST_CLAMD=host:port to scan with a real clamd")
def test_a_real_clamd_finds_the_test_file_hidden_in_a_word_file_and_passes_the_samples():
    host, port = os.environ["CENTERLINE_TEST_CLAMD"].rsplit(":", 1)
    real = ScannerSettings("clamd", host, int(port), 60)
    assert scan(samples.infected_docx(), real) == ("infected", "Eicar-Test-Signature")
    for clean in (samples.vertical_pdf(), samples.nozzle_pdf(), samples.bottom_docx()):
        assert scan(clean, real) == ("clean", "stream: OK")
