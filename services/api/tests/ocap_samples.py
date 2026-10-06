"""Sample OCAPs for the tests (ADR-0031), made here: the plant's real ones aren't in the repository. And a stand-in
for clamd.

- `vertical_pdf()`: OCAP-017, English, four pages, with a header and a "Page n of m" footer on each, numbered headings
  set bold and larger, and the heater-fault section on page 3.
- `nozzle_pdf()`: OCAP-021, Filipino, two pages.
- `bottom_docx()`: OCAP-030, a Word file with heading styles, a table, and a page break before its last section.
- `infected_docx()`: that Word file with the EICAR test file hidden inside it, which clamd finds (EICAR only counts at
  the start of a file, so one written after a PDF header passes a real clamd).
- `FakeClamd`: clamd's INSTREAM protocol on a free local port.
"""

from __future__ import annotations

import io
import socketserver
import struct
import threading
import zipfile

from centerline_api.settings import ScannerSettings

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"  # the harmless antivirus test file

VERTICAL = [
    (1, "OCAP-017: Vertical sealing temperature off its centerline", 16, None),
    (1, "1 Purpose", 13, "What the line does when a vertical heater's HMI setpoint or actual temperature leaves "
                         "its centerline. It applies to Vertical 1 to Vertical 6 on the Volpak filler."),
    (1, "2 Safety", 13, "The jaws are hot. Lock out the machine before touching a heater or a thermocouple. "
                        "Wear heat-resistant gloves."),
    (2, "3 Corrective actions", 13, None),
    (2, "3.1 HMI setpoint changed by mistake", 11,
     "If the HMI setpoint of a vertical heater differs from its centerline target, set it back to the target on "
     "the HMI. Check with the shift leader whether a new film roll or a trial asked for the change. Record the "
     "reason in Centerline."),
    (3, "3.2 Heater element or thermocouple fault", 11,
     "If the actual temperature stays below the setpoint while the HMI setpoint is on target, the heater element "
     "or its thermocouple may have failed. Check the heater's current, then the thermocouple's reading against a "
     "handheld probe. Replace the faulty part and test-seal ten sachets before releasing the line."),
    (4, "4 Escalation", 13, "Call the maintenance technician when the temperature doesn't come back within "
                            "15 minutes. Tell the Manager on shift about any product sealed outside the centerline."),
]

NOZZLE = [
    (1, "OCAP-021: Presyon ng nozzle na wala sa centerline", 16, None),
    (1, "1 Layunin", 13, "Ang gagawin kapag ang presyon ng nozzle ay mas mataas o mas mababa sa centerline. "
                         "Para ito sa lahat ng nozzle ng Volpak filler."),
    (2, "2 Mga hakbang kapag barado ang nozzle", 13,
     "Kapag tumaas ang presyon at bumaba ang dami ng laman ng sachet, maaaring barado ang nozzle. Itigil ang "
     "makina, linisin ang nozzle, at suriin ang filter bago muling patakbuhin."),
]


def _pdf(code: str, title: str, items: list) -> bytes:
    from fpdf import FPDF

    pages = max(p for p, *_ in items)

    class Ocap(FPDF):
        def header(self):
            self.set_font("helvetica", size=8)
            self.cell(0, 6, f"Volpak filler - {code} - {title}", new_x="LMARGIN", new_y="NEXT")
            self.ln(4)

        def footer(self):
            self.set_y(-15)
            self.set_font("helvetica", size=8)
            self.cell(0, 6, f"Page {self.page_no()} of {pages}", align="C")

    pdf = Ocap()
    pdf.set_auto_page_break(True, margin=20)
    for page, heading, size, body in items:
        while pdf.page_no() < page:
            pdf.add_page()
        pdf.set_font("helvetica", style="B", size=size)
        pdf.multi_cell(0, size * 0.5, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        if body:
            pdf.set_font("helvetica", size=10)
            pdf.multi_cell(0, 5, body, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
    return bytes(pdf.output())


def vertical_pdf() -> bytes:
    return _pdf("OCAP-017", "Vertical sealing temperature", VERTICAL)


def nozzle_pdf() -> bytes:
    return _pdf("OCAP-021", "Presyon ng nozzle", NOZZLE)


def bottom_docx() -> bytes:
    from docx import Document
    from docx.enum.text import WD_BREAK

    doc = Document()
    doc.add_heading("OCAP-030: Bottom sealing temperature", level=0)
    doc.add_heading("Purpose", level=1)
    doc.add_paragraph("What to do when the front or rear bottom sealing temperature leaves its centerline.")
    doc.add_heading("Checks", level=1)
    doc.add_paragraph("Compare the HMI setpoint with the centerline target for the bottom heater.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Zone", "Target"
    table.cell(1, 0).text, table.cell(1, 1).text = "Rear bottom", "180 °C"
    run = doc.add_paragraph().add_run()
    run.add_break(WD_BREAK.PAGE)
    doc.add_heading("Bottom heater fault", level=2)
    doc.add_paragraph("If the rear bottom actual temperature drops while its setpoint is on target, check the "
                      "heater cartridge and its fuse.")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def infected_docx() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bottom_docx())) as z, zipfile.ZipFile(out, "w") as w:
        for name in z.namelist():
            w.writestr(name, z.read(name))
        w.writestr("word/media/eicar.com", EICAR)
    return out.getvalue()


class FakeClamd:
    """clamd's INSTREAM: it answers FOUND for the EICAR test string, OK otherwise, or what `reply` says."""

    def __init__(self):
        self.scanned: list[bytes] = []
        self.reply: bytes | None = None
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                f = self.request.makefile("rb")
                command = b""
                while not command.endswith(b"\0"):
                    command += f.read(1)
                data = b""
                while (n := struct.unpack(">I", f.read(4))[0]) != 0:
                    data += f.read(n)
                fake.scanned.append(data)
                self.request.sendall(fake.reply or (b"stream: Eicar-Signature FOUND\0" if b"EICAR-STANDARD-ANTIVIRUS" in data
                                                    else b"stream: OK\0"))

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.settings = ScannerSettings("clamd", "127.0.0.1", self.server.server_address[1], 5)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
