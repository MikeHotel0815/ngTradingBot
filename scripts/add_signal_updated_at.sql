-- Add updated_at column to trading_signals table
-- This enables tracking when signals are updated with new confidence values

ALTER TABLE trading_signals 
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Set updated_at = created_at for existing signals
UPDATE trading_signals 
SET updated_at = created_at 
WHERE updated_at IS NULL;

-- Create index for faster queries on updated_at
CREATE INDEX IF NOT EXISTS idx_signal_updated ON trading_signals(updated_at);

-- Add comment
COMMENT ON COLUMN trading_signals.updated_at IS 'Last time signal was updated (confidence, prices, etc.)';
