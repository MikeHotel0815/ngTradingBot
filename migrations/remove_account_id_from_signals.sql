-- Migration: Remove account_id from trading_signals (GLOBAL model)
-- Date: 2025-10-25
-- Reason: TradingSignal is GLOBAL (shared across accounts), not account-specific
-- Related: COMPREHENSIVE_BOT_AUDIT_2025.md, BTCUSD_NO_SIGNALS_ANALYSIS.md

-- Step 1: Drop the NOT NULL constraint first (in case we want to rollback)
ALTER TABLE trading_signals ALTER COLUMN account_id DROP NOT NULL;

-- Step 2: Drop the column entirely
ALTER TABLE trading_signals DROP COLUMN account_id;

-- Verification query (run after migration)
-- \d trading_signals
-- Should show NO account_id column
