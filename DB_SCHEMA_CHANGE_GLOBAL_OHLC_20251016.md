# Database Schema Change: Global OHLC & Tick Data

**Date:** 2025-10-16  
**Type:** Schema Optimization  
**Impact:** BREAKING CHANGE for existing queries

## Changes

### Before (Account-Specific)
```python
# OHLCData with account_id
ohlc = OHLCData(
    account_id=account.id,  # ❌ Account-specific
    symbol='EURUSD',
    timeframe='H1',
    timestamp=datetime.utcnow(),
    open=1.08500,
    high=1.08650,
    low=1.08450,
    close=1.08600,
    volume=50000
)

# Query with account_id
ohlc_data = db.query(OHLCData).filter_by(
    account_id=account.id,  # ❌ Required
    symbol='EURUSD',
    timeframe='H1'
).all()
```

### After (Global Market Data)
```python
# OHLCData without account_id
ohlc = OHLCData(
    # account_id removed! ✅ Global data
    symbol='EURUSD',
    timeframe='H1',
    timestamp=datetime.utcnow(),
    open=1.08500,
    high=1.08650,
    low=1.08450,
    close=1.08600,
    volume=50000
)

# Query without account_id
ohlc_data = db.query(OHLCData).filter_by(
    # No account_id! ✅ Shared across all accounts
    symbol='EURUSD',
    timeframe='H1'
).all()
```

## Rationale

Market data (OHLC bars and ticks) is **universal** - a EURUSD H1 candle is the same for all accounts/brokers.

**Benefits:**
1. ✅ **Reduced Storage:** No duplicate candles per account
2. ✅ **Faster Queries:** Smaller table, better indexing
3. ✅ **Easier Backtesting:** Single source of truth for historical data
4. ✅ **Better Data Quality:** Only one copy to maintain/update

**Database Size Reduction:**
- Old: 6 accounts × 6 symbols × 2 timeframes × 168 bars = **12,096 rows**
- New: 6 symbols × 2 timeframes × 168 bars = **2,016 rows** (83% reduction!)

## Affected Files

### ✅ Already Updated:
1. `app.py` - Both OHLC endpoints:
   - `/api/ohlc/historical` (receive)
   - `/api/ohlc/coverage` (check)
2. `technical_indicators.py` - Query without account_id
3. `signal_worker.py` - Query without account_id
4. Database models (presumably)

### ⚠️ May Need Updates:
Check these files for `OHLCData` queries with `account_id`:
- `backtesting_engine.py`
- `smart_tp_sl.py`
- `pattern_recognition.py`
- `ohlc_aggregator.py`

### Search & Replace Pattern:
```bash
# Find old patterns:
grep -r "OHLCData.*account_id" /projects/ngTradingBot/*.py

# Replace pattern:
# OLD: filter_by(account_id=account.id, symbol=..., timeframe=...)
# NEW: filter_by(symbol=..., timeframe=...)
```

## Migration

### Database Migration (if needed):
```sql
-- Remove account_id column from ohlc_data table
ALTER TABLE ohlc_data DROP COLUMN account_id;

-- Update primary key / unique constraint
ALTER TABLE ohlc_data DROP CONSTRAINT IF EXISTS ohlc_data_pkey;
ALTER TABLE ohlc_data ADD PRIMARY KEY (symbol, timeframe, timestamp);

-- Recreate index for faster queries
CREATE INDEX idx_ohlc_symbol_tf_time ON ohlc_data (symbol, timeframe, timestamp DESC);
```

### Data Cleanup (remove duplicates):
```sql
-- Keep only one copy of each unique candle
DELETE FROM ohlc_data a USING ohlc_data b
WHERE a.id > b.id
  AND a.symbol = b.symbol
  AND a.timeframe = b.timeframe
  AND a.timestamp = b.timestamp;
```

## Testing Checklist

- [ ] Verify OHLC data is being stored without account_id
- [ ] Check that `/api/ohlc/coverage` returns correct counts
- [ ] Verify signal generation still works
- [ ] Test backtesting engine with global data
- [ ] Confirm technical indicators calculate correctly
- [ ] Check that all accounts see the same market data

## Rollback Plan

If issues occur:
1. Re-add `account_id` column to OHLCData model
2. Revert all queries to include `account_id`
3. Restart server to apply old schema
4. EA will repopulate data with account_id

## Notes

- **Ticks** are also global now (same change applied)
- **Trades** remain account-specific (each account has different positions)
- **Signals** remain account-specific (different accounts may have different strategies)
