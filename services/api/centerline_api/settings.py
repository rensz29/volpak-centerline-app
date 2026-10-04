"""api settings, read from a JSON file.

The path comes from CENTERLINE_API_CONFIG, else services/api/config.json.
Relative paths inside the file resolve against the file's own folder.
Secrets (a Timebase token, the database password) are referenced by file path,
never stored here. Without a "database" block the api uses the development
database from deploy/dev/compose.yaml.
"""

from __future__ import annotations

import json
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
    ranges_csv: Path | None = None  # Analytics-valid ranges (ANA-10); None = none loaded
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
    secure_cookie: bool = True  # browsers accept Secure cookies on http://localhost too


@dataclass(frozen=True)
class Settings:
    timebase: dict  # passed to TimebaseClient: base_url, dataset, auth, timeout_s, verify_tls
    register_path: Path
    analytics: AnalyticsSettings = field(default_factory=AnalyticsSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    cors_origins: tuple[str, ...] = ()
    audit_log: Path | None = None
    # Configuration page: connections.json, secrets/ and history/ live here (git-ignored)
    config_dir: Path = REPO / "config"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    migrate_on_start: bool = True  # apply db/migrations when the api starts
    # When `database` is the services' role (centerline_app, ADR-0020), the migrations need the owner
    migrate_database: DatabaseConfig | None = None


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
    analytics = AnalyticsSettings(**{k: v for k, v in a.items() if k in known and k != "ranges_csv"},
                                  ranges_csv=rel(a.get("ranges_csv")))
    au = raw.get("auth") or {}
    auth = AuthSettings(**{k: v for k, v in au.items() if k in AuthSettings.__dataclass_fields__
                           and k not in ("operator_workstations", "trusted_proxies")},
                        operator_workstations=tuple((w["name"], w["ip"]) for w in au.get("operator_workstations") or ()),
                        trusted_proxies=tuple(au.get("trusted_proxies") or ()))
    return Settings(
        timebase=raw["timebase"],
        register_path=rel(raw.get("register")) or REPO / "config" / "parameter-register.json",
        analytics=analytics,
        auth=auth,
        cors_origins=tuple(raw.get("cors_origins") or ()),
        audit_log=rel(raw.get("audit_log")),
        config_dir=rel(raw.get("config_dir")) or REPO / "config",
        # Without a "database" block: the development database, as the services' role, migrated by its owner (ADR-0020)
        database=DatabaseConfig.from_dict(raw["database"], base) if raw.get("database") else roles.app_database(DatabaseConfig()),
        migrate_on_start=bool(raw.get("migrate_on_start", True)),
        migrate_database=(DatabaseConfig.from_dict(raw["migrate_database"], base) if raw.get("migrate_database")
                          else None if raw.get("database") else DatabaseConfig()),
    )
