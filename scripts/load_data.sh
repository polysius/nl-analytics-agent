#!/usr/bin/env bash
# Load the f1db PostgreSQL dump (the maintained successor of the Ergast database) into the
# compose Postgres, then create the read-only role. Safe to rerun: the dump drops its tables first.
set -euo pipefail

VERSION="${F1DB_VERSION:-v2026.20.0}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

curl -fsSL -o "$WORKDIR/f1db.zip" \
  "https://github.com/f1db/f1db/releases/download/${VERSION}/f1db-sql-postgresql.zip"
unzip -q "$WORKDIR/f1db.zip" -d "$WORKDIR"

# MSYS_NO_PATHCONV stops Git Bash on Windows from rewriting the /tmp path.
export MSYS_NO_PATHCONV=1
docker compose cp "$WORKDIR/f1db-sql-postgresql.sql" postgres:/tmp/f1db.sql
docker compose exec -T postgres psql -U admin -d f1 -q -v ON_ERROR_STOP=1 -f /tmp/f1db.sql
docker compose exec -T postgres psql -U admin -d f1 -q < scripts/setup_roles.sql
echo "Loaded f1db ${VERSION} and created role agent_ro"
