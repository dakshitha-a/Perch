#!/usr/bin/env bash
# Restore test (ARCHITECTURE_V1 6.6, Phase 10): dump a database, restore the dump into a
# scratch database, compare the row count of every public table, then drop the scratch
# database. Exit 0 only if every table matches. Prints counts only, never row text.
#
#   restore_test.sh [SOURCE_DB] [DUMP_FILE]
#
# SOURCE_DB defaults to `perch`. With DUMP_FILE (a backup.sh file) that file is restored;
# without it a fresh dump of SOURCE_DB is taken. Tools run through $PG_EXEC when set, for a
# host without the Postgres client, for example:
#   PG_EXEC="docker exec -i perch-test-pg" restore_test.sh perch_dev
# Connection settings are the standard PG* variables (or the container's local socket).
# The SCRATCH name is perch_restore_scratch_<timestamp>; it is refused if it matches SOURCE_DB.
set -eu

SRC=${1:-perch}
DUMP=${2:-}
X=${PG_EXEC:-}
SCRATCH="perch_restore_scratch_$(date -u +%Y%m%d%H%M%S)"
TMP=$(mktemp)
trap '$X psql -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true; rm -f "$TMP"' EXIT

COUNTS="SELECT table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"

if [ -n "$DUMP" ]; then
  cat "$DUMP" > "$TMP"
else
  $X pg_dump --format=custom --dbname="$SRC" > "$TMP"
fi
echo "dump bytes=$(wc -c < "$TMP")"

$X psql -q -d postgres -c "CREATE DATABASE $SCRATCH"
# --no-owner: roles may not exist on the scratch server; extensions come back with the dump.
$X pg_restore --no-owner --exit-on-error --dbname="$SCRATCH" < "$TMP"

before=$($X psql -At -F ' ' -d "$SRC" -c "$COUNTS")
after=$($X psql -At -F ' ' -d "$SCRATCH" -c "$COUNTS")
tables=$(printf '%s\n' "$after" | grep -c . || true)
rows=$(printf '%s\n' "$after" | awk '{s += $2} END {print s + 0}')
if [ "$before" = "$after" ] && [ "$tables" -gt 0 ]; then
  echo "restore ok: tables=$tables rows=$rows scratch=$SCRATCH (dropped)"
else
  echo "restore MISMATCH between $SRC and $SCRATCH" >&2
  diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") >&2 2>/dev/null || true
  exit 1
fi
