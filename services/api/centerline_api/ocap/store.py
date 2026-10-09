"""The OCAP library in the database (OCP-01…03, ADR-0031).

- An upload is checked (PDF, Word or Excel, 20 MB at most), scanned for malware, read into sections, and saved as a
  Draft version of its document, kept byte for byte.
- An Excel row that names a phenomenon is also a reason an operator can pick for an HMI mismatch (ADR-0039): for the
  parameters and the direction proposed from the file, which a Manager can change. Each change is a row in
  `ocap_reason_tag`, and audited.
- A Manager activates it, keeping or superseding the earlier active version, or suspends an active one. Each change
  is a row in `ocap_status`, and audited.
- The search, without AI, is PostgreSQL's full-text search over the Active versions' sections. English uses the
  `english` configuration, Filipino `simple` with its function words dropped. The document's title and the heading
  weigh more than the text.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re

from centerline_common.db import uuid7

from ..ai import embed as embed_mod
from ..config import audit
from ..config.audit import iso
from ..config.store import invalid
from ..config.versioning import reason_errors
from ..problems import Problem
from . import choices as choices_mod
from . import parse as parse_mod
from .translations import Translations
from .scan import ScannerUnavailable, scan

LANGUAGES = {"en": "english", "fil": "simple"}  # PostgreSQL has no Filipino stemmer
CHUNK_CHARS = 1200
LOCK = "centerline.ocap"
CANDIDATES = 10  # of each ranking, merged into the top three (ADR-0048)
RRF = 60  # reciprocal rank fusion's constant: a section ranked well by both beats one ranked first by only one
EXCERPT_CHARS = 240  # of a section found by meaning alone: its opening words
CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{0,39}")
# Filipino function words: left out of a query, or every Filipino section would match every reason
FILIPINO_STOPWORDS = sorted({
    "ang", "ng", "sa", "na", "at", "ay", "mga", "si", "ni", "kay", "para", "ito", "iyon", "iyan", "ko", "mo", "niya",
    "namin", "natin", "nila", "ka", "ako", "siya", "kami", "tayo", "sila", "din", "rin", "lang", "lamang", "po", "opo",
    "hindi", "oo", "may", "wala", "kung", "kapag", "pag", "dahil", "kasi", "pero", "o", "nang", "upang", "yung",
    "iyong", "dito", "doon", "diyan", "ba", "pa", "na", "nga", "naman", "kaya", "dapat", "isang", "ang", "mas"})


def decode_upload(content_base64: str, field: str = "contentBase64") -> bytes:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise invalid("The file can't be read", [{"field": field, "message": "Not base64: upload the file again"}]) from None
    if not data:
        raise invalid("The file is empty", [{"field": field, "message": "Choose a file"}])
    if len(data) > parse_mod.MAX_BYTES:
        raise invalid("The file is too large", [{"field": field, "message": "Larger than 20 MB"}])
    return data


def checked_file(conn, data: bytes, name: str, scanner, what: str,
                 kinds: tuple[str, ...] = (parse_mod.PDF, parse_mod.DOCX)) -> tuple[str, str, str]:
    """A file's type and its scan, or the reason it's refused: (media type, "clean" | "not_scanned", the scanner's
    answer). An infected file is refused and the refusal audited (SEC-01). A guidance's file is PDF or Word (GDE-01);
    an OCAP can also be Excel (ADR-0039)."""
    try:
        media_type = parse_mod.sniff(data, kinds)
    except parse_mod.Unreadable as e:
        raise invalid(str(e), [{"field": "contentBase64", "message": str(e)}]) from None
    try:
        verdict, detail = scan(data, scanner)
    except ScannerUnavailable as e:
        raise Problem(503, "scanner-unavailable", "The malware scanner isn't answering",
                      f"Uploads wait for it: {e}. Try again in a moment, or ask the Administrator.") from None
    if verdict == "infected":
        audit.record(conn, "upload.refused", f"{what} {name!r} refused: malware found ({detail})",
                     None, {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "found": detail})
        conn.commit()
        raise Problem(422, "malware-found", "The file was refused", f"The malware scanner found {detail} in it. "
                      "Nothing was saved.", errors=[{"field": "contentBase64", "message": f"Malware found: {detail}"}])
    return media_type, verdict, detail


def _chunks(body: str) -> list[str]:
    out, cur = [], ""
    for para in [p.strip() for p in body.split("\n") if p.strip()]:
        while len(para) > CHUNK_CHARS:  # one long paragraph: cut at a sentence
            cut = para.rfind(". ", 0, CHUNK_CHARS)
            cut = cut + 1 if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
            out.append(((cur + "\n") if cur else "") + para[:cut].strip())
            cur, para = "", para[cut:].strip()
        if cur and len(cur) + len(para) + 1 > CHUNK_CHARS:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        out.append(cur)
    return out


def citation(code: str, number: int, heading: str | None, page_from: int | None, page_to: int | None,
             sheet: str | None = None, row_from: int | None = None, row_to: int | None = None) -> str:
    if sheet is not None:  # an Excel section: its sheet and rows (ADR-0039)
        where = f" · {sheet}, row {row_from}" if row_to in (None, row_from) else f" · {sheet}, rows {row_from}–{row_to}"
    else:
        where = "" if page_from is None else (f" · p. {page_from}" if page_to in (None, page_from) else f" · pp. {page_from}–{page_to}")
    return f"{code} v{number} · {heading or 'Opening text'}{where}"


SECTION_COLUMNS = "s.id, s.ordinal, s.heading, s.level, s.page_from, s.page_to, s.body, s.sheet, s.row_from, s.row_to, s.phenomenon"


def _where(s: dict) -> dict:
    return {"pageFrom": s["page_from"], "pageTo": s["page_to"], "sheet": s["sheet"], "rowFrom": s["row_from"],
            "rowTo": s["row_to"]}


def _cite(code: str, number: int, s: dict) -> str:
    return citation(code, number, s["heading"], s["page_from"], s["page_to"], s["sheet"], s["row_from"], s["row_to"])


class OcapStore:
    def __init__(self, ai_translates: bool = False, ai=None):
        self.ai_translates = ai_translates  # the local AI translates the Active OCAPs into Tagalog (ADR-0045)
        self.ai = ai  # the AI settings: with an embedding model, the search goes by meaning too (ADR-0048)

    # -- saving ----------------------------------------------------------------------------------------------------

    @staticmethod
    def _insert(conn, document_id, title: str, code: str, language: str, source: str, media_type: str, original,
                sha: str, scan_status: str, scan_detail: str | None, parsed, reason: str, params: list[dict] | None = None) -> tuple:
        number = conn.execute("SELECT coalesce(max(number), 0) + 1 AS n FROM ocap_version WHERE document_id = %s",
                              (document_id,)).fetchone()["n"]
        vid, cfg = uuid7(), LANGUAGES[language]
        conn.execute(f"""INSERT INTO ocap_version (id, document_id, number, language, source, media_type, original, sha256,
                                                   scan, scan_detail, pages, reason, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (vid, document_id, number, language, source, media_type, original, sha, scan_status, scan_detail,
                      parsed.pages, reason))
        for i, s in enumerate(parsed.sections, start=1):
            sid = uuid7()
            conn.execute("""INSERT INTO ocap_section (id, version_id, ordinal, heading, level, page_from, page_to, body, sheet,
                                                      row_from, row_to, phenomenon)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                         (sid, vid, i, s.heading, s.level, s.page_from, s.page_to, s.body, s.sheet, s.row_from, s.row_to,
                          s.phenomenon))
            if s.phenomenon and params is not None:  # a reason an operator can pick, once a Manager activates it
                ids, direction = choices_mod.propose(s.area, s.phenomenon, s.cause, params)
                conn.execute(f"""INSERT INTO ocap_reason_tag (section_id, parameter_ids, direction, by_user, reason)
                                 VALUES (%s, %s, %s, {audit.ACTOR}, 'Proposed from the file')""", (sid, ids, direction))
            for j, text in enumerate(_chunks(s.body), start=1):
                conn.execute("""INSERT INTO ocap_chunk (id, section_id, ordinal, body, tsv)
                                VALUES (%s, %s, %s, %s, setweight(to_tsvector(%s::regconfig, %s), 'A')
                                                     || setweight(to_tsvector(%s::regconfig, %s), 'D'))""",
                             (uuid7(), sid, j, text, cfg, f"{code} {title} {s.heading or ''}", cfg, text))
        conn.execute(f"INSERT INTO ocap_status (version_id, status, by_user, reason) VALUES (%s, 'draft', {audit.ACTOR}, %s)",
                     (vid, reason))
        return vid, number

    @staticmethod
    def _fields(body, document: bool) -> list[dict]:
        errors = reason_errors(body.reason)
        if body.language not in LANGUAGES:
            errors.append({"field": "language", "message": "English (en) or Filipino (fil)"})
        if document:
            if not CODE.fullmatch(body.code.strip()):
                errors.append({"field": "code", "message": "The OCAP's code, e.g. OCAP-017: letters, digits, . _ / -"})
            if not body.title.strip() or len(body.title.strip()) > 200:
                errors.append({"field": "title", "message": "A title, 200 characters at most"})
        return errors

    def _check_code(self, conn, code: str) -> None:
        if conn.execute("SELECT 1 FROM ocap_document WHERE lower(code) = lower(%s)", (code.strip(),)).fetchone():
            raise invalid("That code is taken", [{"field": "code", "message": f"{code.strip()} already exists: upload a new version of it"}])

    @staticmethod
    def _read(conn, code: str, body, scanner) -> tuple:
        """The upload checked, scanned and read, before anything is saved: a refusal commits only its audit entry."""
        data = decode_upload(body.content_base64)
        name = body.source.strip() or "upload"
        media_type, verdict, detail = checked_file(conn, data, name, scanner, f"OCAP {code}",
                                                   (parse_mod.PDF, parse_mod.DOCX, parse_mod.XLSX))
        try:
            parsed = parse_mod.parse(data, media_type)
        except parse_mod.Unreadable as e:
            raise invalid(str(e), [{"field": "contentBase64", "message": str(e)}]) from None
        return data, name, media_type, verdict, detail, parsed

    def _save(self, conn, document_id, code: str, title: str, body, read: tuple, register):
        data, name, media_type, verdict, detail, parsed = read
        sha = hashlib.sha256(data).hexdigest()
        vid, number = self._insert(conn, document_id, title, code, body.language, name, media_type, data, sha, verdict,
                                   detail, parsed, body.reason.strip(), choices_mod.parameters(register))
        pages = f", {parsed.pages} page{'s' if parsed.pages != 1 else ''}" if parsed.pages else ""
        reasons = sum(1 for s in parsed.sections if s.phenomenon)
        pages += f", {reasons} reason{'s' if reasons != 1 else ''} to pick" if reasons else ""
        audit.record(conn, "ocap.version", f"{code} v{number} uploaded from {name}: {len(parsed.sections)} sections{pages}"
                     f"{'' if verdict == 'clean' else ', not scanned'} (draft)", body.reason,
                     {"version": str(vid), "number": number, "sha256": sha, "scan": verdict})
        return vid

    def create(self, conn, body, scanner, register):
        """A new OCAP with its first version, a Draft. Commits; returns the version's id."""
        if errors := self._fields(body, True):
            raise invalid("The OCAP can't be saved", errors)
        self._check_code(conn, body.code)
        read = self._read(conn, body.code.strip(), body, scanner)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        self._check_code(conn, body.code)  # again, under the lock
        did = uuid7()
        conn.execute(f"INSERT INTO ocap_document (id, code, title, created_by) VALUES (%s, %s, %s, {audit.ACTOR})",
                     (did, body.code.strip(), body.title.strip()))
        vid = self._save(conn, did, body.code.strip(), body.title.strip(), body, read, register)
        conn.commit()
        return vid

    def add_version(self, conn, document_id, body, scanner, register):
        """A new Draft version of an OCAP. Commits; returns its id."""
        doc = self._document(conn, document_id)
        if errors := self._fields(body, False):
            raise invalid("The version can't be saved", errors)
        read = self._read(conn, doc["code"], body, scanner)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        vid = self._save(conn, doc["id"], doc["code"], doc["title"], body, read, register)
        conn.commit()
        return vid

    def write(self, conn, code: str, title: str, language: str, text: str, reason: str) -> tuple:
        """A reusable OCAP written in Centerline, from a Manager's guidance (GDE-01): active at once. The caller commits."""
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        self._check_code(conn, code)
        did = uuid7()
        conn.execute(f"INSERT INTO ocap_document (id, code, title, created_by) VALUES (%s, %s, %s, {audit.ACTOR})",
                     (did, code.strip(), title.strip()))
        parsed = parse_mod.from_text(title, text)
        vid, number = self._insert(conn, did, title.strip(), code.strip(), language, parse_mod.WRITTEN, parse_mod.TEXT, None,
                                   hashlib.sha256(text.encode("utf-8")).hexdigest(), "written", None, parsed, reason)
        conn.execute(f"INSERT INTO ocap_status (version_id, status, by_user, reason) VALUES (%s, 'active', {audit.ACTOR}, %s)",
                     (vid, reason))
        audit.record(conn, "ocap.version", f"{code.strip()} v{number} written in Centerline and activated", reason,
                     {"version": str(vid), "number": number})
        return vid, number

    # -- status ----------------------------------------------------------------------------------------------------

    @staticmethod
    def _version(conn, version_id) -> dict:
        v = conn.execute("""SELECT v.id, v.number, v.document_id, d.code, d.title, s.status FROM ocap_version v
                              JOIN ocap_document d ON d.id = v.document_id JOIN ocap_version_status s ON s.version_id = v.id
                             WHERE v.id = %s""", (version_id,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such OCAP version", "Reload the page")
        return v

    @staticmethod
    def _document(conn, document_id) -> dict:
        d = conn.execute("SELECT id, code, title FROM ocap_document WHERE id = %s", (document_id,)).fetchone()
        if d is None:
            raise Problem(404, "not-found", "No such OCAP", "Reload the page")
        return d

    def activate(self, conn, version_id, reason: str, earlier: str) -> None:
        """Searched from now on (OCP-01); the document's other active versions stay so or are superseded (OCP-03)."""
        if errors := reason_errors(reason):
            raise invalid("It can't be activated", errors)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        v = self._version(conn, version_id)
        if v["status"] == "active":
            raise Problem(409, "already-active", "Already active", f"{v['code']} v{v['number']} is already active")
        others = conn.execute("""SELECT v.id, v.number FROM ocap_version v JOIN ocap_version_status s ON s.version_id = v.id
                                  WHERE v.document_id = %s AND v.id <> %s AND s.status = 'active' ORDER BY v.number""",
                              (v["document_id"], version_id)).fetchall()
        conn.execute(f"INSERT INTO ocap_status (version_id, status, by_user, reason) VALUES (%s, 'active', {audit.ACTOR}, %s)",
                     (version_id, reason.strip()))
        what = f"{v['code']} v{v['number']} activated"
        if others and earlier == "supersede":
            for o in others:
                conn.execute(f"""INSERT INTO ocap_status (version_id, status, by_user, reason)
                                 VALUES (%s, 'superseded', {audit.ACTOR}, %s)""", (o["id"], reason.strip()))
            what += "; " + ", ".join(f"v{o['number']}" for o in others) + " superseded"
        elif others:
            what += "; " + ", ".join(f"v{o['number']}" for o in others) + " stay active"
        audit.record(conn, "ocap.activate", what, reason, {"version": str(version_id), "earlier": earlier})
        conn.commit()

    def suspend(self, conn, version_id, reason: str) -> None:
        if errors := reason_errors(reason):
            raise invalid("It can't be suspended", errors)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        v = self._version(conn, version_id)
        if v["status"] != "active":
            raise Problem(409, "not-active", "Not active", f"{v['code']} v{v['number']} isn't active")
        conn.execute(f"INSERT INTO ocap_status (version_id, status, by_user, reason) VALUES (%s, 'suspended', {audit.ACTOR}, %s)",
                     (version_id, reason.strip()))
        audit.record(conn, "ocap.suspend", f"{v['code']} v{v['number']} suspended", reason, {"version": str(version_id)})
        conn.commit()

    # -- reading ---------------------------------------------------------------------------------------------------

    @staticmethod
    def listing(conn) -> dict:
        rows = conn.execute("""SELECT d.id AS document_id, d.code, d.title, v.id, v.number, v.language, v.source, v.media_type,
                                      v.scan, v.pages, v.created_at, v.created_by, v.reason, s.status, s.at AS status_at,
                                      s.by_user AS status_by, (SELECT count(*) FROM ocap_section x WHERE x.version_id = v.id) AS sections
                                 FROM ocap_document d JOIN ocap_version v ON v.document_id = d.id
                                 JOIN ocap_version_status s ON s.version_id = v.id
                                ORDER BY lower(d.code), v.number DESC""").fetchall()
        docs: dict = {}
        for r in rows:
            d = docs.setdefault(r["document_id"], {"id": str(r["document_id"]), "code": r["code"], "title": r["title"],
                                                   "versions": []})
            d["versions"].append({"id": str(r["id"]), "number": r["number"], "language": r["language"], "source": r["source"],
                                  "mediaType": r["media_type"], "scan": r["scan"], "pages": r["pages"], "sections": r["sections"],
                                  "createdAt": iso(r["created_at"]), "by": r["created_by"], "reason": r["reason"],
                                  "status": r["status"], "statusAt": iso(r["status_at"]), "statusBy": r["status_by"]})
        for d in docs.values():
            d["active"] = [v["number"] for v in d["versions"] if v["status"] == "active"]
        return {"documents": list(docs.values()),
                "counts": {"documents": len(docs), "active": sum(1 for d in docs.values() if d["active"])}}

    def version(self, conn, version_id, register) -> dict:
        v = conn.execute("""SELECT v.*, d.code, d.title, s.status FROM ocap_version v JOIN ocap_document d ON d.id = v.document_id
                              JOIN ocap_version_status s ON s.version_id = v.id WHERE v.id = %s""", (version_id,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such OCAP version", "Reload the page")
        sections = conn.execute(f"""SELECT {SECTION_COLUMNS}, c.parameter_ids, c.direction, c.at AS tag_at, c.by_user AS tag_by,
                                           c.reason AS tag_reason
                                      FROM ocap_section s LEFT JOIN ocap_reason_choice c ON c.section_id = s.id
                                     WHERE s.version_id = %s ORDER BY s.ordinal""", (version_id,)).fetchall()
        history = conn.execute("SELECT status, at, by_user, reason FROM ocap_status WHERE version_id = %s ORDER BY seq",
                               (version_id,)).fetchall()
        translations, tagalog = Translations.of_version(conn, version_id)
        by_ai = Translations.by_ai(conn, [s["id"] for s in sections])
        kept = {sid for sid, a in by_ai.items() if a["outcome"] == "rejected"}
        intact = v["original"] is None or hashlib.sha256(bytes(v["original"])).hexdigest() == v["sha256"]
        return {"id": str(v["id"]), "documentId": str(v["document_id"]), "code": v["code"], "title": v["title"],
                "number": v["number"], "language": v["language"], "source": v["source"], "mediaType": v["media_type"],
                "sha256": v["sha256"], "intact": intact, "scan": v["scan"], "scanDetail": v["scan_detail"], "pages": v["pages"],
                "createdAt": iso(v["created_at"]), "by": v["created_by"], "reason": v["reason"], "status": v["status"],
                "sections": [{"id": str(s["id"]), "ordinal": s["ordinal"], "heading": s["heading"], "level": s["level"],
                              **_where(s), "body": s["body"], "citation": _cite(v["code"], v["number"], s),
                              "phenomenon": s["phenomenon"],
                              "fil": tagalog.get(s["id"]),
                              # Why the AI's translation of it isn't shown: it failed a check (ADR-0045)
                              "filNote": by_ai[s["id"]]["detail"] if s["id"] in kept and s["id"] not in tagalog else None,
                              "reason": None if s["phenomenon"] is None else {
                                  "parameterIds": s["parameter_ids"] or [], "direction": s["direction"] or "either",
                                  "at": iso(s["tag_at"]), "by": s["tag_by"], "why": s["tag_reason"]}}
                             for s in sections],
                # What a reason can be offered for: the parameters whose HMI setpoints are judged (ADR-0039)
                "reasonParameters": choices_mod.parameters(register),
                # Its checked Tagalog versions, newest first (ADR-0044)
                "translations": translations,
                # The local AI's Tagalog (ADR-0045): translated once the version is Active, a section at a time
                "aiTagalog": {"on": self.ai_translates, "translated": sum(1 for a in by_ai.values() if a["text"]), "english": len(kept),
                              "waiting": sum(1 for s in sections if s["id"] not in by_ai or by_ai[s["id"]]["outcome"] in ("failed", "timeout"))},
                "history": [{"status": h["status"], "at": iso(h["at"]), "by": h["by_user"], "reason": h["reason"]} for h in history]}

    @staticmethod
    def original(conn, version_id) -> tuple[str, str, bytes]:
        v = conn.execute("SELECT source, media_type, original FROM ocap_version WHERE id = %s", (version_id,)).fetchone()
        if v is None or v["original"] is None:
            raise Problem(404, "not-found", "No file", "This version has no file: it was written in Centerline")
        return v["source"], v["media_type"], bytes(v["original"])

    @staticmethod
    def sections(conn, ids: list) -> dict:
        """Sections by id, with their document, version and citation: what an operator reads (OCP-02)."""
        if not ids:
            return {}
        rows = conn.execute(f"""SELECT {SECTION_COLUMNS}, v.id AS version_id, v.number, v.language,
                                       v.original IS NOT NULL AS has_file, d.code, d.title, st.status
                                  FROM ocap_section s JOIN ocap_version v ON v.id = s.version_id
                                  JOIN ocap_document d ON d.id = v.document_id JOIN ocap_version_status st ON st.version_id = v.id
                                 WHERE s.id = ANY(%s)""", (list(ids),)).fetchall()
        tagalog = Translations.active(conn, [r["id"] for r in rows])
        return {r["id"]: {"sectionId": str(r["id"]), "versionId": str(r["version_id"]), "code": r["code"], "title": r["title"],
                          "version": r["number"], "language": r["language"], "heading": r["heading"], **_where(r),
                          "body": r["body"], "status": r["status"], "hasFile": r["has_file"], "citation": _cite(r["code"], r["number"], r),
                          "fil": tagalog.get(r["id"])}  # its checked Tagalog text, once a Manager activated it (ADR-0044)
                for r in rows}

    # -- reasons to pick (ADR-0039) ----------------------------------------------------------------------------

    def tag(self, conn, section_id, parameter_ids: list[str], direction: str, reason: str, register) -> None:
        """Which HMI mismatches offer this row as a reason, from now on. Commits."""
        errors = reason_errors(reason)
        known = {p["id"] for p in choices_mod.parameters(register)}
        unknown = [p for p in parameter_ids if p not in known]
        if unknown:
            errors.append({"field": "parameterIds", "message": f"Not a parameter whose HMI setpoint is judged: {', '.join(unknown)}"})
        if direction not in choices_mod.DIRECTIONS:
            errors.append({"field": "direction", "message": "raised, lowered or either"})
        if errors:
            raise invalid("It can't be saved", errors)
        s = conn.execute("""SELECT s.id, s.heading, s.phenomenon, v.number, d.code FROM ocap_section s
                              JOIN ocap_version v ON v.id = s.version_id JOIN ocap_document d ON d.id = v.document_id
                             WHERE s.id = %s""", (section_id,)).fetchone()
        if s is None:
            raise Problem(404, "not-found", "No such section", "Reload the page")
        if s["phenomenon"] is None:
            raise Problem(409, "not-a-reason", "This section isn't a reason", "Only an Excel row that names a phenomenon can be picked as a reason")
        ids = [p["id"] for p in choices_mod.parameters(register) if p["id"] in set(parameter_ids)]  # the register's order
        conn.execute(f"""INSERT INTO ocap_reason_tag (section_id, parameter_ids, direction, by_user, reason)
                         VALUES (%s, %s, %s, {audit.ACTOR}, %s)""", (section_id, ids, direction, reason.strip()))
        when = "" if direction == "either" else f", when {direction}"
        audit.record(conn, "ocap.reason", f"{s['code']} v{s['number']} · {s['heading']}: offered as a reason for "
                     f"{', '.join(ids) or 'no parameter'}{when}", reason,
                     {"section": str(section_id), "parameters": ids, "direction": direction})
        conn.commit()

    @staticmethod
    def choices(conn, parameter_id: str, direction: str | None) -> list[dict]:
        """The reasons an operator can pick for an HMI mismatch on this parameter: rows of the Active versions, those
        for this direction first, each in its OCAP's order."""
        rows = conn.execute(f"""SELECT {SECTION_COLUMNS}, c.direction, v.number, d.code, d.title
                                  FROM ocap_reason_choice c JOIN ocap_section s ON s.id = c.section_id
                                  JOIN ocap_version v ON v.id = s.version_id JOIN ocap_document d ON d.id = v.document_id
                                  JOIN ocap_version_status st ON st.version_id = v.id AND st.status = 'active'
                                 WHERE %s = ANY(c.parameter_ids) AND (c.direction = 'either' OR c.direction = %s)
                                 ORDER BY c.direction = 'either', lower(d.code), v.number, s.ordinal""",
                            (parameter_id, direction or "either")).fetchall()
        tagalog = Translations.active(conn, [r["id"] for r in rows])
        return [{"sectionId": str(r["id"]), "label": r["phenomenon"], "code": r["code"], "title": r["title"],
                 "version": r["number"], "direction": r["direction"], **_where(r), "citation": _cite(r["code"], r["number"], r),
                 "labelFil": (tagalog.get(r["id"]) or {}).get("phenomenon")}
                for r in rows]

    def search(self, conn, text: str, limit: int = 3, meaning: str | None = None) -> list[dict]:
        """The Active versions' sections that best match, best first: by their keywords and, with the embedding model
        on, by meaning (`meaning`, else `text`), the two rankings merged by reciprocal rank fusion (ADR-0048). Each says
        how it was found ("keyword" or "hybrid") and carries an excerpt, the keywords' matches highlighted («…»)."""
        keywords = self.keywords(conn, text, CANDIDATES)
        near = self.by_meaning(conn, meaning or text, CANDIDATES)
        if not near:
            return [k | {"method": "keyword"} for k in keywords[:limit]]
        fused: dict[str, float] = {}
        for ranking in ([k["sectionId"] for k in keywords], [sid for sid, _ in near]):
            for rank, sid in enumerate(ranking, start=1):
                fused[sid] = fused.get(sid, 0.0) + 1 / (RRF + rank)
        best = sorted(fused, key=lambda sid: -fused[sid])[:limit]
        by_keyword = {k["sectionId"]: k for k in keywords}
        found = OcapStore.sections(conn, [sid for sid in best if sid not in by_keyword])
        found = {str(k): v for k, v in found.items()}
        return [(by_keyword.get(sid) or found[sid] | {"excerpt": found[sid]["body"][:EXCERPT_CHARS]})
                | {"score": round(fused[sid], 4), "method": "hybrid"} for sid in best]

    def by_meaning(self, conn, text: str, limit: int) -> list[tuple[str, float]] | None:
        """The Active sections nearest in meaning to `text`, as (section id, similarity), nearest first, those below
        `min_similarity` left out; None when the embedding model can't be used (ADR-0048)."""
        if self.ai is None:
            return None
        q = embed_mod.query(self.ai, text)
        if q is None:
            return None
        model, digest, vector = q
        rows = conn.execute("""SELECT c.section_id, max(1 - (e.embedding <=> %s::vector)) AS similarity
                                 FROM ocap_chunk_embedding e JOIN ocap_chunk c ON c.id = e.chunk_id
                                 JOIN ocap_section s ON s.id = c.section_id
                                 JOIN ocap_version_status st ON st.version_id = s.version_id AND st.status = 'active'
                                WHERE e.model = %s AND e.model_digest = %s
                                GROUP BY c.section_id ORDER BY similarity DESC LIMIT %s""", (vector, model, digest, limit)).fetchall()
        return [(str(r["section_id"]), float(r["similarity"])) for r in rows if r["similarity"] >= self.ai.min_similarity]

    @staticmethod
    def keywords(conn, text: str, limit: int = 3) -> list[dict]:
        """The Active versions' sections that best match `text`'s keywords, best first, with a highlighted excerpt («…»)."""
        q = """WITH words AS (
                   SELECT (SELECT string_agg(quote_literal(l), ' | ') FROM unnest(tsvector_to_array(to_tsvector('english', %(t)s))) l) AS en,
                          (SELECT string_agg(quote_literal(l), ' | ') FROM unnest(tsvector_to_array(to_tsvector('simple', %(t)s))) l
                            WHERE l <> ALL(%(stop)s) AND length(l) > 1) AS fil),
               q AS (SELECT CASE WHEN en IS NULL THEN NULL ELSE to_tsquery('simple', en) END AS en,
                            CASE WHEN fil IS NULL THEN NULL ELSE to_tsquery('simple', fil) END AS fil FROM words),
               hits AS (
                   SELECT c.section_id, max(ts_rank_cd(c.tsv, CASE WHEN v.language = 'en' THEN q.en ELSE q.fil END, 32)) AS score
                     FROM ocap_chunk c JOIN ocap_section s ON s.id = c.section_id JOIN ocap_version v ON v.id = s.version_id
                     JOIN ocap_version_status st ON st.version_id = v.id AND st.status = 'active', q
                    WHERE c.tsv @@ (CASE WHEN v.language = 'en' THEN q.en ELSE q.fil END)
                    GROUP BY c.section_id)
               SELECT h.section_id, h.score,
                      ts_headline(CASE WHEN v.language = 'en' THEN 'english' ELSE 'simple' END::regconfig, s.body,
                                  CASE WHEN v.language = 'en' THEN q.en ELSE q.fil END,
                                  'StartSel=«, StopSel=», MaxFragments=2, MaxWords=30, MinWords=12') AS excerpt
                 FROM hits h JOIN ocap_section s ON s.id = h.section_id JOIN ocap_version v ON v.id = s.version_id, q
                ORDER BY h.score DESC, v.created_at DESC, s.ordinal
                LIMIT %(limit)s"""
        rows = conn.execute(q, {"t": text, "stop": FILIPINO_STOPWORDS, "limit": limit}).fetchall()
        found = OcapStore.sections(conn, [r["section_id"] for r in rows])
        return [found[r["section_id"]] | {"score": round(float(r["score"]), 4), "excerpt": r["excerpt"]} for r in rows]
