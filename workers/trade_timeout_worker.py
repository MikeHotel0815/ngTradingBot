#!/usr/bin/env python3
"""
Trade Timeout Worker
Überwacht offene Trades und schließt oder alarmiert bei zu langer Laufzeit
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Füge Parent-Verzeichnis zum Path hinzu
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

# Import aus Parent-Verzeichnis
try:
    from db import get_db_session
    from models import Trade
except ImportError:
    # Falls Import fehlschlägt, nutze direkte DB-Verbindung
    from models import Trade, Base

    def get_db_session():
        """Erstelle DB-Session direkt"""
        database_url = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
        engine = create_engine(database_url)
        SessionLocal = sessionmaker(bind=engine)
        return SessionLocal()

# Logging-Konfiguration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('trade_timeout_worker')

# Konfiguration aus Environment
TRADE_TIMEOUT_HOURS = int(os.getenv('TRADE_TIMEOUT_HOURS', '24'))
TRADE_TIMEOUT_ENABLED = os.getenv('TRADE_TIMEOUT_ENABLED', 'true').lower() == 'true'
TRADE_TIMEOUT_ACTION = os.getenv('TRADE_TIMEOUT_ACTION', 'close')  # close, alert, ignore
CHECK_INTERVAL = 300  # 5 Minuten


class TradeTimeoutWorker:
    """Worker für automatisches Schließen/Warnen bei lang laufenden Trades"""

    def __init__(self):
        self.session = None
        self.timeout_hours = TRADE_TIMEOUT_HOURS
        self.enabled = TRADE_TIMEOUT_ENABLED
        self.action = TRADE_TIMEOUT_ACTION

        logger.info(f"Trade Timeout Worker initialisiert")
        logger.info(f"Timeout: {self.timeout_hours} Stunden")
        logger.info(f"Enabled: {self.enabled}")
        logger.info(f"Action: {self.action}")

    def connect_db(self):
        """Verbindung zur Datenbank herstellen"""
        try:
            self.session = get_db_session()
            logger.info("Datenbankverbindung hergestellt")
            return True
        except Exception as e:
            logger.error(f"Fehler bei Datenbankverbindung: {e}")
            return False

    def get_long_running_trades(self) -> List[Trade]:
        """Hole alle Trades, die länger als timeout_hours laufen"""
        try:
            if not self.session:
                if not self.connect_db():
                    return []

            timeout_threshold = datetime.utcnow() - timedelta(hours=self.timeout_hours)

            # Hole offene Trades, die vor dem Threshold erstellt wurden
            long_running_trades = self.session.query(Trade).filter(
                Trade.status == 'open',
                Trade.created_at < timeout_threshold
            ).all()

            logger.info(f"Gefunden: {len(long_running_trades)} lang laufende Trades")
            return long_running_trades

        except Exception as e:
            logger.error(f"Fehler beim Abrufen lang laufender Trades: {e}")
            return []

    def close_trade(self, trade: Trade) -> bool:
        """Schließe einen Trade automatisch"""
        try:
            runtime = datetime.utcnow() - trade.created_at
            runtime_hours = runtime.total_seconds() / 3600

            logger.info(
                f"Schließe Trade {trade.id} (Symbol: {trade.symbol}, "
                f"Laufzeit: {runtime_hours:.1f}h, Side: {trade.side})"
            )

            # Trade als geschlossen markieren
            trade.status = 'closed'
            trade.closed_at = datetime.utcnow()
            trade.close_reason = f'auto_timeout_after_{runtime_hours:.1f}h'

            # PnL berechnen falls möglich
            if trade.entry_price and trade.current_price:
                if trade.side == 'buy':
                    pnl = (trade.current_price - trade.entry_price) * trade.quantity
                else:  # sell/short
                    pnl = (trade.entry_price - trade.current_price) * trade.quantity

                trade.pnl = pnl
                logger.info(f"Trade {trade.id} geschlossen mit PnL: {pnl:.2f}")
            else:
                logger.warning(f"Trade {trade.id} geschlossen, aber PnL konnte nicht berechnet werden")

            self.session.commit()
            logger.info(f"✓ Trade {trade.id} erfolgreich geschlossen (Timeout)")
            return True

        except Exception as e:
            logger.error(f"Fehler beim Schließen von Trade {trade.id}: {e}")
            self.session.rollback()
            return False

    def alert_trade(self, trade: Trade):
        """Warnung für lang laufenden Trade"""
        runtime = datetime.utcnow() - trade.created_at
        runtime_hours = runtime.total_seconds() / 3600

        logger.warning(
            f"⚠️  TRADE TIMEOUT WARNUNG - Trade {trade.id} läuft seit {runtime_hours:.1f}h "
            f"(Symbol: {trade.symbol}, Side: {trade.side}, "
            f"Entry: {trade.entry_price}, Current: {trade.current_price})"
        )

    def process_long_running_trades(self):
        """Verarbeite alle lang laufenden Trades"""
        if not self.enabled:
            logger.debug("Trade Timeout ist deaktiviert (TRADE_TIMEOUT_ENABLED=false)")
            return

        try:
            long_running_trades = self.get_long_running_trades()

            if not long_running_trades:
                logger.debug("Keine lang laufenden Trades gefunden")
                return

            for trade in long_running_trades:
                runtime = datetime.utcnow() - trade.created_at
                runtime_hours = runtime.total_seconds() / 3600

                if self.action == 'close':
                    # Automatisch schließen
                    self.close_trade(trade)

                elif self.action == 'alert':
                    # Nur warnen
                    self.alert_trade(trade)

                elif self.action == 'ignore':
                    # Nichts tun
                    logger.debug(
                        f"Trade {trade.id} läuft seit {runtime_hours:.1f}h "
                        f"(Action: ignore)"
                    )
                else:
                    logger.error(f"Unbekannte Action: {self.action}")

        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten lang laufender Trades: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Hole Statistiken über Trade-Laufzeiten"""
        try:
            if not self.session:
                if not self.connect_db():
                    return {}

            # Offene Trades
            open_trades = self.session.query(Trade).filter(
                Trade.status == 'open'
            ).all()

            if not open_trades:
                return {
                    'total_open_trades': 0,
                    'avg_runtime_hours': 0,
                    'max_runtime_hours': 0,
                    'trades_over_timeout': 0
                }

            runtimes = []
            trades_over_timeout = 0
            timeout_threshold = datetime.utcnow() - timedelta(hours=self.timeout_hours)

            for trade in open_trades:
                runtime = datetime.utcnow() - trade.created_at
                runtime_hours = runtime.total_seconds() / 3600
                runtimes.append(runtime_hours)

                if trade.created_at < timeout_threshold:
                    trades_over_timeout += 1

            stats = {
                'total_open_trades': len(open_trades),
                'avg_runtime_hours': sum(runtimes) / len(runtimes) if runtimes else 0,
                'max_runtime_hours': max(runtimes) if runtimes else 0,
                'min_runtime_hours': min(runtimes) if runtimes else 0,
                'trades_over_timeout': trades_over_timeout,
                'timeout_threshold_hours': self.timeout_hours
            }

            return stats

        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Statistiken: {e}")
            return {}

    def run(self):
        """Hauptschleife des Workers"""
        logger.info("Trade Timeout Worker gestartet")
        logger.info(f"Prüfintervall: {CHECK_INTERVAL}s")

        if not self.enabled:
            logger.warning("Trade Timeout ist deaktiviert! Worker läuft im Monitoring-Modus.")

        iteration = 0

        while True:
            try:
                iteration += 1
                logger.info(f"=== Iteration {iteration} ===")

                # Verarbeite lang laufende Trades
                self.process_long_running_trades()

                # Zeige Statistiken alle 10 Iterationen (ca. alle 50 Minuten)
                if iteration % 10 == 0:
                    stats = self.get_statistics()
                    if stats:
                        logger.info("=== Trade Laufzeit-Statistiken ===")
                        logger.info(f"Offene Trades gesamt: {stats['total_open_trades']}")
                        logger.info(f"Durchschnittliche Laufzeit: {stats['avg_runtime_hours']:.1f}h")
                        logger.info(f"Maximale Laufzeit: {stats['max_runtime_hours']:.1f}h")
                        logger.info(f"Minimale Laufzeit: {stats['min_runtime_hours']:.1f}h")
                        logger.info(f"Trades über Timeout ({self.timeout_hours}h): {stats['trades_over_timeout']}")
                        logger.info("=" * 35)

                # Warte bis zum nächsten Check
                logger.debug(f"Warte {CHECK_INTERVAL}s bis zum nächsten Check...")
                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Worker durch Benutzer beendet")
                break

            except Exception as e:
                logger.error(f"Fehler in Hauptschleife: {e}")
                time.sleep(60)  # Bei Fehler 1 Minute warten

        logger.info("Trade Timeout Worker beendet")


if __name__ == '__main__':
    worker = TradeTimeoutWorker()
    worker.run()
