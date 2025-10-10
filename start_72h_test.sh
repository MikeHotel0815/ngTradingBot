#!/bin/bash

# Starter-Skript für den 72-Stunden unbeaufsichtigten Test

echo "=========================================="
echo "ngTradingBot - 72-Stunden Test"
echo "=========================================="
echo ""

# Prüfe ob Monitoring-Verzeichnis existiert
MONITOR_DIR="/projects/ngTradingBot/monitoring"
mkdir -p "$MONITOR_DIR"

# Prüfe ob bereits ein Test läuft
if pgrep -f "72h_monitor.sh" > /dev/null; then
    echo "WARNUNG: Ein 72h-Monitor läuft bereits!"
    echo "PID(s): $(pgrep -f '72h_monitor.sh')"
    echo ""
    read -p "Trotzdem neuen Test starten? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Abgebrochen."
        exit 1
    fi
fi

# Prüfe ob alle Container laufen
echo "Prüfe Container-Status..."
REQUIRED_CONTAINERS=("ngtradingbot_server" "ngtradingbot_db" "ngtradingbot_redis")
ALL_RUNNING=true

for container in "${REQUIRED_CONTAINERS[@]}"; do
    if ! docker ps --filter "name=$container" --format "{{.Names}}" | grep -q "$container"; then
        echo "FEHLER: Container $container läuft nicht!"
        ALL_RUNNING=false
    fi
done

if [ "$ALL_RUNNING" = false ]; then
    echo ""
    read -p "Container starten? (Y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo "Starte Container..."
        cd /projects/ngTradingBot
        docker compose up -d
        sleep 10
    else
        echo "Abgebrochen."
        exit 1
    fi
fi

echo "Alle erforderlichen Container laufen."
echo ""

# Zeige aktuelle System-Info
echo "Aktuelle System-Statistiken:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" | grep ngtradingbot
echo ""

# Erstelle Backup vor dem Start
echo "Erstelle Datenbank-Backup vor Test-Start..."
if /projects/ngTradingBot/backup_database.sh; then
    echo "✓ Backup erfolgreich erstellt"
else
    echo "✗ Backup fehlgeschlagen - trotzdem fortfahren?"
    read -p "Fortfahren? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Mache Monitor-Skript ausführbar
chmod +x /projects/ngTradingBot/72h_monitor.sh

# Zeige Test-Konfiguration
echo "=========================================="
echo "TEST-KONFIGURATION:"
echo "=========================================="
echo "Dauer: 72 Stunden (3 Tage)"
echo "Start: $(date)"
echo "Voraussichtliches Ende: $(date -d '+72 hours')"
echo "Prüfintervall: 60 Sekunden"
echo "Monitoring-Verzeichnis: $MONITOR_DIR"
echo "=========================================="
echo ""

# Frage nach Bestätigung
read -p "72-Stunden Test jetzt starten? (Y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "Abgebrochen."
    exit 0
fi

# Starte Monitor im Hintergrund mit nohup
echo ""
echo "Starte 72-Stunden Monitor..."
nohup /projects/ngTradingBot/72h_monitor.sh > "$MONITOR_DIR/monitor_output_$(date +%Y%m%d_%H%M%S).log" 2>&1 &
MONITOR_PID=$!

sleep 2

# Prüfe ob Monitor läuft
if ps -p $MONITOR_PID > /dev/null; then
    echo "✓ Monitor erfolgreich gestartet (PID: $MONITOR_PID)"
    echo ""
    echo "=========================================="
    echo "TEST LÄUFT!"
    echo "=========================================="
    echo ""
    echo "Der 72-Stunden Test läuft jetzt unbeaufsichtigt im Hintergrund."
    echo ""
    echo "ÜBERWACHUNG:"
    echo "  - Monitor PID: $MONITOR_PID"
    echo "  - Logs: $MONITOR_DIR"
    echo ""
    echo "NÜTZLICHE BEFEHLE:"
    echo "  - Status prüfen: tail -f $MONITOR_DIR/72h_test_*.log"
    echo "  - Fehler ansehen: tail -f $MONITOR_DIR/errors_*.log"
    echo "  - Statistiken: tail -f $MONITOR_DIR/stats_*.csv"
    echo "  - Alarme: tail -f $MONITOR_DIR/alerts_*.log"
    echo "  - Monitor stoppen: kill $MONITOR_PID"
    echo "  - Alle laufenden Monitore: pgrep -f 72h_monitor.sh"
    echo ""
    echo "Der Test wird automatisch nach 72 Stunden beendet."
    echo "=========================================="
    echo ""

    # Speichere PID für später
    echo "$MONITOR_PID" > "$MONITOR_DIR/monitor.pid"

else
    echo "✗ FEHLER: Monitor konnte nicht gestartet werden!"
    echo "Prüfe die Logs in $MONITOR_DIR"
    exit 1
fi

exit 0
