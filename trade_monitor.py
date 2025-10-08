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
from models import Trade, Account, Tick, GlobalSettings
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
        self.monitor_interval = 1  # Check every 1 second for real-time updates
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

    def get_eurusd_rate(self, db: Session, account_id: int) -> float:
        """Get current EUR/USD exchange rate for currency conversion"""
        try:
            eurusd_tick = db.query(Tick).filter_by(
                account_id=account_id,
                symbol='EURUSD'
            ).order_by(Tick.timestamp.desc()).first()

            if eurusd_tick:
                # Use mid price for conversion
                return float((eurusd_tick.bid + eurusd_tick.ask) / 2)
            else:
                # Fallback rate if no EURUSD data available
                logger.warning("No EURUSD rate available, using fallback rate 1.17")
                return 1.17
        except Exception as e:
            logger.error(f"Error getting EURUSD rate: {e}")
            return 1.17  # Fallback

    def calculate_position_pnl(self, trade: Trade, current_price: Dict, eurusd_rate: float = None) -> Dict:
        """
        Calculate current P&L for open position in EUR (account currency)

        CRITICAL FIX: Use MT5 profit directly - it's already correct in account currency!
        The EA sends profit from PositionGetDouble(POSITION_PROFIT) which is always accurate.
        We only calculate distance to TP/SL here for display purposes.
        """
        try:
            # Determine direction (handle both string and numeric formats)
            is_buy = trade.direction.upper() in ['BUY', '0'] if isinstance(trade.direction, str) else trade.direction == 0

            # Determine close price based on direction
            if is_buy:  # BUY position
                close_price = float(current_price['bid'])  # Close at bid
            else:  # SELL position
                close_price = float(current_price['ask'])  # Close at ask

            # Convert all values to float to avoid Decimal/float type errors
            open_price = float(trade.open_price)
            close_price_val = close_price  # Already converted above
            volume = float(trade.volume)

            # ✅ FIXED: Use MT5 profit directly - it's already correct in account currency (EUR)!
            # The previous calculation was completely broken and showed wrong values
            mt5_profit = float(trade.profit) if trade.profit else 0.0

            # Log correct P&L (not the broken calculation)
            logger.debug(
                f"✓ {trade.symbol} ticket {trade.ticket}: P&L=€{mt5_profit:.2f} "
                f"(open={open_price:.5f}, current={close_price_val:.5f}, "
                f"distance={(close_price_val - open_price) * 10000:.1f} pips)"
            )

            # Calculate points moved (for display only)
            points = abs(close_price - open_price)

            # Distance to TP/SL in price points (for display)
            distance_to_tp = None
            distance_to_sl = None

            if trade.tp:
                tp_val = float(trade.tp)
                if is_buy:  # BUY
                    distance_to_tp = tp_val - close_price_val
                else:  # SELL
                    distance_to_tp = close_price_val - tp_val

            if trade.sl:
                sl_val = float(trade.sl)
                if is_buy:  # BUY
                    distance_to_sl = close_price_val - sl_val
                else:  # SELL
                    distance_to_sl = sl_val - close_price_val

            return {
                'current_price': close_price,
                'pnl': round(mt5_profit, 2),  # ✅ Use MT5 profit - already correct!
                'points': round(points, 5),
                'distance_to_tp': round(distance_to_tp, 5) if distance_to_tp else None,
                'distance_to_tp_eur': None,  # Remove broken EUR calculation
                'distance_to_sl': round(distance_to_sl, 5) if distance_to_sl else None,
                'distance_to_sl_eur': None,  # Remove broken EUR calculation
                'tp_reached': distance_to_tp is not None and distance_to_tp <= 0,
                'sl_reached': distance_to_sl is not None and distance_to_sl <= 0
            }

        except Exception as e:
            logger.error(f"Error calculating P&L for trade {trade.ticket}: {e}")
            return None

    def broadcast_positions_update(self, db: Session, account_id: int):
        """Immediately calculate and broadcast position updates for real-time WebSocket"""
        try:
            # Get all open trades for this account
            open_trades = db.query(Trade).filter(
                Trade.account_id == account_id,
                Trade.status == 'open'
            ).all()

            if not open_trades:
                return

            total_pnl = 0
            positions_data = []

            # Check if trailing stop is enabled globally
            settings = db.query(GlobalSettings).first()
            trailing_stop_enabled = settings.trailing_stop_enabled if settings else False

            # Get EUR/USD rate for P&L conversion (only used if MT5 profit not available)
            eurusd_rate = self.get_eurusd_rate(db, account_id)

            for trade in open_trades:
                # Get current price for display and trailing stop
                current_price = self.get_current_price(db, trade.account_id, trade.symbol)

                if not current_price:
                    continue

                # IMPORTANT: Use MT5 profit directly - it's already correct in account currency (EUR)
                # The EA sends profit from PositionGetDouble(POSITION_PROFIT) which is always in account currency
                mt5_profit = float(trade.profit) if trade.profit else 0.0

                total_pnl += mt5_profit

                # Check if this trade has TP and SL (required for trailing stop)
                has_trailing_stop = trailing_stop_enabled and trade.tp and trade.sl

                # Calculate distance to TP/SL for display (but use MT5 profit for P&L)
                pnl_data = self.calculate_position_pnl(trade, current_price, eurusd_rate)

                # Get trailing stop info for display
                trailing_stop_info = None
                if has_trailing_stop:
                    # Extract float price from current_price dict (use BID for BUY, ASK for SELL)
                    if isinstance(current_price, dict):
                        close_price = float(current_price['bid']) if trade.direction == 'buy' else float(current_price['ask'])
                    else:
                        close_price = float(current_price) if current_price else float(trade.open_price)
                    trailing_stop_info = self.trailing_stop_manager.get_trailing_stop_info(
                        trade, close_price, db
                    )

                position_info = {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'direction': trade.direction.upper() if isinstance(trade.direction, str) else ('BUY' if trade.direction == 0 else 'SELL'),
                    'volume': float(trade.volume),
                    'open_price': float(trade.open_price),
                    'current_price': pnl_data['current_price'] if pnl_data else float(current_price['bid']),
                    'pnl': mt5_profit,  # ✅ Use MT5 profit directly - always correct!
                    'tp': float(trade.tp) if trade.tp else None,
                    'sl': float(trade.sl) if trade.sl else None,
                    'distance_to_tp': pnl_data.get('distance_to_tp') if pnl_data else None,
                    'distance_to_sl': pnl_data.get('distance_to_sl') if pnl_data else None,
                    'open_time': trade.open_time.isoformat() if trade.open_time else None,
                    'has_trailing_stop': has_trailing_stop,
                    'trailing_stop_info': trailing_stop_info,
                }
                positions_data.append(position_info)

            # Emit WebSocket event for real-time UI updates
            monitoring_data = {
                'account_id': account_id,
                'position_count': len(positions_data),
                'positions': positions_data,
                'total_pnl': round(total_pnl, 2),
                'timestamp': datetime.utcnow().isoformat()
            }

            from app import socketio
            socketio.emit('positions_update', monitoring_data, namespace='/', to=None)

        except Exception as e:
            logger.error(f"Error in broadcast_positions_update: {e}")

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

            # Check if trailing stop is enabled globally
            settings = db.query(GlobalSettings).first()
            trailing_stop_enabled = settings.trailing_stop_enabled if settings else False

            # Get EUR/USD rate once for all trades (account currency is EUR)
            # Use account_id from first trade (all trades should be from same account)
            first_account_id = open_trades[0].account_id if open_trades else 1
            eurusd_rate = self.get_eurusd_rate(db, first_account_id)
            logger.debug(f"Using EUR/USD rate: {eurusd_rate:.5f} for P&L conversion")

            for trade in open_trades:
                # Get current price for display and trailing stop
                current_price = self.get_current_price(db, trade.account_id, trade.symbol)

                if not current_price:
                    logger.warning(f"No price data for {trade.symbol} (Trade {trade.ticket})")
                    continue

                # IMPORTANT: Use MT5 profit directly - it's already correct in account currency (EUR)
                # The EA sends profit from PositionGetDouble(POSITION_PROFIT) which is always in account currency
                mt5_profit = float(trade.profit) if trade.profit else 0.0

                total_pnl += mt5_profit

                # Check if this trade has TP and SL (required for trailing stop)
                has_trailing_stop = trailing_stop_enabled and trade.tp and trade.sl

                # Calculate distance to TP/SL for display (but use MT5 profit for P&L)
                pnl_data = self.calculate_position_pnl(trade, current_price, eurusd_rate)

                # Get entry reason from signal if available
                entry_reason = None
                if trade.signal_id and trade.signal:
                    # Signal has reasons as JSONB array
                    if trade.signal.reasons:
                        entry_reason = ', '.join(trade.signal.reasons) if isinstance(trade.signal.reasons, list) else str(trade.signal.reasons)

                # Get trailing stop info for display
                trailing_stop_info = None
                if has_trailing_stop:
                    # Extract float price from current_price dict (use BID for BUY, ASK for SELL)
                    if isinstance(current_price, dict):
                        close_price = float(current_price['bid']) if trade.direction == 'buy' else float(current_price['ask'])
                    else:
                        close_price = float(current_price) if current_price else float(trade.open_price)
                    trailing_stop_info = self.trailing_stop_manager.get_trailing_stop_info(
                        trade, close_price, db
                    )

                position_info = {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'direction': trade.direction.upper() if isinstance(trade.direction, str) else ('BUY' if trade.direction == 0 else 'SELL'),
                    'volume': float(trade.volume),
                    'open_price': float(trade.open_price),
                    'current_price': pnl_data['current_price'] if pnl_data else float(current_price['bid']),
                    'pnl': mt5_profit,  # ✅ Use MT5 profit directly - always correct!
                    'tp': float(trade.tp) if trade.tp else None,
                    'sl': float(trade.sl) if trade.sl else None,
                    'distance_to_tp': pnl_data['distance_to_tp'] if pnl_data else None,
                    'distance_to_sl': pnl_data['distance_to_sl'] if pnl_data else None,
                    'has_trailing_stop': has_trailing_stop,
                    'open_time': trade.open_time.isoformat() if trade.open_time else None,
                    'source': trade.source,
                    'signal_id': trade.signal_id,
                    'timeframe': trade.timeframe,
                    'reason': entry_reason,
                    'trailing_stop_info': trailing_stop_info,
                }

                positions_data.append(position_info)

                # Process trailing stop for profitable trades
                if mt5_profit > 0 and trade.tp and trade.sl:
                    try:
                        trailing_result = self.trailing_stop_manager.process_trade(
                            db=db,
                            trade=trade,
                            current_price=pnl_data['current_price'] if pnl_data else float(current_price['bid'])
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
                if pnl_data and pnl_data.get('tp_reached'):
                    logger.info(f"🎯 TP REACHED: Trade {trade.ticket} ({trade.symbol}) - P&L: €{mt5_profit}")

                if pnl_data and pnl_data.get('sl_reached'):
                    logger.warning(f"🛑 SL REACHED: Trade {trade.ticket} ({trade.symbol}) - P&L: €{mt5_profit}")

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

                    # Emit WebSocket event for real-time UI updates
                    try:
                        from app import socketio
                        # Emit from background thread - use socketio.emit directly
                        socketio.emit('positions_update', monitoring_data, namespace='/', to=None)
                        logger.info(f"📡 WebSocket: Emitted positions_update for {len(account_positions)} positions to all clients")
                    except Exception as ws_error:
                        # Don't fail if WebSocket is not available
                        logger.warning(f"WebSocket emission failed (non-critical): {ws_error}")

                logger.info(f"📊 Monitoring {len(positions_data)} positions - Total P&L: €{round(total_pnl, 2)}")

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


def get_trade_monitor():
    """Alias for get_monitor() - for compatibility"""
    return get_monitor()


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
