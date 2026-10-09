"""A checked Tagalog version of an OCAP version (LAN-01, OCP-02, ADR-0044).

The plant's own translation, never the AI's: a Manager uploads it against the version it translates; it's scanned,
read like an OCAP and paired with the version section by section (an Excel workbook by sheet and rows, PDF or Word by
order). Every section must have its match, or nothing is saved. It's a Draft until a Manager activates it; then the
operator's chat shows it in Tagalog, always beside the English, which stays the authoritative text. A newer one for the
same version supersedes it; it can be withdrawn. Every change is audited.

Since ADR-0045 it's optional: without one, operators read the local AI's translation, the sections that passed its
checks. An active checked one is shown instead, section by section.
"""

from __future__ import annotations

import hashlib

from centerline_common.db import uuid7

from ..config import audit
from ..config.audit import iso
from ..config.store import invalid
from ..config.versioning import reason_errors
from ..problems import Problem
from ..ai.translate import PROMPT_VERSION as AI_PROMPT
from . import parse as parse_mod

LANGUAGE_NAMES = {"fil": "Tagalog"}


def pair(english: list[dict], parsed: list) -> tuple[dict, list[str]]:
    """Each English section's id → its translated section, or why they don't line up."""
    problems: list[str] = []
    out: dict = {}
    if english and all(e["sheet"] is not None for e in english):
        by_place = {(s.sheet, s.row_from, s.row_to): s for s in parsed}
        for e in english:
            s = by_place.get((e["sheet"], e["row_from"], e["row_to"]))
            if s is None:
                rows = f"row {e['row_from']}" if e["row_from"] == e["row_to"] else f"rows {e['row_from']}–{e['row_to']}"
                problems.append(f"{e['sheet']}, {rows} ({e['heading'] or 'opening text'}) has no match in the file")
            else:
                out[e["id"]] = s
        if len(parsed) > len(out) and not problems:
            problems.append(f"the file has {len(parsed) - len(out)} section(s) more than the OCAP")
    elif len(parsed) != len(english):
        problems.append(f"the file has {len(parsed)} sections; the OCAP has {len(english)}")
    else:
        out = {e["id"]: s for e, s in zip(english, parsed)}
    return out, problems


class Translations:
    @staticmethod
    def _version(conn, version_id) -> dict:
        v = conn.execute("""SELECT v.id, v.number, d.code FROM ocap_version v JOIN ocap_document d ON d.id = v.document_id
                             WHERE v.id = %s""", (version_id,)).fetchone()
        if v is None:
            raise Problem(404, "not-found", "No such OCAP version", "Reload the page")
        return v

    def add(self, conn, version_id, language: str, source: str, content_base64: str, reason: str, scanner) -> object:
        """A Draft translation of the version, paired section by section. Commits; returns its id."""
        from .store import checked_file, decode_upload  # the OCAP store imports this module

        errors = reason_errors(reason)
        if language not in LANGUAGE_NAMES:
            errors.append({"field": "language", "message": "Tagalog (fil)"})
        if errors:
            raise invalid("The translation can't be saved", errors)
        v = self._version(conn, version_id)
        data = decode_upload(content_base64)
        name = source.strip() or "translation"
        media_type, verdict, detail = checked_file(conn, data, name, scanner, f"Translation of {v['code']} v{v['number']}",
                                                   (parse_mod.PDF, parse_mod.DOCX, parse_mod.XLSX))
        try:
            parsed = parse_mod.parse(data, media_type).sections
        except parse_mod.Unreadable as e:
            raise invalid(str(e), [{"field": "contentBase64", "message": str(e)}]) from None
        english = conn.execute("""SELECT id, ordinal, heading, sheet, row_from, row_to FROM ocap_section WHERE version_id = %s
                                   ORDER BY ordinal""", (version_id,)).fetchall()
        paired, problems = pair(english, parsed)
        if problems:
            shown = problems[:5] + ([f"and {len(problems) - 5} more"] if len(problems) > 5 else [])
            raise invalid(f"The file doesn't line up with {v['code']} v{v['number']}",
                          [{"field": "contentBase64", "message": f"It must have the same sheets and rows as the OCAP: {'; '.join(shown)}"}])
        tid = uuid7()
        sha = hashlib.sha256(data).hexdigest()
        conn.execute(f"""INSERT INTO ocap_translation (id, version_id, language, source, media_type, original, sha256, scan,
                                                       scan_detail, reason, created_by)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {audit.ACTOR})""",
                     (tid, version_id, language, name, media_type, data, sha, verdict, detail, reason.strip()))
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO ocap_translation_section (translation_id, section_id, heading, body, phenomenon)
                               VALUES (%s, %s, %s, %s, %s)""",
                            [(tid, sid, s.heading, s.body, s.phenomenon) for sid, s in paired.items()])
        conn.execute(f"INSERT INTO ocap_translation_status (translation_id, status, by_user, reason) VALUES (%s, 'draft', {audit.ACTOR}, %s)",
                     (tid, reason.strip()))
        audit.record(conn, "ocap.translation", f"{LANGUAGE_NAMES[language]} version of {v['code']} v{v['number']} uploaded from "
                     f"{name}: {len(paired)} sections paired (draft)", reason, {"translation": str(tid), "version": str(version_id),
                                                                                  "sha256": sha, "scan": verdict})
        conn.commit()
        return tid

    def set_status(self, conn, translation_id, status: str, reason: str) -> object:
        """Activate (an earlier active one for the same version and language is superseded) or withdraw. Commits;
        returns the version's id."""
        if errors := reason_errors(reason):
            raise invalid("It can't be changed", errors)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('centerline.ocap'))")
        t = conn.execute("""SELECT t.id, t.version_id, t.language, c.status, v.number, d.code FROM ocap_translation t
                              JOIN ocap_translation_current c ON c.translation_id = t.id
                              JOIN ocap_version v ON v.id = t.version_id JOIN ocap_document d ON d.id = v.document_id
                             WHERE t.id = %s""", (translation_id,)).fetchone()
        if t is None:
            raise Problem(404, "not-found", "No such translation", "Reload the page")
        what = f"{LANGUAGE_NAMES[t['language']]} version of {t['code']} v{t['number']}"
        if status == "active":
            if t["status"] == "active":
                raise Problem(409, "already-active", "Already active", f"The {what} is already shown to operators")
            for o in conn.execute("""SELECT t.id FROM ocap_translation t JOIN ocap_translation_current c ON c.translation_id = t.id
                                      WHERE t.version_id = %s AND t.language = %s AND t.id <> %s AND c.status = 'active'""",
                                  (t["version_id"], t["language"], translation_id)).fetchall():
                conn.execute(f"""INSERT INTO ocap_translation_status (translation_id, status, by_user, reason)
                                 VALUES (%s, 'superseded', {audit.ACTOR}, %s)""", (o["id"], reason.strip()))
            summary = f"{what} activated: operators see it in Tagalog"
        else:
            if t["status"] != "active":
                raise Problem(409, "not-active", "Not active", f"The {what} isn't shown to operators")
            summary = f"{what} withdrawn"
        conn.execute(f"INSERT INTO ocap_translation_status (translation_id, status, by_user, reason) VALUES (%s, %s, {audit.ACTOR}, %s)",
                     (translation_id, status, reason.strip()))
        audit.record(conn, f"ocap.translation.{'activate' if status == 'active' else 'withdraw'}", summary, reason,
                     {"translation": str(translation_id)})
        conn.commit()
        return t["version_id"]

    @staticmethod
    def of_version(conn, version_id) -> tuple[list[dict], dict]:
        """The version's translations, newest first, and the newest one's text per section (for the Manager to check)."""
        rows = conn.execute("""SELECT t.id, t.language, t.source, t.scan, t.created_at, t.created_by, t.reason, c.status, c.at AS status_at
                                 FROM ocap_translation t JOIN ocap_translation_current c ON c.translation_id = t.id
                                WHERE t.version_id = %s ORDER BY t.created_at DESC""", (version_id,)).fetchall()
        listed = [{"id": str(r["id"]), "language": r["language"], "source": r["source"], "scan": r["scan"], "status": r["status"],
                   "createdAt": iso(r["created_at"]), "by": r["created_by"], "reason": r["reason"], "statusAt": iso(r["status_at"])}
                  for r in rows]
        shown = next((r for r in rows if r["status"] in ("active", "draft")), None)
        texts = {}
        if shown is not None:
            for s in conn.execute("SELECT section_id, heading, body, phenomenon FROM ocap_translation_section WHERE translation_id = %s",
                                  (shown["id"],)):
                texts[s["section_id"]] = {"heading": s["heading"], "body": s["body"], "phenomenon": s["phenomenon"],
                                          "status": shown["status"], "by": "plant"}
        # The AI's, where the plant has none shown (ADR-0045)
        ids = [r["id"] for r in conn.execute("SELECT id FROM ocap_section WHERE version_id = %s", (version_id,))]
        if shown is None or shown["status"] != "active":
            for sid, a in Translations.by_ai(conn, ids).items():
                if a["text"] and sid not in texts:
                    texts[sid] = {**a["text"], "status": "active"}
        return listed, texts

    @staticmethod
    def by_ai(conn, section_ids: list) -> dict:
        """The AI's attempt for each section under the current prompt (ADR-0045): {"outcome", "detail", "at", "text"},
        where "text" is the translation that passed the checks, or None."""
        if not section_ids:
            return {}
        rows = conn.execute("""SELECT DISTINCT ON (section_id) section_id, outcome, detail, heading, label, body, model, at
                                 FROM ocap_ai_translation WHERE section_id = ANY(%s) AND prompt_version = %s
                                ORDER BY section_id, outcome IN ('used', 'rejected') DESC, at DESC""",
                            (list(section_ids), AI_PROMPT)).fetchall()
        return {r["section_id"]: {"outcome": r["outcome"], "detail": r["detail"], "at": iso(r["at"]),
                                  "text": {"heading": r["heading"], "body": r["body"], "phenomenon": r["label"], "by": "ai",
                                           "model": r["model"]} if r["outcome"] == "used" else None}
                for r in rows}

    @staticmethod
    def active(conn, section_ids: list) -> dict:
        """Each section's Tagalog text, where there's one: what operators read. The plant's checked one when it's active,
        else the AI's that passed the checks (ADR-0045); "by" says which."""
        if not section_ids:
            return {}
        rows = conn.execute("""SELECT s.section_id, s.heading, s.body, s.phenomenon FROM ocap_translation_section s
                                 JOIN ocap_translation_current c ON c.translation_id = s.translation_id AND c.status = 'active'
                                WHERE s.section_id = ANY(%s)""", (list(section_ids),)).fetchall()
        texts = {r["section_id"]: {"heading": r["heading"], "body": r["body"], "phenomenon": r["phenomenon"], "by": "plant"} for r in rows}
        for sid, a in Translations.by_ai(conn, [i for i in section_ids if i not in texts]).items():
            if a["text"]:
                texts[sid] = a["text"]
        return texts

    @staticmethod
    def original(conn, translation_id) -> tuple[str, str, bytes]:
        t = conn.execute("SELECT source, media_type, original FROM ocap_translation WHERE id = %s", (translation_id,)).fetchone()
        if t is None:
            raise Problem(404, "not-found", "No such translation", "Reload the page")
        return t["source"], t["media_type"], bytes(t["original"])
