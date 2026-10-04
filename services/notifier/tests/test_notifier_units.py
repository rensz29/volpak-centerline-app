"""The retry schedule, the routing rules and what each message says (ADR-0023). Pure."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from centerline_common import messages
from centerline_common import routing as routing_mod
from centerline_notifier.schedule import next_attempt

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)  # 14:00 Manila


def test_retries_come_after_30_s_1_min_5_min_then_every_15_min_until_24_h():
    waits, at = [], T0
    for failed in range(1, 200):
        nxt = next_attempt(T0, failed, at)
        if nxt is None:
            break
        waits.append(nxt - at)
        at = nxt
    assert waits[:5] == [timedelta(seconds=30), timedelta(minutes=1), timedelta(minutes=5),
                         timedelta(minutes=15), timedelta(minutes=15)]
    assert at <= T0 + timedelta(hours=24) < at + timedelta(minutes=15)  # the last try is within the 24 h (NOT-05)


def rule(name, types, channel, *targets):
    return {"name": name, "types": types, "channel": channel, "targets": list(targets)}


def test_each_kind_of_message_has_one_routing_type():
    t = routing_mod.type_of
    assert t("initial", {"kind": "HMI mismatch"}) == "hmi_mismatch"
    assert t("initial", {"kind": "Actual Warning"}) == "actual_warning"
    assert t("initial", {"kind": "Actual Critical"}) == t("escalated", {}) == "actual_critical"
    assert (t("critical_repeat", {}), t("critical_escalation", {}), t("recovery", {})) == \
        ("critical_repeat", "critical_escalation", "recovery")
    assert (t("changeover", {}), t("system", {"kind": "Maintenance overdue (MNT-01)"}), t("test", {})) == \
        ("changeover", "system", "test")


def test_routing_rules_are_checked_and_criticals_must_reach_someone():
    rules = routing_mod.normalize([rule(" Shift leads ", ["recovery", "hmi_mismatch", "nonsense"], "email", "lead@plant.test ", ""),
                                   rule("", [], "fax", *[]),
                                   rule("Shift leads", ["system"], "email", "not an address", "a@b.co", "A@b.co")])
    assert rules[0] == {"name": "Shift leads", "types": ["hmi_mismatch", "recovery"], "channel": "email",
                        "targets": ["lead@plant.test"]}  # trimmed, in a fixed order, unknown types dropped
    fields = [e["field"] for e in routing_mod.validate(rules)]
    assert fields == ["rules[1].name", "rules[1].types", "rules[1].channel", "rules[1].targets",
                      "rules[2].name", "rules[2].targets", "rules[2].targets"]
    assert routing_mod.critical_gaps(rules) == list(routing_mod.CRITICAL)
    assert any("ACT-03" in w for w in routing_mod.warnings(rules))
    ok = routing_mod.normalize([rule("Management", list(routing_mod.TYPES), "teams", "Alerts"),
                                rule("Management by email", ["actual_critical"], "email", "boss@example.invalid")])
    assert routing_mod.critical_gaps(ok) == [] and routing_mod.validate(ok) == []
    assert routing_mod.warnings(ok) == ["Placeholder addresses nothing will reach: boss@example.invalid (O-05)"]


def test_a_type_goes_to_each_target_once_per_channel():
    rules = routing_mod.normalize([rule("A", ["actual_critical"], "email", "x@plant.test", "y@plant.test"),
                                   rule("B", ["actual_critical", "system"], "email", "X@plant.test"),
                                   rule("C", ["actual_critical"], "teams", "x@plant.test")])
    assert routing_mod.match(rules, "actual_critical") == [("A", "email", "x@plant.test"), ("A", "email", "y@plant.test"),
                                                           ("C", "teams", "x@plant.test")]
    assert routing_mod.match(rules, "system") == [("B", "email", "X@plant.test")]
    assert routing_mod.match(rules, "recovery") == []


def outbox(kind, payload, event_id=None):
    return {"id": "n1", "dedup_key": "e1:initial", "kind": kind, "event_id": event_id, "created_at": T0, "payload": payload}


ZONE = {"parameter": "P03", "parameterName": "Bottom Temperature", "zone": "REAR", "zoneName": "Rear", "unit": "°C", "sku": "67890123"}


def test_each_message_says_what_happened_where_and_when_in_manila_time():
    m = messages.render(outbox("initial", {**ZONE, "kind": "HMI mismatch", "hmi": "190", "target": "180"}, "e1"), "hmi_mismatch",
                        app_url="https://centerline.plant.test/")
    assert m["subject"] == "HMI mismatch · Bottom Temperature · Rear · Volpak" and m["severity"] == "MISMATCH"
    assert m["text"] == "The HMI setpoint 190 °C differs from the target 180 °C for SKU 67890123."
    facts = {f["name"]: f["value"] for f in m["facts"]}
    assert facts["Zone"] == "Bottom Temperature · Rear (P03.REAR)" and facts["Sent"] == "01 Oct 2026 14:00:00 Manila"
    assert m["link"] == "https://centerline.plant.test/alarms/active?event=e1" and m["footer"].endswith("ref e1:initial")

    crit = messages.render(outbox("escalated", {**ZONE, "kind": "Actual Critical", "actual": "191", "hmi": "180"}, "e1"), "actual_critical")
    assert crit["severity"] == "CRITICAL" and "gone from Warning to Critical" in crit["text"] and "acknowledges" in crit["text"]
    assert messages.render(outbox("critical_repeat", {**ZONE, "repeat": 2, "actual": "191", "hmi": "180"}), "critical_repeat")[
        "subject"].startswith("Still Critical (reminder 2 of 4)")
    back = messages.render(outbox("recovery", {**ZONE, "actual": "181", "hmi": "180"}, "e1"), "recovery", event={"kind": "ACTUAL"},
                           app_url="https://c")
    assert back["subject"].startswith("Back to normal") and back["link"] == "https://c/alarms/history?event=e1"
    on_target = messages.render(outbox("recovery", {**ZONE, "hmi": "180", "target": "180"}), "recovery", event={"kind": "HMI_MISMATCH"})
    assert on_target["text"] == "The HMI setpoint 180 °C is back on the target 180 °C."
    placeholder = messages.render(outbox("initial", {**ZONE, "kind": "Actual Warning", "sku": "PLACEHOLDER"}), "actual_warning",
                                  event={"kind": "ACTUAL", "rule": {"sku_placeholder": True}})
    assert {f["name"]: f["value"] for f in placeholder["facts"]}["SKU"].startswith("PLACEHOLDER (placeholder")
    silent = messages.render(outbox("system", {"kind": "monitor-core silent", "since": "2026-10-01T05:59:00+00:00"}), "system")
    assert silent["severity"] == "CRITICAL" and "13:59:00 Manila" in silent["text"]
    assert messages.render(outbox("test", {"by": "szyrelle"}), "test")["subject"] == "TEST - NO PRODUCTION EVENT"  # NOT-07


def test_an_overdue_reason_request_says_what_it_waits_for_and_links_to_it():
    assert routing_mod.type_of("workflow_escalation", {"kind": "Reason overdue"}) == "reason_overdue"
    p = {**ZONE, "kind": "Reason overdue", "hmi": "190", "target": "180", "shift": "B", "shiftLabel": "Shift B, 1 Oct (14:00–22:00)",
         "request": "r1", "waitingSince": "2026-10-01T06:05:00+00:00", "status": "waiting_reason"}
    m = messages.render(outbox("workflow_escalation", p, "e1"), "reason_overdue",
                        event={"kind": "HMI_MISMATCH", "opened_at": T0 - timedelta(minutes=10)}, app_url="https://c/")
    assert m["subject"] == "Reason request overdue · Bottom Temperature · Rear · Volpak" and m["severity"] == "WARNING"
    assert m["text"] == ("The reason request for the HMI mismatch on Bottom Temperature · Rear is still open 15 minutes after it "
                         "was made: the operator hasn't given a reason yet. The HMI setpoint is 190 °C against the target 180 °C.")
    facts = {f["name"]: f["value"] for f in m["facts"]}
    assert (facts["Shift"], facts["Requested"]) == ("Shift B, 1 Oct (14:00–22:00)", "01 Oct 2026 14:05:00 Manila")
    assert facts["Since"] == "01 Oct 2026 13:50:00 Manila"  # the mismatch itself, which may be older than this shift's request
    assert m["link"] == "https://c/reasons?request=r1"
    guided = messages.render(outbox("workflow_escalation", {**p, "status": "waiting_guidance"}, "e1"), "reason_overdue")
    assert "it waits for a Manager's guidance" in guided["text"]


def test_email_and_teams_carry_the_same_message_and_its_reference():
    n = outbox("initial", {**ZONE, "kind": "Actual Warning", "actual": "186", "hmi": "180"}, "e1")
    email = messages.content(n, "actual_warning", "email", "lead@plant.test", "e1:initial:email:lead@plant.test", "<d1@centerline>",
                             app_url="https://c")
    assert email["body"].startswith("The actual value 186 °C is outside its Warning band")
    assert "Open in Centerline: https://c/alarms/active?event=e1" in email["body"] and email["body"].rstrip().endswith("ref e1:initial")
    teams = messages.content(n, "actual_warning", "teams", "Alerts", "e1:initial:teams:Alerts", "<d2@centerline>")["teams"]
    assert (teams["schema"], teams["dedupKey"], teams["messageId"], teams["target"], teams["severity"]) == \
        ("centerline.notification/1", "e1:initial:teams:Alerts", "<d2@centerline>", "Alerts", "WARNING")
    assert teams["card"]["type"] == "AdaptiveCard" and teams["card"]["body"][0]["text"] == teams["title"]
