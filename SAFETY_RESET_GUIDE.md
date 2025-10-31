# Safety Monitor & Circuit Breaker Reset Guide

## Übersicht

Dieses Dokument beschreibt, wie du die Safety-Systeme des ngTradingBot zurücksetzen kannst.

## Safety-Systeme

### 1. Daily Drawdown Protection
- **Tabelle**: `daily_drawdown_limits`
- **Funktion**: Schützt vor übermäßigen Tagesverlusten
- **Parameter**:
  - `max_daily_loss_percent`: Max. Tagesverlust in %
  - `max_daily_loss_eur`: Max. Tagesverlust in EUR
  - `circuit_breaker_tripped`: Circuit Breaker Status
  - `limit_reached`: Ob Limit erreicht wurde
  - `protection_enabled`: Ob Schutz aktiviert ist

### 2. Symbol-Level Circuit Breakers
- **Tabelle**: `symbol_trading_config`
- **Funktion**: Pausiert Symbole nach zu vielen Verlusten
- **Parameter**:
  - `consecutive_losses`: Anzahl aufeinanderfolgender Verluste
  - `paused_at`: Zeitpunkt der Pausierung
  - `pause_reason`: Grund der Pausierung
  - `auto_pause_enabled`: Ob Auto-Pause aktiviert ist
  - `pause_after_consecutive_losses`: Schwellwert für Pause

## Reset-Befehle

### Schnell-Reset (Empfohlen)

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownLimit
from sqlalchemy import text
from datetime import date

db = SessionLocal()

# Reset Daily Drawdown Protection
limits = db.query(DailyDrawdownLimit).all()
for limit in limits:
    limit.circuit_breaker_tripped = False
    limit.limit_reached = False
    limit.auto_trading_disabled_at = None
    limit.tracking_date = date.today()
    limit.daily_pnl = 0.0

# Reset Symbol-Level Pauses
db.execute(text('''
    UPDATE symbol_trading_config
    SET consecutive_losses = 0,
        consecutive_wins = 0,
        paused_at = NULL,
        pause_reason = NULL
    WHERE paused_at IS NOT NULL OR consecutive_losses > 0
'''))

db.commit()
db.close()

print('✅ All safety systems reset')
"
```

### Status-Check

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownLimit
from sqlalchemy import text

db = SessionLocal()

# Check Daily Drawdown
limits = db.query(DailyDrawdownLimit).all()
print('Daily Drawdown Protection:')
for limit in limits:
    print(f'  Account {limit.account_id}:')
    print(f'    Circuit Breaker: {\"TRIPPED\" if limit.circuit_breaker_tripped else \"OK\"}')
    print(f'    Daily P/L: €{limit.daily_pnl:.2f}')
    print(f'    Limit Reached: {limit.limit_reached}')
    print()

# Check Symbol Pauses
paused = db.execute(text('''
    SELECT symbol, direction, consecutive_losses, paused_at
    FROM symbol_trading_config
    WHERE paused_at IS NOT NULL OR consecutive_losses >= 3
''')).fetchall()

print('Paused Symbols:')
if paused:
    for row in paused:
        print(f'  {row[0]} {row[1]}: {row[2]} losses, paused at {row[3]}')
else:
    print('  None')

db.close()
"
```

## Einzelne Komponenten zurücksetzen

### Nur Circuit Breakers

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownLimit

db = SessionLocal()
limits = db.query(DailyDrawdownLimit).all()
for limit in limits:
    limit.circuit_breaker_tripped = False
db.commit()
db.close()
print('✅ Circuit Breakers reset')
"
```

### Nur Daily Loss Limits

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownLimit
from datetime import date

db = SessionLocal()
limits = db.query(DailyDrawdownLimit).all()
for limit in limits:
    limit.limit_reached = False
    limit.auto_trading_disabled_at = None
    limit.tracking_date = date.today()
    limit.daily_pnl = 0.0
db.commit()
db.close()
print('✅ Daily loss limits reset')
"
```

### Nur Symbol Pauses

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
db.execute(text('''
    UPDATE symbol_trading_config
    SET consecutive_losses = 0,
        paused_at = NULL,
        pause_reason = NULL
'''))
db.commit()
db.close()
print('✅ Symbol pauses reset')
"
```

## API Endpoints

### Reset via Dashboard API

```bash
# Reset Daily Drawdown (falls API-Endpoint existiert)
curl -X POST http://localhost:9905/api/safety/reset-daily-drawdown

# Reset Circuit Breakers
curl -X POST http://localhost:9905/api/safety/reset-circuit-breakers

# Reset Symbol Pauses
curl -X POST http://localhost:9905/api/safety/reset-symbol-pauses
```

## Automatisches Reset

Die Daily Drawdown Protection resettet sich automatisch jeden Tag um 00:00 UTC.

Wenn du ein manuelles Reset durchführst:
- Circuit Breakers werden sofort freigegeben
- Symbol-Pauses werden aufgehoben
- Consecutive Loss Counter werden auf 0 gesetzt
- Tracking-Datum wird auf heute aktualisiert

## Wann sollte man resetten?

✅ **Gute Gründe für Reset:**
- Neuer Handelstag beginnt
- Nach System-Wartung/Update
- Nach manueller Analyse der Verlustursachen
- Nach Strategie-Anpassungen
- Testphase nach Deployment

❌ **Schlechte Gründe für Reset:**
- Während aktiver Verlustserie
- Ohne Analyse der Ursachen
- Mehrmals pro Tag
- Als "Quick Fix" für schlechte Performance

## Monitoring nach Reset

Nach einem Reset solltest du überwachen:

1. **Trades werden wieder eröffnet**:
   ```bash
   docker logs ngtradingbot_server -f | grep "Opening trade"
   ```

2. **Keine sofortigen Circuit Breaker Trips**:
   ```bash
   docker logs ngtradingbot_server -f | grep "Circuit breaker"
   ```

3. **Dashboard Status**:
   - Öffne http://localhost:9905
   - Prüfe "System Status" Karte
   - Schaue auf aktive Signale

## Troubleshooting

### Trades werden nach Reset nicht eröffnet

```bash
# 1. Prüfe Auto-Trading Status
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownProtection

protection = DailyDrawdownProtection(account_id=3)
result = protection.check_and_update(auto_trading_enabled=True)
print(f'Can Trade: {result[\"allowed\"]}')
if not result['allowed']:
    print(f'Reason: {result[\"reason\"]}')
"

# 2. Prüfe Signal Generator
docker logs ngtradingbot_server | grep "signal_worker" | tail -20

# 3. Prüfe Connection
docker logs ngtradingbot_server | grep "Heartbeat" | tail -5
```

### Circuit Breaker triggered sofort wieder

Dies deutet auf ein systematisches Problem hin:
1. Analysiere die letzten Trades
2. Prüfe Symbol-Performance
3. Überprüfe Risk Management Einstellungen
4. Checke Spread-Konfiguration

### Symbol-Pauses kommen zurück

Wenn Symbole sofort wieder pausiert werden:
1. Prüfe `auto_pause_enabled` Flag
2. Erhöhe `pause_after_consecutive_losses` Schwellwert
3. Deaktiviere Auto-Pause temporär für Analyse

## Konfiguration anpassen

### Daily Loss Limit ändern

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from daily_drawdown_protection import DailyDrawdownLimit

db = SessionLocal()
limit = db.query(DailyDrawdownLimit).filter_by(account_id=3).first()
limit.max_daily_loss_percent = 5.0  # 5% statt 10%
db.commit()
db.close()
print('✅ Daily loss limit updated to 5%')
"
```

### Auto-Pause deaktivieren

```bash
docker exec ngtradingbot_server python3 -c "
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
db.execute(text('''
    UPDATE symbol_trading_config
    SET auto_pause_enabled = false
'''))
db.commit()
db.close()
print('✅ Auto-pause disabled for all symbols')
"
```

---

**Letztes Update**: 2025-10-30
**Status**: ✅ Implementiert und getestet
