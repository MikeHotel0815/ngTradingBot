-- Migration: Add outcome tracking fields to ml_predictions table
-- Purpose: Enable logging of actual trade outcomes for ML model evaluation
-- Date: 2025-10-27

-- Add actual_outcome field (win/loss/no_trade)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS actual_outcome VARCHAR(20);

-- Add actual_profit field (actual profit/loss in EUR)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS actual_profit DOUBLE PRECISION;

-- Add outcome_time field (when the outcome was determined)
ALTER TABLE ml_predictions
ADD COLUMN IF NOT EXISTS outcome_time TIMESTAMP;

-- Create index for querying predictions by outcome
CREATE INDEX IF NOT EXISTS idx_ml_predictions_outcome
ON ml_predictions(actual_outcome)
WHERE actual_outcome IS NOT NULL;

-- Create index for querying predictions with outcomes
CREATE INDEX IF NOT EXISTS idx_ml_predictions_outcome_time
ON ml_predictions(outcome_time DESC)
WHERE outcome_time IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN ml_predictions.actual_outcome IS 'Actual trading outcome: win, loss, or no_trade';
COMMENT ON COLUMN ml_predictions.actual_profit IS 'Actual profit/loss in EUR from the trade';
COMMENT ON COLUMN ml_predictions.outcome_time IS 'Timestamp when the trade outcome was determined';
