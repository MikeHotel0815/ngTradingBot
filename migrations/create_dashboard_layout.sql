-- Dashboard Layout Preferences Table
-- Stores user preferences for dashboard panel ordering

CREATE TABLE IF NOT EXISTS dashboard_layout (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    panel_order JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_layout_account ON dashboard_layout(account_id);

-- Default panel order (for reference)
-- [
--   "open-positions",
--   "trading-signals",
--   "symbol-performance",
--   "pnl-performance",
--   "spread-config",
--   "trading-stats",
--   "ai-decision-log",
--   "ml-models",
--   "trade-history",
--   "live-prices",
--   "backtesting",
--   "global-settings"
-- ]

COMMENT ON TABLE dashboard_layout IS 'Stores user dashboard layout preferences';
COMMENT ON COLUMN dashboard_layout.panel_order IS 'Ordered array of panel IDs';
