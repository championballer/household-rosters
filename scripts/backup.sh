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
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/manage.py" backup_database
