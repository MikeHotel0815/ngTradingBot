-- Add auto-trade persistence to global_settings table
-- This ensures auto-trade status survives server restarts

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS autotrade_enabled BOOLEAN DEFAULT TRUE NOT NULL;

ALTER TABLE global_settings
ADD COLUMN IF NOT EXISTS autotrade_min_confidence NUMERIC(5, 2) DEFAULT 60.0 NOT NULL;

-- Add comments
COMMENT ON COLUMN global_settings.autotrade_enabled IS 'Auto-trading enabled/disabled state (persists across server restarts)';
COMMENT ON COLUMN global_settings.autotrade_min_confidence IS 'Minimum signal confidence for auto-trading (0-100)';
