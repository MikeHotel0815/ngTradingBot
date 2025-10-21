-- Migration: Add continuous signal validation columns
-- Date: 2025-10-21
-- Purpose: Enable continuous validation of signals based on indicator state instead of age

-- Add indicator_snapshot column to store signal creation conditions
ALTER TABLE trading_signals
ADD COLUMN IF NOT EXISTS indicator_snapshot JSONB;

-- Add last_validated timestamp to track when signal was last checked
ALTER TABLE trading_signals
ADD COLUMN IF NOT EXISTS last_validated TIMESTAMP;

-- Add is_valid flag to quickly filter valid signals
ALTER TABLE trading_signals
ADD COLUMN IF NOT EXISTS is_valid BOOLEAN DEFAULT true;

-- Add index for fast filtering of valid signals
CREATE INDEX IF NOT EXISTS idx_trading_signals_is_valid
ON trading_signals(is_valid) WHERE is_valid = true;

-- Add index for validation worker to find signals needing revalidation
CREATE INDEX IF NOT EXISTS idx_trading_signals_last_validated
ON trading_signals(last_validated) WHERE is_valid = true;

-- Add comments
COMMENT ON COLUMN trading_signals.indicator_snapshot IS 'JSONB snapshot of all indicator values at signal creation time. Used to validate if signal conditions still hold.';
COMMENT ON COLUMN trading_signals.last_validated IS 'Timestamp of last validation check by signal_validator worker.';
COMMENT ON COLUMN trading_signals.is_valid IS 'False if ANY signal creation condition no longer holds. Signals are deleted when invalid.';

-- Log migration
DO $$
BEGIN
    RAISE NOTICE 'Migration completed: Added continuous signal validation columns';
    RAISE NOTICE 'indicator_snapshot: Stores signal creation conditions (indicators, patterns, price levels)';
    RAISE NOTICE 'last_validated: Tracks validation freshness';
    RAISE NOTICE 'is_valid: Fast filtering flag - invalid signals are deleted immediately';
    RAISE NOTICE 'Age-based rejection will be removed - signals stay valid as long as conditions hold';
END $$;
