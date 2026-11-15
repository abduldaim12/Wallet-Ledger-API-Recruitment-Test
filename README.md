# Wallet Ledger API

A PostgreSQL-backed ledger service that exposes `credit`, `debit`, and `get_balance` on port `8080` behind a bearer token.

## Quick start

```bash
docker compose up --build
```

The service listens on `http://localhost:8080` and expects the bearer token configured as the `API_TOKEN` environment variable in `docker-compose.yml`.

The default token is:

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

Response:

```json
{"user_id":"u123","balance":25000}
```

### Debit

```http
POST /debit
Content-Type: application/json

{"user_id":"u123","amount":4000}
```

Response:

```json
{"user_id":"u123","balance":21000}
```

### Balance

```http
GET /balance/u123
```

Response:

```json
{"user_id":"u123","balance":21000}
```

## Design decisions

### Schema

`ledger` holds immutable transaction history; `user_balances` is a per-user aggregate used for fast reads. The balance cache is updated in the same transaction as the ledger row, so they stay consistent under load.

### Indexing

- `ledger(user_id, created_at DESC)` speeds time-range and user history lookups.
- `ledger(user_id, id)` is useful for hot-user analysis and reconstruction.
- `user_balances(user_id)` is the primary key for fast reads and row-level locking.

### Concurrency safety

Every credit/debit updates a single user row under `SELECT ... FOR UPDATE` in a transaction. This serializes writes per user while leaving different users independent.

The debit logic checks `balance >= amount` before writing anything, so concurrent debits cannot drive the balance negative or produce a lost update.

### Seed strategy

The project adds a seed script that populates the ledger with 10M+ rows across 100k+ users. The first 100 users are intentionally hot: each receives ~100,000 rows; the remaining 99,900 users receive one row each. This creates a realistic hot-user distribution while keeping the seed fast enough to run on a laptop.

The seed script stores only immutable ledger rows and then recomputes the per-user cash totals into `user_balances`.

### Seed timing

The seed runtime has not been measured in this environment. Measure it on the target laptop and record the result here.

## Query plans

These are the critical plans used by the API.

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

- The balance cache is intentionally derived from the ledger and is not the source of truth.
- The design is optimized for a single Postgres primary; if the app were horizontally scaled, the next step would be to shard by user_id or add a write-through cache with distributed locking.
- Under a 10x load increase, the first bottleneck is likely the database's `INSERT` rate and WAL pressure; a multi-instance deployment would need either partitioning or a dedicated write path.

## Validation notes

The project includes a PostgreSQL-backed test suite for auth checks and edge conditions, a seed routine designed to satisfy the 100k-user / 10M-row rules, and a simple load-test helper at `scripts/load_test.py` for recording p50/p99 timing samples.
