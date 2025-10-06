-- Migration: Add unique constraint on active signals to prevent race conditions
-- Date: 2025-10-06
-- Purpose: Prevent duplicate signals for same symbol/timeframe/account

-- Drop the constraint if it already exists (for idempotency)
DROP INDEX IF EXISTS idx_unique_active_signal;

-- Create partial unique index - only ONE active signal per account/symbol/timeframe
CREATE UNIQUE INDEX idx_unique_active_signal
ON trading_signals (account_id, symbol, timeframe)
WHERE status = 'active';

-- Verify the constraint
SELECT
    indexname,
    indexdef
FROM
    pg_indexes
WHERE
    tablename = 'trading_signals'
    AND indexname = 'idx_unique_active_signal';
