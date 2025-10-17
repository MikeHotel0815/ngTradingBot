-- Migration: Add autotrade_risk_profile to global_settings
-- Date: 2025-10-17
-- Purpose: Support dynamic confidence calculation based on risk profile

-- Add column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name='global_settings' 
        AND column_name='autotrade_risk_profile'
    ) THEN
        ALTER TABLE global_settings 
        ADD COLUMN autotrade_risk_profile VARCHAR(20) DEFAULT 'normal' NOT NULL;
        
        RAISE NOTICE 'Added autotrade_risk_profile column to global_settings';
    ELSE
        RAISE NOTICE 'Column autotrade_risk_profile already exists';
    END IF;
END $$;

-- Ensure default value is set for existing row
UPDATE global_settings 
SET autotrade_risk_profile = 'normal' 
WHERE autotrade_risk_profile IS NULL;

SELECT 'Migration completed: autotrade_risk_profile added' AS result;
