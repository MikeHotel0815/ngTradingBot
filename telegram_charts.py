#!/usr/bin/env python3
"""
Telegram P/L Charts Generator

Generiert P/L Charts als Bilder und sendet sie per Telegram.
Kann manuell aufgerufen werden oder per Button im Telegram Bot.
"""

import os
import sys
import io
import logging
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pnl_analyzer import PnLAnalyzer
from telegram_notifier import TelegramNotifier

# Matplotlib imports
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TelegramChartsGenerator:
    """Generates P/L charts and sends them via Telegram"""

    def __init__(self, account_id: int = 3):
        self.account_id = account_id
        self.notifier = TelegramNotifier()
        self.intervals = ['1h', '12h', '24h', '1w', 'ytd']

        # Colors
        self.colors = {
            'positive': '#10b981',
            'negative': '#ef4444',
            'grid': '#333333',
            'bg': '#1a1a1a',
            'text': '#e0e0e0'
        }

    def get_interval_label(self, interval: str) -> str:
        """Get German label for interval"""
        labels = {
            '1h': 'Letzte Stunde',
            '12h': 'Letzte 12 Stunden',
            '24h': 'Letzte 24 Stunden',
            '1w': 'Letzte Woche',
            'ytd': 'Aktuelles Jahr'
        }
        return labels.get(interval, interval)

    def generate_chart(self, interval: str) -> Optional[io.BytesIO]:
        """
        Generate P/L chart for given interval

        Returns:
            BytesIO buffer with PNG image or None on error
        """
        try:
            # Get data
            with PnLAnalyzer(account_id=self.account_id) as analyzer:
                data = analyzer.get_aggregated_pnl(interval)

            if data['trade_count'] == 0:
                logger.warning(f"No trades found for interval {interval}")
                return None

            # Create figure with dark theme
            fig = Figure(figsize=(10, 6), facecolor=self.colors['bg'])
            ax = fig.add_subplot(111, facecolor=self.colors['bg'])

            # Parse timestamps
            timestamps = [datetime.fromisoformat(ts) for ts in data['timestamps']]
            pnl_values = data['pnl_values']

            # Determine line color
            final_pnl = pnl_values[-1] if pnl_values else 0
            line_color = self.colors['positive'] if final_pnl > 0 else self.colors['negative']

            # Plot line
            ax.plot(timestamps, pnl_values, color=line_color, linewidth=2, label='Kumulativer P/L')
            ax.fill_between(timestamps, pnl_values, 0, alpha=0.2, color=line_color)

            # Add zero line
            ax.axhline(y=0, color=self.colors['text'], linestyle='--', linewidth=0.5, alpha=0.5)

            # Styling
            ax.set_title(
                f"📊 {self.get_interval_label(interval)}",
                color=self.colors['text'],
                fontsize=14,
                fontweight='bold',
                pad=15
            )
            ax.set_xlabel('Zeit', color=self.colors['text'], fontsize=10)
            ax.set_ylabel('P/L (€)', color=self.colors['text'], fontsize=10)

            # Grid
            ax.grid(True, alpha=0.2, color=self.colors['text'], linestyle='-', linewidth=0.5)
            ax.set_axisbelow(True)

            # Ticks
            ax.tick_params(colors=self.colors['text'], labelsize=9)

            # Format x-axis
            if interval in ['1h', '12h']:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            elif interval == '24h':
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            elif interval == '1w':
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M'))
            else:  # ytd
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))

            # Rotate x-axis labels
            fig.autofmt_xdate(rotation=45, ha='right')

            # Spine colors
            for spine in ax.spines.values():
                spine.set_edgecolor(self.colors['grid'])
                spine.set_linewidth(0.5)

            # Add stats text
            stats_text = (
                f"Trades: {data['trade_count']} | "
                f"Win Rate: {data['win_rate']}% | "
                f"Total P/L: €{data['total_pnl']:.2f}"
            )
            ax.text(
                0.5, 0.02, stats_text,
                transform=ax.transAxes,
                ha='center',
                va='bottom',
                color=self.colors['text'],
                fontsize=9,
                bbox=dict(boxstyle='round', facecolor=self.colors['bg'], alpha=0.8, edgecolor=self.colors['grid'])
            )

            # Tight layout
            fig.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            fig.savefig(buf, format='png', facecolor=self.colors['bg'], dpi=100)
            buf.seek(0)

            plt.close(fig)

            return buf

        except Exception as e:
            logger.error(f"Error generating chart for {interval}: {e}", exc_info=True)
            return None

    def send_charts_to_telegram(self) -> bool:
        """
        Generate all charts and send them to Telegram

        Returns:
            True if successful, False otherwise
        """
        if not self.notifier.enabled:
            logger.error("Telegram not configured")
            return False

        try:
            logger.info("📊 Generating P/L charts for Telegram...")

            # Send header message
            header = (
                "📊 <b>P/L Performance Charts</b>\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                f"👤 Account: {self.account_id}\n\n"
                "Generiere Charts..."
            )
            self.notifier.send_message(header, parse_mode='HTML')

            # Generate and send each chart
            charts_sent = 0
            for interval in self.intervals:
                logger.info(f"Generating chart for {interval}...")

                chart_buffer = self.generate_chart(interval)

                if chart_buffer:
                    # Send chart as photo
                    caption = f"📊 {self.get_interval_label(interval)}"
                    success = self.notifier.send_photo(chart_buffer, caption=caption)

                    if success:
                        charts_sent += 1
                        logger.info(f"✅ Chart sent for {interval}")
                    else:
                        logger.error(f"❌ Failed to send chart for {interval}")
                else:
                    logger.warning(f"⚠️ No data for {interval}")

            # Send summary
            if charts_sent > 0:
                summary = f"✅ {charts_sent}/{len(self.intervals)} Charts erfolgreich gesendet!"
                self.notifier.send_message(summary)
                logger.info(f"✅ Successfully sent {charts_sent} charts to Telegram")
                return True
            else:
                error_msg = "❌ Keine Charts konnten generiert werden."
                self.notifier.send_message(error_msg)
                logger.error("❌ No charts could be generated")
                return False

        except Exception as e:
            logger.error(f"Error sending charts to Telegram: {e}", exc_info=True)
            error_msg = f"❌ Fehler beim Senden der Charts: {str(e)}"
            self.notifier.send_message(error_msg)
            return False


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Send P/L Charts to Telegram')
    parser.add_argument('account_id', type=int, nargs='?', default=3, help='MT5 Account ID')
    parser.add_argument('--interval', choices=['1h', '12h', '24h', '1w', 'ytd'], help='Send only specific interval')

    args = parser.parse_args()

    generator = TelegramChartsGenerator(account_id=args.account_id)

    if not generator.notifier.enabled:
        logger.error("❌ Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        sys.exit(1)

    if args.interval:
        # Send single chart
        logger.info(f"Generating chart for {args.interval}...")
        chart = generator.generate_chart(args.interval)
        if chart:
            caption = f"📊 {generator.get_interval_label(args.interval)}"
            success = generator.notifier.send_photo(chart, caption=caption)
            if success:
                logger.info("✅ Chart sent successfully")
                sys.exit(0)
            else:
                logger.error("❌ Failed to send chart")
                sys.exit(1)
        else:
            logger.error("❌ Failed to generate chart")
            sys.exit(1)
    else:
        # Send all charts
        success = generator.send_charts_to_telegram()
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
