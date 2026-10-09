#!/usr/bin/env bash
# The offline install kit (BKP-02, ADR-0037): what a PC without the internet needs to run Centerline again, kept
# beside the backups. Restoring onto a spare PC needs the images, and building them needs the internet: the kit
# carries them instead.
#
#   deploy/kit.sh make [folder]   # a kit of this stack, in deploy/backups/kits/ unless a folder is given
#   deploy/kit.sh verify <kit>    # its checksums, and every archive whole
#   deploy/kit.sh load <kit>      # on the new PC: the images exactly as they were, and ClamAV's signatures
#
# A kit holds no secrets (those travel in the backup sets):
#   images/*.tar.gz     every image the stack runs (docker save); manifest.json has each one's layers' digests, which
#                       identify it on any engine (an image's id depends on the engine's image store)
#   clamav-db.tar.gz    ClamAV's signatures as of the kit's day, so uploads are scanned offline (O-24)
#   centerline.bundle   the repository at the kit's commit (git bundle): clone it for the code and these scripts
#   RESTORE.md          the steps on a new PC; manifest.json; SHA256SUMS
#
# `make` refuses uncommitted changes, which the bundle wouldn't carry (--allow-dirty to make one anyway), keeps the
# two newest kits in its folder, and copies the new kit off-host when deploy/.env names CENTERLINE_BACKUP_OFFHOST.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
project="${CENTERLINE_PROJECT:-centerline}"
compose=(docker compose -p "$project" -f "$repo/deploy/compose.yaml")
say() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { echo "$*" >&2; exit 1; }
KEEP=2

verify() {
  local kit="$1"
  [[ -f "$kit/SHA256SUMS" && -f "$kit/manifest.json" ]] || die "not a kit: $kit"
  (cd "$kit" && sha256sum --quiet -c SHA256SUMS) || die "the kit is damaged: a file doesn't match its checksum"
  for f in "$kit"/images/*.tar.gz "$kit/clamav-db.tar.gz"; do gzip -t "$f" || die "$f isn't whole"; done
  git bundle list-heads "$kit/centerline.bundle" >/dev/null || die "the repository bundle isn't readable"
  say "the kit is whole: $(python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(f\"commit {m['commit']}, made {m['created_at']}\")" "$kit/manifest.json")"
}

make_kit() {
  local allow_dirty="" parent=""
  for a in "$@"; do [[ "$a" == "--allow-dirty" ]] && allow_dirty=1 || parent="$a"; done
  parent="${parent:-$repo/deploy/backups/kits}"
  local dirty=false
  if [[ -n "$(git -C "$repo" status --porcelain)" ]]; then
    [[ -n "$allow_dirty" ]] || die "uncommitted changes: commit them first, so the kit's bundle matches its images (or --allow-dirty)"
    dirty=true
  fi
  local commit stamp name work images=()
  commit="$(git -C "$repo" rev-parse --short HEAD)"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  name="centerline-kit-$commit-$stamp"
  mapfile -t images < <("${compose[@]}" config --images | sort -u)
  for img in "${images[@]}"; do
    docker image inspect "$img" >/dev/null 2>&1 || die "$img isn't on this PC: build the stack first (up -d --build)"
  done
  umask 077
  mkdir -p "$parent"
  work="$parent/$name.partial"
  rm -rf "$work"
  mkdir -p "$work/images"

  for img in "${images[@]}"; do
    say "saving $img"
    docker save "$img" | gzip -1 > "$work/images/$(echo "$img" | tr '/:' '__').tar.gz"
  done
  say "saving ClamAV's signatures"
  docker run --rm -v "${project}_clamav-db:/db:ro" pgvector/pgvector:pg17 tar czf - -C /db . > "$work/clamav-db.tar.gz"
  say "bundling the repository at $commit"
  git -C "$repo" bundle create "$work/centerline.bundle" HEAD "$(git -C "$repo" branch --show-current)" 2>/dev/null
  cp "$repo/deploy/kit-restore.md" "$work/RESTORE.md"

  python3 - "$work" "$commit" "$dirty" "${images[@]}" <<'EOF'
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
work, commit, dirty, images = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "true", sys.argv[4:]
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
def inspect(img, fmt):
    return subprocess.run(["docker", "image", "inspect", img, "--format", fmt], capture_output=True, text=True, check=True).stdout.strip()
manifest = {
    "commit": commit, "dirty": dirty,
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "docker": subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True).stdout.strip(),
    # The layers' content digests identify an image on any engine; its id here depends on this engine's image store
    "images": [{"image": img, "layers": json.loads(inspect(img, "{{json .RootFS.Layers}}")), "id_here": inspect(img, "{{.Id}}"),
                "digests": json.loads(inspect(img, "{{json .RepoDigests}}")),
                "file": f"images/{img.replace('/', '_').replace(':', '_')}.tar.gz"} for img in images],
}
(work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
files = sorted(p for p in work.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
(work / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(work)}\n" for p in files), encoding="utf-8")
EOF
  local final="$parent/$name"
  mv "$work" "$final"
  verify "$final"
  say "kit $name: $(du -sh "$final" | cut -f1)"

  # The two newest kits stay
  mapfile -t old < <(ls -1d "$parent"/centerline-kit-* 2>/dev/null | grep -v '\.partial$' | sort | head -n -"$KEEP")
  for k in "${old[@]}"; do rm -rf "$k"; say "removed the older kit $(basename "$k")"; done

  local offhost
  offhost="$(sed -n 's/^CENTERLINE_BACKUP_OFFHOST=//p' "$repo/deploy/.env" 2>/dev/null | tail -1)"
  if [[ -n "$offhost" ]]; then
    [[ -d "$offhost" ]] || die "the off-host folder $offhost isn't there: the kit is only here"
    mkdir -p "$offhost/kits"
    cp -r "$final" "$offhost/kits/$name.partial" && mv "$offhost/kits/$name.partial" "$offhost/kits/$name"
    verify "$offhost/kits/$name"
    say "copied off-host: $offhost/kits/$name"
  else
    say "no off-host folder in deploy/.env (CENTERLINE_BACKUP_OFFHOST): the kit is only on this PC"
  fi
  [[ "$dirty" == false ]] || say "made from uncommitted changes: its bundle lacks them. Commit, then make another"
}

load_kit() {
  local kit="${1:?usage: deploy/kit.sh load <kit>}"
  kit="$(cd "$kit" && pwd)"
  verify "$kit"
  python3 -c "import json,sys; [print(i['file'], i['image']) for i in json.load(open(sys.argv[1]))['images']]" "$kit/manifest.json" |
    while read -r file img; do
      gunzip -c "$kit/$file" | docker load -q >/dev/null
      # The same layers, digest for digest, as the kit's: the image as it was made
      docker image inspect "$img" --format '{{json .RootFS.Layers}}' | python3 -c "
import json, sys
kit = next(i for i in json.load(open(sys.argv[1]))['images'] if i['image'] == sys.argv[2])
sys.exit(0 if json.load(sys.stdin) == kit['layers'] else 1)" "$kit/manifest.json" "$img" || die "$img loaded with other layers than the kit's"
      say "loaded $img: its layers match the kit's"
    done
  local volume="${project}_clamav-db"
  if docker volume inspect "$volume" >/dev/null 2>&1 &&
     [[ -n "$(docker run --rm -v "$volume:/db:ro" pgvector/pgvector:pg17 ls -A /db)" ]]; then
    say "ClamAV's signatures: keeping the ones already in $volume"
  else
    docker volume create "$volume" >/dev/null
    docker run --rm -i -v "$volume:/db" pgvector/pgvector:pg17 tar xzf - -C /db < "$kit/clamav-db.tar.gz"
    say "ClamAV's signatures loaded into $volume (as of the kit's day)"
  fi
  say "done. Next: deploy/restore.sh <a backup set>, deploy/setup.sh, then deploy/compose.sh up -d (never --build offline): RESTORE.md"
}

case "${1:-}" in
  make) shift; make_kit "$@" ;;
  verify) verify "${2:?usage: deploy/kit.sh verify <kit>}" ;;
  load) load_kit "${2:-}" ;;
  *) die "usage: deploy/kit.sh make [folder] [--allow-dirty] | verify <kit> | load <kit>" ;;
esac
