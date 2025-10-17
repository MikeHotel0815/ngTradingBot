#!/bin/bash

# Stoppt den 72-Stunden Test

MONITOR_DIR="/projects/ngTradingBot/monitoring"

echo "Stoppe 72-Stunden Test..."

# Prüfe ob PID-Datei existiert
if [ -f "$MONITOR_DIR/monitor.pid" ]; then
    PID=$(cat "$MONITOR_DIR/monitor.pid")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stoppe Monitor (PID: $PID)..."
        kill "$PID"
        sleep 2
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Monitor läuft noch, erzwinge Beendigung..."
            kill -9 "$PID"
        fi
        echo "✓ Monitor gestoppt"
        rm "$MONITOR_DIR/monitor.pid"
    else
        echo "Monitor mit PID $PID läuft nicht mehr"
        rm "$MONITOR_DIR/monitor.pid"
    fi
else
    # Suche nach laufenden Monitoren
    PIDS=$(pgrep -f "72h_monitor.sh")
    if [ -n "$PIDS" ]; then
        echo "Gefundene Monitor-Prozesse: $PIDS"
        echo "Stoppe alle Monitor-Prozesse..."
        pkill -f "72h_monitor.sh"
        sleep 2
        echo "✓ Alle Monitore gestoppt"
    else
        echo "Kein laufender Monitor gefunden"
    fi
fi

echo "Fertig."
