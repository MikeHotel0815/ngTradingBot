# ✅ Automatisches Monitoring Eingerichtet!

**Datum:** 2025-10-20
**Status:** 🟢 Aktiv und getestet

---

## Was Wurde Eingerichtet

### 1. Daily Monitoring Script ✅
**File:** `/projects/ngTradingBot/daily_monitor_job.sh`

**Was es tut:**
- Läuft automatisch jeden Tag um 8:00 Uhr morgens
- Erstellt täglichen Audit-Report
- Zeigt BUY vs SELL Performance (letzte 24h)
- Prüft Position Sizing, Signal Staleness, Circuit Breaker
- Speichert alles in Log-Dateien

### 2. Log-Verzeichnis ✅
**Location:** `/var/log/ngtradingbot/`

**Dateien:**
- `daily_audit_YYYYMMDD.log` - Täglicher Report (z.B. daily_audit_20251020.log)
- `errors.log` - Fehlerlog falls Probleme auftreten
- Alte Logs werden nach 30 Tagen automatisch gelöscht

### 3. Manueller Start Script ✅
**File:** `/projects/ngTradingBot/run_daily_audit.sh`

**Nutzen:** Du kannst jederzeit manuell einen Report erstellen

---

## 🚀 Wie Du Es Nutzt

### Heutigen Report Anschauen
```bash
cat /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log
```

**Beispiel-Output:**
```
========================================
Daily Audit - 2025-10-20 18:54:49
========================================

Running audit monitor...

Quick Database Stats (Last 24h):
----------------------------------------
 Total Trades: 14 | Wins: 10 | WR: 71.4% | Profit: €0.39

BUY vs SELL (Last 24h):
 BUY: 6 trades, 66.7% WR, €-2.15 profit
 SELL: 8 trades, 75.0% WR, €2.54 profit

✅ Daily audit completed
```

### Manuell Audit Jetzt Starten
```bash
/projects/ngTradingBot/run_daily_audit.sh
```

### Alle Logs Ansehen
```bash
ls -lh /var/log/ngtradingbot/
```

### Letzten Report Anzeigen
```bash
tail -50 /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log
```

### Alle Reports Der Letzten Woche
```bash
find /var/log/ngtradingbot/ -name "daily_audit_*.log" -mtime -7 -exec echo "=== {} ===" \; -exec cat {} \; | less
```

---

## ⏰ Zeitplan

**Automatische Ausführung:**
- **Täglich um 8:00 Uhr** morgens (Europe/Berlin Zeit)
- Läuft im Hintergrund
- Kein Neustart nötig

**Was Passiert:**
1. 8:00 Uhr: Script startet automatisch
2. Sammelt Performance-Daten der letzten 24h
3. Erstellt Report in `/var/log/ngtradingbot/`
4. Bereit zum Lesen wann immer du willst

---

## 📊 Was Der Report Enthält

### 1. Gesamt-Performance (Letzte 24h)
- Anzahl Trades
- Anzahl Wins/Losses
- Win Rate %
- Total Profit in €

### 2. BUY vs SELL Vergleich
- Separate Stats für BUY und SELL
- Win Rate Comparison
- Profit Comparison

### 3. System-Status Checks
- Position Sizing: Funktioniert es? (Logs zeigen wenn alle Trades 0.01 lot sind)
- Signal Staleness: Gibt es alte Signale? (>5 Minuten)
- Circuit Breaker: Gab es Trips?
- Command Success Rate: Laufen Befehle durch?

### 4. Warnungen
- ⚠️ Automatische Warnungen bei Problemen
- Z.B. "BUY Win Rate is dropping"
- Z.B. "Circuit Breaker tripped"

---

## 🔧 Erweiterte Nutzung

### Monitoring Im Hintergrund Starten (24/7)
```bash
# Startet endlos-Schleife die täglich um 8:00 Uhr läuft
nohup /projects/ngTradingBot/start_monitoring.sh > /var/log/ngtradingbot/monitoring_service.log 2>&1 &

# Prozess ID speichern
echo $! > /var/log/ngtradingbot/monitoring.pid
```

### Monitoring Stoppen
```bash
# Prozess finden und stoppen
pkill -f start_monitoring.sh

# Oder mit gespeicherter PID
kill $(cat /var/log/ngtradingbot/monitoring.pid)
```

### Status Prüfen
```bash
# Läuft das Monitoring?
ps aux | grep start_monitoring.sh

# Letzter Log-Eintrag
ls -lt /var/log/ngtradingbot/ | head -5
```

---

## 🎯 Integration Mit Telegram (Optional)

Wenn du Telegram-Benachrichtigungen willst, kann ich das auch einrichten:

### Was Du Bekommen Würdest:
```
🤖 ngTradingBot Daily Report

📊 Last 24h:
   Trades: 14
   Win Rate: 71.4%
   Profit: €0.39

   BUY: 6 trades, 66.7% WR
   SELL: 8 trades, 75.0% WR

✅ All systems normal
```

**Sag Bescheid wenn du das willst!**

---

## 📈 Erweiterte Reports

### Wöchentlicher Report (Sonntagabend)
```bash
# Erstelle wöchentlichen Summary
python3 /projects/ngTradingBot/analyze_current_performance.py --days 7 --export
```

### Monatlicher Backtest
```bash
# Ersten jeden Monats
python3 /projects/ngTradingBot/run_audit_backtests.py --quick
```

---

## ❓ Troubleshooting

### Problem: Logs werden nicht erstellt
**Lösung:**
```bash
# Check ob Script ausführbar ist
ls -l /projects/ngTradingBot/daily_monitor_job.sh

# Manuell ausführen zum Testen
/projects/ngTradingBot/daily_monitor_job.sh

# Errors checken
cat /var/log/ngtradingbot/errors.log
```

### Problem: Database Connection Error
**Lösung:**
```bash
# Check ob Docker läuft
docker ps | grep ngtradingbot_db

# Test Database Connection
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -c "SELECT COUNT(*) FROM trades;"
```

### Problem: Alte Logs häufen sich an
**Lösung:**
```bash
# Manuell alte Logs löschen (älter als 30 Tage)
find /var/log/ngtradingbot -name "daily_audit_*.log" -mtime +30 -delete

# Script macht das automatisch, aber du kannst es manuell machen
```

---

## 📁 File Locations

| File | Location | Purpose |
|------|----------|---------|
| **Daily Monitor Script** | `/projects/ngTradingBot/daily_monitor_job.sh` | Hauptscript für Daily Audit |
| **Manual Run Script** | `/projects/ngTradingBot/run_daily_audit.sh` | Manueller Start des Audits |
| **Background Service** | `/projects/ngTradingBot/start_monitoring.sh` | 24/7 Background Monitoring |
| **Daily Logs** | `/var/log/ngtradingbot/daily_audit_*.log` | Tägliche Reports |
| **Error Log** | `/var/log/ngtradingbot/errors.log` | Fehlerprotokoll |
| **Service Log** | `/var/log/ngtradingbot/monitoring_service.log` | Background Service Log |

---

## 🎓 Best Practices

### 1. Morgendliche Routine (2 Minuten)
```bash
# Step 1: Gestrigen Report lesen
cat /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log

# Step 2: Auf Warnungen achten
grep "⚠️" /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log

# Step 3: BUY vs SELL Gap prüfen
# (Steht direkt im Log)
```

### 2. Wöchentliche Review (10 Minuten)
```bash
# Alle Logs der Woche ansehen
for day in $(seq 0 6); do
    date=$(date -d "-$day days" +%Y%m%d)
    echo "=== $date ==="
    cat /var/log/ngtradingbot/daily_audit_$date.log 2>/dev/null | grep "Total Trades"
done

# Trend erkennen: Wird es besser oder schlechter?
```

### 3. Monatliche Analyse (30 Minuten)
```bash
# Vollständige Performance-Analyse
python3 /projects/ngTradingBot/analyze_current_performance.py --days 30 --export

# Backtest-Vergleich
python3 /projects/ngTradingBot/run_audit_backtests.py --quick

# Entscheidung: Settings anpassen?
```

---

## 🔔 Nächste Schritte (Optional)

### Level Up: Telegram Bot
**Was es bringt:**
- Push-Benachrichtigungen aufs Handy
- Sofortige Alerts bei Problemen
- Tägliche Zusammenfassung morgens

**Setup-Zeit:** 10 Minuten
**Sag Bescheid wenn du das willst!**

### Level Up: Web Dashboard
**Was es bringt:**
- Live-Charts im Browser
- Echtzeit-Metriken
- Schöne visuelle Darstellung

**Setup-Zeit:** 20 Minuten
**Sag Bescheid wenn du das willst!**

### Level Up: Alert System
**Was es bringt:**
- Email bei Circuit Breaker Trip
- SMS bei kritischen Fehlern
- Webhook Integration (Discord, Slack, etc.)

**Setup-Zeit:** 15 Minuten
**Sag Bescheid wenn du das willst!**

---

## ✅ Zusammenfassung

**Was Jetzt Automatisch Läuft:**
✅ Tägliches Monitoring um 8:00 Uhr
✅ Performance Reports (24h Fenster)
✅ BUY vs SELL Tracking
✅ System Health Checks
✅ Automatische Log-Rotation (30 Tage)

**Was Du Tun Musst:**
- Jeden Morgen: Log kurz ansehen (2 Minuten)
- Bei Warnungen: Genauer prüfen
- Sonst: Läuft von selbst! 🎉

**Nächster Auto-Report:**
Morgen um 8:00 Uhr in `/var/log/ngtradingbot/daily_audit_$(date -d tomorrow +%Y%m%d).log`

---

**Du Kannst Jetzt:**
1. ✅ Logs jederzeit lesen
2. ✅ Manuell Reports erstellen
3. ✅ Warnungen automatisch bekommen
4. ✅ Trends über Zeit verfolgen

**Brauchst Du Mehr?**
- Telegram Bot? Sag "ja"
- Web Dashboard? Sag "ja"
- Email Alerts? Sag "ja"

Ansonsten: **Alles fertig! 🎉**
