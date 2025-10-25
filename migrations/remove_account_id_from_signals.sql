-- Migration: Remove account_id from GLOBAL models
-- Date: 2025-10-25
-- Reason: TradingSignal and PatternDetection are GLOBAL (shared across accounts), not account-specific
-- Related: COMPREHENSIVE_BOT_AUDIT_2025.md, BTCUSD_NO_SIGNALS_ANALYSIS.md

-- Remove account_id from trading_signals (GLOBAL model)
ALTER TABLE trading_signals DROP COLUMN account_id CASCADE;

-- Remove account_id from pattern_detections (GLOBAL model)
ALTER TABLE pattern_detections DROP COLUMN account_id CASCADE;

-- Verification queries (run after migration)
-- \d trading_signals
-- \d pattern_detections
-- Should show NO account_id column in either table
