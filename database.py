import os
import sys
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import tuple_row


def get_db_dsn() -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "wallet")
    password = os.getenv("DB_PASSWORD", "walletpass")
    dbname = os.getenv("DB_NAME", "wallet")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def connect_db() -> psycopg.Connection:
    conn = psycopg.connect(get_db_dsn(), autocommit=False, row_factory=tuple_row)
    return conn


def create_connection_pool() -> ConnectionPool:
    return ConnectionPool(
        conninfo=get_db_dsn(),
        min_size=int(os.getenv("DB_POOL_MIN_SIZE", "5")),
        max_size=int(os.getenv("DB_POOL_MAX_SIZE", "40")),
        kwargs={"autocommit": False, "row_factory": tuple_row},
        open=False,
    )


def ensure_schema(conn: psycopg.Connection) -> None:
    migration_dir = Path(__file__).resolve().parent / "migrations"
    for migration in sorted(migration_dir.glob("*.sql")):
        sql = migration.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
    conn.commit()


def ensure_seed(conn: psycopg.Connection, target_rows: int, user_count: int) -> None:
    if target_rows <= 0:
        target_rows = 10_000_000
    if user_count <= 0:
        user_count = 100_000

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ledger")
        count = cur.fetchone()[0]

    if count >= target_rows:
        conn.commit()
        return

    seed_ledger(conn, user_count)


def seed_ledger(conn: psycopg.Connection, user_count: int) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE ledger, user_balances RESTART IDENTITY CASCADE")

    batch: list[tuple[str, str, int, Any]] = []
    hot_users = 100
    if user_count < hot_users:
        hot_users = user_count

    for user_index in range(user_count):
        user_id = f"u{user_index:06d}"
        rows_for_user = 100_000 if user_index < hot_users else 1
        for row_index in range(rows_for_user):
            amount = 1 + ((user_index + row_index) % 1000)
            batch.append((user_id, "credit", amount, __now()))
            if len(batch) >= 5_000:
                insert_seed_batch(conn, batch)
                batch.clear()

    if batch:
        insert_seed_batch(conn, batch)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_balances (user_id, balance)
            SELECT user_id, SUM(amount)::BIGINT AS total
            FROM ledger
            GROUP BY user_id
            ON CONFLICT (user_id) DO UPDATE SET balance = EXCLUDED.balance
            """
        )

    conn.commit()
    print(f"Seeded {user_count} users and ledger rows successfully")


def insert_seed_batch(conn: psycopg.Connection, rows: Iterable[tuple[str, str, int, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ledger (user_id, entry_type, amount, created_at) VALUES (%s, %s, %s, %s)",
            list(rows),
        )


def __now() -> Any:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc)
