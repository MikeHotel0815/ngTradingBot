#!/usr/bin/env python3
"""
TP/SL Monitor Worker
Continuously monitors open trades and alerts if any don't have TP/SL set
"""

import logging
import time
from datetime import datetime
from database import init_db, ScopedSession
from models import Trade, Log

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TPSLMonitor:
    def __init__(self):
        self.check_interval = 30  # Check every 30 seconds
        self.alerted_tickets = set()  # Track which tickets we've already alerted on

    def check_trades(self, db):
        """Check all open trades for missing TP/SL"""
        trades = db.query(Trade).filter(
            Trade.status == 'open',
            ((Trade.tp == 0) | (Trade.tp == None) | (Trade.sl == 0) | (Trade.sl == None))
        ).all()

        for trade in trades:
            if trade.ticket not in self.alerted_tickets:
                # New trade without TP/SL found!
                self.alert_missing_tpsl(db, trade)
                self.alerted_tickets.add(trade.ticket)

        # Clean up alerted tickets for closed trades
        open_tickets = set(t.ticket for t in db.query(Trade).filter_by(status='open').all())
        self.alerted_tickets = self.alerted_tickets & open_tickets

    def alert_missing_tpsl(self, db, trade: Trade):
        """Create alert for trade without TP/SL"""
        logger.error(
            f"⚠️  ALERT: Trade #{trade.ticket} ({trade.symbol} {trade.direction}) "
            f"is MISSING TP/SL! Entry: {trade.open_price}"
        )

        # Log to database
        log_entry = Log(
            account_id=trade.account_id,
            level='ERROR',
            message='Trade opened without TP/SL',
            details={
                'ticket': int(trade.ticket),
                'symbol': trade.symbol,
                'direction': trade.direction,
                'entry_price': float(trade.open_price) if trade.open_price else 0,
                'tp': float(trade.tp) if trade.tp else 0,
                'sl': float(trade.sl) if trade.sl else 0,
                'source': trade.source,
                'alert_type': 'MISSING_TPSL'
            },
            timestamp=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()

        logger.warning(f"  💡 Run: python3 fix_missing_tpsl.py --execute")

    def run(self):
        """Main monitoring loop"""
        logger.info("=" * 80)
        logger.info("TP/SL Monitor Worker Started")
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info("=" * 80)

        while True:
            try:
                with ScopedSession() as db:
                    self.check_trades(db)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)

            time.sleep(self.check_interval)


if __name__ == '__main__':
    init_db()
    monitor = TPSLMonitor()
    monitor.run()
