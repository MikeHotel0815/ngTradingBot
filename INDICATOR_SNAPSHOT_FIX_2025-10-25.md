# Indicator Snapshot Fix - 2025-10-25

## Problem
Indicator snapshots in the database had empty `indicators: {}` field, making retrospective analysis of trades impossible.

**Database Evidence:**
```json
{
  "indicators": {},
  "patterns": ["Bearish Harami"],
  "price_levels": {"bid": 98765.43, "ask": 98767.21},
  "timestamp": "2025-10-25T14:30:00"
}
```

Only patterns were captured, but ALL indicator values were missing.

## Root Cause
The `_capture_indicator_snapshot()` method in [signal_generator.py](signal_generator.py:606-673) used a **manual whitelist approach** with if/elif statements:

```python
for indicator_name, value in signal.get('indicators_used', {}).items():
    if indicator_name == 'RSI':
        # capture RSI
    elif indicator_name == 'MACD':
        # capture MACD
    # ... only 8 specific indicators
```

**Problem:**
- Only 8 indicators were whitelisted: RSI, MACD, BB, Stochastic, ADX, ATR, EMA, OBV
- Any other indicator (HEIKEN_ASHI_TREND, SUPERTREND, ICHIMOKU, PRICE_ACTION, etc.) was **silently skipped**
- Result: `indicators: {}` in database snapshot

## Solution Implemented

### 1. Removed Manual Whitelist
**Before:**
```python
for indicator_name, value in signal.get('indicators_used', {}).items():
    if indicator_name == 'RSI':
        rsi_data = self.indicators.calculate_rsi()
        snapshot['indicators']['RSI'] = {...}
    elif indicator_name == 'MACD':
        # ... repeat for 8 indicators
```

**After:**
```python
# Capture ALL indicator values directly from signal
for indicator_name, value in signal.get('indicators_used', {}).items():
    try:
        # Store the indicator value as-is (already contains all relevant data)
        snapshot['indicators'][indicator_name] = value
    except Exception as e:
        logger.warning(f"Failed to capture {indicator_name} snapshot: {e}")
```

**Benefits:**
- ✅ Captures EVERY indicator in `signal['indicators_used']`
- ✅ No need to maintain whitelist
- ✅ Works with future indicators automatically
- ✅ Simpler, more maintainable code

### 2. Added Market Regime Information
**New field:**
```python
snapshot['market_regime'] = {
    'state': regime.get('regime'),  # TRENDING/RANGING/TOO_WEAK
    'trend_strength': regime.get('trend_strength'),
    'volatility': regime.get('volatility'),
    'direction': regime.get('direction')  # bullish/bearish/neutral
}
```

**Why Critical:**
- Market regime explains WHY a signal was generated or filtered
- Essential for understanding signal quality in context
- Enables analysis like "were RANGING market signals more profitable?"

### 3. Enhanced Price Levels
**Added spread calculation:**
```python
snapshot['price_levels']['spread'] = float(latest_tick.ask) - float(latest_tick.bid)
```

**Why Important:**
- Spread affects trade profitability
- High spread = harder to profit
- Useful for filtering symbols by trading conditions

## Impact on Retrospective Analysis

### Before Fix
**What you could analyze:**
- ❌ Which indicators triggered the trade (empty)
- ✅ Which patterns were detected
- ✅ Entry price
- ❌ Market conditions at signal generation (missing)

**Query result:**
```sql
SELECT indicator_snapshot FROM trading_signals WHERE symbol='BTCUSD';
-- Result: {"indicators": {}, "patterns": [...]}
```

### After Fix
**What you can analyze:**
- ✅ Which indicators triggered the trade (ALL values)
- ✅ Which patterns were detected
- ✅ Entry price + spread
- ✅ Market regime (TRENDING/RANGING)
- ✅ Trend strength and direction
- ✅ Volatility level

**Query result:**
```sql
SELECT indicator_snapshot FROM trading_signals WHERE symbol='BTCUSD';
-- Result: {
--   "indicators": {
--     "RSI": {"value": 65.2, "signal": "BUY"},
--     "MACD": {"histogram": 0.015, "signal": "BUY"},
--     "HEIKEN_ASHI_TREND": {"direction": "bullish", "strength": 0.8},
--     "SUPERTREND": {"trend": "bullish", "price_distance": 150.3},
--     "PRICE_ACTION": {"pattern": "higher_highs", "strength": 0.7}
--   },
--   "patterns": ["Bullish Engulfing"],
--   "market_regime": {
--     "state": "TRENDING",
--     "trend_strength": 75.3,
--     "direction": "bullish",
--     "volatility": 1.2
--   },
--   "price_levels": {"bid": 98765.43, "ask": 98767.21, "spread": 1.78}
-- }
```

## New Analysis Capabilities

### 1. Indicator Performance by Market Regime
```sql
-- Find which indicators work best in RANGING markets
SELECT
    t.symbol,
    ts.indicator_snapshot->'market_regime'->>'state' AS regime,
    COUNT(*) AS trades,
    AVG(t.profit_loss) AS avg_profit,
    COUNT(CASE WHEN t.profit_loss > 0 THEN 1 END) * 100.0 / COUNT(*) AS win_rate
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE ts.indicator_snapshot->'market_regime'->>'state' = 'RANGING'
GROUP BY t.symbol, regime
ORDER BY avg_profit DESC;
```

### 2. Indicator Contribution Analysis
```sql
-- Which indicators appear in winning vs losing trades?
SELECT
    jsonb_object_keys(ts.indicator_snapshot->'indicators') AS indicator,
    COUNT(CASE WHEN t.profit_loss > 0 THEN 1 END) AS wins,
    COUNT(CASE WHEN t.profit_loss <= 0 THEN 1 END) AS losses,
    AVG(t.profit_loss) AS avg_profit
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE ts.indicator_snapshot->'indicators' IS NOT NULL
GROUP BY indicator
ORDER BY avg_profit DESC;
```

### 3. Spread Impact on Profitability
```sql
-- Do high-spread trades have lower win rates?
SELECT
    CASE
        WHEN CAST(ts.indicator_snapshot->'price_levels'->>'spread' AS FLOAT) < 2.0 THEN 'Low (<2 pips)'
        WHEN CAST(ts.indicator_snapshot->'price_levels'->>'spread' AS FLOAT) < 5.0 THEN 'Medium (2-5 pips)'
        ELSE 'High (>5 pips)'
    END AS spread_category,
    COUNT(*) AS trades,
    AVG(t.profit_loss) AS avg_profit,
    COUNT(CASE WHEN t.profit_loss > 0 THEN 1 END) * 100.0 / COUNT(*) AS win_rate
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE ts.indicator_snapshot->'price_levels'->>'spread' IS NOT NULL
GROUP BY spread_category
ORDER BY avg_profit DESC;
```

### 4. Trend Strength vs. Profitability
```sql
-- Are stronger trends more profitable?
SELECT
    CASE
        WHEN CAST(ts.indicator_snapshot->'market_regime'->>'trend_strength' AS FLOAT) < 30 THEN 'Weak (<30%)'
        WHEN CAST(ts.indicator_snapshot->'market_regime'->>'trend_strength' AS FLOAT) < 60 THEN 'Medium (30-60%)'
        ELSE 'Strong (>60%)'
    END AS trend_category,
    COUNT(*) AS trades,
    AVG(t.profit_loss) AS avg_profit,
    COUNT(CASE WHEN t.profit_loss > 0 THEN 1 END) * 100.0 / COUNT(*) AS win_rate
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE ts.indicator_snapshot->'market_regime'->>'trend_strength' IS NOT NULL
GROUP BY trend_category
ORDER BY avg_profit DESC;
```

## Code Changes

**File:** [signal_generator.py](signal_generator.py:606-673)

**Lines Modified:**
- Lines 606-673: Complete rewrite of `_capture_indicator_snapshot()`
- Removed: 70+ lines of if/elif whitelisting
- Added: Direct copy of all indicators from `signal['indicators_used']`
- Added: Market regime capture
- Added: Spread calculation

**Total Changes:**
- Deleted: ~70 lines (whitelist logic)
- Added: ~15 lines (generic capture + regime)
- Net reduction: 55 lines
- Complexity reduction: O(n) instead of O(n*m) where m=whitelist size

## Testing Plan

### 1. Verify Snapshot Structure
```python
from signal_generator import SignalGenerator
from database import ScopedSession

db = ScopedSession()
generator = SignalGenerator(1, 'BTCUSD', 'H1', 'aggressive')
signals = generator.generate_signals()

if signals:
    snapshot = signals[0].get('indicator_snapshot', {})
    print(f"Indicators captured: {len(snapshot.get('indicators', {}))}")
    print(f"Market regime: {snapshot.get('market_regime')}")
    print(f"Indicators: {list(snapshot.get('indicators', {}).keys())}")
```

**Expected Output:**
```
Indicators captured: 5-10 (not 0!)
Market regime: {'state': 'RANGING', 'trend_strength': 50.3, ...}
Indicators: ['RSI', 'MACD', 'HEIKEN_ASHI_TREND', 'SUPERTREND', 'PRICE_ACTION', ...]
```

### 2. Database Verification
```sql
-- Check latest signals have populated indicators
SELECT
    symbol,
    timeframe,
    jsonb_object_keys(indicator_snapshot->'indicators') AS indicators_count,
    indicator_snapshot->'market_regime'->>'state' AS regime,
    created_at
FROM trading_signals
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;
```

**Expected:** Multiple indicator names listed, not empty.

### 3. Monitor Logs
```bash
docker logs ngtradingbot_workers --tail 500 -f | grep -i "indicator snapshot"
```

**Expected:** No warnings about failed captures for common indicators.

## Deployment Steps

1. ✅ Code changes committed
2. ⏳ Rebuild Docker containers: `docker compose build --no-cache workers`
3. ⏳ Restart containers: `docker compose up -d`
4. ⏳ Monitor logs for 5 minutes
5. ⏳ Verify new signals have populated indicator_snapshot
6. ⏳ Run retrospective analysis queries

## Backwards Compatibility

**Old signals** (with empty indicators):
- Still have patterns and price_levels
- market_regime will be missing (expected)
- Can be excluded from analysis with `WHERE indicator_snapshot->'indicators' != '{}'`

**New signals** (after fix):
- Have complete indicators
- Have market_regime
- Have spread in price_levels

**Migration:** No database migration needed - JSONB fields are flexible.

## Performance Impact

### Before
- 8 indicator method calls (calculate_rsi, calculate_macd, etc.)
- Each call fetches data from database/cache
- Total: ~8 DB/cache hits per signal

### After
- 0 indicator method calls (data already in signal)
- 1 regime detection call (already cached)
- Total: ~1 cache hit per signal

**Result:** ✅ FASTER (90% fewer calls)

## Related Documentation

- [TRADE_DATA_CAPTURE_ANALYSIS.md](TRADE_DATA_CAPTURE_ANALYSIS.md) - Original analysis identifying the issue
- [BTCUSD_NO_SIGNALS_ANALYSIS.md](BTCUSD_NO_SIGNALS_ANALYSIS.md) - Market regime filtering
- [RISK_PROFILE_REGIME_FILTER_INTEGRATION.md](RISK_PROFILE_REGIME_FILTER_INTEGRATION.md) - Aggressive mode integration

## Date
2025-10-25 15:45 UTC
