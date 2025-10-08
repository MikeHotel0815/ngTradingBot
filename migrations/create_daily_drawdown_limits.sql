-- Migration: Create daily_drawdown_limits table
-- Date: 2025-10-08
-- Description: Creates table for daily drawdown protection to prevent excessive daily losses

CREATE TABLE IF NOT EXISTS daily_drawdown_limits (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL UNIQUE,
    max_daily_loss_percent NUMERIC(5, 2) DEFAULT 2.0,
    max_daily_loss_eur NUMERIC(10, 2),
    tracking_date DATE DEFAULT CURRENT_DATE,
    daily_pnl NUMERIC(10, 2) DEFAULT 0.0,
    limit_reached BOOLEAN DEFAULT FALSE,
    auto_trading_disabled_at DATE
);

COMMENT ON TABLE daily_drawdown_limits IS 'Daily drawdown protection tracking per account';
COMMENT ON COLUMN daily_drawdown_limits.max_daily_loss_percent IS 'Maximum daily loss as percentage of balance (default 2%)';
COMMENT ON COLUMN daily_drawdown_limits.max_daily_loss_eur IS 'Optional absolute daily loss limit in EUR';
