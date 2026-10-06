#!/usr/bin/env bash
# Throwaway local Postgres for the DB-dependent tests (added 2026-10-06).
#
# Tests must never reach the database in .env, which is production. Without
# TEST_DATABASE_URL, tests/conftest.py SKIPS the DB-dependent tests. This script
# provides a non-production database so they can run instead:
#
#   scripts/test_db_local.sh start     # initdb + SSL + alembic upgrade head
#   TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/osint_test \
#       .venv311/bin/python -m pytest
#   scripts/test_db_local.sh stop      # stop the server and delete its data dir
#
# Why each step exists (all measured 2026-10-06):
#   * TCP on 127.0.0.1 only, with no unix socket: a socket under a long TMPDIR
#     path exceeds the 103-byte limit.
#   * A self-signed certificate: db/database.py get_engine_args() forces
#     sslmode/ssl=require for every non-Render Postgres host and offers no way to
#     disable it. "require" does not verify the certificate, so a self-signed one
#     suffices and no product code changes.
#   * `alembic upgrade head` on an empty database reaches the current head. The
#     tests need no seed data (tests/api/test_pro_spatial.py docstring).
set -euo pipefail

PORT="${TEST_PG_PORT:-54329}"
DIR="${TEST_PG_DIR:-${TMPDIR:-/tmp}/osint-test-pg}"
URL="postgresql://postgres@127.0.0.1:${PORT}/osint_test"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv311/bin/python}"

case "${1:-}" in
  start)
    if [ ! -d "$DIR/data" ]; then
      mkdir -p "$DIR"
      initdb -D "$DIR/data" -U postgres -A trust >/dev/null
      openssl req -new -x509 -days 30 -nodes -subj "/CN=127.0.0.1" \
        -keyout "$DIR/data/server.key" -out "$DIR/data/server.crt" >/dev/null 2>&1
      chmod 600 "$DIR/data/server.key"
    fi
    pg_ctl -D "$DIR/data" -l "$DIR/log" -w \
      -o "-p $PORT -k '' -c listen_addresses=127.0.0.1 -c ssl=on" start >/dev/null
    createdb -h 127.0.0.1 -p "$PORT" -U postgres osint_test 2>/dev/null || true
    # Refuse to migrate anything that is not this local database.
    (cd "$ROOT" && DATABASE_URL="$URL" "$PY" -c "
from config.settings import settings
assert settings.database_url == '$URL', 'settings did not take the local URL; refusing to migrate'
")
    (cd "$ROOT" && DATABASE_URL="$URL" "$PY" -m alembic upgrade head)
    echo "TEST_DATABASE_URL=$URL"
    ;;
  stop)
    pg_ctl -D "$DIR/data" -w stop >/dev/null 2>&1 || true
    rm -rf "$DIR"
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 2
    ;;
esac
