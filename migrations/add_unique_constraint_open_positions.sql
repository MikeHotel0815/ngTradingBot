-- Migration: Add unique constraint to prevent duplicate open positions per symbol+timeframe
-- This prevents race conditions from creating multiple trades for the same symbol+timeframe

-- Step 1: Add a partial unique index (only for open trades)
-- This allows multiple closed trades but only one open trade per account+symbol+timeframe+direction
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_unique_open_position
ON trades (account_id, symbol, timeframe, direction)
WHERE status = 'open';

-- Note: This index only applies to 'open' trades, so closed/cancelled trades are not affected
-- If a duplicate open position is attempted, PostgreSQL will raise an IntegrityError
