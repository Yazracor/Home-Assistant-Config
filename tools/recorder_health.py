"""Small read-only Recorder probe; no table scans or database maintenance."""

import json
from pathlib import Path
import sqlite3
import sys
import time


def probe(database):
    database = Path(database).resolve()
    result = {"ok": 0, "checked_at": int(time.time())}
    started = time.monotonic()
    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            db.set_progress_handler(lambda: int(time.monotonic() - started > 3), 1000)
            # This existing sensor changes its checked_at attribute every minute.
            # Use its indexed history, not MAX() over the entire states table.
            row = db.execute(
                "SELECT last_updated_ts FROM states WHERE metadata_id = "
                "(SELECT metadata_id FROM states_meta WHERE entity_id = ?) "
                "ORDER BY last_updated_ts DESC LIMIT 1",
                ("sensor.home_assistant_config_update_pending",),
            ).fetchone()
        result["query_ms"] = round((time.monotonic() - started) * 1000, 3)
        if row is None or row[0] is None:
            result["error"] = "heartbeat_missing"
        else:
            result["heartbeat_age_s"] = round(max(0, time.time() - row[0]), 1)
            result["ok"] = 1
        result["database_mib"] = round(database.stat().st_size / 1048576, 3)
        wal = Path(str(database) + "-wal")
        try:
            result["wal_mib"] = round(wal.stat().st_size / 1048576, 3)
        except FileNotFoundError:
            result["wal_mib"] = 0
    except (sqlite3.Error, OSError) as error:
        result["ok"] = 0
        result["error"] = type(error).__name__
    return result


if __name__ == "__main__":
    print(json.dumps(probe(sys.argv[1] if len(sys.argv) > 1 else "/config/home-assistant_v2.db")))
