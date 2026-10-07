"""The backup agent's rules (BKP-01/02, ADR-0035), without a database: PostgreSQL's tools are replaced by fakes that
write files, so these tests show what a set holds, what's kept, and what the status says. The real tools run against
the Docker stack's database (deploy/README.md, Backups)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from centerline_backup import agent as backup
from centerline_backup.agent import Agent, BackupError, BackupSettings, prune, sets
from centerline_backup.retention import Keep, keep

pytestmark = pytest.mark.urs("BKP-01", "BKP-02")
UTC = timezone.utc
NOW = datetime(2026, 10, 7, 12, 2, tzinfo=UTC)


def hourly(start: datetime, hours: int) -> list[datetime]:
    return [start + timedelta(hours=h) for h in range(hours)]


# --- Retention -----------------------------------------------------------------------------------------------------

def test_keeps_two_days_of_hours_then_one_a_day_for_30_days_then_one_a_month_for_12():
    stamps = hourly(NOW - timedelta(days=500), 500 * 24 + 1)
    kept = keep(stamps, NOW)
    assert all(s in kept for s in stamps if NOW - s <= timedelta(hours=48))
    older = sorted(s for s in kept if NOW - s > timedelta(hours=48))
    days = {s.date() for s in older if (NOW.date() - s.date()).days < 30}
    assert len(days) == 27  # the other three of the 30 days end inside the 48 hours
    assert all(s.hour == 23 for s in older if (NOW.date() - s.date()).days < 30), "a day keeps its newest set"
    months = {(s.year, s.month) for s in kept}
    assert len(months) == 12
    # 49 sets in 48 hours, 27 more days, and 10 more months: this month's and last month's newest are already kept
    assert len(kept) == 49 + 27 + 10


def test_the_newest_set_is_always_kept():
    old = [NOW - timedelta(days=900)]
    assert keep(old, NOW) == set(old)
    assert keep([], NOW) == set()


def test_a_shorter_policy():
    stamps = hourly(NOW - timedelta(days=3), 72)
    kept = keep(stamps, NOW, Keep(hours=1, days=1, months=1))
    assert kept == {max(stamps)}


# --- Sets ----------------------------------------------------------------------------------------------------------

class FakeTools(Agent):
    """pg_dump, pg_dumpall, psql and the restore check, as files and answers."""

    def __init__(self, settings: BackupSettings, chain_breaks_at: str = ""):
        super().__init__(settings)
        self.calls: list[tuple[str, ...]] = []
        self.chain_breaks_at = chain_breaks_at

    def _run(self, *args: str, timeout: int = 1800) -> str:
        self.calls.append(args)
        if args[0] in ("pg_dump", "pg_dumpall"):
            Path(args[args.index("-f") + 1]).write_bytes(f"{args[0]} output".encode())
        return ""

    def _sql(self, database: str, query: str) -> str:
        if "audit_log_verify" in query:
            return self.chain_breaks_at
        return {"SHOW server_version": "17.11"}.get(query, "42")


@pytest.fixture
def settings(tmp_path: Path) -> BackupSettings:
    config = tmp_path / "config"
    (config / "secrets").mkdir(parents=True)
    (config / "api.json").write_text("{}")
    (config / "secrets" / "postgres-password").write_text("not a real one")
    return BackupSettings(config_dir=config, backup_dir=tmp_path / "backups")


def test_a_set_holds_the_database_the_roles_and_the_settings_with_their_checksums(settings):
    folder = FakeTools(settings).backup(NOW)
    assert folder.name == "20261007T120200Z"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert set(manifest["files"]) == {"centerline.dump", "globals.sql", "config.tar.gz"}
    for name, meta in manifest["files"].items():
        assert meta["sha256"] == backup.sha256(folder / name)
    assert manifest["server"] == "17.11"
    assert not list(settings.backup_dir.glob("*.partial"))


def test_the_first_set_of_a_day_is_restored_and_checked_the_others_not(settings):
    tools = FakeTools(settings)
    first = tools.backup(NOW)
    second = tools.backup(NOW + timedelta(hours=1))
    assert json.loads((first / "manifest.json").read_text())["check"]["audit_chain"] == "intact"
    assert json.loads((second / "manifest.json").read_text())["check"] is None
    assert ("pg_restore", "--exit-on-error", "-d", backup.CHECK_DATABASE, str(first.with_suffix(".partial") / "centerline.dump")) in tools.calls
    assert tools.calls.count(("dropdb", "--if-exists", backup.CHECK_DATABASE)) == 2  # before the check, and after it


def test_a_set_whose_check_fails_is_kept_and_the_status_says_so(settings):
    tools = FakeTools(settings, chain_breaks_at="7")
    assert tools.run_once(check=True) is False
    (stamp, folder), = sets(settings.backup_dir)
    assert json.loads((folder / "manifest.json").read_text())["check"]["result"] == "failed"
    status = tools.status()
    assert "audit chain breaks at row 7" in status["error"]
    assert "last_success" not in status


def test_a_failed_dump_leaves_no_set_and_the_status_says_why(settings):
    class Failing(FakeTools):
        def _run(self, *args, timeout=1800):
            if args[0] == "pg_dump":
                raise BackupError("pg_dump failed: connection refused")
            return super()._run(*args, timeout=timeout)

    tools = Failing(settings)
    assert tools.run_once() is False
    assert sets(settings.backup_dir) == []
    assert tools.status()["error"] == "pg_dump failed: connection refused"


def test_prune_deletes_what_the_policy_drops_and_leftovers_of_interrupted_runs(settings):
    tools = FakeTools(settings)
    for stamp in [NOW - timedelta(days=3, hours=h) for h in range(3)] + [NOW]:
        tools.backup(stamp, check=False)
    (settings.backup_dir / "20261001T000000Z.partial").mkdir()
    deleted = prune(settings.backup_dir, NOW, Keep())
    assert sorted(deleted) == ["20261001T000000Z.partial", "20261004T100200Z", "20261004T110200Z"]
    assert [p.name for _, p in sets(settings.backup_dir)] == ["20261004T120200Z", "20261007T120200Z"]


# --- Off-host ------------------------------------------------------------------------------------------------------

def test_each_set_is_copied_off_host_and_checked_there(settings, tmp_path):
    offhost = tmp_path / "share"
    offhost.mkdir()
    tools = FakeTools(BackupSettings(**{**settings.__dict__, "offhost_dir": offhost}))
    assert tools.run_once() is True
    (_, copy), = sets(offhost)
    assert sorted(p.name for p in copy.iterdir()) == ["centerline.dump", "config.tar.gz", "globals.sql", "manifest.json"]
    assert tools.status()["offhost"]["last_copy"]


def test_an_unmounted_share_fails_the_off_host_copy_not_the_backup(settings, tmp_path):
    tools = FakeTools(BackupSettings(**{**settings.__dict__, "offhost_dir": tmp_path / "not-mounted"}))
    assert tools.run_once() is False
    status = tools.status()
    assert status["last_success"] and len(sets(settings.backup_dir)) == 1
    assert "isn't there" in status["offhost"]["error"]


def test_without_an_off_host_folder_the_status_says_the_backups_are_only_here(settings):
    tools = FakeTools(settings)
    assert tools.run_once() is True
    assert tools.status()["offhost"] == {"configured": False, "note": "no off-host folder: set CENTERLINE_BACKUP_OFFHOST in deploy/.env"}


def test_settings_from_the_stack(tmp_path, monkeypatch):
    (tmp_path / "secrets").mkdir()
    path = tmp_path / "backup.json"
    path.write_text(json.dumps({
        "database": {"host": "postgres", "port": 5432, "dbname": "centerline", "user": "centerline", "password_file": "secrets/postgres-password"},
        "config_dir": ".", "backup_dir": "/backups", "keep": {"days": 7},
    }))
    monkeypatch.setenv("CENTERLINE_OFFHOST", "/offhost")
    s = backup.load_settings(path)
    assert (s.database.host, s.database.user) == ("postgres", "centerline")
    assert s.database.password_file == (tmp_path / "secrets" / "postgres-password").resolve()
    assert (s.config_dir, s.backup_dir, s.offhost_dir) == (tmp_path.resolve(), Path("/backups"), Path("/offhost"))
    assert s.keep == Keep(hours=48, days=7, months=12)
