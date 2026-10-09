"""api settings, read from a JSON file.

The path comes from CENTERLINE_API_CONFIG, else services/api/config.json.
Relative paths inside the file resolve against the file's own folder.
Secrets (a Timebase token, the database password) are referenced by file path,
never stored here. Without a "database" block the api uses the development
database from deploy/dev/compose.yaml.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from centerline_common import roles
from centerline_common.db import DatabaseConfig

API_DIR = Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]


@dataclass(frozen=True)
class AnalyticsSettings:
    max_range_days: int = 30  # ANA-18: Administrator-configurable maximum
    pair_limit: int = 10_000  # ANA-19
    min_coverage: float = 0.5  # share of a bucket that must be known for its value to count
    use_heartbeat: bool = True  # detect data gaps from each machine area's `_timestamp`
    heartbeat_gap_s: int = 120  # an area silent longer than this is a data gap
    fetch_window_s: int = 21_600  # one Timebase request covers 6 h
    fetch_workers: int = 3  # windows fetched in parallel; kept low to be gentle on the historian
    min_window_s: int = 60
    good_quality_min: int = 192
    clock_warning_s: float = 30.0  # warn when the Timebase clock differs by more than this
    visible_groups: int = 10  # ANA-17


@dataclass(frozen=True)
class AuthSettings:
    """Sign-in and session rules (ADR-0016). The defaults are the URS values; tests shorten them."""

    # Operators sign in only at these workstations, as (name, IP) pairs (SES-04). Empty: nowhere yet.
    operator_workstations: tuple[tuple[str, str], ...] = ()
    # Peers whose X-Forwarded-For header gives the browser's address: the proxy (guide §12)
    trusted_proxies: tuple[str, ...] = ()
    privileged_idle_min: float = 15  # SES-02: Managers and Administrators, warned at 13 min
    idle_warning_min: float = 13
    operator_takeover_min: float = 5  # SES-04: an operator session with no heartbeat for 5 min can be taken over
    privileged_sessions_max: int = 10  # SES-01
    lockout_failures: int = 5  # IAM-03: 5 failed sign-ins lock the account for 15 min
    lockout_min: float = 15
    temporary_password_h: float = 24  # IAM-03
    password_min_length: int = 12
    password_history: int = 5  # the last five passwords can't be used again
    argon2_time_cost: int = 3  # RFC 9106's second recommended profile: 64 MiB, 3 passes, 4 lanes
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4
    secure_cookie: bool = True  # browsers accept Secure cookies on http://localhost too, but not on http://<address>


@dataclass(frozen=True)
class ScannerSettings:
    """Malware scanning of uploads (SEC-01, ADR-0031): clamd in production; "none" only on a development PC, where
    every upload is marked not scanned."""

    type: str = "none"  # "clamd" or "none"
    host: str = "127.0.0.1"
    port: int = 3310
    timeout_s: float = 60.0


@dataclass(frozen=True)
class AiSettings:
    """The local language model the reason workflow asks (AI-01, ADR-0041): Ollama on this host, never a cloud service.
    Off, or slow or wrong, the fixed questions are asked instead: nothing waits for it."""

    enabled: bool = False
    url: str = "http://127.0.0.1:11434"  # Ollama's API
    model: str = ""  # e.g. qwen3.5:4b
    model_digest: str | None = None  # when set, a model whose digest differs isn't used (pinned by digest, SDD §7.2)
    timeout_s: float = 25.0  # PER-01 gives an AI result 30 s
    num_ctx: int = 4096  # the prompt is at most ~2500 tokens; a bigger context leaves less of the model on a small GPU
    think: bool | None = False  # the model's thinking off, for speed; None for a model that has none
    warm_every_s: float = 0  # how often to check the model is loaded, and load it if not; 0: never (a development PC)
    open_every_s: float = 0  # how often to write the opening questions of new requests (ADR-0042); 0: never
    # The OCAP search by meaning (ADR-0048): the embedding model, pinned like the chat model; "" for keyword search only
    embed_model: str = ""  # e.g. bge-m3
    embed_model_digest: str | None = None
    embed_every_s: float = 0  # how often to embed the Active OCAPs' sections not embedded yet; 0: never
    embed_timeout_s: float = 5.0  # a search's own embedding: an OCAP search has 10 s (PER-01), then it's keywords alone
    min_similarity: float = 0.45  # a section nearer than this to what was written isn't a match by meaning
    summary_every_s: float = 0  # how often to write the summaries of the OCAP sections offered (ADR-0046); 0: never
    translate_every_s: float = 0  # how often to translate one more OCAP section into Tagalog (ADR-0045); 0: never
    translate_timeout_s: float = 180.0  # a whole section, in the background: nobody waits for it


@dataclass(frozen=True)
class Settings:
    timebase: dict  # passed to TimebaseClient: base_url, dataset, auth, timeout_s, verify_tls
    register_path: Path
    analytics: AnalyticsSettings = field(default_factory=AnalyticsSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    scanner: ScannerSettings = field(default_factory=ScannerSettings)
    ai: AiSettings = field(default_factory=AiSettings)
    cors_origins: tuple[str, ...] = ()
    audit_log: Path | None = None
    # Configuration page: connections.json, secrets/ and history/ live here (git-ignored)
    config_dir: Path = REPO / "config"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    migrate_on_start: bool = True  # apply db/migrations when the api starts
    # When `database` is the services' role (centerline_app, ADR-0020), the migrations need the owner
    migrate_database: DatabaseConfig | None = None
    # The backup agent's status.json, read-only, for the health page (ADR-0035, ADR-0038); None where backups don't run
    backup_status: Path | None = None


def _ai(raw: dict) -> AiSettings:
    """The AI settings; the Ollama to ask is CENTERLINE_OLLAMA_URL when it's set (deploy/.env, ADR-0050), else ai.url."""
    ai = {k: v for k, v in raw.items() if k in AiSettings.__dataclass_fields__}
    if url := os.environ.get("CENTERLINE_OLLAMA_URL", "").strip():
        ai["url"] = url
    return AiSettings(**ai)


def load_settings(path: str | Path | None = None) -> Settings:
    cfg_path = Path(path or os.environ.get("CENTERLINE_API_CONFIG") or API_DIR / "config.json").resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"api config not found: {cfg_path} (copy config.example.json)")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg_path.parent

    def rel(p: str | None) -> Path | None:
        return (base / p).resolve() if p else None

    a = raw.get("analytics") or {}
    known = AnalyticsSettings.__dataclass_fields__
    if a.get("ranges_csv"):  # before ADR-0029 the ranges were a file named here; now they're versions in the database
        logging.getLogger("centerline.api").warning(
            "analytics.ranges_csv is no longer read: an Administrator uploads the file on Configuration → Analytics ranges")
    analytics = AnalyticsSettings(**{k: v for k, v in a.items() if k in known})
    au = raw.get("auth") or {}
    if "secure_cookie" not in au and os.environ.get("CENTERLINE_SCHEME") == "http":
        # The Docker stack's proxy serves plain HTTP (ADR-0032): browsers elsewhere wouldn't send a Secure cookie back
        au = {**au, "secure_cookie": False}
    auth = AuthSettings(**{k: v for k, v in au.items() if k in AuthSettings.__dataclass_fields__
                           and k not in ("operator_workstations", "trusted_proxies")},
                        operator_workstations=tuple((w["name"], w["ip"]) for w in au.get("operator_workstations") or ()),
                        trusted_proxies=tuple(au.get("trusted_proxies") or ()))
    return Settings(
        timebase=raw["timebase"],
        register_path=rel(raw.get("register")) or REPO / "config" / "parameter-register.json",
        analytics=analytics,
        auth=auth,
        scanner=ScannerSettings(**{k: v for k, v in (raw.get("scanner") or {}).items() if k in ScannerSettings.__dataclass_fields__}),
        ai=_ai(raw.get("ai") or {}),
        cors_origins=tuple(raw.get("cors_origins") or ()),
        audit_log=rel(raw.get("audit_log")),
        config_dir=rel(raw.get("config_dir")) or REPO / "config",
        # Without a "database" block: the development database, as the services' role, migrated by its owner (ADR-0020)
        database=DatabaseConfig.from_dict(raw["database"], base) if raw.get("database") else roles.app_database(DatabaseConfig()),
        migrate_on_start=bool(raw.get("migrate_on_start", True)),
        migrate_database=(DatabaseConfig.from_dict(raw["migrate_database"], base) if raw.get("migrate_database")
                          else None if raw.get("database") else DatabaseConfig()),
        backup_status=rel(raw.get("backup_status")),
    )
