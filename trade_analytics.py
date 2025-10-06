#!/usr/bin/env python3
"""
Trade Analytics Module for ngTradingBot
Analyzes trading performance and generates insights
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from database import ScopedSession
from models import Trade, TradeAnalytics, Account

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TradeAnalyticsEngine:
    """Analyzes trade performance and generates metrics"""

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.db = ScopedSession()

    def calculate_analytics(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> Dict:
        """
        Calculate trade analytics for given parameters

        Args:
            symbol: Filter by symbol (None = all symbols)
            timeframe: Filter by timeframe (None = all timeframes)
            period_start: Start date (None = all time)
            period_end: End date (None = now)

        Returns:
            Dictionary with analytics metrics
        """
        try:
            # Set defaults
            if period_end is None:
                period_end = datetime.utcnow()
            if period_start is None:
                period_start = period_end - timedelta(days=30)  # Last 30 days by default

            # Build query
            query = self.db.query(Trade).filter(
                and_(
                    Trade.account_id == self.account_id,
                    Trade.status == 'closed',
                    Trade.close_time >= period_start,
                    Trade.close_time <= period_end
                )
            )

            if symbol:
                query = query.filter(Trade.symbol == symbol)
            if timeframe:
                query = query.filter(Trade.timeframe == timeframe)

            trades = query.all()

            if not trades:
                logger.info(f"No trades found for period {period_start} → {period_end}")
                return self._empty_analytics(period_start, period_end)

            # Calculate metrics
            metrics = self._calculate_metrics(trades, period_start, period_end)

            # Save to database
            self._save_analytics(metrics, symbol, timeframe, period_start, period_end)

            return metrics

        except Exception as e:
            logger.error(f"Error calculating analytics: {e}")
            raise
        finally:
            self.db.close()

    def _calculate_metrics(self, trades: List[Trade], period_start: datetime, period_end: datetime) -> Dict:
        """Calculate all performance metrics"""

        total_trades = len(trades)
        winning_trades = [t for t in trades if float(t.profit) > 0]
        losing_trades = [t for t in trades if float(t.profit) < 0]
        breakeven_trades = [t for t in trades if float(t.profit) == 0]

        total_profit = sum(float(t.profit) for t in winning_trades) if winning_trades else 0
        total_loss = abs(sum(float(t.profit) for t in losing_trades)) if losing_trades else 0
        net_profit = total_profit - total_loss

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else (total_profit if total_profit > 0 else 0)

        # Best/Worst trades
        best_trade = max((float(t.profit) for t in trades), default=0)
        worst_trade = min((float(t.profit) for t in trades), default=0)

        # Average win/loss
        avg_win = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        # Duration statistics
        durations = []
        for t in trades:
            if t.open_time and t.close_time:
                duration = (t.close_time - t.open_time).total_seconds() / 60  # minutes
                durations.append(duration)

        avg_duration = sum(durations) / len(durations) if durations else 0

        # Consecutive wins/losses
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_wins = 0
        current_losses = 0

        sorted_trades = sorted(trades, key=lambda t: t.close_time)
        for trade in sorted_trades:
            if float(trade.profit) > 0:
                current_wins += 1
                current_losses = 0
                max_consecutive_wins = max(max_consecutive_wins, current_wins)
            elif float(trade.profit) < 0:
                current_losses += 1
                current_wins = 0
                max_consecutive_losses = max(max_consecutive_losses, current_losses)

        return {
            'period_start': period_start,
            'period_end': period_end,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'breakeven_trades': len(breakeven_trades),
            'win_rate': round(win_rate, 4),
            'profit_factor': round(profit_factor, 4),
            'total_profit': round(total_profit, 2),
            'total_loss': round(total_loss, 2),
            'net_profit': round(net_profit, 2),
            'best_trade_profit': round(best_trade, 2),
            'worst_trade_loss': round(worst_trade, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'avg_duration_minutes': int(avg_duration),
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses
        }

    def _empty_analytics(self, period_start: datetime, period_end: datetime) -> Dict:
        """Return empty analytics when no trades found"""
        return {
            'period_start': period_start,
            'period_end': period_end,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'breakeven_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'total_profit': 0,
            'total_loss': 0,
            'net_profit': 0,
            'best_trade_profit': 0,
            'worst_trade_loss': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'avg_duration_minutes': 0,
            'max_consecutive_wins': 0,
            'max_consecutive_losses': 0
        }

    def _save_analytics(self, metrics: Dict, symbol: Optional[str], timeframe: Optional[str],
                       period_start: datetime, period_end: datetime):
        """Save analytics to database"""

        # Check if analytics already exists for this combination
        existing = self.db.query(TradeAnalytics).filter(
            and_(
                TradeAnalytics.account_id == self.account_id,
                TradeAnalytics.symbol == symbol,
                TradeAnalytics.timeframe == timeframe,
                TradeAnalytics.period_start == period_start,
                TradeAnalytics.period_end == period_end
            )
        ).first()

        if existing:
            # Update existing
            for key, value in metrics.items():
                if key not in ['period_start', 'period_end']:
                    setattr(existing, key, value)
            existing.calculated_at = datetime.utcnow()
        else:
            # Create new
            analytics = TradeAnalytics(
                account_id=self.account_id,
                symbol=symbol,
                timeframe=timeframe,
                **metrics
            )
            self.db.add(analytics)

        self.db.commit()
        logger.info(f"Analytics saved: {symbol or 'ALL'} {timeframe or 'ALL'} | Win Rate: {metrics['win_rate']:.2%}")

    def get_symbol_performance(self, period_days: int = 30) -> List[Dict]:
        """Get performance breakdown by symbol"""

        period_start = datetime.utcnow() - timedelta(days=period_days)

        # Get all unique symbols
        symbols = self.db.query(Trade.symbol).filter(
            and_(
                Trade.account_id == self.account_id,
                Trade.status == 'closed',
                Trade.close_time >= period_start
            )
        ).distinct().all()

        results = []
        for (symbol,) in symbols:
            metrics = self.calculate_analytics(
                symbol=symbol,
                period_start=period_start
            )
            metrics['symbol'] = symbol
            results.append(metrics)

        # Sort by profit factor
        results.sort(key=lambda x: x['profit_factor'], reverse=True)

        return results

    def get_timeframe_performance(self, period_days: int = 30) -> List[Dict]:
        """Get performance breakdown by timeframe"""

        period_start = datetime.utcnow() - timedelta(days=period_days)

        timeframes = ['M1', 'M5', 'M15', 'H1', 'H4', 'D1']
        results = []

        for tf in timeframes:
            metrics = self.calculate_analytics(
                timeframe=tf,
                period_start=period_start
            )
            metrics['timeframe'] = tf
            if metrics['total_trades'] > 0:
                results.append(metrics)

        # Sort by win rate
        results.sort(key=lambda x: x['win_rate'], reverse=True)

        return results

    def get_best_pairs(self, period_days: int = 30, min_trades: int = 5) -> List[Dict]:
        """Get best performing symbol/timeframe combinations"""

        period_start = datetime.utcnow() - timedelta(days=period_days)

        # Get all unique combinations
        combinations = self.db.query(
            Trade.symbol,
            Trade.timeframe
        ).filter(
            and_(
                Trade.account_id == self.account_id,
                Trade.status == 'closed',
                Trade.close_time >= period_start
            )
        ).distinct().all()

        results = []
        for symbol, timeframe in combinations:
            metrics = self.calculate_analytics(
                symbol=symbol,
                timeframe=timeframe,
                period_start=period_start
            )

            if metrics['total_trades'] >= min_trades:
                metrics['symbol'] = symbol
                metrics['timeframe'] = timeframe
                results.append(metrics)

        # Sort by profit factor
        results.sort(key=lambda x: x['profit_factor'], reverse=True)

        return results[:10]  # Top 10

    def get_worst_pairs(self, period_days: int = 30, min_trades: int = 5) -> List[Dict]:
        """Get worst performing symbol/timeframe combinations"""

        best_pairs = self.get_best_pairs(period_days, min_trades)
        worst_pairs = sorted(best_pairs, key=lambda x: x['profit_factor'])

        return worst_pairs[:10]  # Bottom 10


if __name__ == '__main__':
    # Example usage
    analytics = TradeAnalyticsEngine(account_id=1)

    # Overall performance
    overall = analytics.calculate_analytics(period_days=30)
    print(f"Overall Performance (30 days):")
    print(f"  Win Rate: {overall['win_rate']:.2%}")
    print(f"  Profit Factor: {overall['profit_factor']:.2f}")
    print(f"  Net Profit: ${overall['net_profit']:.2f}")

    # Best symbols
    print("\nTop Symbols:")
    for metrics in analytics.get_symbol_performance()[:5]:
        print(f"  {metrics['symbol']}: Win Rate {metrics['win_rate']:.2%}, PF {metrics['profit_factor']:.2f}")
