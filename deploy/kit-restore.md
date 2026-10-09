# Restore Centerline on a new PC, without the internet

This kit and a backup set are all you need. The kit has the application. The backup set has the database and the
settings: the newest set from the off-host folder, or `deploy/backups/` if the old PC's disk still reads. Target: back
in under 4 hours (BKP-02).

Write down the time you start.

1. **Docker and git.** Install Docker Engine with the Compose plugin, and git, from IT's offline packages. Check:
   `docker version` and `docker compose version`.
   - **With an NVIDIA GPU** (the AI runs on it, ADR-0049): its driver and, on Linux, the NVIDIA Container Toolkit,
     from IT's offline packages too. After step 3, `docker run --rm --gpus all pgvector/pgvector:pg17 nvidia-smi -L`
     must list the GPU.
2. **The code.** Clone the kit's repository and go into it:
   ```bash
   git clone <kit>/centerline.bundle centerline
   cd centerline
   ```
3. **The images.** Load them, and ClamAV's signatures:
   ```bash
   deploy/kit.sh load <kit>
   ```
   It checks every file first, and stops if anything doesn't match.
4. **The database and the settings.**
   ```bash
   deploy/restore.sh <backup set>
   ```
   With no `deploy/config` on this PC, it takes the settings from the set. It restores the database, checks the audit
   chain, and starts nothing else.
5. **This PC's address.** In `deploy/.env`, set `CENTERLINE_BIND`, `CENTERLINE_PORT` and, for HTTPS, `CENTERLINE_SITE`.
   Then run `deploy/setup.sh`, which only adds what's missing. It checks whether Docker reaches an NVIDIA GPU and
   writes `CENTERLINE_GPU` (`nvidia` or `none`); `CENTERLINE_SIMULATOR` must stay `off`.
6. **Start it,** without `--build` (building needs the internet):
   ```bash
   deploy/compose.sh up -d
   deploy/compose.sh ps
   ```
   - **If the old PC might still be judging the line,** stop it there first. Two monitor-cores mean two judges and
     two histories.
   - **For a drill,** stop this monitor-core at once: `deploy/compose.sh stop monitor-core`.
7. **Check.** Sign in, and open Digital Centerline and Alarms. On System health, the AI model should say it's on the
   GPU (a minute after the start, once it's loaded). Write down the time.

Anything judged after the set's time is lost: at most an hour.

**For a quarterly drill (BKP-02):** use a clean machine with no internet, the newest off-host set and kit, and record
both times.
