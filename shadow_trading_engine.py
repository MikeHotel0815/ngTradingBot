"""
Shadow Trading Engine - Simulates trades for disabled symbols to monitor recovery
"""

from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from models import (
    ShadowTrade, TradingSignal, SymbolPerformanceTracking,
    AutoOptimizationConfig, Account
)
from database import ScopedSession
import logging

logger = logging.getLogger(__name__)


class ShadowTradingEngine:
    """
    Simulates trades for disabled symbols without actual execution.
    This allows monitoring of performance recovery for potential re-enablement.
    """

    def __init__(self):
        self.db = ScopedSession()

    def __del__(self):
        self.db.close()

    def process_signal_for_disabled_symbol(self, signal: TradingSignal) -> ShadowTrade:
        """
        Create a shadow trade when a signal is generated for a disabled symbol.

        Args:
            signal: TradingSignal that would have been executed if symbol was enabled

        Returns:
            ShadowTrade record
        """
        try:
            # Get the latest performance tracking for this symbol
            perf = self.db.query(SymbolPerformanceTracking).filter(
                SymbolPerformanceTracking.account_id == signal.account_id,
                SymbolPerformanceTracking.symbol == signal.symbol,
                SymbolPerformanceTracking.status == 'disabled'
            ).order_by(SymbolPerformanceTracking.evaluation_date.desc()).first()

            if not perf:
                logger.warning(f"No disabled performance tracking found for {signal.symbol}")
                return None

            # Get account for position sizing
            account = self.db.query(Account).get(signal.account_id)
            if not account:
                logger.error(f"Account {signal.account_id} not found")
                return None

            # Calculate position size (same logic as live trading)
            lot_size = self._calculate_position_size(
                account.balance,
                signal.entry_price,
                signal.stop_loss,
                signal.symbol
            )

            # Create shadow trade
            shadow_trade = ShadowTrade(
                performance_tracking_id=perf.id,
                signal_id=signal.id,
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                lot_size=lot_size,
                confidence=signal.confidence,
                timeframe=signal.timeframe,
                entry_time=signal.created_at,
                status='open'
            )

            self.db.add(shadow_trade)
            self.db.commit()

            logger.info(f"🌑 Shadow trade created: {signal.symbol} {signal.direction} @ {signal.entry_price} (conf={signal.confidence}%)")

            return shadow_trade

        except Exception as e:
            logger.error(f"Error creating shadow trade: {e}")
            self.db.rollback()
            return None

    def update_shadow_trades(self, symbol: str, current_price: float, timestamp: datetime):
        """
        Update open shadow trades based on current price.
        Closes trades that hit SL/TP.

        Args:
            symbol: Trading symbol
            current_price: Current market price
            timestamp: Current timestamp
        """
        try:
            # Get all open shadow trades for this symbol
            open_shadows = self.db.query(ShadowTrade).filter(
                ShadowTrade.symbol == symbol,
                ShadowTrade.status == 'open'
            ).all()

            for shadow in open_shadows:
                # Check if SL or TP hit
                close_price = None
                close_reason = None

                if shadow.direction == 'BUY':
                    if current_price <= shadow.stop_loss:
                        close_price = shadow.stop_loss
                        close_reason = 'stop_loss'
                    elif current_price >= shadow.take_profit:
                        close_price = shadow.take_profit
                        close_reason = 'take_profit'
                else:  # SELL
                    if current_price >= shadow.stop_loss:
                        close_price = shadow.stop_loss
                        close_reason = 'stop_loss'
                    elif current_price <= shadow.take_profit:
                        close_price = shadow.take_profit
                        close_reason = 'take_profit'

                if close_price:
                    self._close_shadow_trade(shadow, close_price, close_reason, timestamp)

            self.db.commit()

        except Exception as e:
            logger.error(f"Error updating shadow trades for {symbol}: {e}")
            self.db.rollback()

    def _close_shadow_trade(self, shadow: ShadowTrade, close_price: float, reason: str, timestamp: datetime):
        """Close a shadow trade and calculate profit"""
        shadow.exit_price = close_price
        shadow.exit_time = timestamp
        shadow.status = 'closed'

        # Calculate profit (same as real trading)
        if shadow.direction == 'BUY':
            price_diff = close_price - shadow.entry_price
        else:  # SELL
            price_diff = shadow.entry_price - close_price

        # For XAUUSD: 1 lot = $100 per point, for BTCUSD: 1 lot = $1 per point
        point_value = 100 if shadow.symbol == 'XAUUSD' else 1
        shadow.profit = float(price_diff * shadow.lot_size * point_value)

        logger.info(f"🌑 Shadow trade closed: {shadow.symbol} {shadow.direction} | "
                   f"Entry: {shadow.entry_price} → Exit: {close_price} | "
                   f"Profit: ${shadow.profit:.2f} ({reason})")

    def calculate_daily_shadow_performance(self, symbol: str, account_id: int, date: datetime) -> dict:
        """
        Calculate shadow trading performance for a specific day.
        Used by PerformanceAnalyzer to evaluate re-enablement criteria.

        Args:
            symbol: Trading symbol
            account_id: Account ID
            date: Date to analyze

        Returns:
            dict with shadow performance metrics
        """
        try:
            # Get performance tracking for this symbol
            perf = self.db.query(SymbolPerformanceTracking).filter(
                SymbolPerformanceTracking.account_id == account_id,
                SymbolPerformanceTracking.symbol == symbol,
                SymbolPerformanceTracking.evaluation_date == date.date()
            ).first()

            if not perf:
                return {
                    'total_trades': 0,
                    'profitable_trades': 0,
                    'total_profit': 0.0,
                    'win_rate': 0.0
                }

            # Get all closed shadow trades for this day
            day_start = datetime.combine(date.date(), datetime.min.time())
            day_end = day_start + timedelta(days=1)

            shadows = self.db.query(ShadowTrade).filter(
                ShadowTrade.performance_tracking_id == perf.id,
                ShadowTrade.status == 'closed',
                ShadowTrade.exit_time >= day_start,
                ShadowTrade.exit_time < day_end
            ).all()

            total_trades = len(shadows)
            profitable_trades = sum(1 for s in shadows if s.profit > 0)
            total_profit = sum(s.profit for s in shadows)
            win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0.0

            return {
                'total_trades': total_trades,
                'profitable_trades': profitable_trades,
                'total_profit': float(total_profit),
                'win_rate': float(win_rate)
            }

        except Exception as e:
            logger.error(f"Error calculating shadow performance for {symbol}: {e}")
            return {
                'total_trades': 0,
                'profitable_trades': 0,
                'total_profit': 0.0,
                'win_rate': 0.0
            }

    def _calculate_position_size(self, balance: float, entry: float, sl: float, symbol: str) -> float:
        """
        Calculate position size based on account balance and risk.
        Uses same logic as live trading (2% risk per trade).

        CRITICAL: Validates all inputs to prevent division by zero and invalid calculations.
        """
        # CRITICAL VALIDATION #1: Check balance
        if balance <= 0:
            logger.error(f"Invalid balance: {balance}, using minimum lot size")
            return 0.01

        # CRITICAL VALIDATION #2: Check entry price
        if entry <= 0:
            logger.error(f"Invalid entry price: {entry}, using minimum lot size")
            return 0.01

        # CRITICAL VALIDATION #3: Check stop loss
        if sl <= 0:
            logger.error(f"Invalid stop loss: {sl}, using minimum lot size")
            return 0.01

        risk_percent = 2.0  # 2% risk per trade
        risk_amount = balance * (risk_percent / 100)

        # Calculate points at risk
        points_risk = abs(entry - sl)

        # CRITICAL VALIDATION #4: Check SL distance
        if points_risk <= 0:
            logger.warning(f"Invalid SL distance for {symbol}: {points_risk}")
            return 0.01

        # CRITICAL VALIDATION #5: SL distance sanity check - must be at least 0.1% of price
        min_sl_distance = entry * 0.001
        if points_risk < min_sl_distance:
            logger.warning(f"SL too tight for {symbol}: {points_risk} < {min_sl_distance}")
            return 0.01

        # Point value: XAUUSD = $100/lot, BTCUSD = $1/lot
        point_value = 100 if symbol == 'XAUUSD' else 1

        # CRITICAL VALIDATION #6: Check point value
        if point_value <= 0:
            logger.error(f"Invalid point value for {symbol}: {point_value}")
            return 0.01

        # Calculate denominator
        denominator = points_risk * point_value

        # CRITICAL VALIDATION #7: Check denominator before division
        if denominator <= 0:
            logger.error(f"Invalid denominator: {denominator}")
            return 0.01

        # Lot size = risk amount / (points at risk × point value)
        lot_size = risk_amount / denominator

        # Round to 2 decimals, minimum 0.01
        lot_size = max(0.01, round(lot_size, 2))

        # FINAL VALIDATION: Sanity check lot size range
        if lot_size <= 0 or lot_size > 100:
            logger.error(f"Calculated lot size out of range: {lot_size}")
            return 0.01

        return lot_size

    def get_shadow_trade_summary(self, symbol: str, account_id: int, days: int = 7) -> dict:
        """
        Get summary of shadow trading performance over the last N days.

        Args:
            symbol: Trading symbol
            account_id: Account ID
            days: Number of days to look back

        Returns:
            dict with summary metrics
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # Get performance tracking records
            perfs = self.db.query(SymbolPerformanceTracking).filter(
                SymbolPerformanceTracking.account_id == account_id,
                SymbolPerformanceTracking.symbol == symbol,
                SymbolPerformanceTracking.evaluation_date >= cutoff_date.date()
            ).all()

            if not perfs:
                return {
                    'period_days': days,
                    'total_trades': 0,
                    'profitable_trades': 0,
                    'total_profit': 0.0,
                    'win_rate': 0.0,
                    'profitable_days': 0
                }

            # Get all shadow trades
            perf_ids = [p.id for p in perfs]
            shadows = self.db.query(ShadowTrade).filter(
                ShadowTrade.performance_tracking_id.in_(perf_ids),
                ShadowTrade.status == 'closed'
            ).all()

            total_trades = len(shadows)
            profitable_trades = sum(1 for s in shadows if s.profit > 0)
            total_profit = sum(s.profit for s in shadows)
            win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0.0

            # Count profitable days
            profitable_days = sum(1 for p in perfs if p.shadow_profit and p.shadow_profit > 0)

            return {
                'period_days': days,
                'total_trades': total_trades,
                'profitable_trades': profitable_trades,
                'total_profit': float(total_profit),
                'win_rate': float(win_rate),
                'profitable_days': profitable_days
            }

        except Exception as e:
            logger.error(f"Error getting shadow trade summary for {symbol}: {e}")
            return {
                'period_days': days,
                'total_trades': 0,
                'profitable_trades': 0,
                'total_profit': 0.0,
                'win_rate': 0.0,
                'profitable_days': 0
            }


def process_signal_for_shadow_trading(signal_id: int):
    """Helper function to create shadow trade from signal ID"""
    engine = ShadowTradingEngine()
    db = ScopedSession()

    try:
        signal = db.query(TradingSignal).get(signal_id)
        if signal:
            engine.process_signal_for_disabled_symbol(signal)
    finally:
        db.close()


def update_shadow_trades_for_tick(symbol: str, price: float, timestamp: datetime = None):
    """Helper function to update shadow trades based on new tick data"""
    if timestamp is None:
        timestamp = datetime.utcnow()

    engine = ShadowTradingEngine()
    engine.update_shadow_trades(symbol, price, timestamp)
