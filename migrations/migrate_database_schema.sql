-- ============================================================================
-- DATABASE CONSOLIDATION MIGRATION
-- ============================================================================
-- Goals:
-- 1. Make ticks/ohlc/patterns GLOBAL (remove account_id)
-- 2. Delete Account #1 (MT5: 729712, internal ID: 1)
-- 3. Keep Account #3 (MT5: 730630, internal ID: 3) as THE account
-- 4. Use MT5 account number (730630) as direct ID
-- ============================================================================

BEGIN;

-- ============================================================================
-- PHASE 1: DELETE ACCOUNT #1 DATA
-- ============================================================================

\echo '>>> PHASE 1: Deleting Account #1 data...'

-- Delete Account #1 specific data (keep global data for now)
-- Must delete in correct order (respecting FK constraints):
-- 1. First delete things that reference backtest_runs
DELETE FROM backtest_trades WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE account_id = 1);
DELETE FROM symbol_performance_tracking WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE account_id = 1);
DELETE FROM symbol_performance_tracking WHERE account_id = 1;  -- Also delete by account_id
-- 2. Delete auto_optimization_events (references both backtest_runs AND account)
DELETE FROM auto_optimization_events WHERE backtest_run_id IN (SELECT id FROM backtest_runs WHERE account_id = 1);
DELETE FROM auto_optimization_events WHERE account_id = 1;
-- 3. Now we can delete backtest_runs
DELETE FROM backtest_runs WHERE account_id = 1;
-- 4. Delete all other account-specific data
DELETE FROM trades WHERE account_id = 1;
DELETE FROM shadow_trades WHERE account_id = 1;
DELETE FROM commands WHERE account_id = 1;
DELETE FROM logs WHERE account_id = 1;
DELETE FROM auto_trade_config WHERE account_id = 1;
DELETE FROM auto_optimization_config WHERE account_id = 1;
DELETE FROM daily_backtest_schedule WHERE account_id = 1;
DELETE FROM subscribed_symbols WHERE account_id = 1;
DELETE FROM symbol_trading_config WHERE account_id = 1;
DELETE FROM trade_analytics WHERE account_id = 1;

\echo '>>> Account #1 specific data deleted'

-- ============================================================================
-- PHASE 2: MAKE GLOBAL TABLES TRULY GLOBAL (Remove account_id)
-- ============================================================================

\echo '>>> PHASE 2: Making global tables global...'

-- ============================================================================
-- TICKS: Remove account_id, keep only unique ticks
-- ============================================================================

\echo '>>> Processing TICKS table...'

-- Drop foreign key constraint
ALTER TABLE ticks DROP CONSTRAINT IF EXISTS ticks_account_id_fkey;

-- Remove duplicate ticks (keep the most recent one based on id)
DELETE FROM ticks a USING ticks b
WHERE a.id < b.id
  AND a.symbol = b.symbol
  AND ABS(EXTRACT(EPOCH FROM (a.timestamp - b.timestamp))) < 1;  -- Within 1 second = duplicate

\echo '>>> Duplicates removed from ticks'

-- Drop account_id column
ALTER TABLE ticks DROP COLUMN IF EXISTS account_id;

-- Add unique constraint
CREATE UNIQUE INDEX IF NOT EXISTS ticks_symbol_timestamp_unique
ON ticks(symbol, timestamp);

\echo '>>> TICKS table is now global'

-- ============================================================================
-- OHLC_DATA: Remove account_id
-- ============================================================================

\echo '>>> Processing OHLC_DATA table...'

ALTER TABLE ohlc_data DROP CONSTRAINT IF EXISTS ohlc_data_account_id_fkey;

-- Remove duplicates
DELETE FROM ohlc_data a USING ohlc_data b
WHERE a.id < b.id
  AND a.symbol = b.symbol
  AND a.timeframe = b.timeframe
  AND a.timestamp = b.timestamp;

ALTER TABLE ohlc_data DROP COLUMN IF EXISTS account_id;

CREATE UNIQUE INDEX IF NOT EXISTS ohlc_symbol_timeframe_timestamp_unique
ON ohlc_data(symbol, timeframe, timestamp);

\echo '>>> OHLC_DATA table is now global'

-- ============================================================================
-- PATTERN_DETECTIONS: Remove account_id
-- ============================================================================

\echo '>>> Processing PATTERN_DETECTIONS table...'

ALTER TABLE pattern_detections DROP CONSTRAINT IF EXISTS pattern_detections_account_id_fkey;

-- Remove duplicates
DELETE FROM pattern_detections a USING pattern_detections b
WHERE a.id < b.id
  AND a.symbol = b.symbol
  AND a.timeframe = b.timeframe
  AND a.pattern_type = b.pattern_type
  AND a.detected_at = b.detected_at;

ALTER TABLE pattern_detections DROP COLUMN IF EXISTS account_id;

\echo '>>> PATTERN_DETECTIONS table is now global'

-- ============================================================================
-- TRADING_SIGNALS: Remove account_id
-- ============================================================================

\echo '>>> Processing TRADING_SIGNALS table...'

ALTER TABLE trading_signals DROP CONSTRAINT IF EXISTS trading_signals_account_id_fkey;

-- Remove duplicates
DELETE FROM trading_signals a USING trading_signals b
WHERE a.id < b.id
  AND a.symbol = b.symbol
  AND a.timeframe = b.timeframe
  AND a.signal_type = b.signal_type
  AND a.created_at = b.created_at;

ALTER TABLE trading_signals DROP COLUMN IF EXISTS account_id;

\echo '>>> TRADING_SIGNALS table is now global'

-- ============================================================================
-- INDICATOR_SCORES: Remove account_id
-- ============================================================================

\echo '>>> Processing INDICATOR_SCORES table...'

ALTER TABLE indicator_scores DROP CONSTRAINT IF EXISTS indicator_scores_account_id_fkey;

-- Simply drop column - duplicates don't matter for now
-- (These tables will be repopulated by the system anyway)

ALTER TABLE indicator_scores DROP COLUMN IF EXISTS account_id;

\echo '>>> INDICATOR_SCORES table is now global'

-- ============================================================================
-- INDICATOR_VALUES: Remove account_id
-- ============================================================================

\echo '>>> Processing INDICATOR_VALUES table...'

ALTER TABLE indicator_values DROP CONSTRAINT IF EXISTS indicator_values_account_id_fkey;

-- Simply drop column - will be recalculated

ALTER TABLE indicator_values DROP COLUMN IF EXISTS account_id;

\echo '>>> INDICATOR_VALUES table is now global'

-- ============================================================================
-- BROKER_SYMBOLS: Remove account_id
-- ============================================================================

\echo '>>> Processing BROKER_SYMBOLS table...'

ALTER TABLE broker_symbols DROP CONSTRAINT IF EXISTS broker_symbols_account_id_fkey;

-- Remove duplicates first (keep newer one based on id)
DELETE FROM broker_symbols a USING broker_symbols b
WHERE a.id < b.id AND a.symbol = b.symbol;

-- Just drop column - will be refreshed from MT5
ALTER TABLE broker_symbols DROP COLUMN IF EXISTS account_id;

-- Add unique constraint on symbol
CREATE UNIQUE INDEX IF NOT EXISTS broker_symbols_symbol_unique
ON broker_symbols(symbol);

\echo '>>> BROKER_SYMBOLS table is now global'

-- ============================================================================
-- PHASE 3: DELETE ACCOUNT #1 FROM ACCOUNTS TABLE
-- ============================================================================

\echo '>>> PHASE 3: Deleting Account #1 from accounts table...'

DELETE FROM accounts WHERE id = 1;  -- Account #1 (MT5: 729712)

\echo '>>> Account #1 deleted'

-- ============================================================================
-- PHASE 4: SKIP FOR NOW - ID Migration too complex with FKs
-- ============================================================================

\echo '>>> PHASE 4: Skipping ID migration (keeping internal ID=3, MT5=730630)'
\echo '>>> This can be done later if needed'

-- ============================================================================
-- VERIFICATION
-- ============================================================================

\echo '>>> VERIFICATION:'

SELECT 'Accounts' as table_name, COUNT(*) as count FROM accounts
UNION ALL
SELECT 'Ticks', COUNT(*) FROM ticks
UNION ALL
SELECT 'OHLC Data', COUNT(*) FROM ohlc_data
UNION ALL
SELECT 'Patterns', COUNT(*) FROM pattern_detections
UNION ALL
SELECT 'Signals', COUNT(*) FROM trading_signals
UNION ALL
SELECT 'Trades', COUNT(*) FROM trades;

\echo '>>> Checking account details:'
SELECT id, mt5_account_number, broker, balance FROM accounts;

\echo ''
\echo '============================================================================'
\echo 'MIGRATION COMPLETED SUCCESSFULLY!'
\echo '============================================================================'
\echo ''
\echo 'Changes made:'
\echo '  ✅ Account #1 (MT5: 729712) - DELETED'
\echo '  ✅ Ticks - Now GLOBAL (account_id removed)'
\echo '  ✅ OHLC Data - Now GLOBAL (account_id removed)'
\echo '  ✅ Patterns - Now GLOBAL (account_id removed)'
\echo '  ✅ Signals - Now GLOBAL (account_id removed)'
\echo '  ✅ Indicators - Now GLOBAL (account_id removed)'
\echo '  ✅ Broker Symbols - Now GLOBAL (account_id removed)'
\echo '  ℹ️  Account remains as ID=3, MT5=730630 (ID migration skipped)'
\echo ''

COMMIT;
