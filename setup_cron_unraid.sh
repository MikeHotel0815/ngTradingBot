#!/bin/bash
# Setup Cron-Jobs für ngTradingBot auf Unraid Host

echo "=========================================="
echo "📅 CRON-JOB SETUP für ngTradingBot"
echo "=========================================="
echo ""

# Prüfe ob auf Unraid
if [ ! -f /boot/config/go ]; then
    echo "⚠️  Warnung: Nicht auf Unraid erkannt"
    echo "   Aber Script funktioniert trotzdem auf Linux"
fi

# Cron-Job Zeilen
CRON_PHASE3="0 */6 * * * docker exec ngtradingbot_workers python3 /app/phase3_telegram_notifier.py >> /mnt/user/appdata/ngtradingbot/logs/phase3_cron.log 2>&1"
CRON_PERFORMANCE="0 18 * * * /projects/ngTradingBot/daily_performance_report.sh >> /projects/ngTradingBot/logs/cron.log 2>&1"

echo "📊 Cron-Job 1: Daily Performance Report (18:00 Uhr)"
echo "$CRON_PERFORMANCE"
echo ""

echo "🔔 Cron-Job 2: Phase 3 Reminder (alle 6h)"
echo "$CRON_PHASE3"
echo ""

# Prüfe ob Performance Report schon existiert
if crontab -l 2>/dev/null | grep -q "daily_performance_report.sh"; then
    echo "ℹ️  Performance Report Cron-Job existiert bereits!"
    crontab -l | grep "daily_performance_report.sh"
else
    echo "➕ Füge Performance Report Cron-Job hinzu..."
    (crontab -l 2>/dev/null; echo "$CRON_PERFORMANCE") | crontab -
    if [ $? -eq 0 ]; then
        echo "✅ Performance Report Cron-Job hinzugefügt!"
    else
        echo "❌ Fehler beim Hinzufügen!"
        exit 1
    fi
fi

echo ""

# Prüfe ob Phase3 schon existiert
if crontab -l 2>/dev/null | grep -q "phase3_telegram_notifier.py"; then
    echo "ℹ️  Phase 3 Cron-Job existiert bereits!"
    crontab -l | grep "phase3_telegram_notifier.py"
else
    echo "➕ Füge Phase 3 Cron-Job hinzu..."
    (crontab -l 2>/dev/null; echo "$CRON_PHASE3") | crontab -
    if [ $? -eq 0 ]; then
        echo "✅ Phase 3 Cron-Job hinzugefügt!"
    else
        echo "❌ Fehler beim Hinzufügen!"
        exit 1
    fi
fi

echo ""
echo "Aktueller Crontab:"
crontab -l | tail -5

echo ""
echo "=========================================="
echo "✅ SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "📊 AKTIVE CRON-JOBS:"
echo ""
echo "1️⃣  Daily Performance Report"
echo "   Zeitplan: Täglich um 18:00 Uhr"
echo "   Funktion: Dashboard generieren + Telegram senden"
echo "   Script: /projects/ngTradingBot/daily_performance_report.sh"
echo ""
echo "2️⃣  Phase 3 Reminder"
echo "   Zeitplan: Alle 6 Stunden (0:00, 6:00, 12:00, 18:00)"
echo "   Funktion: Prüft ob Phase 3 bereit ist (50+ Trades)"
echo "   Script: phase3_telegram_notifier.py"
echo ""
echo "🔍 LOGS:"
echo "   Performance: tail -f /projects/ngTradingBot/logs/cron.log"
echo "   Performance Dashboard: ls -lh /projects/ngTradingBot/logs/performance_dashboard_*.txt"
echo "   Phase 3: tail -f /mnt/user/appdata/ngtradingbot/logs/phase3_cron.log"
echo ""
echo "🧪 MANUELLER TEST:"
echo "   Performance: /projects/ngTradingBot/daily_performance_report.sh"
echo "   Phase 3: docker exec ngtradingbot_workers python3 /app/phase3_telegram_notifier.py"
echo ""
