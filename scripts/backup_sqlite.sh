#!/usr/bin/env bash
# WAL-safe SQLite backup using Python's SQLite Online Backup API.
#
# Why not `cp`?
#   - WAL mode: `cp db.sqlite3` alone loses uncommitted writes still in -wal
#   - DELETE mode: `cp` during active writes can produce a torn / corrupt file
#
# Python's `sqlite3.Connection.backup()` works on a running database in any
# journal mode and always produces a clean single-file snapshot (no -wal /
# -shm needed). Python is already present in the BeeCount image; the sqlite3
# CLI is not.
#
# Usage:
#   ./backup_sqlite.sh [DB_PATH] [OUT_DIR]
# Defaults:
#   DB_PATH = /data/beecount.db
#   OUT_DIR = ./backups/sqlite
set -euo pipefail

DB_PATH="${1:-/data/beecount.db}"
OUT_DIR="${2:-./backups/sqlite}"
TS="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="$OUT_DIR/beecount-${TS}.db"

mkdir -p "$OUT_DIR"

if [ -e "$OUT_FILE" ]; then
  echo "ERROR: backup target already exists: $OUT_FILE" >&2
  exit 1
fi

# Write to a private temporary file first. A failed backup or failed integrity
# check must not leave a file that looks like a usable backup.
TMP_FILE="$(mktemp "$OUT_DIR/.beecount-${TS}.db.tmp.XXXXXX")"
cleanup() { rm -f -- "$TMP_FILE"; }
trap cleanup EXIT

python3 - "$DB_PATH" "$TMP_FILE" <<'PY'
from pathlib import Path
import sqlite3
import sys

source_path, target_path = sys.argv[1:3]
source = sqlite3.connect(Path(source_path).resolve().as_uri() + "?mode=ro", uri=True)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
    integrity = target.execute("PRAGMA integrity_check").fetchone()
    quick = target.execute("PRAGMA quick_check").fetchone()
    if integrity != ("ok",) or quick != ("ok",):
        raise RuntimeError(
            f"backup verification failed: integrity_check={integrity!r}, quick_check={quick!r}"
        )
finally:
    target.close()
    source.close()
PY

# Publish with link(2), whose destination creation is atomic and fails when a
# concurrent process creates the target after the initial existence check.
python3 - "$TMP_FILE" "$OUT_FILE" <<'PY'
import os
import sys

source_path, target_path = sys.argv[1:3]
try:
    os.link(source_path, target_path)
except FileExistsError:
    print(f"ERROR: backup target appeared during backup: {target_path}", file=sys.stderr)
    raise SystemExit(1)
PY
rm -f -- "$TMP_FILE"
echo "backup created: $OUT_FILE"
