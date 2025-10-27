#!/bin/bash
#
# Daily Performance Report - Sends dashboard via Telegram
# Run daily at 18:00 UTC
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/projects/ngTradingBot/logs/performance_dashboard_$(date +%Y%m%d).txt"
ERROR_LOG="/projects/ngTradingBot/logs/performance_errors.log"

# Ensure logs directory exists
mkdir -p /projects/ngTradingBot/logs

# Run performance monitor with Telegram notification
echo "========================================" >> "$ERROR_LOG"
echo "Daily Performance Report - $(date)" >> "$ERROR_LOG"
echo "========================================" >> "$ERROR_LOG"

docker exec ngtradingbot_server python3 /app/performance_monitor.py \
    --telegram \
    --output /app/logs/performance_dashboard.txt \
    > "$LOG_FILE" 2>> "$ERROR_LOG"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Daily performance report sent successfully" >> "$ERROR_LOG"

    # Copy report from container to host for backup
    docker cp ngtradingbot_server:/app/logs/performance_dashboard.txt "$LOG_FILE" 2>/dev/null
else
    echo "❌ Daily performance report FAILED with exit code $EXIT_CODE" >> "$ERROR_LOG"
fi

# Keep only last 30 days of logs
find /projects/ngTradingBot/logs -name "performance_dashboard_*.txt" -mtime +30 -delete

echo "" >> "$ERROR_LOG"

exit $EXIT_CODE
