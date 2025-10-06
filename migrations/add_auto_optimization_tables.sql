-- Migration: Add Auto-Optimization Tables
-- Created: 2025-10-06
-- Description: Tables for adaptive trading system with automatic symbol optimization

-- 1. Symbol Performance Tracking
-- Tracks daily performance metrics per symbol for auto-enable/disable decisions
CREATE TABLE IF NOT EXISTS symbol_performance_tracking (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    evaluation_date DATE NOT NULL,

    -- Symbol Status
    status VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active', 'watch', 'disabled'
    previous_status VARCHAR(20), -- Track status changes
    status_changed_at TIMESTAMP,
    auto_disabled_reason TEXT,

    -- 14-Day Rolling Backtest Results
    backtest_run_id INTEGER REFERENCES backtest_runs(id),
    backtest_start_date TIMESTAMP,
    backtest_end_date TIMESTAMP,
    backtest_total_trades INTEGER DEFAULT 0,
    backtest_winning_trades INTEGER DEFAULT 0,
    backtest_losing_trades INTEGER DEFAULT 0,
    backtest_win_rate NUMERIC(5,2), -- e.g., 66.7%
    backtest_profit NUMERIC(15,2), -- Total profit/loss
    backtest_profit_percent NUMERIC(10,4), -- ROI %
    backtest_max_drawdown NUMERIC(15,2),
    backtest_max_drawdown_percent NUMERIC(10,4),
    backtest_profit_factor NUMERIC(10,4), -- Gross Profit / Gross Loss
    backtest_sharpe_ratio NUMERIC(10,4),
    backtest_avg_trade_duration INTEGER, -- Minutes
    backtest_best_trade NUMERIC(15,2),
    backtest_worst_trade NUMERIC(15,2),

    -- Live Trading Results (same day)
    live_trades INTEGER DEFAULT 0,
    live_winning_trades INTEGER DEFAULT 0,
    live_losing_trades INTEGER DEFAULT 0,
    live_profit NUMERIC(15,2),
    live_win_rate NUMERIC(5,2),

    -- Shadow Trading Results (for disabled symbols)
    shadow_trades INTEGER DEFAULT 0,
    shadow_winning_trades INTEGER DEFAULT 0,
    shadow_losing_trades INTEGER DEFAULT 0,
    shadow_profit NUMERIC(15,2),
    shadow_win_rate NUMERIC(5,2),
    shadow_profitable_days INTEGER DEFAULT 0, -- Consecutive profitable days in shadow

    -- Auto-Decision Metrics
    consecutive_loss_days INTEGER DEFAULT 0,
    consecutive_profit_days INTEGER DEFAULT 0,
    meets_enable_criteria BOOLEAN DEFAULT FALSE,
    meets_disable_criteria BOOLEAN DEFAULT FALSE,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_symbol_date UNIQUE (account_id, symbol, evaluation_date)
);

CREATE INDEX idx_symbol_perf_account_symbol ON symbol_performance_tracking(account_id, symbol);
CREATE INDEX idx_symbol_perf_status ON symbol_performance_tracking(status);
CREATE INDEX idx_symbol_perf_date ON symbol_performance_tracking(evaluation_date DESC);


-- 2. Auto-Optimization Configuration
-- Stores configurable thresholds and rules for auto-optimization
CREATE TABLE IF NOT EXISTS auto_optimization_config (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,

    -- Feature Flags
    enabled BOOLEAN DEFAULT TRUE,
    auto_disable_enabled BOOLEAN DEFAULT TRUE,
    auto_enable_enabled BOOLEAN DEFAULT TRUE,
    shadow_trading_enabled BOOLEAN DEFAULT TRUE,

    -- Backtest Configuration
    backtest_window_days INTEGER DEFAULT 14, -- 14-day rolling window
    backtest_schedule_time TIME DEFAULT '00:00:00', -- Daily at midnight UTC
    backtest_min_confidence NUMERIC(5,4) DEFAULT 0.60, -- 60%

    -- Auto-Disable Thresholds
    disable_consecutive_loss_days INTEGER DEFAULT 3,
    disable_min_win_rate NUMERIC(5,2) DEFAULT 35.0, -- 35%
    disable_max_loss_percent NUMERIC(10,4) DEFAULT -0.10, -- -10%
    disable_max_drawdown_percent NUMERIC(10,4) DEFAULT 0.15, -- 15%
    disable_min_trades INTEGER DEFAULT 5, -- Need at least 5 trades to evaluate

    -- Auto-Enable Thresholds (Shadow Trading)
    enable_consecutive_profit_days INTEGER DEFAULT 5,
    enable_min_win_rate NUMERIC(5,2) DEFAULT 55.0, -- 55%
    enable_min_profit_percent NUMERIC(10,4) DEFAULT 0.05, -- +5%
    enable_min_shadow_trades INTEGER DEFAULT 10,

    -- Watch Status Thresholds (borderline performance)
    watch_min_win_rate NUMERIC(5,2) DEFAULT 40.0, -- 40%
    watch_max_win_rate NUMERIC(5,2) DEFAULT 50.0, -- 50%
    watch_min_profit_percent NUMERIC(10,4) DEFAULT -0.02, -- -2%
    watch_max_profit_percent NUMERIC(10,4) DEFAULT 0.02, -- +2%

    -- Email Notifications
    email_enabled BOOLEAN DEFAULT TRUE,
    email_daily_report BOOLEAN DEFAULT TRUE,
    email_on_status_change BOOLEAN DEFAULT TRUE,
    email_recipient VARCHAR(255),

    -- Kill Switch
    max_daily_loss_percent NUMERIC(10,4) DEFAULT 0.05, -- 5% daily loss = pause system
    max_consecutive_losses INTEGER DEFAULT 5,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_account_config UNIQUE (account_id)
);


-- 3. Auto-Optimization Events Log
-- Audit trail of all auto-optimization decisions and actions
CREATE TABLE IF NOT EXISTS auto_optimization_events (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(20),
    event_type VARCHAR(50) NOT NULL, -- 'symbol_disabled', 'symbol_enabled', 'status_changed', 'backtest_completed', 'kill_switch_triggered'
    event_timestamp TIMESTAMP DEFAULT NOW(),

    -- Event Details
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    trigger_reason TEXT,

    -- Metrics at time of event
    metrics JSONB, -- Store all relevant metrics as JSON

    -- Related Objects
    backtest_run_id INTEGER REFERENCES backtest_runs(id),
    symbol_performance_id INTEGER REFERENCES symbol_performance_tracking(id),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_auto_opt_events_account ON auto_optimization_events(account_id);
CREATE INDEX idx_auto_opt_events_symbol ON auto_optimization_events(symbol);
CREATE INDEX idx_auto_opt_events_type ON auto_optimization_events(event_type);
CREATE INDEX idx_auto_opt_events_timestamp ON auto_optimization_events(event_timestamp DESC);


-- 4. Shadow Trades
-- Tracks "what if" trades for disabled symbols
CREATE TABLE IF NOT EXISTS shadow_trades (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    signal_id INTEGER REFERENCES trading_signals(id),

    -- Trade Details (mirroring backtest_trades)
    timeframe VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL, -- BUY, SELL
    volume NUMERIC(10,2) NOT NULL,

    -- Entry
    entry_time TIMESTAMP NOT NULL,
    entry_price NUMERIC(20,5) NOT NULL,
    sl NUMERIC(20,5),
    tp NUMERIC(20,5),

    -- Exit (simulated)
    exit_time TIMESTAMP,
    exit_price NUMERIC(20,5),
    exit_reason VARCHAR(50), -- 'SL_HIT', 'TP_HIT', 'MANUAL', 'TIMEOUT'

    -- Performance
    profit NUMERIC(15,2),
    profit_percent NUMERIC(10,4),
    duration_minutes INTEGER,

    -- Signal Info
    signal_confidence NUMERIC(5,2),
    entry_reason VARCHAR(500),

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),

    -- Note: Shadow trades are simulated, not real
    is_simulated BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_shadow_trades_account_symbol ON shadow_trades(account_id, symbol);
CREATE INDEX idx_shadow_trades_entry_time ON shadow_trades(entry_time DESC);
CREATE INDEX idx_shadow_trades_symbol_status ON shadow_trades(symbol) WHERE exit_time IS NULL;


-- 5. Daily Backtest Schedule
-- Tracks scheduled and completed daily backtests
CREATE TABLE IF NOT EXISTS daily_backtest_schedule (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,

    scheduled_date DATE NOT NULL,
    scheduled_time TIME DEFAULT '00:00:00',

    -- Execution Status
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'running', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Results
    backtest_runs_created INTEGER DEFAULT 0, -- Number of backtest runs created (one per symbol)
    total_symbols_evaluated INTEGER DEFAULT 0,
    symbols_enabled INTEGER DEFAULT 0,
    symbols_disabled INTEGER DEFAULT 0,
    symbols_watch INTEGER DEFAULT 0,

    -- Errors
    error_message TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_account_schedule_date UNIQUE (account_id, scheduled_date)
);

CREATE INDEX idx_daily_backtest_schedule_account ON daily_backtest_schedule(account_id);
CREATE INDEX idx_daily_backtest_schedule_date ON daily_backtest_schedule(scheduled_date DESC);
CREATE INDEX idx_daily_backtest_schedule_status ON daily_backtest_schedule(status);


-- 6. Add column to existing SubscribedSymbol for auto-optimization status
-- (Only if column doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'subscribed_symbols'
        AND column_name = 'auto_optimization_status'
    ) THEN
        ALTER TABLE subscribed_symbols
        ADD COLUMN auto_optimization_status VARCHAR(20) DEFAULT 'active',
        ADD COLUMN auto_disabled_at TIMESTAMP,
        ADD COLUMN auto_disabled_reason TEXT,
        ADD COLUMN shadow_trading_enabled BOOLEAN DEFAULT FALSE;
    END IF;
END $$;


-- Insert default configuration for existing accounts
INSERT INTO auto_optimization_config (account_id)
SELECT id FROM accounts
ON CONFLICT (account_id) DO NOTHING;


-- Comments for documentation
COMMENT ON TABLE symbol_performance_tracking IS 'Daily performance tracking per symbol for auto-enable/disable decisions';
COMMENT ON TABLE auto_optimization_config IS 'Configuration and thresholds for auto-optimization system';
COMMENT ON TABLE auto_optimization_events IS 'Audit trail of all auto-optimization decisions and actions';
COMMENT ON TABLE shadow_trades IS 'Simulated trades for disabled symbols to monitor recovery';
COMMENT ON TABLE daily_backtest_schedule IS 'Schedule and tracking of daily automated backtests';

COMMENT ON COLUMN symbol_performance_tracking.status IS 'active = live trading, watch = borderline performance, disabled = shadow trading only';
COMMENT ON COLUMN symbol_performance_tracking.backtest_profit_factor IS 'Gross Profit / Gross Loss (>1.0 = profitable)';
COMMENT ON COLUMN auto_optimization_config.disable_consecutive_loss_days IS 'Auto-disable after N consecutive days of losses';
COMMENT ON COLUMN auto_optimization_config.enable_consecutive_profit_days IS 'Auto-enable after N consecutive days of shadow profits';
