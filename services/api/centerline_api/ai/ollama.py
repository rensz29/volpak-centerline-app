"""Ollama's HTTP API, with the standard library (ADR-0041). The model only answers what it's asked: it has no tools,
no files and nothing to send anywhere."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

_digests: dict[tuple[str, str], tuple[str | None, float]] = {}


class AiUnavailable(Exception):
    """Ollama didn't answer, or answered with an error."""


class AiTimeout(AiUnavailable):
    """Ollama took longer than the settings allow."""


def _base(settings) -> str:
    return settings.url.rstrip("/")


def digest(settings, model: str | None = None) -> str | None:
    """The installed model's digest (the chat model's, or `model`'s), or None when it isn't pulled. Asked again after a
    minute."""
    model = model or settings.model
    key = (settings.url, model)
    hit = _digests.get(key)
    if hit and time.monotonic() - hit[1] < 60:
        return hit[0]
    try:
        with urllib.request.urlopen(_base(settings) + "/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
    except (OSError, ValueError) as e:
        raise AiUnavailable(f"Ollama at {settings.url} isn't answering: {e}") from None
    name = model if ":" in model else model + ":latest"
    found = next((m.get("digest") for m in tags.get("models", []) if name in (m.get("name"), m.get("model"))), None)
    _digests[key] = (found, time.monotonic())
    return found


def _post(settings, path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(_base(settings) + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except TimeoutError:
        raise AiTimeout(f"no answer within {timeout:g} s") from None
    except urllib.error.HTTPError as e:
        raise AiUnavailable(f"Ollama answered {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise AiTimeout(f"no answer within {timeout:g} s") from None
        raise AiUnavailable(f"Ollama at {settings.url} isn't answering: {e.reason}") from None
    except (OSError, ValueError) as e:
        raise AiUnavailable(f"Ollama's answer couldn't be read: {e}") from None


def chat(settings, system: str, user: str, schema: dict) -> str:
    """One answer, held to `schema` (JSON), at temperature 0, without the model's thinking. Raises AiUnavailable."""
    body = {"model": settings.model, "stream": False, "format": schema,
            "options": {"temperature": 0, "num_ctx": settings.num_ctx},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if settings.think is not None:
        body["think"] = settings.think
    out = _post(settings, "/api/chat", body, settings.timeout_s)
    return (out.get("message") or {}).get("content") or ""


def embed(settings, texts: list[str], timeout: float) -> list[list[float]]:
    """Each text's embedding by the embedding model (ADR-0048), on the CPU: the GPU is the chat model's, and a short
    text takes a fraction of a second there. Raises AiUnavailable."""
    body = {"model": settings.embed_model, "input": texts, "truncate": True, "keep_alive": "24h", "options": {"num_gpu": 0}}
    out = _post(settings, "/api/embed", body, timeout).get("embeddings")
    if not isinstance(out, list) or len(out) != len(texts) or not all(isinstance(v, list) and v for v in out):
        raise AiUnavailable(f"Ollama's {settings.embed_model} gave no embedding for {len(texts)} text(s)")
    return out


def loaded(settings) -> bool:
    """Whether the model is in memory now (Ollama's /api/ps)."""
    name = settings.model if ":" in settings.model else settings.model + ":latest"
    try:
        with urllib.request.urlopen(_base(settings) + "/api/ps", timeout=3) as r:
            running = json.loads(r.read()).get("models", [])
    except (OSError, ValueError) as e:
        raise AiUnavailable(f"Ollama at {settings.url} isn't answering: {e}") from None
    return any(name in (m.get("name"), m.get("model")) for m in running)


def on_gpu(settings) -> float | None:
    """How much of the loaded model is on the GPU, from 0 (the CPU only) to 1, or None when it isn't loaded
    (Ollama's /api/ps): after a move to another PC, the sign that Docker reached its GPU (ADR-0049)."""
    name = settings.model if ":" in settings.model else settings.model + ":latest"
    try:
        with urllib.request.urlopen(_base(settings) + "/api/ps", timeout=3) as r:
            running = json.loads(r.read()).get("models", [])
    except (OSError, ValueError) as e:
        raise AiUnavailable(f"Ollama at {settings.url} isn't answering: {e}") from None
    m = next((m for m in running if name in (m.get("name"), m.get("model"))), None)
    if m is None or not m.get("size"):
        return None
    return round(m.get("size_vram", 0) / m["size"], 2)


def keep_warm(settings, stop) -> None:
    """Load the model and run one tiny question whenever it isn't in memory, so an operator's first question after a
    restart doesn't wait for it (loading took 40 s and the first answer 35 s more on a 4 GB laptop GPU)."""
    log = logging.getLogger("centerline.api.ai")
    while not stop.wait(5):
        try:
            if not loaded(settings) and digest(settings):
                started = time.monotonic()
                body = {"model": settings.model, "stream": False, "keep_alive": "24h",
                        "options": {"temperature": 0, "num_ctx": settings.num_ctx, "num_predict": 8},
                        "messages": [{"role": "user", "content": "Reply with OK."}]}
                if settings.think is not None:
                    body["think"] = settings.think
                req = urllib.request.Request(_base(settings) + "/api/chat", data=json.dumps(body).encode("utf-8"), method="POST",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    r.read()
                log.info("AI model %s loaded and warmed in %.0f s", settings.model, time.monotonic() - started)
        except (AiUnavailable, OSError, ValueError) as e:
            log.debug("AI model not warmed: %s", e)
        if stop.wait(max(5.0, settings.warm_every_s - 5)):
            return
