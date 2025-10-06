#!/usr/bin/env python3
"""
Trade Monitor for ngTradingBot
Monitors open positions in real-time and provides P&L tracking with smart trailing stops
"""

import logging
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from database import ScopedSession
from models import Trade, Account, Tick
from redis_client import get_redis
from trailing_stop_manager import get_trailing_stop_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TradeMonitor:
    """Monitors open trades and calculates real-time P&L with smart trailing stops"""

    def __init__(self):
        self.redis = get_redis()
        self.monitor_interval = 5  # Check every 5 seconds
        self.running = False
        self.trailing_stop_manager = get_trailing_stop_manager()
        self.trailing_stops_processed = 0

    def get_current_price(self, db: Session, account_id: int, symbol: str) -> Optional[Dict]:
        """Get current bid/ask prices for symbol"""
        try:
            latest_tick = db.query(Tick).filter_by(
                account_id=account_id,
                symbol=symbol
            ).order_by(Tick.timestamp.desc()).first()

            if latest_tick:
                return {
                    'bid': latest_tick.bid,
                    'ask': latest_tick.ask,
                    'timestamp': latest_tick.timestamp
                }
            return None
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def calculate_position_pnl(self, trade: Trade, current_price: Dict) -> Dict:
        """Calculate current P&L for open position"""
        try:
            # Determine direction (handle both string and numeric formats)
            is_buy = trade.direction.upper() in ['BUY', '0'] if isinstance(trade.direction, str) else trade.direction == 0

            # Determine close price based on direction
            if is_buy:  # BUY position
                close_price = current_price['bid']  # Close at bid
            else:  # SELL position
                close_price = current_price['ask']  # Close at ask

            # Calculate P&L
            if is_buy:  # BUY
                pnl = (close_price - trade.open_price) * trade.volume
            else:  # SELL
                pnl = (trade.open_price - close_price) * trade.volume

            # Calculate points moved
            points = abs(close_price - trade.open_price)

            # Distance to TP/SL
            distance_to_tp = None
            distance_to_sl = None

            if trade.tp:
                if is_buy:  # BUY
                    distance_to_tp = trade.tp - close_price
                else:  # SELL
                    distance_to_tp = close_price - trade.tp

            if trade.sl:
                if is_buy:  # BUY
                    distance_to_sl = close_price - trade.sl
                else:  # SELL
                    distance_to_sl = trade.sl - close_price

            return {
                'current_price': close_price,
                'pnl': round(pnl, 2),
                'points': round(points, 5),
                'distance_to_tp': round(distance_to_tp, 5) if distance_to_tp else None,
                'distance_to_sl': round(distance_to_sl, 5) if distance_to_sl else None,
                'tp_reached': distance_to_tp is not None and distance_to_tp <= 0,
                'sl_reached': distance_to_sl is not None and distance_to_sl <= 0
            }

        except Exception as e:
            logger.error(f"Error calculating P&L for trade {trade.ticket}: {e}")
            return None

    def monitor_open_trades(self, db: Session):
        """Monitor all open trades for an account"""
        try:
            # Get all open trades
            open_trades = db.query(Trade).filter(
                Trade.status == 'open'
            ).all()

            if not open_trades:
                return

            total_pnl = 0
            positions_data = []

            for trade in open_trades:
                # Get current price
                current_price = self.get_current_price(db, trade.account_id, trade.symbol)

                if not current_price:
                    logger.warning(f"No price data for {trade.symbol} (Trade {trade.ticket})")
                    continue

                # Calculate P&L
                pnl_data = self.calculate_position_pnl(trade, current_price)

                if not pnl_data:
                    continue

                total_pnl += pnl_data['pnl']

                position_info = {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'direction': trade.direction.upper() if isinstance(trade.direction, str) else ('BUY' if trade.direction == 0 else 'SELL'),
                    'volume': float(trade.volume),
                    'open_price': float(trade.open_price),
                    'current_price': pnl_data['current_price'],
                    'pnl': pnl_data['pnl'],
                    'tp': float(trade.tp) if trade.tp else None,
                    'sl': float(trade.sl) if trade.sl else None,
                    'distance_to_tp': pnl_data['distance_to_tp'],
                    'distance_to_sl': pnl_data['distance_to_sl'],
                    'open_time': trade.open_time.isoformat() if trade.open_time else None,
                    'source': trade.source,
                    'signal_id': trade.signal_id
                }

                positions_data.append(position_info)

                # Process trailing stop for profitable trades
                if pnl_data['pnl'] > 0 and trade.tp and trade.sl:
                    try:
                        trailing_result = self.trailing_stop_manager.process_trade(
                            db=db,
                            trade=trade,
                            current_price=pnl_data['current_price']
                        )
                        if trailing_result:
                            self.trailing_stops_processed += 1
                            logger.info(
                                f"🎯 Trailing Stop Applied: {trade.symbol} #{trade.ticket} - "
                                f"Stage: {trailing_result['stage']}, SL: {trailing_result['old_sl']:.5f} → {trailing_result['new_sl']:.5f}"
                            )
                    except Exception as e:
                        logger.error(f"Error processing trailing stop for trade {trade.ticket}: {e}")

                # Alert if TP/SL about to be hit
                if pnl_data['tp_reached']:
                    logger.info(f"🎯 TP REACHED: Trade {trade.ticket} ({trade.symbol}) - P&L: ${pnl_data['pnl']}")

                if pnl_data['sl_reached']:
                    logger.warning(f"🛑 SL REACHED: Trade {trade.ticket} ({trade.symbol}) - P&L: ${pnl_data['pnl']}")

            # Cache monitoring data in Redis
            if positions_data:
                for account_id in set(t.account_id for t in open_trades):
                    account_positions = [p for p in positions_data if any(
                        t.ticket == p['ticket'] and t.account_id == account_id for t in open_trades
                    )]

                    monitoring_data = {
                        'positions': account_positions,
                        'total_pnl': round(total_pnl, 2),
                        'position_count': len(account_positions),
                        'last_update': datetime.utcnow().isoformat()
                    }

                    # Cache for 30 seconds
                    import json
                    from decimal import Decimal

                    # Custom JSON encoder to handle Decimal types
                    class DecimalEncoder(json.JSONEncoder):
                        def default(self, obj):
                            if isinstance(obj, Decimal):
                                return float(obj)
                            return super(DecimalEncoder, self).default(obj)

                    self.redis.set_with_expiry(
                        f"monitoring:account:{account_id}",
                        json.dumps(monitoring_data, cls=DecimalEncoder),
                        30
                    )

                logger.info(f"📊 Monitoring {len(positions_data)} positions - Total P&L: ${round(total_pnl, 2)}")

        except Exception as e:
            logger.error(f"Error monitoring trades: {e}")

    def monitor_loop(self):
        """Main monitoring loop"""
        logger.info(f"Trade Monitor started (interval: {self.monitor_interval}s)")

        self.running = True

        while self.running:
            try:
                db = ScopedSession()
                self.monitor_open_trades(db)
                db.close()

                time.sleep(self.monitor_interval)

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                time.sleep(5)

    def stop(self):
        """Stop monitoring loop"""
        self.running = False
        logger.info("Trade Monitor stopped")


# Singleton instance
_monitor = None


def get_monitor():
    """Get or create monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = TradeMonitor()
    return _monitor


def start_trade_monitor():
    """Start trade monitor in background thread"""
    monitor = get_monitor()
    thread = Thread(target=monitor.monitor_loop, daemon=True)
    thread.start()
    logger.info("Trade Monitor thread started")
    return monitor


if __name__ == '__main__':
    # Run standalone
    monitor = TradeMonitor()
    monitor.monitor_loop()
