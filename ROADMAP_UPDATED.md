# 🗺️ ngTradingBot - AKTUALISIERTE ENTWICKLUNGS-ROADMAP

**Erstellt**: 2025-10-08
**Status**: Production-Ready Preparation
**Ziel**: System auf €5.000-50.000 Live-Kapital vorbereiten

---

## 📊 **AKTUELLE SITUATION**

### ✅ **Was bereits funktioniert**:
- Docker-Container-Architektur (PostgreSQL, Redis, Flask)
- 13 technische Indikatoren (inkl. Ichimoku, VWAP, SuperTrend)
- Market Regime Detection (TRENDING vs RANGING)
- Auto-Disable Mechanismus (Symbols <30% Win-Rate)
- Shadow Trading für disabled Symbols
- Symbol-spezifische Parameter (SL-Multipliers, Break-Even)
- Live Performance Tracking (24h Rolling)
- SuperTrend Dynamic SL
- Dashboard mit Real-time Updates
- Backtest-System (Basis vorhanden)

### ⚠️ **Was fehlt** (Broker-Kritik):
- ❌ Daily Drawdown Protection
- ❌ News/Economic Calendar Filter
- ❌ Correlation Matrix & Exposure Limits
- ❌ Multi-Timeframe Confirmation
- ❌ Historische Daten für Backtesting (2 Jahre)
- ❌ AI Decision Log (User-Transparenz)
- ⚠️ Spread-Adjustment in TP/SL
- ⚠️ Exit-Optimierung (TP zu früh)

---

## 🎯 **NEUE PRIORITÄTEN** (User-Request)

### **1. OHLC Daten-Pipeline** ⭐⭐⭐⭐⭐ HÖCHSTE PRIORITÄT
**Problem**: Kein schneller Zugriff auf historische Daten → Backtest dauert ewig
**Lösung**: TimescaleDB Hypertable mit 2 Jahren OHLC-Daten

**Implementierung**:
- ✅ `historical_data_manager.py` erstellt
- ✅ TimescaleDB Hypertable mit Kompression
- ✅ MT5 Download-Integration
- ✅ Dukascopy Fallback (Forex)
- ✅ CLI Tool für Daten-Management

**Next Steps**:
```bash
# Daten herunterladen (via CLI):
cd /projects/ngTradingBot
python historical_data_manager.py --download \
  --symbols EURUSD GBPUSD USDJPY XAUUSD BTCUSD DE40.c \
  --timeframes M15 H1 H4 D1 \
  --years 2

# Coverage prüfen:
python historical_data_manager.py --coverage
```

**Geschätzter Download-Zeit**: ~15-30 Minuten (abhängig von MT5-Verbindung)
**Speicherbedarf**: ~100-200 MB (mit Kompression)
**Query-Performance**: <100ms für 2 Jahre Daten

---

### **2. AI Decision Log Dashboard** ⭐⭐⭐⭐⭐ HÖCHSTE PRIORITÄT
**Problem**: User sieht nicht, was das System "denkt" → kein Vertrauen
**Lösung**: Transparenz-Dashboard mit allen AI-Entscheidungen

**Implementierung**:
- ✅ `ai_decision_log.py` erstellt
- ✅ PostgreSQL Tabelle `ai_decision_log`
- ✅ API Endpoints (`/api/ai-decisions`)
- ⏳ Dashboard Widget (TODO)
- ⏳ Integration in Auto-Trader (TODO)

**Decision Types**:
- 🔵 TRADE_OPEN: Warum Trade geöffnet/abgelehnt
- 🔴 TRADE_CLOSE: Warum Trade geschlossen
- ⏭️ SIGNAL_SKIP: Warum Signal übersprungen
- ⛔ SYMBOL_DISABLE: Warum Symbol deaktiviert
- ⚠️ RISK_LIMIT: Warum Risk-Limit aktiv
- 🔗 CORRELATION_BLOCK: Warum korreliertes Pair blockiert
- 📰 NEWS_PAUSE: Warum Trading wegen News pausiert
- 📉 DD_LIMIT: Warum Daily Drawdown Limit erreicht
- 🎯 SUPERTREND_SL: Warum SuperTrend SL verwendet
- 📊 MTF_CONFLICT: Warum Multi-Timeframe Konflikt

**Dashboard Features**:
- Real-time Feed der letzten 50 Entscheidungen
- Filter nach Decision Type
- Highlight von "Action Required" Einträgen
- Statistiken (Decisions/hour, by type)

---

## 🔴 **PHASE 1: KRITISCHE RISK-FEATURES** (1-2 Wochen)

### **1.1 Daily Drawdown Protection** 🛡️
**Priorität**: KRITISCH
**Aufwand**: ~4 Stunden
**Impact**: ⭐⭐⭐⭐⭐

**Implementierung**:
```python
# Neues File: daily_drawdown_monitor.py
class DailyDrawdownMonitor:
    def check_drawdown_limit(self, account_id):
        # Track P&L seit Tagesstart (00:00 UTC)
        # Wenn > max_daily_drawdown_percent:
        #   - Auto-Trade DISABLE
        #   - Alert an User (Telegram)
        #   - AI Decision Log: DD_LIMIT
        #   - USER_ACTION_REQUIRED = True
```

**Settings**:
- `max_daily_drawdown_percent`: 5.0%
- `max_daily_drawdown_eur`: 100.00€
- `dd_reset_hour`: 0 (UTC Midnight)

**Integration**:
- Hook in `app.py` bei Trade Close
- Check vor jedem neuen Trade

---

### **1.2 News/Economic Calendar Filter** 📰
**Priorität**: KRITISCH
**Aufwand**: ~8 Stunden
**Impact**: ⭐⭐⭐⭐⭐

**Implementierung**:
```python
# Neues File: economic_calendar.py
class EconomicCalendar:
    def get_upcoming_events(self, minutes=30):
        # Scrape ForexFactory.com
        # Return High-Impact Events in next N minutes

    def is_trading_allowed(self):
        # Check if High-Impact Event in next 15min
        # Return False → Trading PAUSE
```

**Datenquellen** (Priorität):
1. **ForexFactory** (kostenlos, Scraping)
2. Trading Economics API (€50/Monat)
3. Investing.com Calendar

**Settings**:
- `news_pause_before_minutes`: 15
- `news_pause_after_minutes`: 5
- `news_impact_filter`: ['High', 'Medium']

**AI Decision Log**:
- Type: `NEWS_PAUSE`
- Reason: "NFP Release in 10 minutes"
- USER_ACTION_REQUIRED: False

---

### **1.3 Correlation Matrix & Exposure Limits** 🔗
**Priorität**: KRITISCH
**Aufwand**: ~5 Stunden
**Impact**: ⭐⭐⭐⭐

**Implementierung**:
```python
# Neues File: correlation_manager.py
CORRELATIONS = {
    ('EURUSD', 'GBPUSD'): 0.85,  # Stark korreliert
    ('EURUSD', 'USDCHF'): -0.90, # Negativ korreliert
    ('USDJPY', 'EURJPY'): 0.75,
    # ...
}

def check_correlation_exposure(new_symbol, existing_positions):
    for pos in existing_positions:
        corr = get_correlation(new_symbol, pos.symbol)
        if abs(corr) > 0.7 and same_direction:
            if count >= max_correlated_positions:
                return False, "Correlation limit"
    return True, "OK"
```

**Settings**:
- `max_correlated_positions`: 2
- `correlation_threshold`: 0.7

**AI Decision Log**:
- Type: `CORRELATION_BLOCK`
- Reason: "Already 2 EUR pairs open (EURUSD, GBPUSD)"
- USER_ACTION_REQUIRED: False

---

### **1.4 Telegram Bot Integration** 📱
**Priorität**: HOCH
**Aufwand**: ~4 Stunden
**Impact**: ⭐⭐⭐⭐

**Implementierung**:
```python
# Neues File: telegram_bot.py
def send_alert(message, level='INFO'):
    # Send to Telegram
    # Levels: INFO, WARNING, CRITICAL
```

**Alerts**:
- ✅ Trade Opened (+€ potential)
- ✅ Trade Closed (±€ P&L)
- ⛔ Symbol Auto-Disabled
- ⚠️ Daily DD Limit (50%, 75%, 100%)
- 📰 News Pause Active
- 🔗 Correlation Block
- 🚨 Server Error/Restart

---

## 🟡 **PHASE 2: PERFORMANCE-OPTIMIERUNG** (2-4 Wochen)

### **2.1 Multi-Timeframe Confirmation** 📊
**Priorität**: HOCH
**Aufwand**: ~8 Stunden
**Impact**: ⭐⭐⭐⭐⭐ (Erwartet: +10-15% Win-Rate!)

**Implementierung**:
```python
# In technical_indicators.py:
def get_higher_timeframe_trend(symbol, entry_timeframe):
    # H1 → check H4
    # M15 → check H1

    # Indicators für Trend:
    # - ADX > 25 (strong trend)
    # - Ichimoku Cloud (price above/below)
    # - SuperTrend direction
    # - EMA 200 (price above/below)

    if 3/4 indicators agree:
        return 'BULLISH' or 'BEARISH'
    else:
        return 'UNCLEAR'

# In auto_trader.py:
def check_mtf_confirmation(signal):
    higher_trend = get_higher_timeframe_trend(...)

    if signal.type == 'BUY' and higher_trend != 'BULLISH':
        return False, "MTF Conflict: H1 BUY vs H4 BEARISH"

    return True, "MTF Confirmed"
```

**Settings**:
- `require_mtf_confirmation`: True
- `mtf_agreement_threshold`: 0.75 (3/4 indicators)

**AI Decision Log**:
- Type: `MTF_CONFLICT`
- Reason: "H1 BUY signal rejected - H4 shows BEARISH trend"

---

### **2.2 Exit-Optimierung (Partial Close)** 🎯
**Priorität**: MITTEL
**Aufwand**: ~6 Stunden
**Impact**: ⭐⭐⭐⭐

**Problem**: Wins nur 8.9 Min, Losses 83.6 Min → TP zu früh!

**Lösung A: Partial Close**:
```python
# Bei 1:1 RR erreicht:
- Close 50% der Position (Lock Profit)
- Move SL to Break-Even
- Lasse 50% mit Trailing Stop laufen
```

**Lösung B: Dynamischer TP**:
```python
# Statt fixem TP:
tp_distance = sl_distance * risk_reward_ratio
# risk_reward_ratio: 2.0 (1:2) oder 3.0 (1:3)
```

**Settings**:
- `partial_close_enabled`: True
- `partial_close_percent`: 50
- `partial_close_at_rr`: 1.0 (bei 1:1 RR)
- `risk_reward_ratio`: 2.0

---

### **2.3 Spread-Adjustment** 💰
**Priorität**: MITTEL
**Aufwand**: ~3 Stunden
**Impact**: ⭐⭐⭐

**Implementierung**:
```python
def adjust_for_spread(signal):
    spread = get_current_spread(signal.symbol)

    if signal.type == 'BUY':
        signal.entry_price += spread  # Entry bei ASK
        signal.tp += spread  # TP weiter weg
    else:
        signal.entry_price -= spread  # Entry bei BID
        signal.tp -= spread
```

---

## 🟢 **PHASE 3: BACKTEST & VALIDATION** (2-3 Wochen)

### **3.1 Historische Daten Download** 💾
**Priorität**: HÖCHSTE (bereits implementiert!)
**Aufwand**: ~1 Stunde (nur Download-Zeit)
**Impact**: ⭐⭐⭐⭐⭐

**CLI Commands**:
```bash
# Download 2 Jahre Daten:
python historical_data_manager.py --download \
  --symbols EURUSD GBPUSD USDJPY XAUUSD BTCUSD DE40.c \
  --timeframes M15 H1 H4 D1 \
  --years 2

# Check Coverage:
python historical_data_manager.py --coverage
```

**Expected Output**:
```
Symbol     TF    First Date           Last Date            Bars        Days
EURUSD     H1    2023-10-08 00:00    2025-10-08 23:00     17,520      730
EURUSD     H4    2023-10-08 00:00    2025-10-08 20:00     4,380       730
...
```

---

### **3.2 Backtest Report Verbesserung** 📈
**Priorität**: MITTEL
**Aufwand**: ~8 Stunden
**Impact**: ⭐⭐⭐⭐

**Neue Metriken**:
- Sharpe Ratio
- Sortino Ratio
- Max Drawdown (absolut & %)
- Recovery Factor
- Profit Factor
- Avg Win vs Avg Loss
- Win-Rate pro Symbol
- Best/Worst Month
- Monte Carlo Simulation (1000 Runs)

**Export Formats**:
- PDF Report mit Charts
- Excel Export
- JSON für API

---

## 📋 **ZUSAMMENFASSUNG - EMPFOHLENE REIHENFOLGE**

### **🔴 SOFORT (HEUTE/MORGEN)**:
1. ✅ **OHLC Daten herunterladen** (~30 Min)
   ```bash
   cd /projects/ngTradingBot
   python historical_data_manager.py --download --years 2
   ```

2. ⏳ **AI Decision Log Dashboard Widget** (~3h)
   - Dashboard HTML erstellen
   - Integration in Auto-Trader
   - Testing

---

### **🔴 WOCHE 1-2: KRITISCHE RISK-FEATURES**:
3. **Daily Drawdown Protection** (~4h)
4. **News Filter** (~8h)
5. **Correlation Limits** (~5h)
6. **Telegram Alerts** (~4h)

**Total**: ~21 Stunden
**Ergebnis**: System ist production-safe! ✅

---

### **🟡 WOCHE 3-4: PERFORMANCE**:
7. **Multi-Timeframe Confirmation** (~8h)
8. **Exit-Optimierung** (~6h)
9. **Spread Adjustment** (~3h)

**Total**: ~17 Stunden
**Ergebnis**: Win-Rate +10-15%, besserer Profit! 📈

---

### **🟢 WOCHE 5-6: VALIDATION**:
10. **Backtest Reports** (~8h)
11. **Monte Carlo Simulation** (~4h)

**Total**: ~12 Stunden
**Ergebnis**: Vertrauen & Proof! 🎯

---

## 🎯 **GESAMTAUFWAND**: ~50 Stunden (~2-3 Wochen)

---

## 📊 **BROKER APPROVAL CHECKLIST**

### **Micro-Live (€1.000 - €5.000)** ← AKTUELLES ZIEL:
- [ ] Daily Drawdown Protection (Phase 1.1)
- [ ] News Filter (Phase 1.2)
- [ ] Correlation Limits (Phase 1.3)
- [ ] AI Decision Log Dashboard (Phase 0)
- [ ] 2 Jahre historische Daten (Phase 3.1)
- [ ] Min. 100 Trades Live-Statistik
- [ ] Telegram Alerts (Phase 1.4)

**Erwartete Completion**: ~2-3 Wochen

---

### **Standard-Live (€5.000 - €50.000)**:
- [ ] Alle Micro-Live Requirements
- [ ] Multi-Timeframe Confirmation (Phase 2.1)
- [ ] Exit-Optimierung (Phase 2.2)
- [ ] 500+ Trades profitable Performance
- [ ] 6-12 Monate Track Record
- [ ] Backtest mit Monte Carlo (Phase 3.2)

**Erwartete Completion**: ~3-6 Monate

---

## 🚀 **NÄCHSTE SCHRITTE - ACTION ITEMS**

### **HEUTE**:
1. ✅ OHLC Daten herunterladen:
   ```bash
   python historical_data_manager.py --download --years 2
   ```

2. ⏳ AI Decision Log Dashboard Widget erstellen
3. ⏳ Container rebuild mit --no-cache

### **MORGEN**:
4. Daily Drawdown Protection implementieren
5. Integration testen

### **DIESE WOCHE**:
6. News Filter (ForexFactory)
7. Correlation Manager
8. Telegram Bot Setup

---

**Status**: Ready to Execute!
**Nächste Session**: AI Decision Log Dashboard Widget + OHLC Download

---
