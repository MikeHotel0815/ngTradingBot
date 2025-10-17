#!/bin/bash

# 72-Stunden unbeaufsichtigter Test-Monitor für ngTradingBot
# Überwacht System-Gesundheit, Performance und Trading-Aktivitäten

MONITOR_DIR="/projects/ngTradingBot/monitoring"
LOG_FILE="$MONITOR_DIR/72h_test_$(date +%Y%m%d_%H%M%S).log"
ERROR_LOG="$MONITOR_DIR/errors_$(date +%Y%m%d_%H%M%S).log"
STATS_FILE="$MONITOR_DIR/stats_$(date +%Y%m%d_%H%M%S).csv"
ALERT_FILE="$MONITOR_DIR/alerts_$(date +%Y%m%d_%H%M%S).log"

# Test-Dauer in Sekunden (72 Stunden = 259200 Sekunden)
TEST_DURATION=$((72 * 60 * 60))
CHECK_INTERVAL=60  # Prüfung alle 60 Sekunden

# Erstelle Monitoring-Verzeichnis
mkdir -p "$MONITOR_DIR"

# Schwellenwerte für Alarme
MAX_CPU_PERCENT=80
MAX_MEM_PERCENT=75
MAX_ERROR_RATE=10  # Fehler pro Minute
MIN_UPTIME=55      # Minimum Uptime in Sekunden zwischen Restarts

# Funktion zum Logging mit Zeitstempel
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Funktion für Fehler-Logging
log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$ERROR_LOG" "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ALERT: $1" >> "$ALERT_FILE"
}

# Funktion für Warnungen
log_warning() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1" | tee -a "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1" >> "$ALERT_FILE"
}

# Erstelle CSV-Header
echo "Timestamp,Container,Status,CPU%,Memory_MB,Memory%,Restart_Count,Trade_Count,Decision_Count,Error_Count" > "$STATS_FILE"

# Initialisierung
START_TIME=$(date +%s)
END_TIME=$((START_TIME + TEST_DURATION))
CHECK_COUNT=0
TOTAL_ERRORS=0
LAST_RESTART_COUNT=0

log_message "=========================================="
log_message "72-STUNDEN UNBEAUFSICHTIGTER TEST GESTARTET"
log_message "=========================================="
log_message "Start: $(date)"
log_message "Ende geplant: $(date -d @$END_TIME)"
log_message "Prüfintervall: ${CHECK_INTERVAL}s"
log_message "Log-Datei: $LOG_FILE"
log_message "Fehler-Log: $ERROR_LOG"
log_message "Statistik: $STATS_FILE"
log_message "=========================================="

# Hauptüberwachungsschleife
while [ $(date +%s) -lt $END_TIME ]; do
    CHECK_COUNT=$((CHECK_COUNT + 1))
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    REMAINING=$((END_TIME - CURRENT_TIME))

    log_message "Check #$CHECK_COUNT - Verstrichene Zeit: $(($ELAPSED / 3600))h $(($ELAPSED % 3600 / 60))m - Verbleibend: $(($REMAINING / 3600))h $(($REMAINING % 3600 / 60))m"

    # 1. Container-Status prüfen
    CONTAINERS=("ngtradingbot_server" "ngtradingbot_db" "ngtradingbot_redis" "ngtradingbot_news_fetch" "ngtradingbot_decision_cleanup")

    for CONTAINER in "${CONTAINERS[@]}"; do
        if docker ps --filter "name=$CONTAINER" --format "{{.Names}}" | grep -q "$CONTAINER"; then
            # Container läuft - hole Statistiken
            STATS=$(docker stats --no-stream --format "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}" "$CONTAINER" 2>/dev/null)

            if [ -n "$STATS" ]; then
                CPU=$(echo "$STATS" | cut -d'|' -f1 | sed 's/%//')
                MEM_USAGE=$(echo "$STATS" | cut -d'|' -f2 | cut -d'/' -f1 | sed 's/MiB//' | sed 's/ //')
                MEM_PERC=$(echo "$STATS" | cut -d'|' -f3 | sed 's/%//')

                # Restart-Zähler
                RESTART_COUNT=$(docker inspect "$CONTAINER" --format='{{.RestartCount}}' 2>/dev/null || echo "0")

                # CPU-Warnung
                if (( $(echo "$CPU > $MAX_CPU_PERCENT" | bc -l) )); then
                    log_warning "$CONTAINER: CPU-Nutzung hoch: ${CPU}%"
                fi

                # Memory-Warnung
                if (( $(echo "$MEM_PERC > $MAX_MEM_PERCENT" | bc -l) )); then
                    log_warning "$CONTAINER: Speicher-Nutzung hoch: ${MEM_PERC}%"
                fi

                # Restart-Warnung
                if [ "$RESTART_COUNT" -gt "$LAST_RESTART_COUNT" ]; then
                    log_error "$CONTAINER wurde neu gestartet! Restart Count: $RESTART_COUNT"
                    LAST_RESTART_COUNT=$RESTART_COUNT
                fi

                # Für Server-Container: zusätzliche Metriken
                if [ "$CONTAINER" = "ngtradingbot_server" ]; then
                    # Prüfe ob Server antwortet
                    if ! curl -sf http://localhost:9900/health > /dev/null 2>&1; then
                        log_error "Server antwortet nicht auf Health-Check!"
                    fi

                    # Hole Trading-Statistiken aus der Datenbank
                    TRADE_COUNT=$(docker exec ngtradingbot_db psql -U tradingbot -d tradingbot -t -c "SELECT COUNT(*) FROM trades WHERE created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")
                    DECISION_COUNT=$(docker exec ngtradingbot_db psql -U tradingbot -d tradingbot -t -c "SELECT COUNT(*) FROM trading_decisions WHERE created_at > NOW() - INTERVAL '1 minute';" 2>/dev/null | xargs || echo "0")

                    # Zähle Fehler in den letzten 5 Minuten
                    ERROR_COUNT=$(docker logs --since 5m "$CONTAINER" 2>&1 | grep -i "error\|exception\|critical" | wc -l)

                    if [ "$ERROR_COUNT" -gt "$MAX_ERROR_RATE" ]; then
                        log_warning "Hohe Fehlerrate im Server: $ERROR_COUNT Fehler in 5 Minuten"
                        TOTAL_ERRORS=$((TOTAL_ERRORS + ERROR_COUNT))
                    fi
                else
                    TRADE_COUNT=0
                    DECISION_COUNT=0
                    ERROR_COUNT=0
                fi

                # Schreibe Statistiken in CSV
                echo "$(date '+%Y-%m-%d %H:%M:%S'),$CONTAINER,RUNNING,$CPU,$MEM_USAGE,$MEM_PERC,$RESTART_COUNT,$TRADE_COUNT,$DECISION_COUNT,$ERROR_COUNT" >> "$STATS_FILE"

                log_message "$CONTAINER: Status=OK CPU=${CPU}% MEM=${MEM_USAGE}MiB (${MEM_PERC}%) Restarts=$RESTART_COUNT"
            fi
        else
            log_error "$CONTAINER ist nicht verfügbar oder gestoppt!"
            echo "$(date '+%Y-%m-%d %H:%M:%S'),$CONTAINER,STOPPED,0,0,0,0,0,0,0" >> "$STATS_FILE"
        fi
    done

    # 2. Disk-Space prüfen
    DISK_USAGE=$(df -h /projects | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$DISK_USAGE" -gt 90 ]; then
        log_warning "Festplatten-Nutzung kritisch: ${DISK_USAGE}%"
    fi
    log_message "Disk-Nutzung: ${DISK_USAGE}%"

    # 3. Database-Größe prüfen
    DB_SIZE=$(docker exec ngtradingbot_db psql -U tradingbot -d tradingbot -t -c "SELECT pg_size_pretty(pg_database_size('tradingbot'));" 2>/dev/null | xargs || echo "N/A")
    log_message "Datenbank-Größe: $DB_SIZE"

    # 4. Redis-Status prüfen
    REDIS_KEYS=$(docker exec ngtradingbot_redis redis-cli DBSIZE 2>/dev/null | grep -oP '\d+' || echo "N/A")
    log_message "Redis Keys: $REDIS_KEYS"

    # 5. Zusammenfassung alle 60 Minuten
    if [ $((CHECK_COUNT % 60)) -eq 0 ]; then
        log_message "========== STÜNDLICHE ZUSAMMENFASSUNG =========="
        log_message "Laufzeit: $(($ELAPSED / 3600))h $(($ELAPSED % 3600 / 60))m"
        log_message "Gesamte Fehler: $TOTAL_ERRORS"
        log_message "Gesamte Restarts: $LAST_RESTART_COUNT"

        # Backup erstellen
        log_message "Erstelle Backup..."
        if /projects/ngTradingBot/backup_database.sh > /dev/null 2>&1; then
            log_message "Backup erfolgreich erstellt"
        else
            log_error "Backup-Erstellung fehlgeschlagen"
        fi
        log_message "==============================================="
    fi

    # Warte bis zum nächsten Check
    sleep "$CHECK_INTERVAL"
done

# Test abgeschlossen
log_message "=========================================="
log_message "72-STUNDEN TEST ABGESCHLOSSEN"
log_message "=========================================="
log_message "Ende: $(date)"
log_message "Gesamtdauer: 72 Stunden"
log_message "Gesamte Checks: $CHECK_COUNT"
log_message "Gesamte Fehler: $TOTAL_ERRORS"
log_message "Gesamte Container-Restarts: $LAST_RESTART_COUNT"
log_message "=========================================="
log_message "Logs gespeichert in:"
log_message "  - Haupt-Log: $LOG_FILE"
log_message "  - Fehler-Log: $ERROR_LOG"
log_message "  - Statistiken: $STATS_FILE"
log_message "  - Alarme: $ALERT_FILE"
log_message "=========================================="

# Erstelle abschließenden Report
REPORT_FILE="$MONITOR_DIR/final_report_$(date +%Y%m%d_%H%M%S).txt"
{
    echo "=========================================="
    echo "72-STUNDEN TEST - ABSCHLUSSBERICHT"
    echo "=========================================="
    echo "Test-Zeitraum: $(date -d @$START_TIME) bis $(date)"
    echo ""
    echo "ZUSAMMENFASSUNG:"
    echo "- Gesamte Prüfungen: $CHECK_COUNT"
    echo "- Gesamte Fehler: $TOTAL_ERRORS"
    echo "- Container-Restarts: $LAST_RESTART_COUNT"
    echo ""
    echo "ENDGÜLTIGE CONTAINER-STATUS:"
    docker ps --filter "name=ngtradingbot" --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
    echo ""
    echo "RESSOURCEN-NUTZUNG:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"
    echo ""
    echo "DATENBANK-STATISTIKEN:"
    docker exec ngtradingbot_db psql -U tradingbot -d tradingbot -c "SELECT 'Total Trades' as Metric, COUNT(*) as Count FROM trades UNION ALL SELECT 'Total Decisions', COUNT(*) FROM trading_decisions UNION ALL SELECT 'Total Signals', COUNT(*) FROM trading_signals;"
    echo ""
    echo "=========================================="
} > "$REPORT_FILE"

log_message "Abschlussbericht erstellt: $REPORT_FILE"

exit 0
