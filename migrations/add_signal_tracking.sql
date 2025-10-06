-- Add signal tracking and enhanced error information to trades table

-- Add signal_id to link trades back to the signal that generated them
ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_id INTEGER REFERENCES trading_signals(id);
CREATE INDEX IF NOT EXISTS idx_trades_signal_id ON trades(signal_id);

-- Add timeframe to track which timeframe the trade was based on
ALTER TABLE trades ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10);

-- Add close reason to better understand why trades close
ALTER TABLE trades ADD COLUMN IF NOT EXISTS close_reason VARCHAR(100);

-- Add comments
COMMENT ON COLUMN trades.signal_id IS 'Reference to the trading signal that generated this trade';
COMMENT ON COLUMN trades.timeframe IS 'Timeframe the signal was generated on (M5, M15, H1, H4, D1)';
COMMENT ON COLUMN trades.close_reason IS 'Reason for trade closure (TP_HIT, SL_HIT, MANUAL, TRAILING_STOP, etc)';
