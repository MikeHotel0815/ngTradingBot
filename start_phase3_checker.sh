#!/bin/bash
# Phase 3 Checker - Läuft alle 6 Stunden automatisch im Hintergrund

echo "🚀 Starting Phase 3 Telegram Checker..."

# Infinite Loop - prüft alle 6 Stunden
while true; do
    echo "$(date): Checking Phase 3 status..."

    docker exec ngtradingbot_workers python3 /app/phase3_telegram_notifier.py

    # Warte 6 Stunden (21600 Sekunden)
    echo "$(date): Next check in 6 hours..."
    sleep 21600
done
