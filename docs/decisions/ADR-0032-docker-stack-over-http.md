# ADR-0032: The Docker stack serves plain HTTP by default; HTTPS stays one setting away

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decider:** Szyrelle (system owner), on 2026-10-06: "run this on the http only not https". Asked whether that meant
  the development setup or the Docker stack, the owner chose "Docker stack over HTTP".
- **Amends:** [ADR-0030](ADR-0030-docker-stack.md) (its proxy served HTTPS only, with Caddy's own CA)
- **URS:** SEC-01, SES-01…04 (the session cookie); affects guide §12

## Context

- The Docker stack's proxy served HTTPS with a certificate signed by Caddy's own local CA ([ADR-0030](ADR-0030-docker-stack.md)).
- Browsers warn about that certificate on every PC that doesn't trust the CA. Trusting it means exporting the CA and
  installing it on each workstation, or asking IT to.
- The owner tests the features from several devices, and wants them to open the page without that step.

## Decision

1. **The proxy serves plain HTTP by default**, on `http://<name or address>:6040`, for any name or address the
   browser uses. Nothing to trust, nothing to install.
2. **HTTPS stays available** with `CENTERLINE_SCHEME=https` in a host's `deploy/.env`, configured as before:
   `CENTERLINE_SITE`, `CENTERLINE_DEFAULT_SNI`, the local CA, HSTS.
   - The proxy has one configuration per scheme: `deploy/caddy/http.Caddyfile` and `https.Caddyfile`, which share
     `app.caddy`.
   - Both listen on the container's port 8080, published as `CENTERLINE_PORT`.
3. **The session cookie follows the scheme.** Over HTTP the api doesn't mark it `Secure`, because a browser on another
   PC wouldn't send a Secure cookie back over HTTP. It stays `HttpOnly` and `SameSite=Strict`.
   - Compose passes `CENTERLINE_SCHEME` to the api.
   - `auth.secure_cookie` in `api.json` still overrides it.
   - The development setup (`http://localhost:5173`) is unchanged: browsers treat localhost as secure.
4. **The pages work over HTTP.** The browser's clipboard API exists only on secure pages, so copying a temporary
   password falls back to the browser's older copy command. Idempotency keys already had a fallback for
   `crypto.randomUUID` ([ADR-0028](ADR-0028-polling-idempotency-g2-acceptance.md)).

## Consequences

- **Passwords and session cookies cross the network unencrypted.** Anyone on the same network who can see the traffic
  can read a password as it's typed, or take over a session. Over HTTP the stack is for testing, on a network the
  owner trusts.
- **HTTP or HTTPS at go-live is open (O-25).** The SDD and guide §12 expect HTTPS on the LAN. The control-room PC
  needs the owner's decision before G5: one line in `deploy/.env`, plus a certificate the workstations trust.
- **Browsers that opened the HTTPS address remember it.** HSTS makes them switch `http://localhost:6040` back to
  `https://`, which no longer answers. Clear it once in the browser: `edge://net-internals/#hsts` (or
  `chrome://net-internals/#hsts`), "Delete domain security policies", `localhost`. Or open `http://127.0.0.1:6040`:
  HSTS never applies to an address.
- **AT-04's cookie check** stays on the api alone: its test sees a Secure cookie, as the HTTPS setting gives.
