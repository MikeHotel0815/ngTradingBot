# Signal Generator Refactoring - 2025-11-03

## Overview

Comprehensive refactoring of the Signal Generator to address over-engineering, remove dead code, and make all parameters configurable.

## Problems Identified

### 1. **Over-Complexity**
- Multiple validation layers accumulated over time
- Commented-out code suggesting past over-fitting
- Hard-to-maintain code with scattered magic numbers

### 2. **Double-Penalty on BUY Signals**
- `BUY_SIGNAL_ADVANTAGE = 2` (requires 2 more confirming signals)
- `BUY_CONFIDENCE_PENALTY = 2.0` (reduces confidence by 2%)
- **This was likely filtering out valid BUY opportunities**

### 3. **Hard-Coded Thresholds**
- `MIN_GENERATION_CONFIDENCE = 50`
- `MAX_SPREAD_MULTIPLIER = 3.0`
- No symbol-specific customization
- No way to A/B test different values

### 4. **Dead Code**
- Large commented-out sections mentioning removed filters
- References to "overengineered" systems
- Unclear what was working vs not working

## Changes Implemented

### 1. **New Configuration System** (`signal_config.py`)

Created centralized configuration with:

```python
# Core parameters
MIN_GENERATION_CONFIDENCE = 50
MIN_ACTIVE_CONFIDENCE = 50
MAX_SPREAD_MULTIPLIER = 3.0

# BUY/SELL balance (REDUCED from previous values)
BUY_SIGNAL_ADVANTAGE = 1      # Was 2 - less conservative
BUY_CONFIDENCE_PENALTY = 1.0  # Was 2.0 - less harsh

# Confidence weights
PATTERN_WEIGHT = 30
INDICATOR_WEIGHT = 40
STRENGTH_WEIGHT = 30

# Bonus points
ADX_STRONG_TREND_BONUS = 3
OBV_DIVERGENCE_BONUS = 2
CONFLUENCE_BONUS_PER_INDICATOR = 2

# Symbol-specific overrides
SYMBOL_OVERRIDES = {
    'XAUUSD': {
        'MIN_GENERATION_CONFIDENCE': 55,
        'BUY_SIGNAL_ADVANTAGE': 2,  # More conservative for gold
    },
    'EURUSD': {
        'MIN_GENERATION_CONFIDENCE': 48,  # Less conservative for forex majors
        'BUY_SIGNAL_ADVANTAGE': 1,
    },
    # ... more symbols
}
```

### 2. **Refactored Signal Generator**

#### Before:
- Hard-coded values scattered throughout
- Long comments explaining removed features
- Unclear configuration

#### After:
- All thresholds loaded from config
- Symbol-specific configuration support
- Clean, maintainable code
- Easy to A/B test different parameters

Key changes:
```python
# Load symbol-specific config
self.config = get_config(symbol)

# Use config values
min_confidence = self.config['MIN_GENERATION_CONFIDENCE']
buy_advantage = self.config['BUY_SIGNAL_ADVANTAGE']
buy_penalty = self.config['BUY_CONFIDENCE_PENALTY']

# Calculate weights from config
pattern_weight = self.config['PATTERN_WEIGHT']
indicator_weight = self.config['INDICATOR_WEIGHT']
strength_weight = self.config['STRENGTH_WEIGHT']
```

### 3. **Reduced BUY Signal Bias**

| Parameter | Before | After | Change |
|-----------|--------|-------|--------|
| BUY_SIGNAL_ADVANTAGE | 2 | 1 | -50% (less conservative) |
| BUY_CONFIDENCE_PENALTY | 2.0% | 1.0% | -50% (less harsh) |

**Rationale:**
- The double-penalty was likely over-conservative
- May have been filtering out valid BUY opportunities
- More balanced approach should improve overall performance

### 4. **Removed Dead Code**

Cleaned up:
- Large commented-out sections about removed filters
- Redundant comments explaining past iterations
- Unclear historical notes

### 5. **Symbol-Specific Configuration**

Now supports per-symbol overrides:
- **Metals (XAUUSD, XAGUSD)**: More conservative (55% min confidence, advantage=2)
- **Forex Majors (EURUSD, GBPUSD, AUDUSD)**: Less conservative (48% min confidence, advantage=1)
- **Default**: Balanced approach (50% min confidence, advantage=1)

## Expected Improvements

### 1. **More BUY Signals**
With reduced bias, expect:
- 20-30% more BUY signal generation
- Better balance between BUY/SELL signals
- Improved opportunity capture

### 2. **Better Maintainability**
- Single source of truth for all parameters
- Easy to adjust without code changes
- Clear documentation of what each parameter does

### 3. **Symbol-Specific Optimization**
- Can now tune parameters per symbol
- Different risk levels for different asset classes
- Data-driven optimization possible

### 4. **Easier A/B Testing**
- Can test different configurations easily
- Track which parameters work best
- Iterate based on actual performance data

## Configuration API

### Get Config
```python
from signal_config import get_config

# Get default config
config = get_config()

# Get symbol-specific config (with overrides applied)
config = get_config('EURUSD')
```

### Update Config at Runtime
```python
from signal_config import update_config

# Update config for specific symbol
update_config('XAUUSD',
    MIN_GENERATION_CONFIDENCE=60,
    BUY_SIGNAL_ADVANTAGE=3
)
```

## Migration Notes

### No Database Changes Required
- All changes are code-level only
- No migrations needed
- Backward compatible with existing signals

### Configuration Tuning
After deployment, monitor:
1. BUY vs SELL signal ratio
2. Win rates for each signal type
3. Confidence distribution

Adjust `SYMBOL_OVERRIDES` based on actual performance data.

## Testing

### Build & Deploy
```bash
docker compose build workers
docker compose restart workers
```

### Monitor Logs
```bash
docker logs ngtradingbot_workers --tail 100 -f
```

Look for:
- ✅ Signal generation working
- Confidence values using new thresholds
- BUY signal increase (expected)

## Next Steps

### Short-term (1-3 days)
1. **Monitor BUY/SELL ratio** - Should be more balanced
2. **Track win rates** - Both BUY and SELL should improve
3. **Watch confidence distribution** - Should see more 48-52% signals

### Medium-term (1-2 weeks)
1. **Analyze performance by symbol** - Identify which need tuning
2. **Optimize SYMBOL_OVERRIDES** - Data-driven configuration
3. **A/B test different parameter sets** - Find optimal values

### Long-term (1+ month)
1. **Implement dynamic configuration** - Learn from performance
2. **Add configuration UI** - Allow runtime adjustments
3. **Automated parameter optimization** - ML-based tuning

## Rollback Plan

If issues occur:
```bash
git revert <commit_hash>
docker compose build workers
docker compose restart workers
```

Configuration is backward compatible - can revert to old values in `signal_config.py`:
```python
BUY_SIGNAL_ADVANTAGE = 2      # Revert to old value
BUY_CONFIDENCE_PENALTY = 2.0  # Revert to old value
```

## Files Modified

1. **signal_config.py** - NEW: Centralized configuration
2. **signal_generator.py** - REFACTORED: Uses config system
   - Removed hard-coded values
   - Cleaned up dead code
   - Added symbol-specific support

## Performance Baseline

Before refactoring (from context):
- Issue: Double-penalty on BUY signals
- Hard-coded thresholds
- No symbol-specific tuning

After refactoring:
- **Will measure after 24-48 hours of operation**
- Expected: Better BUY signal quality
- Expected: More balanced BUY/SELL ratio
- Expected: Symbol-specific optimization working

---

## Conclusion

This refactoring addresses the core issues identified:
1. ✅ **Simplified** - Removed over-engineering and dead code
2. ✅ **Configurable** - All thresholds now in central config
3. ✅ **Balanced** - Reduced BUY signal bias
4. ✅ **Maintainable** - Clear, clean, documented code
5. ✅ **Extensible** - Symbol-specific configuration support

The signal generator is now easier to understand, maintain, and optimize based on actual performance data.
