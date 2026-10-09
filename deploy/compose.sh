#!/usr/bin/env bash
# The stack as this PC runs it (ADR-0049): deploy/compose.yaml, plus
#   deploy/compose.gpu.yaml   when deploy/.env has CENTERLINE_GPU=nvidia: Ollama on the NVIDIA GPU
#   deploy/compose.sim.yaml   when deploy/.env has CENTERLINE_SIMULATOR=on: the simulated line, away from the plant only
# so every command keeps them, and a restart never brings Ollama back without its GPU. Any docker compose command:
#   deploy/compose.sh up -d --build
#   deploy/compose.sh ps
#   deploy/compose.sh exec ollama ollama list
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
setting() { sed -n "s/^$1=//p" "$repo/deploy/.env" 2>/dev/null | tail -1 | tr -d "\"'\r"; }

files=(-f "$repo/deploy/compose.yaml")
if [[ "$(setting CENTERLINE_GPU)" == "nvidia" ]]; then
  files+=(-f "$repo/deploy/compose.gpu.yaml")
fi
if [[ "$(setting CENTERLINE_SIMULATOR)" == "on" ]]; then
  files+=(-f "$repo/deploy/compose.sim.yaml")
fi
exec docker compose "${files[@]}" "$@"
