"""OCAP files read into sections with their pages or rows, the reasons they offer, and the malware scanner's protocol
(ADR-0031, ADR-0039)."""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from centerline_api.ocap import parse
from centerline_api.ocap.choices import direction_of, propose
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


def test_only_pdf_word_and_excel_files_with_text_are_read():
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


EVERY = (parse.PDF, parse.DOCX, parse.XLSX)


def test_an_excel_workbook_is_read_row_by_row_with_its_sheet_rows_and_phenomenon():
    data = samples.sealer_xlsx()
    assert parse.sniff(data, EVERY) == parse.XLSX
    with pytest.raises(parse.Unreadable, match="not a Word document"):
        parse.sniff(data)  # a guidance's file is PDF or Word (GDE-01)
    parsed = parse.parse(data, parse.XLSX)
    assert parsed.pages is None
    assert [(s.sheet, s.row_from, s.row_to, s.heading, s.phenomenon) for s in parsed.sections] == [
        ("OCAP - Sealing", 4, 5, "1. Weak seal on the vertical side", "Weak seal on the vertical side"),  # merged rows: one block
        ("OCAP - Sealing", 6, 6, "2. Weak bottom seal", "Weak bottom seal"),
        ("OCAP - Sealing", 7, 7, "3. Weak top seal", "Weak top seal"),
        ("Troubleshooting", 1, 2, "SEALER TROUBLESHOOTING", None),  # its title lines, but not the OCAP sheet's lone title
        ("Troubleshooting", 4, 4, "1. Seal separates easily", "Seal separates easily"),
        ("Troubleshooting", 5, 5, "2. Burnt or brittle seal", "Burnt or brittle seal"),
        ("Troubleshooting", 6, 6, "3. Seal not centred on the cutter", "Seal not centred on the cutter"),
        ("Troubleshooting", 7, 7, "4. Vertical seal narrower than 6 mm", "Vertical seal narrower than 6 mm"),
        ("Troubleshooting", 9, 9, "Notes", None)]  # below the empty row; the hidden sheet isn't read
    first = parsed.sections[0]
    assert first.body.startswith("Phenomena: Weak seal on the vertical side\nAssembly: Vertical Sealer")
    assert "Inspection:\n1. Compare the vertical heaters on the HMI\n2. Check the seal width" in first.body
    assert "Why change?" not in first.body and "OCAP #" not in first.body  # the group header and the number column
    assert (first.area, first.cause) == ("Vertical Sealer Vertical Sealing 1 - 6", None)
    assert parsed.sections[4].cause == "Temperature too low; heater not warm yet"
    assert parsed.sections[-1].body == "CONTROL NOTE: tell the Cell Lead before running outside the centerline."


def test_a_workbook_that_unpacks_too_large_or_has_no_text_is_refused(monkeypatch):
    monkeypatch.setattr(parse, "UNPACKED_MAX", 1000)
    with pytest.raises(parse.Unreadable, match="unpacks to more than"):
        parse.parse(samples.sealer_xlsx(), parse.XLSX)
    monkeypatch.undo()
    with pytest.raises(parse.Unreadable, match="no text"):
        parse.parse(samples.xlsx([("Empty", {}, [], False)]), parse.XLSX)
    with pytest.raises(parse.Unreadable, match="save it as .docx or .xlsx"):
        parse.sniff(b"\xd0\xcf\x11\xe0 an old .xls", EVERY)


PARAMETERS = [{"id": "P02", "name": "Vertical Temperature"}, {"id": "P03", "name": "Bottom Temperature"},
              {"id": "P04", "name": "Top Temperature"}, {"id": "P05", "name": "Hopper Pressure"}, {"id": "P09", "name": "Pressure"}]


def test_a_rows_parameters_come_from_its_sealer_columns_and_its_direction_from_its_cause():
    assert propose("Top / Bottom / Vertical", "Seal separates easily", "Temperature too low", PARAMETERS) == (["P02", "P03", "P04"], "raised")
    assert propose("Vertical Sealer Vertical Sealing 1 - 6", None, None, PARAMETERS) == (["P02"], "either")
    assert propose("Cutter", "Seal not centred", "Temperature too high", PARAMETERS) == ([], "lowered")
    assert propose(None, "Weak bottom seal", "too low here, too high there", PARAMETERS) == (["P03"], "either")  # no area: the phenomenon
    assert propose("Hopper pressure", None, None, PARAMETERS) == (["P05", "P09"], "either")  # every word of a name
    assert [direction_of(222, 180), direction_of(170, 180), direction_of(180, 180), direction_of(None, 180)] == [
        "raised", "lowered", None, None]


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
    assert citation("OCAP-040", 1, "1. Weak seal", None, None, "OCAP - Sealing", 4, 5) == "OCAP-040 v1 · 1. Weak seal · OCAP - Sealing, rows 4–5"
    assert citation("OCAP-040", 1, "Notes", None, None, "Troubleshooting", 9, 9) == "OCAP-040 v1 · Notes · Troubleshooting, row 9"


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
