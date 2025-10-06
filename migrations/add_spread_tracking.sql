-- Migration: Add spread tracking to ticks and trades
-- Created: 2025-10-06
-- Purpose: Track bid/ask spread for realistic P&L calculation

-- Add spread column to ticks table
ALTER TABLE ticks ADD COLUMN IF NOT EXISTS spread NUMERIC(10, 5);

-- Add spread tracking to backtest_trades
ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS entry_spread NUMERIC(10, 5);
ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS exit_spread NUMERIC(10, 5);
ALTER TABLE backtest_trades ADD COLUMN IF NOT EXISTS spread_cost NUMERIC(15, 2) DEFAULT 0;

-- Add spread tracking to shadow_trades
ALTER TABLE shadow_trades ADD COLUMN IF NOT EXISTS entry_spread NUMERIC(10, 5);
ALTER TABLE shadow_trades ADD COLUMN IF NOT EXISTS exit_spread NUMERIC(10, 5);
ALTER TABLE shadow_trades ADD COLUMN IF NOT EXISTS spread_cost NUMERIC(15, 2) DEFAULT 0;

-- Add spread tracking to trades (live trading)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_spread NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_spread NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS spread_cost NUMERIC(15, 2) DEFAULT 0;

-- Create spread statistics table for analysis
CREATE TABLE IF NOT EXISTS spread_statistics (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    hour_utc INTEGER NOT NULL CHECK (hour_utc >= 0 AND hour_utc < 24),
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week < 7), -- 0=Monday, 6=Sunday

    -- Spread metrics
    avg_spread NUMERIC(10, 5),
    min_spread NUMERIC(10, 5),
    max_spread NUMERIC(10, 5),
    median_spread NUMERIC(10, 5),

    -- Sample size
    sample_count INTEGER DEFAULT 0,

    -- Timestamps
    first_recorded TIMESTAMP,
    last_updated TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_spread_stat UNIQUE (symbol, hour_utc, day_of_week)
);

CREATE INDEX IF NOT EXISTS idx_spread_stats_symbol ON spread_statistics(symbol);
CREATE INDEX IF NOT EXISTS idx_spread_stats_hour ON spread_statistics(hour_utc);
CREATE INDEX IF NOT EXISTS idx_ticks_spread ON ticks(symbol, timestamp, spread);

COMMENT ON TABLE spread_statistics IS 'Aggregated spread statistics per symbol, hour, and day of week';
COMMENT ON COLUMN spread_statistics.hour_utc IS 'Hour of day in UTC (0-23)';
COMMENT ON COLUMN spread_statistics.day_of_week IS 'Day of week: 0=Monday, 6=Sunday';
