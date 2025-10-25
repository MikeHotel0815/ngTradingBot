#!/bin/bash
# Phase 3 Checker - Läuft alle 6 Stunden automatisch im Hintergrund

echo "🚀 Starting Phase 3 Telegram Checker..."

# Infinite Loop - prüft alle 6 Stunden
while true; do
    echo "$(date): Checking Phase 3 status..."

    docker exec ngtradingbot_workers python3 << 'PYTHON_EOF'
import os
from datetime import datetime
os.environ['TELEGRAM_BOT_TOKEN'] = '8454891267:AAHKrGTcGCVfXjb0LNjq6QAC816Un9ig7VA'
os.environ['TELEGRAM_CHAT_ID'] = '557944459'

from phase3_telegram_notifier import main
main()
PYTHON_EOF

    # Warte 6 Stunden (21600 Sekunden)
    echo "$(date): Next check in 6 hours..."
    sleep 21600
done
