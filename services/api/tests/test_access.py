"""Who may call what (ADR-0016): every route's roles as the owner decided them (O-13), and the guards."""

from __future__ import annotations

from dataclasses import replace

from fastapi.routing import APIRoute

from centerline_api.auth import deps

from .conftest import FAST_AUTH

EVERY = {"OPERATOR", "MANAGER", "ADMINISTRATOR"}
PRIV = {"MANAGER", "ADMINISTRATOR"}
MGR, ADM, OPR = {"MANAGER"}, {"ADMINISTRATOR"}, {"OPERATOR"}
SESSION = "any session, even one that must change its password"

EXPECTED = {
    ("POST", "/api/v1/auth/login"): None,
    ("POST", "/api/v1/auth/takeover"): None,
    ("GET", "/api/v1/health/live"): None,
    ("GET", "/api/v1/auth/session"): SESSION,
    ("POST", "/api/v1/auth/activity"): SESSION,
    ("POST", "/api/v1/auth/password"): SESSION,
    ("POST", "/api/v1/auth/logout"): SESSION,
    # Digital Centerline: every role reads; a Manager acknowledges a Critical (ACT-04)
    ("GET", "/api/v1/monitoring/live"): EVERY,
    ("GET", "/api/v1/monitoring/brief-changes"): EVERY,
    ("GET", "/api/v1/events"): EVERY,
    ("GET", "/api/v1/events/{event_id}"): EVERY,
    ("GET", "/api/v1/events/counts"): EVERY,
    ("GET", "/api/v1/events/export.csv"): PRIV,  # exports: Manager and Administrator (EXP-01)
    ("POST", "/api/v1/events/{event_id}/acknowledge"): MGR,
    # Monitoring control (ADR-0017): every role sees it; a Manager switches zones off (O-13), an Administrator
    # runs maintenance (MNT-01)
    ("GET", "/api/v1/monitoring/control"): EVERY,
    ("POST", "/api/v1/monitoring/switch"): MGR,
    ("GET", "/api/v1/maintenance"): EVERY,
    ("POST", "/api/v1/maintenance"): ADM,
    ("POST", "/api/v1/maintenance/{window_id}/extend"): ADM,
    ("POST", "/api/v1/maintenance/{window_id}/end"): ADM,
    # Analytics: Manager and Administrator (O-13)
    ("GET", "/api/v1/analytics/options"): PRIV,
    ("POST", "/api/v1/analytics/query"): PRIV,
    # Configuration: both read every tab; Connections and Tags are the Administrator's (O-13)
    ("GET", "/api/v1/config/connections"): PRIV,
    ("PUT", "/api/v1/config/connections/historian"): ADM,
    ("POST", "/api/v1/config/connections/historian/test"): ADM,
    ("PUT", "/api/v1/config/connections/mqtt"): ADM,
    ("POST", "/api/v1/config/connections/mqtt/test"): ADM,
    ("GET", "/api/v1/config/historian/tags"): PRIV,
    ("POST", "/api/v1/config/historian/latest"): PRIV,  # reads values: the Rules editor uses it too
    ("GET", "/api/v1/config/register"): PRIV,
    ("PUT", "/api/v1/config/register/parameters/{pid}"): ADM,
    # the Rules tab is the Manager's (O-13)
    ("GET", "/api/v1/config/rules"): PRIV,
    ("GET", "/api/v1/config/rules/proposal"): PRIV,
    ("GET", "/api/v1/config/versions/{number}"): PRIV,
    ("POST", "/api/v1/config/versions/check"): MGR,
    ("POST", "/api/v1/config/versions"): MGR,
    ("POST", "/api/v1/config/versions/{number}/activate"): MGR,
    ("POST", "/api/v1/config/activations/{activation_id}/cancel"): MGR,
    # the Mappings tab, mapping import included, is the Administrator's (O-13)
    ("GET", "/api/v1/config/mappings"): PRIV,
    ("GET", "/api/v1/config/mappings/versions/{number}"): PRIV,
    ("GET", "/api/v1/config/mappings/versions/{number}/export.csv"): PRIV,
    ("POST", "/api/v1/config/mappings/versions/check"): ADM,
    ("POST", "/api/v1/config/mappings/versions"): ADM,
    ("POST", "/api/v1/config/mappings/versions/{number}/activate"): ADM,
    ("POST", "/api/v1/config/mappings/activations/{activation_id}/cancel"): ADM,
    ("POST", "/api/v1/config/mappings/import"): ADM,
    ("POST", "/api/v1/config/mappings/discover"): ADM,
    # Notifications (ADR-0023): both read the log and the routing; the Administrator changes the routing and the
    # channels, sends TEST messages (NOT-07) and re-drives a failure (NOT-05)
    ("PUT", "/api/v1/config/connections/notifications"): ADM,
    ("POST", "/api/v1/config/connections/notifications/email-test"): ADM,
    ("GET", "/api/v1/config/routing"): PRIV,
    ("GET", "/api/v1/config/routing/proposal"): PRIV,
    ("GET", "/api/v1/config/routing/versions/{number}"): PRIV,
    ("POST", "/api/v1/config/routing/versions/check"): ADM,
    ("POST", "/api/v1/config/routing/versions"): ADM,
    ("POST", "/api/v1/config/routing/versions/{number}/activate"): ADM,
    ("POST", "/api/v1/config/routing/activations/{activation_id}/cancel"): ADM,
    # Analytics-valid ranges (ANA-11, ADR-0029): both read them; an Administrator uploads and activates them
    ("GET", "/api/v1/config/analytics-ranges"): PRIV,
    ("GET", "/api/v1/config/analytics-ranges/template.csv"): PRIV,
    ("GET", "/api/v1/config/analytics-ranges/versions/{number}"): PRIV,
    ("GET", "/api/v1/config/analytics-ranges/versions/{number}/original.csv"): PRIV,
    ("POST", "/api/v1/config/analytics-ranges/versions/check"): ADM,
    ("POST", "/api/v1/config/analytics-ranges/versions"): ADM,
    ("POST", "/api/v1/config/analytics-ranges/versions/{number}/activate"): ADM,
    ("POST", "/api/v1/config/analytics-ranges/activations/{activation_id}/cancel"): ADM,
    ("GET", "/api/v1/notifications"): PRIV,
    ("GET", "/api/v1/notifications/{notification_id}"): PRIV,
    ("POST", "/api/v1/notifications/test"): ADM,
    ("POST", "/api/v1/deliveries/{delivery_id}/redrive"): ADM,
    # The reason workflow (ADR-0025): every role reads; the operator writes the reason, answers and acknowledgment,
    # a Manager the guidance; the follow-up questions are the Administrator's to change
    ("GET", "/api/v1/workflow/requests"): EVERY,
    ("GET", "/api/v1/workflow/requests/{request_id}"): EVERY,
    ("POST", "/api/v1/workflow/requests/{request_id}/reason"): OPR,
    ("POST", "/api/v1/workflow/requests/{request_id}/answers"): OPR,
    ("POST", "/api/v1/workflow/requests/{request_id}/acknowledge"): OPR,
    ("POST", "/api/v1/workflow/requests/{request_id}/guidance"): MGR,
    ("POST", "/api/v1/workflow/requests/{request_id}/ocap"): OPR,  # the operator chooses the OCAP (ADR-0031)
    ("GET", "/api/v1/workflow/attachments/{attachment_id}"): EVERY,
    # The OCAP library (OCP-03, ADR-0031): every role reads it; any Manager uploads, activates and suspends
    ("GET", "/api/v1/ocaps"): EVERY,
    ("GET", "/api/v1/ocaps/search"): EVERY,
    ("GET", "/api/v1/ocaps/versions/{version_id}"): EVERY,
    ("GET", "/api/v1/ocaps/versions/{version_id}/original"): EVERY,
    ("GET", "/api/v1/ocaps/sections/{section_id}"): EVERY,
    ("POST", "/api/v1/ocaps"): MGR,
    ("POST", "/api/v1/ocaps/{document_id}/versions"): MGR,
    ("POST", "/api/v1/ocaps/versions/{version_id}/activate"): MGR,
    ("POST", "/api/v1/ocaps/versions/{version_id}/suspend"): MGR,
    ("POST", "/api/v1/ocaps/sections/{section_id}/reason"): MGR,  # which mismatches offer an Excel row as a reason (ADR-0039)
    ("POST", "/api/v1/ocaps/versions/{version_id}/translations"): MGR,  # the plant's checked Tagalog version (ADR-0044)
    ("POST", "/api/v1/ocaps/translations/{translation_id}/activate"): MGR,
    ("POST", "/api/v1/ocaps/translations/{translation_id}/withdraw"): MGR,
    ("GET", "/api/v1/ocaps/translations/{translation_id}/original"): EVERY,
    ("GET", "/api/v1/config/workflow"): PRIV,
    ("PUT", "/api/v1/config/workflow"): ADM,
    # accounts and the detailed health
    ("GET", "/api/v1/users"): ADM,
    ("POST", "/api/v1/users"): ADM,
    ("PUT", "/api/v1/users/{user_id}"): ADM,
    ("POST", "/api/v1/users/{user_id}/temporary-password"): ADM,
    ("GET", "/api/v1/health"): ADM,
}


def routes(items):
    """Every endpoint, also inside included routers (FastAPI keeps those as wrappers of the original router)."""
    for r in items:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):
            yield from routes(r.original_router.routes)


def effective(route: APIRoute):
    """The roles a route lets through: the router's rule and the endpoint's, together."""
    calls = []

    def walk(d):
        for sub in d.dependencies:
            calls.append(sub.call)
            walk(sub)

    walk(route.dependant)
    rules = [set(c.roles) for c in calls if hasattr(c, "roles")]
    if rules:
        return set.intersection(*rules)
    if deps.current_session in calls:
        return EVERY
    if deps.session_any in calls:
        return SESSION
    return None


def test_every_route_lets_through_exactly_the_roles_decided(make_client):
    app = make_client(roles=None).app
    actual = {(m, r.path): effective(r) for r in routes(app.routes) if r.path.startswith("/api/") for m in r.methods}
    assert actual == EXPECTED  # a new route fails here until its roles are decided and listed


def test_without_signing_in_only_the_public_routes_answer(make_client):
    c = make_client(roles=None)
    assert c.get("/api/v1/health/live").json() == {"status": "ok"}
    r = c.get("/api/v1/monitoring/live")
    assert r.status_code == 401 and r.json()["type"] == "/problems/not-signed-in"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert c.get("/api/v1/health").status_code == 401


def test_a_state_changing_call_without_the_csrf_header_is_refused(make_client):
    c = make_client()
    r = c.put("/api/v1/config/connections/mqtt", json={"host": "b"}, headers={deps.CSRF_HEADER: ""})
    assert r.status_code == 403 and r.json()["type"] == "/problems/csrf"
    r = c.post("/api/v1/auth/login", json={"name": "a", "password": "b"}, headers={deps.CSRF_HEADER: ""})
    assert r.status_code == 403  # signing in too: no one can be signed in from another site's form
    assert c.get("/api/v1/config/rules").status_code == 200  # reading needs no header


def test_each_role_reaches_its_own_pages_only(make_client):
    operator = make_client(roles=["OPERATOR"], address="10.0.0.5",
                           auth=replace(FAST_AUTH, operator_workstations=(("Line desk", "10.0.0.5"),)))
    manager, admin = make_client(roles=["MANAGER"]), make_client(roles=["ADMINISTRATOR"])

    assert operator.get("/api/v1/monitoring/live").status_code == 200
    for path in ("/api/v1/analytics/options", "/api/v1/config/rules", "/api/v1/config/connections", "/api/v1/users"):
        r = operator.get(path)
        assert r.status_code == 403 and r.json()["type"] == "/problems/not-allowed", path

    assert manager.get("/api/v1/analytics/options").status_code == 200
    assert manager.get("/api/v1/config/connections").status_code == 200  # reads every tab
    r = manager.put("/api/v1/config/connections/mqtt", json={"host": "broker", "subscriptions": ["#"]})
    assert r.status_code == 403 and "Administrator" in r.json()["detail"]
    proposal = manager.get("/api/v1/config/rules/proposal").json()
    draft = {"expectedLatest": None, "settings": proposal["settings"], "rules": proposal["rules"], "reason": ""}
    assert manager.post("/api/v1/config/versions/check", json=draft).status_code == 200
    assert manager.get("/api/v1/users").status_code == 403

    assert admin.get("/api/v1/config/rules").status_code == 200
    r = admin.post("/api/v1/config/versions/check", json=draft)
    assert r.status_code == 403 and "Manager" in r.json()["detail"]
    assert admin.get("/api/v1/users").status_code == 200
    assert admin.get("/api/v1/health").status_code == 200
