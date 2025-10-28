-- Migration: Remove account_id from indicator_scores table
-- Date: 2025-10-28
-- Reason: Indicator scores should be GLOBAL, not per-account
--         Technical indicator performance is universal across all accounts

BEGIN;

-- Drop existing indexes that include account_id
DROP INDEX IF EXISTS idx_indicator_scores_lookup;
DROP INDEX IF EXISTS idx_indicator_scores_symbol;

-- Remove NOT NULL constraint first (if needed)
ALTER TABLE indicator_scores ALTER COLUMN account_id DROP NOT NULL;

-- Drop the foreign key constraint
ALTER TABLE indicator_scores DROP CONSTRAINT IF EXISTS indicator_scores_account_id_fkey;

-- Drop the account_id column
ALTER TABLE indicator_scores DROP COLUMN IF EXISTS account_id;

-- Recreate indexes WITHOUT account_id
CREATE UNIQUE INDEX idx_indicator_scores_lookup ON indicator_scores(symbol, timeframe, indicator_name);
CREATE INDEX idx_indicator_scores_symbol ON indicator_scores(symbol, indicator_name);

COMMIT;
