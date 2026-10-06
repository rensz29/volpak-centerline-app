"""The OCAP library in the database (OCP-01…03, ADR-0031).

- An upload is checked (PDF or Word, 20 MB at most), scanned for malware, read into sections, and saved as a Draft
  version of its document, kept byte for byte.
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

from ..config import audit
from ..config.audit import iso
from ..config.store import invalid
from ..config.versioning import reason_errors
from ..problems import Problem
from . import parse as parse_mod
from .scan import ScannerUnavailable, scan

LANGUAGES = {"en": "english", "fil": "simple"}  # PostgreSQL has no Filipino stemmer
CHUNK_CHARS = 1200
LOCK = "centerline.ocap"
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


def checked_file(conn, data: bytes, name: str, scanner, what: str) -> tuple[str, str, str]:
    """A file's type and its scan, or the reason it's refused: (media type, "clean" | "not_scanned", the scanner's
    answer). An infected file is refused and the refusal audited (SEC-01)."""
    try:
        media_type = parse_mod.sniff(data)
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


def citation(code: str, number: int, heading: str | None, page_from: int | None, page_to: int | None) -> str:
    pages = "" if page_from is None else (f" · p. {page_from}" if page_to in (None, page_from) else f" · pp. {page_from}–{page_to}")
    return f"{code} v{number} · {heading or 'Opening text'}{pages}"


class OcapStore:
    # -- saving ----------------------------------------------------------------------------------------------------

    @staticmethod
    def _insert(conn, document_id, title: str, code: str, language: str, source: str, media_type: str, original,
                sha: str, scan_status: str, scan_detail: str | None, parsed, reason: str) -> tuple:
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
            conn.execute("""INSERT INTO ocap_section (id, version_id, ordinal, heading, level, page_from, page_to, body)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                         (sid, vid, i, s.heading, s.level, s.page_from, s.page_to, s.body))
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
        media_type, verdict, detail = checked_file(conn, data, name, scanner, f"OCAP {code}")
        try:
            parsed = parse_mod.parse(data, media_type)
        except parse_mod.Unreadable as e:
            raise invalid(str(e), [{"field": "contentBase64", "message": str(e)}]) from None
        return data, name, media_type, verdict, detail, parsed

    def _save(self, conn, document_id, code: str, title: str, body, read: tuple):
        data, name, media_type, verdict, detail, parsed = read
        sha = hashlib.sha256(data).hexdigest()
        vid, number = self._insert(conn, document_id, title, code, body.language, name, media_type, data, sha, verdict,
                                   detail, parsed, body.reason.strip())
        pages = f", {parsed.pages} page{'s' if parsed.pages != 1 else ''}" if parsed.pages else ""
        audit.record(conn, "ocap.version", f"{code} v{number} uploaded from {name}: {len(parsed.sections)} sections{pages}"
                     f"{'' if verdict == 'clean' else ', not scanned'} (draft)", body.reason,
                     {"version": str(vid), "number": number, "sha256": sha, "scan": verdict})
        return vid

    def create(self, conn, body, scanner):
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
        vid = self._save(conn, did, body.code.strip(), body.title.strip(), body, read)
        conn.commit()
        return vid

    def add_version(self, conn, document_id, body, scanner):
        """A new Draft version of an OCAP. Commits; returns its id."""
        doc = self._document(conn, document_id)
        if errors := self._fields(body, False):
            raise invalid("The version can't be saved", errors)
        read = self._read(conn, doc["code"], body, scanner)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK,))
        vid = self._save(conn, doc["id"], doc["code"], doc["title"], body, read)
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

    @staticmethod
    def version(conn, version_id) -> dict:
        v = conn.execute("""SELECT v.*, d.code, d.title, s.status FROM ocap_version v JOIN ocap_document d ON d.id = v.document_id
                              JOIN ocap_version_status s ON s.version_id = v.id WHERE v.id = %s""", (version_id,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such OCAP version", "Reload the page")
        sections = conn.execute("""SELECT id, ordinal, heading, level, page_from, page_to, body FROM ocap_section
                                    WHERE version_id = %s ORDER BY ordinal""", (version_id,)).fetchall()
        history = conn.execute("SELECT status, at, by_user, reason FROM ocap_status WHERE version_id = %s ORDER BY seq",
                               (version_id,)).fetchall()
        intact = v["original"] is None or hashlib.sha256(bytes(v["original"])).hexdigest() == v["sha256"]
        return {"id": str(v["id"]), "documentId": str(v["document_id"]), "code": v["code"], "title": v["title"],
                "number": v["number"], "language": v["language"], "source": v["source"], "mediaType": v["media_type"],
                "sha256": v["sha256"], "intact": intact, "scan": v["scan"], "scanDetail": v["scan_detail"], "pages": v["pages"],
                "createdAt": iso(v["created_at"]), "by": v["created_by"], "reason": v["reason"], "status": v["status"],
                "sections": [{"id": str(s["id"]), "ordinal": s["ordinal"], "heading": s["heading"], "level": s["level"],
                              "pageFrom": s["page_from"], "pageTo": s["page_to"], "body": s["body"],
                              "citation": citation(v["code"], v["number"], s["heading"], s["page_from"], s["page_to"])}
                             for s in sections],
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
        rows = conn.execute("""SELECT s.id, s.heading, s.page_from, s.page_to, s.body, v.id AS version_id, v.number, v.language,
                                      v.original IS NOT NULL AS has_file, d.code, d.title, st.status
                                 FROM ocap_section s JOIN ocap_version v ON v.id = s.version_id
                                 JOIN ocap_document d ON d.id = v.document_id JOIN ocap_version_status st ON st.version_id = v.id
                                WHERE s.id = ANY(%s)""", (list(ids),)).fetchall()
        return {r["id"]: {"sectionId": str(r["id"]), "versionId": str(r["version_id"]), "code": r["code"], "title": r["title"],
                          "version": r["number"], "language": r["language"], "heading": r["heading"], "pageFrom": r["page_from"],
                          "pageTo": r["page_to"], "body": r["body"], "status": r["status"], "hasFile": r["has_file"],
                          "citation": citation(r["code"], r["number"], r["heading"], r["page_from"], r["page_to"])}
                for r in rows}

    @staticmethod
    def search(conn, text: str, limit: int = 3) -> list[dict]:
        """The Active versions' sections that best match `text`, best first, with a highlighted excerpt («…»)."""
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
