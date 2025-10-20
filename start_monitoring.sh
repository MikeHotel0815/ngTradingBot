#!/bin/bash
# Continuous Monitoring Service for ngTradingBot
# Runs in background and generates daily reports

LOG_DIR="/var/log/ngtradingbot"
mkdir -p "$LOG_DIR"

echo "🚀 Starting ngTradingBot Continuous Monitoring..."
echo "   Log Directory: $LOG_DIR"
echo "   Monitoring Interval: Every 24 hours at 8:00 AM"
echo ""

while true; do
    # Calculate seconds until next 8:00 AM
    current_epoch=$(date +%s)
    next_8am=$(date -d "tomorrow 08:00" +%s)
    sleep_seconds=$((next_8am - current_epoch))

    # If it's past 8 AM today but before 8 AM tomorrow
    if [ $(date +%H) -ge 8 ]; then
        next_8am=$(date -d "tomorrow 08:00" +%s)
        sleep_seconds=$((next_8am - current_epoch))
    else
        next_8am=$(date -d "today 08:00" +%s)
        sleep_seconds=$((next_8am - current_epoch))
    fi

    echo "⏰ Next audit: $(date -d @$next_8am '+%Y-%m-%d %H:%M:%S')"
    echo "   Sleeping for $((sleep_seconds / 3600)) hours..."

    sleep "$sleep_seconds"

    # Run the audit
    echo "📊 Running daily audit at $(date '+%Y-%m-%d %H:%M:%S')..."
    /projects/ngTradingBot/daily_monitor_job.sh

    echo "   ✅ Audit complete!"
    echo ""
done
