
# Wallet Ledger API

A PostgreSQL-backed wallet ledger service providing atomic credit, debit, and balance operations through a REST API.

The service uses PostgreSQL as its persistent database, FastAPI for HTTP endpoints, Psycopg for database access, and Docker Compose for deployment.

## 1. Quick Start

Start the application and database:

```bash
docker compose up --build
```

The API listens at:

```text
http://localhost:8080
```

Interactive API documentation:

```text
http://localhost:8080/docs
```

All API endpoints require a bearer token configured through `API_TOKEN`.

Default development token:

```text
recruitment-test-token
```

For production deployments, replace the default token with a securely generated secret.

## 2. API Contract

All endpoints require:

```http
Authorization: Bearer <token>
```

Amounts are integer minor units. No floating-point currency calculations are used.

### Credit

**Request**

```http
POST /credit
Content-Type: application/json
Authorization: Bearer recruitment-test-token
```

```json
{
  "user_id": "u123",
  "amount": 10000
}
```

**Success response — 200**

```json
{
  "user_id": "u123",
  "balance": 25000
}
```

Credit creates the user balance record if it does not already exist.

### Debit

**Request**

```http
POST /debit
Content-Type: application/json
Authorization: Bearer recruitment-test-token
```

```json
{
  "user_id": "u123",
  "amount": 4000
}
```

**Success response — 200**

```json
{
  "user_id": "u123",
  "balance": 21000
}
```

A debit is rejected if the user does not exist or if the requested amount exceeds the available balance.

### Get Balance

**Request**

```http
GET /balance/u123
Authorization: Bearer recruitment-test-token
```

**Success response — 200**

```json
{
  "user_id": "u123",
  "balance": 21000
}
```

### Input Validation

- `user_id` must contain between 1 and 64 characters.
- Allowed characters: letters, digits, underscore (`_`), and hyphen (`-`).
- `amount` must be a strict JSON integer.
- Minimum amount: `1`.
- Maximum amount: `1,000,000,000`.
- Numeric strings, floating-point values, and booleans are rejected.
- Unknown JSON fields are ignored.

## 3. Error Contract

All errors use the following JSON structure:

```json
{
  "error": "error_code",
  "message": "Description of the error"
}
```

| HTTP Status | Error Code | Description |
|---|---|---|
| 400 | `invalid_request` | Malformed JSON, missing fields, or invalid input |
| 401 | `unauthorized` | Missing or invalid bearer token |
| 404 | `user_not_found` | User does not exist |
| 409 | `insufficient_funds` | Debit would reduce balance below zero |

Authentication is checked before database operations.

Token comparison uses constant-time comparison to avoid ordinary timing-based token comparison leaks.

## 4. Database Design

The application uses PostgreSQL.

### Ledger Table

The `ledger` table stores the transaction history.

Each transaction records:

- `id`: Unique ledger entry identifier.
- `user_id`: Wallet owner.
- `entry_type`: `credit` or `debit`.
- `amount`: Positive integer amount.
- `created_at`: Transaction timestamp.

The ledger is the source of truth for wallet transactions.

### User Balances Table

The `user_balances` table maintains the current balance for each user.

It provides:

- Fast balance lookups.
- Per-user row locking.
- Efficient balance updates.
- A primary-key index on `user_id`.

The balance table is maintained transactionally alongside ledger entries.

### Indexes

The schema includes:

```sql
CREATE INDEX IF NOT EXISTS idx_ledger_user_created_at
ON ledger(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_user_id
ON ledger(user_id, id);
```

The `user_balances.user_id` column is the primary key.

These indexes support user-specific ledger queries and fast balance lookups.

## 5. Transaction and Concurrency Safety

Credit and debit operations execute inside PostgreSQL transactions.

### Credit Workflow

1. Create the balance record if it does not exist.
2. Lock the user's balance row using `SELECT ... FOR UPDATE`.
3. Calculate the new balance.
4. Insert the credit entry into the ledger.
5. Update the user's balance.
6. Commit both changes atomically.

### Debit Workflow

1. Lock the user's balance row using `SELECT ... FOR UPDATE`.
2. Verify that the user exists.
3. Check that sufficient funds are available.
4. Insert the debit entry into the ledger.
5. Update the user's balance.
6. Commit both changes atomically.

If a transaction fails, its ledger and balance changes are rolled back together.

### Concurrency Guarantees

Row-level locking serializes writes to the same user's wallet while allowing transactions for different users to proceed independently.

This prevents:

- Negative balances from concurrent debits.
- Lost balance updates.
- Ledger and balance inconsistencies caused by partial transactions.

The implementation also retries selected PostgreSQL concurrency errors, including serialization failures, deadlocks, and lock-not-available errors, using bounded exponential backoff.

### Connection Pooling

The API uses synchronous FastAPI route handlers for synchronous Psycopg operations. FastAPI executes these handlers in its worker thread pool.

A managed Psycopg connection pool is initialized and closed through the FastAPI application lifespan.

Default configuration:

| Setting | Default |
|---|---:|
| Minimum connections | 5 |
| Maximum connections | 40 |
| Autocommit | Disabled |

Pool sizes can be configured through:

```text
DB_POOL_MIN_SIZE
DB_POOL_MAX_SIZE
```

This allows database connections to be reused rather than establishing a new connection for every request.

## 6. Database Seeding

The seed process is designed to create at least 10 million ledger records across 100,000 or more users.

The distribution is deliberately uneven:

- The first 100 users receive approximately 100,000 records each.
- Remaining users receive one record each.

This creates hot-user workloads for concurrency and performance testing.

The seed process:

1. Generates ledger entries in batches.
2. Inserts the ledger records.
3. Recomputes the user balance table from the ledger.
4. Commits the seeded data.

The seed routine checks the existing ledger count before deciding whether additional seeding is required.

### Running the Seed Command

```bash
python main.py seed
```

**Seed timing:** The execution duration has not yet been measured and is intentionally not reported as a benchmark.

The seed routine should only be executed against an isolated test database when testing destructive reseeding behavior.

## 7. Query Plans

The following plans were captured using PostgreSQL `EXPLAIN` against the seeded database.

These are estimated execution plans, not `EXPLAIN ANALYZE` runtime measurements.

### Credit Operation

The credit API locks the user's balance, inserts a ledger entry, and updates the balance in one transaction.

**Ledger insert plan:**

```text
Insert on ledger (cost=0.00..0.01 rows=0 width=0)
  -> Result (cost=0.00..0.01 rows=1 width=88)
```

**Balance update plan:**

```text
Update on user_balances (cost=0.29..8.31 rows=0 width=0)
  -> Index Scan using user_balances_pkey on user_balances
       (cost=0.29..8.31 rows=1 width=14)
       Index Cond: (user_id = 'u000000'::text)
```

### Debit Operation

```text
LockRows (cost=0.29..8.32 rows=1 width=14)
  -> Index Scan using user_balances_pkey on user_balances
       (cost=0.29..8.31 rows=1 width=14)
       Index Cond: (user_id = 'u000000'::text)
```

The primary-key index locates the user's balance row before PostgreSQL acquires the row lock.

### Balance Operation

```text
Index Scan using user_balances_pkey on user_balances
  (cost=0.29..8.31 rows=1 width=8)
  Index Cond: (user_id = 'u000000'::text)
```

Balance reads use the primary-key index instead of scanning the full ledger.

## 8. Load Test Results

The following results were collected from the local Docker Compose environment using the seeded PostgreSQL database.

### Test Command

```bash
python scripts/load_test.py --concurrency 100 --requests 1000
```

### Test Configuration

| Parameter | Value |
|---|---:|
| Concurrent workers | 100 |
| Requests per endpoint | 1,000 |
| Endpoints tested | 3 |
| Total benchmark requests | 3,000 |
| Database | PostgreSQL |
| Ledger size | More than 10 million records |

### Measured Results

| Metric | Result |
|---|---:|
| Total duration | 67.896 seconds |
| Overall throughput | 44.19 requests/second |
| Credit p50 | 1,611.298 ms |
| Credit p99 | 10,071.670 ms |
| Debit p50 | 1,485.783 ms |
| Debit p99 | 9,868.125 ms |
| Balance p50 | 1,184.466 ms |
| Balance p99 | 9,443.756 ms |
| Failed requests | 0 |

### Final Balance Verification

The benchmark used a single hot user.

Initial funding was 1,000 units. The test executed 1,000 credits and 1,000 debits of one unit each.

| Verification | Result |
|---|---:|
| Expected final balance | 1,000 |
| Actual final balance | 1,000 |
| Balance matched | Yes |

All 3,000 benchmark requests returned HTTP 200.

### Performance Observations

The test deliberately sends concurrent writes to the same user, causing contention on that user's balance row.

The results demonstrate successful request handling and correct final balance under this workload.

However, tail latency is high. These measurements represent a single-hot-user stress test and should not be interpreted as general multi-user throughput.

Further performance evaluation should include distributed users, different concurrency levels, and separate 1M versus 10M database comparisons.

### Repeat Run (2026-11-16)

The threaded load-test client was used against `http://127.0.0.1:8080` with the same 100-worker, 1,000-requests-per-endpoint hot-user workload.

| Metric | Credit | Debit | Balance |
|---|---:|---:|---:|
| Requests | 1,000 | 1,000 | 1,000 |
| p50 | 806.369 ms | 571.120 ms | 481.505 ms |
| p99 | 4,213.180 ms | 3,609.089 ms | 1,076.296 ms |
| Successful responses | 1,000 | 1,000 | 1,000 |

Total duration was 24.819 seconds (120.88 requests/second overall). The final balance matched the expected 1,000 units. The database row count and ledger-to-balance SQL reconciliation could not be independently verified for this repeat run in the current environment, so these numbers should not be treated as a verified 10M-row comparison.

## 9. Automated Tests

The repository includes tests for:

- API input validation.
- Authentication.
- Invalid amount handling.
- API error response contracts.
- Concurrent debit safety.
- Concurrent credit correctness.

Run the test suite:

```bash
python -m pytest -q
```

PostgreSQL integration tests require a configured PostgreSQL test database.

**Important:** The concurrency integration tests truncate their test tables. Always configure them to use an isolated test database, never the seeded application database.

Example Windows CMD configuration:

```cmd
set DB_HOST=localhost
set DB_PORT=5432
set DB_USER=wallet
set DB_PASSWORD=walletpass
set DB_NAME=wallet_test
python -m pytest -q
```

## 10. Known Limitations and Future Improvements

- The balance table is a derived aggregate; the ledger remains the source of truth.
- Seed execution time has not yet been measured.
- The recorded load test focuses on one hot user and does not represent a distributed-user workload.
- High p99 latency under hot-user contention requires further investigation.
- The current architecture targets a single primary PostgreSQL database.
- Larger deployments may require database tuning, workload distribution, and horizontal scaling strategies.
- Database-level enforcement of ledger immutability should be independently verified before claiming protection against direct database modifications.

## 11. Docker Services

Docker Compose runs:

- PostgreSQL database service.
- FastAPI application service.

Start services:

```bash
docker compose up -d --build
```

Check service status:

```bash
docker compose ps
```

View application logs:

```bash
docker compose logs -f api
```

Open API documentation:

```text
http://localhost:8080/docs
```

## 12. Review Call Talking Points

### Why maintain a separate balance table?

The ledger provides the transaction history, while the balance table enables fast balance lookups without aggregating millions of ledger rows for every request.

### How are concurrent debits handled?

The application locks the user's balance row with `SELECT ... FOR UPDATE`, checks available funds, and commits the ledger entry and balance update in one transaction.

### How are lost updates prevented?

Concurrent transactions for the same user are serialized by PostgreSQL row-level locking.

### How does the application handle database concurrency errors?

Selected retryable PostgreSQL errors are retried with bounded exponential backoff.

### What is the main performance limitation?

A heavily accessed single wallet creates row-lock contention. The recorded benchmark shows high p99 latency under this workload.

### What would be needed for horizontal scaling?

A larger deployment would require careful database capacity planning, connection-pool tuning, and potentially partitioning or sharding strategies while preserving per-user transaction consistency.

---

## Summary

The Wallet Ledger API provides PostgreSQL-backed credit, debit, and balance endpoints with bearer authentication, strict input validation, transactional ledger writes, row-level concurrency control, connection pooling, and a large-data seeding strategy.

The implementation has been tested with automated tests and a 100-concurrent-worker hot-user load test. The benchmark confirms correct final balance and successful requests, while also identifying tail latency as an area for further optimization.
