# Trade Data Capture - Retrospektive Analyse-Fähigkeit

## Zusammenfassung

**Antwort: JA, aber mit wichtigen Lücken!**

Das System erfasst bereits **sehr umfangreiche Daten** für retrospektive Analysen, aber es gibt **kritische Lücken** bei der Verknüpfung von Trades zu ihren auslösenden Indikatoren und Mustern.

---

## ✅ Was wird AKTUELL erfasst

### 1. Trade-Tabelle (`trades`)

**Sehr umfangreich - 40+ Felder:**

#### Basis-Trade-Daten
- `ticket`, `account_id`, `symbol`, `direction`, `volume`
- `open_price`, `close_price`, `sl`, `tp`
- `open_time`, `close_time`
- `profit`, `commission`, `swap`

#### Auslösende Signal-Information
```python
signal_id = Column(Integer, ForeignKey('trading_signals.id'))  # ✅ Link zum Signal
timeframe = Column(String(10))                                  # ✅ Timeframe
entry_reason = Column(String(200))                             # ✅ Grund (Text)
entry_confidence = Column(Numeric(5, 2))                       # ✅ Signal Confidence
```

**Status: ✅ VORHANDEN**
- Direkter Link zum TradingSignal über `signal_id`
- Confidence Score gespeichert
- Entry Reason als Text

**Limitation:**
- `entry_reason` ist nur TEXT (nicht strukturiert)
- Keine direkte Liste der Indikatoren (nur über Signal-Lookup)

#### Performance-Tracking
```python
max_favorable_excursion = Column(Numeric(10, 2))   # Max Profit während Trade
max_adverse_excursion = Column(Numeric(10, 2))     # Max Drawdown während Trade
pips_captured = Column(Numeric(10, 2))
risk_reward_realized = Column(Numeric(10, 2))
hold_duration_minutes = Column(Integer)
```

**Status: ✅ HERVORRAGEND**

#### Market-Context
```python
entry_volatility = Column(Numeric(10, 5))  # ATR/Spread bei Entry
exit_volatility = Column(Numeric(10, 5))   # ATR/Spread bei Exit
session = Column(String(20))               # Trading Session
entry_bid = Column(Numeric(20, 5))        # Bid bei Entry
entry_ask = Column(Numeric(20, 5))        # Ask bei Entry
entry_spread = Column(Numeric(10, 5))     # Spread bei Entry
```

**Status: ✅ SEHR GUT**

#### Trailing Stop Tracking
```python
trailing_stop_active = Column(Boolean)
trailing_stop_moves = Column(Integer)     # Wie oft wurde SL bewegt
```

**Status: ✅ VORHANDEN**

#### Close Tracking
```python
close_reason = Column(String(100))  # TP_HIT, SL_HIT, MANUAL, TRAILING_STOP, etc
exit_bid, exit_ask, exit_spread    # Market conditions bei Exit
```

**Status: ✅ SEHR GUT**

---

### 2. TradingSignal-Tabelle (`trading_signals`)

**HERVORRAGEND strukturiert:**

```python
# Basis-Signal
symbol, timeframe, signal_type      # Was, wo, wann
confidence = Column(Numeric(5, 2))  # Wie sicher
entry_price, sl_price, tp_price     # Levels

# ✅ KRITISCH FÜR RETROSPEKTIVE ANALYSE:
indicators_used = Column(JSONB)     # {'RSI': 32, 'MACD': {...}, 'EMA_20': 1.0850}
patterns_detected = Column(JSONB)   # ['Bullish Engulfing', 'Above 200 EMA']
reasons = Column(JSONB)             # ['RSI Oversold Bounce', 'MACD Bullish Crossover']

# ✅ Indikator-Snapshot für Validation
indicator_snapshot = Column(JSONB)  # Kompletter Snapshot aller Indikatoren
last_validated = Column(DateTime)
is_valid = Column(Boolean)

status  # active, expired, executed, ignored
created_at, executed_at, expires_at
```

**Status: ✅ AUSGEZEICHNET**

**Dies ist GOLDGRUBE für Analysen:**
- Alle verwendeten Indikatoren mit Werten
- Alle erkannten Muster
- Strukturierte Gründe (Array)
- Kompletter Snapshot

---

### 3. AI Decision Log (`ai_decision_log`)

```python
timestamp, decision_type, decision
symbol, timeframe
primary_reason          # Text-Grund
detailed_reasoning      # Detaillierte Begründung
signal_id              # ✅ Link zum Signal
trade_id               # ✅ Link zum Trade
confidence_score       # AI Confidence
risk_score            # Risk Assessment
account_balance       # Account-State bei Decision
open_positions        # Anzahl offener Positions
impact_level          # HIGH, MEDIUM, LOW
user_action_required  # Flag für User-Intervention
```

**Status: ✅ HERVORRAGEND**

**Ermöglicht:**
- Warum wurde ein Signal abgelehnt?
- Warum wurde ein Trade NICHT eröffnet trotz Signal?
- Was war der AI-Reasoning?

---

### 4. Indicator Values (`indicator_values`)

```python
symbol, timeframe
indicator_name        # z.B. "RSI", "MACD", "HEIKEN_ASHI"
value = Column(JSONB) # Komplette Indicator-Daten
calculated_at
account_id
```

**Status: ✅ VORHANDEN**

**Problem:**
- Hat `account_id`, obwohl Indikatoren GLOBAL sein sollten (nach Migration)
- Wird gecached, aber nicht langfristig archiviert

---

### 5. Pattern Detections (`pattern_detections`)

```python
symbol, timeframe
pattern_name          # z.B. "Bullish Engulfing"
pattern_type          # BULLISH, BEARISH
reliability_score     # Wie zuverlässig ist das Pattern
ohlc_snapshot         # OHLC-Daten bei Detection
detected_at
account_id
```

**Status: ✅ VORHANDEN**

**Problem:**
- Hat `account_id`, obwohl Patterns GLOBAL sein sollten
- Nicht direkt mit Trades verknüpft

---

### 6. Trade History Events (`trade_history_events`)

```python
trade_id, ticket
event_type            # TP_MODIFIED, SL_MODIFIED, VOLUME_MODIFIED, PRICE_UPDATE
timestamp
old_value, new_value  # Vorher/Nachher
reason                # Warum wurde geändert
source                # Welches System-Komponente
price_at_change       # Marktpreis bei Änderung
spread_at_change      # Spread bei Änderung
event_metadata        # Zusätzliche Daten (JSONB)
```

**Status: ✅ HERVORRAGEND**

**Ermöglicht:**
- Komplette Audit-Trail aller Trade-Modifikationen
- Trailing Stop History
- TP/SL Anpassungen

---

## ❌ Kritische Lücken für Retrospektive Analyse

### 1. Indikator-Werte sind NICHT dauerhaft archiviert

**Problem:**
- `indicator_values` Tabelle ist ein **CACHE**, kein Archiv
- Alte Werte werden wahrscheinlich gelöscht
- Bei Trade-Analyse fehlen dann die exakten Indikator-Werte

**Impact: 🔴 HOCH**

**Lösung:**
- Entweder: `indicator_snapshot` in `trading_signals` nutzen (bereits vorhanden!)
- Oder: `indicator_values` NICHT löschen, sondern archivieren

### 2. Pattern Detections nicht direkt mit Trades verknüpft

**Problem:**
- Patterns haben KEINEN direkten FK zu Trades
- Muss über `trading_signals.patterns_detected` (JSONB) nachgeschlagen werden
- Zeitbasiertes Matching erforderlich

**Impact: 🟡 MITTEL**

**Workaround:**
- Via `Trade.signal_id` → `TradingSignal.patterns_detected` (JSONB Array)

### 3. Indicator Performance Tracking fehlt Kontext

**Problem:**
- `indicator_scores` Tabelle trackt Win-Rate pro Indikator
- ABER: Keine Details WELCHE Trades zu welchem Score beigetragen haben
- Keine Breakdown nach Market Conditions

**Impact: 🟡 MITTEL**

**Was fehlt:**
- `indicator_trade_contributions` Tabelle
- Welcher Indikator hat WIE VIEL zum Trade-Decision beigetragen
- Performance pro Indikator pro Market Regime

### 4. Multi-Indicator Confluence nicht explizit erfasst

**Problem:**
- Wir wissen welche Indikatoren verwendet wurden (JSONB)
- ABER: Nicht wie sie interagiert haben
- Keine "Confluence Score" pro Indikator-Kombination

**Impact: 🟡 MITTEL**

---

## 🎯 Was du JETZT analysieren kannst

### ✅ Möglich mit aktuellen Daten:

#### 1. Trade Performance nach Signal-Typ
```sql
SELECT
    ts.signal_type,
    COUNT(*) as total_trades,
    AVG(t.profit) as avg_profit,
    AVG(t.pips_captured) as avg_pips,
    AVG(t.risk_reward_realized) as avg_rr,
    SUM(CASE WHEN t.profit > 0 THEN 1 ELSE 0 END)::float / COUNT(*) as win_rate
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE t.status = 'closed'
GROUP BY ts.signal_type;
```

#### 2. Performance nach Indicator-Confluence
```sql
SELECT
    jsonb_array_length(ts.reasons) as num_reasons,
    COUNT(*) as trades,
    AVG(t.profit) as avg_profit,
    AVG(t.entry_confidence) as avg_confidence
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE t.status = 'closed'
GROUP BY num_reasons
ORDER BY num_reasons;
```

#### 3. Pattern Performance
```sql
SELECT
    pattern_elem->>'pattern' as pattern_name,
    COUNT(*) as occurrences,
    AVG(t.profit) as avg_profit,
    SUM(CASE WHEN t.profit > 0 THEN 1 ELSE 0 END)::float / COUNT(*) as win_rate
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id,
     jsonb_array_elements(ts.patterns_detected) as pattern_elem
WHERE t.status = 'closed'
GROUP BY pattern_name
ORDER BY win_rate DESC;
```

#### 4. Indikator-spezifische Performance
```sql
-- Trades wo RSI verwendet wurde
SELECT
    AVG(t.profit) as avg_profit_with_rsi,
    COUNT(*) as trades_with_rsi
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE t.status = 'closed'
  AND ts.indicators_used ? 'RSI';  -- JSONB hat 'RSI' Key
```

#### 5. MFE/MAE Analyse (Max Favorable/Adverse Excursion)
```sql
SELECT
    symbol,
    AVG(max_favorable_excursion) as avg_mfe,
    AVG(max_adverse_excursion) as avg_mae,
    AVG(pips_captured) as avg_pips_captured,
    AVG(max_favorable_excursion - pips_captured) as avg_pips_left_on_table
FROM trades
WHERE status = 'closed'
GROUP BY symbol;
```

#### 6. Session Performance
```sql
SELECT
    session,
    COUNT(*) as trades,
    AVG(profit) as avg_profit,
    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END)::float / COUNT(*) as win_rate
FROM trades
WHERE status = 'closed'
GROUP BY session
ORDER BY avg_profit DESC;
```

#### 7. Trailing Stop Effectiveness
```sql
SELECT
    trailing_stop_active,
    COUNT(*) as trades,
    AVG(profit) as avg_profit,
    AVG(pips_captured) as avg_pips,
    AVG(trailing_stop_moves) as avg_ts_moves
FROM trades
WHERE status = 'closed'
GROUP BY trailing_stop_active;
```

---

## ❌ Was du NICHT analysieren kannst (ohne Erweiterung)

### 1. Indikator-Werte zum Zeitpunkt des Trades
**Problem:** Cache, keine Archivierung

**Workaround:** Nutze `trading_signals.indicator_snapshot`

### 2. Detaillierte Indikator-Gewichtung
**Fehlt:** Welcher Indikator hatte wie viel Einfluss auf die Decision

### 3. Indikator-Performance unter spezifischen Market Conditions
**Fehlt:** Performance-Breakdown nach:
- Volatilität
- Trend vs. Ranging
- Session
- Symbol

### 4. Confluence-Pattern Performance
**Fehlt:** Welche Indikator-Kombinationen funktionieren am besten

---

## 🔧 Empfohlene Erweiterungen

### Priority 1: Indikator-Snapshot archivieren

**Option A: Nutze existing indicator_snapshot** (EINFACH)
```python
# In trading_signals ist bereits vorhanden:
indicator_snapshot = Column(JSONB)
```

**Dieses Feld sollte bei Signal-Creation gefüllt werden!**

**Option B: Separate Archiv-Tabelle** (SAUBER)
```sql
CREATE TABLE indicator_snapshots (
    id SERIAL PRIMARY KEY,
    signal_id INT REFERENCES trading_signals(id),
    trade_id INT REFERENCES trades(id),
    snapshot_at TIMESTAMP NOT NULL,
    indicators JSONB NOT NULL,  -- Alle Indikator-Werte
    market_state JSONB          -- ATR, Trend, Volatility, etc.
);
```

### Priority 2: Indicator Contribution Tracking

```sql
CREATE TABLE indicator_contributions (
    id SERIAL PRIMARY KEY,
    trade_id INT REFERENCES trades(id),
    signal_id INT REFERENCES trading_signals(id),
    indicator_name VARCHAR(50) NOT NULL,
    indicator_value JSONB,
    contribution_weight NUMERIC(5, 4),  -- 0.0 - 1.0
    direction VARCHAR(10),               -- BUY, SELL, NEUTRAL
    confidence NUMERIC(5, 2)
);
```

**Ermöglicht:**
- Welcher Indikator hatte WIEVIEL Einfluss
- Performance pro Indikator isoliert
- Confluence-Analyse

### Priority 3: Pattern-Trade Link

```sql
-- Add FK zu pattern_detections
ALTER TABLE pattern_detections ADD COLUMN trade_id INT REFERENCES trades(id);
```

### Priority 4: Market Regime Tracking

```sql
CREATE TABLE market_regimes (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    regime VARCHAR(20) NOT NULL,  -- TRENDING, RANGING, TOO_WEAK
    trend_strength NUMERIC(5, 2), -- 0-100%
    volatility_level VARCHAR(20), -- LOW, NORMAL, HIGH
    detected_at TIMESTAMP NOT NULL,
    indicators JSONB               -- ADX, ATR, Volatility, etc.
);

-- Link to trades
ALTER TABLE trades ADD COLUMN market_regime_id INT REFERENCES market_regimes(id);
```

---

## 📊 Zusammenfassung

### Was GUT ist ✅

1. **Trade-Tracking**: Hervorragend (40+ Felder)
2. **Signal-Tracking**: Ausgezeichnet (indicators_used, patterns_detected, indicator_snapshot)
3. **AI Decision Log**: Sehr gut (warum wurden Trades abgelehnt)
4. **Trade History**: Perfekt (vollständige Audit-Trail)
5. **MFE/MAE**: Hervorragend für Exit-Optimierung
6. **Performance Metrics**: Umfassend (pips, R:R, duration)

### Was FEHLT ❌

1. **Indikator-Archivierung**: Keine dauerhafte Speicherung
2. **Indikator-Gewichtung**: Kein Contribution Tracking
3. **Market Regime Link**: Nicht explizit mit Trades verknüpft
4. **Confluence Analysis**: Keine strukturierte Indikator-Kombinations-Analyse

### Priorität für Implementierung

1. **🔴 CRITICAL**: Sicherstellen dass `trading_signals.indicator_snapshot` befüllt wird
2. **🟡 HIGH**: `indicator_contributions` Tabelle hinzufügen
3. **🟢 MEDIUM**: `market_regimes` Tracking hinzufügen
4. **🟢 LOW**: Pattern-Trade direkte Verlinkung

---

## 🎯 Sofortige Handlungsempfehlung

### 1. Prüfen ob indicator_snapshot befüllt wird

```python
# In signal_generator.py prüfen:
# Wird indicator_snapshot beim Signal-Save gefüllt?

from database import ScopedSession
db = ScopedSession()
signal = db.query(TradingSignal).filter_by(status='active').first()
print(signal.indicator_snapshot)
# Sollte NICHT None sein!
```

### 2. Falls NICHT befüllt, implementieren:

```python
# In signal_generator.py bei _save_signal():
indicator_snapshot = {
    'indicators': indicators_used,  # Alle Indikator-Werte
    'market_state': {
        'atr': current_atr,
        'regime': market_regime,
        'trend_strength': trend_strength,
        'volatility': volatility_level
    },
    'timestamp': datetime.utcnow().isoformat()
}

new_signal = TradingSignal(
    ...,
    indicator_snapshot=indicator_snapshot  # ✅ Speichern!
)
```

### 3. Test Query für Retrospektive Analyse

```sql
-- Beispiel: Trades mit RSI < 30 bei Entry
SELECT
    t.ticket,
    t.symbol,
    t.profit,
    t.pips_captured,
    ts.indicator_snapshot->'indicators'->>'RSI' as rsi_value,
    ts.indicator_snapshot->'market_state'->>'regime' as market_regime
FROM trades t
JOIN trading_signals ts ON t.signal_id = ts.id
WHERE t.status = 'closed'
  AND (ts.indicator_snapshot->'indicators'->>'RSI')::numeric < 30
ORDER BY t.profit DESC;
```

---

## Datum
2025-10-25 15:45 UTC
