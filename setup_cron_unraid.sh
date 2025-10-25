#!/bin/bash
# Setup Cron-Job für Phase 3 Telegram-Benachrichtigung auf Unraid Host

echo "=========================================="
echo "📅 CRON-JOB SETUP für Phase 3 Reminder"
echo "=========================================="
echo ""

# Prüfe ob auf Unraid
if [ ! -f /boot/config/go ]; then
    echo "⚠️  Warnung: Nicht auf Unraid erkannt"
    echo "   Aber Script funktioniert trotzdem auf Linux"
fi

# Cron-Job Zeile
CRON_LINE="0 */6 * * * docker exec ngtradingbot_workers python3 /app/phase3_telegram_notifier.py >> /mnt/user/appdata/ngtradingbot/logs/phase3_cron.log 2>&1"

echo "Cron-Job wird hinzugefügt:"
echo "$CRON_LINE"
echo ""

# Prüfe ob schon existiert
if crontab -l 2>/dev/null | grep -q "phase3_telegram_notifier.py"; then
    echo "ℹ️  Cron-Job existiert bereits!"
    crontab -l | grep "phase3_telegram_notifier.py"
    echo ""
    read -p "Ersetzen? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Abgebrochen"
        exit 0
    fi
    # Entferne alte Version
    crontab -l | grep -v "phase3_telegram_notifier.py" | crontab -
fi

# Füge neuen Cron-Job hinzu
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

if [ $? -eq 0 ]; then
    echo "✅ Cron-Job erfolgreich hinzugefügt!"
else
    echo "❌ Fehler beim Hinzufügen!"
    exit 1
fi

echo ""
echo "Aktueller Crontab:"
crontab -l | tail -5

echo ""
echo "=========================================="
echo "✅ SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "📊 WAS JETZT PASSIERT:"
echo "   - Alle 6 Stunden (0:00, 6:00, 12:00, 18:00 Uhr)"
echo "   - Script prüft ob Phase 3 bereit ist"
echo "   - Bei 50+ Trades: Telegram-Nachricht"
echo ""
echo "🔍 LOGS:"
echo "   tail -f /mnt/user/appdata/ngtradingbot/logs/phase3_cron.log"
echo ""
echo "🧪 TEST (jetzt ausführen):"
echo "   docker exec ngtradingbot_workers python3 /app/phase3_telegram_notifier.py"
echo ""
