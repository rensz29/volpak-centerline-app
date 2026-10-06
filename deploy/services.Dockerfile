# The Python services in one image: the api, monitor-core and the notifier, each with its own command
# (deploy/compose.yaml). The repository root is /app, as the code expects (centerline_common.db.REPO):
# the migrations and seeds in /app/db, this host's settings and secrets mounted at /app/config.
FROM python:3.12-slim

ARG UID=1000
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/services/common:/app/services/api:/app/services/monitor_core:/app/services/notifier

WORKDIR /app/services
COPY services/requirements.txt /tmp/requirements.txt
# The runtime part only: the list ends with the development and test tools
RUN sed '/^# development/,$d' /tmp/requirements.txt > /tmp/runtime.txt \
 && pip install --no-cache-dir -r /tmp/runtime.txt \
 && rm /tmp/requirements.txt /tmp/runtime.txt

COPY db /app/db
COPY services/common common
COPY services/api/centerline_api api/centerline_api
COPY services/monitor_core/centerline_monitor monitor_core/centerline_monitor
COPY services/notifier/centerline_notifier notifier/centerline_notifier

# The same uid as the host's config folder, which is bind-mounted; the journal folder seeds its volume, 0700 (RES-01)
RUN useradd --uid "${UID}" --home-dir /app --no-create-home centerline \
 && mkdir -p /app/config /app/data/journal \
 && chown centerline /app/config /app/data /app/data/journal \
 && chmod 700 /app/data/journal
USER centerline
