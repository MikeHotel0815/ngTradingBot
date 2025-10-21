-- Symbol-specific spread configuration table
-- Allows per-symbol customization of spread limits

CREATE TABLE IF NOT EXISTS symbol_spread_config (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL UNIQUE,

    -- Spread limits
    typical_spread DECIMAL(10, 5) NOT NULL,           -- Normal expected spread
    max_spread_multiplier DECIMAL(5, 2) DEFAULT 3.0,  -- Max allowed = typical * multiplier
    absolute_max_spread DECIMAL(10, 5),                -- Hard limit regardless of multiplier

    -- Session-specific spreads (optional)
    asian_session_spread DECIMAL(10, 5),               -- Wider spreads during Asian hours
    weekend_spread DECIMAL(10, 5),                     -- For crypto/indices that trade 24/7

    -- Configuration
    enabled BOOLEAN DEFAULT true,                      -- Enable/disable spread checking for this symbol
    use_dynamic_limits BOOLEAN DEFAULT true,           -- Use multiplier vs absolute limit

    -- Metadata
    asset_type VARCHAR(20),                            -- FOREX, COMMODITY, INDEX, CRYPTO
    notes TEXT,                                        -- User notes/comments
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast lookups
CREATE INDEX idx_symbol_spread_symbol ON symbol_spread_config(symbol);
CREATE INDEX idx_symbol_spread_enabled ON symbol_spread_config(enabled);

-- Insert default values for common symbols
INSERT INTO symbol_spread_config (symbol, typical_spread, max_spread_multiplier, absolute_max_spread, asset_type, notes) VALUES
    -- Forex Major Pairs
    ('EURUSD', 0.00020, 2.5, 0.00050, 'FOREX', 'Most liquid pair - tight spreads expected'),
    ('GBPUSD', 0.00030, 2.5, 0.00070, 'FOREX', 'Cable - moderate spreads'),
    ('USDJPY', 0.00200, 2.5, 0.00500, 'FOREX', 'JPY pairs use different pip calculation'),
    ('USDCHF', 0.00030, 2.5, 0.00070, 'FOREX', 'Swissy - moderate liquidity'),

    -- Forex Minor Pairs
    ('EURGBP', 0.00050, 3.0, 0.00150, 'FOREX', 'Cross pair - wider spreads'),
    ('EURJPY', 0.00500, 3.0, 0.01500, 'FOREX', 'JPY cross - wider spreads'),
    ('GBPJPY', 0.01000, 3.5, 0.03000, 'FOREX', 'Volatile cross - wide spreads'),
    ('AUDUSD', 0.00030, 2.5, 0.00080, 'FOREX', 'Aussie - commodity currency'),

    -- Precious Metals
    ('XAUUSD', 0.30000, 2.5, 0.80000, 'COMMODITY', 'Gold - spreads vary by session'),
    ('XAGUSD', 0.05000, 4.0, 0.20000, 'COMMODITY', 'Silver - very volatile, wide spread swings'),

    -- Indices
    ('US30.c', 2.00000, 3.0, 8.00000, 'INDEX', 'Dow Jones - point-based spread'),
    ('US500.c', 0.50000, 3.0, 2.00000, 'INDEX', 'S&P 500 - tight spreads'),
    ('NAS100.c', 1.50000, 3.0, 5.00000, 'INDEX', 'Nasdaq - tech volatility'),
    ('DE40.c', 1.00000, 3.0, 4.00000, 'INDEX', 'DAX - European index'),

    -- Crypto
    ('BTCUSD', 10.00000, 5.0, 100.00000, 'CRYPTO', 'Bitcoin - highly volatile spreads'),
    ('ETHUSD', 2.00000, 5.0, 20.00000, 'CRYPTO', 'Ethereum - volatile'),
    ('XRPUSD', 0.00050, 5.0, 0.00500, 'CRYPTO', 'Ripple - smaller absolute values')
ON CONFLICT (symbol) DO NOTHING;

-- Update trigger for updated_at
CREATE OR REPLACE FUNCTION update_symbol_spread_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER symbol_spread_config_updated_at
    BEFORE UPDATE ON symbol_spread_config
    FOR EACH ROW
    EXECUTE FUNCTION update_symbol_spread_config_updated_at();

COMMENT ON TABLE symbol_spread_config IS 'Per-symbol spread limits configuration for auto-trading spread validation';
COMMENT ON COLUMN symbol_spread_config.typical_spread IS 'Expected normal spread for this symbol';
COMMENT ON COLUMN symbol_spread_config.max_spread_multiplier IS 'Maximum allowed spread as multiple of typical (e.g., 3.0 = 3x typical)';
COMMENT ON COLUMN symbol_spread_config.absolute_max_spread IS 'Hard limit - reject if spread exceeds this regardless of multiplier';
