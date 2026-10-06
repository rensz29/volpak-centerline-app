"""What a notification says (ADR-0023): subject, text, facts and the Teams card. Pure functions, no I/O.

The notifier renders each delivery once, when it routes the message, and stores it: every
retry sends exactly that, and the Notifications page shows it. Times are Asia/Manila. Every
message ends with its reference, the notification's dedup key, the same on every retry (NOT-04).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MANILA = timezone(timedelta(hours=8))
TEST_SUBJECT = "TEST - NO PRODUCTION EVENT"  # NOT-07
SCHEMA = "centerline.notification/1"  # what the Power Automate flow receives
COLOR = {"CRITICAL": "Attention", "WARNING": "Warning", "MISMATCH": "Warning", "OK": "Good", "INFO": "Accent", "TEST": "Accent"}
# What a reason request still open after 15 min waits for (WF-03, ADR-0025)
WAITING = {"waiting_reason": "the operator hasn't given a reason yet",
           "waiting_answers": "the operator hasn't answered the follow-up questions yet",
           "waiting_guidance": "it waits for a Manager's guidance",
           "waiting_acknowledgment": "the operator hasn't acknowledged the guidance yet"}


def manila(t: datetime | str | None) -> str:
    if t is None:
        return "—"
    if isinstance(t, str):
        t = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return t.astimezone(MANILA).strftime("%d %b %Y %H:%M:%S") + " Manila"


def _v(value, unit: str | None) -> str:
    return "—" if value in (None, "") else f"{value} {unit}" if unit else str(value)


def render(n: dict, type_: str, *, event: dict | None = None, line: str = "Volpak", app_url: str | None = None) -> dict:
    """One notification as {subject, severity, text, facts, link, footer}.

    n: {id, dedup_key, kind, created_at, payload}. event, when it has one: {id, kind, opened_at, rule}.
    """
    p, kind = n.get("payload") or {}, n["kind"]
    unit = p.get("unit")
    where = f"{p.get('parameterName')} · {p.get('zoneName')}" if p.get("parameter") else None
    facts: list[tuple[str, str]] = [("Line", line)]
    if where:
        facts.append(("Zone", f"{where} ({p['parameter']}.{p['zone']})"))
    hmi, target, actual = _v(p.get("hmi"), unit), _v(p.get("target"), unit), _v(p.get("actual"), unit)
    link_page = "active"
    ack = " A Manager acknowledges it in Centerline to stop the reminders."

    if type_ == "hmi_mismatch":
        severity, subject = "MISMATCH", f"HMI mismatch · {where} · {line}"
        text = f"The HMI setpoint {hmi} differs from the target {target}."
        if p.get("supersedes"):
            text += " It replaces the earlier mismatch on this zone."
        facts += [("HMI setpoint", hmi), ("Target", target)]
    elif type_ == "actual_warning":
        severity, subject = "WARNING", f"Actual Warning · {where} · {line}"
        text = f"The actual value {actual} is outside its Warning band around the HMI setpoint {hmi}."
        facts += [("Actual", actual), ("HMI setpoint", hmi)]
    elif type_ == "actual_critical":
        severity, subject = "CRITICAL", f"Actual Critical · {where} · {line}"
        text = (f"The actual value {actual} has gone from Warning to Critical against the HMI setpoint {hmi}." if kind == "escalated"
                else f"The actual value {actual} is outside its Critical band around the HMI setpoint {hmi}.") + ack
        facts += [("Actual", actual), ("HMI setpoint", hmi)]
    elif type_ == "critical_repeat":
        severity, subject = "CRITICAL", f"Still Critical (reminder {p.get('repeat', '?')} of 4) · {where} · {line}"
        text = f"The actual value {actual} is still Critical against the HMI setpoint {hmi}, and nobody has acknowledged it." + ack
        facts += [("Actual", actual), ("HMI setpoint", hmi)]
    elif type_ == "critical_escalation":
        severity, subject = "CRITICAL", f"Critical for 75 min, not acknowledged · {where} · {line}"
        text = (f"The actual value {actual} has been Critical for 75 minutes against the HMI setpoint {hmi}, and nobody "
                "has acknowledged it. This is the last reminder.")
        facts += [("Actual", actual), ("HMI setpoint", hmi)]
    elif type_ == "recovery":
        severity, link_page = "OK", "history"
        if (event or {}).get("kind") == "HMI_MISMATCH" or "target" in p:
            subject, text = f"Back on target · {where} · {line}", f"The HMI setpoint {hmi} is back on the target {target}."
            facts += [("HMI setpoint", hmi), ("Target", target)]
        else:
            subject = f"Back to normal · {where} · {line}"
            text = f"The actual value {actual} is back inside its band around the HMI setpoint {hmi}."
            facts += [("Actual", actual), ("HMI setpoint", hmi)]
    elif type_ == "reason_overdue":  # WF-03: the shift's request is still open 15 min after it was made
        severity, subject = "WARNING", f"Reason request overdue · {where} · {line}"
        text = (f"The reason request for the HMI mismatch on {where} is still open 15 minutes after it was made: "
                f"{WAITING.get(p.get('status'), 'it is still open')}. The HMI setpoint is {hmi} against the target {target}.")
        facts += [("HMI setpoint", hmi), ("Target", target), ("Shift", p.get("shiftLabel") or "—"),
                  ("Requested", manila(p.get("waitingSince")))]
    elif type_ == "test":
        severity, subject = "TEST", TEST_SUBJECT
        text = f"A test message from Centerline, sent by {p.get('by') or 'an Administrator'}. There is no production event."
        if p.get("note"):
            facts.append(("Note", p["note"]))
    else:  # system
        severity, subject, text = _system(p, line)
    if type_ in ("hmi_mismatch", "actual_warning", "actual_critical", "critical_repeat", "critical_escalation", "recovery",
                 "reason_overdue"):
        facts.append(("Since", manila((event or {}).get("opened_at") or n["created_at"])))
    facts.append(("Sent", manila(n["created_at"])))

    link = None
    if app_url:
        base = app_url.rstrip("/")
        if type_ == "reason_overdue":
            link = f"{base}/reasons?request={p.get('request')}"
        elif n.get("event_id"):
            link = f"{base}/alarms/{link_page}?event={n['event_id']}"
        elif p.get("kind") == "Maintenance overdue (MNT-01)":
            link = f"{base}/maintenance"
        else:
            link = f"{base}/centerline"
    footer = f"Centerline · {line} · times are Asia/Manila · ref {n['dedup_key']}"
    return {"subject": subject, "severity": severity, "text": text, "facts": [{"name": k, "value": v} for k, v in facts],
            "link": link, "footer": footer}


def _system(p: dict, line: str) -> tuple[str, str, str]:
    kind = p.get("kind", "")
    if kind == "Rules incomplete (OPC-08)":
        return ("INFO", f"Monitoring paused: the rules are incomplete · {line}",
                "Centerline isn't judging the line: " + "; ".join(p.get("reasons") or []) + ". A Manager completes them in Centerline.")
    if kind == "Maintenance overdue (MNT-01)":
        return ("WARNING", f"Maintenance window overdue · {line}",
                f"The maintenance window “{p.get('reason')}” was planned to end {manila(p.get('plannedEnd'))} and is still "
                "in force, so its zones aren't judged. An Administrator ends it in Centerline.")
    if kind == "monitor-core silent":
        return ("CRITICAL", f"Monitoring may be down: no heartbeat · {line}",
                f"monitor-core hasn't written its heartbeat since {manila(p.get('since'))}. Live values and alarms may be out of date.")
    if kind == "monitor-core back":
        return ("OK", f"Monitoring is back · {line}", "monitor-core is writing its heartbeat again.")
    return "INFO", f"Centerline: {kind or 'system message'} · {line}", "; ".join(f"{k}: {v}" for k, v in p.items())


def email_body(msg: dict) -> str:
    lines = [msg["text"], ""]
    lines += [f"{f['name']}: {f['value']}" for f in msg["facts"]]
    if msg["link"]:
        lines += ["", f"Open in Centerline: {msg['link']}"]
    lines += ["", "--", msg["footer"]]
    return "\n".join(lines) + "\n"


def teams_payload(msg: dict, target: str, dedup_key: str, message_id: str, type_: str) -> dict:
    """What the Power Automate flow receives: the fields, and a ready Adaptive Card to post (O-05)."""
    body = [{"type": "TextBlock", "text": msg["subject"], "weight": "Bolder", "size": "Medium", "wrap": True,
             "color": COLOR.get(msg["severity"], "Default")},
            {"type": "TextBlock", "text": msg["text"], "wrap": True},
            {"type": "FactSet", "facts": [{"title": f["name"], "value": f["value"]} for f in msg["facts"]]},
            {"type": "TextBlock", "text": msg["footer"], "isSubtle": True, "size": "Small", "wrap": True}]
    card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.4",
            "body": body, "actions": [{"type": "Action.OpenUrl", "title": "Open in Centerline", "url": msg["link"]}] if msg["link"] else []}
    return {"schema": SCHEMA, "dedupKey": dedup_key, "messageId": message_id, "type": type_, "severity": msg["severity"],
            "test": type_ == "test", "target": target, "title": msg["subject"], "text": msg["text"], "facts": msg["facts"],
            "link": msg["link"], "footer": msg["footer"], "card": card}


def content(n: dict, type_: str, channel: str, target: str, dedup_key: str, message_id: str, *, event: dict | None = None,
            line: str = "Volpak", app_url: str | None = None) -> dict:
    """The stored content of one delivery: the message, plus the email body or the Teams payload."""
    msg = render(n, type_, event=event, line=line, app_url=app_url)
    if channel == "email":
        return {**msg, "body": email_body(msg)}
    return {**msg, "teams": teams_payload(msg, target, dedup_key, message_id, type_)}
