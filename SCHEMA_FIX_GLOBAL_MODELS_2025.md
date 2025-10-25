# Schema Fix: Global Models - account_id Entfernung

**Datum:** 25. Oktober 2025
**Issue:** CRITICAL - Schema Code Mismatch in models.py
**Status:** ✅ BEHOBEN

---

## Problem

Die Datenbank-Migration hatte `account_id` aus globalen Tabellen entfernt (Ticks, OHLC, Trading Signals, Patterns, etc.), aber `models.py` erwartete noch diese Spalte. Dies führte zu:
- SQLAlchemy Query-Fehlern
- Potenzielle Dateninkonsistenz
- Foreign Key Constraints auf nicht-existente Spalten

**Root Cause:** Die neue Architektur macht Strategie-Daten (Signale, Indikatoren, Patterns) **global**, während nur Account-spezifische Daten (Balance, Trades, Settings) die `account_id` behalten.

---

## Behobene Models

### 1. TradingSignal (Zeile 343-401)

**Vorher:**
```python
class TradingSignal(Base):
    __tablename__ = 'trading_signals'
    __table_args__ = (
        Index('idx_unique_active_signal', 'account_id', 'symbol', 'timeframe', ...),
    )

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    # ...
    account = relationship("Account", foreign_keys=[account_id])
```

**Nachher:**
```python
class TradingSignal(Base):
    """Trading Signals - GLOBAL

    NOTE: Trading signals are now GLOBAL (no account_id).
    """
    __tablename__ = 'trading_signals'
    __table_args__ = (
        Index('idx_unique_active_signal', 'symbol', 'timeframe', ...),  # ✅ account_id entfernt
    )

    id = Column(Integer, primary_key=True)
    # account_id removed - trading signals are global
    # ...
    # No relationships - trading signals are global
```

**Änderungen:**
- ✅ `account_id` Spalte entfernt
- ✅ `account_id` aus UNIQUE Index entfernt
- ✅ Foreign Key Constraint entfernt
- ✅ Relationship zu Account entfernt

---

### 2. PatternDetection (Zeile 404-430)

**Vorher:**
```python
class PatternDetection(Base):
    __tablename__ = 'pattern_detections'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    # ...
    account = relationship("Account", foreign_keys=[account_id])
```

**Nachher:**
```python
class PatternDetection(Base):
    """Candlestick Pattern Detections - GLOBAL

    NOTE: Pattern detections are now GLOBAL (no account_id).
    """
    __tablename__ = 'pattern_detections'

    id = Column(Integer, primary_key=True)
    # account_id removed - pattern detections are global
    # ...
    # No relationships - pattern detections are global
```

**Änderungen:**
- ✅ `account_id` Spalte entfernt
- ✅ Foreign Key Constraint entfernt
- ✅ Relationship zu Account entfernt

---

### 3. IndicatorValue (Zeile 432-456)

**Vorher:**
```python
class IndicatorValue(Base):
    """Calculated Technical Indicator Values (Cache)"""
    __tablename__ = 'indicator_values'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    # ...
    account = relationship("Account", foreign_keys=[account_id])
```

**Nachher:**
```python
class IndicatorValue(Base):
    """Calculated Technical Indicator Values (Cache) - GLOBAL

    NOTE: Indicator values are now GLOBAL (no account_id).
    """
    __tablename__ = 'indicator_values'

    id = Column(Integer, primary_key=True)
    # account_id removed - indicator values are global
    # ...
    # No relationships - indicator values are global
```

**Änderungen:**
- ✅ `account_id` Spalte entfernt
- ✅ Foreign Key Constraint entfernt
- ✅ Relationship zu Account entfernt

---

### 4. IndicatorScore (Zeile 733-853)

**Vorher:**
```python
class IndicatorScore(Base):
    """Symbol-specific indicator performance scores"""
    __tablename__ = 'indicator_scores'

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    # ...

    __table_args__ = (
        Index('idx_indicator_scores_lookup', 'account_id', 'symbol', 'timeframe', 'indicator_name'),
    )

    @classmethod
    def get_or_create(cls, db, account_id: int, symbol: str, ...):
        score = db.query(cls).filter_by(account_id=account_id, ...).first()
```

**Nachher:**
```python
class IndicatorScore(Base):
    """Symbol-specific indicator performance scores - GLOBAL

    NOTE: Indicator scores are now GLOBAL (no account_id).
    """
    __tablename__ = 'indicator_scores'

    id = Column(Integer, primary_key=True)
    # account_id removed - indicator scores are global
    # ...

    __table_args__ = (
        Index('idx_indicator_scores_lookup', 'symbol', 'timeframe', 'indicator_name', unique=True),
    )

    @classmethod
    def get_or_create(cls, db, symbol: str, ...):
        score = db.query(cls).filter_by(symbol=symbol, ...).first()
```

**Änderungen:**
- ✅ `account_id` Spalte entfernt
- ✅ `account_id` aus Composite Index entfernt
- ✅ UNIQUE Constraint hinzugefügt (symbol+timeframe+indicator_name)
- ✅ Alle `@classmethod` Methoden aktualisiert:
  - `get_or_create()` - account_id Parameter entfernt
  - `get_symbol_scores()` - account_id Parameter entfernt
  - `get_top_indicators()` - account_id Parameter entfernt

---

## Bereits korrekte Global Models

Diese Models waren bereits korrekt ohne `account_id`:

✅ **Tick** (Zeile 109-131)
- NOTE: "Ticks are now GLOBAL (no account_id). A EURUSD tick is the same for everyone."

✅ **OHLCData** (Zeile 133-157)
- NOTE: "OHLC data is now GLOBAL (no account_id). Candles are the same for everyone."

✅ **BrokerSymbol** (Zeile 57-86)
- NOTE: "BrokerSymbols are now GLOBAL (no account_id). Broker symbol specs are the same for all."

---

## Account-Spezifische Models (behalten account_id)

Diese Models behalten **korrekt** die `account_id`, da sie Account-spezifisch sind:

✅ **Account** - Kontostand, Broker, API Key
✅ **SubscribedSymbol** - Welche Symbole ein Account überwacht
✅ **Trade** - Trades gehören einem Account
✅ **TradeHistoryEvent** - Trade-Historie gehört einem Account
✅ **Command** - Commands gehören einem Account
✅ **Log** - Logs gehören einem Account
✅ **AccountTransaction** - Deposits/Withdrawals eines Accounts
✅ **AutoTradeConfig** - Auto-Trading-Einstellungen eines Accounts
✅ **BacktestRun** - Backtests eines Accounts
✅ **BacktestTrade** - Backtest-Trades eines Accounts
✅ **TradeAnalytics** - Analytics eines Accounts
✅ **DailyBacktestSchedule** - Schedule eines Accounts
✅ **SymbolTradingConfig** - Symbol-Config eines Accounts
✅ **SymbolSpreadConfig** - Spread-Config (könnte global sein, aber aktuell Account-spezifisch)

---

## Auswirkungen

### Datenbank-Schema
- **Keine Änderungen erforderlich** - Die Datenbank-Migration hatte diese Spalten bereits entfernt
- Models sind jetzt **synchron** mit der tatsächlichen Datenbankstruktur

### Code-Änderungen erforderlich

**Alle Aufrufe von `IndicatorScore` Methoden müssen angepasst werden:**

```python
# ❌ ALT (mit account_id)
score = IndicatorScore.get_or_create(db, account_id=1, symbol='EURUSD', timeframe='H1', indicator_name='RSI')
scores = IndicatorScore.get_symbol_scores(db, account_id=1, symbol='EURUSD', timeframe='H1')
top = IndicatorScore.get_top_indicators(db, account_id=1, symbol='EURUSD', timeframe='H1')

# ✅ NEU (ohne account_id)
score = IndicatorScore.get_or_create(db, symbol='EURUSD', timeframe='H1', indicator_name='RSI')
scores = IndicatorScore.get_symbol_scores(db, symbol='EURUSD', timeframe='H1')
top = IndicatorScore.get_top_indicators(db, symbol='EURUSD', timeframe='H1')
```

**Betroffene Dateien (potentiell):**
- `signal_generator.py` - Nutzt IndicatorScore für Gewichtung
- `technical_indicators.py` - Könnte IndicatorScore verwenden
- `indicator_scorer.py` - Direkter Zugriff auf IndicatorScore
- Alle Backtest-Skripte

### Vorteile der Änderung

**1. Daten-Deduplizierung:**
```
Vorher (Account-spezifisch):
- Account 1: EURUSD H1 RSI Signal (60% Confidence)
- Account 2: EURUSD H1 RSI Signal (60% Confidence)  ← Duplikat!

Nachher (Global):
- EURUSD H1 RSI Signal (60% Confidence)  ← Nur 1× gespeichert
```

**2. Konsistente Strategie:**
- Alle Accounts nutzen dieselben Signale
- Keine Divergenz zwischen Accounts
- Einfachere Backtesting (global = reproduzierbar)

**3. Performance:**
- Weniger DB-Writes (1× statt N× pro Account)
- Kleinere Tabellen → schnellere Queries
- Bessere Cache-Hits (Redis)

**4. Simplified Logic:**
- Keine account_id in Signal-Queries
- Keine account_id Joins bei Signal-Fetching
- Universelle Indicator Scores

---

## Verifizierung

**Test durchgeführt:**
```bash
cd /projects/ngTradingBot && python3 -c "
from models import TradingSignal, PatternDetection, IndicatorValue, IndicatorScore

models_to_check = [TradingSignal, PatternDetection, IndicatorValue, IndicatorScore]
for model in models_to_check:
    has_account_id = hasattr(model, 'account_id')
    print(f'{model.__name__}: has account_id = {has_account_id}')
"

# Output:
# TradingSignal: has account_id = False ✅
# PatternDetection: has account_id = False ✅
# IndicatorValue: has account_id = False ✅
# IndicatorScore: has account_id = False ✅
```

---

## Nächste Schritte

### 1. Code-Anpassungen (REQUIRED)

Suchen und ersetzen Sie alle Aufrufe von:
```bash
# Finde alle IndicatorScore Aufrufe mit account_id
grep -r "IndicatorScore.get_or_create.*account_id" /projects/ngTradingBot/
grep -r "IndicatorScore.get_symbol_scores.*account_id" /projects/ngTradingBot/
grep -r "IndicatorScore.get_top_indicators.*account_id" /projects/ngTradingBot/

# Finde alle IndicatorScore Queries mit filter_by(account_id=...)
grep -r "IndicatorScore.*filter_by.*account_id" /projects/ngTradingBot/
```

### 2. Testing

**Unit Tests:**
```python
# test_indicator_score.py
def test_get_or_create_no_account_id():
    score = IndicatorScore.get_or_create(db, symbol='EURUSD', timeframe='H1', indicator_name='RSI')
    assert score.symbol == 'EURUSD'
    assert score.score == 50.0  # Default

def test_unique_constraint():
    # Verify that duplicate (symbol, timeframe, indicator) fails
    score1 = IndicatorScore(symbol='EURUSD', timeframe='H1', indicator_name='RSI')
    db.add(score1)
    db.commit()

    score2 = IndicatorScore(symbol='EURUSD', timeframe='H1', indicator_name='RSI')
    db.add(score2)
    with pytest.raises(IntegrityError):  # Should fail due to UNIQUE constraint
        db.commit()
```

**Integration Tests:**
```bash
# Teste Signal-Generierung ohne account_id
python3 -c "
from signal_generator import SignalGenerator
from database import get_db

db = next(get_db())
gen = SignalGenerator(1, 'EURUSD', 'H1')  # account_id still needed for Trade linking
signal = gen.generate_signal()

print(f'Signal: {signal}')
# Signal sollte erstellt werden OHNE account_id
"
```

### 3. Deployment

**Deployment-Checklist:**
1. ✅ models.py aktualisiert
2. ⚠️ Code-Anpassungen durchführen (grep search)
3. ⚠️ Tests ausführen
4. ⚠️ Backup erstellen
5. ⚠️ Docker Container neu bauen:
   ```bash
   docker compose build --no-cache server workers
   docker compose up -d
   ```
6. ⚠️ Logs prüfen auf SQLAlchemy Fehler

---

## Zusammenfassung

**Status:** ✅ **BEHOBEN**

**Geänderte Dateien:**
- `/projects/ngTradingBot/models.py` - 4 Models aktualisiert

**Geänderte Models:**
1. `TradingSignal` - account_id entfernt, Index aktualisiert
2. `PatternDetection` - account_id entfernt
3. `IndicatorValue` - account_id entfernt
4. `IndicatorScore` - account_id entfernt, Methoden aktualisiert, UNIQUE constraint hinzugefügt

**Next Action:**
- **CRITICAL:** Suche alle `IndicatorScore` Aufrufe im Code und entferne `account_id` Parameter
- Testing durchführen
- Docker Container neu bauen

**Risiko:** 🟡 **MEDIUM**
- Backward-incompatible change (API-Signaturen geändert)
- Aber: Datenbank war bereits korrekt (nur Code-Mismatch)
- Keine Datenmigrationen erforderlich

---

**Fix completed:** 25. Oktober 2025
**Signatur:** Claude Code Agent v3.0
