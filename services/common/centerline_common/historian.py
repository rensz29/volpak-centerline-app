"""Read-only client for the Timebase Historian REST API (the SDD's HistorianClient).

Only GET requests are issued; nothing here can write to or delete from the
historian. Stdlib only, so the Phase 0 tools and the api service share it.

Behaviour of the plant's Timebase, probed on 2026-09-29 (http://<host>:4516, dataset "dressings"):

* ``GET /api/datasets/{ds}/data?tagname=a&tagname=b&unixStart=S&unixEnd=E`` returns
  ``{"s": ISO, "e": ISO, "tl": [{"t": {"n": tag}, "d": [{"t": ISO, "v": value, "q": 192}]}]}``.
* The first point of each tag is the value in force at the start, so it can be
  older than the start (a "carry-in").
* Values are stored on change only; ``v`` may be missing for empty strings.
* One unknown tag fails the whole request: HTTP 404 ``{"key": "Error.TagNotFound", ...}``.
* Some tag/time spans can't be read. A single-tag request answers HTTP 500; the
  same span inside a multi-tag request gives a truncated body or an empty
  HTTP 200. Every response is therefore validated, and ``read_window`` falls
  back to single tags and then to smaller windows, reporting what it couldn't
  read. Spans found unreadable are remembered for the life of the process, so
  later reads skip them instead of searching again.
* The tag listing returns ``{"User": [...], "System": [...]}``.

Connections are kept alive (one per thread): a new TCP connection per request
cost more than the data on the plant network.
"""

from __future__ import annotations

import array
import base64
import email.utils
import http.client
import json
import re
import ssl
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Sample:
    t: datetime  # always UTC
    v: float | str | None  # None = unknown (unreadable span or missing value)
    q: int


@dataclass(frozen=True)
class Gap:
    """A tag/time span the server couldn't return."""

    tag: str
    start: int  # epoch seconds
    end: int
    reason: str


UNREADABLE_Q = -1  # quality of the marker sample that starts a span the server couldn't return


class TimebaseError(Exception):
    pass


class TagNotFound(TimebaseError):
    def __init__(self, tag: str, message: str):
        super().__init__(message)
        self.tag = tag


class BadResponse(TimebaseError):
    """HTTP 5xx, truncated or empty body, invalid JSON, or tags missing from the answer."""


_NATIVE_ISO = sys.version_info >= (3, 11)  # fromisoformat accepts "Z" and 7 fractional digits from 3.11


def parse_ts(raw: str) -> datetime:
    """Parse Timebase ISO timestamps, which carry anything from 0 to 7 fractional digits."""
    if _NATIVE_ISO:
        try:
            dt = datetime.fromisoformat(raw)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    s = raw.strip().replace("Z", "+00:00")
    if "." in s:
        head, rest = s.split(".", 1)
        frac, tz = rest, ""
        for sep in ("+", "-"):
            if sep in rest:
                frac, tz = rest.split(sep, 1)
                tz = sep + tz
                break
        s = f"{head}.{frac[:6].ljust(6, '0')}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc(epoch_s: float) -> datetime:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc)


def _read_secret(path: str | None) -> str:
    if not path:
        raise ValueError("auth config needs a *_file path for the secret")
    return Path(path).expanduser().read_text(encoding="utf-8").strip()


# (base url, dataset, tag) -> spans already found unreadable in this process
_bad_spans: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
_bad_lock = threading.Lock()


class TimebaseClient:
    def __init__(self, cfg: dict[str, Any]):
        self.base = cfg["base_url"].rstrip("/")
        self.dataset = cfg["dataset"]
        self.timeout = cfg.get("timeout_s", 60)
        self.headers = {"Accept": "application/json", "Connection": "keep-alive"}
        self.last_server_date: float | None = None
        u = urllib.parse.urlsplit(self.base)
        self._https = u.scheme == "https"
        self._host, self._port = u.hostname, u.port or (443 if self._https else 80)
        self._prefix = u.path.rstrip("/")
        self._ctx = ssl._create_unverified_context() if cfg.get("verify_tls") is False else None
        self._local = threading.local()
        self._conns: list[http.client.HTTPConnection] = []
        self._conns_lock = threading.Lock()

        # Secrets normally come from files; an inline "token"/"password" is only for testing
        # settings that haven't been saved yet (the Configuration page's Test button).
        auth = cfg.get("auth") or {"type": "none"}
        kind = auth.get("type", "none")
        if kind == "bearer":
            self.headers["Authorization"] = f"Bearer {auth.get('token') or _read_secret(auth.get('token_file'))}"
        elif kind == "basic":
            pw = auth.get("password") or _read_secret(auth.get("password_file"))
            token = base64.b64encode(f"{auth['username']}:{pw}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"
        elif kind == "header":
            self.headers[auth["header_name"]] = _read_secret(auth.get("token_file"))
        elif kind != "none":
            raise ValueError(f"unknown auth type {kind!r}")

    # -- transport -----------------------------------------------------------

    def _conn(self) -> http.client.HTTPConnection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if self._https:
                conn = http.client.HTTPSConnection(self._host, self._port, timeout=self.timeout, context=self._ctx)
            else:
                conn = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout)
            self._local.conn = conn
            with self._conns_lock:
                self._conns.append(conn)
        return conn

    def _drop(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def close(self) -> None:
        with self._conns_lock:
            for conn in self._conns:
                conn.close()
            self._conns.clear()
        self._local = threading.local()

    def _request(self, path: str, params: list[tuple[str, str]] | None = None) -> tuple[int, bytes]:
        """GET on a kept-alive connection. HTTP error statuses are returned, not raised."""
        url = self._prefix + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        last: Exception | None = None
        for attempt in range(3):
            conn = self._conn()
            try:
                conn.request("GET", url, headers=self.headers)
                resp = conn.getresponse()
            except (OSError, http.client.HTTPException) as e:
                # A kept-alive connection the server has closed fails here: retry on a new one.
                self._drop()
                last = e
                if attempt:
                    time.sleep(2 ** (attempt - 1))
                continue
            self._note_date(resp.getheader("Date"))
            try:
                body = resp.read()
            except http.client.IncompleteRead as e:
                self._drop()
                raise BadResponse(f"truncated body after {len(e.partial)} bytes") from None
            except (OSError, http.client.HTTPException) as e:
                self._drop()
                raise BadResponse(f"connection dropped mid-body ({e.__class__.__name__})") from None
            if resp.will_close:
                self._drop()
            return resp.status, body
        raise TimebaseError(f"GET {self.base}{path} failed after retries: {last}")

    def _note_date(self, header: str | None) -> None:
        if header:
            try:
                self.last_server_date = email.utils.parsedate_to_datetime(header).timestamp()
            except (TypeError, ValueError):
                pass

    def get_raw(self, path: str) -> tuple[int, str]:
        """Status and the start of the body; used by the probe for endpoints that may not be JSON."""
        status, body = self._request(path)
        return status, body[:2000].decode("utf-8", "replace")

    def _get_json(self, path: str, params: list[tuple[str, str]] | None = None) -> Any:
        status, body = self._request(path, params)
        if status == 404 and body:
            try:
                err = json.loads(body)
            except json.JSONDecodeError:
                err = {}
            if err.get("key") == "Error.TagNotFound":
                m = re.search(r"Tag '(.+?)' could not be found", err.get("message", ""))
                raise TagNotFound(m.group(1) if m else "?", err.get("message", "tag not found"))
        if status in (401, 403):
            raise TimebaseError(f"HTTP {status}: check the auth settings / token")
        if status >= 500:
            raise BadResponse(f"HTTP {status}")
        if status != 200:
            raise TimebaseError(f"HTTP {status}: {body[:200]!r}")
        if not body:
            raise BadResponse("empty body")
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise BadResponse(f"invalid JSON ({e.msg} at byte {e.pos} of {len(body)})") from None

    # -- metadata ------------------------------------------------------------

    def datasets(self) -> list[dict]:
        return self._get_json("/api/datasets") or []

    def tag_types(self, contains: str | None = None) -> dict[str, str | None]:
        """Tag name → data type (e.g. "System.Double") for every tag whose name contains `contains`."""
        ds = urllib.parse.quote(self.dataset, safe="")
        payload = self._get_json(f"/api/datasets/{ds}/tags", [("contains", contains)] if contains else None)
        items = payload if isinstance(payload, list) else [t for v in (payload or {}).values() for t in v]
        return {t["n"]: t.get("t") for t in items if isinstance(t, dict) and "n" in t}

    def tag_names(self, contains: str | None = None) -> set[str]:
        return set(self.tag_types(contains))

    # -- data ----------------------------------------------------------------

    def read(self, tags: list[str], start: int | None = None, end: int | None = None) -> dict[str, list[Sample]]:
        """One request for several tags. Without start/end Timebase returns the latest point."""
        params = [("tagname", t) for t in tags]
        if start is not None:
            params.append(("unixStart", str(int(start))))
        if end is not None:
            params.append(("unixEnd", str(int(end))))
        ds = urllib.parse.quote(self.dataset, safe="")
        out = _parse_blocks(self._get_json(f"/api/datasets/{ds}/data", params))
        missing = [t for t in tags if t not in out]
        if missing:
            raise BadResponse(f"{len(missing)} of {len(tags)} tags missing from the answer")
        return out

    def read_window(self, tags: list[str], start: int, end: int, min_window_s: int = 60,
                    gaps: list[Gap] | None = None) -> dict[str, list[Sample]]:
        """Like ``read``, but never gives up on the whole window.

        On a bad response it retries tag by tag, then halves the window for a
        failing tag down to ``min_window_s``. A span that still can't be read is
        recorded in ``gaps`` and marked in the series by an unknown sample.
        """
        gaps = gaps if gaps is not None else []
        if not any(self._known_bad(t, start, end) for t in tags):
            try:
                return self.read(tags, start, end)
            except BadResponse:
                pass
        return {t: self._read_tag(t, start, end, min_window_s, gaps) for t in tags}

    def read_range(self, tags: list[str], start: int, end: int, window_s: int = 21600,
                   min_window_s: int = 60, gaps: list[Gap] | None = None,
                   workers: int = 3) -> dict[str, list[Sample]]:
        """All samples of several tags over [start, end), one window per request.

        Windows are fetched ``workers`` at a time. Each tag's list starts with
        its carry-in (the value in force at ``start``); repeated carry-ins
        between windows are dropped.
        """
        gaps = gaps if gaps is not None else []
        windows = [(w0, min(end, w0 + window_s)) for w0 in range(start, end, window_s)]

        def fetch(w: tuple[int, int]) -> dict[str, list[Sample]]:
            return self.read_window(tags, w[0], w[1], min_window_s, gaps)

        if workers > 1 and len(windows) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(windows))) as pool:
                parts = list(pool.map(fetch, windows))
        else:
            parts = [fetch(w) for w in windows]
        out: dict[str, list[Sample]] = {t: [] for t in tags}
        for (w0, _), part in zip(windows, parts):
            for tag, samples in part.items():
                _extend(out[tag], samples, w0)
        gaps.sort(key=lambda g: (g.tag, g.start))
        return out

    def read_times(self, tag: str, start: int, end: int, window_s: int = 21600, min_window_s: int = 60,
                   gaps: list[Gap] | None = None, workers: int = 3) -> array.array:
        """Epoch seconds of every sample of one tag over [start, end), plus its carry-in.

        For message-arrival tags such as `_timestamp`, where only the times
        matter: no Sample objects, so 30 days of one-per-second data stays small.
        Unreadable spans simply contribute no times.
        """
        gaps = gaps if gaps is not None else []
        ds = urllib.parse.quote(self.dataset, safe="")
        windows = [(w0, min(end, w0 + window_s)) for w0 in range(start, end, window_s)]

        def fetch(w: tuple[int, int]) -> array.array:
            times = array.array("d")
            try:
                if self._known_bad(tag, *w):
                    raise BadResponse("known unreadable span")
                payload = self._get_json(f"/api/datasets/{ds}/data",
                                         [("tagname", tag), ("unixStart", str(w[0])), ("unixEnd", str(w[1]))])
                blocks = payload.get("tl") if isinstance(payload, dict) else None
                if not blocks:
                    raise BadResponse("tag missing from the answer")
                times.extend(parse_ts(p["t"]).timestamp() for p in blocks[0].get("d") or [] if "t" in p)
            except BadResponse:
                times.extend(x.t.timestamp() for x in self._read_tag(tag, w[0], w[1], min_window_s, gaps)
                             if x.q != UNREADABLE_Q)
            return times

        if workers > 1 and len(windows) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(windows))) as pool:
                parts = list(pool.map(fetch, windows))
        else:
            parts = [fetch(w) for w in windows]
        out = array.array("d")
        for part in parts:
            # Each window repeats the previous one's last time as its carry-in.
            k = 0
            while k < len(part) and out and part[k] <= out[-1]:
                k += 1
            out.extend(part[k:])
        return out

    # -- unreadable spans ----------------------------------------------------

    def _key(self, tag: str) -> tuple[str, str, str]:
        return (self.base, self.dataset, tag)

    def _known_bad(self, tag: str, start: int, end: int) -> list[tuple[int, int]]:
        with _bad_lock:
            return [(a, b) for a, b in _bad_spans.get(self._key(tag), []) if a < end and b > start]

    def _remember_bad(self, tag: str, start: int, end: int) -> None:
        with _bad_lock:
            spans = _bad_spans.setdefault(self._key(tag), [])
            if (start, end) not in spans:
                spans.append((start, end))

    def _read_tag(self, tag: str, start: int, end: int, min_window_s: int, gaps: list[Gap]) -> list[Sample]:
        """One tag over [start, end), skipping spans already known to be unreadable."""
        out: list[Sample] = []
        cursor = start
        for a, b in sorted(self._known_bad(tag, start, end)):
            a, b = max(a, start), min(b, end)
            if a > cursor:
                out = join_series(out, self._bisect(tag, cursor, a, min_window_s, gaps), cursor)
            gaps.append(Gap(tag, a, b, "unreadable (seen before)"))
            out = join_series(out, [Sample(utc(a), None, UNREADABLE_Q)], a)
            cursor = max(cursor, b)
        if cursor < end:
            out = join_series(out, self._bisect(tag, cursor, end, min_window_s, gaps), cursor)
        return out

    def _bisect(self, tag: str, start: int, end: int, min_window_s: int, gaps: list[Gap]) -> list[Sample]:
        try:
            return self.read([tag], start, end)[tag]
        except BadResponse as e:
            if end - start <= min_window_s:
                gaps.append(Gap(tag, start, end, str(e)))
                self._remember_bad(tag, start, end)
                return [Sample(utc(start), None, UNREADABLE_Q)]
        mid = start + (end - start) // 2
        return join_series(self._bisect(tag, start, mid, min_window_s, gaps),
                           self._bisect(tag, mid, end, min_window_s, gaps), mid)


def _extend(out: list[Sample], second: list[Sample], at: int) -> None:
    """join_series in place: only the start of `second` can overlap `out`, so nothing is copied."""
    k = 0
    while k < len(second) and out and second[k].t <= out[-1].t:
        s = second[k]
        if out[-1].v is None and s.v is not None and utc(at) > out[-1].t:
            out.append(Sample(utc(at), s.v, s.q))
        k += 1
    out.extend(second[k:])


def join_series(first: list[Sample], second: list[Sample], at: int) -> list[Sample]:
    """Concatenate two consecutive reads, dropping repeated carry-ins.

    After an unreadable span the next read's carry-in is the value in force at
    ``at``, so it is re-stamped to ``at`` rather than dropped.
    """
    out = list(first)
    for s in second:
        if out and s.t <= out[-1].t:
            if out[-1].v is None and s.v is not None:
                s = Sample(utc(at), s.v, s.q)
                if s.t <= out[-1].t:
                    continue
            else:
                continue
        out.append(s)
    return out


def _parse_blocks(payload: Any) -> dict[str, list[Sample]]:
    """Accept the ``{"tl": [...]}`` envelope and the older single/list block shapes."""
    if isinstance(payload, dict) and "tl" in payload:
        blocks = payload["tl"] or []
    elif isinstance(payload, list):
        blocks = payload
    else:
        blocks = [payload]
    out: dict[str, list[Sample]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        name = (block.get("t") or {}).get("n")
        if name is None:
            continue
        # Values pass through untouched: codes such as "00123" must stay strings.
        out[name] = [Sample(parse_ts(p["t"]), p.get("v"), int(p.get("q", 0)))
                     for p in block.get("d") or [] if "t" in p]
    return out
