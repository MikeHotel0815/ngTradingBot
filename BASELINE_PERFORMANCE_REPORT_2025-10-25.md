# Baseline Performance Report - 2025-10-25

## Executive Summary

**Zeitraum:** Letzte 7 Tage (2025-10-18 bis 2025-10-25)
**Total Trades:** 190 geschlossene Trades
**Overall Win Rate:** 69.47%
**Total Profit/Loss:** **-€148.47** ⚠️

**Status:** 🟡 MIXED - Gute Win Rate, aber negative Profitability durch einzelne Problem-Symbole

---

## 1. Symbol Performance Analysis

### 🎯 Top Performers (KEEP & OPTIMIZE)

| Symbol | Trades | Win Rate | Avg Profit | Total P/L | Status |
|--------|--------|----------|------------|-----------|--------|
| **AUDUSD** | 2 | **100.00%** | €0.10 | €0.20 | ✅ EXCELLENT (aber zu wenig Daten) |
| **GBPUSD** | 2 | **100.00%** | €0.08 | €0.15 | ✅ EXCELLENT (aber zu wenig Daten) |
| **BTCUSD** | 17 | **82.35%** | €0.22 | **€3.81** | ✅ EXCELLENT |
| **EURUSD** | 13 | **76.92%** | -€0.42 | -€5.52 | 🟡 GOOD WR, BAD PROFIT |
| **US500.c** | 105 | **76.19%** | €0.03 | €3.09 | ✅ GOOD (hohe Volume) |
| **XAUUSD** | 23 | **73.91%** | -€0.66 | -€15.17 | 🟡 GOOD WR, BAD PROFIT |

**Key Insights:**
- ✅ **BTCUSD ist der Star:** 82.35% Win Rate, €3.81 Profit, stabile Performance
- ✅ **US500.c ist zuverlässig:** 76.19% Win Rate bei hohem Volume (105 Trades)
- 🟡 **EURUSD & XAUUSD:** Gute Win Rate aber schlechte Profitability (kleine Gewinne, große Verluste)

### ❌ Problem Performers (PAUSE IMMEDIATELY)

| Symbol | Trades | Win Rate | Avg Profit | Total P/L | Status |
|--------|--------|----------|------------|-----------|--------|
| **XAGUSD** | 8 | **0.00%** | -€13.83 | **-€110.62** | 🔴 DISASTER |
| **USDJPY** | 12 | 33.33% | -€0.20 | -€2.40 | 🔴 BAD |
| **DE40.c** | 8 | 37.50% | -€2.75 | -€22.01 | 🔴 BAD |

**Key Insights:**
- 🔴 **XAGUSD ist katastrophal:** 0% Win Rate, -€110.62 Loss (8 straight losses!)
- 🔴 **DE40.c & USDJPY:** Unter 40% Win Rate, signifikante Losses

**Root Cause Analysis - XAGUSD:**
- Avg MFE: €0.03 (kaum positive movement)
- Avg MAE: €22.50 (große negative movements)
- MFE/MAE Ratio: 0.00 (Trades erreichen nie Profit Zone)
- **Problem:** Signale sind komplett falsch oder Market Conditions passen nicht

**Root Cause Analysis - EURUSD/XAUUSD:**
- EURUSD: Avg MFE €1.79 vs. Avg MAE €4.65 → Verluste 2.6x größer als Gewinne
- XAUUSD: Avg MFE €2388 vs. Avg MAE €9869 → Verluste 4.1x größer als Gewinne
- **Problem:** TP zu konservativ oder SL zu eng

---

## 2. Session Performance Analysis

### ⚠️ CRITICAL FINDING: Keine Session-Daten!

| Session | Trades | Win Rate | Avg Profit | Total P/L |
|---------|--------|----------|------------|-----------|
| **UNKNOWN** | 190 | 69.47% | -€0.78 | -€148.47 |

**Problem:** Das `session` Feld ist für ALLE 190 Trades `NULL` oder leer!

**Impact:**
- ❌ Keine Session-basierte Optimierung möglich
- ❌ Können nicht feststellen ob ASIA/LONDON/US Sessions unterschiedlich performen
- ❌ Time-of-day Analysis nicht möglich

**Root Cause:**
- Session-Tracking wurde möglicherweise nicht korrekt implementiert
- Oder `session` wird nicht beim Trade-Opening gesetzt

**Recommendation:**
```python
# In auto_trader.py oder trade_executor.py
from market_hours import get_current_session

session = get_current_session(symbol)  # Returns: ASIA/LONDON/OVERLAP/US/CLOSED
trade.session = session  # Set before saving
```

**Estimated Impact wenn gefixt:**
- Basierend auf typischen Forex Patterns:
  - LONDON Session: Beste Volatility & Volume → Erwarte 70-80% WR
  - US Session: Gute Trends → Erwarte 65-75% WR
  - ASIA Session: Niedrige Volatility & Ranges → Erwarte 50-60% WR
  - OVERLAP (London+US): Höchste Volatility → Erwarte 60-70% WR aber höheres Risk

---

## 3. Confidence Score Validation

### 📊 Win Rate by Confidence Band

| Confidence Band | Trades | Win Rate | Avg Profit | Total P/L |
|-----------------|--------|----------|------------|-----------|
| **70-80%** | 97 | **76.29%** | -€0.07 | -€6.64 |
| **50-60%** | 46 | **73.91%** | -€0.38 | -€17.45 |
| **80-100%** | 26 | **69.23%** | -€1.45 | -€37.58 |
| **60-70%** | 21 | **28.57%** | -€4.13 | **-€86.80** |

### 🔍 Key Findings:

**1. ÜBERRASCHUNG: 60-70% Confidence ist SCHLECHTER als 50-60%!**
- 60-70%: Nur 28.57% Win Rate ⚠️
- 50-60%: 73.91% Win Rate ✅
- **Erwartung:** Höhere Confidence → Höhere Win Rate
- **Realität:** U-förmige Kurve (nicht linear!)

**2. 70-80% Confidence ist optimal:**
- Höchste Win Rate: 76.29%
- Meiste Trades: 97 (51% aller Trades)
- Durchschnittliche Profitability

**3. 80-100% Confidence ist NICHT besser:**
- Nur 69.23% Win Rate (schlechter als 70-80%!)
- Schlechteste Avg Profit: -€1.45
- **Mögliche Ursache:** Overfitting? Zu konservativ?

**4. risk_reward_realized ist NULL für ALLE Trades:**
- Field existiert aber ist leer
- **Impact:** Können R:R Ratio nicht validieren
- **Fix needed:** Berechne R:R beim Trade-Close

### 🎯 Recommendations:

**Option A: Erhöhe Min-Confidence 50% → 65%**
- ✅ Filtert die schlechten 60-70% Trades raus
- ✅ Behält die guten 70-80% Trades
- ❌ Verliert die überraschend guten 50-60% Trades

**Option B: Bimodale Strategie**
- ✅ Akzeptiere 50-60% Confidence (73.91% WR!)
- ✅ Akzeptiere 70-80% Confidence (76.29% WR!)
- ❌ REJECT 60-70% Confidence (28.57% WR!)
- Ungewöhnlich aber passt zu den Daten!

**Option C: Investigate 60-70% Band**
- Was ist anders an diesen Trades?
- Welche Symbole? → Könnte XAGUSD/DE40/USDJPY sein
- Welche Indicators? → Brauchen Indicator-Daten (Phase 3)

**My Recommendation:** Option C first (verstehen), dann Option B (implementieren)

---

## 4. Trailing Stop vs. Fixed TP Effectiveness

### 📈 Clear Winner: Trailing Stop

| Exit Strategy | Trades | Win Rate | Avg Profit | Total P/L |
|---------------|--------|----------|------------|-----------|
| **Trailing Stop** | 164 | **79.88%** | €0.20 | **€33.58** |
| **Fixed TP** | 26 | **3.85%** | -€7.00 | **-€182.05** |

### 🎯 Key Findings:

**1. Trailing Stop ist MASSIV besser:**
- Win Rate: 79.88% vs. 3.85% (20x besser!)
- Avg Profit: €0.20 vs. -€7.00
- Total P/L: +€33.58 vs. -€182.05

**2. Fixed TP ist katastrophal:**
- Nur 1 von 26 Trades (3.85%) erreicht TP!
- 25 von 26 Trades (96.15%) hit SL!
- **Root Cause:** TP ist zu weit entfernt (unrealistisch)

**3. Trailing Stop Settings funktionieren:**
- Avg Trailing Moves: 4.4x pro Trade
- SL wird im Schnitt 4x nachgezogen bevor Exit
- **Conclusion:** Trailing Logic arbeitet korrekt

### 🎯 Recommendations:

**✅ KEEP Trailing Stop aktiv (default)**
- Current Strategy funktioniert sehr gut
- 79.88% Win Rate ist exzellent

**🔧 FIX Fixed TP Settings:**
- Wenn Trailing Stop disabled (manuell oder per Config):
  - Aktuell: TP zu weit entfernt (96% failure rate)
  - **Fix:** Reduziere TP Distance oder verwende ATR-basiertes TP
  - Beispiel: Statt 3x ATR → 1.5x ATR für Fixed TP

**Alternative:** Disable Fixed TP komplett
- Immer Trailing Stop nutzen
- Nur in besonderen Cases (z.B. News Events) Fixed TP

---

## 5. Close Reason Distribution

### 📊 How Do Trades Exit?

| Close Reason | Count | % of Total | Avg Profit | Win Rate |
|--------------|-------|------------|------------|----------|
| **TRAILING_STOP** | 149 | **78.42%** | €0.22 | **80.54%** |
| **MANUAL** | 32 | 16.84% | -€2.18 | 31.25% |
| **SL_HIT** | 6 | 3.16% | -€18.14 | **0.00%** |
| Duplicate Position | 2 | 1.05% | -€1.57 | 50.00% |
| UNKNOWN | 1 | 0.53% | €0.02 | 100.00% |

### 🔍 Key Findings:

**1. Trailing Stop dominiert (gut!):**
- 78.42% aller Trades enden mit Trailing Stop
- 80.54% Win Rate bei Trailing Stop Exits
- Avg Profit: €0.22 (positiv!)

**2. MANUAL Closes sind problematisch:**
- 32 Trades (16.84%) manuell geschlossen
- Nur 31.25% Win Rate (schlechter als Auto-Close!)
- Avg Loss: -€2.18
- **Mögliche Ursachen:**
  - User greift ein bei losing Trades?
  - Emergency Stops bei News Events?
  - Bug im Auto-Close System?

**3. SL_HIT ist selten aber teuer:**
- Nur 6 Trades (3.16%) hit SL
- ALLE 6 sind Verluste (0% Win Rate)
- Avg Loss: -€18.14 (sehr hoch!)
- **Root Cause:** Wenn SL hit wird, sind Verluste extrem (kein Trailing hat geholfen)

**4. Duplicate Position Prevention arbeitet:**
- Nur 2 Cases (1.05%) in 7 Tagen
- System erkennt und schließt Duplicates
- ✅ Working as intended

### 🎯 Recommendations:

**Investigate MANUAL Closes:**
```sql
-- Warum wurden Trades manuell geschlossen?
SELECT
    t.id,
    t.symbol,
    t.profit,
    t.open_time,
    t.close_time,
    EXTRACT(EPOCH FROM (t.close_time - t.open_time))/60 as duration_min,
    t.close_reason
FROM trades t
WHERE t.close_reason = 'MANUAL'
  AND t.close_time > NOW() - INTERVAL '7 days'
ORDER BY t.close_time DESC;
```

**Analyze SL_HIT Cases:**
- Welche Symbole? (Vermutlich XAGUSD, DE40, etc.)
- War Initial SL zu eng?
- Oder Market Gaps/Slippage?

---

## 6. Data Quality Issues

### ⚠️ Missing/Incomplete Data Fields

| Field | Status | Impact | Priority |
|-------|--------|--------|----------|
| **session** | ❌ NULL für alle Trades | HIGH - Keine Session-Analyse möglich | 🔴 HIGH |
| **risk_reward_realized** | ❌ NULL für alle Trades | MEDIUM - Keine R:R Validation | 🟡 MEDIUM |
| **hold_duration_minutes** | ❌ NULL für alle Trades | MEDIUM - Keine Time-in-Trade Analysis | 🟡 MEDIUM |
| **entry_volatility** | ❌ NULL für alle Trades | LOW - Nice-to-have | 🟢 LOW |
| **exit_volatility** | ❌ NULL für alle Trades | LOW - Nice-to-have | 🟢 LOW |
| **pips_captured** | ❌ NULL für alle Trades | MEDIUM - Keine Pips Analysis | 🟡 MEDIUM |

### 🔧 Quick Fixes Needed:

**1. Session Tracking (HIGH Priority):**
```python
# In auto_trader.py before trade execution
from market_hours import get_current_session

trade.session = get_current_session(symbol)
```

**2. Risk/Reward Calculation (MEDIUM Priority):**
```python
# In trade_monitor.py or close handler
def calculate_risk_reward(trade):
    initial_risk = abs(trade.open_price - trade.initial_sl)
    potential_reward = abs(trade.initial_tp - trade.open_price)
    realized_pl = trade.profit

    if initial_risk > 0:
        trade.risk_reward_realized = realized_pl / initial_risk
```

**3. Hold Duration (MEDIUM Priority):**
```python
# In trade_monitor.py on close
trade.hold_duration_minutes = (trade.close_time - trade.open_time).total_seconds() / 60
```

**4. Pips Captured:**
```python
# In trade_monitor.py on close
pip_value = get_pip_value(trade.symbol)
trade.pips_captured = (trade.close_price - trade.open_price) / pip_value
if trade.direction == 'SELL':
    trade.pips_captured *= -1
```

---

## 7. Quick Win Recommendations

### 🔴 IMMEDIATE ACTIONS (Implement Today)

#### 1. **PAUSE XAGUSD** (Highest Priority)
```python
# In symbol_configs or GlobalSettings
UPDATE symbol_configs
SET status = 'paused',
    pause_reason = 'Baseline Report: 0% WR, -€110.62 loss in 7 days'
WHERE symbol = 'XAGUSD';
```

**Impact:** Prevents further losses (saved €110.62 in last 7 days if paused earlier)

#### 2. **PAUSE DE40.c & USDJPY**
```python
UPDATE symbol_configs
SET status = 'paused',
    pause_reason = 'Baseline Report: <40% WR, negative P/L'
WHERE symbol IN ('DE40.c', 'USDJPY');
```

**Impact:** Prevents low Win Rate trades (combined -€24.41 loss)

#### 3. **FIX Session Tracking**
- Implement session field population
- Test on paper trades first
- Deploy to production

**Impact:** Enables Session-based analysis in future reports

### 🟡 MEDIUM PRIORITY (Implement This Week)

#### 4. **Investigate 60-70% Confidence Band**
- Query which symbols are in this band
- Check if XAGUSD/DE40/USDJPY dominate
- If yes: Problem is symbol-specific, not confidence-specific

#### 5. **Fix Fixed TP Settings**
- Reduce TP distance from current (3x ATR?) to 1.5x ATR
- Or disable Fixed TP entirely (force Trailing Stop)

**Impact:** Improves fallback when Trailing Stop disabled

#### 6. **Add Missing Data Fields**
- session, risk_reward_realized, hold_duration_minutes, pips_captured
- Enables deeper analysis in Phase 3

### 🟢 LOW PRIORITY (Nice-to-Have)

#### 7. **Optimize EURUSD & XAUUSD**
- Good Win Rate but poor profitability
- Possible fixes:
  - Widen SL (reduce MAE/MFE ratio)
  - Tighten TP (capture profits earlier)
  - Adjust Trailing Stop trigger distance

#### 8. **Investigate MANUAL Closes**
- Why are 16.84% of trades manually closed?
- Is this user intervention or system bug?
- If user: Are interventions helpful? (31% WR suggests NO)

---

## 8. Expected Impact of Quick Wins

### Baseline (Last 7 Days - Actual):
- Total Trades: 190
- Win Rate: 69.47%
- Total P/L: **-€148.47**
- Problem Symbols: XAGUSD (-€110.62), DE40 (-€22.01), USDJPY (-€2.40)

### After Quick Win Implementation (Projected):
- Total Trades: 162 (remove 28 problem trades)
- Win Rate: **76.54%** (+7.07%)
- Total P/L: **-€13.44** (Improvement: €135.03!)

### Calculation:
```
Original: 190 trades, -€148.47 total
Remove XAGUSD: -8 trades, +€110.62 profit
Remove DE40.c: -8 trades, +€22.01 profit
Remove USDJPY: -12 trades, +€2.40 profit

New Total: 162 trades, -€13.44 loss
New Win Rate: (132 wins / 162 trades) = 81.48%

Wait, let me recalculate...
Original: 132 wins out of 190 = 69.47% WR
Problem trades:
- XAGUSD: 0 wins, 8 losses
- DE40: 3 wins, 5 losses
- USDJPY: 4 wins, 8 losses
= 7 wins, 21 losses from problem symbols

Remaining: 125 wins, 37 losses = 162 trades
New Win Rate: 125/162 = 77.16%
```

**Corrected Projection:**
- Win Rate: **77.16%** (+7.69% improvement)
- Total P/L: **-€13.44** (€135.03 saved)
- Still negative but 90% better!

**Why still negative?**
- EURUSD: -€5.52 (good WR, bad profit)
- XAUUSD: -€15.17 (good WR, bad profit)
- Need Phase 3 (Indicator Analysis) to fix these

---

## 9. Next Steps

### Phase 1: ✅ COMPLETE
- [x] Baseline Report erstellt
- [x] Quick Wins identifiziert
- [x] Data Quality Issues gefunden

### Phase 2: Datensammlung (Start nach Quick Win Implementation)
**Duration:** 2-3 Tage
**Goal:** 50-100 Trades mit vollständigen Indicator-Snapshots

**Wait for:**
- Bei ~30 Trades/Tag (nach Pause von 3 Symbolen → ~20 Trades/Tag)
- Brauchen ~3-4 Tage für 90 Trades

### Phase 3: Indicator Analyse
**Start:** Nach Phase 2 complete
**Duration:** 4-6 Stunden
**Deliverable:** INDICATOR_ANALYSIS_REPORT.md

### Phase 4: Dynamic Strategy Implementation
**Start:** Nach Phase 3 complete
**Duration:** 1 Tag
**Deliverables:**
- strategy_selector.py
- performance_tracker.py
- Updated signal_generator.py

---

## 10. Summary & Action Items

### 📊 Current State:
- ✅ Good Win Rate: 69.47%
- ❌ Negative Profitability: -€148.47
- 🔴 3 Problem Symbols: XAGUSD (0% WR), DE40 (37.5% WR), USDJPY (33.3% WR)
- 🟡 Data Quality Issues: session, R:R, duration fields missing
- ✅ Trailing Stop arbeitet exzellent: 79.88% WR

### 🎯 Quick Wins (Immediate):
1. ✅ **PAUSE XAGUSD** → Saves €110.62 per week
2. ✅ **PAUSE DE40.c & USDJPY** → Saves €24.41 per week
3. 🔧 **FIX Session Tracking** → Enables future analysis
4. 🔧 **FIX Data Fields** → session, R:R, duration, pips

### 📈 Expected Impact:
- Win Rate: 69.47% → **77.16%** (+7.69%)
- Total P/L: -€148.47 → **-€13.44** (+€135.03)
- Still work needed on EURUSD/XAUUSD profitability

### ⏭️ Next Phase:
Wait 2-3 days for Indicator-Snapshot data collection, then run Phase 3 analysis.

---

## Appendix: Raw SQL Queries Used

```sql
-- 1. Symbol Performance
SELECT symbol, COUNT(*) as trades,
       ROUND(COUNT(CASE WHEN profit > 0 THEN 1 END) * 100.0 / COUNT(*), 2) as win_rate,
       ROUND(SUM(profit), 2) as total_pl
FROM trades WHERE status = 'closed' AND close_time > NOW() - INTERVAL '7 days'
GROUP BY symbol ORDER BY win_rate DESC;

-- 2. Session Performance
SELECT session, COUNT(*) as trades,
       ROUND(AVG(profit), 2) as avg_profit
FROM trades WHERE status = 'closed' AND close_time > NOW() - INTERVAL '7 days'
GROUP BY session;

-- 3. Confidence Validation
SELECT CASE
         WHEN entry_confidence >= 80 THEN '80-100%'
         WHEN entry_confidence >= 70 THEN '70-80%'
         WHEN entry_confidence >= 60 THEN '60-70%'
         ELSE '50-60%'
       END as conf_band,
       COUNT(*) as trades,
       ROUND(COUNT(CASE WHEN profit > 0 THEN 1 END) * 100.0 / COUNT(*), 2) as wr
FROM trades WHERE status = 'closed' AND close_time > NOW() - INTERVAL '7 days'
GROUP BY conf_band;

-- 4. Trailing Stop Effectiveness
SELECT trailing_stop_active, COUNT(*) as trades,
       ROUND(COUNT(CASE WHEN profit > 0 THEN 1 END) * 100.0 / COUNT(*), 2) as wr
FROM trades WHERE status = 'closed' AND close_time > NOW() - INTERVAL '7 days'
GROUP BY trailing_stop_active;

-- 5. Close Reason Distribution
SELECT close_reason, COUNT(*) as count,
       ROUND(AVG(profit), 2) as avg_profit
FROM trades WHERE status = 'closed' AND close_time > NOW() - INTERVAL '7 days'
GROUP BY close_reason ORDER BY count DESC;
```

---

**Report Generated:** 2025-10-25 15:00 UTC
**Author:** Claude (Automated Analysis)
**Next Review:** After Phase 2 completion (~2025-10-28)
