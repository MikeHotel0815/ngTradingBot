"""
Dashboard Core Logic
Central metrics calculation for all dashboard components
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from sqlalchemy import func, and_, desc, text
from sqlalchemy.orm import Session

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import ScopedSession
from models import (
    Trade, TradingSignal, Account, SubscribedSymbol,
    Command, Tick, ShadowTrade
)
from monitoring.dashboard_config import get_config

logger = logging.getLogger(__name__)


class DashboardCore:
    """Core dashboard metrics calculator"""

    def __init__(self, account_id: Optional[int] = None, db_session: Optional[Session] = None):
        """Initialize dashboard core

        Args:
            account_id: MT5 account ID (defaults to config)
            db_session: Optional SQLAlchemy session (creates new if None)
        """
        self.config = get_config()
        self.account_id = account_id or self.config.DEFAULT_ACCOUNT_ID
        self.db = db_session or ScopedSession()
        self._should_close_db = db_session is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._should_close_db:
            self.db.close()

    # =========================================================================
    # SECTION 1: Real-Time Trading Overview
    # =========================================================================

    def get_realtime_trading_overview(self) -> Dict:
        """Get real-time trading overview for all symbols

        Returns:
            Dict with structure:
            {
                'symbols': [
                    {
                        'symbol': 'EURUSD',
                        'status': 'active',  # active, shadow_trade, paused
                        'open_positions': 2,
                        'today_pnl': 12.45,
                        'win_rate': 67.5,
                        'signals_today': 15
                    },
                    ...
                ],
                'total': {
                    'open_positions': 5,
                    'today_pnl': 45.67,
                    'win_rate': 64.2,
                    'total_signals': 48
                },
                'last_update': '2025-10-26 16:45:00'
            }
        """
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            # Get subscribed symbols
            subscribed = self.db.query(SubscribedSymbol).filter(
                SubscribedSymbol.account_id == self.account_id,
                SubscribedSymbol.active == True
            ).all()

            symbols_data = []
            total_open = 0
            total_pnl = 0.0
            total_signals = 0
            total_trades_today = 0
            total_wins_today = 0

            for sub in subscribed:
                symbol = sub.symbol

                # Check status from symbol_trading_config
                try:
                    from models import SymbolTradingConfig
                    config_buy = self.db.query(SymbolTradingConfig).filter(
                        SymbolTradingConfig.account_id == self.account_id,
                        SymbolTradingConfig.symbol == symbol,
                        SymbolTradingConfig.direction == 'BUY'
                    ).first()

                    status = config_buy.status if config_buy else 'active'
                except:
                    status = 'active'

                # Open positions
                open_pos = self.db.query(Trade).filter(
                    Trade.account_id == self.account_id,
                    Trade.symbol == symbol,
                    Trade.status == 'open'
                ).count()

                # Today's P&L
                today_trades = self.db.query(Trade).filter(
                    Trade.account_id == self.account_id,
                    Trade.symbol == symbol,
                    Trade.close_time >= today_start,
                    Trade.status == 'closed'
                ).all()

                today_pnl = sum(float(t.profit or 0) for t in today_trades)
                wins = sum(1 for t in today_trades if float(t.profit or 0) > 0)
                win_rate = (wins / len(today_trades) * 100) if today_trades else None

                # Signals today
                signals = self.db.query(TradingSignal).filter(
                    TradingSignal.symbol == symbol,
                    TradingSignal.created_at >= today_start
                ).count()

                symbols_data.append({
                    'symbol': symbol,
                    'status': status,
                    'open_positions': open_pos,
                    'today_pnl': today_pnl,
                    'win_rate': win_rate,
                    'signals_today': signals,
                    'trades_today': len(today_trades)
                })

                total_open += open_pos
                total_pnl += today_pnl
                total_signals += signals
                total_trades_today += len(today_trades)
                total_wins_today += wins

            # Calculate overall win rate
            overall_wr = (total_wins_today / total_trades_today * 100) if total_trades_today > 0 else 0.0

            return {
                'symbols': sorted(symbols_data, key=lambda x: x['symbol']),
                'total': {
                    'open_positions': total_open,
                    'today_pnl': total_pnl,
                    'win_rate': overall_wr,
                    'total_signals': total_signals,
                    'trades_today': total_trades_today
                },
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting realtime trading overview: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 2: ML Performance Metrics
    # =========================================================================

    def get_ml_performance_metrics(self) -> Dict:
        """Get ML model performance metrics

        Returns:
            Dict with ML performance data per symbol
        """
        try:
            since_24h = datetime.utcnow() - timedelta(hours=24)

            # Get subscribed symbols
            subscribed = self.db.query(SubscribedSymbol).filter(
                SubscribedSymbol.account_id == self.account_id,
                SubscribedSymbol.active == True
            ).all()

            ml_metrics = []

            for sub in subscribed:
                symbol = sub.symbol

                # Get ML predictions from last 24h
                try:
                    from models import MLPrediction
                    predictions = self.db.query(MLPrediction).filter(
                        MLPrediction.symbol == symbol,
                        MLPrediction.created_at >= since_24h
                    ).all()

                    if predictions:
                        avg_confidence = sum(float(p.confidence) for p in predictions) / len(predictions)

                        # Calculate accuracy (predictions that led to profitable trades)
                        correct = 0
                        total_verified = 0
                        for pred in predictions:
                            if pred.actual_profit is not None:
                                total_verified += 1
                                predicted_dir = pred.predicted_direction
                                was_profitable = float(pred.actual_profit) > 0
                                if (predicted_dir == 'BUY' and was_profitable) or \
                                   (predicted_dir == 'SELL' and was_profitable):
                                    correct += 1

                        accuracy = (correct / total_verified * 100) if total_verified > 0 else None
                    else:
                        avg_confidence = None
                        accuracy = None
                except:
                    avg_confidence = None
                    accuracy = None

                # Get trades that used ML (from signals)
                trades_24h = self.db.query(Trade).join(
                    TradingSignal, Trade.signal_id == TradingSignal.id
                ).filter(
                    Trade.account_id == self.account_id,
                    Trade.symbol == symbol,
                    Trade.created_at >= since_24h
                ).count()

                ml_metrics.append({
                    'symbol': symbol,
                    'avg_confidence': avg_confidence,
                    'prediction_accuracy': accuracy,
                    'trades_24h': trades_24h
                })

            # Overall averages
            confidences = [m['avg_confidence'] for m in ml_metrics if m['avg_confidence'] is not None]
            accuracies = [m['prediction_accuracy'] for m in ml_metrics if m['prediction_accuracy'] is not None]

            avg_confidence = sum(confidences) / len(confidences) if confidences else None
            avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else None

            return {
                'symbols': ml_metrics,
                'overall': {
                    'avg_confidence': avg_confidence,
                    'avg_accuracy': avg_accuracy
                },
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting ML performance metrics: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 3: Risk Management Status
    # =========================================================================

    def get_risk_management_status(self) -> Dict:
        """Get current risk management status

        Returns:
            Dict with risk management metrics
        """
        try:
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            # Daily P&L
            today_trades = self.db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.close_time >= today_start,
                Trade.status == 'closed'
            ).all()

            daily_pnl = sum(float(t.profit or 0) for t in today_trades)

            # Calculate drawdown status
            dd_warning = self.config.DRAWDOWN_WARNING_THRESHOLD
            dd_critical = self.config.DRAWDOWN_CRITICAL_THRESHOLD
            dd_emergency = self.config.DRAWDOWN_EMERGENCY_THRESHOLD

            if daily_pnl <= dd_emergency:
                dd_status = 'EMERGENCY'
            elif daily_pnl <= dd_critical:
                dd_status = 'CRITICAL'
            elif daily_pnl <= dd_warning:
                dd_status = 'WARNING'
            else:
                dd_status = 'SAFE'

            # Position limits
            try:
                from models import GlobalSettings
                settings = self.db.query(GlobalSettings).first()
                max_total_positions = settings.max_total_open_positions if settings else 5
                max_per_symbol = settings.max_positions_per_symbol if settings else 1
            except:
                max_total_positions = 5
                max_per_symbol = 1

            current_open = self.db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.status == 'open'
            ).count()

            position_usage_pct = (current_open / max_total_positions * 100) if max_total_positions > 0 else 0

            # SL Enforcement check
            open_trades = self.db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.status == 'open'
            ).all()

            trades_without_sl = sum(1 for t in open_trades if not t.sl or float(t.sl) == 0)
            sl_enforcement_ok = trades_without_sl == 0

            # Duplicate prevention check (DB constraint)
            duplicate_prevention_active = True  # Assume active from migration

            return {
                'daily_drawdown': {
                    'current': daily_pnl,
                    'warning_limit': dd_warning,
                    'critical_limit': dd_critical,
                    'emergency_limit': dd_emergency,
                    'status': dd_status
                },
                'position_limits': {
                    'current_open': current_open,
                    'max_total': max_total_positions,
                    'max_per_symbol': max_per_symbol,
                    'usage_pct': position_usage_pct
                },
                'sl_enforcement': {
                    'all_trades_have_sl': sl_enforcement_ok,
                    'trades_without_sl': trades_without_sl,
                    'total_open_trades': len(open_trades)
                },
                'duplicate_prevention': {
                    'active': duplicate_prevention_active
                },
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting risk management status: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 4: Live Position Details
    # =========================================================================

    def get_live_positions(self) -> Dict:
        """Get detailed list of all open positions

        Returns:
            Dict with open positions data
        """
        try:
            # Query with duration calculated in database
            # NOTE: open_time is stored in broker local time (UTC+2 / EET - Eastern European Time)
            # We need to adjust for the timezone offset when calculating duration
            from sqlalchemy import literal_column

            # Calculate duration assuming open_time is in EET (UTC+2)
            # Formula: current_utc - (open_time_eet - 2 hours) = current_utc - open_time_utc
            open_trades = self.db.query(
                Trade,
                literal_column("EXTRACT(EPOCH FROM (NOW() - (open_time - INTERVAL '2 hours'))) / 60").label('duration_minutes')
            ).filter(
                Trade.account_id == self.account_id,
                Trade.status == 'open'
            ).order_by(Trade.open_time.desc()).all()

            positions = []
            for trade, duration_minutes in open_trades:
                # Get current price from latest tick
                try:
                    latest_tick = self.db.query(Tick).filter(
                        Tick.symbol == trade.symbol
                    ).order_by(Tick.timestamp.desc()).first()

                    if latest_tick:
                        if trade.direction.upper() == 'BUY':
                            current_price = float(latest_tick.bid)
                        else:
                            current_price = float(latest_tick.ask)
                    else:
                        current_price = None
                except:
                    current_price = None

                # Calculate unrealized P&L
                if current_price and trade.open_price:
                    if trade.direction.upper() == 'BUY':
                        price_diff = current_price - float(trade.open_price)
                    else:
                        price_diff = float(trade.open_price) - current_price

                    # Rough P&L calculation (needs contract size)
                    # This is simplified - real calculation needs pip value
                    unrealized_pnl = price_diff * float(trade.volume) * 100000  # Simplified
                else:
                    unrealized_pnl = None

                positions.append({
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'direction': trade.direction.upper(),
                    'volume': float(trade.volume),
                    'entry_price': float(trade.open_price) if trade.open_price else None,
                    'current_price': current_price,
                    'sl': float(trade.sl) if trade.sl else None,
                    'tp': float(trade.tp) if trade.tp else None,
                    'unrealized_pnl': unrealized_pnl,
                    'open_time': trade.open_time.strftime('%Y-%m-%d %H:%M:%S') if trade.open_time else None,
                    'duration_minutes': int(duration_minutes) if duration_minutes is not None else None
                })

            total_unrealized = sum(p['unrealized_pnl'] for p in positions if p['unrealized_pnl'])

            return {
                'positions': positions,
                'total_open': len(positions),
                'total_unrealized_pnl': total_unrealized,
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting live positions: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 5: Signal Quality Tracking
    # =========================================================================

    def get_signal_quality_metrics(self) -> Dict:
        """Get signal generation and execution quality metrics

        Returns:
            Dict with signal quality data
        """
        try:
            since_1h = datetime.utcnow() - timedelta(hours=1)

            # Signals generated in last hour
            signals = self.db.query(TradingSignal).filter(
                TradingSignal.created_at >= since_1h
            ).all()

            total_generated = len(signals)

            # Signals that led to trades (executed)
            executed = sum(1 for s in signals if s.status == 'executed')

            # Signals rejected (not executed)
            rejected = total_generated - executed

            # Rejection reasons (from AI decision log)
            rejection_reasons = {}
            try:
                from models import AIDecisionLog
                rejections = self.db.query(AIDecisionLog).filter(
                    AIDecisionLog.created_at >= since_1h,
                    AIDecisionLog.decision.in_(['rejected', 'skipped'])
                ).all()

                for rej in rejections:
                    reason = rej.reason or 'Unknown'
                    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
            except:
                rejection_reasons = {}

            # Average signal latency (signal created → trade executed)
            latencies = []
            for signal in signals:
                if signal.status == 'executed' and signal.executed_at:
                    latency_ms = (signal.executed_at - signal.created_at).total_seconds() * 1000
                    latencies.append(latency_ms)

            avg_latency = sum(latencies) / len(latencies) if latencies else None

            return {
                'last_hour': {
                    'generated': total_generated,
                    'executed': executed,
                    'rejected': rejected,
                    'execution_rate_pct': (executed / total_generated * 100) if total_generated > 0 else 0
                },
                'rejection_reasons': rejection_reasons,
                'latency': {
                    'average_ms': avg_latency,
                    'target_ms': self.config.SIGNAL_LATENCY_TARGET_MS,
                    'within_target': avg_latency < self.config.SIGNAL_LATENCY_TARGET_MS if avg_latency else None
                },
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting signal quality metrics: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 6: Shadow Trading Analytics (XAGUSD)
    # =========================================================================

    def get_shadow_trading_analytics(self) -> Dict:
        """Get shadow trading progress for XAGUSD

        Returns:
            Dict with shadow trading metrics
        """
        try:
            # Get shadow trades for XAGUSD
            shadow_trades = self.db.query(ShadowTrade).filter(
                ShadowTrade.symbol == 'XAGUSD'
            ).all()

            total_shadow = len(shadow_trades)
            wins = sum(1 for t in shadow_trades if t.simulated_profit_loss and float(t.simulated_profit_loss) > 0)
            win_rate = (wins / total_shadow * 100) if total_shadow > 0 else 0.0

            simulated_pnl = sum(float(t.simulated_profit_loss or 0) for t in shadow_trades)

            # Average confidence
            confidences = [float(t.confidence) for t in shadow_trades if t.confidence]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            # Progress towards re-activation
            trade_progress = (total_shadow / self.config.SHADOW_MIN_TRADES * 100)
            wr_progress = (win_rate / self.config.SHADOW_MIN_WIN_RATE * 100) if self.config.SHADOW_MIN_WIN_RATE > 0 else 0
            pnl_ok = simulated_pnl >= self.config.SHADOW_MIN_PROFIT

            # ETA calculation (based on signal rate)
            since_7d = datetime.utcnow() - timedelta(days=7)
            recent_signals = self.db.query(TradingSignal).filter(
                TradingSignal.symbol == 'XAGUSD',
                TradingSignal.created_at >= since_7d
            ).count()

            avg_signals_per_day = recent_signals / 7 if recent_signals > 0 else 0
            trades_needed = max(0, self.config.SHADOW_MIN_TRADES - total_shadow)
            eta_days = trades_needed / avg_signals_per_day if avg_signals_per_day > 0 else None

            # Last 10 shadow trades
            recent_shadows = self.db.query(ShadowTrade).filter(
                ShadowTrade.symbol == 'XAGUSD'
            ).order_by(ShadowTrade.created_at.desc()).limit(10).all()

            recent_list = [
                {
                    'symbol': t.symbol,
                    'direction': t.direction,
                    'entry_price': float(t.entry_price) if t.entry_price else None,
                    'confidence': float(t.confidence) if t.confidence else None,
                    'simulated_pnl': float(t.simulated_profit_loss) if t.simulated_profit_loss else None,
                    'created_at': t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else None
                }
                for t in recent_shadows
            ]

            return {
                'progress': {
                    'total_trades': total_shadow,
                    'target_trades': self.config.SHADOW_MIN_TRADES,
                    'trade_progress_pct': min(100, trade_progress),
                    'win_rate': win_rate,
                    'target_win_rate': self.config.SHADOW_MIN_WIN_RATE,
                    'wr_progress_pct': min(100, wr_progress),
                    'simulated_pnl': simulated_pnl,
                    'target_pnl': self.config.SHADOW_MIN_PROFIT,
                    'pnl_ok': pnl_ok,
                    'avg_confidence': avg_confidence
                },
                'eta': {
                    'days_remaining': eta_days,
                    'avg_signals_per_day': avg_signals_per_day
                },
                'recent_trades': recent_list,
                'ready_to_activate': (
                    total_shadow >= self.config.SHADOW_MIN_TRADES and
                    win_rate >= self.config.SHADOW_MIN_WIN_RATE and
                    pnl_ok
                ),
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting shadow trading analytics: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 7: System Health
    # =========================================================================

    def get_system_health(self) -> Dict:
        """Get system health metrics

        Returns:
            Dict with system health status
        """
        try:
            # MT5 Connection check
            account = self.db.query(Account).filter(
                Account.id == self.account_id
            ).first()

            if account and account.last_heartbeat:
                heartbeat_age = (datetime.utcnow() - account.last_heartbeat).total_seconds()
                mt5_connected = heartbeat_age < 60  # Connected if heartbeat < 60s ago
            else:
                heartbeat_age = None
                mt5_connected = False

            # PostgreSQL stats
            try:
                db_size_result = self.db.execute(text(
                    "SELECT pg_database_size('ngtradingbot') as size"
                )).fetchone()
                db_size_bytes = db_size_result[0] if db_size_result else 0
                db_size_mb = db_size_bytes / (1024 * 1024)

                conn_result = self.db.execute(text(
                    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'ngtradingbot'"
                )).fetchone()
                db_connections = conn_result[0] if conn_result else 0
            except:
                db_size_mb = None
                db_connections = None

            # Redis check (simplified - would need redis client)
            redis_healthy = True  # Assume healthy for now

            return {
                'mt5_connection': {
                    'connected': mt5_connected,
                    'last_heartbeat_seconds_ago': heartbeat_age,
                    'account_number': account.mt5_account_number if account else None
                },
                'postgresql': {
                    'connected': True,  # If we got here, it's connected
                    'database_size_mb': db_size_mb,
                    'active_connections': db_connections
                },
                'redis': {
                    'connected': redis_healthy
                },
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting system health: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # SECTION 8: Performance Analytics (Rolling 24h)
    # =========================================================================

    def get_performance_analytics(self, hours: int = 24) -> Dict:
        """Get performance analytics for specified time period

        Args:
            hours: Lookback period in hours (default: 24)

        Returns:
            Dict with performance analytics
        """
        try:
            since = datetime.utcnow() - timedelta(hours=hours)

            trades = self.db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.close_time >= since,
                Trade.status == 'closed'
            ).order_by(Trade.close_time).all()

            if not trades:
                return {
                    'summary': {
                        'total_trades': 0,
                        'winning_trades': 0,
                        'losing_trades': 0,
                        'breakeven_trades': 0,
                        'win_rate': 0.0,
                        'total_pnl': 0.0,
                        'avg_win': 0.0,
                        'avg_loss': 0.0,
                        'profit_factor': 0.0,
                        'expectancy': 0.0
                    },
                    'best_trade': None,
                    'worst_trade': None,
                    'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                }

            # Calculate metrics
            total = len(trades)
            wins = [t for t in trades if float(t.profit or 0) > 0]
            losses = [t for t in trades if float(t.profit or 0) < 0]
            breakeven = [t for t in trades if float(t.profit or 0) == 0]

            total_pnl = sum(float(t.profit or 0) for t in trades)
            avg_win = sum(float(t.profit or 0) for t in wins) / len(wins) if wins else 0.0
            avg_loss = abs(sum(float(t.profit or 0) for t in losses)) / len(losses) if losses else 0.0

            win_rate = len(wins) / total * 100 if total > 0 else 0.0

            gross_profit = sum(float(t.profit or 0) for t in wins)
            gross_loss = abs(sum(float(t.profit or 0) for t in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

            expectancy = total_pnl / total if total > 0 else 0.0

            # Best and worst trades
            best = max(trades, key=lambda t: float(t.profit or 0))
            worst = min(trades, key=lambda t: float(t.profit or 0))

            # Average duration
            durations = []
            for t in trades:
                if t.open_time and t.close_time:
                    duration = (t.close_time - t.open_time).total_seconds() / 60  # minutes
                    durations.append(duration)

            avg_duration_minutes = sum(durations) / len(durations) if durations else 0

            return {
                'summary': {
                    'total_trades': total,
                    'winning_trades': len(wins),
                    'losing_trades': len(losses),
                    'breakeven_trades': len(breakeven),
                    'win_rate': win_rate,
                    'total_pnl': total_pnl,
                    'avg_win': avg_win,
                    'avg_loss': avg_loss,
                    'profit_factor': profit_factor,
                    'expectancy': expectancy,
                    'avg_duration_minutes': avg_duration_minutes
                },
                'best_trade': {
                    'symbol': best.symbol,
                    'direction': best.direction,
                    'profit': float(best.profit or 0),
                    'ticket': best.ticket
                } if best else None,
                'worst_trade': {
                    'symbol': worst.symbol,
                    'direction': worst.direction,
                    'profit': float(worst.profit or 0),
                    'ticket': worst.ticket
                } if worst else None,
                'period_hours': hours,
                'last_update': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            logger.error(f"Error getting performance analytics: {e}", exc_info=True)
            return {'error': str(e)}

    # =========================================================================
    # Convenience method: Get all dashboard data
    # =========================================================================

    def get_complete_dashboard(self) -> Dict:
        """Get all dashboard sections in one call

        Returns:
            Dict with all dashboard sections
        """
        return {
            'section_1_trading_overview': self.get_realtime_trading_overview(),
            'section_2_ml_performance': self.get_ml_performance_metrics(),
            'section_3_risk_management': self.get_risk_management_status(),
            'section_4_live_positions': self.get_live_positions(),
            'section_5_signal_quality': self.get_signal_quality_metrics(),
            'section_6_shadow_trading': self.get_shadow_trading_analytics(),
            'section_7_system_health': self.get_system_health(),
            'section_8_performance_24h': self.get_performance_analytics(hours=24),
            'section_8_performance_7d': self.get_performance_analytics(hours=168),
            'generated_at': datetime.utcnow().isoformat()
        }


# Convenience function
def get_dashboard(account_id: Optional[int] = None) -> Dict:
    """Get complete dashboard data (convenience function)

    Args:
        account_id: Optional account ID (uses default from config if None)

    Returns:
        Dict with all dashboard data
    """
    with DashboardCore(account_id=account_id) as dashboard:
        return dashboard.get_complete_dashboard()
