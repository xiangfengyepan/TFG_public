#!/usr/bin/env bash
# Linux / macOS counterpart of start_api.ps1.
# `$PSScriptRoot` becomes this script's dir; the repo root is one up.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/api/.env"
API_HOST="0.0.0.0"
API_PORT="8000"

# Parse api/.env for API_HOST / API_PORT (skip blanks and comments).
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        trim="${line#"${line%%[![:space:]]*}"}"
        trim="${trim%"${trim##*[![:space:]]}"}"
        [ -z "$trim" ] && continue
        case "$trim" in \#*) continue ;; esac
        key="${trim%%=*}"
        val="${trim#*=}"
        key="${key#"${key%%[![:space:]]*}"}"; key="${key%"${key##*[![:space:]]}"}"
        val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
        val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
        case "$key" in
            API_HOST) API_HOST="$val" ;;
            API_PORT) API_PORT="$val" ;;
        esac
    done < "$ENV_FILE"
fi

echo "Starting EvoMas API server on http://${API_HOST}:${API_PORT}"
exec "$REPO_ROOT/evomas/venv/bin/uvicorn" --app-dir "$REPO_ROOT/api" server:app \
    --host "$API_HOST" --port "$API_PORT" --reload
