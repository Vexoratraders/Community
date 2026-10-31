#!/usr/bin/env sh
set -eu
if [ "$#" -ne 1 ] || [ ! -s "$1" ]; then
  echo "Usage: $0 backups/vexora-YYYYMMDDTHHMMSSZ.sql.gz" >&2
  exit 2
fi
echo "WARNING: this overwrites the current VEXORA database. Stop the app and ensure a separate backup exists."
printf 'Type RESTORE to continue: '
read answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
gunzip -c "$1" | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
