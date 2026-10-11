#!/bin/sh
set -eu
umask 077
PROJECT_DIR=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  . "$PROJECT_DIR/.env"
  set +a
fi

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "Virtual environment is missing. Follow the setup steps in README.md." >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs" "$PROJECT_DIR/backups"
export HOUSEHOLD_DEBUG=0
export HOUSEHOLD_DATA_DIR="${HOUSEHOLD_DATA_DIR:-$PROJECT_DIR/data}"
export HOUSEHOLD_ALLOWED_HOSTS="${HOUSEHOLD_ALLOWED_HOSTS:-localhost,127.0.0.1}"
if [ -z "${HOUSEHOLD_BIND_IP:-}" ]; then
  echo "Set HOUSEHOLD_BIND_IP to this host's reserved home-network IPv4 address in .env." >&2
  exit 1
fi

exec "$PROJECT_DIR/.venv/bin/python" -m waitress \
  --listen="127.0.0.1:8000 ${HOUSEHOLD_BIND_IP}:8000" \
  --max-request-body-size=131072 \
  --max-request-header-size=16384 \
  config.wsgi:application
