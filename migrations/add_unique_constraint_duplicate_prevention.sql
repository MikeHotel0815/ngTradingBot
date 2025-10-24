-- Migration: Add UNIQUE constraint to prevent duplicate open positions
-- Date: 2025-10-24
-- Purpose: Fix Race Condition that allows duplicate positions for same symbol+timeframe

-- IMPORTANT: This will prevent opening multiple positions for the same symbol+account
-- while a position is already open (status='open')

-- Step 1: Check for existing duplicate open positions
SELECT
    account_id,
    symbol,
    COUNT(*) as open_count
FROM trades
WHERE status = 'open'
GROUP BY account_id, symbol
HAVING COUNT(*) > 1
ORDER BY open_count DESC;

-- If duplicates exist, you need to manually close extras before running this migration!

-- Step 2: Create partial UNIQUE index (only for open trades)
-- This allows multiple closed trades, but only ONE open trade per account+symbol

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_unique_open_trade_per_symbol
ON trades (account_id, symbol)
WHERE status = 'open';

-- Explanation:
-- - CONCURRENTLY: Creates index without locking table (safe for production)
-- - WHERE status='open': Only enforces uniqueness for open trades
-- - This prevents: Opening EURUSD BUY while EURUSD SELL is already open
-- - This allows: Multiple closed EURUSD trades in history

-- Verification:
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'trades'
  AND indexname = 'idx_unique_open_trade_per_symbol';

-- Expected result:
-- idx_unique_open_trade_per_symbol | CREATE UNIQUE INDEX idx_unique_open_trade_per_symbol ON public.trades USING btree (account_id, symbol) WHERE (status = 'open'::text)

-- Test (should fail with duplicate key error):
-- INSERT INTO trades (account_id, ticket, symbol, type, direction, volume, status)
-- VALUES (1, 99999998, 'EURUSD', 'market_buy', 'buy', 0.01, 'open');
--
-- INSERT INTO trades (account_id, ticket, symbol, type, direction, volume, status)
-- VALUES (1, 99999999, 'EURUSD', 'market_buy', 'buy', 0.01, 'open');
--
-- Expected: ERROR: duplicate key value violates unique constraint "idx_unique_open_trade_per_symbol"
