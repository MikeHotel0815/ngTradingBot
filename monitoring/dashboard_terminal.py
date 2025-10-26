#!/usr/bin/env python3
"""
Terminal Dashboard for ngTradingBot
CLI interface with rich formatting and live updates
"""

import sys
import os
import time
import argparse
from datetime import datetime
from typing import Optional

# Rich library for colored terminal output
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Warning: 'rich' library not installed. Run: pip install rich")
    print("Falling back to basic output...")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.dashboard_core import DashboardCore
from monitoring.dashboard_config import get_config

console = Console() if RICH_AVAILABLE else None


class TerminalDashboard:
    """Terminal-based dashboard with rich formatting"""

    def __init__(self, account_id: Optional[int] = None):
        self.config = get_config()
        self.account_id = account_id or self.config.DEFAULT_ACCOUNT_ID
        self.dashboard = DashboardCore(account_id=self.account_id)

    def format_pnl(self, pnl: float) -> str:
        """Format P&L with color"""
        if not RICH_AVAILABLE:
            return f"€{pnl:+.2f}"

        if pnl > 0:
            return f"[green]€{pnl:+.2f}[/green]"
        elif pnl < 0:
            return f"[red]€{pnl:+.2f}[/red]"
        else:
            return f"[dim]€{pnl:.2f}[/dim]"

    def format_status(self, status: str) -> str:
        """Format status with color"""
        if not RICH_AVAILABLE:
            return status.upper()

        status_lower = status.lower()
        if status_lower == 'active':
            return "[green]●[/green] ACTIVE"
        elif status_lower == 'shadow_trade':
            return "[yellow]○[/yellow] SHADOW"
        elif status_lower == 'paused':
            return "[red]⏸[/red] PAUSED"
        else:
            return status.upper()

    def create_trading_overview_table(self, data: dict) -> Table:
        """Create trading overview table"""
        table = Table(title="🔴 LIVE TRADING STATUS", box=box.ROUNDED, show_header=True, header_style="bold cyan")

        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Open Pos", justify="right")
        table.add_column("Today P&L", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Signals", justify="right")

        symbols = data.get('symbols', [])
        for sym in symbols:
            wr = f"{sym['win_rate']:.1f}%" if sym['win_rate'] is not None else "N/A"

            table.add_row(
                sym['symbol'],
                self.format_status(sym['status']),
                str(sym['open_positions']),
                self.format_pnl(sym['today_pnl']),
                wr,
                str(sym['signals_today'])
            )

        # Total row
        total = data.get('total', {})
        table.add_row(
            "[bold]TOTAL[/bold]",
            "",
            f"[bold]{total.get('open_positions', 0)}[/bold]",
            f"[bold]{self.format_pnl(total.get('today_pnl', 0))}[/bold]",
            f"[bold]{total.get('win_rate', 0):.1f}%[/bold]",
            f"[bold]{total.get('total_signals', 0)}[/bold]",
            style="bold"
        )

        return table

    def create_risk_management_panel(self, data: dict) -> Panel:
        """Create risk management status panel"""
        dd = data.get('daily_drawdown', {})
        pos = data.get('position_limits', {})
        sl = data.get('sl_enforcement', {})

        # Drawdown status
        dd_status = dd.get('status', 'UNKNOWN')
        dd_current = dd.get('current', 0)

        if dd_status == 'SAFE':
            dd_color = 'green'
        elif dd_status == 'WARNING':
            dd_color = 'yellow'
        else:
            dd_color = 'red'

        # Position usage
        usage_pct = pos.get('usage_pct', 0)
        if usage_pct >= 90:
            pos_color = 'red'
        elif usage_pct >= 80:
            pos_color = 'yellow'
        else:
            pos_color = 'green'

        # SL enforcement
        sl_ok = sl.get('all_trades_have_sl', False)
        sl_color = 'green' if sl_ok else 'red'

        text = f"""[{dd_color}]Drawdown: €{dd_current:+.2f} ({dd_status})[/{dd_color}]
Limit: €{dd.get('warning_limit', 0):.2f} (Warning) / €{dd.get('critical_limit', 0):.2f} (Critical)

[{pos_color}]Positions: {pos.get('current_open', 0)} / {pos.get('max_total', 0)} ({usage_pct:.0f}% used)[/{pos_color}]

[{sl_color}]SL Enforcement: {'✅ OK' if sl_ok else '❌ FAILED'}[/{sl_color}]
Trades without SL: {sl.get('trades_without_sl', 0)}
"""

        return Panel(text, title="🛡️ RISK MANAGEMENT", border_style="cyan")

    def create_live_positions_table(self, data: dict) -> Table:
        """Create live positions table"""
        table = Table(title="📈 OPEN POSITIONS", box=box.ROUNDED, show_header=True, header_style="bold cyan")

        table.add_column("Ticket", style="dim")
        table.add_column("Symbol", style="cyan")
        table.add_column("Dir", justify="center")
        table.add_column("Entry", justify="right")
        table.add_column("Current", justify="right")
        table.add_column("SL", justify="right")
        table.add_column("TP", justify="right")
        table.add_column("P&L", justify="right")

        positions = data.get('positions', [])

        if not positions:
            table.add_row("No open positions", "", "", "", "", "", "", "")
            return table

        for pos in positions:
            dir_color = "blue" if pos['direction'] == 'BUY' else "yellow"

            pnl = pos.get('unrealized_pnl')
            pnl_str = self.format_pnl(pnl) if pnl else "N/A"

            table.add_row(
                str(pos['ticket']),
                pos['symbol'],
                f"[{dir_color}]{pos['direction']}[/{dir_color}]",
                f"{pos['entry_price']:.5f}" if pos['entry_price'] else "N/A",
                f"{pos['current_price']:.5f}" if pos['current_price'] else "N/A",
                f"{pos['sl']:.5f}" if pos['sl'] else "N/A",
                f"{pos['tp']:.5f}" if pos['tp'] else "N/A",
                pnl_str
            )

        return table

    def create_performance_panel(self, data: dict) -> Panel:
        """Create performance analytics panel"""
        summary = data.get('summary', {})

        total = summary.get('total_trades', 0)
        wins = summary.get('winning_trades', 0)
        losses = summary.get('losing_trades', 0)
        wr = summary.get('win_rate', 0)
        pnl = summary.get('total_pnl', 0)
        pf = summary.get('profit_factor', 0)

        wr_color = 'green' if wr >= 60 else 'yellow' if wr >= 50 else 'red'
        pf_color = 'green' if pf >= 1.5 else 'yellow' if pf >= 1.0 else 'red'

        text = f"""Total Trades: {total} ({wins}W / {losses}L)
[{wr_color}]Win Rate: {wr:.1f}%[/{wr_color}]
{self.format_pnl(pnl)}
[{pf_color}]Profit Factor: {pf:.2f}[/{pf_color}]

Avg Win: €{summary.get('avg_win', 0):.2f}
Avg Loss: €{summary.get('avg_loss', 0):.2f}
Expectancy: €{summary.get('expectancy', 0):.2f} per trade
"""

        best = data.get('best_trade')
        worst = data.get('worst_trade')

        if best:
            text += f"\nBest: {best['symbol']} {best['direction']} €{best['profit']:+.2f}"
        if worst:
            text += f"\nWorst: {worst['symbol']} {worst['direction']} €{worst['profit']:+.2f}"

        return Panel(text, title="📊 PERFORMANCE (24H)", border_style="cyan")

    def create_system_health_panel(self, data: dict) -> Panel:
        """Create system health panel"""
        mt5 = data.get('mt5_connection', {})
        pg = data.get('postgresql', {})
        redis = data.get('redis', {})

        mt5_status = "🟢 CONNECTED" if mt5.get('connected') else "🔴 DISCONNECTED"
        pg_status = "🟢 CONNECTED" if pg.get('connected') else "🔴 DISCONNECTED"
        redis_status = "🟢 CONNECTED" if redis.get('connected') else "🔴 DISCONNECTED"

        heartbeat = mt5.get('last_heartbeat_seconds_ago')
        hb_str = f"{heartbeat:.0f}s ago" if heartbeat else "N/A"

        text = f"""MT5: {mt5_status} (Last: {hb_str})
PostgreSQL: {pg_status} ({pg.get('active_connections', 0)} conn, {pg.get('database_size_mb', 0):.0f} MB)
Redis: {redis_status}
"""

        return Panel(text, title="💻 SYSTEM HEALTH", border_style="cyan")

    def generate_dashboard_layout(self) -> Layout:
        """Generate complete dashboard layout"""
        # Fetch all data
        trading = self.dashboard.get_realtime_trading_overview()
        risk = self.dashboard.get_risk_management_status()
        positions = self.dashboard.get_live_positions()
        performance = self.dashboard.get_performance_analytics(hours=24)
        health = self.dashboard.get_system_health()

        # Create layout
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )

        # Header
        header_text = Text(f"ngTradingBot Ultimate Dashboard - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                          style="bold cyan", justify="center")
        layout["header"].update(Panel(header_text))

        # Body
        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )

        layout["left"].split_column(
            Layout(self.create_trading_overview_table(trading)),
            Layout(self.create_live_positions_table(positions))
        )

        layout["right"].split_column(
            Layout(self.create_risk_management_panel(risk)),
            Layout(self.create_performance_panel(performance)),
            Layout(self.create_system_health_panel(health))
        )

        # Footer
        footer_text = Text("Press Ctrl+C to exit | Update interval: 5s",
                          style="dim", justify="center")
        layout["footer"].update(Panel(footer_text))

        return layout

    def run_live(self, update_interval: int = 5):
        """Run dashboard in live mode with auto-refresh"""
        if not RICH_AVAILABLE:
            print("Live mode requires 'rich' library. Install with: pip install rich")
            return

        console.print("[bold green]Starting live dashboard...[/bold green]")
        console.print(f"Update interval: {update_interval}s\n")

        try:
            with Live(self.generate_dashboard_layout(), refresh_per_second=1, console=console) as live:
                while True:
                    time.sleep(update_interval)
                    live.update(self.generate_dashboard_layout())
        except KeyboardInterrupt:
            console.print("\n[yellow]Dashboard stopped by user[/yellow]")

    def run_once(self):
        """Run dashboard once and exit"""
        if not RICH_AVAILABLE:
            # Fallback to simple text output
            data = self.dashboard.get_complete_dashboard()
            print(json.dumps(data, indent=2, default=str))
            return

        layout = self.generate_dashboard_layout()
        console.print(layout)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='ngTradingBot Terminal Dashboard')
    parser.add_argument('--live', action='store_true', help='Run in live mode with auto-refresh')
    parser.add_argument('--interval', type=int, default=5, help='Update interval in seconds (default: 5)')
    parser.add_argument('--account-id', type=int, help='Account ID (defaults to config)')

    args = parser.parse_args()

    dashboard = TerminalDashboard(account_id=args.account_id)

    if args.live:
        dashboard.run_live(update_interval=args.interval)
    else:
        dashboard.run_once()


if __name__ == '__main__':
    main()
