#!/bin/sh
# Postgres backups for the v1 stack (ARCHITECTURE_V1 6.1 and 6.6). Runs as the `backup`
# Compose service, or once by hand with `backup.sh once`.
#
# Each database is dumped on its own schedule into its own directory, so the two can sit on
# separate volumes or storage accounts (a restore of one must not revive a key deleted in
# the other). Files older than the retention are deleted after every dump. The retention
# default is 35 days less one interval, so no dump is older than 35 days when it is deleted:
# that is what the consent text ("backups clear within 35 days") promises.
#
# Connection comes from the standard PGHOST, PGPORT, PGUSER and PGPASSWORD variables.
#   BACKUP_DIR              default /backups; subdirectories `perch` and `perch_keys`
#   BACKUP_INTERVAL_S       default 86400
#   BACKUP_RETENTION_DAYS   default 35
#   BACKUP_DATABASES        default "perch perch_keys"
#   BACKUP_KEYS_DIR         optional separate root for perch_keys (a second volume)
#
# After ANY restore, run `perch reconcile-shreds` before serving (ARCHITECTURE_V1 6.6).
set -eu

DIR=${BACKUP_DIR:-/backups}
EVERY=${BACKUP_INTERVAL_S:-86400}
KEEP_DAYS=${BACKUP_RETENTION_DAYS:-35}
DBS=${BACKUP_DATABASES:-perch perch_keys}
KEEP_MIN=$(( (KEEP_DAYS * 86400 - EVERY) / 60 ))

dump_one() {
  db=$1
  root=$DIR
  if [ "$db" = "perch_keys" ] && [ -n "${BACKUP_KEYS_DIR:-}" ]; then root=$BACKUP_KEYS_DIR; fi
  mkdir -p "$root/$db"
  f="$root/$db/$db-$(date -u +%Y%m%dT%H%M%SZ).dump"
  if pg_dump --format=custom --dbname="$db" --file="$f.part"; then
    mv "$f.part" "$f"
    echo "backup ok db=$db file=$(basename "$f") bytes=$(wc -c < "$f")"
  else
    rm -f "$f.part"
    echo "backup FAILED db=$db" >&2
    return 1
  fi
  find "$root/$db" -name '*.dump' -mmin "+$KEEP_MIN" -print -delete \
    | sed 's/^.*\//pruned /'
}

run_all() {
  rc=0
  for db in $DBS; do dump_one "$db" || rc=1; done
  return $rc
}

if [ "${1:-loop}" = "once" ]; then
  run_all
  exit $?
fi

while true; do
  run_all || true
  touch /tmp/backup-heartbeat
  sleep "$EVERY"
done
