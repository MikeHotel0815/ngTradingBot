# 🔍 Warum wird EURUSD Signal NICHT getradet?
**Diagnose-Guide**

---

## ❓ Mögliche Gründe (Sortiert nach Wahrscheinlichkeit)

### 1. **Confidence zu niedrig für Symbol-Schwellenwert** (Häufigster Grund)

**Problem:**
Signal hat z.B. 55% Confidence, aber EURUSD benötigt 60% (dynamisch angepasst).

**Prüfen:**
```python
# In auto_trader.py:727-732
if signal.confidence < symbol_min_confidence:
    return {'execute': False, 'reason': f'Low confidence ({signal.confidence}% < {symbol_min_confidence}%)'}
```

**Logs suchen:**
```bash
grep "Low confidence" /var/log/ngTradingBot/auto_trader.log | grep EURUSD
```

**Lösung:**
- Symbol-Konfiguration anpassen: `min_confidence_threshold` für EURUSD senken
- Oder: Signal-Generator Confidence verbessern

---

### 2. **Symbol Status ist "paused" oder "disabled"**

**Problem:**
EURUSD wurde automatisch pausiert (z.B. nach Verlusten) oder manuell deaktiviert.

**Prüfen:**
```sql
SELECT symbol, status, pause_reason, min_confidence_threshold
FROM symbol_dynamic_config
WHERE symbol = 'EURUSD';
```

**Mögliche Status:**
- `active` ✅ → Handel erlaubt
- `paused` ⚠️ → Temporär pausiert (Cooldown läuft)
- `disabled` ❌ → Komplett deaktiviert

**Logs suchen:**
```bash
grep "Symbol config: symbol_disabled\|paused" auto_trader.log | grep EURUSD
```

**Lösung:**
- Manuell reaktivieren in Dashboard → Symbol Config
- Oder warten bis Cooldown abgelaufen ist

---

### 3. **Auto-Trading global deaktiviert**

**Problem:**
Auto-Trading ist systemweit ausgeschaltet.

**Prüfen:**
```sql
SELECT autotrade_enabled, autotrade_risk_profile, autotrade_min_confidence
FROM global_settings;
```

**Logs suchen:**
```bash
grep "Auto-Trading disabled" auto_trader.log | tail -20
```

**Lösung:**
Dashboard → Settings → "Enable Auto-Trading"

---

### 4. **Max Open Trades erreicht**

**Problem:**
- Global: Maximale Anzahl offener Trades erreicht
- Symbol-spezifisch: Zu viele EURUSD Trades offen

**Prüfen Auto-Trader:**
```python
# auto_trader.py checkt:
# 1. Globales Limit (z.B. max 10 Trades gesamt)
# 2. Symbol Limit (z.B. max 2 EURUSD Trades)
# 3. Confidence-basiertes Limit (höhere Confidence = mehr Trades erlaubt)
```

**Logs suchen:**
```bash
grep "max.*trades\|position limit" auto_trader.log | grep EURUSD
```

**Lösung:**
- Trades schließen um Platz zu schaffen
- Max Trades Limit erhöhen in Symbol Config

---

### 5. **Dynamic Confidence Threshold zu hoch**

**Problem:**
Dynamische Berechnung erhöht Schwellenwert basierend auf:
- **Session** (Asiatische Session = höhere Confidence nötig)
- **Volatilität** (Hohe Volatilität = höhere Confidence nötig)
- **Risk Profile** (Conservative = höhere Confidence nötig)

**Code:**
```python
# auto_trader.py:693-725
required_conf, breakdown = calculator.calculate_required_confidence(
    symbol=signal.symbol,
    risk_profile=self.risk_profile,
    session=session_name,
    volatility=volatility
)

# Nimmt das HÖHERE von static oder dynamic:
symbol_min_confidence = max(symbol_min_confidence, required_conf)
```

**Logs suchen:**
```bash
grep "Dynamic Confidence for EURUSD" auto_trader.log | tail -10
```

**Beispiel Log:**
```
🎯 Dynamic Confidence for EURUSD: Required=65.0%
   (profile=conservative, session=asian, volatility=1.5x)
```

**Lösung:**
- Risk Profile ändern: `normal` statt `conservative`
- Oder: Während besserer Session traden (London/NY)

---

### 6. **Spread zu hoch**

**Problem:**
EURUSD Spread ist höher als erlaubt (z.B. 20 Pips statt normal 2 Pips).

**Prüfen:**
```python
# spread_utils.py checkt:
if current_spread > typical_spread * max_multiplier:
    # Trade blockiert
```

**Logs suchen:**
```bash
grep "spread.*high\|spread validation failed" auto_trader.log | grep EURUSD
```

**Lösung:**
- Warten bis Spread normal ist (oft während News-Events hoch)
- Spread-Limits anpassen in `symbol_spread_config`

---

### 7. **TP/SL Validation fehlgeschlagen**

**Problem:**
Take Profit oder Stop Loss sind ungültig:
- TP = 0 oder SL = 0
- TP in falscher Richtung (BUY aber TP < Entry)
- SL zu eng (< 0.05% für Forex)
- TP/SL Ratio unrealistisch

**Code:**
```python
# auto_trader.py:754-819
def _validate_tp_sl(self, signal, adjusted_sl):
    # Check 1: TP and SL must not be zero
    if tp == 0 or sl == 0:
        return False

    # Check 2: Direction correct
    if signal.signal_type == 'BUY':
        if tp <= entry or sl >= entry:
            return False

    # Check 3: Minimum SL distance (0.05% for forex)
    if sl_distance_pct < min_sl_distance_pct:
        return False
```

**Logs suchen:**
```bash
grep "TP/SL validation failed\|SL too tight" auto_trader.log | grep EURUSD
```

**Lösung:**
- Signal Generator TP/SL Berechnung überprüfen
- Minimum SL Distance anpassen wenn nötig

---

### 8. **Missing Entry/SL/TP Prices**

**Problem:**
Signal hat keine Entry Price, SL oder TP definiert.

**Code:**
```python
# auto_trader.py:734-739
if not signal.entry_price or not signal.sl_price or not signal.tp_price:
    return {'execute': False, 'reason': 'Missing entry/SL/TP'}
```

**Logs suchen:**
```bash
grep "Missing entry/SL/TP" auto_trader.log | grep EURUSD
```

**Lösung:**
Signal Generator Bug fixen - sollte immer alle Prices setzen

---

### 9. **Circuit Breaker aktiv**

**Problem:**
Nach mehreren schnellen Verlusten wurde Auto-Trading automatisch pausiert.

**Code:**
```python
# auto_trader.py:1550
CIRCUIT_BREAKER_COOLDOWN_MINUTES = 5  # Wait 5 min before auto-resume
```

**Logs suchen:**
```bash
grep "CIRCUIT BREAKER\|circuit breaker" auto_trader.log | tail -10
```

**Lösung:**
- Warten 5 Minuten
- Oder manuell wieder aktivieren
- Oder Circuit Breaker Logik anpassen

---

### 10. **Daily Drawdown Limit erreicht**

**Problem:**
Täglicher Verlust-Limit wurde erreicht, Auto-Trading pausiert.

**Logs suchen:**
```bash
grep "drawdown\|daily loss limit" auto_trader.log | tail -10
```

**Lösung:**
- Warten bis nächster Tag (00:00 UTC)
- Oder Drawdown Limit erhöhen in Settings

---

## 🔧 Diagnose-Workflow

### Schritt 1: Log-Datei prüfen

```bash
cd /projects/ngTradingBot
tail -100 /var/log/ngTradingBot/auto_trader.log | grep EURUSD
```

Suchen nach:
```
❌ Rejecting signal
✅ Executing signal
🛑 Signal blocked:
```

---

### Schritt 2: Datenbank prüfen

```sql
-- EURUSD Konfiguration
SELECT * FROM symbol_dynamic_config WHERE symbol = 'EURUSD';

-- Letzte EURUSD Signale
SELECT
    id,
    generated_at,
    signal_type,
    confidence,
    status,
    executed
FROM trading_signals
WHERE symbol = 'EURUSD'
ORDER BY generated_at DESC
LIMIT 10;

-- Offene EURUSD Trades
SELECT COUNT(*) FROM trades
WHERE symbol = 'EURUSD' AND status = 'open';
```

---

### Schritt 3: Dashboard prüfen

1. **Settings → Auto-Trading**
   - Is Auto-Trading enabled? ✅
   - Risk Profile? (normal/conservative/aggressive)
   - Min Confidence? (50%?)

2. **Symbol Configuration → EURUSD**
   - Status? (active/paused/disabled)
   - Min Confidence Threshold?
   - Max Open Trades?
   - Pause Reason?

3. **Signals Page → EURUSD**
   - Are signals being generated?
   - What's the confidence?
   - Status = "pending" or "expired"?

---

## 🎯 Schnelle Lösungen

### Problem: Confidence zu niedrig
```sql
-- EURUSD Confidence Threshold senken
UPDATE symbol_dynamic_config
SET min_confidence_threshold = 50.0
WHERE symbol = 'EURUSD';
```

### Problem: Symbol pausiert
```sql
-- EURUSD reaktivieren
UPDATE symbol_dynamic_config
SET status = 'active', pause_reason = NULL
WHERE symbol = 'EURUSD';
```

### Problem: Auto-Trading aus
```sql
-- Auto-Trading global aktivieren
UPDATE global_settings
SET autotrade_enabled = TRUE;
```

---

## 📊 Debug Mode aktivieren

```python
# In auto_trader.py - setze Log Level auf DEBUG
import logging
logging.basicConfig(level=logging.DEBUG)
```

Dann sehen Sie ALLE Checks:
```
DEBUG: Evaluating EURUSD signal #12345
DEBUG: Confidence check: 55.0% >= 50.0% ✅
DEBUG: Symbol status: active ✅
DEBUG: Max trades check: 1/2 ✅
DEBUG: Dynamic confidence: 65.0% required ❌
REJECTED: Low confidence (55.0% < 65.0%)
```

---

## ✅ Checkliste

- [ ] Auto-Trading global enabled?
- [ ] EURUSD status = "active"?
- [ ] Signal Confidence >= Min Threshold?
- [ ] Max Open Trades nicht erreicht?
- [ ] TP/SL sind valide?
- [ ] Spread normal?
- [ ] Kein Circuit Breaker aktiv?
- [ ] Kein Daily Drawdown Limit erreicht?

---

## 🆘 Wenn nichts hilft

**Logs mit Details teilen:**
```bash
# Letzte 200 Zeilen mit EURUSD
grep EURUSD /var/log/ngTradingBot/auto_trader.log | tail -200

# Aktuelle Symbol Konfiguration
docker exec -it ngtradingbot_workers_1 python3 -c "
from database import SessionLocal
from models import SymbolDynamicConfig
db = SessionLocal()
cfg = db.query(SymbolDynamicConfig).filter_by(symbol='EURUSD').first()
print(f'Status: {cfg.status}')
print(f'Min Confidence: {cfg.min_confidence_threshold}%')
print(f'Pause Reason: {cfg.pause_reason}')
"
```

Dann kann ich genau sehen, welcher Check fehlschlägt! 🔍
