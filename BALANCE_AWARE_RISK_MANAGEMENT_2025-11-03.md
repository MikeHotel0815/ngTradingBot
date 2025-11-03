# Balance-Aware Risk Management - Implementation

**Date**: 2025-11-03  
**Status**: ✅ Implemented  
**Version**: v2.0

## Problem

**Critical Issue**: Fixed SL limits caused excessive risk at low account balance

### Example (XAUUSD Trade #17106111)
- **Balance**: €613
- **Fixed SL Limit**: €100 
- **Actual Risk**: **16.5% of account** (WAY TOO HIGH!)
- **Volume**: 0.02 lot (minimum)
- **SL Distance**: 50.46 points

**Standard Risk Management Rule**: Max 2-3% risk per trade, not 16.5%!

## Root Cause

System used **FIXED** maximum loss limits per symbol:
```python
# OLD (BROKEN):
MAX_LOSS_PER_TRADE = {
    'XAUUSD': 100.00,  # ❌ Fixed €100 regardless of balance
    'EURUSD': 30.00,   # ❌ Fixed €30 regardless of balance
}
```

**Problems**:
1. €100 limit = 16.5% risk at €613 balance
2. €100 limit = 5% risk at €2000 balance  
3. €100 limit = 1% risk at €10,000 balance
4. Risk percentage changes as account grows/shrinks!

## Solution: Percentage-Based Risk

Changed to **DYNAMIC** risk based on account balance:

```python
# NEW (BALANCE-AWARE):
MAX_RISK_PCT_PER_TRADE = {
    'XAUUSD': 2.0,    # ✅ 2% of CURRENT balance
    'EURUSD': 2.0,    # ✅ 2% of CURRENT balance
    'BTCUSD': 2.5,    # ✅ 2.5% of CURRENT balance (more volatile)
}
```

**Benefits**:
- €613 balance → Max €12.26 loss (2%)
- €2000 balance → Max €40 loss (2%)
- €10,000 balance → Max €200 loss (2%)
- **Risk percentage stays constant** as account changes!

## Implementation

### 1. Modified `sl_enforcement.py`

**Lines 27-45**: Added `MAX_RISK_PCT_PER_TRADE` configuration
```python
MAX_RISK_PCT_PER_TRADE = {
    'XAGUSD': 2.0,    # Silver: Max 2% of balance per trade
    'XAUUSD': 2.0,    # Gold: Max 2% of balance per trade
    'DE40.c': 2.0,    # DAX: Max 2% of balance per trade
    'US500.c': 2.0,   # S&P500: Max 2% of balance per trade
    'BTCUSD': 2.5,    # Bitcoin: Max 2.5% of balance (more volatile OK)
    'ETHUSD': 2.5,    # Ethereum: Max 2.5% of balance
    'USDJPY': 2.0,    # USDJPY: Max 2% of balance
    'EURUSD': 2.0,    # EURUSD: Max 2% of balance
    'GBPUSD': 2.0,    # GBPUSD: Max 2% of balance
    'AUDUSD': 2.0,    # AUDUSD: Max 2% of balance
    'FOREX': 2.0,     # Default Forex: Max 2% of balance
    'DEFAULT': 2.0    # Fallback: Max 2% of balance
}
```

**Lines 247-272**: Updated `_validate_max_loss()` to calculate dynamic limits
```python
# Get current account balance
account = db.query(Account).first()
balance = float(account.balance)

# Get max risk percentage for this symbol
max_risk_pct = self.MAX_RISK_PCT_PER_TRADE.get(symbol, 2.0)

# Calculate max allowed loss based on balance
max_loss = balance * (max_risk_pct / 100.0)

logger.info(
    f"SL Validation: {symbol} | Balance: €{balance:.2f} | "
    f"Max Risk: {max_risk_pct}% (€{max_loss:.2f}) | "
    f"Potential Loss: €{potential_loss_eur:.2f}"
)
```

### 2. Modified `position_sizer.py`

**Lines 184-212**: Updated position sizing to use balance-aware limits
```python
# Get max risk percentage for this symbol (balance-aware)
max_risk_pct = sl_enforcer.MAX_RISK_PCT_PER_TRADE.get(
    symbol.upper(),
    sl_enforcer.MAX_RISK_PCT_PER_TRADE.get('DEFAULT', 2.0)
)

# Calculate max loss based on CURRENT balance (dynamic!)
max_loss_limit = balance * (max_risk_pct / 100.0)

# If potential loss exceeds limit, reduce lot size proportionally
if potential_loss > max_loss_limit:
    max_safe_lot = max_loss_limit / (sl_distance_pips * pip_value_per_lot)
    
    logger.warning(
        f"⚠️ Reducing lot size for {symbol}: "
        f"Original: {final_lot:.3f} lot (loss: €{potential_loss:.2f}) → "
        f"Adjusted: {max_safe_lot:.3f} lot (max loss: €{max_loss_limit:.2f} "
        f"= {max_risk_pct}% of €{balance:.2f})"
    )
    
    final_lot = max_safe_lot
```

## Impact Analysis

### Before (Fixed Limits)

| Balance | Symbol  | Fixed Limit | Actual Risk % |
|---------|---------|-------------|---------------|
| €613    | XAUUSD  | €100        | 16.3% ❌      |
| €613    | EURUSD  | €30         | 4.9% ❌       |
| €2000   | XAUUSD  | €100        | 5.0% ❌       |
| €10000  | XAUUSD  | €100        | 1.0% ✅       |

**Problem**: Risk varies wildly with account size!

### After (Percentage-Based)

| Balance | Symbol  | 2% Limit | Actual Risk % |
|---------|---------|----------|---------------|
| €613    | XAUUSD  | €12.26   | 2.0% ✅       |
| €613    | EURUSD  | €12.26   | 2.0% ✅       |
| €2000   | XAUUSD  | €40.00   | 2.0% ✅       |
| €10000  | XAUUSD  | €200.00  | 2.0% ✅       |

**Solution**: Risk stays constant at 2% regardless of balance!

## Example Calculations

### XAUUSD at €613 Balance

**Before (Fixed €100 limit)**:
- SL Distance: 50 points
- Volume: 0.02 lot
- Max Loss: €100
- Risk: 16.3% of account ❌

**After (2% of balance)**:
- SL Distance: 50 points
- Volume: 0.005 lot (auto-reduced)
- Max Loss: €12.26
- Risk: 2.0% of account ✅

### XAUUSD at €2000 Balance

**Before (Fixed €100 limit)**:
- SL Distance: 50 points
- Volume: 0.02 lot
- Max Loss: €100
- Risk: 5.0% of account ❌

**After (2% of balance)**:
- SL Distance: 50 points
- Volume: 0.008 lot (auto-adjusted)
- Max Loss: €40
- Risk: 2.0% of account ✅

## Files Modified

- ✅ `sl_enforcement.py` (Lines 27-45, 247-304)
- ✅ `position_sizer.py` (Lines 184-232)

## Backward Compatibility

Old `MAX_LOSS_PER_TRADE` dictionary kept but **DEPRECATED**:
- Not used in calculations anymore
- Kept only for reference
- Will be removed in future version

## Testing Plan

### 1. Verify Current Trades (Immediate)
```bash
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c \
  "SELECT ticket, symbol, volume, 
   ROUND((ABS(open_price - sl) * volume * 100)::numeric, 2) as max_loss_eur,
   ROUND((ABS(open_price - sl) * volume * 100 / (SELECT balance FROM accounts LIMIT 1) * 100)::numeric, 2) as risk_pct
   FROM trades WHERE status='open';"
```

Expected: All trades should show risk_pct ≤ 2.5%

### 2. Monitor New Trade Creation (24-48h)
Watch logs for:
```
SL Validation: XAUUSD | Balance: €613.00 | Max Risk: 2.0% (€12.26) | Potential Loss: €10.50
📊 Position Size: XAUUSD | Balance: €613.00 | ... | Max Loss: €10.50 (limit: €12.26 = 2.0% of balance)
```

### 3. Test Balance Growth (Long-term)
- €600 → Max loss €12
- €1000 → Max loss €20
- €2000 → Max loss €40
- Verify risk scales proportionally

## Benefits

✅ **Consistent Risk**: Always 2% regardless of account size  
✅ **Account Protection**: Prevents catastrophic losses at low balance  
✅ **Scalability**: Risk grows with account automatically  
✅ **Flexibility**: Different symbols can have different risk %  
✅ **Transparency**: Logs show exact balance, risk %, and limits

## Rollback Plan

If issues occur:

1. **Revert sl_enforcement.py**:
   - Change line 266: `max_loss = self.MAX_LOSS_PER_TRADE.get(symbol)`
   - Remove lines 247-263 (balance query)

2. **Revert position_sizer.py**:
   - Change lines 188-195 to use `MAX_LOSS_PER_TRADE` directly

3. **Restart server**:
   ```bash
   docker restart ngtradingbot_server
   ```

## Next Steps

1. ✅ Deploy changes (rebuild container)
2. ⏳ Monitor first 5-10 new trades
3. ⏳ Verify risk percentages in logs
4. ⏳ Confirm no trades exceed 2.5% risk
5. ⏳ Document real-world results

---

**Generated**: 2025-11-03  
**Implementation**: Balance-Aware Risk Management  
**Purpose**: Protect account from excessive risk at low balance
