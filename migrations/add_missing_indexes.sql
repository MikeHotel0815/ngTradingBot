-- Migration: Add missing database indexes for query performance
-- Date: 2025-10-06
-- Purpose: Optimize frequently queried columns

-- Index #1: SKIPPED - shadow_trades.performance_tracking_id column doesn't exist
-- NOTE: shadow_trading_engine.py references this column but it's missing from the schema
-- This is a schema mismatch that needs to be fixed separately
-- The queries in shadow_trading_engine.py (lines 68, 194, 278) will fail until column is added

-- Index #2: shadow_trades.exit_time for time-range queries
-- Used in: shadow_trading_engine.py calculate_daily_shadow_performance()
-- Queries filter by exit_time ranges for daily calculations
CREATE INDEX IF NOT EXISTS idx_shadow_trades_exit_time
ON shadow_trades (exit_time DESC)
WHERE exit_time IS NOT NULL;

-- Index #3: trades.account_id + status for open positions query
-- Used in: auto_trader.py check_correlation_exposure()
-- Queries count open positions frequently
CREATE INDEX IF NOT EXISTS idx_trades_account_status
ON trades (account_id, status)
WHERE status = 'open';

-- Index #4: symbol_performance_tracking composite for shadow queries
-- Used in: shadow_trading_engine.py process_signal_for_disabled_symbol()
-- Queries filter by account_id, symbol, status = 'disabled'
CREATE INDEX IF NOT EXISTS idx_symbol_perf_disabled
ON symbol_performance_tracking (account_id, symbol, evaluation_date DESC)
WHERE status = 'disabled';

-- Verify all indexes created
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE indexname IN (
    'idx_shadow_trades_exit_time',
    'idx_trades_account_status',
    'idx_symbol_perf_disabled'
)
ORDER BY tablename, indexname;
