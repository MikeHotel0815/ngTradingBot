#!/usr/bin/env python3
"""
Phase 3 Telegram Notification Scheduler
Läuft als Background-Worker und prüft alle 6 Stunden automatisch

Verwendung:
    Als eigener Worker starten ODER in unified_worker.py integrieren
"""

import logging
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Import der Phase 3 Checker-Logik
from phase3_telegram_notifier import count_trades_with_metrics
from telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class Phase3NotificationScheduler:
    """Scheduled checker für Phase 3 Bereitschaft"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.notifier = TelegramNotifier()
        self.notified = False
        self.marker_file = "/tmp/phase3_notified.marker"

        # Prüfe ob schon benachrichtigt
        import os
        if os.path.exists(self.marker_file):
            self.notified = True
            logger.info("✅ Phase 3 Benachrichtigung bereits gesendet (Marker vorhanden)")

    def check_phase3_ready(self):
        """Prüfe ob Phase 3 bereit und sende Telegram wenn ja"""

        if self.notified:
            logger.debug("Phase 3 bereits benachrichtigt - Skip")
            return

        logger.info("🔍 Prüfe Phase 3 Status...")

        try:
            # Zähle Trades
            trade_count = count_trades_with_metrics()
            TARGET_MIN = 50

            logger.info(f"📊 Trades mit Metriken: {trade_count}/{TARGET_MIN}")

            if trade_count >= TARGET_MIN:
                logger.info(f"✅ Phase 3 BEREIT! ({trade_count} >= {TARGET_MIN})")

                if not self.notifier.enabled:
                    logger.warning("⚠️  Telegram nicht konfiguriert - keine Benachrichtigung")
                    return

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
                success = self.notifier.send_message(message, parse_mode='HTML')

                if success:
                    logger.info("✅ Phase 3 Telegram-Nachricht gesendet!")

                    # Setze Marker
                    import os
                    with open(self.marker_file, 'w') as f:
                        f.write(f"Phase 3 ready notified at {datetime.utcnow().isoformat()}\n")
                        f.write(f"Trade count: {trade_count}\n")

                    self.notified = True
                    logger.info("✅ Marker gesetzt - keine weiteren Benachrichtigungen")

                    # Stoppe Scheduler (Aufgabe erfüllt)
                    self.scheduler.shutdown()
                    logger.info("✅ Scheduler gestoppt (Aufgabe erfüllt)")
                else:
                    logger.error("❌ Fehler beim Senden der Telegram-Nachricht")
            else:
                logger.info(f"⏳ Noch nicht bereit ({trade_count}/{TARGET_MIN})")

        except Exception as e:
            logger.error(f"❌ Fehler beim Phase 3 Check: {e}", exc_info=True)

    def start(self):
        """Starte Scheduler"""

        if self.notified:
            logger.info("ℹ️  Phase 3 bereits benachrichtigt - Scheduler nicht gestartet")
            return

        # Alle 6 Stunden (0:00, 6:00, 12:00, 18:00 UTC)
        self.scheduler.add_job(
            self.check_phase3_ready,
            CronTrigger(hour='*/6'),
            id='phase3_check',
            name='Phase 3 Readiness Check',
            replace_existing=True
        )

        # Erste Prüfung sofort (beim Start)
        logger.info("🚀 Phase 3 Notification Scheduler gestartet")
        logger.info("   Intervall: Alle 6 Stunden (0:00, 6:00, 12:00, 18:00 UTC)")
        logger.info("   Ziel: 50 Trades mit Metriken")
        logger.info("   Erste Prüfung: JETZT")

        self.scheduler.start()

        # Erste Prüfung sofort
        self.check_phase3_ready()

        logger.info("✅ Scheduler läuft im Hintergrund")

    def stop(self):
        """Stoppe Scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("✅ Phase 3 Scheduler gestoppt")


# Globale Instanz
_scheduler = None


def get_phase3_scheduler():
    """Singleton für Phase 3 Scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = Phase3NotificationScheduler()
    return _scheduler


def start_phase3_scheduler():
    """Start Phase 3 Scheduler (für unified_worker.py Integration)"""
    scheduler = get_phase3_scheduler()
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    # Standalone Mode - läuft als eigener Worker
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 60)
    logger.info("Phase 3 Notification Scheduler - Standalone Mode")
    logger.info("=" * 60)

    scheduler = Phase3NotificationScheduler()
    scheduler.start()

    try:
        # Halte Prozess am Leben
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutdown angefordert...")
        scheduler.stop()
        logger.info("✅ Beendet")
        sys.exit(0)
