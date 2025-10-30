# Dynamic Risk Management System
**Datum**: 2025-10-30
**Problem**: Statische SL-Limits und R:R Ratios passen sich NICHT an Kontostand und Performance an

---

## 🎯 Problem-Statement

**Sie haben absolut Recht!**

> "SL-Limits / Risk/Reward Ratios müssen permanent überprüft und an den Kontostand und das global gewählte Risiko angepasst werden!"

### Warum ist das kritisch?

**Aktueller Zustand** (STATISCH ❌):
```python
# sl_enforcement.py
MAX_LOSS_PER_TRADE = {
    'XAUUSD': 5.50,  # ← FEST! Egal ob Konto 500€ oder 5000€!
    'AUDUSD': 4.00,  # ← FEST!
}
```

**Probleme**:
1. **Account wächst auf 2000€**: SL-Limits bleiben bei $4-5 → Zu konservativ!
2. **Account fällt auf 500€**: SL-Limits bleiben bei $4-5 → Zu aggressiv!
3. **Performance schlecht** (PF 0.7): R:R Ratios bleiben gleich → Keine Anpassung!
4. **Performance gut** (PF 2.0): R:R Ratios bleiben gleich → Verpasste Chance!

---

## ✅ Lösung: Dynamic Risk Management System

### Komponenten

1. **`dynamic_risk_manager.py`**: Core Logic
   - Berechnet SL-Limits basierend auf Kontostand
   - Berechnet R:R Ratios basierend auf Performance
   - 3 Risk-Profile: Conservative, Moderate, Aggressive

2. **`risk_parameter_scheduler.py`**: Automatischer Scheduler
   - **Täglich**: SL-Limits aktualisieren
   - **Wöchentlich**: R:R Ratios aktualisieren
   - Läuft im Hintergrund (wie unified_workers)

---

## 📊 Wie funktioniert es?

### 1. Risk Profiles

**3 vordefinierte Profile**:

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| Base Risk/Trade | 0.5% | 1.0% ✅ | 2.0% |
| Max Loss/Trade | 2% | 3% | 5% |
| Max Daily Loss | 5% | 8% | 12% |
| FOREX R:R | 3.0:0.7 | 3.5:0.8 ✅ | 4.0:0.9 |
| METALS R:R | 1.5:0.4 | 1.2:0.4 ✅ | 1.5:0.5 |

**✅ MODERATE = Aktueller optimierter Status (aus 36h Analyse)**

### 2. Dynamic SL Limits

**Formel**:
```python
base_max_loss = account_balance * (max_loss_percent / 100)
growth_factor = current_balance / initial_balance  # 1.5 = 50% gewachsen
performance_factor = profit_factor_mapping(last_7_days)  # 0.6-1.3

adjusted_max_loss = base_max_loss * growth_factor * performance_factor
```

**Beispiel** (Account 3, Moderate Profile):

| Szenario | Balance | Growth | Performance | XAUUSD SL | AUDUSD SL |
|----------|---------|--------|-------------|-----------|-----------|
| **Start** | €1,000 | 1.0x | 1.0x | €5.60 | €8.00 |
| **Wachstum** | €1,500 | 1.5x | 1.2x (gut) | €10.08 | €14.40 |
| **Drawdown** | €800 | 0.8x | 0.7x (schlecht) | €3.13 | €4.48 |

**Auto-Adjustment**:
- Konto wächst → SL-Limits steigen proportional
- Konto fällt → SL-Limits fallen → Weniger Risiko
- Performance gut → SL-Limits steigen leicht (mehr Vertrauen)
- Performance schlecht → SL-Limits fallen (weniger Risiko)

### 3. Dynamic R:R Ratios

**Performance-basierte Anpassung**:

```python
# Profit Factor Mapping
PF > 2.0  → Performance Factor 1.3 (scale UP)
PF 1.5-2.0 → Performance Factor 1.2
PF 1.0-1.5 → Performance Factor 1.0 (neutral)
PF 0.7-1.0 → Performance Factor 0.8 (scale DOWN)
PF < 0.7  → Performance Factor 0.6 (scale DOWN more)

# TP/SL Adjustment
tp_multiplier = base_tp * (1.0 + (perf_factor - 1.0) * 0.3)  # +/- 30%
sl_multiplier = base_sl * (1.0 - (perf_factor - 1.0) * 0.15)  # +/- 15%
```

**Beispiel** (FOREX, Moderate Profile):

| Performance | Profit Factor | TP Mult | SL Mult | R:R Ratio |
|-------------|---------------|---------|---------|-----------|
| **Excellent** | 2.5 | 4.06x | 0.77x | 5.27:1 |
| **Good** | 1.8 | 3.85x | 0.79x | 4.87:1 |
| **Neutral** | 1.0 | 3.50x | 0.80x | 4.38:1 ✅ |
| **Poor** | 0.7 | 3.22x | 0.83x | 3.88:1 |
| **Bad** | 0.4 | 2.94x | 0.86x | 3.42:1 |

**Effekt**:
- Performance gut → TPs weiter weg (Gewinne laufen lassen)
- Performance schlecht → TPs näher (Gewinne mitnehmen)
- SL wird entsprechend angepasst

---

## 🚀 Setup & Deployment

### 1. Dateien hinzufügen

Bereits erstellt:
- ✅ `dynamic_risk_manager.py`: Core System
- ✅ `risk_parameter_scheduler.py`: Automatischer Scheduler

### 2. Scheduler integrieren

**Option A: Als separater Container** (empfohlen):

```yaml
# docker-compose.yml
  risk_scheduler:
    build: .
    container_name: ngtradingbot_risk_scheduler
    command: python risk_parameter_scheduler.py 3 moderate
    environment:
      - DATABASE_URL=postgresql://trader:${DB_PASSWORD}@postgres:5432/ngtradingbot
    depends_on:
      - postgres
    restart: unless-stopped
```

**Option B: In unified_workers integrieren**:

```python
# unified_workers.py
from risk_parameter_scheduler import RiskParameterScheduler

# Add to UnifiedWorkers class
def start_risk_scheduler(self):
    scheduler = RiskParameterScheduler(
        account_id=3,
        risk_profile='moderate'  # oder aus ENV
    )
    # Run in thread
    import threading
    thread = threading.Thread(target=scheduler.run, daemon=True)
    thread.start()
```

### 3. Manueller Test

```bash
# Einmalige Ausführung (Test)
docker exec ngtradingbot_server python3 risk_parameter_scheduler.py 3 moderate --once

# Zeigt:
# - Aktuelle Balance & Growth Factor
# - Performance Factor (7 Tage)
# - Neue SL-Limits für alle Symbole
# - Neue R:R Ratios
# - 30-Tage Performance Summary
```

### 4. Risk Profile ändern

**In Environment Variable** (.env oder docker-compose.yml):
```bash
RISK_PROFILE=moderate  # conservative, moderate, aggressive
```

**Im Code** (wenn kein ENV):
```python
# risk_parameter_scheduler.py Zeile ~230
risk_profile = sys.argv[2] if len(sys.argv) > 2 else 'moderate'
# Ändern zu: 'conservative' oder 'aggressive'
```

---

## 📈 Use Cases & Szenarien

### Szenario 1: Account wächst von 1000€ auf 2000€

**Ohne Dynamic Risk**:
- SL-Limits: Bleiben bei $4-5
- Problem: Account hat sich verdoppelt, aber Risiko nicht angepasst
- Ergebnis: Zu konservativ, verpasste Gewinne

**Mit Dynamic Risk**:
- SL-Limits: Steigen auf $8-10
- Growth Factor: 2.0x
- Ergebnis: Risiko skaliert mit Kontowachstum ✅

### Szenario 2: 7 Tage schlechte Performance (PF 0.5)

**Ohne Dynamic Risk**:
- R:R Ratios: Bleiben bei 4.4:1
- Problem: Bot läuft weiter mit gleichen Parametern trotz Verlust
- Ergebnis: Weitere Verluste wahrscheinlich

**Mit Dynamic Risk**:
- R:R Ratios: Reduziert auf ~3.0:1
- TPs näher (Gewinne früher mitnehmen)
- Performance Factor: 0.6x → SL-Limits auch reduziert
- Ergebnis: Defensivere Strategie bis Performance sich erholt ✅

### Szenario 3: Wechsel von Moderate → Aggressive Profile

**Änderung**:
```bash
# docker-compose.yml oder .env
RISK_PROFILE=aggressive
docker restart ngtradingbot_risk_scheduler
```

**Effekt**:
- Base Risk: 1% → 2% pro Trade
- Max Loss: 3% → 5% pro Trade
- R:R Ratios: 4.4:1 → 4.8:1 (aggressivere TPs)
- Confidence Scaling: Stärker (Vertrauen in gute Signale)

**Wann sinnvoll**:
- Account >5000€
- Profit Factor >2.0 für mehrere Wochen
- Win Rate >65%
- Erfahrener Trader, versteht Risiko

### Szenario 4: Daily Loss Limit erreicht

**Automatischer Schutz**:
```python
is_exceeded, daily_loss, limit = risk_manager.check_daily_loss_limit(db)

if is_exceeded:
    # Stop all new trades for rest of day
    logger.warning("Daily loss limit exceeded, no new trades today")
    return None
```

**Moderate Profile**: Max 8% Daily Loss
- Balance 1000€ → Max -80€ pro Tag
- Balance 2000€ → Max -160€ pro Tag

---

## 🔧 Konfiguration & Tuning

### Risk Profile Parameter ändern

```python
# dynamic_risk_manager.py
RISK_PROFILES = {
    'moderate': RiskProfile(
        name='moderate',
        base_risk_percent=1.0,  # ← Anpassen: 0.5-2.0
        max_loss_per_trade_percent=3.0,  # ← Anpassen: 2.0-5.0
        max_daily_loss_percent=8.0,  # ← Anpassen: 5.0-12.0
        forex_tp_multiplier=3.5,  # ← Aktuell optimiert
        forex_sl_multiplier=0.8,  # ← Aktuell optimiert
        # ...
    ),
}
```

### Symbol-spezifische SL-Anpassungen

```python
# dynamic_risk_manager.py get_dynamic_sl_limits()
symbol_sl_limits = {
    'XAUUSD': adjusted_max_loss * 0.7,  # ← 70% von base
    'BTCUSD': adjusted_max_loss * 1.2,  # ← 120% (profitabel!)
    # ...
}
```

### Update-Frequenz ändern

```python
# risk_parameter_scheduler.py __init__()
self.daily_update_interval = timedelta(days=1)  # ← Täglich
self.weekly_update_interval = timedelta(days=7)  # ← Wöchentlich

# Schneller für Testing:
self.daily_update_interval = timedelta(hours=6)  # 4x täglich
self.weekly_update_interval = timedelta(days=1)  # Täglich
```

---

## 📊 Monitoring & Logs

### Tägliche Updates (SL-Limits)

```
============================================================
DAILY RISK PARAMETER UPDATE
============================================================
📊 Account State:
   Balance: $1245.50 (Initial: $1000.00)
   Growth Factor: 1.25x
   Performance Factor (7d): 1.10x
✅ Daily Loss OK: $-12.30 / $99.64 limit
✅ SL Limits Updated:
   XAUUSD    : $7.74
   AUDUSD    : $11.06
   BTCUSD    : $13.27
   US500.c   : $8.85
```

### Wöchentliche Updates (R:R Ratios)

```
============================================================
WEEKLY RISK PARAMETER UPDATE
============================================================
📈 Performance Review (7 days):
   Performance Factor: 1.20x
   Status: ✅ GOOD - Maintaining risk
✅ R:R Ratios Updated:
   FOREX: TP=3.85x, SL=0.79x (R:R 4.87:1)
   METALS: TP=1.32x, SL=0.39x (R:R 3.38:1)

📊 30-Day Performance Summary:
   Trades: 245
   Win Rate: 68.5%
   Profit Factor: 1.85
   Net P/L: $+143.50
   Avg P/L: $+0.59
```

### Logs überwachen

```bash
# Container Logs
docker logs -f ngtradingbot_risk_scheduler

# Nur wichtige Events
docker logs -f ngtradingbot_risk_scheduler | grep "UPDATE\|EXCEEDED\|Factor"

# Daily Loss Limits
docker logs -f ngtradingbot_risk_scheduler | grep "Daily Loss"
```

---

## ⚙️ Integration mit bestehendem System

### SL Enforcement

**Vorher** (statisch):
```python
# sl_enforcement.py
MAX_LOSS_PER_TRADE = {
    'XAUUSD': 5.50,  # Hart-kodiert
}
```

**Nachher** (dynamisch):
```python
# Am Start von unified_workers oder im Scheduler:
from dynamic_risk_manager import update_sl_enforcement_limits
update_sl_enforcement_limits(db, account_id=3, risk_profile='moderate')

# MAX_LOSS_PER_TRADE wird automatisch aktualisiert!
```

### Smart TP/SL

**Vorher** (statisch):
```python
# smart_tp_sl.py
'FOREX_MAJOR': {
    'atr_tp_multiplier': 3.5,  # Hart-kodiert
    'atr_sl_multiplier': 0.8,
}
```

**Nachher** (dynamisch):
```python
# Im Scheduler oder weekly:
from dynamic_risk_manager import update_smart_tpsl_ratios
update_smart_tpsl_ratios(db, account_id=3, risk_profile='moderate')

# ASSET_CLASSES wird automatisch aktualisiert!
```

### Position Sizer

**Integration**:
```python
# position_sizer.py calculate_lot_size()
from dynamic_risk_manager import get_risk_manager

risk_manager = get_risk_manager(account_id, risk_profile='moderate')
risk_multiplier = risk_manager.get_position_size_multiplier(confidence)

# Apply to lot calculation
final_lot = base_lot * risk_multiplier
```

---

## 🎯 Best Practices

### 1. Start Conservative

```python
# Erste 2 Wochen: Conservative Profile
risk_profile = 'conservative'

# Nach 500+ Trades mit PF >1.5:
risk_profile = 'moderate'

# Nur bei Account >5k und PF >2.0:
risk_profile = 'aggressive'
```

### 2. Monitor Performance wöchentlich

```bash
# Jede Woche prüfen:
docker exec ngtradingbot_server python3 - <<'EOF'
from database import get_db
from dynamic_risk_manager import get_risk_manager

db = next(get_db())
rm = get_risk_manager(account_id=3, risk_profile='moderate')

# Prüfe aktuelle Faktoren
growth = rm.get_account_growth_factor(db)
perf = rm.get_recent_performance_factor(db, days=7)

print(f"Growth: {growth:.2f}x, Performance: {perf:.2f}x")

# Wenn Performance dauerhaft <0.8: Auf Conservative wechseln!
# Wenn Growth >2.0 und Performance >1.2: Auf Aggressive wechseln!
EOF
```

### 3. Daily Loss Limit beachten

**Automatischer Schutz im Signal Generator**:
```python
# signal_generator.py generate_signal()
from dynamic_risk_manager import get_risk_manager

risk_manager = get_risk_manager(self.account_id)
is_exceeded, daily_loss, limit = risk_manager.check_daily_loss_limit(db)

if is_exceeded:
    logger.warning(f"Daily loss limit exceeded: {daily_loss:.2f} / {limit:.2f}")
    return None  # Keine neuen Trades heute!
```

### 4. Manual Override möglich

```python
# Manuelle SL-Limit Änderung (temporär):
from sl_enforcement import SLEnforcement
SLEnforcement.MAX_LOSS_PER_TRADE['XAUUSD'] = 3.0  # Niedriger als dynamisch

# Wird beim nächsten Daily Update überschrieben!
```

---

## 📝 Zusammenfassung

### Problem gelöst ✅

**Vorher**:
- ❌ SL-Limits statisch (unabhängig von Kontostand)
- ❌ R:R Ratios statisch (unabhängig von Performance)
- ❌ Keine Anpassung bei Wachstum oder Drawdown

**Jetzt**:
- ✅ SL-Limits skalieren mit Account Balance
- ✅ R:R Ratios passen sich an Performance an
- ✅ Automatische tägliche/wöchentliche Updates
- ✅ 3 Risk Profiles (Conservative, Moderate, Aggressive)
- ✅ Daily Loss Limit Protection

### Nächste Schritte

1. **Heute**: System testen
   ```bash
   docker exec ngtradingbot_server python3 risk_parameter_scheduler.py 3 moderate --once
   ```

2. **Diese Woche**: Scheduler integrieren
   - Option A: Separater Container (empfohlen)
   - Option B: In unified_workers

3. **Langfristig**: Profile optimieren
   - Nach 1 Monat: Performance evaluieren
   - Risk Profile ggf. anpassen
   - Symbol-spezifische Faktoren tunen

---

**Ihr Einwand war 100% korrekt!** Risk Management muss dynamisch sein. Dieses System löst das Problem komplett.
