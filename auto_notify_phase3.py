#!/usr/bin/env python3
"""
Automatische Benachrichtigung wenn Phase 3 bereit ist

Setup (auf deinem Server):
    1. Kopiere dieses Script
    2. Füge zu crontab hinzu:
       # Prüfe alle 6 Stunden
       0 */6 * * * cd /projects/ngTradingBot && python auto_notify_phase3.py

    3. Konfiguriere Benachrichtigungs-Methode unten
"""

import os
import sys
from datetime import datetime, timedelta
from database import get_db
from models import Trade
from sqlalchemy import and_

# ==================== KONFIGURATION ====================
NOTIFICATION_METHOD = "telegram"  # "file", "email", "telegram", "webhook"

# Email Settings (wenn NOTIFICATION_METHOD = "email")
EMAIL_TO = "deine@email.de"
EMAIL_FROM = "trading@bot.de"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "deine@email.de"
SMTP_PASSWORD = "dein_password"

# Telegram Settings (wenn NOTIFICATION_METHOD = "telegram")
# TODO: Füge hier deine Werte ein (siehe get_telegram_chat_id.py)
TELEGRAM_BOT_TOKEN = "DEIN_BOT_TOKEN_HIER"  # Von @BotFather
TELEGRAM_CHAT_ID = "DEINE_CHAT_ID_HIER"     # Von get_telegram_chat_id.py

# Webhook Settings (wenn NOTIFICATION_METHOD = "webhook")
WEBHOOK_URL = "https://your-webhook-url.com/notify"

# File Settings (Standard)
NOTIFICATION_FILE = "/tmp/phase3_ready.txt"
# =======================================================


def count_closed_trades_with_metrics():
    """Zähle geschlossene Trades mit vollständigen Metriken"""
    phase2_start = datetime(2025, 10, 25, 15, 16)  # UTC
    db = next(get_db())

    count = db.query(Trade).filter(
        and_(
            Trade.created_at >= phase2_start,
            Trade.status == 'closed',
            Trade.session.isnot(None),
            Trade.risk_reward_realized.isnot(None),
            Trade.hold_duration_minutes.isnot(None),
            Trade.pips_captured.isnot(None)
        )
    ).count()

    db.close()
    return count


def send_file_notification(trade_count):
    """Schreibe Benachrichtigung in File"""
    message = f"""
PHASE 3 BEREIT!
===============
Zeit: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC
Trades gesammelt: {trade_count}

Aktion erforderlich:
→ Starte Claude Code
→ Sage: "Starte Phase 3 Analyse"

Das System hat genug Daten für intelligente Erkenntnisse!
"""
    with open(NOTIFICATION_FILE, 'w') as f:
        f.write(message)
    print(f"✅ Benachrichtigung geschrieben: {NOTIFICATION_FILE}")


def send_email_notification(trade_count):
    """Sende Email-Benachrichtigung"""
    import smtplib
    from email.mime.text import MIMEText

    subject = "🚀 Trading Bot: Phase 3 Analyse bereit!"
    body = f"""
Hallo,

Dein Trading Bot hat genug Daten gesammelt für Phase 3!

Status:
- Trades mit Metriken: {trade_count}
- Zeitpunkt: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

Nächste Schritte:
1. Öffne Claude Code
2. Sage: "Starte Phase 3 Analyse"
3. Ich analysiere die Daten und gebe dir Empfehlungen

Das System kann jetzt intelligente Erkenntnisse über:
- Session-basierte Performance
- Indicator-Korrelationen
- Symbol-spezifische Optimierungen

liefern!

Grüße,
Dein Trading Bot
"""

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"✅ Email gesendet an {EMAIL_TO}")
    except Exception as e:
        print(f"❌ Email-Fehler: {e}")


def send_telegram_notification(trade_count):
    """Sende Telegram-Benachrichtigung"""
    import requests

    message = f"""
🚀 *PHASE 3 BEREIT!*

Status:
• Trades: {trade_count}
• Zeit: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

Nächster Schritt:
→ Starte Claude Code
→ Sage: "Starte Phase 3 Analyse"

Das System hat genug Daten gesammelt! 📊
"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        r = requests.post(url, json=payload)
        if r.status_code == 200:
            print("✅ Telegram-Nachricht gesendet")
        else:
            print(f"❌ Telegram-Fehler: {r.status_code}")
    except Exception as e:
        print(f"❌ Telegram-Fehler: {e}")


def send_webhook_notification(trade_count):
    """Sende Webhook-Benachrichtigung"""
    import requests

    payload = {
        'event': 'phase3_ready',
        'trade_count': trade_count,
        'timestamp': datetime.utcnow().isoformat(),
        'message': 'Phase 3 analysis ready to start'
    }

    try:
        r = requests.post(WEBHOOK_URL, json=payload)
        if r.status_code == 200:
            print("✅ Webhook gesendet")
        else:
            print(f"❌ Webhook-Fehler: {r.status_code}")
    except Exception as e:
        print(f"❌ Webhook-Fehler: {e}")


def main():
    """Prüfe Status und sende Benachrichtigung wenn bereit"""

    # Prüfe ob schon benachrichtigt wurde
    marker_file = "/tmp/phase3_notified.marker"
    if os.path.exists(marker_file):
        print("ℹ️  Benachrichtigung bereits gesendet (Marker existiert)")
        return

    # Zähle Trades
    trade_count = count_closed_trades_with_metrics()
    print(f"📊 Trades mit Metriken: {trade_count}")

    # Prüfe ob Minimum erreicht
    TARGET_MIN = 50

    if trade_count >= TARGET_MIN:
        print(f"✅ Ziel erreicht! ({trade_count} >= {TARGET_MIN})")

        # Sende Benachrichtigung
        if NOTIFICATION_METHOD == "file":
            send_file_notification(trade_count)
        elif NOTIFICATION_METHOD == "email":
            send_email_notification(trade_count)
        elif NOTIFICATION_METHOD == "telegram":
            send_telegram_notification(trade_count)
        elif NOTIFICATION_METHOD == "webhook":
            send_webhook_notification(trade_count)
        else:
            print(f"❌ Unbekannte Methode: {NOTIFICATION_METHOD}")
            return

        # Setze Marker damit wir nur einmal benachrichtigen
        with open(marker_file, 'w') as f:
            f.write(f"Phase 3 ready notified at {datetime.utcnow().isoformat()}\n")
            f.write(f"Trade count: {trade_count}\n")

        print("✅ Benachrichtigung gesendet und Marker gesetzt")
    else:
        print(f"⏳ Noch nicht bereit ({trade_count}/{TARGET_MIN})")


if __name__ == "__main__":
    main()
