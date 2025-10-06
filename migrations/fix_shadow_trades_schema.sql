-- Migration: Fix shadow_trades schema mismatch
-- Date: 2025-10-06
-- Purpose: Add missing performance_tracking_id column that code references

-- Add the missing column
ALTER TABLE shadow_trades
ADD COLUMN performance_tracking_id INTEGER;

-- Add foreign key constraint
ALTER TABLE shadow_trades
ADD CONSTRAINT shadow_trades_performance_tracking_fkey
FOREIGN KEY (performance_tracking_id)
REFERENCES symbol_performance_tracking(id)
ON DELETE SET NULL;

-- Add index for query performance
CREATE INDEX idx_shadow_trades_perf_tracking
ON shadow_trades(performance_tracking_id)
WHERE performance_tracking_id IS NOT NULL;

-- Verify the column was added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'shadow_trades' AND column_name = 'performance_tracking_id';

-- Verify the index was created
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'shadow_trades' AND indexname = 'idx_shadow_trades_perf_tracking';
