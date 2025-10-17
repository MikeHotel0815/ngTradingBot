-- ============================================================================
-- COMPREHENSIVE TRADE TRACKING MIGRATION
-- Created: 2025-10-17
-- Purpose: Add complete trade tracking fields for detailed analytics
-- ============================================================================

-- ============================================================================
-- PART 1: Extend TRADES table with comprehensive tracking fields
-- ============================================================================

BEGIN;

-- Initial TP/SL Snapshot (captured at trade opening)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS initial_tp NUMERIC(20, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS initial_sl NUMERIC(20, 5);

COMMENT ON COLUMN trades.initial_tp IS 'Original TP value when trade was opened (for TP extension tracking)';
COMMENT ON COLUMN trades.initial_sl IS 'Original SL value when trade was opened (for trailing stop detection)';

-- Price Action at Entry
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_bid NUMERIC(20, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_ask NUMERIC(20, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_spread NUMERIC(10, 5);

COMMENT ON COLUMN trades.entry_bid IS 'Bid price at trade entry';
COMMENT ON COLUMN trades.entry_ask IS 'Ask price at trade entry';
COMMENT ON COLUMN trades.entry_spread IS 'Spread at trade entry (in price units)';

-- Price Action at Exit
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_bid NUMERIC(20, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_ask NUMERIC(20, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_spread NUMERIC(10, 5);

COMMENT ON COLUMN trades.exit_bid IS 'Bid price at trade exit';
COMMENT ON COLUMN trades.exit_ask IS 'Ask price at trade exit';
COMMENT ON COLUMN trades.exit_spread IS 'Spread at trade exit (in price units)';

-- Trailing Stop Tracking
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trailing_stop_active BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS trailing_stop_moves INTEGER DEFAULT 0;

COMMENT ON COLUMN trades.trailing_stop_active IS 'Whether trailing stop was activated for this trade';
COMMENT ON COLUMN trades.trailing_stop_moves IS 'Number of times SL was moved by trailing stop';

-- Maximum Favorable/Adverse Excursion (MFE/MAE)
ALTER TABLE trades ADD COLUMN IF NOT EXISTS max_favorable_excursion NUMERIC(10, 2) DEFAULT 0;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS max_adverse_excursion NUMERIC(10, 2) DEFAULT 0;

COMMENT ON COLUMN trades.max_favorable_excursion IS 'Maximum profit reached during trade (in pips)';
COMMENT ON COLUMN trades.max_adverse_excursion IS 'Maximum drawdown during trade (in pips, negative value)';

-- Performance Metrics
ALTER TABLE trades ADD COLUMN IF NOT EXISTS pips_captured NUMERIC(10, 2);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS risk_reward_realized NUMERIC(10, 2);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS hold_duration_minutes INTEGER;

COMMENT ON COLUMN trades.pips_captured IS 'Profit/Loss in pips';
COMMENT ON COLUMN trades.risk_reward_realized IS 'Actual Risk:Reward ratio achieved (based on initial SL)';
COMMENT ON COLUMN trades.hold_duration_minutes IS 'Trade duration in minutes';

-- Market Context
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_volatility NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_volatility NUMERIC(10, 5);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS session VARCHAR(20);

COMMENT ON COLUMN trades.entry_volatility IS 'Market volatility at entry (ATR or spread-based)';
COMMENT ON COLUMN trades.exit_volatility IS 'Market volatility at exit (ATR or spread-based)';
COMMENT ON COLUMN trades.session IS 'Trading session when trade was opened (London/NY/Asia/Pacific)';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trades_trailing_stop ON trades(trailing_stop_active) WHERE trailing_stop_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session);
CREATE INDEX IF NOT EXISTS idx_trades_hold_duration ON trades(hold_duration_minutes);

COMMIT;


-- ============================================================================
-- PART 2: Create TRADE_HISTORY_EVENTS table for change tracking
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS trade_history_events (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    ticket BIGINT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Before/After Values
    old_value NUMERIC(20, 5),
    new_value NUMERIC(20, 5),
    
    -- Context
    reason VARCHAR(200),
    source VARCHAR(50),
    
    -- Market State at time of change
    price_at_change NUMERIC(20, 5),
    spread_at_change NUMERIC(10, 5),
    
    -- Additional metadata
    metadata JSONB
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_trade_history_trade_id ON trade_history_events(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_history_ticket ON trade_history_events(ticket);
CREATE INDEX IF NOT EXISTS idx_trade_history_event_type ON trade_history_events(event_type);
CREATE INDEX IF NOT EXISTS idx_trade_history_timestamp ON trade_history_events(timestamp DESC);

-- Composite index for common queries
CREATE INDEX IF NOT EXISTS idx_trade_history_ticket_timestamp ON trade_history_events(ticket, timestamp DESC);

COMMENT ON TABLE trade_history_events IS 'Tracks all modifications to trades (TP/SL changes, volume modifications, etc.)';
COMMENT ON COLUMN trade_history_events.event_type IS 'Event type: TP_MODIFIED, SL_MODIFIED, VOLUME_MODIFIED, PRICE_UPDATE';
COMMENT ON COLUMN trade_history_events.reason IS 'Human-readable reason for the change (e.g., "Trailing Stop activated")';
COMMENT ON COLUMN trade_history_events.source IS 'System component that made the change (e.g., "smart_trailing_stop", "manual")';

COMMIT;


-- ============================================================================
-- PART 3: Create helper view for trade analysis
-- ============================================================================

BEGIN;

CREATE OR REPLACE VIEW trade_analytics_view AS
SELECT 
    t.id,
    t.ticket,
    t.symbol,
    t.direction,
    t.volume,
    t.open_time,
    t.close_time,
    t.status,
    
    -- Entry/Exit Prices
    t.open_price,
    t.close_price,
    t.entry_bid,
    t.entry_ask,
    t.entry_spread,
    t.exit_bid,
    t.exit_ask,
    t.exit_spread,
    
    -- TP/SL Tracking
    t.initial_tp,
    t.initial_sl,
    t.tp,
    t.sl,
    t.original_tp,
    t.tp_extended_count,
    
    -- Trailing Stop
    t.trailing_stop_active,
    t.trailing_stop_moves,
    
    -- Performance
    t.profit,
    t.pips_captured,
    t.risk_reward_realized,
    t.max_favorable_excursion,
    t.max_adverse_excursion,
    t.hold_duration_minutes,
    
    -- Context
    t.close_reason,
    t.entry_reason,
    t.entry_confidence,
    t.session,
    t.entry_volatility,
    t.exit_volatility,
    
    -- Calculated Fields
    CASE 
        WHEN t.max_favorable_excursion > 0 AND t.pips_captured IS NOT NULL 
        THEN ROUND((t.pips_captured / t.max_favorable_excursion * 100), 2)
        ELSE NULL
    END as profit_capture_percent,
    
    CASE 
        WHEN t.max_favorable_excursion > 0 AND t.pips_captured IS NOT NULL
        THEN ROUND((t.max_favorable_excursion - t.pips_captured), 2)
        ELSE NULL
    END as opportunity_cost_pips,
    
    -- Count of history events
    (SELECT COUNT(*) FROM trade_history_events WHERE ticket = t.ticket) as modification_count

FROM trades t;

COMMENT ON VIEW trade_analytics_view IS 'Comprehensive view for trade analytics with calculated metrics';

COMMIT;


-- ============================================================================
-- PART 4: Data Migration - Initialize existing trades
-- ============================================================================

BEGIN;

-- For existing trades without initial values, copy current TP/SL to initial
UPDATE trades 
SET 
    initial_tp = tp,
    initial_sl = sl,
    trailing_stop_active = FALSE,
    trailing_stop_moves = 0,
    max_favorable_excursion = 0,
    max_adverse_excursion = 0
WHERE initial_tp IS NULL 
  AND initial_sl IS NULL;

-- Calculate hold_duration_minutes for closed trades
UPDATE trades
SET hold_duration_minutes = EXTRACT(EPOCH FROM (close_time - open_time)) / 60
WHERE status = 'closed'
  AND open_time IS NOT NULL
  AND close_time IS NOT NULL
  AND hold_duration_minutes IS NULL;

COMMIT;


-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify new columns exist
SELECT 
    column_name, 
    data_type, 
    column_default,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'trades' 
  AND column_name IN (
    'initial_tp', 'initial_sl', 
    'entry_bid', 'entry_ask', 'entry_spread',
    'exit_bid', 'exit_ask', 'exit_spread',
    'trailing_stop_active', 'trailing_stop_moves',
    'max_favorable_excursion', 'max_adverse_excursion',
    'pips_captured', 'risk_reward_realized', 'hold_duration_minutes',
    'entry_volatility', 'exit_volatility', 'session'
)
ORDER BY column_name;

-- Verify trade_history_events table
SELECT 
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'trade_history_events') as column_count
FROM information_schema.tables
WHERE table_name = 'trade_history_events';

-- Show sample of updated trades
SELECT 
    ticket,
    symbol,
    direction,
    initial_tp,
    initial_sl,
    trailing_stop_active,
    hold_duration_minutes,
    status
FROM trades
ORDER BY id DESC
LIMIT 5;

SELECT 'Migration completed successfully!' as status;
