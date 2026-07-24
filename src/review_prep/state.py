"""SQLite persistence for prep runs, delivery routes, and launch leases."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


class StateRepo:
    """SQLite-backed repository for daily review prep state.

    Persists prep runs, per-card delivery route status, and once-per-day
    launch leases so the assistant can resume and avoid duplicate launches.

    Attributes:
        db_path (Path): Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the repository with a database path.

        Args:
            db_path (Path): Path to the SQLite database file.
        """
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with row factory enabled.

        Returns:
            (sqlite3.Connection) Open database connection.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def ensure_schema(self) -> None:
        """Create tables if they do not already exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS prep_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    local_date TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    acked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prep_run_id INTEGER NOT NULL,
                    card_sg_id INTEGER NOT NULL,
                    route_kind TEXT NOT NULL,
                    route_key TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (card_sg_id, route_kind, route_key),
                    FOREIGN KEY (prep_run_id) REFERENCES prep_runs(id)
                );

                CREATE TABLE IF NOT EXISTS launch_leases (
                    file_key TEXT NOT NULL,
                    local_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (file_key, local_date)
                );
                """
            )

    def start_prep_run(self, local_date: str, trigger: str) -> int:
        """Insert a new prep run and return its id.

        Args:
            local_date (str): Local calendar date for the run (YYYY-MM-DD).
            trigger (str): What started the run (e.g. scheduled, manual).

        Returns:
            (int) The new prep_runs row id.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prep_runs (local_date, trigger, created_at, acked_at)
                VALUES (?, ?, ?, NULL)
                """,
                (local_date, trigger, _utc_now_iso()),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("INSERT into prep_runs did not return a row id")
            return int(row_id)

    def upsert_route(self, *, prep_run_id: int, card_sg_id: int, route_kind: str, route_key: str, state: str, detail: str) -> None:
        """Insert or update a delivery route by card/kind/key.

        Args:
            prep_run_id (int): Owning prep run id.
            card_sg_id (int): ShotGrid card entity id.
            route_kind (str): Delivery route kind value.
            route_key (str): Stable route key within the card.
            state (str): Current route state value.
            detail (str): Human-readable status detail.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO routes (
                    prep_run_id, card_sg_id, route_kind, route_key,
                    state, detail, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (card_sg_id, route_kind, route_key) DO UPDATE SET
                    prep_run_id = excluded.prep_run_id,
                    state = excluded.state,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (prep_run_id, card_sg_id, route_kind, route_key, state, detail, _utc_now_iso()),
            )

    def get_routes_for_card(self, card_id: int) -> list[dict[str, object]]:
        """Return all routes for a ShotGrid card.

        Args:
            card_id (int): ShotGrid card entity id.

        Returns:
            (list[dict[str, object]]) Route rows as plain dicts.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, prep_run_id, card_sg_id, route_kind, route_key,
                       state, detail, updated_at
                FROM routes
                WHERE card_sg_id = ?
                ORDER BY id
                """,
                (card_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_routes_for_date(self, local_date: str) -> list[dict[str, object]]:
        """Return all routes belonging to prep runs on a local date.

        Args:
            local_date (str): Local calendar date (YYYY-MM-DD).

        Returns:
            (list[dict[str, object]]) Route rows as plain dicts.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.prep_run_id, r.card_sg_id, r.route_kind, r.route_key,
                       r.state, r.detail, r.updated_at
                FROM routes r
                JOIN prep_runs p ON p.id = r.prep_run_id
                WHERE p.local_date = ?
                ORDER BY r.id
                """,
                (local_date,),
            ).fetchall()
            return [dict(row) for row in rows]

    def has_launch_lease(self, file_key: str, local_date: str) -> bool:
        """Return whether a launch lease exists for the file on that date.

        Args:
            file_key (str): Stable key for the file.
            local_date (str): Local calendar date (YYYY-MM-DD).

        Returns:
            (bool) True if a lease row exists.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM launch_leases
                WHERE file_key = ? AND local_date = ?
                """,
                (file_key, local_date),
            ).fetchone()
            return row is not None

    def record_launch_lease(self, file_key: str, local_date: str) -> bool:
        """Record a launch lease; return False if already held for that day.

        Args:
            file_key (str): Stable key for the file being launched.
            local_date (str): Local calendar date (YYYY-MM-DD).

        Returns:
            (bool) True if the lease was newly recorded; False if already held.
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO launch_leases (file_key, local_date, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (file_key, local_date, _utc_now_iso()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def release_launch_lease(self, file_key: str, local_date: str) -> None:
        """Delete a launch lease so the file can be claimed again for that day.

        Args:
            file_key (str): Stable key for the file.
            local_date (str): Local calendar date (YYYY-MM-DD).
        """
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM launch_leases
                WHERE file_key = ? AND local_date = ?
                """,
                (file_key, local_date),
            )

    def ack_summary(self, prep_run_id: int) -> None:
        """Mark a prep run summary as acknowledged.

        Args:
            prep_run_id (int): Prep run id to acknowledge.
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE prep_runs
                SET acked_at = ?
                WHERE id = ?
                """,
                (_utc_now_iso(), prep_run_id),
            )

    def latest_unacked_run(self) -> int | None:
        """Return the most recent prep run that has not been acknowledged.

        Returns:
            (int | None) Latest unacked prep_runs id, or None if none exist.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM prep_runs
                WHERE acked_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return int(row["id"]) if row is not None else None
