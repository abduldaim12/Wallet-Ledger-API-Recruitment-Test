CREATE TABLE IF NOT EXISTS ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('credit', 'debit')),
    amount BIGINT NOT NULL CHECK (amount > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_balances (
    user_id TEXT PRIMARY KEY,
    balance BIGINT NOT NULL CHECK (balance >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ledger_user_created_at
    ON ledger (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_user_id
    ON ledger (user_id, id);
