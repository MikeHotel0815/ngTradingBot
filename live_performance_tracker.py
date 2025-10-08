"""
Live Performance Tracker
Updates symbol performance metrics in real-time after each trade closes
Provides feedback and auto-adjusts parameters based on performance
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from models import Trade, SymbolPerformanceTracking, AutoOptimizationEvent
from database import ScopedSession

logger = logging.getLogger(__name__)


class LivePerformanceTracker:
    """Tracks live trading performance per symbol and provides feedback"""

    def __init__(self):
        self.performance_cache = {}  # Cache for quick lookups
        self.last_update = {}

    def update_after_trade_close(self, trade: Trade, db: Session):
        """
        Update performance metrics after a trade closes

        Args:
            trade: Closed trade object
            db: Database session
        """
        try:
            symbol = trade.symbol
            account_id = trade.account_id
            today = datetime.utcnow().date()

            logger.info(f"📊 Updating live performance for {symbol} after trade #{trade.ticket}")

            # Get or create today's performance tracking
            perf = db.query(SymbolPerformanceTracking).filter(
                SymbolPerformanceTracking.account_id == account_id,
                SymbolPerformanceTracking.symbol == symbol,
                SymbolPerformanceTracking.evaluation_date == today
            ).first()

            if not perf:
                perf = SymbolPerformanceTracking(
                    account_id=account_id,
                    symbol=symbol,
                    evaluation_date=today,
                    status='active'
                )
                db.add(perf)
                logger.info(f"Created new performance tracking for {symbol}")

            # Calculate live metrics from last 24h
            metrics = self._calculate_live_metrics(symbol, account_id, db)

            # Update live performance fields
            perf.live_trades = metrics['total_trades']
            perf.live_winning_trades = metrics['winning_trades']
            perf.live_losing_trades = metrics['losing_trades']
            perf.live_profit = metrics['total_profit']
            perf.live_win_rate = metrics['win_rate']
            perf.updated_at = datetime.utcnow()

            # Check if symbol should be disabled
            should_disable = self._check_disable_criteria(metrics, symbol)
            if should_disable and perf.status == 'active':
                perf.previous_status = perf.status
                perf.status = 'disabled'
                perf.status_changed_at = datetime.utcnow()
                perf.auto_disabled_reason = should_disable
                perf.meets_disable_criteria = True

                # Log optimization event
                self._log_optimization_event(
                    db, perf.id, 'SYMBOL_DISABLED',
                    f"{symbol} auto-disabled: {should_disable}",
                    {'reason': should_disable, 'metrics': metrics}
                )

                logger.warning(f"⚠️ {symbol} AUTO-DISABLED: {should_disable}")

            # Check if symbol should be re-enabled
            should_enable = self._check_enable_criteria(metrics, symbol)
            if should_enable and perf.status == 'disabled':
                perf.previous_status = perf.status
                perf.status = 'active'
                perf.status_changed_at = datetime.utcnow()
                perf.meets_enable_criteria = True

                self._log_optimization_event(
                    db, perf.id, 'SYMBOL_ENABLED',
                    f"{symbol} auto-enabled: {should_enable}",
                    {'reason': should_enable, 'metrics': metrics}
                )

                logger.info(f"✅ {symbol} AUTO-ENABLED: {should_enable}")

            db.commit()

            # Provide user feedback
            self._provide_feedback(symbol, metrics, perf.status, db)

        except Exception as e:
            logger.error(f"Error updating live performance for {trade.symbol}: {e}")
            db.rollback()

    def _calculate_live_metrics(self, symbol: str, account_id: int, db: Session) -> Dict:
        """Calculate performance metrics from last 24 hours of live trades"""
        cutoff = datetime.utcnow() - timedelta(hours=24)

        trades = db.query(Trade).filter(
            Trade.account_id == account_id,
            Trade.symbol == symbol,
            Trade.status == 'closed',
            Trade.close_time >= cutoff
        ).all()

        total_trades = len(trades)
        if total_trades == 0:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_profit': Decimal('0'),
                'win_rate': Decimal('0'),
                'avg_profit': Decimal('0'),
                'avg_loss': Decimal('0'),
                'profit_factor': Decimal('0'),
                'avg_win_duration': 0,
                'avg_loss_duration': 0
            }

        winning_trades = [t for t in trades if t.profit and t.profit > 0]
        losing_trades = [t for t in trades if t.profit and t.profit <= 0]

        total_profit = sum(t.profit for t in trades if t.profit)
        total_wins = sum(t.profit for t in winning_trades)
        total_losses = abs(sum(t.profit for t in losing_trades)) if losing_trades else Decimal('1')

        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else Decimal('0')
        profit_factor = (total_wins / total_losses) if total_losses > 0 else Decimal('0')

        # Calculate average durations
        avg_win_duration = 0
        if winning_trades:
            win_durations = [
                (t.close_time - t.open_time).total_seconds() / 60
                for t in winning_trades if t.close_time and t.open_time
            ]
            avg_win_duration = sum(win_durations) / len(win_durations) if win_durations else 0

        avg_loss_duration = 0
        if losing_trades:
            loss_durations = [
                (t.close_time - t.open_time).total_seconds() / 60
                for t in losing_trades if t.close_time and t.open_time
            ]
            avg_loss_duration = sum(loss_durations) / len(loss_durations) if loss_durations else 0

        return {
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'total_profit': round(total_profit, 2),
            'win_rate': round(win_rate, 2),
            'avg_profit': round(total_wins / len(winning_trades), 2) if winning_trades else Decimal('0'),
            'avg_loss': round(total_losses / len(losing_trades), 2) if losing_trades else Decimal('0'),
            'profit_factor': round(profit_factor, 2),
            'avg_win_duration': round(avg_win_duration, 1),
            'avg_loss_duration': round(avg_loss_duration, 1)
        }

    def _check_disable_criteria(self, metrics: Dict, symbol: str) -> Optional[str]:
        """
        Check if symbol should be auto-disabled

        Returns reason string if should disable, None otherwise
        """
        total_trades = metrics['total_trades']

        # Need at least 10 trades to make decision
        if total_trades < 10:
            return None

        win_rate = float(metrics['win_rate'])
        total_profit = float(metrics['total_profit'])
        avg_loss = float(metrics['avg_loss'])

        # Disable criteria
        if win_rate < 30 and total_trades >= 10:
            return f"Low win-rate: {win_rate:.1f}% (< 30%) over {total_trades} trades"

        if total_profit < -10 and total_trades >= 10:
            return f"High losses: €{total_profit:.2f} over {total_trades} trades"

        if avg_loss > 2.0 and metrics['losing_trades'] >= 5:
            return f"High average loss: €{avg_loss:.2f} per losing trade"

        # Check loss duration (if losses run too long)
        if metrics['avg_loss_duration'] > 120 and metrics['losing_trades'] >= 5:
            return f"Losses run too long: {metrics['avg_loss_duration']:.0f} minutes average"

        return None

    def _check_enable_criteria(self, metrics: Dict, symbol: str) -> Optional[str]:
        """
        Check if previously disabled symbol should be re-enabled

        Returns reason string if should enable, None otherwise
        """
        total_trades = metrics['total_trades']

        # Need at least 10 trades to make decision
        if total_trades < 10:
            return None

        win_rate = float(metrics['win_rate'])
        total_profit = float(metrics['total_profit'])
        profit_factor = float(metrics['profit_factor'])

        # Re-enable criteria
        if win_rate >= 60 and total_profit > 0 and total_trades >= 10:
            return f"Good performance: {win_rate:.1f}% win-rate, €{total_profit:.2f} profit"

        if profit_factor >= 2.0 and total_trades >= 10:
            return f"Strong profit factor: {profit_factor:.2f}"

        return None

    def _log_optimization_event(
        self,
        db: Session,
        performance_id: int,
        event_type: str,
        description: str,
        parameters: Dict
    ):
        """Log an auto-optimization event"""
        import json

        event = AutoOptimizationEvent(
            symbol_performance_id=performance_id,
            event_type=event_type,
            description=description,
            parameters_before=json.dumps(parameters),
            parameters_after=json.dumps(parameters),  # Same for now
            created_at=datetime.utcnow()
        )
        db.add(event)

    def _provide_feedback(self, symbol: str, metrics: Dict, status: str, db: Session):
        """
        Provide user feedback about symbol performance

        This logs important metrics and status changes
        """
        total_trades = metrics['total_trades']
        if total_trades == 0:
            return

        win_rate = float(metrics['win_rate'])
        total_profit = float(metrics['total_profit'])

        # Feedback based on performance
        if status == 'disabled':
            logger.warning(
                f"⛔ {symbol} is DISABLED | "
                f"{total_trades} trades | Win-Rate: {win_rate:.1f}% | "
                f"Profit: €{total_profit:.2f}"
            )
        elif win_rate >= 70:
            logger.info(
                f"⭐ {symbol} performing EXCELLENT | "
                f"{total_trades} trades | Win-Rate: {win_rate:.1f}% | "
                f"Profit: €{total_profit:.2f}"
            )
        elif win_rate >= 50:
            logger.info(
                f"✅ {symbol} performing GOOD | "
                f"{total_trades} trades | Win-Rate: {win_rate:.1f}% | "
                f"Profit: €{total_profit:.2f}"
            )
        elif win_rate < 40:
            logger.warning(
                f"⚠️ {symbol} performing POORLY | "
                f"{total_trades} trades | Win-Rate: {win_rate:.1f}% | "
                f"Profit: €{total_profit:.2f} | WATCH CLOSELY"
            )

    def get_all_symbol_performance(self, account_id: int, db: Session) -> List[Dict]:
        """Get performance summary for all symbols"""
        today = datetime.utcnow().date()

        # Get all symbols from performance tracking
        perfs = db.query(SymbolPerformanceTracking).filter(
            SymbolPerformanceTracking.account_id == account_id,
            SymbolPerformanceTracking.evaluation_date == today
        ).all()

        results = []
        for perf in perfs:
            results.append({
                'symbol': perf.symbol,
                'status': perf.status,
                'live_trades': perf.live_trades or 0,
                'live_win_rate': float(perf.live_win_rate or 0),
                'live_profit': float(perf.live_profit or 0),
                'backtest_win_rate': float(perf.backtest_win_rate or 0),
                'backtest_profit': float(perf.backtest_profit or 0),
                'auto_disabled_reason': perf.auto_disabled_reason,
                'updated_at': perf.updated_at
            })

        return sorted(results, key=lambda x: x['live_profit'], reverse=True)


# Global instance
_live_tracker = None


def get_live_tracker():
    """Get global live performance tracker instance"""
    global _live_tracker
    if _live_tracker is None:
        _live_tracker = LivePerformanceTracker()
    return _live_tracker
