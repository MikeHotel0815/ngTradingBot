#!/usr/bin/env python3
"""
Chart Generator for ngTradingBot Dashboard
Creates visual analytics charts using matplotlib
"""

import sys
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import io
import base64

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import ScopedSession
from models import Trade, TradingSignal
from monitoring.dashboard_config import get_config

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate analytics charts for dashboard"""

    def __init__(self, account_id: Optional[int] = None):
        self.config = get_config()
        self.account_id = account_id or self.config.DEFAULT_ACCOUNT_ID
        self.db = ScopedSession()

        # Apply dark theme
        plt.style.use(self.config.CHART_STYLE)

        # Colors from config
        self.colors = self.config.CHART_COLORS

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def save_chart_to_file(self, fig: Figure, filename: str, output_dir: str = '/app/data/charts') -> str:
        """Save chart to file

        Args:
            fig: Matplotlib figure
            filename: Output filename (without path)
            output_dir: Output directory

        Returns:
            Full path to saved file
        """
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        fig.savefig(filepath, dpi=self.config.CHART_DPI, bbox_inches='tight', facecolor=self.colors['background'])
        plt.close(fig)
        logger.info(f"Chart saved to {filepath}")
        return filepath

    def fig_to_base64(self, fig: Figure) -> str:
        """Convert figure to base64 string for embedding in HTML

        Args:
            fig: Matplotlib figure

        Returns:
            Base64-encoded PNG image
        """
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=self.config.CHART_DPI, bbox_inches='tight', facecolor=self.colors['background'])
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)
        return img_base64

    # =========================================================================
    # CHART 1: Win Rate Over Time (Rolling Window)
    # =========================================================================

    def generate_winrate_chart(self, days_back: int = 7, rolling_window: int = 20) -> Figure:
        """Generate win rate over time chart with rolling window

        Args:
            days_back: Number of days to look back
            rolling_window: Rolling window size for smoothing

        Returns:
            Matplotlib figure
        """
        since = datetime.utcnow() - timedelta(days=days_back)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).order_by(Trade.close_time).all()

        if len(trades) < rolling_window:
            logger.warning(f"Not enough trades ({len(trades)}) for rolling window ({rolling_window})")
            rolling_window = max(1, len(trades) // 2)

        # Calculate rolling win rate
        close_times = [t.close_time for t in trades]
        profits = [float(t.profit or 0) for t in trades]

        rolling_wr = []
        for i in range(rolling_window, len(trades) + 1):
            window = profits[i - rolling_window:i]
            wins = sum(1 for p in window if p > 0)
            wr = wins / len(window) * 100
            rolling_wr.append(wr)

        plot_times = close_times[rolling_window - 1:]

        # Create figure
        fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)

        ax.plot(plot_times, rolling_wr, color=self.colors['profit'], linewidth=2, label=f'Rolling WR ({rolling_window} trades)')
        ax.axhline(y=60, color=self.colors['profit'], linestyle='--', alpha=0.5, label='Target (60%)')
        ax.axhline(y=50, color=self.colors['neutral'], linestyle='--', alpha=0.5, label='Breakeven (50%)')

        ax.set_xlabel('Date', fontsize=12, color=self.colors['text'])
        ax.set_ylabel('Win Rate (%)', fontsize=12, color=self.colors['text'])
        ax.set_title(f'Win Rate Over Time (Last {days_back} Days)', fontsize=14, fontweight='bold', color=self.colors['text'])
        ax.grid(True, alpha=0.2, color=self.colors['grid'])
        ax.legend(loc='best', facecolor=self.colors['background'], edgecolor=self.colors['grid'])

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        plt.xticks(rotation=45)

        # Set y-axis limits
        ax.set_ylim(0, 100)

        fig.tight_layout()
        return fig

    # =========================================================================
    # CHART 2: P&L Curve (Cumulative)
    # =========================================================================

    def generate_pnl_curve(self, days_back: int = 7) -> Figure:
        """Generate cumulative P&L curve

        Args:
            days_back: Number of days to look back

        Returns:
            Matplotlib figure
        """
        since = datetime.utcnow() - timedelta(days=days_back)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).order_by(Trade.close_time).all()

        if not trades:
            logger.warning("No trades found for P&L curve")
            fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)
            ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14, color=self.colors['text'])
            return fig

        # Calculate cumulative P&L
        close_times = [t.close_time for t in trades]
        profits = [float(t.profit or 0) for t in trades]
        cumulative_pnl = np.cumsum(profits)

        # Create figure
        fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)

        # Color the line based on positive/negative
        colors_line = [self.colors['profit'] if p >= 0 else self.colors['loss'] for p in cumulative_pnl]

        ax.plot(close_times, cumulative_pnl, color=self.colors['profit'], linewidth=2, label='Cumulative P&L')
        ax.fill_between(close_times, 0, cumulative_pnl,
                        where=(np.array(cumulative_pnl) >= 0),
                        color=self.colors['profit'], alpha=0.3)
        ax.fill_between(close_times, 0, cumulative_pnl,
                        where=(np.array(cumulative_pnl) < 0),
                        color=self.colors['loss'], alpha=0.3)

        ax.axhline(y=0, color=self.colors['neutral'], linestyle='-', linewidth=1)

        ax.set_xlabel('Date', fontsize=12, color=self.colors['text'])
        ax.set_ylabel('Cumulative P&L (€)', fontsize=12, color=self.colors['text'])
        ax.set_title(f'Cumulative P&L (Last {days_back} Days)', fontsize=14, fontweight='bold', color=self.colors['text'])
        ax.grid(True, alpha=0.2, color=self.colors['grid'])
        ax.legend(loc='best', facecolor=self.colors['background'], edgecolor=self.colors['grid'])

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        plt.xticks(rotation=45)

        # Add final value annotation
        final_pnl = cumulative_pnl[-1]
        ax.annotate(f'€{final_pnl:+.2f}',
                   xy=(close_times[-1], final_pnl),
                   xytext=(10, 10), textcoords='offset points',
                   fontsize=10, color=self.colors['text'],
                   bbox=dict(boxstyle='round,pad=0.5', fc=self.colors['background'], alpha=0.8))

        fig.tight_layout()
        return fig

    # =========================================================================
    # CHART 3: Symbol Performance Comparison (Bar Chart)
    # =========================================================================

    def generate_symbol_performance_chart(self, days_back: int = 7) -> Figure:
        """Generate symbol performance comparison bar chart

        Args:
            days_back: Number of days to look back

        Returns:
            Matplotlib figure
        """
        since = datetime.utcnow() - timedelta(days=days_back)

        # Query trades by symbol
        from sqlalchemy import func
        results = self.db.query(
            Trade.symbol,
            func.count(Trade.id).label('count'),
            func.sum(Trade.profit).label('total_profit')
        ).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).group_by(Trade.symbol).all()

        if not results:
            logger.warning("No trades found for symbol performance chart")
            fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)
            ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14, color=self.colors['text'])
            return fig

        symbols = [r.symbol for r in results]
        profits = [float(r.total_profit or 0) for r in results]
        counts = [r.count for r in results]

        # Sort by profit
        sorted_data = sorted(zip(symbols, profits, counts), key=lambda x: x[1], reverse=True)
        symbols, profits, counts = zip(*sorted_data)

        # Create figure
        fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)

        # Color bars based on positive/negative
        colors_bars = [self.colors['profit'] if p >= 0 else self.colors['loss'] for p in profits]

        bars = ax.bar(symbols, profits, color=colors_bars, alpha=0.8)

        # Add count labels on bars
        for bar, count in zip(bars, counts):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., height,
                   f'{count} trades',
                   ha='center', va='bottom' if height >= 0 else 'top',
                   fontsize=9, color=self.colors['text'])

        ax.axhline(y=0, color=self.colors['neutral'], linestyle='-', linewidth=1)

        ax.set_xlabel('Symbol', fontsize=12, color=self.colors['text'])
        ax.set_ylabel('Total P&L (€)', fontsize=12, color=self.colors['text'])
        ax.set_title(f'Symbol Performance (Last {days_back} Days)', fontsize=14, fontweight='bold', color=self.colors['text'])
        ax.grid(True, alpha=0.2, axis='y', color=self.colors['grid'])

        plt.xticks(rotation=45)

        fig.tight_layout()
        return fig

    # =========================================================================
    # CHART 4: ML Confidence Distribution (Histogram)
    # =========================================================================

    def generate_ml_confidence_histogram(self, days_back: int = 7) -> Figure:
        """Generate ML confidence distribution histogram

        Args:
            days_back: Number of days to look back

        Returns:
            Matplotlib figure
        """
        since = datetime.utcnow() - timedelta(days=days_back)

        signals = self.db.query(TradingSignal).filter(
            TradingSignal.created_at >= since
        ).all()

        if not signals:
            logger.warning("No signals found for ML confidence histogram")
            fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)
            ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14, color=self.colors['text'])
            return fig

        confidences = [float(s.confidence or 0) for s in signals if s.confidence]

        # Create figure
        fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)

        ax.hist(confidences, bins=20, color=self.colors['buy'], alpha=0.7, edgecolor=self.colors['text'])

        # Add vertical lines for thresholds
        ax.axvline(x=60, color=self.colors['profit'], linestyle='--', linewidth=2, label='Target Threshold (60%)')
        ax.axvline(x=np.mean(confidences), color=self.colors['neutral'], linestyle='--', linewidth=2, label=f'Mean ({np.mean(confidences):.1f}%)')

        ax.set_xlabel('Confidence (%)', fontsize=12, color=self.colors['text'])
        ax.set_ylabel('Frequency', fontsize=12, color=self.colors['text'])
        ax.set_title(f'ML Confidence Distribution (Last {days_back} Days)', fontsize=14, fontweight='bold', color=self.colors['text'])
        ax.grid(True, alpha=0.2, axis='y', color=self.colors['grid'])
        ax.legend(loc='best', facecolor=self.colors['background'], edgecolor=self.colors['grid'])

        fig.tight_layout()
        return fig

    # =========================================================================
    # CHART 5: Buy vs Sell Performance
    # =========================================================================

    def generate_buy_sell_comparison(self, days_back: int = 7) -> Figure:
        """Generate BUY vs SELL performance comparison

        Args:
            days_back: Number of days to look back

        Returns:
            Matplotlib figure
        """
        since = datetime.utcnow() - timedelta(days=days_back)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).all()

        if not trades:
            logger.warning("No trades found for BUY/SELL comparison")
            fig, ax = plt.subplots(figsize=self.config.CHART_FIGSIZE)
            ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14, color=self.colors['text'])
            return fig

        # Separate by direction
        buy_trades = [t for t in trades if t.direction.upper() == 'BUY']
        sell_trades = [t for t in trades if t.direction.upper() == 'SELL']

        # Calculate metrics
        buy_wins = sum(1 for t in buy_trades if float(t.profit or 0) > 0)
        buy_wr = (buy_wins / len(buy_trades) * 100) if buy_trades else 0
        buy_pnl = sum(float(t.profit or 0) for t in buy_trades)

        sell_wins = sum(1 for t in sell_trades if float(t.profit or 0) > 0)
        sell_wr = (sell_wins / len(sell_trades) * 100) if sell_trades else 0
        sell_pnl = sum(float(t.profit or 0) for t in sell_trades)

        # Create figure with subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=self.config.CHART_FIGSIZE)

        # Subplot 1: Win Rate Comparison
        categories = ['BUY', 'SELL']
        win_rates = [buy_wr, sell_wr]
        colors_bars = [self.colors['buy'], self.colors['sell']]

        bars1 = ax1.bar(categories, win_rates, color=colors_bars, alpha=0.8)

        for bar, wr, count in zip(bars1, win_rates, [len(buy_trades), len(sell_trades)]):
            ax1.text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                    f'{wr:.1f}%\n({count} trades)',
                    ha='center', va='bottom',
                    fontsize=10, color=self.colors['text'])

        ax1.axhline(y=50, color=self.colors['neutral'], linestyle='--', alpha=0.5)
        ax1.set_ylabel('Win Rate (%)', fontsize=12, color=self.colors['text'])
        ax1.set_title('Win Rate Comparison', fontsize=12, fontweight='bold', color=self.colors['text'])
        ax1.set_ylim(0, 100)
        ax1.grid(True, alpha=0.2, axis='y', color=self.colors['grid'])

        # Subplot 2: P&L Comparison
        pnls = [buy_pnl, sell_pnl]
        colors_bars2 = [self.colors['profit'] if p >= 0 else self.colors['loss'] for p in pnls]

        bars2 = ax2.bar(categories, pnls, color=colors_bars2, alpha=0.8)

        for bar, pnl in zip(bars2, pnls):
            ax2.text(bar.get_x() + bar.get_width() / 2., bar.get_height(),
                    f'€{pnl:+.2f}',
                    ha='center', va='bottom' if pnl >= 0 else 'top',
                    fontsize=10, color=self.colors['text'])

        ax2.axhline(y=0, color=self.colors['neutral'], linestyle='-', linewidth=1)
        ax2.set_ylabel('Total P&L (€)', fontsize=12, color=self.colors['text'])
        ax2.set_title('P&L Comparison', fontsize=12, fontweight='bold', color=self.colors['text'])
        ax2.grid(True, alpha=0.2, axis='y', color=self.colors['grid'])

        fig.suptitle(f'BUY vs SELL Performance (Last {days_back} Days)', fontsize=14, fontweight='bold', color=self.colors['text'])
        fig.tight_layout()
        return fig

    # =========================================================================
    # Convenience method: Generate all charts
    # =========================================================================

    def generate_all_charts(self, days_back: int = 7, output_dir: str = '/app/data/charts') -> Dict[str, str]:
        """Generate all dashboard charts and save to files

        Args:
            days_back: Number of days to look back
            output_dir: Output directory for saved charts

        Returns:
            Dict mapping chart names to file paths
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        charts = {}

        try:
            logger.info("Generating win rate chart...")
            fig = self.generate_winrate_chart(days_back=days_back)
            charts['winrate'] = self.save_chart_to_file(fig, f'winrate_{timestamp}.png', output_dir)
        except Exception as e:
            logger.error(f"Error generating win rate chart: {e}")

        try:
            logger.info("Generating P&L curve...")
            fig = self.generate_pnl_curve(days_back=days_back)
            charts['pnl_curve'] = self.save_chart_to_file(fig, f'pnl_curve_{timestamp}.png', output_dir)
        except Exception as e:
            logger.error(f"Error generating P&L curve: {e}")

        try:
            logger.info("Generating symbol performance chart...")
            fig = self.generate_symbol_performance_chart(days_back=days_back)
            charts['symbol_performance'] = self.save_chart_to_file(fig, f'symbol_performance_{timestamp}.png', output_dir)
        except Exception as e:
            logger.error(f"Error generating symbol performance chart: {e}")

        try:
            logger.info("Generating ML confidence histogram...")
            fig = self.generate_ml_confidence_histogram(days_back=days_back)
            charts['ml_confidence'] = self.save_chart_to_file(fig, f'ml_confidence_{timestamp}.png', output_dir)
        except Exception as e:
            logger.error(f"Error generating ML confidence histogram: {e}")

        try:
            logger.info("Generating BUY/SELL comparison...")
            fig = self.generate_buy_sell_comparison(days_back=days_back)
            charts['buy_sell'] = self.save_chart_to_file(fig, f'buy_sell_{timestamp}.png', output_dir)
        except Exception as e:
            logger.error(f"Error generating BUY/SELL comparison: {e}")

        logger.info(f"Generated {len(charts)} charts")
        return charts


def main():
    """Main entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Generate dashboard charts')
    parser.add_argument('--days', type=int, default=7, help='Days to look back (default: 7)')
    parser.add_argument('--output-dir', type=str, default='/app/data/charts', help='Output directory')
    parser.add_argument('--account-id', type=int, help='Account ID')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with ChartGenerator(account_id=args.account_id) as generator:
        charts = generator.generate_all_charts(days_back=args.days, output_dir=args.output_dir)

        print("\n✅ Charts generated successfully:")
        for name, path in charts.items():
            print(f"  - {name}: {path}")


if __name__ == '__main__':
    main()
