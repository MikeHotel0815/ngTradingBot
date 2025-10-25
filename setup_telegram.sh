#!/bin/bash
# Telegram-Benachrichtigung Setup Script

echo "=========================================="
echo "📱 TELEGRAM SETUP für Phase 3 Reminder"
echo "=========================================="
echo ""

# Schritt 1: Bot-Token
echo "Schritt 1: Bot erstellen"
echo "------------------------"
echo "1. Öffne Telegram"
echo "2. Suche nach @BotFather"
echo "3. Sende: /newbot"
echo "4. Folge den Anweisungen"
echo "5. Kopiere den Bot-Token"
echo ""
read -p "Bot-Token eingeben: " BOT_TOKEN

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ Kein Token eingegeben!"
    exit 1
fi

# Schritt 2: Erste Nachricht
echo ""
echo "Schritt 2: Chat-ID ermitteln"
echo "----------------------------"
echo "1. Öffne Telegram"
echo "2. Suche nach deinem Bot: @dein_bot_name"
echo "3. Sende eine Nachricht (z.B. 'Hallo')"
echo ""
read -p "Hast du eine Nachricht gesendet? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Bitte zuerst eine Nachricht senden!"
    exit 1
fi

# Schritt 3: Chat-ID abrufen
echo ""
echo "Ermittle Chat-ID..."
python3 get_telegram_chat_id.py "$BOT_TOKEN"

if [ $? -ne 0 ]; then
    echo "❌ Fehler beim Abrufen der Chat-ID"
    exit 1
fi

echo ""
read -p "Chat-ID eingeben (aus dem Output oben): " CHAT_ID

if [ -z "$CHAT_ID" ]; then
    echo "❌ Keine Chat-ID eingegeben!"
    exit 1
fi

# Schritt 4: Konfiguration schreiben
echo ""
echo "Schreibe Konfiguration..."

cat > telegram_config.py << EOF
# Telegram-Konfiguration (automatisch generiert)
TELEGRAM_BOT_TOKEN = "$BOT_TOKEN"
TELEGRAM_CHAT_ID = "$CHAT_ID"
EOF

# Update auto_notify_phase3.py
sed -i "s/TELEGRAM_BOT_TOKEN = \"DEIN_BOT_TOKEN_HIER\"/TELEGRAM_BOT_TOKEN = \"$BOT_TOKEN\"/g" auto_notify_phase3.py
sed -i "s/TELEGRAM_CHAT_ID = \"DEINE_CHAT_ID_HIER\"/TELEGRAM_CHAT_ID = \"$CHAT_ID\"/g" auto_notify_phase3.py

echo "✅ Konfiguration gespeichert!"
echo ""

# Schritt 5: Test
echo "Schritt 3: Test-Nachricht senden"
echo "--------------------------------"
read -p "Soll ich eine Test-Nachricht senden? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 << EOF
import requests

bot_token = "$BOT_TOKEN"
chat_id = "$CHAT_ID"

message = """
🎉 *Telegram Setup erfolgreich!*

Dein Trading Bot kann dich jetzt benachrichtigen.

Wenn Phase 3 bereit ist, bekommst du eine Nachricht wie diese:

🚀 *PHASE 3 BEREIT!*

Status:
• Trades: 73
• Zeit: 2025-10-28 10:00 UTC

Nächster Schritt:
→ Starte Claude Code
→ Sage: "Starte Phase 3 Analyse"

Das System hat genug Daten gesammelt! 📊
"""

url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
payload = {
    'chat_id': chat_id,
    'text': message,
    'parse_mode': 'Markdown'
}

try:
    r = requests.post(url, json=payload)
    if r.status_code == 200:
        print("✅ Test-Nachricht gesendet!")
        print("   Prüfe dein Telegram!")
    else:
        print(f"❌ Fehler: {r.status_code}")
        print(r.text)
except Exception as e:
    print(f"❌ Fehler: {e}")
EOF
fi

# Schritt 6: Cron-Job Setup
echo ""
echo "Schritt 4: Automatischen Check einrichten"
echo "-----------------------------------------"
echo ""
echo "Cron-Job Zeile:"
echo "0 */6 * * * cd $(pwd) && python3 auto_notify_phase3.py"
echo ""
read -p "Soll ich den Cron-Job automatisch hinzufügen? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Aktuellen Crontab sichern
    crontab -l > /tmp/crontab_backup.txt 2>/dev/null || true

    # Prüfe ob Job schon existiert
    if crontab -l 2>/dev/null | grep -q "auto_notify_phase3.py"; then
        echo "ℹ️  Cron-Job existiert bereits"
    else
        # Füge neuen Job hinzu
        (crontab -l 2>/dev/null; echo "0 */6 * * * cd $(pwd) && python3 auto_notify_phase3.py") | crontab -
        echo "✅ Cron-Job hinzugefügt!"
    fi
else
    echo ""
    echo "Manuelles Setup:"
    echo "1. crontab -e"
    echo "2. Füge hinzu: 0 */6 * * * cd $(pwd) && python3 auto_notify_phase3.py"
fi

# Fertig!
echo ""
echo "=========================================="
echo "✅ SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "📊 STATUS:"
echo "   - Bot-Token: ${BOT_TOKEN:0:20}..."
echo "   - Chat-ID: $CHAT_ID"
echo "   - Methode: Telegram"
echo "   - Check-Intervall: Alle 6 Stunden"
echo ""
echo "🎯 WAS JETZT?"
echo "   Das System prüft automatisch alle 6h den Status"
echo "   Wenn Phase 3 bereit ist, bekommst du eine Telegram-Nachricht!"
echo ""
echo "🔍 MANUELLE PRÜFUNG:"
echo "   python3 check_phase_status.py"
echo ""
echo "📅 ERWARTUNG:"
echo "   Benachrichtigung in 2-3 Tagen (27.-28. Oktober)"
echo ""
