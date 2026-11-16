**ENGINEERING RECRUITMENT** 



# **Wallet Ledger API: Recruitment Test** 

Take-home assessment brief 

## **Overview** 

Build an HTTP API, backed by a SQL database, that keeps a money ledger for many users and exposes three operations: <mark>`credit` ,</mark> <mark>`debit`</mark> and <mark>`get_balance` .</mark> 

The API will be called by many threads at once against a ledger of millions of rows. Submissions are scored on data consistency, correctness and response time, and on how well you explain your design in a review call. 

## **Setup and authentication** 

The whole system must start with <mark>`docker compose up` ,</mark> serve on <mark>`http://localhost:8080` ,</mark> and reject any request without the static bearer token. 

|**Setting**|**Required value**|
|---|---|
|Language / framework|Your choice|
|Database|Any client-server SQL database (PostgreSQL, MySQL, SQL Server, etc.). SQLite<br>is not accepted.|
|Start command|`docker compose up` starts the API and database, no other steps|
|Port|`8080`|
|Token variable|`API_TOKEN`|
|Token value in docker-|`recruitment-test-token` (reviewers may override it)|
|compose.yml||



Authentication rules: 

- Every endpoint requires the header <mark>`Authorization: Bearer <token>` .</mark> 

- 

- Missing header, wrong scheme or wrong token → <mark>`401 unauthorized` ,</mark> checked before any database access. 

- The token is never hard-coded in source, logged, or returned in responses. 

- 

- Compare tokens in constant time. 

- 

## **API** 

All requests and responses are JSON. Amounts and balances are integers in minor units (e.g. cents: <mark>`10000`</mark> = 100.00). 

Niobi · Engineering · Confidential 

Page 1 of 4 

Wallet Ledger API: Recruitment Test 

|**Endpoint**|**Request body**|**Success response**|**Behaviour**|
|---|---|---|---|
|`POST /credit`|`{"user_id": "u123",`|`200 {"user_id": "u123",`|Adds<br>`amount`.Creates the user|
||`"amount": 10000}`|`"balance": 25000}`|on first credit.|
|`POST /debit`|`{"user_id": "u123",`|`200 {"user_id": "u123",`|Subtracts<br>`amount`.Rejected if|
||`"amount": 4000}`|`"balance": 21000}`|the balance would go below 0.|
|`GET /balance/`|none|`200 {"user_id": "u123",`|Returns the current balance.|
|`{user_id}`||`"balance": 21000}`||



The balance returned by <mark>`credit`</mark> and <mark>`debit`</mark> is the balance immediately after that operation. 

### Input rules: 

- 

- <mark>`user_id` :</mark> string of 1 to 64 characters, only <mark>`A–Z` ,</mark> <mark>`a–z` ,</mark> <mark>`0–9` ,</mark> <mark>`_`</mark> and <mark>`-` .</mark> 

- <mark>`amount` :</mark> JSON integer, 1 ≤ amount ≤ 1,000,000,000. Decimals, floats, strings, 0 and negatives are 

- rejected. 

- Unknown fields are ignored. 

- 

Errors use the shape <mark>`{"error": "<code>", "message": "<text>"}` :</mark> 

|**Status**|**Code**|**When**|
|---|---|---|
|400|`invalid_request`|Malformed JSON, missing field, or a field breaking the input rules|
|401|`unauthorized`|Missing or wrong bearer token|
|404|`user_not_found`|`get_balance` or<br>`debit` for a user that has never been credited|
|409|`insufficient_funds`|Debit larger than the current balance; nothing is written|



## **Data and scale** 

The ledger table is the source of truth and must hold at least 10 million rows; every design choice should assume that volume. 

Ledger rules: 

- Every credit and debit is stored as one immutable ledger row. Rows are never updated or deleted. 

- 

- Each row records at least: an id, <mark>`user_id` ,</mark> <mark>`type`</mark> (credit or debit), <mark>`amount`</mark> (integer, always positive) and a server timestamp. 

- You may add any other tables, columns or indexes you need. 

- 

### Balance rules: 

- A user's balance must always equal the sum of that user's credits minus the sum of their debits in the ledger. Reviewers check this with SQL after the load test. 

- <mark>`get_balance`</mark> must stay fast at 10M+ rows. A request that scans the whole table, or a user's whole 

- history, will not meet this. 

### Seed data: 

- Ship a seed script that loads at least 10 million ledger rows across at least 100,000 users, with an uneven spread (some users with 100,000+ rows). 

- Seeded data must already satisfy every rule here: no user's balance below 0 at any point, and any extra tables consistent with the ledger. 

Niobi · Engineering · Confidential 

Page 2 of 4 

Wallet Ledger API: Recruitment Test 

- The seed must finish in a reasonable time on a laptop; state how long it took in the README. 

## **Concurrency and consistency** 

No mix of concurrent requests may ever produce a negative balance, a lost update, or a balance that disagrees with the ledger. 

1. **Non-negative balance:** two concurrent debits of 60 against a balance of 100 must give exactly one <mark>`200`</mark> and one <mark>`409` .</mark> 

2. **No lost updates:** 1,000 concurrent credits of 100 to one user must raise the balance by exactly 100,000. 

3. **Atomicity:** each credit or debit is written completely or not at all. A crash mid-request must leave the data consistent. 

4. **Read-your-writes:** once <mark>`credit`</mark> or <mark>`debit`</mark> returns <mark>`200` ,</mark> any later <mark>`get_balance`</mark> reflects it. 

5. **Isolation across users:** heavy traffic on one user must not slow or block requests for other users. 

6. **No silent failures:** deadlocks or conflicts must be handled (e.g. retried) and never surface as a <mark>`500`</mark> or a wrong balance. 

## **Performance** 

There are no fixed latency thresholds: submissions are compared with each other on p50 and p99 latency per endpoint, measured on the same reviewer machine. 

- Measured with the 10M+ row seed loaded and about 100 concurrent client threads. 

- 

- Traffic is a mix of credits, debits and balance reads across many users, plus a hot-user test (many threads on one user). 

- Latency should barely change as the table grows; compare your own timings at 1M and 10M rows. 

- 

- Requests other than expected <mark>`400`</mark> / <mark>`401`</mark> / <mark>`404`</mark> / <mark>`409`</mark> responses must not fail under load. 

- 

- Include the query plans ( <mark>`EXPLAIN` )</mark> for your <mark>`credit` ,</mark> <mark>`debit`</mark> and <mark>`get_balance`</mark> queries in the README. 

## **Use of AI tools** 

You may use LLMs and AI coding assistants, but you own every line you submit and must be able to defend it in the review call. 

Be ready to explain: 

- **Decisions made:** your schema, indexes, how the balance is computed, how concurrent writes are kept safe, and your transaction isolation level. 

- **Alternatives rejected:** the other options you considered for each of these, and why you did not choose them. 

- **Limits:** what breaks first at 10× the load, and what changes if the API ran as several instances. 

- 

Code you cannot explain earns no credit, whoever or whatever wrote it. 

## **Deliverables** 

Submit a Git repository link (public, or with reviewer access) within 5 days of receiving this test; we expect about 6 to 8 hours of work. 

- API source code 

Niobi · Engineering · Confidential 

Page 3 of 4 

Wallet Ledger API: Recruitment Test 

- <mark>`docker-compose.yml`</mark> that starts the API on port 8080 and the database with <mark>`docker compose up`</mark> 

- Schema / migrations, including all indexes 

- 

- Seed script (10M+ rows, 100k+ users) 

- 

- Automated tests, including concurrency tests for the rules above 

- 

- Load-test script and your results (p50/p99 per endpoint) 

- 

- README: how to run, design decisions, query plans, known limits, and what you would do with more time 

Optional extras earn no points but may break ties: an <mark>`Idempotency-Key`</mark> header on <mark>`credit`</mark> / <mark>`debit` ,</mark> a health endpoint, graceful shutdown. 

## **Evaluation** 

Submissions are scored out of 100. A negative balance, or any balance that disagrees with the ledger after our load test, fails the submission outright. 

|**Area**|**Points**|**What reviewers check**|
|---|---|---|
|Data consistency|30|Balances match the ledger; no lost updates; atomic writes; correct under races|
|Response time|25|p50/p99 per endpoint at 10M+ rows, compared across submissions; query plans;<br>hot-user isolation|
|Correctness|20|API contract, input validation, status codes, non-negative rule, auth on every<br>endpoint|
|Review call|15|Explaining decisions made and alternatives rejected|
|Code, tests and<br>docs|10|Readability, meaningful concurrency tests, clear README, one-command setup|



How we review: 

1. We run <mark>`docker compose up` ,</mark> load your seed, and run our own concurrent test suite against port 8080. 

2. We reconcile every user's balance against the ledger with SQL. 

3. Shortlisted candidates join a 45-minute review call to walk through the code and design (see Use of AI tools). 

Niobi · Engineering · Confidential 

Page 4 of 4 

