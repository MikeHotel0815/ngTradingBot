# 72-Stunden Unbeaufsichtigter Test - Dokumentation

## Übersicht

Dieses System ermöglicht einen vollautomatischen 72-Stunden-Test des ngTradingBot mit umfassender Überwachung und automatischem Trade-Management.

## Neue Features

### 1. Trade Timeout Management

Automatisches Schließen oder Warnen bei Trades, die zu lange laufen:

**Konfiguration in `.env`:**
```bash
TRADE_TIMEOUT_HOURS=24          # Maximale Laufzeit eines Trades
TRADE_TIMEOUT_ENABLED=true      # Feature aktivieren/deaktivieren
TRADE_TIMEOUT_ACTION=close      # Aktion: close, alert, ignore
```

**Aktionen:**
- `close`: Trades werden automatisch geschlossen nach Timeout
- `alert`: Nur Warnung im Log, keine Aktion
- `ignore`: Monitoring nur, keine Warnungen

**Worker:** `ngtradingbot_trade_timeout` Container läuft automatisch

### 2. 72-Stunden Monitoring

Umfassendes Monitoring-System das überwacht:
- Container-Status und Restarts
- CPU und Memory Nutzung
- Trade-Aktivität
- Fehlerrate
- Datenbank-Größe
- Redis-Keys
- Disk-Space

## Verfügbare Skripte

### Start des 72h-Tests
```bash
/projects/ngTradingBot/start_72h_test.sh
```

**Was passiert:**
1. Prüft ob Container laufen
2. Erstellt Backup vor Test-Start
3. Startet Monitor im Hintergrund
4. Läuft 72 Stunden unbeaufsichtigt

### Status-Prüfung während des Tests
```bash
/projects/ngTradingBot/check_test_status.sh
```

**Zeigt:**
- Monitor-Status (PID, Laufzeit)
- Neueste Log-Einträge
- Fehler und Alarme
- Container-Status
- Ressourcen-Nutzung

### Test stoppen
```bash
/projects/ngTradingBot/stop_72h_test.sh
```

### Manuelle Log-Überwachung
```bash
# Haupt-Log live
tail -f /projects/ngTradingBot/monitoring/72h_test_*.log

# Fehler live
tail -f /projects/ngTradingBot/monitoring/errors_*.log

# Alarme live
tail -f /projects/ngTradingBot/monitoring/alerts_*.log

# Statistiken (CSV)
tail -f /projects/ngTradingBot/monitoring/stats_*.csv
```

## Monitoring-Details

### Prüfintervall
- **Standard:** 60 Sekunden
- Jede Minute werden alle Container geprüft

### Überwachte Metriken
1. **Container-Gesundheit**
   - Running/Stopped Status
   - Restart Count
   - Uptime

2. **Ressourcen**
   - CPU-Nutzung (Alarm bei >80%)
   - Memory-Nutzung (Alarm bei >75%)
   - Disk-Space (Alarm bei >90%)

3. **Trading-Aktivität**
   - Trades pro Minute
   - Trading Decisions pro Minute
   - Fehlerrate

4. **System-Integrität**
   - Health-Check Endpoint
   - Datenbank-Verfügbarkeit
   - Redis-Verfügbarkeit

### Automatische Aktionen

1. **Stündliche Zusammenfassung**
   - Automatisches Backup alle 60 Minuten
   - Statistik-Zusammenfassung im Log

2. **Alarm-Bedingungen**
   - Container-Restart
   - Hohe CPU/Memory-Nutzung
   - Hohe Fehlerrate (>10 Fehler/5min)
   - Health-Check fehlgeschlagen
   - Container gestoppt

3. **Abschlussbericht**
   - Wird automatisch nach 72h erstellt
   - Enthält vollständige Statistiken
   - Gespeichert als `final_report_*.txt`

## Log-Dateien

Alle Logs werden in `/projects/ngTradingBot/monitoring/` gespeichert:

```
monitoring/
├── 72h_test_TIMESTAMP.log          # Haupt-Log
├── errors_TIMESTAMP.log             # Nur Fehler
├── alerts_TIMESTAMP.log             # Warnungen & Alarme
├── stats_TIMESTAMP.csv              # Metriken als CSV
├── final_report_TIMESTAMP.txt       # Abschlussbericht
└── monitor.pid                      # Prozess-ID des Monitors
```

## Trade Timeout Worker

### Funktionsweise
Der Worker läuft alle 5 Minuten und:
1. Sucht offene Trades älter als `TRADE_TIMEOUT_HOURS`
2. Führt konfigurierte Aktion aus (close/alert/ignore)
3. Berechnet PnL beim Schließen
4. Loggt alle Aktionen

### Statistiken
Alle 50 Minuten werden Statistiken geloggt:
- Anzahl offener Trades
- Durchschnittliche Laufzeit
- Maximale/Minimale Laufzeit
- Anzahl Trades über Timeout

### Trade-Schließung
Wenn ein Trade geschlossen wird:
- Status → 'closed'
- `closed_at` → Aktueller Timestamp
- `close_reason` → 'auto_timeout_after_Xh'
- PnL wird berechnet (Entry vs. Current Price)

## Container-Übersicht

Nach der Aktualisierung laufen:
1. `ngtradingbot_server` - Haupt-API Server
2. `ngtradingbot_db` - PostgreSQL Datenbank
3. `ngtradingbot_redis` - Redis Cache
4. `ngtradingbot_decision_cleanup` - Bereinigt alte Decisions
5. `ngtradingbot_news_fetch` - News Fetcher
6. `ngtradingbot_trade_timeout` - **NEU** Trade Timeout Manager

## Empfohlene Nutzung

### Vor dem Test
```bash
# 1. System-Update durchführen
cd /projects/ngTradingBot
docker compose down
docker compose build
docker compose up -d

# 2. Warte bis alle Container healthy sind
docker compose ps

# 3. Starte 72h-Test
./start_72h_test.sh
```

### Während des Tests
```bash
# Status prüfen
./check_test_status.sh

# Oder Live-Logs
tail -f monitoring/72h_test_*.log
```

### Nach dem Test
```bash
# Abschlussbericht ansehen
cat monitoring/final_report_*.txt

# CSV-Daten analysieren
# Die stats_*.csv Datei kann in Excel/LibreOffice geöffnet werden
```

## Troubleshooting

### Monitor läuft nicht
```bash
# Prüfe ob Prozess läuft
pgrep -f 72h_monitor.sh

# Manuell starten
nohup /projects/ngTradingBot/72h_monitor.sh > /tmp/monitor.log 2>&1 &
```

### Zu viele Alarme
Passe Schwellenwerte in `72h_monitor.sh` an:
```bash
MAX_CPU_PERCENT=80     # CPU-Alarm Schwellenwert
MAX_MEM_PERCENT=75     # Memory-Alarm Schwellenwert
MAX_ERROR_RATE=10      # Fehler pro Minute
```

### Trade Timeout zu aggressiv
Passe `.env` an:
```bash
TRADE_TIMEOUT_HOURS=48              # Länger laufen lassen
TRADE_TIMEOUT_ACTION=alert          # Nur warnen, nicht schließen
```

## Performance-Hinweise

### Disk-Space
- Logs können über 72h mehrere MB groß werden
- CSV-Datei: ~1 KB pro Stunde (~72 KB gesamt)
- Backups: Je nach DB-Größe (stündlich)

### System-Load
- Monitor: Minimaler Overhead (~1% CPU)
- Trade Timeout Worker: Sehr leicht (<1% CPU)
- Haupt-Last kommt vom Trading-System selbst

## Sicherheit

### Automatische Backups
- Stündlich während des Tests
- 30 Tage Aufbewahrung
- Optional: GitHub-Upload (siehe `.env`)

### Fehler-Recovery
- Alle Container haben `restart: unless-stopped`
- Bei Container-Restart wird alarmiert
- Monitor läuft unabhängig von Containern

## Beispiel-Workflow

```bash
# 1. System vorbereiten
cd /projects/ngTradingBot
docker compose up -d

# 2. Test starten
./start_72h_test.sh
# [Bestätigung: Y]

# 3. Status checken (nach 1 Stunde)
./check_test_status.sh

# 4. Logs checken (optional)
tail -20 monitoring/72h_test_*.log

# 5. Nach 72h: Abschlussbericht
cat monitoring/final_report_*.txt

# 6. Statistiken analysieren
# CSV in Excel öffnen für Charts
```

## Support

Bei Problemen:
1. Prüfe `/projects/ngTradingBot/monitoring/errors_*.log`
2. Prüfe Container-Logs: `docker compose logs -f`
3. Prüfe System-Ressourcen: `df -h` und `free -h`

---

**Erstellt:** $(date)
**Version:** 1.0
**Autor:** ngTradingBot Team
