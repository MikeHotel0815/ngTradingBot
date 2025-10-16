-- Migration: Add Symbol-Specific Dynamic Trading Configuration
-- Created: 2025-10-14
-- Purpose: Enable per-symbol dynamic risk management and performance-based auto-adjustments

-- ========================================
-- 1. Create symbol_trading_config table
-- ========================================

CREATE TABLE IF NOT EXISTS symbol_trading_config (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10),  -- NULL = both directions, 'BUY' for longs, 'SELL' for shorts

    -- Dynamic Confidence Thresholds
    -- System learns: increase threshold for losing symbols, decrease for winners
    min_confidence_threshold NUMERIC(5,2) DEFAULT 50.0 NOT NULL,  -- 50% = neutral start
    confidence_adjustment_factor NUMERIC(5,2) DEFAULT 1.0 NOT NULL,  -- Performance multiplier

    -- Dynamic Risk Management
    -- System learns: reduce risk for losers, increase for winners
    risk_multiplier NUMERIC(5,2) DEFAULT 1.0 NOT NULL CHECK (risk_multiplier >= 0.1 AND risk_multiplier <= 3.0),
    position_size_multiplier NUMERIC(5,2) DEFAULT 1.0 NOT NULL CHECK (position_size_multiplier >= 0.1 AND position_size_multiplier <= 3.0),
    sl_multiplier NUMERIC(5,2) DEFAULT 1.0 NOT NULL CHECK (sl_multiplier >= 0.5 AND sl_multiplier <= 2.0),
    tp_multiplier NUMERIC(5,2) DEFAULT 1.0 NOT NULL CHECK (tp_multiplier >= 0.5 AND tp_multiplier <= 2.0),

    -- Status & Auto-Pause
    status VARCHAR(20) DEFAULT 'active' NOT NULL CHECK (status IN ('active', 'reduced_risk', 'paused', 'disabled')),
    auto_pause_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    pause_after_consecutive_losses INTEGER DEFAULT 3 NOT NULL,  -- Auto-pause after N losses
    resume_after_cooldown_hours INTEGER DEFAULT 24 NOT NULL,  -- Resume after N hours
    paused_at TIMESTAMP,
    pause_reason TEXT,

    -- Consecutive Performance Tracking
    consecutive_losses INTEGER DEFAULT 0 NOT NULL,
    consecutive_wins INTEGER DEFAULT 0 NOT NULL,
    last_trade_result VARCHAR(10),  -- 'WIN', 'LOSS', 'BREAKEVEN'

    -- Rolling Performance Window (Last 20 Trades)
    rolling_window_size INTEGER DEFAULT 20 NOT NULL,
    rolling_trades_count INTEGER DEFAULT 0 NOT NULL,
    rolling_wins INTEGER DEFAULT 0 NOT NULL,
    rolling_losses INTEGER DEFAULT 0 NOT NULL,
    rolling_breakeven INTEGER DEFAULT 0 NOT NULL,
    rolling_profit NUMERIC(15,2) DEFAULT 0.0,
    rolling_winrate NUMERIC(5,2),  -- Calculated: (rolling_wins / rolling_trades_count) * 100
    rolling_avg_profit NUMERIC(15,2),
    rolling_profit_factor NUMERIC(10,4),

    -- Market Regime Preference Learning
    -- System learns which regime works best for this symbol+direction
    preferred_regime VARCHAR(20),  -- 'TRENDING', 'RANGING', 'ANY'
    regime_performance_trending NUMERIC(5,2),  -- Win rate in trending markets
    regime_performance_ranging NUMERIC(5,2),  -- Win rate in ranging markets
    regime_trades_trending INTEGER DEFAULT 0,
    regime_trades_ranging INTEGER DEFAULT 0,
    regime_wins_trending INTEGER DEFAULT 0,
    regime_wins_ranging INTEGER DEFAULT 0,

    -- Session Performance (Daily Reset)
    session_trades_today INTEGER DEFAULT 0,
    session_profit_today NUMERIC(15,2) DEFAULT 0.0,
    session_date DATE,

    -- Performance History Snapshot (for trend analysis)
    performance_history JSONB,  -- Array of daily performance snapshots

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    last_trade_at TIMESTAMP,
    last_updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    last_adjustment_at TIMESTAMP,
    updated_by VARCHAR(50) DEFAULT 'system',

    -- Ensure one config per account+symbol+direction
    CONSTRAINT unique_symbol_direction UNIQUE (account_id, symbol, direction)
);

-- ========================================
-- 2. Create indexes for fast lookups
-- ========================================

CREATE INDEX idx_symbol_config_account_symbol ON symbol_trading_config(account_id, symbol);
CREATE INDEX idx_symbol_config_status ON symbol_trading_config(status);
CREATE INDEX idx_symbol_config_active ON symbol_trading_config(account_id, symbol, direction) WHERE status = 'active';
CREATE INDEX idx_symbol_config_paused ON symbol_trading_config(account_id, symbol) WHERE status = 'paused';
CREATE INDEX idx_symbol_config_performance ON symbol_trading_config(rolling_winrate DESC, rolling_profit DESC);

-- ========================================
-- 3. Create trigger for automatic updated_at
-- ========================================

CREATE OR REPLACE FUNCTION update_symbol_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_symbol_config_timestamp
    BEFORE UPDATE ON symbol_trading_config
    FOR EACH ROW
    EXECUTE FUNCTION update_symbol_config_timestamp();

-- ========================================
-- 4. Initialize default configs for existing symbols
-- ========================================

-- Get all unique symbols from trades and create default configs
INSERT INTO symbol_trading_config (account_id, symbol, direction)
SELECT DISTINCT
    account_id,
    symbol,
    NULL  -- NULL = applies to both BUY and SELL
FROM trades
WHERE account_id = 1  -- Adjust if you have multiple accounts
ON CONFLICT (account_id, symbol, direction) DO NOTHING;

-- ========================================
-- 5. Create views for easy querying
-- ========================================

-- View: Top performing symbol+direction combinations
CREATE OR REPLACE VIEW v_top_symbol_configs AS
SELECT
    stc.symbol,
    stc.direction,
    stc.status,
    stc.rolling_winrate,
    stc.rolling_profit,
    stc.rolling_trades_count,
    stc.consecutive_wins,
    stc.consecutive_losses,
    stc.min_confidence_threshold,
    stc.risk_multiplier,
    stc.preferred_regime,
    stc.last_trade_at
FROM symbol_trading_config stc
WHERE stc.account_id = 1
ORDER BY stc.rolling_winrate DESC, stc.rolling_profit DESC;

-- View: Paused symbols that may be ready for resume
CREATE OR REPLACE VIEW v_paused_symbols_resume_candidates AS
SELECT
    symbol,
    direction,
    paused_at,
    pause_reason,
    resume_after_cooldown_hours,
    EXTRACT(EPOCH FROM (NOW() - paused_at))/3600 AS hours_paused,
    CASE
        WHEN EXTRACT(EPOCH FROM (NOW() - paused_at))/3600 >= resume_after_cooldown_hours
        THEN TRUE
        ELSE FALSE
    END AS ready_for_resume
FROM symbol_trading_config
WHERE status = 'paused'
    AND account_id = 1
ORDER BY paused_at DESC;

-- View: Real-time performance dashboard per symbol
CREATE OR REPLACE VIEW v_symbol_performance_dashboard AS
SELECT
    stc.symbol,
    stc.direction,
    stc.status,
    stc.min_confidence_threshold AS confidence_req,
    stc.risk_multiplier,
    stc.rolling_winrate AS winrate_20,
    stc.rolling_profit AS profit_20,
    stc.rolling_trades_count AS trades_20,
    stc.consecutive_wins AS streak_wins,
    stc.consecutive_losses AS streak_losses,
    stc.preferred_regime,
    ROUND(stc.regime_performance_trending, 1) AS wr_trending,
    ROUND(stc.regime_performance_ranging, 1) AS wr_ranging,
    stc.session_trades_today AS trades_today,
    stc.session_profit_today AS profit_today,
    stc.last_trade_at
FROM symbol_trading_config stc
WHERE stc.account_id = 1
ORDER BY stc.rolling_profit DESC;

-- ========================================
-- 6. Add comments for documentation
-- ========================================

COMMENT ON TABLE symbol_trading_config IS
'Per-symbol dynamic trading configuration that auto-adjusts based on performance.
Each symbol+direction learns independently and adapts confidence thresholds, risk levels,
and market regime preferences.';

COMMENT ON COLUMN symbol_trading_config.min_confidence_threshold IS
'Minimum signal confidence required for this symbol+direction. Auto-adjusts: increases after losses, decreases after wins.';

COMMENT ON COLUMN symbol_trading_config.risk_multiplier IS
'Dynamic risk multiplier applied to global risk_per_trade. 1.0 = normal, 0.5 = half risk, 2.0 = double risk. Auto-adjusts based on rolling performance.';

COMMENT ON COLUMN symbol_trading_config.status IS
'active: Normal trading | reduced_risk: Risk multiplier reduced | paused: Auto-paused after consecutive losses | disabled: Manually disabled';

COMMENT ON COLUMN symbol_trading_config.rolling_winrate IS
'Win rate calculated from last 20 trades (rolling window). Used for auto-adjustments.';

COMMENT ON COLUMN symbol_trading_config.preferred_regime IS
'Market regime where this symbol+direction performs best. Learned from historical performance. ANY = performs well in both.';

-- ========================================
-- Migration complete
-- ========================================

-- Verify table creation
SELECT 'Migration completed successfully' AS status,
       COUNT(*) AS default_configs_created
FROM symbol_trading_config
WHERE account_id = 1;
