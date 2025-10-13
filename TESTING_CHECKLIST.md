# 🧪 Testing Checklist - Neue Features

**Datum**: 2025-10-13
**Status**: Phase 1 - Monitoring

---

## 📋 WAS TESTEN WIR?

### ✅ Test 1: Drawdown Protection Worker
**Zweck**: Verifizieren dass Emergency Stop funktioniert

#### Zu beobachten:
- [ ] Worker läuft ohne Errors
- [ ] Daily P&L wird korrekt berechnet
- [ ] Warning bei -20 EUR erscheint im Log
- [ ] Trading wird bei -30 EUR pausiert
- [ ] Force Close bei -50 EUR unrealized loss

#### Monitoring Commands:
```bash
# Live Logs verfolgen
docker logs ngtradingbot_drawdown_protection -f

# Status Check
docker logs ngtradingbot_drawdown_protection --tail 20
```

#### Success Kriterien:
✅ Läuft stabil (kein Restart)
✅ P&L Berechnung korrekt (manuell verifizieren)
✅ Bei Verlust-Trade: Warning erscheint rechtzeitig

---

### ✅ Test 2: Partial Close Worker
**Zweck**: Verifizieren dass staged exits funktionieren

#### Zu beobachten:
- [ ] Worker läuft ohne Errors
- [ ] Erkennt Trades mit TP/SL korrekt
- [ ] Berechnet Progress toward TP
- [ ] Erstellt PARTIAL_CLOSE Command bei 50% / 75%

#### Monitoring Commands:
```bash
# Live Logs verfolgen
docker logs ngtradingbot_partial_close -f

# Status Check
docker logs ngtradingbot_partial_close --tail 20
```

#### Success Kriterien:
✅ Läuft stabil
✅ "too small" Meldung bei <0.02 lot ist OK
✅ Bei profitablem Trade (>50% TP): PARTIAL_CLOSE command created

**⚠️ Hinweis**: MT5 EA muss PARTIAL_CLOSE_TRADE command type unterstützen!

---

### ✅ Test 3: Strategy Validation Worker
**Zweck**: Verifizieren dass intelligente Exits funktionieren

#### Zu beobachten:
- [ ] Worker läuft ohne Errors
- [ ] Checked Trades mit Profit <-5 EUR
- [ ] Re-validiert Signal bei Verlust-Trades
- [ ] Erstellt CLOSE command nur bei invalid strategy

#### Monitoring Commands:
```bash
# Live Logs verfolgen
docker logs ngtradingbot_strategy_validation -f

# Status Check
docker logs ngtradingbot_strategy_validation --tail 20
```

#### Success Kriterien:
✅ Läuft stabil
✅ Bei losing trade: "Strategy still valid" oder "Strategy invalid"
✅ Keine False-Positives (Close bei valid strategy)

---

## 📊 LIVE MONITORING DASHBOARD

### Quick Check - Alle Worker:
```bash
# Alle Container Status
docker ps --filter "name=ngtradingbot_" --format "table {{.Names}}\t{{.Status}}"

# Alle Worker Logs letzte 10 Zeilen
echo "=== DRAWDOWN PROTECTION ===" && docker logs ngtradingbot_drawdown_protection --tail 10
echo "\n=== PARTIAL CLOSE ===" && docker logs ngtradingbot_partial_close --tail 10
echo "\n=== STRATEGY VALIDATION ===" && docker logs ngtradingbot_strategy_validation --tail 10
```

### Real-Time Monitoring (während Trade läuft):
```bash
# Terminal 1: Drawdown Protection
docker logs ngtradingbot_drawdown_protection -f

# Terminal 2: Partial Close
docker logs ngtradingbot_partial_close -f

# Terminal 3: Strategy Validation
docker logs ngtradingbot_strategy_validation -f
```

---

## 🎯 TEST SCENARIOS

### Scenario 1: NORMALER GEWINN-TRADE
**Setup**: Trade öffnet, läuft in Profit

**Erwartetes Verhalten**:
1. Drawdown Protection: "Daily P&L: +X.XX EUR" (positiv)
2. Partial Close: Bei 50% TP → "Created PARTIAL_CLOSE command" (wenn >0.02 lot)
3. Strategy Validation: "Strategy still valid" (kein Close)

**Erfolg wenn**: Partial Close triggered, kein vorzeitiger Close

---

### Scenario 2: VERLUST-TRADE MIT GÜLTIGER STRATEGIE
**Setup**: Trade läuft -10 EUR loss, aber Strategie noch valid

**Erwartetes Verhalten**:
1. Drawdown Protection: "Daily P&L: -10.XX EUR" (unter Warning-Level)
2. Partial Close: Skipped (kein Profit)
3. Strategy Validation: "Strategy still valid" → KEIN Close command

**Erfolg wenn**: Trade bleibt offen (Strategy valid)

---

### Scenario 3: VERLUST-TRADE MIT UNGÜLTIGER STRATEGIE
**Setup**: Trade läuft -10 EUR loss, Pattern verschwunden

**Erwartetes Verhalten**:
1. Drawdown Protection: "Daily P&L: -10.XX EUR"
2. Partial Close: Skipped
3. Strategy Validation: "Strategy NO LONGER VALID" → Close command created

**Erfolg wenn**: Trade wird geschlossen (intelligent exit)

---

### Scenario 4: DAILY LOSS LIMIT ERREICHT
**Setup**: Mehrere Verlust-Trades, total -30 EUR

**Erwartetes Verhalten**:
1. Drawdown Protection: "DAILY LOSS LIMIT EXCEEDED"
2. System: Auto-trading pausiert
3. Keine neuen Trades mehr heute

**Erfolg wenn**: System stoppt korrekt

---

### Scenario 5: ACCOUNT EMERGENCY
**Setup**: Unrealized loss -50 EUR

**Erwartetes Verhalten**:
1. Drawdown Protection: "ACCOUNT EMERGENCY LIMIT EXCEEDED"
2. System: ALLE Trades sofort geschlossen
3. Auto-trading pausiert

**Erfolg wenn**: Force Close All funktioniert

---

## ⚠️ BEKANNTE LIMITIERUNGEN (Noch zu implementieren)

### 1. Partial Close EA Support
**Problem**: EA muss `PARTIAL_CLOSE_TRADE` command type unterstützen
**Workaround**: Worker erstellt Commands, aber EA könnte sie ignorieren
**Fix**: EA anpassen für partial close support

**Check**:
```bash
# Commands Tabelle prüfen
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "
SELECT id, command_type, status, payload
FROM commands
WHERE command_type = 'PARTIAL_CLOSE_TRADE'
ORDER BY created_at DESC LIMIT 5;"
```

**Status**: ⏳ Pending (EA Update)

---

### 2. Position Sizer Integration
**Problem**: Lot Size noch statisch (vermutlich 0.01 oder 0.05)
**Impact**: Keine Confidence-based Sizing yet
**Fix**: Integration in auto_trade.py (~30min)

**Status**: ⏳ Pending

---

### 3. News Filter Integration
**Problem**: Signale werden nicht geblockt vor News
**Impact**: Potentiell schlechte Entries bei News
**Fix**: Integration in signal_generator.py (~20min)

**Status**: ⏳ Pending

---

## 📝 TEST LOG

### Trade 1: ____________ (Fill in während Test)
- **Symbol**: _______
- **Direction**: BUY/SELL
- **Entry**: _______
- **TP/SL**: _______ / _______
- **Lot Size**: _______
- **Result**: _______

**Drawdown Protection**:
- [ ] Daily P&L correctly calculated
- [ ] No false alarms
- [ ] _______________________

**Partial Close**:
- [ ] Recognized trade
- [ ] Progress calculated: _____%
- [ ] Triggered at: _____%
- [ ] _______________________

**Strategy Validation**:
- [ ] Strategy check performed
- [ ] Result: Valid / Invalid
- [ ] Action: None / Close
- [ ] _______________________

---

### Trade 2: ____________
(Repeat format)

---

## ✅ WANN IST TESTING ABGESCHLOSSEN?

### Minimum Requirements:
- [x] Alle 3 Worker laufen stabil (kein Crash)
- [ ] Mindestens 1 Trade beobachtet (voller Lifecycle)
- [ ] Drawdown Protection berechnet P&L korrekt
- [ ] Strategy Validation führt Re-Check durch
- [ ] Partial Close erkennt Trade richtig

### Optional (Nice to Have):
- [ ] Partial Close triggered (Trade erreicht 50% TP)
- [ ] Daily Loss Warning gesehen (bei Verlust)
- [ ] Strategy Validation closed einen invalid trade

---

## 🚀 NACH TESTING: INTEGRATION PHASE

Wenn alle Tests ✅:
1. Position Sizer Integration (30min)
2. News Filter Integration (20min)
3. EA Update für Partial Close Support (1-2h)

---

**Testing Start**: ___________
**Testing Ende**: ___________
**Status**: ⏳ In Progress / ✅ Completed

*Nutze diese Checklist während der nächsten Trades!*
