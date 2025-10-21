-- Migration: Add contract_size column to broker_symbols table
-- Date: 2025-10-21
-- Purpose: Store MT5-provided contract sizes to eliminate hardcoded values and prevent calculation errors

-- Add contract_size column to broker_symbols table
ALTER TABLE broker_symbols
ADD COLUMN IF NOT EXISTS contract_size NUMERIC(20, 2);

-- Add comment explaining the field
COMMENT ON COLUMN broker_symbols.contract_size IS 'Contract size from MT5 (e.g., 100000 for forex, 5000 for XAGUSD). Auto-updated by EA via /api/symbol_specs endpoint.';

-- Log migration
DO $$
BEGIN
    RAISE NOTICE 'Migration completed: Added contract_size column to broker_symbols';
    RAISE NOTICE 'Contract sizes will be automatically populated when EA sends symbol specs';
    RAISE NOTICE 'System will fall back to heuristic detection if contract_size is NULL';
END $$;
