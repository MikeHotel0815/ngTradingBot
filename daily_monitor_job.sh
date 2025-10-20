#!/bin/bash
# Daily Monitoring Job
# Runs automatically via cron

LOG_FILE="/var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log"
ERROR_LOG="/var/log/ngtradingbot/errors.log"

echo "========================================" >> "$LOG_FILE"
echo "Daily Audit - $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Set environment variables
export DATABASE_URL="postgresql://trader:tradingbot_secret_2025@localhost:9904/ngtradingbot"
export REDIS_HOST="localhost"
export REDIS_PORT="9905"
export REDIS_DB="0"

cd /projects/ngTradingBot

# Run audit monitor
echo "Running audit monitor..." >> "$LOG_FILE"
python3 audit_monitor.py --once >> "$LOG_FILE" 2>> "$ERROR_LOG"

# Get quick performance stats from database
echo "" >> "$LOG_FILE"
echo "Quick Database Stats (Last 24h):" >> "$LOG_FILE"
echo "----------------------------------------" >> "$LOG_FILE"

docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    'Total Trades: ' || COUNT(*) ||
    ' | Wins: ' || SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END) ||
    ' | WR: ' || ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) || '%' ||
    ' | Profit: €' || ROUND(SUM(profit),2)
FROM trades
WHERE close_time >= NOW()-INTERVAL'24 hours' AND status='closed';
" >> "$LOG_FILE" 2>> "$ERROR_LOG"

echo "" >> "$LOG_FILE"
echo "BUY vs SELL (Last 24h):" >> "$LOG_FILE"
docker exec ngtradingbot_db psql -U trader -d ngtradingbot -t -c "
SELECT
    direction || ': ' || COUNT(*) || ' trades, ' ||
    ROUND(AVG(CASE WHEN profit>0 THEN 1.0 ELSE 0.0 END)*100,1) || '% WR, €' ||
    ROUND(SUM(profit),2) || ' profit'
FROM trades
WHERE close_time >= NOW()-INTERVAL'24 hours' AND status='closed'
GROUP BY direction
ORDER BY direction;
" >> "$LOG_FILE" 2>> "$ERROR_LOG"

echo "" >> "$LOG_FILE"
echo "✅ Daily audit completed" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Check for errors
if [ -s "$ERROR_LOG" ]; then
    echo "⚠️  Errors detected - check $ERROR_LOG" >> "$LOG_FILE"
fi

# Send Telegram report
echo "📱 Sending Telegram report..." >> "$LOG_FILE"
/projects/ngTradingBot/send_telegram_report.sh >> "$LOG_FILE" 2>> "$ERROR_LOG"

# Keep only last 30 days of logs
find /var/log/ngtradingbot -name "daily_audit_*.log" -mtime +30 -delete 2>/dev/null

exit 0
