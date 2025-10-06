# Implementation Plan: Candle-Stick Mustererkennung & Indikator-basierte Handelsempfehlungen

**Status:** Phase 1-5 IMPLEMENTIERT ✅ | Phase 6 Dashboard-UI in Arbeit
**Erstellt:** 2025-10-03
**Zuletzt aktualisiert:** 2025-10-03 12:10 UTC
**Ziel:** Vollständiges Trading-Signal-System mit Mustererkennung und technischen Indikatoren für autonomes Trading

## 🎉 ERFOLG: Signal-Worker läuft und generiert Signale!
- **Status:** Backend vollständig implementiert und funktional
- **Erste Signale generiert:** SELL XAUUSD M15 (40%), BUY BTCUSD M5 (53%)
- **Signal-Generierung:** Alle 60 Sekunden
- **Redis-Caching:** Aktiv für schnelle Performance

---

## Überblick
Implementierung eines vollständigen Trading-Signal-Systems mit Mustererkennung und technischen Indikatoren für autonomes Trading.

---

## Phase 1: Datengrundlage & Infrastruktur ✅

### 1.1 Datenbank-Erweiterungen
- [x] **Neue Tabelle:** `trading_signals`
  - Felder: id, account_id, symbol, timeframe, signal_type (BUY/SELL/HOLD), confidence (0-100%), indicators_used (JSON), pattern_detected, entry_price, sl_price, tp_price, created_at, status (active/expired/executed)

- [x] **Neue Tabelle:** `pattern_detections`
  - Felder: id, account_id, symbol, timeframe, pattern_name, pattern_type (bullish/bearish), reliability_score, detected_at, ohlc_snapshot (JSON)

- [x] **Neue Tabelle:** `indicator_values`
  - Felder: id, account_id, symbol, timeframe, indicator_name, value (JSON für multi-value indicators wie MACD), calculated_at

- [x] **Erweiterte Indizes:** `ohlc_data` für schnellere Mustersuche

### 1.2 Backend-Komponenten
- [x] `pattern_recognition.py` - Candlestick Mustererkennung
- [x] `technical_indicators.py` - Indikator-Berechnungen
- [x] `signal_generator.py` - Signal-Logik & Aggregation (inkl. Confidence-Scoring)
- [x] `signal_worker.py` - Background Worker für kontinuierliche Analyse

---

## Phase 2: Candlestick Mustererkennung ✅

### 2.1 Einzelne Kerzen-Muster - Bullish
- [x] Hammer
- [x] Inverted Hammer
- [x] Bullish Engulfing
- [x] Morning Star
- [x] Three White Soldiers
- [x] Dragonfly Doji

### 2.2 Einzelne Kerzen-Muster - Bearish
- [x] Shooting Star
- [x] Hanging Man
- [x] Bearish Engulfing
- [ ] Evening Star
- [ ] Three Black Crows
- [ ] Gravestone Doji

### 2.3 Multi-Kerzen-Muster
- [ ] Doji-Formationen
- [ ] Harami (bullish/bearish)
- [ ] Piercing Pattern
- [ ] Dark Cloud Cover
- [ ] Rising/Falling Three Methods

### 2.4 Implementierung
- [ ] PatternRecognizer Klasse
- [ ] detect_patterns() Methode
- [ ] calculate_pattern_reliability() Methode

---

## Phase 3: Technische Indikatoren

### 3.1 Trend-Indikatoren
- [ ] **Moving Averages** (SMA, EMA)
  - [ ] Perioden: 20, 50, 100, 200
  - [ ] Golden Cross / Death Cross Detection

- [ ] **MACD** (Moving Average Convergence Divergence)
  - [ ] Signal-Line Crossovers
  - [ ] Histogram-Analyse

- [ ] **ADX** (Average Directional Index)
  - [ ] Trend-Stärke Messung

### 3.2 Momentum-Indikatoren
- [ ] **RSI** (Relative Strength Index)
  - [ ] Überkauft/Überverkauft (>70 / <30)
  - [ ] Divergenzen

- [ ] **Stochastic Oscillator**
  - [ ] %K/%D Crossovers
  - [ ] Overbought/Oversold Levels

### 3.3 Volatilität-Indikatoren
- [ ] **Bollinger Bands**
  - [ ] Band-Touches
  - [ ] Squeeze-Situationen
  - [ ] Breakouts

- [ ] **ATR** (Average True Range)
  - [ ] Für Stop-Loss Berechnung
  - [ ] Volatilitäts-Messung

### 3.4 Volumen-Indikatoren
- [ ] **Volume Profile**
- [ ] **OBV** (On-Balance Volume)
- [ ] **Volume-weighted Moving Averages**

### 3.5 Implementierung
- [ ] TechnicalIndicators Klasse
- [ ] calculate_all() Methode
- [ ] get_indicator_signals() Methode

---

## Phase 4: Signal-Generierung & Aggregation

### 4.1 Signal-Generator
- [ ] SignalGenerator Klasse implementieren
- [ ] generate_signal() Methode
  - [ ] OHLC-Daten laden
  - [ ] Candlestick-Muster erkennen
  - [ ] Indikatoren berechnen
  - [ ] Signale aggregieren
  - [ ] Confidence-Score berechnen
  - [ ] Entry/SL/TP berechnen

### 4.2 Multi-Timeframe-Analyse
- [ ] Timeframe-Hierarchie: M5 → M15 → H1 → H4 → D1
- [ ] Trend-Alignment Logik
- [ ] Höhere Timeframe Bestätigung

### 4.3 Confidence-Scoring
- [ ] Scoring-Algorithmus implementieren
  - Pattern_Reliability * 0.3
  - Indicator_Confluence * 0.4
  - Timeframe_Alignment * 0.2
  - Volume_Confirmation * 0.1
- [ ] Schwellwerte definieren (40%, 60%, 80%)

### 4.4 Entry/Exit Berechnung
- [ ] PositionCalculator Klasse
- [ ] calculate_entry_sl_tp() Methode
  - [ ] Entry-Point Berechnung
  - [ ] Stop-Loss (Pattern-basiert + ATR)
  - [ ] Take-Profit (Risk/Reward + Resistance)

---

## Phase 5: Signal-Worker (Background Processing)

### 5.1 Worker-Architektur
- [ ] SignalWorker Klasse
- [ ] worker_loop() Methode
- [ ] Integration mit App-Lifecycle (Start/Stop)

### 5.2 Performance-Optimierung
- [ ] Redis Cache für Indikator-Werte
- [ ] Multi-Threading für verschiedene Symbole
- [ ] Lazy Computation (nur bei neuen OHLC-Daten)

---

## Phase 6: Dashboard-Integration

### 6.1 Neue Dashboard-Komponenten
- [ ] Signals Panel HTML/CSS
- [ ] Signal-Filter (Timeframe, Confidence, Type)
- [ ] Signal-Liste mit Details
- [ ] Signal-Reasons Anzeige
- [ ] Action Buttons (Execute/Ignore)

### 6.2 Symbol-View Erweiterung
- [ ] Signal-Indicator bei jedem Symbol (📈/📉)
- [ ] Tooltip mit Signal-Details
- [ ] Farbcodierung nach Confidence

### 6.3 Signal-Detail-Ansicht
- [ ] Modal/Sidebar für Details
- [ ] Vollständige Indikator-Werte
- [ ] Pattern-Erklärung
- [ ] Historische Performance (optional)

### 6.4 API-Endpoints
- [ ] GET /api/signals - Liste aktiver Signale
- [ ] GET /api/signals/<signal_id> - Signal-Details
- [ ] POST /api/signals/<signal_id>/execute - Trade ausführen (später)
- [ ] GET /api/signals/stats - Signal-Statistiken

### 6.5 Frontend JavaScript
- [ ] Signal-Polling (alle 5 Sekunden)
- [ ] Real-time Signal Updates
- [ ] Filter-Logik
- [ ] Signal-Benachrichtigungen (optional)

---

## Phase 7: Auto-Trading Integration (SPÄTER)

### 7.1 Signal-Execution-Engine
- [ ] SignalExecutor Klasse
- [ ] execute_signal() Methode
- [ ] should_execute() Validation
- [ ] Position Size Calculation

### 7.2 Auto-Trading Modes
- [ ] Manual Mode (nur Anzeige)
- [ ] Semi-Auto Mode (1-Click Execute)
- [ ] Full-Auto Mode (Auto-Execution > 80%)
- [ ] Mode-Switcher im Dashboard

### 7.3 Risk Management
- [ ] Max Positions pro Symbol: 1
- [ ] Max Total Positions: 5
- [ ] Max Risiko pro Trade: 2%
- [ ] Max Total Portfolio Risiko: 10%
- [ ] Daily Loss Limit: 5%

---

## Phase 8: Testing & Validation

### 8.1 Unit Tests
- [ ] Pattern Recognition Tests
- [ ] Indicator Calculation Tests
- [ ] Signal Generation Tests
- [ ] Confidence Scoring Tests

### 8.2 Integration Tests
- [ ] Worker-Integration Tests
- [ ] API-Endpoint Tests
- [ ] Database-Integration Tests

### 8.3 Paper Trading (optional)
- [ ] Virtuelles Portfolio
- [ ] Signal-Tracking
- [ ] Performance-Metriken

### 8.4 Monitoring & Logging
- [ ] Signal-Generierung loggen
- [ ] False Positives tracken
- [ ] Pattern-Performance messen
- [ ] Alert bei System-Fehlern

---

## Technologie-Stack

### Python Libraries
- [ ] **Installation:** `pip install ta-lib pandas numpy`
- [ ] talib - Technical Analysis Library
- [ ] pandas - Datenverarbeitung
- [ ] numpy - Numerische Berechnungen

### Performance-Überlegungen
- [ ] Redis Cache für Indikator-Werte
- [ ] Database Indizes optimieren
- [ ] Chunked Processing implementieren
- [ ] Async Workers einrichten

---

## Implementierungs-Reihenfolge

1. [ ] **Datenbank-Schema** erweitern (Phase 1.1)
2. [ ] **Technical Indicators** implementieren - Start mit RSI, MACD, EMA (Phase 3)
3. [ ] **Einfache Pattern Recognition** - 5-10 wichtigste Muster (Phase 2)
4. [ ] **Signal Generator** - Basic-Version (Phase 4.1)
5. [ ] **Dashboard API** für Signale (Phase 6.4)
6. [ ] **Dashboard UI** für Signal-Anzeige (Phase 6.1-6.2)
7. [ ] **Signal Worker** - Background Processing (Phase 5)
8. [ ] **Multi-Timeframe Analysis** (Phase 4.2)
9. [ ] **Confidence Scoring** verfeinern (Phase 4.3)
10. [ ] **Auto-Trading Integration** - wenn gewünscht (Phase 7)

---

## Erwartete Herausforderungen & Lösungen

### 1. Datenmenge
**Problem:** OHLC-Daten für alle Timeframes können groß werden
**Lösung:** Nur letzte N Candles pro Timeframe speichern (z.B. 200 für M5, 500 für H1)

### 2. False Signals
**Problem:** Pattern & Indikatoren können Fehlsignale generieren
**Lösung:** Multi-Indikator Bestätigung, hohe Confidence-Schwellwerte

### 3. Performance
**Problem:** Kontinuierliche Berechnung für viele Symbole/Timeframes
**Lösung:** Caching, Parallelisierung, lazy computation

### 4. Latency
**Problem:** Signal muss schnell zum Dashboard & MT5
**Lösung:** WebSocket für Real-time Updates (optional), Redis Pub/Sub

---

## Erweiterungen für die Zukunft

- [ ] **Machine Learning:** Train Models auf historischen Pattern-Erfolgen
- [ ] **Sentiment Analysis:** News/Social Media Integration
- [ ] **Korrelations-Analyse:** Symbol-Korrelationen für diversifizierten Trade-Entry
- [ ] **Portfolio-Optimierung:** Kelly Criterion für Position Sizing
- [ ] **Advanced Chart Patterns:** Triangles, Flags, Head & Shoulders
- [ ] **Backtesting Engine:** Historische Performance-Messung
- [ ] **WebSocket Integration:** Real-time Signal Push
- [ ] **Mobile Notifications:** Push-Benachrichtigungen bei starken Signalen

---

## Code-Struktur (Vorschau)

```
/projects/ngTradingBot/
├── models.py                    # Erweitert mit neuen Tabellen
├── pattern_recognition.py       # NEU - Candlestick Patterns
├── technical_indicators.py      # NEU - Indicator Calculations
├── signal_generator.py          # NEU - Signal Logic
├── signal_evaluator.py          # NEU - Confidence Scoring
├── signal_worker.py             # NEU - Background Worker
├── app.py                       # Erweitert mit Signal-Endpoints
├── templates/
│   └── dashboard.html           # Erweitert mit Signal-Panel
└── static/
    ├── css/
    │   └── signals.css          # NEU - Signal Styling
    └── js/
        └── signals.js           # NEU - Signal Frontend Logic
```

---

## Nächste Schritte

1. Review & Approval des Plans
2. Dependencies installieren (ta-lib, pandas, numpy)
3. Start mit Phase 1.1: Datenbank-Erweiterungen
4. Iterative Implementierung gemäß Reihenfolge

---

**Status Log:**

- [x] 2025-10-03: Plan erstellt
- [ ] Implementierung gestartet
- [ ] Phase 1 abgeschlossen
- [ ] Phase 2 abgeschlossen
- [ ] Phase 3 abgeschlossen
- [ ] Phase 4 abgeschlossen
- [ ] Phase 5 abgeschlossen
- [ ] Phase 6 abgeschlossen
- [ ] Testing abgeschlossen
- [ ] Production Ready

---

**Notizen:**
- Trading-Hours-Check bereits implementiert (2025-10-03)
- Server läuft auf Ports 9900-9903, 9905
- PostgreSQL Container: ngtradingbot_db
- Redis Container: ngtradingbot_redis

---

## ✅ AKTUELLER IMPLEMENTIERUNGSSTATUS (2025-10-03 12:15 UTC)

### Vollständig implementiert:

1. **Datenbank-Schema** ✅
   - `trading_signals` - Speichert generierte Trading-Signale
   - `pattern_detections` - Speichert erkannte Candlestick-Muster
   - `indicator_values` - Cache für Indikator-Werte

2. **Technical Indicators Module** (`technical_indicators.py`) ✅
   - RSI (Relative Strength Index)
   - MACD (Moving Average Convergence Divergence)
   - EMA (Exponential Moving Average) - 20, 50, 200 Perioden
   - Bollinger Bands
   - ATR (Average True Range)
   - Stochastic Oscillator
   - **Redis-Caching** für schnelle Performance (TTL: 300s)

3. **Pattern Recognition Module** (`pattern_recognition.py`) ✅
   - Bullish Patterns: Hammer, Inverted Hammer, Bullish Engulfing, Morning Star, Three White Soldiers, Dragonfly Doji, Piercing Pattern
   - Bearish Patterns: Shooting Star, Hanging Man, Evening Star, Three Black Crows, Gravestone Doji, Dark Cloud Cover
   - Pattern Reliability Scoring (0-100%)
   - Volume Confirmation
   - Trend Context Analysis
   - **Redis-Caching** für Pattern-Detections (TTL: 60s)

4. **Signal Generator** (`signal_generator.py`) ✅
   - Kombiniert Pattern und Indikator-Signale
   - Multi-Timeframe-Analyse (M5, M15, H1, H4)
   - Confidence-Scoring-Algorithmus:
     - Pattern Reliability: 30%
     - Indicator Confluence: 40%
     - Signal Strength: 30%
   - Entry/SL/TP-Berechnung basierend auf ATR
   - Automatische Signal-Expiration (24h)

5. **Signal Worker** (`signal_worker.py`) ✅
   - Background-Worker läuft alle 60 Sekunden
   - Generiert Signale für alle abonnierten Symbole
   - Timeframes: M5, M15, H1, H4
   - **Status:** AKTIV und generiert Signale!

6. **API Endpoints** (`app.py`) ✅
   - `GET /api/signals` - Liste aktiver Signale (mit Filtern)
   - `GET /api/signals/<id>` - Signal-Details
   - `POST /api/signals/<id>/ignore` - Signal ignorieren
   - `GET /api/signals/stats` - Signal-Statistiken

### Beispiel generierte Signale:
```
- SELL XAUUSD M15 (confidence: 40.0%)
- BUY BTCUSD M5 (confidence: 53.0%)
- Signal generation cycle: 0.37s (3 signals generated)
```

### Noch zu implementieren:

1. **Dashboard UI** (Phase 6) - IN ARBEIT
   - Signals Panel im Dashboard
   - Signal-Liste mit Filtern
   - Signal-Detail-Ansicht
   - Real-time Signal-Updates

2. **Auto-Trading Integration** (Phase 7) - SPÄTER
   - Signal Execution Engine
   - Risk Management
   - Position Sizing
   - Auto-Trading Modes (Manual/Semi-Auto/Full-Auto)

3. **Testing & Validation** (Phase 8) - SPÄTER
   - Unit Tests
   - Integration Tests
   - Paper Trading
   - Performance Monitoring

---

## Implementierte Module - Detailübersicht

### `technical_indicators.py` (16.4 KB)
- **Klasse:** `TechnicalIndicators`
- **Methoden:**
  - `calculate_rsi()` - RSI mit Oversold/Overbought Detection
  - `calculate_macd()` - MACD mit Crossover-Erkennung
  - `calculate_ema()` - EMA mit Trend-Detection
  - `calculate_bollinger_bands()` - BB mit Position-Analyse
  - `calculate_atr()` - ATR für Volatilitäts-Messung
  - `calculate_stochastic()` - Stochastic mit Signal-Generierung
  - `calculate_all()` - Alle Indikatoren auf einmal
  - `get_indicator_signals()` - Extrahiert Trading-Signale
- **Redis-Cache:** Ja, TTL 300 Sekunden

### `pattern_recognition.py` (11.2 KB)
- **Klasse:** `PatternRecognizer`
- **Methoden:**
  - `detect_patterns()` - Erkennt alle Candlestick-Muster
  - `_calculate_pattern_reliability()` - Pattern-Scoring
  - `save_pattern_detection()` - Speichert Pattern in DB
  - `get_pattern_signals()` - Extrahiert Trading-Signale
- **Patterns:** 13 verschiedene Candlestick-Muster
- **Redis-Cache:** Ja, TTL 60 Sekunden

### `signal_generator.py` (11.6 KB)
- **Klasse:** `SignalGenerator`
- **Methoden:**
  - `generate_signal()` - Generiert Trading-Signal
  - `_aggregate_signals()` - Kombiniert Pattern + Indikator-Signale
  - `_calculate_confidence()` - Berechnet Confidence-Score
  - `_calculate_entry_sl_tp()` - Berechnet Entry/SL/TP Preise
  - `get_multi_timeframe_analysis()` - Multi-TF-Analyse
  - `expire_old_signals()` - Cleanup alter Signale
- **Signal-Schwellwerte:**
  - < 40%: Kein Signal
  - 40-60%: Schwaches Signal
  - 60-80%: Mittleres Signal
  - > 80%: Starkes Signal

### `signal_worker.py` (5.3 KB)
- **Klasse:** `SignalWorker`
- **Methoden:**
  - `start()` - Startet Background-Worker
  - `stop()` - Stoppt Worker
  - `_worker_loop()` - Hauptschleife (alle 60s)
  - `_generate_all_signals()` - Generiert für alle Symbole/TFs
  - `get_stats()` - Worker-Statistiken
- **Interval:** 60 Sekunden
- **Status:** LÄUFT und generiert Signale

---

## Nächste Schritte

1. ✅ **ERLEDIGT:** Backend vollständig implementiert
2. ✅ **ERLEDIGT:** Signal-Worker läuft und generiert Signale
3. ✅ **ERLEDIGT:** API-Endpoints implementiert
4. **TODO:** Dashboard UI für Signal-Anzeige
5. **TODO:** Testing und Optimierung
6. **SPÄTER:** Auto-Trading Integration

---

## Technische Details

### Dependencies installiert:
- TA-Lib 0.6.7 ✅
- pandas, numpy ✅
- Redis-Client ✅

### Performance:
- Signal-Generierung: ~0.37s pro Cycle
- Redis-Caching aktiv
- Parallele Berechnung möglich

### Datenfluss:
1. OHLC-Daten aus PostgreSQL → Indikatoren berechnen → Redis Cache
2. OHLC-Daten → Pattern erkennen → Redis Cache
3. Indikatoren + Patterns → Signal generieren → PostgreSQL speichern
4. API abrufen → Signale anzeigen im Dashboard

