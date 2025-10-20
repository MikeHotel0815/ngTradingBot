#!/bin/bash
# Setup Automated Daily Monitoring for ngTradingBot
# This script installs cron jobs for automatic daily monitoring

set -e

echo "=========================================="
echo "ngTradingBot - Automated Monitoring Setup"
echo "=========================================="
echo ""

# Create log directory
LOG_DIR="/var/log/ngtradingbot"
echo "📁 Creating log directory: $LOG_DIR"
sudo mkdir -p "$LOG_DIR"
sudo chown $(whoami):$(whoami) "$LOG_DIR"
echo "   ✅ Log directory created"
echo ""

# Create the monitoring script
MONITOR_SCRIPT="/projects/ngTradingBot/daily_monitor_job.sh"
echo "📝 Creating monitoring script: $MONITOR_SCRIPT"

cat > "$MONITOR_SCRIPT" << 'SCRIPT_END'
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

# Keep only last 30 days of logs
find /var/log/ngtradingbot -name "daily_audit_*.log" -mtime +30 -delete 2>/dev/null

exit 0
SCRIPT_END

chmod +x "$MONITOR_SCRIPT"
echo "   ✅ Monitoring script created and executable"
echo ""

# Install cron job
echo "⏰ Installing cron job..."
CRON_LINE="0 8 * * * $MONITOR_SCRIPT"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$MONITOR_SCRIPT"; then
    echo "   ℹ️  Cron job already exists, updating..."
    crontab -l | grep -v "$MONITOR_SCRIPT" | crontab -
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "   ✅ Cron job installed: Runs daily at 8:00 AM"
echo ""

# Show installed cron jobs
echo "📋 Installed cron jobs:"
crontab -l | grep -E "ngTradingBot|daily_monitor"
echo ""

# Create a manual run script
MANUAL_SCRIPT="/projects/ngTradingBot/run_daily_audit.sh"
echo "📝 Creating manual run script: $MANUAL_SCRIPT"

cat > "$MANUAL_SCRIPT" << 'MANUAL_END'
#!/bin/bash
# Manual Daily Audit
# Run this anytime to see current status

echo "Running daily audit now..."
/projects/ngTradingBot/daily_monitor_job.sh

echo ""
echo "✅ Audit complete!"
echo ""
echo "View log:"
echo "  cat /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log"
echo ""
echo "View all logs:"
echo "  ls -lh /var/log/ngtradingbot/"
echo ""
MANUAL_END

chmod +x "$MANUAL_SCRIPT"
echo "   ✅ Manual run script created"
echo ""

# Test the setup
echo "🧪 Running test audit..."
"$MONITOR_SCRIPT"
TEST_LOG="/var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log"

if [ -f "$TEST_LOG" ]; then
    echo "   ✅ Test successful! Log created:"
    echo ""
    echo "   Last 20 lines of log:"
    echo "   ──────────────────────────────────────"
    tail -20 "$TEST_LOG" | sed 's/^/   /'
    echo "   ──────────────────────────────────────"
else
    echo "   ⚠️  Warning: Test log not found"
fi

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "📍 What was installed:"
echo "   • Cron job: Daily at 8:00 AM"
echo "   • Log directory: $LOG_DIR"
echo "   • Monitoring script: $MONITOR_SCRIPT"
echo "   • Manual run script: $MANUAL_SCRIPT"
echo ""
echo "📖 How to use:"
echo "   • View today's log:"
echo "     cat /var/log/ngtradingbot/daily_audit_$(date +%Y%m%d).log"
echo ""
echo "   • Run manual audit now:"
echo "     $MANUAL_SCRIPT"
echo ""
echo "   • View all logs:"
echo "     ls -lh /var/log/ngtradingbot/"
echo ""
echo "   • Edit cron schedule:"
echo "     crontab -e"
echo ""
echo "   • Disable automatic monitoring:"
echo "     crontab -l | grep -v daily_monitor_job.sh | crontab -"
echo ""
echo "🎉 Automated monitoring is now active!"
echo ""
