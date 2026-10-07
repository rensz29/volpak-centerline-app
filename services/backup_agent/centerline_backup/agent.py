"""The backup agent (BKP-01/02, ADR-0035).

Every hour it writes a backup set: a folder named by its UTC time, holding
- centerline.dump: the whole database (pg_dump's custom format; OCAPs and guidance files are in it);
- globals.sql: the roles, which a restore on a new PC needs before the database;
- config.tar.gz: this host's settings and secrets (deploy/config), which a restore needs to start;
- manifest.json: each file's size and SHA-256, and the restore check's result.

A set is written as <name>.partial and renamed when complete, so a half-written set never looks like a backup.
Once a day the newest set is restored into a scratch database and checked: its tables, and the audit chain
(audit_log_verify). Sets are copied off-host when a folder is given, and both places keep 48 hours of sets, the
newest of each of the last 30 days and of each of the last 12 months. status.json says how the last run went.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from centerline_common.db import REPO, DatabaseConfig, DatabaseUnavailable

from .retention import Keep, keep

log = logging.getLogger("centerline.backup")
STAMP = "%Y%m%dT%H%M%SZ"
CHECK_DATABASE = "centerline_restore_check"
FILES = ("centerline.dump", "globals.sql", "config.tar.gz")
AGENT_DIR = Path(__file__).resolve().parents[1]


class BackupError(Exception):
    """A step failed; the message says which, without any secret."""


@dataclass(frozen=True)
class BackupSettings:
    # The database owner: pg_dumpall's roles and the restore check's scratch database need it (ADR-0035)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    config_dir: Path = REPO / "config"
    backup_dir: Path = REPO / "data" / "backups"
    offhost_dir: Path | None = None
    keep: Keep = Keep()
    every_s: int = 3600
    minute: int = 2  # each hour's backup starts this many minutes past the hour (UTC)


def load_settings(path: str | Path | None = None) -> BackupSettings:
    """From CENTERLINE_BACKUP_CONFIG or services/backup_agent/config.json, if either exists; else the dev defaults.
    CENTERLINE_OFFHOST, when set, is the off-host folder (the Docker stack sets it only when deploy/.env names one)."""
    p = Path(path or os.environ.get("CENTERLINE_BACKUP_CONFIG") or AGENT_DIR / "config.json")
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    base = p.resolve().parent
    offhost = os.environ.get("CENTERLINE_OFFHOST") or raw.get("offhost_dir")
    keep_raw = raw.get("keep") or {}
    return BackupSettings(
        database=DatabaseConfig.from_dict(raw["database"], base) if raw.get("database") else DatabaseConfig(),
        config_dir=(base / raw["config_dir"]).resolve() if raw.get("config_dir") else REPO / "config",
        backup_dir=(base / raw["backup_dir"]).resolve() if raw.get("backup_dir") else REPO / "data" / "backups",
        offhost_dir=(base / offhost).resolve() if offhost else None,
        keep=Keep(**{k: int(v) for k, v in keep_raw.items() if k in Keep.__dataclass_fields__}))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sets(folder: Path) -> list[tuple[datetime, Path]]:
    """The complete sets in a folder, oldest first."""
    found = []
    if folder.is_dir():
        for p in folder.iterdir():
            try:
                stamp = datetime.strptime(p.name, STAMP).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if p.is_dir() and (p / "manifest.json").exists():
                found.append((stamp, p))
    return sorted(found)


def prune(folder: Path, now: datetime, policy: Keep) -> list[str]:
    """Deletes the sets the policy doesn't keep, and leftovers of interrupted runs; returns what it deleted."""
    present = sets(folder)
    kept = keep([s for s, _ in present], now, policy)
    gone = [p for s, p in present if s not in kept]
    gone += [p for p in folder.glob("*.partial") if p.is_dir()]
    for p in gone:
        shutil.rmtree(p)
    return [p.name for p in gone]


class Agent:
    def __init__(self, settings: BackupSettings):
        self.s = settings

    # --- PostgreSQL's tools, with the password from its file, never on a command line or in a log ---------------
    def _env(self) -> dict:
        db = self.s.database
        env = {**os.environ, "PGHOST": db.host, "PGPORT": str(db.port), "PGUSER": db.user, "PGCONNECT_TIMEOUT": "10"}
        if db.password_file:
            try:
                env["PGPASSWORD"] = Path(db.password_file).read_text(encoding="utf-8").strip()
            except OSError as e:
                raise BackupError(f"can't read the database password file: {e}") from None
        return env

    def _run(self, *args: str, timeout: int = 1800) -> str:
        try:
            done = subprocess.run(args, env=self._env(), capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise BackupError(f"{args[0]} isn't installed") from None
        except subprocess.TimeoutExpired:
            raise BackupError(f"{args[0]} took over {timeout} s") from None
        if done.returncode != 0:
            lines = [line for line in done.stderr.strip().splitlines() if line.strip()]
            raise BackupError(f"{args[0]} failed: {lines[-1] if lines else f'exit {done.returncode}'}")
        return done.stdout

    def _sql(self, database: str, query: str) -> str:
        return self._run("psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-d", database, "-c", query, timeout=600).strip()

    # --- One set --------------------------------------------------------------------------------------------------
    def backup(self, now: datetime | None = None, check: bool | None = None) -> Path:
        """Writes one set; restores it into the scratch database to check it when `check` is True, or when it's the
        first set of the UTC day (None). A set whose check fails is kept, with the failure in its manifest: it may
        still be the newest copy there is. Raises BackupError if the set can't be written; the partial set is left
        for the next prune."""
        now = now or datetime.now(timezone.utc)
        name = now.strftime(STAMP)
        self.s.backup_dir.mkdir(parents=True, exist_ok=True)
        work = self.s.backup_dir / f"{name}.partial"
        work.mkdir()
        started = time.monotonic()
        db = self.s.database.dbname
        self._run("pg_dump", "-d", db, "-Fc", "-f", str(work / "centerline.dump"))
        self._run("pg_dumpall", "--globals-only", "-f", str(work / "globals.sql"))
        with tarfile.open(work / "config.tar.gz", "w:gz") as tar:
            tar.add(self.s.config_dir, arcname="config")
        manifest = {
            "set": name,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "database": db,
            "server": self._sql(db, "SHOW server_version"),
            "seconds": None,
            "files": {f: {"bytes": (work / f).stat().st_size, "sha256": sha256(work / f)} for f in FILES},
            "check": None,
        }
        today = [s for s, _ in sets(self.s.backup_dir) if s.date() == now.date()]
        if check or (check is None and not today):
            try:
                manifest["check"] = self.check(work)
            except BackupError as e:
                manifest["check"] = {"at": iso(datetime.now(timezone.utc)), "result": "failed", "error": str(e)}
        manifest["seconds"] = round(time.monotonic() - started, 1)
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        final = self.s.backup_dir / name
        work.rename(final)
        return final

    def check(self, folder: Path) -> dict:
        """Restores a set's dump into the scratch database, checks it, and drops it again."""
        at = iso(datetime.now(timezone.utc))
        try:
            self._run("dropdb", "--if-exists", CHECK_DATABASE)
            self._run("createdb", CHECK_DATABASE)
            self._run("pg_restore", "--exit-on-error", "-d", CHECK_DATABASE, str(folder / "centerline.dump"))
            tables = int(self._sql(CHECK_DATABASE, "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))
            broken = self._sql(CHECK_DATABASE, "SELECT audit_log_verify()")
            audit = int(self._sql(CHECK_DATABASE, "SELECT count(*) FROM audit_log"))
        finally:
            try:
                self._run("dropdb", "--if-exists", CHECK_DATABASE)
            except BackupError as e:
                log.warning("couldn't drop the scratch database %s: %s", CHECK_DATABASE, e)
        if broken:
            raise BackupError(f"the restored audit chain breaks at row {broken}")
        return {"at": at, "result": "restored", "tables": tables, "audit_rows": audit, "audit_chain": "intact"}

    # --- Off-host copy ----------------------------------------------------------------------------------------------
    def copy_offhost(self, folder: Path) -> None:
        target = self.s.offhost_dir
        assert target is not None
        if not target.is_dir():
            raise BackupError(f"the off-host folder {target} isn't there (is the share mounted?)")
        partial = target / f"{folder.name}.partial"
        if partial.exists():
            shutil.rmtree(partial)
        shutil.copytree(folder, partial)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for f, meta in manifest["files"].items():
            if sha256(partial / f) != meta["sha256"]:
                raise BackupError(f"the off-host copy of {f} differs from the set")
        partial.rename(target / folder.name)

    # --- A run: back up, copy, prune, and say how it went -------------------------------------------------------------
    def run_once(self, check: bool | None = None) -> bool:
        now = datetime.now(timezone.utc)
        status = self.status()
        status.update(last_attempt=iso(now), error=None)
        ok = False
        try:
            folder = self.backup(now, check)
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            result = manifest["check"]
            status.update(last_set=folder.name, last_check=result or status.get("last_check"))
            size = sum(m["bytes"] for m in manifest["files"].values())
            if result and result["result"] != "restored":
                status["error"] = f"set {folder.name} was written, but its restore check failed: {result['error']}"
                log.error("backup %s: %.1f MB, but its restore check failed: %s", folder.name, size / 1e6, result["error"])
            else:
                status["last_success"] = iso(now)
                checked = f"; restore check: {result['tables']} tables, audit chain intact" if result else ""
                log.info("backup %s: %.1f MB in %s s%s", folder.name, size / 1e6, manifest["seconds"], checked)
                ok = True
        except (BackupError, DatabaseUnavailable, OSError) as e:
            status["error"] = str(e)
            log.error("backup failed: %s", e)
        deleted = prune(self.s.backup_dir, now, self.s.keep)
        if deleted:
            log.info("pruned %s", ", ".join(deleted))
        off = {"configured": self.s.offhost_dir is not None}
        if self.s.offhost_dir is None:
            off["note"] = "no off-host folder: set CENTERLINE_BACKUP_OFFHOST in deploy/.env"
        elif status.get("last_set") == now.strftime(STAMP):
            try:
                self.copy_offhost(self.s.backup_dir / status["last_set"])
                prune(self.s.offhost_dir, now, self.s.keep)
                off["last_copy"] = iso(now)
            except (BackupError, OSError) as e:
                off["error"] = str(e)
                off["last_copy"] = (status.get("offhost") or {}).get("last_copy")
                log.error("off-host copy failed: %s", e)
        status["offhost"] = off
        status["sets"] = len(sets(self.s.backup_dir))
        self._write_status(status)
        return ok and "error" not in off

    def status(self) -> dict:
        try:
            return json.loads((self.s.backup_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_status(self, status: dict) -> None:
        self.s.backup_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.s.backup_dir / "status.json.tmp"
        tmp.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.s.backup_dir / "status.json")


def iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds").replace("+00:00", "Z")
