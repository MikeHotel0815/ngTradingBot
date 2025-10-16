-- Fix migration error: Restore account_id to account-specific tables
-- These tables SHOULD have account_id (they are account-specific, not global):
-- - trading_signals
-- - pattern_detections
-- - indicator_values
-- - indicator_scores

BEGIN;

-- Fix trading_signals - add back account_id
ALTER TABLE trading_signals ADD COLUMN IF NOT EXISTS account_id INTEGER;
UPDATE trading_signals SET account_id = 3 WHERE account_id IS NULL;
ALTER TABLE trading_signals ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE trading_signals ADD CONSTRAINT trading_signals_account_id_fkey
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- Fix pattern_detections - add back account_id
ALTER TABLE pattern_detections ADD COLUMN IF NOT EXISTS account_id INTEGER;
UPDATE pattern_detections SET account_id = 3 WHERE account_id IS NULL;
ALTER TABLE pattern_detections ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE pattern_detections ADD CONSTRAINT pattern_detections_account_id_fkey
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- Fix indicator_values - add back account_id
ALTER TABLE indicator_values ADD COLUMN IF NOT EXISTS account_id INTEGER;
UPDATE indicator_values SET account_id = 3 WHERE account_id IS NULL;
ALTER TABLE indicator_values ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE indicator_values ADD CONSTRAINT indicator_values_account_id_fkey
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- Fix indicator_scores - add back account_id
ALTER TABLE indicator_scores ADD COLUMN IF NOT EXISTS account_id INTEGER;
UPDATE indicator_scores SET account_id = 3 WHERE account_id IS NULL;
ALTER TABLE indicator_scores ALTER COLUMN account_id SET NOT NULL;
ALTER TABLE indicator_scores ADD CONSTRAINT indicator_scores_account_id_fkey
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

COMMIT;

-- Verify
SELECT 'Signals with account_id', COUNT(*) FROM trading_signals WHERE account_id IS NOT NULL;
SELECT 'Patterns with account_id', COUNT(*) FROM pattern_detections WHERE account_id IS NOT NULL;
SELECT 'Indicator values with account_id', COUNT(*) FROM indicator_values WHERE account_id IS NOT NULL;
SELECT 'Indicator scores with account_id', COUNT(*) FROM indicator_scores WHERE account_id IS NOT NULL;
