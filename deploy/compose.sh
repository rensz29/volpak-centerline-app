#!/usr/bin/env bash
# The stack as this PC runs it (ADR-0049, ADR-0050): deploy/compose.yaml, plus
#   deploy/compose.sim.yaml   when deploy/.env has CENTERLINE_SIMULATOR=on: the simulated line, away from the plant only
# so every command keeps it, and nothing brings the simulator onto the line. Ollama isn't in this stack: the api asks
# the one CENTERLINE_OLLAMA_URL names (deploy/ollama/ runs one). Any docker compose command:
#   deploy/compose.sh up -d --build
#   deploy/compose.sh ps
#   deploy/compose.sh exec ollama ollama list
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
setting() { sed -n "s/^$1=//p" "$repo/deploy/.env" 2>/dev/null | tail -1 | tr -d "\"'\r"; }

files=(-f "$repo/deploy/compose.yaml")
if [[ "$(setting CENTERLINE_SIMULATOR)" == "on" ]]; then
  files+=(-f "$repo/deploy/compose.sim.yaml")
fi
exec docker compose "${files[@]}" "$@"
