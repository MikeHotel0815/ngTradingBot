-- Add ML confidence and AB test columns to trading_signals table
-- This allows us to track and compare ML-enhanced vs rules-based signals

BEGIN;

-- Add ml_confidence column (raw ML model output 0-100%)
ALTER TABLE trading_signals
ADD COLUMN IF NOT EXISTS ml_confidence NUMERIC(5,2);

COMMENT ON COLUMN trading_signals.ml_confidence IS
'Raw ML model confidence score (0-100%). NULL if ML was not used for this signal.';

-- Add ab_test_group column (which group this signal belongs to)
ALTER TABLE trading_signals
ADD COLUMN IF NOT EXISTS ab_test_group VARCHAR(20);

COMMENT ON COLUMN trading_signals.ab_test_group IS
'A/B test group: ml_enhanced, rules_only, or NULL (before AB testing was implemented)';

-- Create index for querying by AB test group
CREATE INDEX IF NOT EXISTS idx_trading_signals_ab_test
ON trading_signals(ab_test_group)
WHERE ab_test_group IS NOT NULL;

-- Create index for querying by ML confidence
CREATE INDEX IF NOT EXISTS idx_trading_signals_ml_confidence
ON trading_signals(ml_confidence)
WHERE ml_confidence IS NOT NULL;

COMMIT;

-- Verify changes
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'trading_signals'
AND column_name IN ('ml_confidence', 'ab_test_group')
ORDER BY ordinal_position;
