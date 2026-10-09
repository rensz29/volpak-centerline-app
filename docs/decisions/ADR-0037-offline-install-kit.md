# ADR-0037: The offline install kit

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decider:** Szyrelle (system owner), on 2026-10-07: "do it now", for the next step recommended after the backups:
  the SDD's offline install kit (§13), so a restore at the plant doesn't need the internet.
- **URS:** BKP-02 (RTO 4 h; a quarterly restore without the internet), DEP-02, A-10; helps O-24

## Context

- The backups (ADR-0035) restore the database in seconds. But a spare PC also needs the application's images, and
  building them needs the internet: Debian's packages, Python's and npm's libraries, Docker Hub. The plant LAN has no
  internet (A-10). So the 4-hour target depended on a download.
- ClamAV fetches its signatures from the internet (O-24). A new PC on the plant LAN would refuse every upload until it
  had some.
- The SDD's §13 plans an offline install kit "stored with the backups".

## Decision

1. **`deploy/kit.sh make`** writes a kit folder, `centerline-kit-<commit>-<UTC time>`, with:
   - **`images/*.tar.gz`:** every image `deploy/compose.yaml` runs (`docker save`, compressed);
   - **`clamav-db.tar.gz`:** ClamAV's signatures from the running stack;
   - **`centerline.bundle`:** the repository at the kit's commit (`git bundle`), for the code and the scripts;
   - **`RESTORE.md`:** the steps on a new PC, from `deploy/kit-restore.md`;
   - **`manifest.json`** and **`SHA256SUMS`**.

   It holds **no secrets**: they travel in the backup sets. It refuses uncommitted changes, which the bundle wouldn't
   carry, unless `--allow-dirty`.
2. **Where:** `deploy/backups/kits/` by default (git-ignored), keeping the two newest. It's copied to the off-host
   folder too when `deploy/.env` names one (O-27).
3. **An image is identified by its layers' content digests,** recorded in the manifest. Its id isn't used: the id
   depends on the engine's image store. Docker Desktop's classic store and a containerd store give the same image
   different ids, while its layers are digest for digest the same.
4. **`deploy/kit.sh verify`** checks every file against its checksum, every archive whole, and the bundle readable.
   **`deploy/kit.sh load`** verifies, loads each image, checks its layers against the manifest, and loads ClamAV's
   signatures into an empty volume. It keeps the ones a volume already has.
5. **Make a kit after each release:** after every `up -d --build` that changes an image, and before a drill. A kit
   is about 600 MB.

## Consequences

- **A restore needs only Docker, git, a kit and a backup set:** Docker and git come from IT's offline packages.
  `RESTORE.md` walks through it, and starts the stack without `--build`.
- **ClamAV scans offline** with the signatures as of the kit's day. That's only as fresh as the last kit, so O-24
  stays open for keeping them up to date at the plant.
- **Not in the kit:**
  - Docker Engine and git themselves, which depend on the PC's operating system;
  - the AI model files, which don't exist yet (O-01).
- A kit made from uncommitted changes would carry images that don't match its bundle, so `make` refuses one by default.

## Tests

On 2026-10-07, from this laptop's stack:
- `make`: 607 MB in 44 s, then verified.
- A Docker with no images and no network (Docker-in-Docker with `--network none`, a containerd image store) loaded all
  four images. Each one's layers matched the manifest; their ids differed, as decision 3 expects, which is why the ids
  aren't used.
- From the kit's signatures, ClamAV started there with no network in about 16 s, found the EICAR test file, and
  passed a clean one.
- `load` on this laptop: every image's layers matched; the existing signatures were kept.
- The test kit, made from uncommitted changes, was deleted afterwards: its bundle lacked these scripts.
