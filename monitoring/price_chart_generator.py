#!/usr/bin/env python3
"""
Price Chart Generator with TP/SL Levels
Creates candlestick charts with Take Profit and Stop Loss levels for open trades
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
import matplotlib.patches as mpatches
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import ScopedSession
from models import Trade, OHLCData
from monitoring.dashboard_config import get_config

logger = logging.getLogger(__name__)


class PriceChartGenerator:
    """Generate price charts with TP/SL levels for open trades"""

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

    def get_ohlc_data(
        self,
        symbol: str,
        timeframe: str = 'H1',
        bars_back: int = 100
    ) -> List[Dict]:
        """Get OHLC data from database

        Args:
            symbol: Trading symbol (e.g., 'EURUSD')
            timeframe: Timeframe (M1, M5, M15, H1, H4, D1)
            bars_back: Number of bars to retrieve

        Returns:
            List of OHLC data dicts with keys: timestamp, open, high, low, close, volume
        """
        since = datetime.utcnow() - timedelta(hours=bars_back * self._get_timeframe_hours(timeframe))

        ohlc_records = self.db.query(OHLCData).filter(
            OHLCData.symbol == symbol,
            OHLCData.timeframe == timeframe,
            OHLCData.timestamp >= since
        ).order_by(OHLCData.timestamp.asc()).limit(bars_back).all()

        if not ohlc_records:
            logger.warning(f"No OHLC data found for {symbol} {timeframe}")
            return []

        data = []
        for record in ohlc_records:
            data.append({
                'timestamp': record.timestamp,
                'open': float(record.open),
                'high': float(record.high),
                'low': float(record.low),
                'close': float(record.close),
                'volume': int(record.volume or 0)
            })

        return data

    def _get_timeframe_hours(self, timeframe: str) -> float:
        """Convert timeframe string to hours"""
        mapping = {
            'M1': 1/60,
            'M5': 5/60,
            'M15': 15/60,
            'H1': 1,
            'H4': 4,
            'D1': 24
        }
        return mapping.get(timeframe, 1)

    def get_trades_for_symbol(
        self,
        symbol: str,
        trade_filter: str = 'open',
        hours_back: int = 24
    ) -> List[Trade]:
        """Get trades for a symbol with flexible filtering

        Args:
            symbol: Trading symbol
            trade_filter: 'open', 'closed', or 'all'
            hours_back: For closed/all trades, how many hours to look back

        Returns:
            List of Trade objects
        """
        query = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.symbol == symbol
        )

        if trade_filter == 'open':
            query = query.filter(Trade.status == 'open')
        elif trade_filter == 'closed':
            # Only recent closed trades
            from datetime import datetime, timedelta
            since = datetime.utcnow() - timedelta(hours=hours_back)
            query = query.filter(
                Trade.status == 'closed',
                Trade.close_time >= since
            )
        elif trade_filter == 'all':
            # Open trades + recent closed trades
            from datetime import datetime, timedelta
            since = datetime.utcnow() - timedelta(hours=hours_back)
            query = query.filter(
                (Trade.status == 'open') |
                ((Trade.status == 'closed') & (Trade.close_time >= since))
            )

        trades = query.all()
        logger.info(f"Found {len(trades)} {trade_filter} trades for {symbol} (last {hours_back}h)")
        return trades

    def get_open_trades_for_symbol(self, symbol: str) -> List[Trade]:
        """Get all open trades for a symbol (legacy compatibility)

        Args:
            symbol: Trading symbol

        Returns:
            List of open Trade objects
        """
        return self.get_trades_for_symbol(symbol, trade_filter='open')

    def plot_candlestick(
        self,
        ax,
        ohlc_data: List[Dict],
        width: float = 0.6
    ):
        """Plot candlestick chart on given axes

        Args:
            ax: Matplotlib axes
            ohlc_data: List of OHLC data dicts
            width: Candlestick width (in days)
        """
        timestamps = [d['timestamp'] for d in ohlc_data]
        opens = [d['open'] for d in ohlc_data]
        highs = [d['high'] for d in ohlc_data]
        lows = [d['low'] for d in ohlc_data]
        closes = [d['close'] for d in ohlc_data]

        # Convert timestamps to matplotlib dates
        dates = mdates.date2num(timestamps)

        # Plot candlesticks
        for i in range(len(ohlc_data)):
            date = dates[i]
            open_price = opens[i]
            high_price = highs[i]
            low_price = lows[i]
            close_price = closes[i]

            # Determine color (green if close > open, red otherwise)
            if close_price >= open_price:
                color = self.colors['profit']
                lower = open_price
                height = close_price - open_price
            else:
                color = self.colors['loss']
                lower = close_price
                height = open_price - close_price

            # Plot high-low line (wick)
            ax.plot([date, date], [low_price, high_price], color=color, linewidth=0.8, alpha=0.8)

            # Plot open-close rectangle (body)
            rect = mpatches.Rectangle(
                (date - width/2, lower),
                width,
                height,
                facecolor=color,
                edgecolor=color,
                alpha=0.9
            )
            ax.add_patch(rect)

    def generate_price_chart_with_tpsl(
        self,
        symbol: str,
        timeframe: str = 'H1',
        bars_back: int = 100,
        trade_filter: str = 'open',
        hours_back: int = 24
    ) -> Optional[Figure]:
        """Generate price chart with TP/SL levels for trades

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (M1, M5, M15, H1, H4, D1)
            bars_back: Number of bars to display
            trade_filter: 'open', 'closed', or 'all'
            hours_back: For closed/all trades, how many hours to look back

        Returns:
            Matplotlib figure or None if no data
        """
        # Get OHLC data
        ohlc_data = self.get_ohlc_data(symbol, timeframe, bars_back)
        if not ohlc_data:
            logger.warning(f"No OHLC data for {symbol} {timeframe}")
            return None

        # Get trades based on filter
        trades = self.get_trades_for_symbol(symbol, trade_filter, hours_back)

        # Create figure
        fig, ax = plt.subplots(figsize=(14, 8))
        fig.patch.set_facecolor(self.colors['background'])
        ax.set_facecolor(self.colors['background'])

        # Plot candlesticks
        self.plot_candlestick(ax, ohlc_data)

        # Get current price (last close)
        current_price = ohlc_data[-1]['close']

        # Plot TP/SL levels for each trade
        legend_handles = []
        trade_colors = ['#ff6b6b', '#4ecdc4', '#ffe66d', '#a8e6cf', '#ff8b94']

        for idx, trade in enumerate(trades):
            trade_color = trade_colors[idx % len(trade_colors)]

            entry_price = float(trade.open_price)

            # For closed trades, use initial_tp/initial_sl (tp/sl are reset to 0 on close)
            # For open trades, use current tp/sl (or fall back to initial if not set)
            if trade.status == 'closed':
                tp_price = float(trade.initial_tp) if trade.initial_tp else None
                sl_price = float(trade.initial_sl) if trade.initial_sl else None
            else:
                tp_price = float(trade.tp) if trade.tp else (float(trade.initial_tp) if trade.initial_tp else None)
                sl_price = float(trade.sl) if trade.sl else (float(trade.initial_sl) if trade.initial_sl else None)

            # Plot Entry Price (dashed line)
            ax.axhline(
                y=entry_price,
                color=trade_color,
                linestyle='--',
                linewidth=1.5,
                alpha=0.7,
                label=f'#{trade.ticket} Entry ({trade.direction})'
            )

            # Plot TP (solid green line)
            if tp_price:
                ax.axhline(
                    y=tp_price,
                    color=self.colors['profit'],
                    linestyle='-',
                    linewidth=2,
                    alpha=0.8
                )
                # Add TP label
                ax.text(
                    ohlc_data[-1]['timestamp'],
                    tp_price,
                    f' TP: {tp_price:.5f}',
                    color=self.colors['profit'],
                    fontsize=9,
                    va='center',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor=self.colors['background'], alpha=0.7, edgecolor=self.colors['profit'])
                )

            # Plot SL (solid red line)
            if sl_price:
                ax.axhline(
                    y=sl_price,
                    color=self.colors['loss'],
                    linestyle='-',
                    linewidth=2,
                    alpha=0.8
                )
                # Add SL label
                ax.text(
                    ohlc_data[-1]['timestamp'],
                    sl_price,
                    f' SL: {sl_price:.5f}',
                    color=self.colors['loss'],
                    fontsize=9,
                    va='center',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor=self.colors['background'], alpha=0.7, edgecolor=self.colors['loss'])
                )

            # Add trade info text box
            profit = float(trade.profit or 0)
            status_label = "OPEN" if trade.status == 'open' else "CLOSED"

            if trade.status == 'open':
                trade_info = (
                    f"#{trade.ticket} {trade.direction} [{status_label}]\n"
                    f"Entry: {entry_price:.5f}\n"
                    f"Current: {current_price:.5f}\n"
                    f"P/L: €{profit:.2f}"
                )
            else:
                # For closed trades, show close price instead of current
                close_price = float(trade.close_price) if trade.close_price else entry_price
                trade_info = (
                    f"#{trade.ticket} {trade.direction} [{status_label}]\n"
                    f"Entry: {entry_price:.5f}\n"
                    f"Close: {close_price:.5f}\n"
                    f"P/L: €{profit:.2f}"
                )

            # Position text box in top-left area, stacked vertically
            text_y = 0.95 - (idx * 0.15)
            ax.text(
                0.02, text_y,
                trade_info,
                transform=ax.transAxes,
                fontsize=9,
                color=self.colors['text'],
                va='top',
                bbox=dict(boxstyle='round,pad=0.5', facecolor=trade_color, alpha=0.3, edgecolor=trade_color)
            )

        # Add current price line
        ax.axhline(
            y=current_price,
            color=self.colors['text'],
            linestyle=':',
            linewidth=1,
            alpha=0.5,
            label=f'Current: {current_price:.5f}'
        )

        # Styling
        ax.set_xlabel('Time', fontsize=12, color=self.colors['text'])
        ax.set_ylabel('Price', fontsize=12, color=self.colors['text'])

        # Title with filter info
        filter_label = trade_filter.upper() if trade_filter != 'all' else f'ALL (last {hours_back}h)'
        title = f'{symbol} - {timeframe} | {filter_label} Trades: {len(trades)}'
        ax.set_title(title, fontsize=14, fontweight='bold', color=self.colors['text'], pad=15)

        ax.grid(True, alpha=0.2, color=self.colors['grid'], linestyle='-', linewidth=0.5)
        ax.tick_params(colors=self.colors['text'])

        # Format x-axis dates
        if timeframe in ['M1', 'M5', 'M15']:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        elif timeframe in ['H1', 'H4']:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        else:  # D1
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))

        plt.xticks(rotation=45)
        fig.autofmt_xdate()

        # Legend (only if there are trades)
        if trades:
            ax.legend(loc='upper left', fontsize=9, facecolor=self.colors['background'],
                     edgecolor=self.colors['grid'], framealpha=0.8)

        fig.tight_layout()
        return fig

    def generate_all_symbols_charts(
        self,
        timeframe: str = 'H1',
        bars_back: int = 100,
        output_dir: str = '/app/data/charts',
        trade_filter: str = 'open',
        hours_back: int = 24
    ) -> Dict[str, str]:
        """Generate price charts for all symbols with trades

        Args:
            timeframe: Timeframe to use
            bars_back: Number of bars to display
            output_dir: Output directory
            trade_filter: 'open', 'closed', or 'all'
            hours_back: For closed/all trades, how many hours to look back

        Returns:
            Dict mapping symbol to file path
        """
        # Get all symbols with trades matching the filter
        from sqlalchemy import distinct, or_
        from datetime import timedelta

        query = self.db.query(distinct(Trade.symbol)).filter(
            Trade.account_id == self.account_id
        )

        if trade_filter == 'open':
            query = query.filter(Trade.status == 'open')
        elif trade_filter == 'closed':
            since = datetime.utcnow() - timedelta(hours=hours_back)
            query = query.filter(
                Trade.status == 'closed',
                Trade.close_time >= since
            )
        elif trade_filter == 'all':
            since = datetime.utcnow() - timedelta(hours=hours_back)
            query = query.filter(
                or_(
                    Trade.status == 'open',
                    (Trade.status == 'closed') & (Trade.close_time >= since)
                )
            )

        symbols = [s[0] for s in query.all()]
        logger.info(f"Generating price charts for {len(symbols)} symbols with {trade_filter} trades")

        charts = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        for symbol in symbols:
            try:
                logger.info(f"Generating chart for {symbol}...")
                fig = self.generate_price_chart_with_tpsl(
                    symbol, timeframe, bars_back, trade_filter, hours_back
                )

                if fig:
                    filename = f'price_{symbol}_{timeframe}_{timestamp}.png'
                    filepath = self.save_chart_to_file(fig, filename, output_dir)
                    charts[symbol] = filepath
                    logger.info(f"✅ Chart saved for {symbol}")
                else:
                    logger.warning(f"⚠️ No chart generated for {symbol}")

            except Exception as e:
                logger.error(f"Error generating chart for {symbol}: {e}", exc_info=True)

        logger.info(f"Generated {len(charts)} price charts")
        return charts


def main():
    """Main entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Generate price charts with TP/SL levels')
    parser.add_argument('--symbol', type=str, help='Symbol to chart (default: all symbols with open trades)')
    parser.add_argument('--timeframe', type=str, default='H1', choices=['M1', 'M5', 'M15', 'H1', 'H4', 'D1'],
                       help='Timeframe (default: H1)')
    parser.add_argument('--bars', type=int, default=100, help='Number of bars to display (default: 100)')
    parser.add_argument('--output-dir', type=str, default='/app/data/charts', help='Output directory')
    parser.add_argument('--account-id', type=int, help='Account ID')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with PriceChartGenerator(account_id=args.account_id) as generator:
        if args.symbol:
            # Generate single chart
            fig = generator.generate_price_chart_with_tpsl(args.symbol, args.timeframe, args.bars)
            if fig:
                filename = f'price_{args.symbol}_{args.timeframe}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
                filepath = generator.save_chart_to_file(fig, filename, args.output_dir)
                print(f"\n✅ Chart generated: {filepath}")
            else:
                print(f"\n❌ Failed to generate chart for {args.symbol}")
        else:
            # Generate charts for all symbols with open trades
            charts = generator.generate_all_symbols_charts(args.timeframe, args.bars, args.output_dir)

            print(f"\n✅ Generated {len(charts)} charts:")
            for symbol, path in charts.items():
                print(f"  - {symbol}: {path}")


if __name__ == '__main__':
    main()
