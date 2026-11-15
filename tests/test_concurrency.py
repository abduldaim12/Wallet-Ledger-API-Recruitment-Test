import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from database import connect_db, ensure_schema


@pytest.fixture
def pg_conn():
    if not os.getenv("DB_HOST"):
        pytest.skip("database integration tests require a PostgreSQL host")
    conn = connect_db()
    ensure_schema(conn)
    yield conn
    conn.close()


def test_concurrent_debits_keep_balance_non_negative(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("TRUNCATE ledger, user_balances RESTART IDENTITY CASCADE")
        cur.execute("INSERT INTO user_balances (user_id, balance) VALUES (%s, %s)", ("u_hot", 100))
    pg_conn.commit()

    def debit_once() -> int:
        conn = connect_db()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT balance FROM user_balances WHERE user_id = %s FOR UPDATE", ("u_hot",))
                    row = cur.fetchone()
                    if row is None:
                        return 404
                    balance = row[0]
                    if balance < 60:
                        return 409
                    cur.execute(
                        "INSERT INTO ledger (user_id, entry_type, amount, created_at) VALUES (%s, %s, %s, NOW())",
                        ("u_hot", "debit", 60),
                    )
                    cur.execute("UPDATE user_balances SET balance = balance - 60 WHERE user_id = %s", ("u_hot",))
                    return 200
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: debit_once(), range(2)))

    assert results.count(200) == 1
    assert results.count(409) == 1

    with pg_conn.cursor() as cur:
        cur.execute("SELECT balance FROM user_balances WHERE user_id = %s", ("u_hot",))
        assert cur.fetchone()[0] == 40


def test_concurrent_credits_sum_exactly(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("TRUNCATE ledger, user_balances RESTART IDENTITY CASCADE")
        cur.execute("INSERT INTO user_balances (user_id, balance) VALUES (%s, %s)", ("u_credits", 0))
    pg_conn.commit()

    def credit_once() -> None:
        conn = connect_db()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT balance FROM user_balances WHERE user_id = %s FOR UPDATE", ("u_credits",))
                    balance = cur.fetchone()[0]
                    new_balance = balance + 100
                    cur.execute(
                        "INSERT INTO ledger (user_id, entry_type, amount, created_at) VALUES (%s, %s, %s, NOW())",
                        ("u_credits", "credit", 100),
                    )
                    cur.execute("UPDATE user_balances SET balance = %s WHERE user_id = %s", (new_balance, "u_credits"))
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: credit_once(), range(1000)))

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ledger WHERE user_id = %s", ("u_credits",))
        assert cur.fetchone()[0] == 1000
        cur.execute("SELECT balance FROM user_balances WHERE user_id = %s", ("u_credits",))
        assert cur.fetchone()[0] == 100000
