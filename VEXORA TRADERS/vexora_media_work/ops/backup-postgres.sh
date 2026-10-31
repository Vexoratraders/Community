#!/usr/bin/env sh
set -eu
# Run from the project directory with Docker Compose and a configured private .env.
# Output is a compressed, timestamped logical backup on the host.
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file="backups/vexora-${stamp}.sql.gz"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > "$file"
test -s "$file"
echo "Backup created: $file"
echo "Copy this file to encrypted off-site storage and test restore procedures regularly."
