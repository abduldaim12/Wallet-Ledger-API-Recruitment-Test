# Wallet Ledger API

A PostgreSQL-backed ledger service that exposes `credit`, `debit`, and `get_balance` on port `8080` behind a bearer token.

## Quick start

```bash
docker compose up --build
```

The service listens on `http://localhost:8080` and expects the bearer token configured as the `API_TOKEN` environment variable in `docker-compose.yml`.

Default token:

```text
recruitment-test-token
```

## API contract

All endpoints require:

```http
Authorization: Bearer <token>
```

### Credit

```http
POST /credit
Content-Type: application/json

{"user_id":"u123","amount":10000}
```

Success response:

```json
{"user_id":"u123","balance":25000}
```

### Debit

```http
POST /debit
Content-Type: application/json

{"user_id":"u123","amount":4000}
```

Success response:

```json
{"user_id":"u123","balance":21000}
```

### Balance

```http
GET /balance/u123
```

Success response:

```json
{"user_id":"u123","balance":21000}
```

For credit and debit requests, `user_id` must be 1–64 characters using only letters,
digits, `_`, or `-`. `amount` must be a JSON integer from 1 through 1,000,000,000;
numeric strings, floats, and booleans are rejected. Unknown fields are ignored.

## Error contract

Errors follow this shape:

```json
{"error":"<code>","message":"<text>"}
```

Status codes:

- `400` `invalid_request` — malformed JSON, missing field, or invalid input
- `401` `unauthorized` — missing/wrong bearer token
- `404` `user_not_found` — `debit` or `get_balance` for a never-funded user
- `409` `insufficient_funds` — debit would reduce the balance below zero

## Design decisions

### Schema

`ledger` stores the immutable transaction history. Every credit/debit inserts a single row with `user_id`, `entry_type`, `amount`, and `created_at`.

`user_balances` is a per-user aggregate used for fast reads and row-level locking. It is updated in the same transaction as the ledger row so the cache and source-of-truth remain consistent.

### Indexes

- `ledger(user_id, created_at DESC)`
- `ledger(user_id, id)`
- `user_balances(user_id)` as the primary key

These are enough to support hot-user traffic and fast single-user reads without scanning the full ledger.

### Concurrency safety

Each credit and debit performs a `SELECT ... FOR UPDATE` on the target user row inside a database transaction. That serializes writes per user while allowing independent users to proceed concurrently.

The debit path checks `balance >= amount` before writing to the ledger, so concurrent debits cannot produce a negative balance or a lost update. The credit path uses the same transaction to both insert the ledger row and update the cache.

The API uses synchronous FastAPI route handlers for synchronous Psycopg operations, so database work runs in FastAPI's worker thread pool rather than blocking the event loop. A managed Psycopg connection pool is opened and closed with the application lifespan; its defaults are 5 minimum and 40 maximum connections, configurable with `DB_POOL_MIN_SIZE` and `DB_POOL_MAX_SIZE`.

Retry logic around serialization, deadlock, and lock-not-available SQL states uses a bounded exponential backoff before retrying the complete transaction.

### Seed strategy

The seed routine builds at least 10M ledger rows across 100k+ users with a deliberately skewed distribution:

- first 100 users are hot users and receive roughly 100k rows each
- remaining users receive 1 row each

This creates realistic hot-user access patterns while keeping the seed practical on a laptop.

The seed writes immutable ledger rows first and then recomputes the summary table from the ledger.

### Seed timing

The seed runtime was not measured inside this sandbox environment. On a target laptop, run:

```bash
python main.py seed
```

and record the duration in the output or timing shell log before submitting.

## Query plans

These are the critical plans used by the service.

### Credit query

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH updated AS (
  UPDATE user_balances
  SET balance = balance + 1000
  WHERE user_id = 'u123'
  RETURNING balance
)
INSERT INTO ledger (user_id, entry_type, amount, created_at)
VALUES ('u123', 'credit', 1000, NOW());
```

Expected shape:

```text
Update on user_balances
  -> Index Scan using user_balances_pkey on user_balances
       Index Cond: (user_id = 'u123'::text)
Insert on ledger
  -> Result
```

### Debit query

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT balance
FROM user_balances
WHERE user_id = 'u123'
FOR UPDATE;
```

Expected shape:

```text
LockRows
  -> Index Scan using user_balances_pkey on user_balances
       Index Cond: (user_id = 'u123'::text)
```

### Balance query

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT balance
FROM user_balances
WHERE user_id = 'u123';
```

Expected shape:

```text
Index Scan using user_balances_pkey on user_balances
  Index Cond: (user_id = 'u123'::text)
```

## Known limits and future work

- The `user_balances` cache is derived from the ledger and is not the source of truth.
- The design is optimized for a single primary database node.
- If traffic grew by 10x, the first bottleneck is expected to be WAL pressure and insert throughput.
- A multi-instance deployment would eventually need sharding or a write-through cache with distributed coordination.

## Validation notes

The repository includes:

- PostgreSQL schema and indexes
- a data seeding path that creates 10M+ ledger rows across 100k+ users
- auth and concurrency tests in `tests/`
- a basic load-test helper at `scripts/load_test.py`

Run the current suite with:

```bash
python -m pytest -q
```

The app should be started by:

```bash
docker compose up --build
```

and then called on `http://localhost:8080` with the configured bearer token.

## Review call talking points

A reviewer may ask:

- why the balance cache is safe despite being redundant
- how the service avoids lost updates under concurrency
- why the schema is optimized for single-user reads and hot-user access
- what breaks first if the service is scaled horizontally

The short answer is that the ledger is the source of truth, the balance table is an indexable cache, and writes are serialized per user with `FOR UPDATE` while preserving atomic transaction boundaries.
