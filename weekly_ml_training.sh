#!/bin/bash
# Weekly ML Model Training
# Runs every Sunday at 2:00 AM
# Add to Unraid cron: 0 2 * * 0 /projects/ngTradingBot/weekly_ml_training.sh

LOG_FILE="/projects/ngTradingBot/data/ml_training_$(date +\%Y\%m\%d_\%H\%M\%S).log"

echo "========================================" | tee -a "$LOG_FILE"
echo "🤖 Weekly ML Training - $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# Check if container is running
if ! docker ps | grep -q ngtradingbot_workers; then
    echo "❌ ERROR: ngtradingbot_workers container not running" | tee -a "$LOG_FILE"
    exit 1
fi

# Run training
echo "📊 Starting training..." | tee -a "$LOG_FILE"
docker exec ngtradingbot_workers python3 /app/train_ml_models.py 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Training completed successfully!" | tee -a "$LOG_FILE"

    # Send Telegram notification (optional)
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        MESSAGE="🤖 ML Training completed successfully!%0A%0ACheck logs: $LOG_FILE"
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_CHAT_ID" \
            -d "text=$MESSAGE" \
            -d "parse_mode=HTML" > /dev/null
    fi
else
    echo "❌ Training failed with exit code: $EXIT_CODE" | tee -a "$LOG_FILE"

    # Send error notification
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        MESSAGE="❌ ML Training FAILED!%0A%0AExit code: $EXIT_CODE%0ACheck logs: $LOG_FILE"
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$TELEGRAM_CHAT_ID" \
            -d "text=$MESSAGE" \
            -d "parse_mode=HTML" > /dev/null
    fi
fi

echo "========================================" | tee -a "$LOG_FILE"
echo "🏁 Training job finished at $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# Cleanup old logs (keep last 30 days)
find /projects/ngTradingBot/data -name "ml_training_*.log" -mtime +30 -delete 2>/dev/null

exit $EXIT_CODE
