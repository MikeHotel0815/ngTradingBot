# Risk Profile Integration mit Regime Filter - 2025-10-25

## Problem
User hat `risk_profile = 'aggressive'` gesetzt, aber BTCUSD generiert trotzdem keine Signale.

**Root Cause:** Das `risk_profile` wurde nur im Auto-Trader verwendet (min_confidence, spread limits), aber **NICHT** im Signal Generator's Regime Filter. Der Regime Filter filterte Signale unabhängig vom risk_profile, was bei RANGING Markets zu sehr wenigen Signalen führte.

## Lösung Implementiert

### 1. Technical Indicators - Regime Filter erweitert
**File:** [technical_indicators.py](technical_indicators.py)

**Änderungen:**
- `__init__()` akzeptiert jetzt `risk_profile` Parameter (default: 'normal')
- `_filter_by_regime()` berücksichtigt `risk_profile` beim Filtern

**Logik:**

#### AGGRESSIVE Mode (mehr Signale):
```python
RANGING Market:
  - ✅ mean_reversion signals
  - ✅ neutral signals
  - ✅ trend_following signals (NEU!)

TRENDING Market:
  - ✅ trend_following signals
  - ✅ neutral signals
  - ✅ mean_reversion signals (NEU!)

TOO_WEAK Market:
  - ✅ neutral signals (NEU!)
```

#### NORMAL Mode (wie bisher):
```python
RANGING Market:
  - ✅ mean_reversion signals
  - ✅ neutral signals
  - ❌ trend_following signals (gefiltert)

TRENDING Market:
  - ✅ trend_following signals
  - ✅ neutral signals
  - ❌ mean_reversion signals (gefiltert)

TOO_WEAK Market:
  - ❌ Alle signals gefiltert
```

#### MODERATE Mode (sehr konservativ):
```python
RANGING Market:
  - ✅ neutral signals ONLY
  - ❌ mean_reversion signals (gefiltert)
  - ❌ trend_following signals (gefiltert)

TRENDING Market:
  - ✅ trend_following signals
  - ✅ neutral signals
  - ❌ mean_reversion signals (gefiltert)

TOO_WEAK Market:
  - ❌ Alle signals gefiltert
```

### 2. Signal Generator - risk_profile Parameter
**File:** [signal_generator.py](signal_generator.py:22)

**Änderung:**
```python
def __init__(self, account_id: int, symbol: str, timeframe: str, risk_profile: str = 'normal'):
    # ...
    self.risk_profile = risk_profile
    self.indicators = TechnicalIndicators(
        account_id, symbol, timeframe,
        cache_ttl=15,
        risk_profile=risk_profile  # NEU!
    )
```

### 3. Unified Workers - risk_profile übergeben
**File:** [unified_workers.py](unified_workers.py:437)

**Änderung:**
```python
for account in accounts:
    # Get account risk profile (default to 'normal' if not set)
    risk_profile = getattr(account, 'risk_profile', 'normal')

    for sub in subscribed:
        for timeframe in ['H1', 'H4']:
            generator = SignalGenerator(
                account.id, sub.symbol, timeframe,
                risk_profile  # NEU!
            )
```

### 4. Signal Worker - risk_profile übergeben
**File:** [signal_worker.py](signal_worker.py:127)

**Änderung:**
```python
# Extract account ID and risk_profile immediately
account_id = account.id
risk_profile = getattr(account, 'risk_profile', 'normal')  # NEU!

# ...later...
generator = SignalGenerator(
    account_id, symbol_name, timeframe,
    risk_profile  # NEU!
)
```

## Erwartete Auswirkung für BTCUSD

### Vorher (NORMAL mode in RANGING market):
```
Signals: 5 total
  ↓ Regime Filter (RANGING, normal)
  ↓ Filtert trend_following aus
Signals: 1 after filter (nur mean_reversion/neutral)
```

### Nachher (AGGRESSIVE mode in RANGING market):
```
Signals: 5 total
  ↓ Regime Filter (RANGING, aggressive)
  ↓ ERLAUBT trend_following UND mean_reversion
Signals: 5 after filter (alle Signale!)
```

**Erwartung:**
- **5× mehr Signale** für BTCUSD in aggressive Mode
- Trend-following Indikatoren (HEIKEN_ASHI_TREND, SUPERTREND, ICHIMOKU) werden jetzt durchgelassen
- Frühe Trend-Reversals in RANGING Markets werden erkannt

## Risk/Reward Trade-off

### Aggressive Mode
**Vorteile:**
- ✅ Mehr Trading-Opportunities
- ✅ Catch early trend reversals in ranging markets
- ✅ Nutzt starke Indikatoren (Heiken Ashi, Ichimoku)

**Nachteile:**
- ⚠️ Mehr False Signals in ranging markets
- ⚠️ Höhere Anzahl an Whipsaw-Losses
- ⚠️ Drawdowns können schneller ansteigen

**Mitigation:**
- Auto-Trader hat noch min_confidence Filter (50% in aggressive)
- SL Enforcement schützt vor zu großen Losses
- Circuit Breakers greifen bei zu hohem Drawdown

### Moderate Mode
**Vorteile:**
- ✅ Sehr konservativ, nur high-quality signals
- ✅ Geringeres Drawdown-Risiko
- ✅ Höhere Win-Rate pro Trade

**Nachteile:**
- ⚠️ Sehr wenige Trading-Opportunities
- ⚠️ Verpasst viele profitable Trades
- ⚠️ Niedrigere absolute Gewinne

## Code Changes Summary

**Files Modified:**
1. [technical_indicators.py](technical_indicators.py)
   - Line 30: Added `risk_profile` parameter to `__init__()`
   - Line 45: Store `self.risk_profile`
   - Lines 1934-2000: Enhanced `_filter_by_regime()` with risk_profile logic

2. [signal_generator.py](signal_generator.py)
   - Line 22: Added `risk_profile` parameter to `__init__()`
   - Line 35: Store `self.risk_profile`
   - Line 38: Pass `risk_profile` to TechnicalIndicators

3. [unified_workers.py](unified_workers.py)
   - Lines 438-439: Load `risk_profile` from Account
   - Line 450: Pass `risk_profile` to SignalGenerator

4. [signal_worker.py](signal_worker.py)
   - Line 129: Load `risk_profile` from Account
   - Line 232: Pass `risk_profile` to SignalGenerator

**Total Changes:** 4 files, ~20 lines of code

## Testing Plan

### 1. Verify risk_profile is loaded
```python
from models import Account
from database import ScopedSession

db = ScopedSession()
account = db.query(Account).first()
print(f"Risk Profile: {getattr(account, 'risk_profile', 'NOT SET')}")
```

### 2. Monitor BTCUSD signal generation
```bash
docker logs ngtradingbot_workers --tail 500 -f | grep -i "btcusd"
```

**Expected Log Output (AGGRESSIVE):**
```
BTCUSD H1 Market: RANGING (50%) - Signals: 5 total, 5 after regime filter
AGGRESSIVE: Included HEIKEN_ASHI_TREND (trend-following in ranging market)
AGGRESSIVE: Included SUPERTREND (trend-following in ranging market)
AGGRESSIVE: Included ICHIMOKU (trend-following in ranging market)
```

### 3. Check signal database
```sql
SELECT symbol, timeframe, signal_type, confidence, status, created_at
FROM trading_signals
WHERE symbol = 'BTCUSD' AND status = 'active'
ORDER BY created_at DESC;
```

## Deployment Steps

1. ✅ Code changes committed
2. ⏳ Rebuild Docker containers: `docker compose build --no-cache server workers`
3. ⏳ Restart containers: `docker compose up -d`
4. ⏳ Monitor logs for 5 minutes
5. ⏳ Verify BTCUSD signals are being generated
6. ⏳ Monitor for 24 hours for stability

## Rollback Plan

If aggressive mode creates too many bad signals:

```sql
UPDATE accounts SET risk_profile = 'normal' WHERE id = 1;
```

Then restart workers:
```bash
docker compose restart workers
```

## Performance Expectations

**BTCUSD in RANGING market (50% strength):**

| Mode | Signals/Hour | Win Rate (estimated) | Trades/Day |
|------|--------------|----------------------|------------|
| Moderate | 0-2 | 80-90% | 0-6 |
| Normal | 2-4 | 70-75% | 6-12 |
| Aggressive | 6-10 | 60-70% | 18-30 |

**Note:** Actual performance depends on market conditions and will be tracked via `ai_decision_log`.

## Related Documentation

- [BTCUSD_NO_SIGNALS_ANALYSIS.md](BTCUSD_NO_SIGNALS_ANALYSIS.md) - Original problem analysis
- [COMPREHENSIVE_BOT_AUDIT_2025.md](COMPREHENSIVE_BOT_AUDIT_2025.md) - Full system audit

## Date
2025-10-25 14:30 UTC
