#!/usr/bin/env python3
"""
Phase 3 Telegram Notifier - Nutzt vorhandenes telegram_notifier.py

Prüft alle 6 Stunden ob Phase 3 bereit ist und sendet Telegram-Nachricht.
Nutzt die bereits vorhandene TelegramNotifier-Infrastruktur!
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Import der vorhandenen Telegram-Infrastruktur
from telegram_notifier import TelegramNotifier
from database import get_db
from models import Trade
from sqlalchemy import and_


def count_trades_with_metrics():
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


def main():
    """Prüfe Status und sende Telegram-Benachrichtigung wenn bereit"""

    # Initialisiere Telegram (liest automatisch aus .env)
    notifier = TelegramNotifier()

    if not notifier.enabled:
        print("❌ Telegram nicht konfiguriert!")
        print("")
        print("Setup:")
        print("1. Erstelle Bot bei @BotFather (Telegram)")
        print("2. Füge zu .env hinzu:")
        print("   TELEGRAM_BOT_TOKEN=your_token")
        print("   TELEGRAM_CHAT_ID=your_chat_id")
        print("")
        print("Hilfe: python get_telegram_chat_id.py YOUR_BOT_TOKEN")
        sys.exit(1)

    # Prüfe ob schon benachrichtigt
    marker_file = "/tmp/phase3_notified.marker"
    if os.path.exists(marker_file):
        print("ℹ️  Benachrichtigung bereits gesendet")
        return

    # Zähle Trades
    trade_count = count_trades_with_metrics()
    print(f"📊 Trades mit Metriken: {trade_count}")

    TARGET_MIN = 50

    if trade_count >= TARGET_MIN:
        print(f"✅ Ziel erreicht! ({trade_count} >= {TARGET_MIN})")

        # Erstelle Nachricht
        message = f"""
🚀 <b>PHASE 3 BEREIT!</b>

<b>Status:</b>
• Trades gesammelt: {trade_count}
• Zeit: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

<b>Nächster Schritt:</b>
→ Starte Claude Code
→ Sage: "Starte Phase 3 Analyse"

Das System hat genug Daten für intelligente Erkenntnisse! 📊

Ich kann jetzt analysieren:
✅ Session-basierte Performance
✅ Indicator-Korrelationen
✅ Symbol-spezifische Optimierungen

<i>Datensammlung läuft seit {(datetime.utcnow() - datetime(2025, 10, 25, 15, 16)).days} Tagen</i>
"""

        # Sende Nachricht
        success = notifier.send_message(message, parse_mode='HTML')

        if success:
            print("✅ Telegram-Nachricht gesendet!")

            # Setze Marker
            with open(marker_file, 'w') as f:
                f.write(f"Phase 3 ready notified at {datetime.utcnow().isoformat()}\n")
                f.write(f"Trade count: {trade_count}\n")

            print("✅ Marker gesetzt - keine weiteren Benachrichtigungen")
        else:
            print("❌ Fehler beim Senden")

    else:
        print(f"⏳ Noch nicht bereit ({trade_count}/{TARGET_MIN})")


if __name__ == "__main__":
    main()
