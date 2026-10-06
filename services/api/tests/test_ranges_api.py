"""Analytics-valid ranges as versions (ANA-10/11, ADR-0029): an Administrator uploads the CSV, accepted or rejected
as a whole, kept exactly as uploaded, activated now or later, rolled back, every step audited."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace

import psycopg
import pytest
from centerline_common import register

from centerline_api.analytics import ranges as ranges_mod

from .conftest import REGISTER

REG = register.load(REGISTER)
RANGES = "/api/v1/config/analytics-ranges"
QUERY = {"from": "2026-09-01T18:00:00Z", "to": "2026-09-02T06:00:00Z", "x": "P02.V1.actual", "y": "P02.V2.actual"}


def csv_file(narrow_p02: bool = False, drop: str | None = None, bom: bool = False) -> bytes:
    rows = ["parameter_id,unit,valid_min,valid_max"]
    for p in REG.parameters:
        if p["id"] == drop:
            continue
        lo, hi = (214.5, 215.5) if narrow_p02 and p["id"] == "P02" else (0, 1000)
        rows.append(f"{p['id']},{p.get('unit') or ''},{lo},{hi}")
    return (b"\xef\xbb\xbf" if bom else b"") + "\r\n".join(rows).encode("utf-8") + b"\r\n"


def upload(c, data: bytes, reason: str = "Process engineering's ranges, 6 Oct", activate: str = "now", **extra):
    latest = c.get(RANGES).json()["latest"]
    return c.post(f"{RANGES}/versions", json={"expectedLatest": latest, "source": "analytics-ranges.csv",
                                              "contentBase64": base64.b64encode(data).decode(), "reason": reason,
                                              "activate": activate, **extra})


def audit(database, prefix: str) -> list[dict]:
    with database.connect() as conn:
        return conn.execute("SELECT actor, action, summary, reason FROM audit_log WHERE action LIKE %s ORDER BY seq",
                            (prefix + "%",)).fetchall()


def test_the_template_lists_every_parameter_with_its_unit(make_client):
    r = make_client(roles=["MANAGER"]).get(f"{RANGES}/template.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == "parameter_id,unit,valid_min,valid_max" and len(lines) == 12
    assert "P02,°C,," in lines


def test_a_file_is_accepted_or_rejected_whole_and_only_by_an_administrator(make_client, database):
    admin = make_client(roles=["ADMINISTRATOR"])
    assert make_client(roles=["MANAGER"]).post(f"{RANGES}/versions", json={"expectedLatest": None, "contentBase64": ""}).status_code == 403
    bad = csv_file(drop="P11").replace(b"P03,\xc2\xb0C,0,1000", b"P03,bar,0,1000")
    check = admin.post(f"{RANGES}/versions/check", json={"source": "x.csv", "contentBase64": base64.b64encode(bad).decode()}).json()
    assert check["rows"] is None and any("P11" in p for p in check["problems"]) and any("unit" in p for p in check["problems"])
    r = upload(admin, bad)
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {"contentBase64"} and "P11" in r.json()["detail"]
    assert upload(admin, csv_file(), reason="").status_code == 422  # a reason is required
    assert admin.get(RANGES).json()["latest"] is None  # nothing was saved
    assert admin.post(f"{RANGES}/versions", json={"expectedLatest": None, "source": "x.csv", "contentBase64": "not base64!",
                                                 "reason": "Typo test"}).status_code == 422


def test_the_original_file_and_its_hash_are_kept_and_the_ranges_apply_to_queries(make_client, database, owner):
    admin = make_client()  # Manager and Administrator
    before = admin.post("/api/v1/analytics/query", json=QUERY).json()
    assert "NO_RANGES" in [w["code"] for w in before["warnings"]] and before["ranges"]["version"] is None

    original = csv_file(narrow_p02=True, bom=True)  # a BOM and CRLF, as a spreadsheet saves it
    r = upload(admin, original)
    assert r.status_code == 201 and r.json()["created"] == 1
    body = r.json()
    assert body["active"]["number"] == 1 and len(body["rows"]) == 11 and body["problems"] == []
    assert next(row for row in body["rows"] if row["parameterId"] == "P02") == {
        "parameterId": "P02", "parameterName": "Vertical Temperature", "unit": "°C", "validMin": 214.5, "validMax": 215.5}
    kept = admin.get(f"{RANGES}/versions/1/original.csv")
    assert kept.content == original  # byte for byte
    v1 = admin.get(f"{RANGES}/versions/1").json()
    assert v1["intact"] and v1["sha256"] == hashlib.sha256(original).hexdigest() and v1["source"] == "analytics-ranges.csv"

    after = admin.post("/api/v1/analytics/query", json=QUERY).json()
    assert after["ranges"] == {"version": 1, "x": [214.5, 215.5], "y": [214.5, 215.5]}
    assert after["exclusions"]["x"]["outOfRange"] > 0 and "NO_RANGES" not in [w["code"] for w in after["warnings"]]
    assert admin.get("/api/v1/analytics/options").json()["ranges"]["version"] == 1
    logged = [json.loads(line) for line in (admin.app.state.settings.audit_log).read_text().splitlines()]
    assert logged[-1]["ranges"] == 1 and logged[-1]["user"]  # who ran it, and under which ranges

    with owner.connect() as conn, pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute("UPDATE analytics_range SET valid_max = 9999")  # kept as saved, even against the owner


def test_versions_activate_later_roll_back_and_every_step_is_audited(make_client, database):
    admin = make_client()
    assert upload(admin, csv_file()).status_code == 201
    assert upload(admin, csv_file(narrow_p02=True), activate="no").status_code == 201
    overview = admin.get(RANGES).json()
    assert (overview["active"]["number"], [v["status"] for v in overview["versions"]]) == (1, ["saved", "active"])

    r = admin.post(f"{RANGES}/versions/2/activate", json={"expectedActive": 1, "at": "2099-01-01T00:00:00Z", "reason": "From the next audit"})
    scheduled = r.json()["scheduled"][0]
    assert scheduled["number"] == 2
    assert admin.post(f"{RANGES}/activations/{scheduled['id']}/cancel", json={"reason": "Not yet approved"}).json()["scheduled"] == []
    assert admin.post(f"{RANGES}/versions/2/activate", json={"expectedActive": 1, "reason": "Approved"}).json()["active"]["number"] == 2
    assert admin.post(f"{RANGES}/versions/1/activate", json={"expectedActive": 2, "reason": "Back to the wide ranges"}).json()["active"]["number"] == 1
    assert admin.post(f"{RANGES}/versions/1/activate", json={"expectedActive": 2, "reason": "Stale page"}).status_code == 409
    summaries = [e["summary"] for e in audit(database, "analytics_ranges.")]
    assert summaries[0] == "Analytics ranges v1 saved from analytics-ranges.csv: 11 parameters"
    assert "Analytics ranges v1 activated (rollback), replacing v2" in summaries
    assert any(s.startswith("Scheduled activation of Analytics ranges v2") for s in summaries)
    assert {e["actor"] for e in audit(database, "analytics_ranges.")} == {admin.get("/api/v1/auth/session").json()["user"]["username"]}


def test_ranges_that_no_longer_fit_the_register_are_not_applied(make_client, database):
    admin = make_client()
    assert upload(admin, csv_file()).status_code == 201
    changed = replace(REG, version="2026-10-06.9",
                      parameters=[{**p, "unit": "bar"} if p["id"] == "P03" else p for p in REG.parameters])
    with database.connect() as conn:
        found = ranges_mod.active(conn, changed)
    assert found.ranges is None and "v1 no longer fit the register" in found.problems[0] and "P03" in found.problems[0]
    with database.connect() as conn:
        assert ranges_mod.active(conn, REG).ranges.version == 1
