-- Migration: Add 'shadow_trade' status to symbol_trading_config
-- Date: 2025-10-26
-- Purpose: Enable shadow trading mode for symbols to monitor recovery without real trades

-- Extend status CHECK constraint to include 'shadow_trade'
ALTER TABLE symbol_trading_config
DROP CONSTRAINT IF EXISTS symbol_trading_config_status_check;

ALTER TABLE symbol_trading_config
ADD CONSTRAINT symbol_trading_config_status_check
CHECK (status IN ('active', 'reduced_risk', 'paused', 'disabled', 'shadow_trade'));

-- Migration summary
-- This allows symbols to be set to 'shadow_trade' status which:
-- 1. Generates signals normally
-- 2. Creates shadow trades (simulated trades)
-- 3. Does NOT execute real trades on MT5
-- 4. Tracks performance for potential re-activation
-- 5. Used for testing SL enforcement fixes before going live
