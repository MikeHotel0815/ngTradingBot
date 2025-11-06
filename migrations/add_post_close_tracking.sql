-- Migration: Add Post-Close TP Tracking Fields
-- Date: 2025-11-06
-- Purpose: Track if TP would have been hit AFTER Trailing Stop closed the trade
-- This enables ML learning about TS aggressiveness

-- Add post-close tracking fields to trades table
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_hit_after_close BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_hit_after_close_time TIMESTAMP;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_hit_after_close_minutes INTEGER;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS max_favorable_after_close NUMERIC(10, 2);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS max_adverse_after_close NUMERIC(10, 2);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS post_close_tracked_until TIMESTAMP;

-- Create index for efficient querying of TS trades that need post-close tracking
CREATE INDEX IF NOT EXISTS idx_trades_post_close_tracking
ON trades(close_reason, post_close_tracked_until)
WHERE close_reason IN ('TRAILING_STOP', 'PARTIAL_CLOSE')
  AND status = 'closed';

-- Add comment for documentation
COMMENT ON COLUMN trades.tp_hit_after_close IS
'Did price reach initial_tp within 4h after TS closed the trade?';

COMMENT ON COLUMN trades.tp_hit_after_close_time IS
'Timestamp when TP level was reached after close (NULL if never reached)';

COMMENT ON COLUMN trades.tp_hit_after_close_minutes IS
'Minutes from trade close to TP hit (for opportunity cost analysis)';

COMMENT ON COLUMN trades.max_favorable_after_close IS
'Maximum favorable price movement (pips) in 4h window after close';

COMMENT ON COLUMN trades.max_adverse_after_close IS
'Maximum adverse price movement (pips) in 4h window after close';

COMMENT ON COLUMN trades.post_close_tracked_until IS
'Timestamp until which post-close tracking was performed (typically close_time + 4h)';

-- Query to find TS trades that need post-close analysis
-- SELECT ticket, symbol, close_time, initial_tp, close_price,
--        post_close_tracked_until, tp_hit_after_close
-- FROM trades
-- WHERE close_reason = 'TRAILING_STOP'
--   AND status = 'closed'
--   AND initial_tp IS NOT NULL
--   AND (post_close_tracked_until IS NULL OR post_close_tracked_until < NOW());
