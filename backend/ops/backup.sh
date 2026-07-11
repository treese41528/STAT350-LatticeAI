#!/usr/bin/env bash
# Nightly SQLite backup — safe under WAL, no downtime. The DB is research
# data now; a backup never restored is a hope, not a backup (rehearse once:
#   sqlite3 backups/tutor-YYYY-MM-DD.db "PRAGMA integrity_check").
set -euo pipefail

BACKEND="${BACKEND_DIR:-/opt/stat350-tutor/backend}"
DB="$BACKEND/data/tutor.db"
OUT_DIR="$BACKEND/backups"
STAMP="$(date +%F)"
OUT="$OUT_DIR/tutor-$STAMP.db"

mkdir -p "$OUT_DIR"
sqlite3 "$DB" ".backup '$OUT'"
CHECK=$(sqlite3 "$OUT" "PRAGMA integrity_check;")
if [ "$CHECK" != "ok" ]; then
    echo "BACKUP INTEGRITY FAILED: $CHECK" >&2
    exit 1
fi

# keep 14 dailies; weekly (Sunday) copies kept 8 weeks
find "$OUT_DIR" -name 'tutor-*.db' -mtime +14 ! -name '*-sun.db' -delete
if [ "$(date +%u)" = "7" ]; then
    cp "$OUT" "$OUT_DIR/tutor-$STAMP-sun.db"
fi
find "$OUT_DIR" -name '*-sun.db' -mtime +56 -delete

# OFF-HOST copy matters — uncomment and point at Data Depot / rclone remote:
# rsync -a "$OUT" depot:/depot/stat350/tutor-backups/
echo "backup ok: $OUT"
