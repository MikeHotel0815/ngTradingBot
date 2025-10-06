# Smart Trailing Stop System

## Übersicht

Das ngTradingBot System verfügt über ein intelligentes **4-Stufen Trailing Stop System**, das Gewinne progressiv sichert, während der Trade sich in Richtung Take Profit bewegt.

## Architektur

### Komponenten
1. **TrailingStopManager** ([trailing_stop_manager.py](trailing_stop_manager.py))
   - Zentrale Logik für Trailing Stop Berechnung
   - 4 verschiedene Stufen mit unterschiedlicher Aggressivität
   - Validierung und Safety-Checks

2. **TradeMonitor** ([trade_monitor.py](trade_monitor.py))
   - Integration des Trailing Stop Managers
   - Überwacht alle offenen Trades alle 5 Sekunden
   - Führt Trailing Stop Updates automatisch durch

3. **GlobalSettings** ([models.py](models.py#L550))
   - Konfigurierbare Parameter für alle 4 Stufen
   - Aktivierung/Deaktivierung pro Stufe
   - Safety-Limits (min/max SL Bewegung)

## Die 4 Stufen

### Stage 1: Break-Even Move 🛡️
**Trigger:** 30% des TP-Abstands erreicht

**Aktion:** SL wird auf Entry-Level verschoben (+5 Punkte Offset für Spread)

**Zweck:** Trade wird risikofrei - maximaler Schutz vor Verlust

**Beispiel:**
```
Entry:    1.10000
TP:       1.10100  (100 Punkte Abstand)
Profit:   +30 Punkte (30% erreicht)
→ Neue SL: 1.10005 (Entry + 5 Punkte)
```

---

### Stage 2: Partial Trailing 📊
**Trigger:** 50% des TP-Abstands erreicht

**Aktion:** SL folgt dem Preis mit 40% Abstand

**Zweck:** Gewinne sichern, aber Raum für weitere Bewegung lassen

**Beispiel:**
```
Entry:     1.10000
Current:   1.10050  (50% zur TP)
TP:        1.10100
→ Trail Distance: 40 Punkte (40% von 100)
→ Neue SL: 1.10010 (Current - Trail Distance)
```

---

### Stage 3: Aggressive Trailing 🎯
**Trigger:** 75% des TP-Abstands erreicht

**Aktion:** SL folgt dem Preis mit nur noch 25% Abstand

**Zweck:** Gewinne aggressiv sichern, Trade ist sehr profitabel

**Beispiel:**
```
Entry:     1.10000
Current:   1.10075  (75% zur TP)
TP:        1.10100
→ Trail Distance: 25 Punkte (25% von 100)
→ Neue SL: 1.10050 (Current - Trail Distance)
```

---

### Stage 4: Near-TP Protection 🔒
**Trigger:** 90% des TP-Abstands erreicht

**Aktion:** SL folgt extrem eng mit nur 15% Abstand

**Zweck:** Maximum Profit sichern, Trade kurz vor TP

**Beispiel:**
```
Entry:     1.10000
Current:   1.10090  (90% zur TP)
TP:        1.10100
→ Trail Distance: 15 Punkte (15% von 100)
→ Neue SL: 1.10075 (Current - Trail Distance)
```

---

## Safety Features 🛡️

### 1. Minimaler SL-Abstand
- SL muss mindestens **10 Punkte** vom aktuellen Preis entfernt bleiben
- Verhindert zu enges Setzen und sofortiges Auslösen

### 2. Maximale SL-Bewegung
- SL darf maximal **100 Punkte** pro Update bewegen
- Verhindert fehlerhafte extreme Sprünge

### 3. Nur Gewinn-Richtung
- **BUY:** SL kann nur nach oben bewegt werden
- **SELL:** SL kann nur nach unten bewegt werden
- Niemals verschlechterte Position!

### 4. Rate Limiting
- Pro Trade nur 1 Update alle 5 Sekunden
- Verhindert exzessives Command-Flooding

### 5. Validierung
- SL muss auf korrekter Seite des Preises sein
- Bewegung muss mindestens 0.1 Pips sein
- Alle Parameter werden vor Ausführung geprüft

---

## Konfiguration

### Standard-Einstellungen (GlobalSettings)

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `trailing_stop_enabled` | `TRUE` | Master-Switch |
| **Stage 1: Break-Even** | | |
| `breakeven_enabled` | `TRUE` | Break-Even aktiviert |
| `breakeven_trigger_percent` | `30.0` | Bei 30% TP-Distanz |
| `breakeven_offset_points` | `5.0` | +5 Punkte Offset |
| **Stage 2: Partial** | | |
| `partial_trailing_trigger_percent` | `50.0` | Bei 50% TP-Distanz |
| `partial_trailing_distance_percent` | `40.0` | 40% hinten nach |
| **Stage 3: Aggressive** | | |
| `aggressive_trailing_trigger_percent` | `75.0` | Bei 75% TP-Distanz |
| `aggressive_trailing_distance_percent` | `25.0` | 25% hinten nach |
| **Stage 4: Near-TP** | | |
| `near_tp_trigger_percent` | `90.0` | Bei 90% TP-Distanz |
| `near_tp_trailing_distance_percent` | `15.0` | 15% hinten nach |
| **Safety** | | |
| `min_sl_distance_points` | `10.0` | Min 10 Punkte |
| `max_sl_move_per_update` | `100.0` | Max 100 Punkte |

### Einstellungen ändern

Über Database:
```sql
UPDATE global_settings
SET breakeven_trigger_percent = 25.0,
    aggressive_trailing_distance_percent = 20.0
WHERE id = 1;
```

Oder über Python:
```python
from models import GlobalSettings
settings = GlobalSettings.get_settings(db)
settings.breakeven_trigger_percent = 25.0
settings.aggressive_trailing_distance_percent = 20.0
db.commit()
```

---

## Log-Ausgaben

### Trailing Stop Applied
```
🎯 Trailing Stop Applied: BTCUSD #12345678 - Stage: breakeven, SL: 24469.40000 → 24470.40000
```

### TradeMonitor Logging
```
🎯 Trailing Stop [BREAKEVEN]: Trade 12345678 (BTCUSD) - Moving SL from 24469.40000 to 24470.40000 (Break-even + 5.0 points)
```

### Command Creation
```
✅ SL Modify command created: Ticket 12345678 → New SL 24470.40000 (Break-even + 5.0 points)
```

---

## Workflow

1. **TradeMonitor Loop** (alle 5 Sekunden)
   - Lädt alle offenen Trades
   - Berechnet aktuellen P&L pro Trade

2. **Trailing Stop Check** (für jeden Trade mit Profit > 0)
   - Prüft ob Update-Intervall erreicht (5s)
   - Lädt aktuelle Settings aus DB
   - Berechnet welche Stage getriggert wird

3. **Stage Berechnung**
   - Berechnet Profit als % von TP-Distanz
   - Wählt höchste getriggerte Stage
   - Berechnet neuen SL basierend auf Stage-Regeln

4. **Validierung**
   - Min/Max Distance Checks
   - Richtung (nur bessere Position)
   - Movement-Limits

5. **Command Execution**
   - Erstellt `modify_sl` Command in DB
   - MT5 EA holt Command und führt aus
   - Trade.sl wird aktualisiert

6. **Logging**
   - Stage, alte SL, neue SL, Grund
   - Counter für Statistics

---

## Integration mit MT5 EA

Der TrailingStopManager erstellt `Command` Objekte in der Datenbank:

```python
Command(
    account_id=trade.account_id,
    command_type='modify_sl',
    ticket=trade.ticket,
    symbol=trade.symbol,
    sl=new_sl,
    status='pending',
    metadata={
        'trailing_stop': True,
        'reason': 'Break-even + 5.0 points',
        'old_sl': 24469.40
    }
)
```

Der MT5 EA (ServerConnector.mq5) pollt diese Commands und führt sie aus:
- Holt pending Commands alle 1-2 Sekunden
- Führt `OrderModify()` aus
- Setzt Status auf `completed` oder `failed`

---

## Performance Metrics

Verfügbar in `TradeMonitor` Instance:
```python
monitor = get_monitor()
print(f"Trailing stops processed: {monitor.trailing_stops_processed}")
```

Verfügbar in Command Metadata:
```sql
SELECT
    COUNT(*) as trailing_stop_commands,
    AVG((metadata->>'old_sl')::numeric - sl) as avg_sl_improvement
FROM commands
WHERE command_type = 'modify_sl'
  AND metadata->>'trailing_stop' = 'true'
  AND status = 'completed';
```

---

## Deaktivierung

### Global deaktivieren:
```sql
UPDATE global_settings SET trailing_stop_enabled = FALSE;
```

### Nur Break-Even deaktivieren:
```sql
UPDATE global_settings SET breakeven_enabled = FALSE;
```

### Pro Trade deaktivieren:
Aktuell nicht implementiert - würde Trade-spezifisches Flag erfordern

---

## Testing & Validation

### Unit Tests (TODO)
```bash
pytest tests/test_trailing_stop_manager.py
```

### Integration Tests
1. Starte Trade mit bekanntem Entry/TP/SL
2. Simuliere Preis-Bewegung
3. Beobachte Trailing Stop Aktivierung
4. Verifiziere SL Updates in DB

### Production Monitoring
```sql
-- Trades mit aktiven Trailing Stops
SELECT
    t.ticket,
    t.symbol,
    t.open_price,
    t.sl,
    t.tp,
    COUNT(c.id) as sl_modifications
FROM trades t
LEFT JOIN commands c ON c.ticket = t.ticket
    AND c.command_type = 'modify_sl'
    AND c.metadata->>'trailing_stop' = 'true'
WHERE t.status = 'open'
GROUP BY t.ticket;
```

---

## Bekannte Limitierungen

1. **Keine Tick-genaue Reaktion**: Trailing Stop prüft nur alle 5 Sekunden
2. **EA Latenz**: MT5 EA muss Commands abholen und ausführen (1-3 Sekunden)
3. **Slippage**: Bei schnellen Märkten kann SL nicht exakt gesetzt werden
4. **Spread-Handling**: Aktuell nur fixer 5-Punkt-Offset bei Break-Even

---

## Zukünftige Verbesserungen

- [ ] **Symbol-spezifische Settings**: Unterschiedliche Trailing-Strategien pro Symbol
- [ ] **Timeframe-abhängig**: Aggressivere Trailing-Stops für Scalping (M1/M5)
- [ ] **Volatilitäts-Anpassung**: Trail-Distance basierend auf ATR
- [ ] **Machine Learning**: Optimale Trigger-Punkte aus Backtest-Daten lernen
- [ ] **Partial Close**: Bei bestimmten Stufen Position teilweise schließen
- [ ] **UI Dashboard**: Visualisierung der Trailing Stop Stages in Echtzeit

---

## Kontakt & Support

Bei Fragen oder Problemen:
- GitHub Issues: [ngTradingBot Issues](https://github.com/MikeHotel0815/ngtradingbot)
- Logs prüfen: `docker logs ngtradingbot_server -f | grep "Trailing"`
