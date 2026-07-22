"""
Scrape result cache, keyed by (container, scrape_date) - FEASIBILITY.md
§10: a same-day re-run reads cache instead of hitting the carrier site
again. Stores the raw scraped payload (e.g. the raw event list as JSON),
not classified/inferred results - classification is cheap and should
always run fresh against the current taxonomy; only the network fetch
is worth avoiding.
"""
import sqlite3
from datetime import date, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_cache (
    container TEXT NOT NULL,
    scrape_date TEXT NOT NULL,
    carrier TEXT NOT NULL,
    payload TEXT NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (container, scrape_date, carrier)
);
"""


class ScrapeCache:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ScrapeCache":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def get(self, container: str, on_date: date, carrier: str) -> str | None:
        row = self._conn.execute(
            "SELECT payload FROM scrape_cache WHERE container = ? AND scrape_date = ? AND carrier = ?",
            (container, on_date.isoformat(), carrier),
        ).fetchone()
        return row[0] if row is not None else None

    def put(self, container: str, on_date: date, carrier: str, payload: str) -> None:
        self._conn.execute(
            """
            INSERT INTO scrape_cache (container, scrape_date, carrier, payload, cached_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (container, scrape_date, carrier)
            DO UPDATE SET payload = excluded.payload, cached_at = excluded.cached_at
            """,
            (container, on_date.isoformat(), carrier, payload, datetime.now().isoformat()),
        )
        self._conn.commit()
