#!/usr/bin/env bash
# This host's settings for the Docker stack (deploy/compose.yaml, ADR-0030), in deploy/config (git-ignored, 0700).
#
#   deploy/setup.sh
#
# Seeded once from the development config/ folder: the parameter register, the plant connections (the broker, the
# historian, the notification channels) with the secrets they name, and the old pre-database history. The stack gets
# its own database password; the api makes the services' role password at its first start. Nothing that's already
# in deploy/config is overwritten, and no secret is printed.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
src="$repo/config"
dst="$repo/deploy/config"
umask 077
mkdir -p "$dst/secrets" "$dst/history" "$dst/logs"
chmod 700 "$dst" "$dst/secrets"

copy() {  # copy <path under config/>, if it's there and not copied yet
  if [[ -e "$src/$1" && ! -e "$dst/$1" ]]; then
    mkdir -p "$(dirname "$dst/$1")"
    cp -p "$src/$1" "$dst/$1"
    chmod 600 "$dst/$1"
    echo "copied   config/$1"
  fi
}

copy parameter-register.json
copy connections.json
copy history/audit.jsonl

# The secrets connections.json names: the broker's password and CA, the Teams flow's URL, the relay's password
if [[ -e "$dst/connections.json" ]]; then
  python3 - "$dst/connections.json" <<'EOF' | while read -r f; do copy "$f"; done
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
m, n = c.get("mqtt") or {}, c.get("notifications") or {}
for f in (m.get("password_file"), (m.get("tls") or {}).get("ca_file"), (n.get("teams") or {}).get("url_file"),
          (n.get("email") or {}).get("password_file"), (c.get("historian") or {}).get("token_file")):
    if f and not f.startswith("/"):
        print(f)
EOF
fi

if [[ ! -e "$dst/secrets/postgres-password" ]]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$dst/secrets/postgres-password"
  echo "created  secrets/postgres-password (the stack's database owner)"
fi

# The three services' settings: the database by its service name, everything else in this folder
python3 - "$dst" "$repo/services/api/config.json" <<'EOF'
import json, os, sys
dst, dev = sys.argv[1], sys.argv[2]
db = {"host": "postgres", "port": 5432, "dbname": "centerline"}
app = {**db, "user": "centerline_app", "password_file": "secrets/postgres-app-password"}
timebase = {"base_url": "http://10.156.116.179:4516", "dataset": "dressings", "timeout_s": 60, "auth": {"type": "none"}}
SCANNER = {"type": "clamd", "host": "clamav", "port": 3310, "timeout_s": 60}  # the clamav container (ADR-0031)
if os.path.exists(dev):
    timebase = json.load(open(dev, encoding="utf-8")).get("timebase") or timebase
files = {
    "api.json": {
        "_note": "The Docker stack's api (deploy/compose.yaml, ADR-0030). Paths are relative to this folder.",
        "timebase": timebase,
        "register": "parameter-register.json",
        "config_dir": ".",
        "audit_log": "logs/analytics-queries.jsonl",
        "database": app,
        "migrate_database": {**db, "user": "centerline", "password_file": "secrets/postgres-password"},
        "auth": {"trusted_proxies": ["proxy"], "operator_workstations": []},
        "scanner": SCANNER,
    },
    "monitor-core.json": {"database": app, "config_dir": ".", "instance": "centerline-docker", "journal_dir": "/app/data/journal"},
    "notifier.json": {"database": app, "config_dir": ".", "instance": "centerline-docker"},
    # The owner: the roles (pg_dumpall) and the daily restore check's scratch database need it (ADR-0035)
    "backup.json": {
        "_note": "The Docker stack's backup agent (ADR-0035). The sets go to /backups: CENTERLINE_BACKUP_DIR in deploy/.env, else deploy/backups.",
        "database": {**db, "user": "centerline", "password_file": "secrets/postgres-password"},
        "config_dir": ".",
        "backup_dir": "/backups",
        "keep": {"hours": 48, "days": 30, "months": 12},
    },
}
for name, content in files.items():
    path = os.path.join(dst, name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2)
            f.write("\n")
        os.chmod(path, 0o600)
        print(f"wrote    {name}")
# An api.json from before ADR-0031 gets the scanner; nothing else in it changes
path = os.path.join(dst, "api.json")
api = json.load(open(path, encoding="utf-8"))
if "scanner" not in api:
    api["scanner"] = SCANNER
    with open(path, "w", encoding="utf-8") as f:
        json.dump(api, f, indent=2)
        f.write("\n")
    print("added    the malware scanner (clamav) to api.json")
EOF

# The backups' folder, made here so Docker doesn't make it as root (ADR-0035). The sets hold every record and this
# host's secrets: this user only
mkdir -p "$repo/deploy/backups/no-offhost"
chmod 700 "$repo/deploy/backups"

# Where browsers reach it: this PC only, until deploy/.env says otherwise
if [[ ! -e "$repo/deploy/.env" ]]; then
  cat > "$repo/deploy/.env" <<'ENV'
# This host's address for the Docker stack (deploy/compose.yaml). Git-ignored. Restart the proxy after a change:
#   docker compose -f deploy/compose.yaml up -d proxy

# http (the default, ADR-0032): plain HTTP, no certificate. https: Caddy's own CA signs one for CENTERLINE_SITE.
CENTERLINE_SCHEME=http
# HTTPS only: the names and addresses browsers open Centerline at, comma-separated. The certificate covers each one.
CENTERLINE_SITE=localhost
# HTTPS only: the one used when a browser opens it by IP address: put that address here too.
CENTERLINE_DEFAULT_SNI=localhost
# 127.0.0.1: this PC only. 0.0.0.0: the plant LAN too (open the port in the firewall as well).
CENTERLINE_BIND=127.0.0.1
CENTERLINE_PORT=6040
# The services run as this user id, the owner of deploy/config (rebuild after a change: up -d --build)
ENV
  echo "CENTERLINE_UID=$(id -u)" >> "$repo/deploy/.env"
  echo "wrote    deploy/.env (this PC only, port 6040, user id $(id -u))"
fi

# The backups' places (ADR-0035), added once to a deploy/.env from before them
if ! grep -q CENTERLINE_BACKUP_OFFHOST "$repo/deploy/.env"; then
  cat >> "$repo/deploy/.env" <<'ENV'

# Backups (ADR-0035): a set every hour in deploy/backups, or the folder CENTERLINE_BACKUP_DIR names. An off-host copy
# goes to CENTERLINE_BACKUP_OFFHOST: a folder on another disk or a mounted network share. Until it's set, the sets
# are only on this PC. Then: docker compose -f deploy/compose.yaml up -d backup
#CENTERLINE_BACKUP_DIR=
#CENTERLINE_BACKUP_OFFHOST=
ENV
  echo "added    the backup settings to deploy/.env (no off-host folder yet)"
fi

echo "deploy/config is ready. Next: docker compose -f deploy/compose.yaml up -d --build (see deploy/README.md)"
