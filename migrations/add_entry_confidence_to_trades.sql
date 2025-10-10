-- Add entry_confidence column to trades table
-- This tracks the signal confidence at entry for opportunity cost comparison

ALTER TABLE trades
ADD COLUMN IF NOT EXISTS entry_confidence NUMERIC(5, 2);

-- Create index for faster queries on confidence
CREATE INDEX IF NOT EXISTS idx_trades_entry_confidence ON trades(entry_confidence);

-- Add comment
COMMENT ON COLUMN trades.entry_confidence IS 'Signal confidence percentage at trade entry (0.00-100.00)';
