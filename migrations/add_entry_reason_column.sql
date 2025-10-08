-- Migration: Add entry_reason column to trades table
-- Date: 2025-10-08
-- Description: Adds entry_reason field to store why a trade was opened

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS entry_reason VARCHAR(200);

COMMENT ON COLUMN trades.entry_reason IS 'Why trade was opened: pattern, indicator confluence, etc';
