#!/usr/bin/env python3
"""One-time scrub of the LEGACY conversations.db before archival.

The old app stored raw client IPs as conversations.user_id — an education
record tied to a network identifier. This replaces every user_id with a
salted hash so the archive keeps its analytic value (distinct users, session
grouping) without the identifier.

    python scripts/scrub_legacy_db.py /path/to/conversations.db
    # writes /path/to/conversations.scrubbed.db, original untouched
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import sqlite3
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    dst = src.replace(".db", ".scrubbed.db")
    salt = os.environ.get("EXPORT_SALT", "legacy-scrub-salt")
    shutil.copy2(src, dst)

    conn = sqlite3.connect(dst)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM conversations")
    mapping = {
        uid: "legacy:" + hmac.new(salt.encode(), str(uid).encode(),
                                  hashlib.sha256).hexdigest()[:12]
        for (uid,) in cur.fetchall()
    }
    for old, new in mapping.items():
        cur.execute("UPDATE conversations SET user_id = ? WHERE user_id = ?",
                    (new, old))
    conn.commit()
    cur.execute("VACUUM")  # drop old pages containing the raw values
    conn.close()
    print(f"Scrubbed {len(mapping)} distinct user_ids → {dst}")
    print("Archive the scrubbed copy; shred the original once verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
