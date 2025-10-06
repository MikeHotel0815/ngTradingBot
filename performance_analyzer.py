"""
Performance Analyzer for Auto-Optimization System
Analyzes backtest results and determines symbol status (active/watch/disabled)
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from models import (
    BacktestRun, BacktestTrade, SymbolPerformanceTracking,
    AutoOptimizationConfig, AutoOptimizationEvent, Account, ShadowTrade
)

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyzes backtest performance and determines symbol trading status"""

    def __init__(self, db: Session, account_id: int):
        self.db = db
        self.account_id = account_id
        self.config = self._load_config()

    def _load_config(self) -> AutoOptimizationConfig:
        """Load auto-optimization configuration for account"""
        config = self.db.query(AutoOptimizationConfig).filter_by(
            account_id=self.account_id
        ).first()

        if not config:
            # Create default config
            config = AutoOptimizationConfig(account_id=self.account_id)
            self.db.add(config)
            self.db.commit()
            logger.info(f"Created default auto-optimization config for account {self.account_id}")

        return config

    def analyze_symbol_performance(
        self,
        symbol: str,
        backtest_run: BacktestRun,
        evaluation_date: datetime
    ) -> SymbolPerformanceTracking:
        """
        Analyze performance for a single symbol and create/update tracking record

        Args:
            symbol: Symbol to analyze (e.g., 'BTCUSD')
            backtest_run: BacktestRun object containing results
            evaluation_date: Date of evaluation

        Returns:
            SymbolPerformanceTracking record
        """
        logger.info(f"Analyzing performance for {symbol} on {evaluation_date}")

        # Get symbol-specific trades from backtest
        trades = self.db.query(BacktestTrade).filter(
            BacktestTrade.backtest_run_id == backtest_run.id,
            BacktestTrade.symbol == symbol
        ).all()

        # Calculate metrics
        metrics = self._calculate_metrics(trades, backtest_run.initial_balance)

        # Get or create performance tracking record
        perf = self.db.query(SymbolPerformanceTracking).filter(
            SymbolPerformanceTracking.account_id == self.account_id,
            SymbolPerformanceTracking.symbol == symbol,
            SymbolPerformanceTracking.evaluation_date == evaluation_date.date()
        ).first()

        if not perf:
            perf = SymbolPerformanceTracking(
                account_id=self.account_id,
                symbol=symbol,
                evaluation_date=evaluation_date.date()
            )
            self.db.add(perf)

        # Update backtest results
        perf.backtest_run_id = backtest_run.id
        perf.backtest_start_date = backtest_run.start_date
        perf.backtest_end_date = backtest_run.end_date
        perf.backtest_total_trades = metrics['total_trades']
        perf.backtest_winning_trades = metrics['winning_trades']
        perf.backtest_losing_trades = metrics['losing_trades']
        perf.backtest_win_rate = metrics['win_rate']
        perf.backtest_profit = metrics['total_profit']
        perf.backtest_profit_percent = metrics['profit_percent']
        perf.backtest_max_drawdown = metrics['max_drawdown']
        perf.backtest_max_drawdown_percent = metrics['max_drawdown_percent']
        perf.backtest_profit_factor = metrics['profit_factor']
        perf.backtest_best_trade = metrics['best_trade']
        perf.backtest_worst_trade = metrics['worst_trade']
        perf.backtest_avg_trade_duration = metrics['avg_trade_duration']

        # Determine status and check criteria
        old_status = perf.status
        new_status = self._determine_status(perf, metrics)

        if new_status != old_status:
            perf.previous_status = old_status
            perf.status = new_status
            perf.status_changed_at = datetime.utcnow()
            logger.info(f"📊 {symbol} status changed: {old_status} → {new_status}")

            # Log status change event
            self._log_event(
                symbol=symbol,
                event_type='status_changed',
                old_status=old_status,
                new_status=new_status,
                metrics=metrics,
                backtest_run_id=backtest_run.id,
                symbol_performance_id=perf.id
            )

        # Update consecutive days tracking
        self._update_consecutive_days(perf, metrics)

        # Check enable/disable criteria
        perf.meets_enable_criteria = self._meets_enable_criteria(perf)
        perf.meets_disable_criteria = self._meets_disable_criteria(perf, metrics)

        perf.updated_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            f"✅ {symbol}: {new_status.upper()} | "
            f"Win Rate: {metrics['win_rate']:.1f}% | "
            f"Profit: ${metrics['total_profit']:.2f} ({metrics['profit_percent']:.2f}%) | "
            f"Trades: {metrics['total_trades']}"
        )

        return perf

    def _calculate_metrics(
        self,
        trades: List[BacktestTrade],
        initial_balance: Decimal
    ) -> Dict:
        """Calculate performance metrics from trades"""
        if not trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_profit': Decimal('0.00'),
                'profit_percent': Decimal('0.0000'),
                'max_drawdown': Decimal('0.00'),
                'max_drawdown_percent': Decimal('0.0000'),
                'profit_factor': Decimal('0.0000'),
                'best_trade': Decimal('0.00'),
                'worst_trade': Decimal('0.00'),
                'avg_trade_duration': 0
            }

        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.profit and t.profit > 0)
        losing_trades = sum(1 for t in trades if t.profit and t.profit <= 0)

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        total_profit = sum(t.profit for t in trades if t.profit) or Decimal('0.00')
        profit_percent = (total_profit / initial_balance) if initial_balance > 0 else Decimal('0.0000')

        gross_profit = sum(t.profit for t in trades if t.profit and t.profit > 0) or Decimal('0.01')
        gross_loss = abs(sum(t.profit for t in trades if t.profit and t.profit < 0)) or Decimal('0.01')
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else Decimal('0.0000')

        best_trade = max((t.profit for t in trades if t.profit), default=Decimal('0.00'))
        worst_trade = min((t.profit for t in trades if t.profit), default=Decimal('0.00'))

        # Calculate drawdown
        running_balance = float(initial_balance)
        peak_balance = running_balance
        max_drawdown = 0.0

        for trade in sorted(trades, key=lambda t: t.entry_time):
            if trade.profit:
                running_balance += float(trade.profit)
                if running_balance > peak_balance:
                    peak_balance = running_balance
                drawdown = peak_balance - running_balance
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        max_drawdown_percent = (Decimal(max_drawdown) / initial_balance) if initial_balance > 0 else Decimal('0.0000')

        # Average trade duration
        durations = [t.duration_minutes for t in trades if t.duration_minutes]
        avg_duration = sum(durations) // len(durations) if durations else 0

        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': round(win_rate, 2),
            'total_profit': total_profit,
            'profit_percent': profit_percent,
            'max_drawdown': Decimal(max_drawdown),
            'max_drawdown_percent': max_drawdown_percent,
            'profit_factor': profit_factor,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'avg_trade_duration': avg_duration
        }

    def _determine_status(
        self,
        perf: SymbolPerformanceTracking,
        metrics: Dict
    ) -> str:
        """
        Determine symbol status based on performance metrics

        Returns: 'active', 'watch', or 'disabled'
        """
        # If not enough trades, keep current status or set to watch
        if metrics['total_trades'] < self.config.disable_min_trades:
            return perf.status if perf.status else 'watch'

        # Check for auto-disable criteria
        if self._meets_disable_criteria(perf, metrics):
            reason = self._generate_disable_reason(metrics)
            perf.auto_disabled_reason = reason
            return 'disabled'

        # Check for watch status (borderline performance)
        if self._is_watch_status(metrics):
            return 'watch'

        # Default to active if performing well
        return 'active'

    def _meets_disable_criteria(
        self,
        perf: SymbolPerformanceTracking,
        metrics: Dict
    ) -> bool:
        """Check if symbol meets criteria for disabling"""
        if not self.config.auto_disable_enabled:
            return False

        # Need minimum trades to evaluate
        if metrics['total_trades'] < self.config.disable_min_trades:
            return False

        # Check win rate
        if metrics['win_rate'] < self.config.disable_min_win_rate:
            return True

        # Check profit/loss
        if metrics['profit_percent'] < self.config.disable_max_loss_percent:
            return True

        # Check drawdown
        if metrics['max_drawdown_percent'] > self.config.disable_max_drawdown_percent:
            return True

        # Check consecutive loss days
        if perf.consecutive_loss_days >= self.config.disable_consecutive_loss_days:
            return True

        return False

    def _meets_enable_criteria(self, perf: SymbolPerformanceTracking) -> bool:
        """Check if disabled symbol meets criteria for re-enabling (via shadow trading)"""
        if not self.config.auto_enable_enabled:
            return False

        if perf.status != 'disabled':
            return False

        # Need shadow trades to evaluate
        if not perf.shadow_trades or perf.shadow_trades < self.config.enable_min_shadow_trades:
            return False

        # Calculate shadow win rate from shadow trades
        shadow_win_rate = self._calculate_shadow_win_rate(perf)
        if shadow_win_rate < self.config.enable_min_win_rate:
            return False

        # Check consecutive profitable shadow days
        if perf.shadow_profitable_days < self.config.enable_consecutive_profit_days:
            return False

        # Check shadow profit is positive
        if not perf.shadow_profit or perf.shadow_profit <= 0:
            return False

        logger.info(f"✅ {perf.symbol} meets re-enable criteria: "
                   f"{perf.shadow_trades} shadow trades, "
                   f"{shadow_win_rate:.1f}% win rate, "
                   f"{perf.shadow_profitable_days} profitable days, "
                   f"${perf.shadow_profit:.2f} shadow profit")
        return True

    def _calculate_shadow_win_rate(self, perf: SymbolPerformanceTracking) -> float:
        """Calculate win rate from shadow trades"""
        shadows = self.db.query(ShadowTrade).filter(
            ShadowTrade.performance_tracking_id == perf.id,
            ShadowTrade.status == 'closed'
        ).all()

        if not shadows:
            return 0.0

        profitable = sum(1 for s in shadows if s.profit > 0)
        return (profitable / len(shadows)) * 100 if len(shadows) > 0 else 0.0

    def _is_watch_status(self, metrics: Dict) -> bool:
        """Check if symbol should be in watch status (borderline performance)"""
        win_rate = metrics['win_rate']
        profit_pct = float(metrics['profit_percent'])

        # Win rate in watch range
        if self.config.watch_min_win_rate <= win_rate <= self.config.watch_max_win_rate:
            return True

        # Profit in watch range
        if self.config.watch_min_profit_percent <= profit_pct <= self.config.watch_max_profit_percent:
            return True

        return False

    def _update_consecutive_days(
        self,
        perf: SymbolPerformanceTracking,
        metrics: Dict
    ):
        """Update consecutive profit/loss days tracking"""
        is_profitable = metrics['total_profit'] > 0

        if is_profitable:
            perf.consecutive_profit_days = (perf.consecutive_profit_days or 0) + 1
            perf.consecutive_loss_days = 0
        else:
            perf.consecutive_loss_days = (perf.consecutive_loss_days or 0) + 1
            perf.consecutive_profit_days = 0

    def _generate_disable_reason(self, metrics: Dict) -> str:
        """Generate human-readable reason for disabling symbol"""
        reasons = []

        if metrics['win_rate'] < self.config.disable_min_win_rate:
            reasons.append(f"Win rate {metrics['win_rate']:.1f}% < {self.config.disable_min_win_rate}%")

        if metrics['profit_percent'] < self.config.disable_max_loss_percent:
            reasons.append(f"Loss {metrics['profit_percent']*100:.2f}% > {self.config.disable_max_loss_percent*100:.1f}%")

        if metrics['max_drawdown_percent'] > self.config.disable_max_drawdown_percent:
            reasons.append(f"Drawdown {metrics['max_drawdown_percent']*100:.2f}% > {self.config.disable_max_drawdown_percent*100:.1f}%")

        return "; ".join(reasons) if reasons else "Poor performance"

    def _log_event(
        self,
        symbol: str,
        event_type: str,
        old_status: str = None,
        new_status: str = None,
        metrics: Dict = None,
        backtest_run_id: int = None,
        symbol_performance_id: int = None,
        trigger_reason: str = None
    ):
        """Log auto-optimization event"""
        event = AutoOptimizationEvent(
            account_id=self.account_id,
            symbol=symbol,
            event_type=event_type,
            old_status=old_status,
            new_status=new_status,
            trigger_reason=trigger_reason,
            metrics=metrics,  # JSONB field
            backtest_run_id=backtest_run_id,
            symbol_performance_id=symbol_performance_id,
            event_timestamp=datetime.utcnow()
        )
        self.db.add(event)
        self.db.commit()
        logger.info(f"📝 Event logged: {event_type} for {symbol}")

    def get_active_symbols(self) -> List[str]:
        """Get list of symbols currently active for trading"""
        results = self.db.query(SymbolPerformanceTracking.symbol).filter(
            SymbolPerformanceTracking.account_id == self.account_id,
            SymbolPerformanceTracking.status == 'active'
        ).distinct().all()

        return [r[0] for r in results]

    def get_disabled_symbols(self) -> List[str]:
        """Get list of symbols currently disabled (for shadow trading)"""
        results = self.db.query(SymbolPerformanceTracking.symbol).filter(
            SymbolPerformanceTracking.account_id == self.account_id,
            SymbolPerformanceTracking.status == 'disabled'
        ).distinct().all()

        return [r[0] for r in results]

    def get_symbol_status_summary(self) -> Dict[str, int]:
        """Get count of symbols by status"""
        results = self.db.query(
            SymbolPerformanceTracking.status,
            func.count(SymbolPerformanceTracking.id).label('count')
        ).filter(
            SymbolPerformanceTracking.account_id == self.account_id
        ).group_by(
            SymbolPerformanceTracking.status
        ).all()

        return {status: count for status, count in results}

    def update_shadow_trading_metrics(self, perf: SymbolPerformanceTracking, evaluation_date: datetime):
        """
        Update shadow trading metrics from closed shadow trades.
        Called daily to aggregate shadow trading performance.
        """
        if perf.status != 'disabled':
            return

        # Get all closed shadow trades for this day
        day_start = datetime.combine(evaluation_date.date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)

        shadows = self.db.query(ShadowTrade).filter(
            ShadowTrade.performance_tracking_id == perf.id,
            ShadowTrade.status == 'closed',
            ShadowTrade.exit_time >= day_start,
            ShadowTrade.exit_time < day_end
        ).all()

        if not shadows:
            # No shadow trades today
            perf.shadow_trades = 0
            perf.shadow_profit = Decimal('0.0')
            perf.shadow_win_rate = Decimal('0.0')
            return

        total_trades = len(shadows)
        profitable_trades = sum(1 for s in shadows if s.profit > 0)
        total_profit = sum(s.profit for s in shadows)
        win_rate = (profitable_trades / total_trades * 100) if total_trades > 0 else 0.0

        perf.shadow_trades = total_trades
        perf.shadow_profit = Decimal(str(total_profit))
        perf.shadow_win_rate = Decimal(str(win_rate))

        # Update consecutive profitable days
        if total_profit > 0:
            perf.shadow_profitable_days = (perf.shadow_profitable_days or 0) + 1
        else:
            perf.shadow_profitable_days = 0

        logger.info(f"🌑 Shadow trading metrics updated for {perf.symbol}: "
                   f"{total_trades} trades, {win_rate:.1f}% win rate, ${total_profit:.2f} profit")
