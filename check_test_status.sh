#!/bin/bash

# Zeigt den aktuellen Status des 72-Stunden Tests

MONITOR_DIR="/projects/ngTradingBot/monitoring"

echo "=========================================="
echo "72-STUNDEN TEST - STATUS"
echo "=========================================="
echo ""

# Prüfe ob Monitor läuft
if [ -f "$MONITOR_DIR/monitor.pid" ]; then
    PID=$(cat "$MONITOR_DIR/monitor.pid")
    if ps -p "$PID" > /dev/null 2>&1; then
        RUNTIME=$(ps -p "$PID" -o etime= | xargs)
        echo "✓ Monitor läuft (PID: $PID, Laufzeit: $RUNTIME)"
    else
        echo "✗ Monitor läuft nicht mehr (PID $PID ist tot)"
    fi
else
    PIDS=$(pgrep -f "72h_monitor.sh")
    if [ -n "$PIDS" ]; then
        echo "✓ Monitor läuft (PID: $PIDS)"
    else
        echo "✗ Kein Monitor läuft aktuell"
    fi
fi

echo ""
echo "LOGS:"
if [ -d "$MONITOR_DIR" ]; then
    # Neueste Log-Dateien
    LATEST_LOG=$(ls -t "$MONITOR_DIR"/72h_test_*.log 2>/dev/null | head -1)
    LATEST_ERROR=$(ls -t "$MONITOR_DIR"/errors_*.log 2>/dev/null | head -1)
    LATEST_ALERT=$(ls -t "$MONITOR_DIR"/alerts_*.log 2>/dev/null | head -1)

    if [ -n "$LATEST_LOG" ]; then
        echo "  - Haupt-Log: $LATEST_LOG"
        echo "    Letzte Zeilen:"
        tail -5 "$LATEST_LOG" | sed 's/^/    /'
    fi

    echo ""
    if [ -n "$LATEST_ERROR" ]; then
        ERROR_COUNT=$(wc -l < "$LATEST_ERROR")
        echo "  - Fehler-Log: $LATEST_ERROR ($ERROR_COUNT Fehler)"
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo "    Letzte Fehler:"
            tail -3 "$LATEST_ERROR" | sed 's/^/    /'
        fi
    fi

    echo ""
    if [ -n "$LATEST_ALERT" ]; then
        ALERT_COUNT=$(wc -l < "$LATEST_ALERT")
        echo "  - Alarm-Log: $LATEST_ALERT ($ALERT_COUNT Alarme)"
        if [ "$ALERT_COUNT" -gt 0 ]; then
            echo "    Letzte Alarme:"
            tail -3 "$LATEST_ALERT" | sed 's/^/    /'
        fi
    fi
else
    echo "  Monitoring-Verzeichnis nicht gefunden"
fi

echo ""
echo "CONTAINER-STATUS:"
docker ps --filter "name=ngtradingbot" --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"

echo ""
echo "RESSOURCEN:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" | grep ngtradingbot

echo ""
echo "=========================================="
