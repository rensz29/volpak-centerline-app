#!/usr/bin/env bash
# Restores the Docker stack's database, and its settings if this PC has none, from a backup set (BKP-02, ADR-0035).
#
#   deploy/restore.sh deploy/backups/20261007T120200Z          # a set folder, here or from the off-host copy
#   deploy/restore.sh deploy/backups/20261007T120200Z --replace # replace a database that already has records
#
# On a new PC: clone the repository and restore. deploy/config comes from the set when this PC has none; then run
# deploy/setup.sh for anything newer. The script checks the set's checksums, starts only postgres, restores the roles
# and the database, sets the roles' passwords to this PC's secret files, and checks the audit chain. It starts nothing
# else: start the stack when you're ready, and only where no other monitor-core judges the line (ADR-0030).
#
# CENTERLINE_PROJECT names another Compose project, for a drill beside the running stack (deploy/README.md).
set -euo pipefail

started=$(date +%s)
repo="$(cd "$(dirname "$0")/.." && pwd)"
project="${CENTERLINE_PROJECT:-centerline}"
compose=(docker compose -p "$project" -f "$repo/deploy/compose.yaml")
set_dir="${1:?usage: deploy/restore.sh <backup set folder> [--replace]}"
replace="${2:-}"
set_dir="$(cd "$set_dir" && pwd)"
say() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
psql_in() { "${compose[@]}" exec -T postgres psql -X -q -U centerline "$@"; }

# 1. The set is whole: every file is there with the checksum its manifest gives
for f in manifest.json centerline.dump globals.sql config.tar.gz; do
  [[ -f "$set_dir/$f" ]] || { echo "not a backup set: $set_dir/$f is missing" >&2; exit 1; }
done
python3 - "$set_dir" <<'EOF'
import hashlib, json, sys
from pathlib import Path
d = Path(sys.argv[1])
m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
for name, meta in m["files"].items():
    h = hashlib.sha256((d / name).read_bytes()).hexdigest()
    if h != meta["sha256"]:
        sys.exit(f"{name} doesn't match its checksum: the set is damaged")
check = m.get("check") or {}
print(f"set {m['set']} from PostgreSQL {m['server']}; restore check: {check.get('result', 'not run for this set')}")
EOF
say "the set's checksums match"

# 2. The settings: this PC's if it has them, else the set's
if [[ -d "$repo/deploy/config" ]]; then
  say "keeping this PC's deploy/config"
else
  (umask 077 && tar -xzf "$set_dir/config.tar.gz" -C "$repo/deploy")
  chmod 700 "$repo/deploy/config"
  say "restored deploy/config from the set: check deploy/.env, then run deploy/setup.sh for anything newer"
fi

# 3. Only postgres, and an empty database unless --replace
"${compose[@]}" up -d postgres >/dev/null
for _ in $(seq 60); do
  "${compose[@]}" exec -T postgres pg_isready -q -U centerline -d centerline && break
  sleep 2
done
tables=$(psql_in -d centerline -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
if [[ "$tables" != "0" ]]; then
  if [[ "$replace" != "--replace" ]]; then
    echo "the database already has $tables tables: nothing restored. To replace it with the set, add --replace" >&2
    exit 1
  fi
  say "replacing the database: stopping the services"
  "${compose[@]}" stop api monitor-core notifier backup proxy >/dev/null 2>&1 || true
  psql_in -d postgres -c "DROP DATABASE centerline WITH (FORCE)" -c "CREATE DATABASE centerline"
fi

# 4. The roles, then their passwords from this PC's secret files, then the database
psql_in -d postgres < "$set_dir/globals.sql" 2>&1 | grep -v -E 'already exists|^$' || true
python3 - "$repo/deploy/config/secrets" <<'EOF' | psql_in -d postgres
import sys
from pathlib import Path
secrets = Path(sys.argv[1])
for role, name in (("centerline", "postgres-password"), ("centerline_app", "postgres-app-password")):
    f = secrets / name
    if f.exists():
        password = f.read_text(encoding="utf-8").strip().replace("'", "''")
        print(f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN ALTER ROLE {role} PASSWORD '{password}'; END IF; END $$;")
EOF
say "restored the roles, with this PC's passwords"
"${compose[@]}" exec -T postgres pg_restore -U centerline -d centerline --exit-on-error < "$set_dir/centerline.dump"
say "restored the database"

# 5. The audit chain is whole
broken=$(psql_in -d centerline -Atc "SELECT audit_log_verify()")
[[ -z "$broken" ]] || { echo "the restored audit chain breaks at row $broken" >&2; exit 1; }
counts=$(psql_in -d centerline -Atc "SELECT (SELECT count(*) FROM audit_log) || ' audit rows, ' || (SELECT count(*) FROM event) || ' events'")
say "audit chain intact: $counts"
say "done in $(( $(date +%s) - started )) s. Start the stack when ready: docker compose -p $project -f deploy/compose.yaml up -d"
