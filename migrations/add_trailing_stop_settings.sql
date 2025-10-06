-- Add trailing stop settings to global_settings table
-- Migration: add_trailing_stop_settings
-- Date: 2025-10-06

-- Add trailing stop enabled flag
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS trailing_stop_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- Stage 1: Break-even settings
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS breakeven_enabled BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS breakeven_trigger_percent NUMERIC(5, 2) NOT NULL DEFAULT 30.0;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS breakeven_offset_points NUMERIC(6, 2) NOT NULL DEFAULT 5.0;

-- Stage 2: Partial trailing settings
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS partial_trailing_trigger_percent NUMERIC(5, 2) NOT NULL DEFAULT 50.0;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS partial_trailing_distance_percent NUMERIC(5, 2) NOT NULL DEFAULT 40.0;

-- Stage 3: Aggressive trailing settings
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS aggressive_trailing_trigger_percent NUMERIC(5, 2) NOT NULL DEFAULT 75.0;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS aggressive_trailing_distance_percent NUMERIC(5, 2) NOT NULL DEFAULT 25.0;

-- Stage 4: Near TP protection settings
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS near_tp_trigger_percent NUMERIC(5, 2) NOT NULL DEFAULT 90.0;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS near_tp_trailing_distance_percent NUMERIC(5, 2) NOT NULL DEFAULT 15.0;

-- Safety settings
ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS min_sl_distance_points NUMERIC(6, 2) NOT NULL DEFAULT 10.0;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS max_sl_move_per_update NUMERIC(6, 2) NOT NULL DEFAULT 100.0;

-- Add comments for documentation
COMMENT ON COLUMN global_settings.trailing_stop_enabled IS 'Enable/disable smart trailing stop system';
COMMENT ON COLUMN global_settings.breakeven_enabled IS 'Enable break-even move (Stage 1)';
COMMENT ON COLUMN global_settings.breakeven_trigger_percent IS 'Trigger break-even when profit reaches X% of TP distance';
COMMENT ON COLUMN global_settings.breakeven_offset_points IS 'Offset above/below entry for break-even SL';
COMMENT ON COLUMN global_settings.partial_trailing_trigger_percent IS 'Start partial trailing at X% of TP distance (Stage 2)';
COMMENT ON COLUMN global_settings.partial_trailing_distance_percent IS 'Trail X% behind current price (Stage 2)';
COMMENT ON COLUMN global_settings.aggressive_trailing_trigger_percent IS 'Start aggressive trailing at X% of TP distance (Stage 3)';
COMMENT ON COLUMN global_settings.aggressive_trailing_distance_percent IS 'Trail X% behind current price (Stage 3)';
COMMENT ON COLUMN global_settings.near_tp_trigger_percent IS 'Start near-TP protection at X% of TP distance (Stage 4)';
COMMENT ON COLUMN global_settings.near_tp_trailing_distance_percent IS 'Trail X% behind current price (Stage 4)';
COMMENT ON COLUMN global_settings.min_sl_distance_points IS 'Minimum distance SL must be from current price (safety)';
COMMENT ON COLUMN global_settings.max_sl_move_per_update IS 'Maximum points SL can move in single update (safety)';

-- Create index for faster settings lookup (if not exists)
CREATE INDEX IF NOT EXISTS idx_global_settings_trailing
ON global_settings(trailing_stop_enabled)
WHERE trailing_stop_enabled = TRUE;
