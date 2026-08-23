# Rollback SOP

## SQLite

1. Stop app container.
2. **Remove old WAL helper files** (server runs in WAL mode — these belong to
   the current db, not the backup):
   ```bash
   rm -f /data/beecount.db-wal /data/beecount.db-shm
   ```
3. Restore db file (backup is always a clean single file, no -wal / -shm):
   ```bash
   cp backups/sqlite/beecount-<ts>.db /data/beecount.db
   ```
4. Start app container. SQLite will auto-create new -wal / -shm on first
   connection.
5. Verify:
   - `GET /ready`
   - Container health, version, logs, and read-only ledger/transaction
     projection checks.
   - Do not run a write smoke test by default. Any write verification needs a
     separate explicit approval and an isolated test resource.

> Why step 2? In WAL mode `/data` contains `beecount.db` + `beecount.db-wal`
> + `beecount.db-shm`. If you only overwrite `beecount.db` and leave the old
> -wal around, SQLite will try to "recover" the old WAL log into the new
> database and corrupt your restore. Always delete them first.

On macOS/Colima, an integrity check issued by the host against the active
bind-mounted WAL database is diagnostic only, not a rollback gate. Check the
clean backup before replacement, or run the in-container online-backup helper
and validate its clean output. Never treat `/ready` alone as a SQLite
integrity check.

## PostgreSQL

1. Stop app container.
2. Restore SQL dump:
   - `cat backups/postgres/beecount-<ts>.sql | docker compose -f docker-compose.yml -f docker-compose.postgres.yml exec -T db psql -U beecount -d beecount`
3. Start app container.
4. Verify:
   - `GET /ready`
   - health, version, logs, and a read-only data check.
   - A write smoke test is not part of the default rollback gate; it requires
     separate explicit approval and an isolated test resource.

## Post-check

- `GET /metrics` is available.
- `admin/sync/errors` has no new critical errors.
- If backup artifacts are used, verify:
  - `GET /api/v1/admin/backups/artifacts?ledger_id=<id>`
  - uploaded `snapshot` artifacts can be restored via `admin/backups/restore`.
