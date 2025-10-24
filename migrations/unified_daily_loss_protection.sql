-- Migration: Unified Daily Loss Protection
-- Date: 2025-10-24
-- Purpose: Harmonize all daily loss protection mechanisms into ONE central system

-- Step 1: Add new columns to daily_drawdown_limits table
ALTER TABLE daily_drawdown_limits
ADD COLUMN IF NOT EXISTS protection_enabled BOOLEAN DEFAULT true,
ADD COLUMN IF NOT EXISTS auto_pause_enabled BOOLEAN DEFAULT true,
ADD COLUMN IF NOT EXISTS pause_after_consecutive_losses INTEGER DEFAULT 3,
ADD COLUMN IF NOT EXISTS max_total_drawdown_percent NUMERIC(5, 2) DEFAULT 20.0,
ADD COLUMN IF NOT EXISTS circuit_breaker_tripped BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS last_reset_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS notes TEXT;

-- Step 2: Update existing records with sensible defaults
UPDATE daily_drawdown_limits
SET protection_enabled = true,
    auto_pause_enabled = false,  -- Disabled for testing (was causing issues)
    pause_after_consecutive_losses = 3,
    max_total_drawdown_percent = 20.0,
    circuit_breaker_tripped = false,
    last_reset_at = NOW()
WHERE protection_enabled IS NULL;

-- Step 3: Set reasonable limits for Account 3 (testing account)
UPDATE daily_drawdown_limits
SET max_daily_loss_percent = 10.0,  -- Back to 10% (was 99% for testing)
    protection_enabled = true,
    auto_pause_enabled = false,  -- Keep disabled for testing
    notes = 'Testing account - auto-pause disabled, daily loss 10%'
WHERE account_id = 3;

-- Step 4: Verify changes
SELECT
    account_id,
    protection_enabled,
    max_daily_loss_percent,
    max_daily_loss_eur,
    auto_pause_enabled,
    pause_after_consecutive_losses,
    max_total_drawdown_percent,
    circuit_breaker_tripped,
    limit_reached,
    daily_pnl
FROM daily_drawdown_limits
ORDER BY account_id;

-- Expected result:
-- account_id | protection_enabled | max_daily_loss_percent | auto_pause_enabled | pause_after_consecutive_losses | circuit_breaker_tripped
-- -----------|-------------------|------------------------|-------------------|-------------------------------|------------------------
--          1 | true              | 2.00                   | false             | 3                             | false
--          3 | true              | 10.00                  | false             | 3                             | false

COMMENT ON COLUMN daily_drawdown_limits.protection_enabled IS 'Master switch: Enable/disable ALL daily loss protection';
COMMENT ON COLUMN daily_drawdown_limits.auto_pause_enabled IS 'Enable auto-pause of symbols after consecutive losses';
COMMENT ON COLUMN daily_drawdown_limits.pause_after_consecutive_losses IS 'Number of consecutive losses before auto-pause triggers';
COMMENT ON COLUMN daily_drawdown_limits.max_total_drawdown_percent IS 'Maximum total account drawdown before circuit breaker trips';
COMMENT ON COLUMN daily_drawdown_limits.circuit_breaker_tripped IS 'Circuit breaker status (persistent across restarts)';
COMMENT ON COLUMN daily_drawdown_limits.last_reset_at IS 'Timestamp of last manual reset';
