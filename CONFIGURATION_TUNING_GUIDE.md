# Configuration Tuning Guide for ngTradingBot

This guide helps you optimize the newly configurable parameters based on your specific trading conditions and performance goals.

---

## 1. BUY Signal Advantage (Consensus Requirement)

**Location:** `signal_generator.py:205`
**Default:** `BUY_SIGNAL_ADVANTAGE = 2`

### What It Does
Controls how many MORE confirming signals a BUY needs compared to SELL to be generated.

### Settings Guide

| Value | Meaning | When to Use |
|-------|---------|-------------|
| **0** | No bias - simple majority for both BUY/SELL | Markets with no directional bias, balanced volatility |
| **1** | BUY needs 1 extra confirming signal | Slight market downward bias, normal conditions |
| **2** | BUY needs 2 extra confirming signals (current) | Strong downward bias, want higher quality BUYs |
| **3+** | BUY needs 3+ extra signals | Extreme bear market, very selective on BUYs |

### How to Tune

1. **Run Backtests:**
   ```bash
   # Test with no bias
   # Edit signal_generator.py: BUY_SIGNAL_ADVANTAGE = 0
   python backtesting_engine.py --start 2025-01-01 --end 2025-10-01

   # Test with slight bias
   # Edit signal_generator.py: BUY_SIGNAL_ADVANTAGE = 1
   python backtesting_engine.py --start 2025-01-01 --end 2025-10-01

   # Test with current bias
   # Edit signal_generator.py: BUY_SIGNAL_ADVANTAGE = 2
   python backtesting_engine.py --start 2025-01-01 --end 2025-10-01
   ```

2. **Compare Metrics:**
   - BUY signal count
   - BUY win rate
   - BUY profit factor
   - Total return (BUY + SELL combined)

3. **Decision Matrix:**
   - If BUY win rate ≥ SELL win rate → Reduce to 0 or 1
   - If BUY win rate 5-10% below SELL → Keep at 1 or 2
   - If BUY win rate >10% below SELL → Increase to 3

### Example Analysis
```
BUY_SIGNAL_ADVANTAGE = 0
  BUY:  100 signals, 45% WR, 0.9 PF
  SELL: 120 signals, 52% WR, 1.3 PF
  → BUY underperforming - increase to 1

BUY_SIGNAL_ADVANTAGE = 1
  BUY:  75 signals, 50% WR, 1.1 PF
  SELL: 120 signals, 52% WR, 1.3 PF
  → BUY improved but still slightly behind - keep at 1

BUY_SIGNAL_ADVANTAGE = 2
  BUY:  50 signals, 55% WR, 1.4 PF
  SELL: 120 signals, 52% WR, 1.3 PF
  → BUY now outperforming but too few signals - reduce to 1
```

**Optimal:** Value where BUY signals are selective enough to maintain quality, but not so restrictive that you miss good opportunities.

---

## 2. BUY Confidence Penalty

**Location:** `signal_generator.py:360`
**Default:** `BUY_CONFIDENCE_PENALTY = 3.0`

### What It Does
Reduces BUY signal confidence by X percentage points before comparing to thresholds.

### Settings Guide

| Value | Effect | When to Use |
|-------|--------|-------------|
| **0.0** | No penalty - treat BUY/SELL equally | BUY performance equals SELL performance |
| **1.5** | Slight penalty (-1.5%) | BUY slightly underperforms SELL |
| **3.0** | Moderate penalty (-3%) - current | BUY moderately underperforms SELL |
| **5.0** | Strong penalty (-5%) | BUY significantly underperforms SELL |

### How to Tune

1. **Analyze Current Performance:**
   ```sql
   SELECT
     direction,
     COUNT(*) as trades,
     AVG(CASE WHEN profit > 0 THEN 1 ELSE 0 END) * 100 as win_rate,
     SUM(profit) as total_profit
   FROM trades
   WHERE close_time >= '2025-09-01'
   GROUP BY direction;
   ```

2. **Calculate Performance Gap:**
   ```
   Gap = SELL Win Rate - BUY Win Rate

   If Gap = 0-3%   → Penalty = 0.0 (no penalty needed)
   If Gap = 3-6%   → Penalty = 1.5 (slight penalty)
   If Gap = 6-10%  → Penalty = 3.0 (moderate penalty - current)
   If Gap = 10%+   → Penalty = 5.0 (strong penalty)
   ```

3. **Test Impact:**
   - Measure: How many BUY signals drop below auto-trade threshold due to penalty
   - Goal: Filter out worst 20-30% of BUY signals while keeping good ones

### Example Scenarios

**Scenario A: Balanced Performance**
```
BUY:  52% WR, 1.2 PF
SELL: 54% WR, 1.3 PF
Gap:  2%
→ Set BUY_CONFIDENCE_PENALTY = 0.0
```

**Scenario B: Moderate Underperformance**
```
BUY:  45% WR, 0.9 PF
SELL: 53% WR, 1.4 PF
Gap:  8%
→ Set BUY_CONFIDENCE_PENALTY = 3.0 (current)
```

**Scenario C: Severe Underperformance**
```
BUY:  38% WR, 0.7 PF
SELL: 55% WR, 1.5 PF
Gap:  17%
→ Set BUY_CONFIDENCE_PENALTY = 5.0
```

---

## 3. Signal Staleness Threshold

**Location:** `auto_trader.py:511`
**Default:** `MAX_SIGNAL_AGE_SECONDS = 300` (5 minutes)

### What It Does
Rejects signals older than X seconds to prevent trading on outdated market conditions.

### Settings Guide

| Value | Meaning | When to Use |
|-------|---------|-------------|
| **60** | 1 minute | Scalping, M1/M5 timeframes, high volatility |
| **180** | 3 minutes | M15 timeframe, normal volatility |
| **300** | 5 minutes (current) | H1 timeframe, balanced approach |
| **600** | 10 minutes | H4/D1 timeframes, low volatility |

### How to Tune

1. **Match to Timeframe:**
   ```python
   # Scalping (M1, M5)
   MAX_SIGNAL_AGE_SECONDS = 60

   # Intraday (M15, H1)
   MAX_SIGNAL_AGE_SECONDS = 300

   # Swing Trading (H4, D1)
   MAX_SIGNAL_AGE_SECONDS = 600
   ```

2. **Monitor Rejection Rate:**
   ```bash
   # Check how many signals are rejected due to staleness
   grep "Signal too old" /var/log/ngTradingBot/auto_trader.log | wc -l
   ```

3. **Adjust Based on System Load:**
   - If many signals rejected → Increase threshold OR optimize signal generation speed
   - If no signals rejected → Decrease threshold for fresher entries

---

## 4. Circuit Breaker Threshold

**Location:** `auto_trader.py:1455`
**Default:** `CIRCUIT_BREAKER_THRESHOLD = 5`

### What It Does
Number of consecutive command failures before auto-trading shuts down.

### Settings Guide

| Value | Sensitivity | When to Use |
|-------|-------------|-------------|
| **3** | High (sensitive) | Unreliable connection, want quick shutdown |
| **5** | Moderate (current) | Normal connection reliability |
| **7** | Low (tolerant) | Stable connection, allow more retries |
| **10** | Very low | Extremely stable setup, rarely fails |

### How to Tune

1. **Monitor Your Connection:**
   ```bash
   # Check command failure rate over last 7 days
   grep "Command.*FAILED" /var/log/ngTradingBot/auto_trader.log | wc -l
   grep "Command.*executed successfully" /var/log/ngTradingBot/auto_trader.log | wc -l
   ```

2. **Calculate Failure Rate:**
   ```
   Failure Rate = Failed / (Failed + Successful)

   If Rate < 1%  → Threshold = 7-10 (very tolerant)
   If Rate 1-3%  → Threshold = 5 (current)
   If Rate 3-5%  → Threshold = 3 (sensitive)
   If Rate > 5%  → Fix connection issues first!
   ```

3. **Consider Your Risk Tolerance:**
   - **Conservative:** Set to 3 (shut down quickly on issues)
   - **Balanced:** Set to 5 (current default)
   - **Aggressive:** Set to 7 (tolerate more failures)

---

## 5. Circuit Breaker Cooldown

**Location:** `auto_trader.py:1456`
**Default:** `CIRCUIT_BREAKER_COOLDOWN_MINUTES = 5`

### What It Does
How long to wait before auto-resuming trading after circuit breaker trips.

### Settings Guide

| Value | Meaning | When to Use |
|-------|---------|-------------|
| **2** | 2 minutes | Quick recovery, stable systems |
| **5** | 5 minutes (current) | Balanced approach |
| **10** | 10 minutes | Give more time for issue resolution |
| **30** | 30 minutes | Conservative, manual intervention preferred |

### How to Tune

1. **Match to Problem Resolution Time:**
   - Network glitch: 2-5 minutes
   - MT5 restart: 5-10 minutes
   - Server issues: 10-30 minutes

2. **Consider Trading Hours:**
   - During active trading hours → Shorter cooldown (2-5 min)
   - During off-hours → Longer cooldown (10-30 min)

3. **Risk Management:**
   - If you want manual review before resuming → Set to 30+ minutes
   - If you trust auto-recovery → Keep at 5 minutes

---

## Recommended Configuration Sets

### Conservative (Quality over Quantity)
```python
# signal_generator.py
BUY_SIGNAL_ADVANTAGE = 2          # Require 2 extra BUY signals
BUY_CONFIDENCE_PENALTY = 5.0      # Strong penalty for BUY

# auto_trader.py
MAX_SIGNAL_AGE_SECONDS = 180      # 3 minute max age
CIRCUIT_BREAKER_THRESHOLD = 3     # Quick shutdown on issues
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 10  # Wait before resuming
```
**Use when:** Account preservation is priority, learning phase, unstable connection

---

### Balanced (Current Defaults)
```python
# signal_generator.py
BUY_SIGNAL_ADVANTAGE = 2          # Moderate BUY selectivity
BUY_CONFIDENCE_PENALTY = 3.0      # Moderate BUY penalty

# auto_trader.py
MAX_SIGNAL_AGE_SECONDS = 300      # 5 minute max age
CIRCUIT_BREAKER_THRESHOLD = 5     # Tolerant of minor issues
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 5   # Quick recovery
```
**Use when:** Normal trading conditions, established system

---

### Aggressive (More Trades)
```python
# signal_generator.py
BUY_SIGNAL_ADVANTAGE = 0          # No BUY bias
BUY_CONFIDENCE_PENALTY = 0.0      # No BUY penalty

# auto_trader.py
MAX_SIGNAL_AGE_SECONDS = 600      # 10 minute max age
CIRCUIT_BREAKER_THRESHOLD = 7     # Very tolerant
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 2   # Quick recovery
```
**Use when:** BUY performance equals SELL, stable connection, growth phase

---

## Testing Workflow

### Step 1: Establish Baseline
```bash
# Run with current settings for 1 week
# Record: total trades, win rate, profit factor, max drawdown
```

### Step 2: Test One Variable at a Time
```bash
# Week 1: Test BUY_SIGNAL_ADVANTAGE (0, 1, 2)
# Week 2: Test BUY_CONFIDENCE_PENALTY (0, 1.5, 3.0, 5.0)
# Week 3: Test CIRCUIT_BREAKER_THRESHOLD (3, 5, 7)
```

### Step 3: Measure Impact
```sql
-- Compare performance metrics
SELECT
  configuration,
  COUNT(*) as trades,
  AVG(CASE WHEN profit > 0 THEN 1 ELSE 0 END) * 100 as win_rate,
  SUM(profit) / SUM(ABS(CASE WHEN profit < 0 THEN profit ELSE 0 END)) as profit_factor,
  MAX(daily_drawdown) as max_dd
FROM backtest_results
GROUP BY configuration;
```

### Step 4: Choose Optimal Settings
- Prioritize: Win rate > Profit factor > Trade count
- Ensure max drawdown stays within risk tolerance
- Validate performance across different market conditions

---

## Monitoring Dashboard Queries

### BUY vs SELL Performance (Last 30 Days)
```sql
SELECT
  direction,
  COUNT(*) as trades,
  ROUND(AVG(CASE WHEN profit > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate_pct,
  ROUND(SUM(profit), 2) as total_profit,
  ROUND(SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) /
        NULLIF(ABS(SUM(CASE WHEN profit < 0 THEN profit ELSE 0 END)), 0), 2) as profit_factor
FROM trades
WHERE close_time >= NOW() - INTERVAL '30 days'
GROUP BY direction
ORDER BY direction;
```

### Signal Staleness Rejection Rate
```sql
-- Check auto_trader.log for rejections
grep "Signal too old" auto_trader.log | wc -l
```

### Circuit Breaker Trips
```sql
SELECT
  created_at,
  decision_type,
  primary_reason,
  detailed_reasoning
FROM ai_decision_log
WHERE decision_type = 'CIRCUIT_BREAKER'
ORDER BY created_at DESC
LIMIT 10;
```

---

## Need Help?

If you're unsure which settings to use:

1. **Start with defaults** (Balanced configuration)
2. **Run for 2 weeks** minimum to gather data
3. **Analyze BUY vs SELL performance** gap
4. **Adjust ONE parameter** at a time
5. **Test for another 2 weeks**
6. **Repeat** until optimal

---

**Last Updated:** 2025-10-20
**Maintained by:** ngTradingBot Team
