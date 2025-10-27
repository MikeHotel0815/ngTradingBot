-- Add custom ML prediction fields for confidence tracking and A/B testing
-- Created: 2025-10-27
-- Purpose: Fix ML prediction logging schema mismatch

-- Add ml_confidence field (ML model's raw confidence score)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS ml_confidence DOUBLE PRECISION;

-- Add rules_confidence field (rules-based confidence score)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS rules_confidence DOUBLE PRECISION;

-- Add final_confidence field (combined/blended confidence)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS final_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0;

-- Add decision field (TRADE/NO_TRADE/SKIP)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS decision VARCHAR(20);

-- Add ab_test_group field (ml_only/rules_only/hybrid)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS ab_test_group VARCHAR(20);

-- Add features_used field (JSON of features used in prediction)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS features_used JSONB;

-- Create index on final_confidence for performance queries
CREATE INDEX IF NOT EXISTS idx_ml_predictions_confidence
ON ml_predictions(final_confidence DESC);

-- Create index on ab_test_group for A/B testing analysis
CREATE INDEX IF NOT EXISTS idx_ml_predictions_ab_group
ON ml_predictions(ab_test_group)
WHERE ab_test_group IS NOT NULL;

-- Add comment
COMMENT ON COLUMN ml_predictions.ml_confidence IS 'Raw ML model confidence score (0-1)';
COMMENT ON COLUMN ml_predictions.rules_confidence IS 'Rules-based confidence score (0-1)';
COMMENT ON COLUMN ml_predictions.final_confidence IS 'Final blended confidence used for decision (0-1)';
COMMENT ON COLUMN ml_predictions.decision IS 'Trading decision: TRADE, NO_TRADE, SKIP';
COMMENT ON COLUMN ml_predictions.ab_test_group IS 'A/B test group: ml_only, rules_only, hybrid';
COMMENT ON COLUMN ml_predictions.features_used IS 'JSON object of features used in prediction';
