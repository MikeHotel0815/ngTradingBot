#!/usr/bin/env python3
"""
Performance Monitor & Growth Projection Dashboard
Tracks trading performance and provides deposit recommendations
"""

import psycopg2
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple
import os
import sys

# Add parent directory to path for telegram_notifier import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from telegram_notifier import TelegramNotifier
except ImportError:
    TelegramNotifier = None


class PerformanceMonitor:
    """Monitor trading performance and project future growth"""

    def __init__(self):
        # Try DATABASE_URL first, fallback to individual env vars
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            self.conn = psycopg2.connect(database_url)
        else:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST', 'postgres'),
                port=int(os.getenv('DB_PORT', 5432)),
                user=os.getenv('DB_USER', 'trader'),
                password=os.getenv('DB_PASSWORD', 'tradingbot_secret_2025'),
                database=os.getenv('DB_NAME', 'ngtradingbot')
            )
        self.cursor = self.conn.cursor()

    def get_account_info(self, account_id: int = 3) -> Dict:
        """Get current account balance and equity"""
        self.cursor.execute("""
            SELECT
                mt5_account_number,
                balance,
                equity,
                free_margin,
                profit_today,
                profit_week,
                profit_month,
                last_heartbeat
            FROM accounts
            WHERE id = %s
        """, (account_id,))

        row = self.cursor.fetchone()
        if not row:
            return {}

        return {
            'mt5_account': row[0],
            'balance': float(row[1]) if row[1] else 0.0,
            'equity': float(row[2]) if row[2] else 0.0,
            'free_margin': float(row[3]) if row[3] else 0.0,
            'profit_today': float(row[4]) if row[4] else 0.0,
            'profit_week': float(row[5]) if row[5] else 0.0,
            'profit_month': float(row[6]) if row[6] else 0.0,
            'last_update': row[7]
        }

    def get_performance_metrics(self, account_id: int = 3, days: int = 30) -> Dict:
        """Calculate performance metrics for given period"""
        self.cursor.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) as losses,
                AVG(CASE WHEN profit > 0 THEN profit ELSE 0 END) as avg_win,
                AVG(CASE WHEN profit < 0 THEN profit ELSE 0 END) as avg_loss,
                SUM(profit) as total_pnl,
                MAX(profit) as best_trade,
                MIN(profit) as worst_trade
            FROM trades
            WHERE account_id = %s
              AND close_time >= NOW() - INTERVAL '%s days'
              AND close_time IS NOT NULL
        """, (account_id, days))

        row = self.cursor.fetchone()
        if not row or row[0] == 0:
            return {}

        total_trades = row[0]
        wins = row[1] or 0
        losses = row[2] or 0
        avg_win = float(row[3]) if row[3] else 0.0
        avg_loss = float(row[4]) if row[4] else 0.0
        total_pnl = float(row[5]) if row[5] else 0.0
        best_trade = float(row[6]) if row[6] else 0.0
        worst_trade = float(row[7]) if row[7] else 0.0

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        # Calculate profit factor
        total_wins = wins * avg_win if wins > 0 else 0
        total_losses = abs(losses * avg_loss) if losses > 0 else 0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else 0

        return {
            'period_days': days,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'total_pnl': round(total_pnl, 2),
            'best_trade': round(best_trade, 2),
            'worst_trade': round(worst_trade, 2),
            'profit_factor': round(profit_factor, 2)
        }

    def calculate_monthly_return(self, account_id: int = 3) -> Dict:
        """Calculate monthly return percentage"""
        # Get starting balance (30 days ago approximate)
        account_info = self.get_account_info(account_id)
        current_balance = account_info.get('balance', 0)
        profit_month = account_info.get('profit_month', 0)

        # Starting balance = current - profit
        starting_balance = current_balance - profit_month

        if starting_balance <= 0:
            return {}

        monthly_return = (profit_month / starting_balance * 100)

        # Get performance for last 7, 14, 30 days
        perf_7d = self.get_performance_metrics(account_id, 7)
        perf_14d = self.get_performance_metrics(account_id, 14)
        perf_30d = self.get_performance_metrics(account_id, 30)

        return {
            'current_balance': current_balance,
            'starting_balance': starting_balance,
            'profit_month': profit_month,
            'monthly_return_pct': round(monthly_return, 2),
            'performance_7d': perf_7d,
            'performance_14d': perf_14d,
            'performance_30d': perf_30d
        }

    def project_compound_growth(
        self,
        starting_balance: float,
        monthly_return_pct: float,
        monthly_deposit: float,
        months: int
    ) -> List[Dict]:
        """Project compound growth over time"""
        projections = []
        balance = starting_balance
        total_invested = starting_balance

        for month in range(1, months + 1):
            # Apply monthly return
            profit = balance * (monthly_return_pct / 100)
            balance += profit

            # Add monthly deposit
            balance += monthly_deposit
            total_invested += monthly_deposit

            weekly_gain = (profit + monthly_deposit * (monthly_return_pct / 100)) / 4

            projections.append({
                'month': month,
                'balance': round(balance, 2),
                'profit': round(profit, 2),
                'weekly_gain': round(weekly_gain, 2),
                'total_invested': round(total_invested, 2),
                'total_profit': round(balance - total_invested, 2),
                'roi_pct': round((balance - total_invested) / total_invested * 100, 1)
            })

        return projections

    def get_deposit_recommendation(self, account_id: int = 3) -> Dict:
        """Determine if additional deposits are recommended"""
        metrics = self.calculate_monthly_return(account_id)

        if not metrics:
            return {
                'recommendation': 'WAIT',
                'reason': 'Insufficient data to calculate performance',
                'confidence': 'LOW'
            }

        monthly_return = metrics.get('monthly_return_pct', 0)
        perf_30d = metrics.get('performance_30d', {})
        win_rate = perf_30d.get('win_rate', 0)
        profit_factor = perf_30d.get('profit_factor', 0)
        total_trades = perf_30d.get('total_trades', 0)

        # Decision criteria
        if total_trades < 50:
            return {
                'recommendation': 'WAIT',
                'reason': f'Not enough trades yet ({total_trades}/50 minimum)',
                'confidence': 'LOW',
                'metrics': metrics
            }

        if monthly_return >= 5.0 and win_rate >= 70 and profit_factor >= 1.5:
            return {
                'recommendation': 'DEPOSIT NOW',
                'reason': f'Strong performance: {monthly_return}% monthly, {win_rate}% WR, {profit_factor} PF',
                'confidence': 'HIGH',
                'suggested_amount': '300-500 EUR/month',
                'metrics': metrics
            }

        elif monthly_return >= 3.0 and win_rate >= 65 and profit_factor >= 1.2:
            return {
                'recommendation': 'DEPOSIT MODERATE',
                'reason': f'Good performance: {monthly_return}% monthly, {win_rate}% WR',
                'confidence': 'MEDIUM',
                'suggested_amount': '200-300 EUR/month',
                'metrics': metrics
            }

        elif monthly_return >= 1.0 and win_rate >= 60:
            return {
                'recommendation': 'DEPOSIT SMALL',
                'reason': f'Positive but weak: {monthly_return}% monthly, {win_rate}% WR',
                'confidence': 'LOW',
                'suggested_amount': '100-200 EUR/month',
                'metrics': metrics
            }

        else:
            return {
                'recommendation': 'DO NOT DEPOSIT',
                'reason': f'System not profitable: {monthly_return}% monthly, {win_rate}% WR',
                'confidence': 'HIGH',
                'suggested_amount': '0 EUR - Wait for improvement',
                'metrics': metrics
            }

    def generate_dashboard_report(self, account_id: int = 3) -> str:
        """Generate comprehensive dashboard report"""
        account_info = self.get_account_info(account_id)
        recommendation = self.get_deposit_recommendation(account_id)
        metrics = recommendation.get('metrics', {})

        # Get projections with different scenarios
        current_balance = account_info.get('balance', 726)
        monthly_return = metrics.get('monthly_return_pct', 3.0)

        # Conservative projection (3% monthly)
        proj_conservative = self.project_compound_growth(current_balance, 3.0, 200, 24)

        # Moderate projection (5% monthly)
        proj_moderate = self.project_compound_growth(current_balance, 5.0, 300, 24)

        # Optimistic projection (7% monthly)
        proj_optimistic = self.project_compound_growth(current_balance, 7.0, 300, 24)

        # Build report
        report = []
        report.append("=" * 80)
        report.append("TRADING BOT PERFORMANCE & GROWTH DASHBOARD")
        report.append("=" * 80)
        report.append("")

        # Account Info
        report.append("📊 CURRENT ACCOUNT STATUS")
        report.append("-" * 80)
        report.append(f"MT5 Account:      {account_info.get('mt5_account', 'N/A')}")
        report.append(f"Balance:          {account_info.get('balance', 0):.2f} EUR")
        report.append(f"Equity:           {account_info.get('equity', 0):.2f} EUR")
        report.append(f"Free Margin:      {account_info.get('free_margin', 0):.2f} EUR")
        report.append(f"Profit Today:     {account_info.get('profit_today', 0):.2f} EUR")
        report.append(f"Profit Week:      {account_info.get('profit_week', 0):.2f} EUR")
        report.append(f"Profit Month:     {account_info.get('profit_month', 0):.2f} EUR")
        report.append(f"Last Update:      {account_info.get('last_update', 'N/A')}")
        report.append("")

        # Performance Metrics
        if metrics:
            perf_30d = metrics.get('performance_30d', {})
            report.append("📈 PERFORMANCE METRICS (Last 30 Days)")
            report.append("-" * 80)
            report.append(f"Monthly Return:   {metrics.get('monthly_return_pct', 0):.2f}%")
            report.append(f"Total Trades:     {perf_30d.get('total_trades', 0)}")
            report.append(f"Win Rate:         {perf_30d.get('win_rate', 0):.1f}%")
            report.append(f"Wins/Losses:      {perf_30d.get('wins', 0)}/{perf_30d.get('losses', 0)}")
            report.append(f"Avg Win:          {perf_30d.get('avg_win', 0):.2f} EUR")
            report.append(f"Avg Loss:         {perf_30d.get('avg_loss', 0):.2f} EUR")
            report.append(f"Profit Factor:    {perf_30d.get('profit_factor', 0):.2f}")
            report.append(f"Best Trade:       {perf_30d.get('best_trade', 0):.2f} EUR")
            report.append(f"Worst Trade:      {perf_30d.get('worst_trade', 0):.2f} EUR")
            report.append(f"Total P/L:        {perf_30d.get('total_pnl', 0):.2f} EUR")
            report.append("")

        # Deposit Recommendation
        report.append("💰 DEPOSIT RECOMMENDATION")
        report.append("-" * 80)
        report.append(f"Recommendation:   {recommendation.get('recommendation', 'N/A')}")
        report.append(f"Confidence:       {recommendation.get('confidence', 'N/A')}")
        report.append(f"Suggested Amount: {recommendation.get('suggested_amount', 'N/A')}")
        report.append(f"Reason:           {recommendation.get('reason', 'N/A')}")
        report.append("")

        # Compound Growth Projections
        report.append("🚀 COMPOUND GROWTH PROJECTIONS (24 Months)")
        report.append("=" * 80)
        report.append("")

        # Conservative Scenario
        report.append("Scenario 1: CONSERVATIVE (3% monthly + 200 EUR/month)")
        report.append("-" * 80)
        for i in [5, 11, 17, 23]:  # 6, 12, 18, 24 months
            proj = proj_conservative[i]
            report.append(
                f"Month {proj['month']:2d}: {proj['balance']:10,.2f} EUR  "
                f"(~{proj['weekly_gain']:6.2f} EUR/week, "
                f"ROI: {proj['roi_pct']:6.1f}%)"
            )
        report.append("")

        # Moderate Scenario
        report.append("Scenario 2: MODERATE (5% monthly + 300 EUR/month)")
        report.append("-" * 80)
        for i in [5, 11, 17, 23]:
            proj = proj_moderate[i]
            report.append(
                f"Month {proj['month']:2d}: {proj['balance']:10,.2f} EUR  "
                f"(~{proj['weekly_gain']:6.2f} EUR/week, "
                f"ROI: {proj['roi_pct']:6.1f}%)"
            )
        report.append("")

        # Optimistic Scenario
        report.append("Scenario 3: OPTIMISTIC (7% monthly + 300 EUR/month)")
        report.append("-" * 80)
        for i in [5, 11, 17, 23]:
            proj = proj_optimistic[i]
            report.append(
                f"Month {proj['month']:2d}: {proj['balance']:10,.2f} EUR  "
                f"(~{proj['weekly_gain']:6.2f} EUR/week, "
                f"ROI: {proj['roi_pct']:6.1f}%)"
            )
        report.append("")

        # Time to 500 EUR/week
        report.append("⏰ TIME TO REACH 500 EUR/WEEK")
        report.append("-" * 80)

        target_monthly = 500 * 4  # 500 EUR/week = 2000 EUR/month

        for scenario_name, projections in [
            ("Conservative (3% + 200 EUR/month)", proj_conservative),
            ("Moderate (5% + 300 EUR/month)", proj_moderate),
            ("Optimistic (7% + 300 EUR/month)", proj_optimistic)
        ]:
            months_to_target = None
            for proj in projections:
                # Calculate monthly gain (profit from balance growth)
                if proj['month'] == 1:
                    continue
                monthly_gain = projections[proj['month']-1]['balance'] * (
                    3.0/100 if 'Conservative' in scenario_name else
                    5.0/100 if 'Moderate' in scenario_name else
                    7.0/100
                )
                if monthly_gain >= target_monthly:
                    months_to_target = proj['month']
                    break

            if months_to_target:
                report.append(f"{scenario_name:45s}: ~{months_to_target} months")
            else:
                report.append(f"{scenario_name:45s}: >24 months")

        report.append("")
        report.append("=" * 80)
        report.append(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 80)

        return "\n".join(report)

    def generate_telegram_summary(self, account_id: int = 3) -> str:
        """Generate compact Telegram summary message"""
        account_info = self.get_account_info(account_id)
        recommendation = self.get_deposit_recommendation(account_id)
        metrics = recommendation.get('metrics', {})
        perf_30d = metrics.get('performance_30d', {})

        # Get recommendation emoji
        rec = recommendation.get('recommendation', 'WAIT')
        if 'DEPOSIT NOW' in rec:
            rec_emoji = '✅'
        elif 'DEPOSIT' in rec and 'NOT' not in rec:
            rec_emoji = '💰'
        elif 'DO NOT DEPOSIT' in rec:
            rec_emoji = '⛔'
        else:
            rec_emoji = '⏳'

        # Profit emoji
        monthly_return = metrics.get('monthly_return_pct', 0)
        if monthly_return >= 5:
            profit_emoji = '🚀'
        elif monthly_return >= 3:
            profit_emoji = '📈'
        elif monthly_return > 0:
            profit_emoji = '➕'
        elif monthly_return == 0:
            profit_emoji = '➖'
        else:
            profit_emoji = '📉'

        message = f"""📊 <b>Daily Performance Report</b>
{datetime.now().strftime('%d.%m.%Y')}

💰 <b>Balance:</b> €{account_info.get('balance', 0):.2f}
{profit_emoji} <b>Monthly Return:</b> {monthly_return:.1f}%

📈 <b>Performance (30 Days):</b>
• Win Rate: {perf_30d.get('win_rate', 0):.1f}% ({perf_30d.get('wins', 0)}W/{perf_30d.get('losses', 0)}L)
• Profit Factor: {perf_30d.get('profit_factor', 0):.2f}
• Total P/L: €{perf_30d.get('total_pnl', 0):.2f}
• Avg Win: €{perf_30d.get('avg_win', 0):.2f} | Avg Loss: €{perf_30d.get('avg_loss', 0):.2f}

{rec_emoji} <b>Deposit Recommendation:</b>
{recommendation.get('recommendation', 'N/A')}
<i>{recommendation.get('reason', 'N/A')}</i>
Amount: {recommendation.get('suggested_amount', 'N/A')}

🎯 <b>Projections (24 months):</b>
Conservative (3%+200): €{self.project_compound_growth(account_info.get('balance', 726), 3.0, 200, 24)[-1]['balance']:,.0f}
Moderate (5%+300): €{self.project_compound_growth(account_info.get('balance', 726), 5.0, 300, 24)[-1]['balance']:,.0f}
Optimistic (7%+300): €{self.project_compound_growth(account_info.get('balance', 726), 7.0, 300, 24)[-1]['balance']:,.0f}

<i>Full report: /app/logs/performance_dashboard.txt</i>
"""
        return message

    def send_telegram_report(self, account_id: int = 3) -> bool:
        """Send performance report via Telegram"""
        if not TelegramNotifier:
            print("⚠️ TelegramNotifier not available")
            return False

        notifier = TelegramNotifier()
        if not notifier.enabled:
            print("⚠️ Telegram notifications not configured")
            return False

        message = self.generate_telegram_summary(account_id)
        success = notifier.send_message(message, silent=True)

        if success:
            print("✅ Telegram report sent successfully")
        else:
            print("❌ Failed to send Telegram report")

        return success

    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Trading Performance Monitor')
    parser.add_argument('--telegram', action='store_true', help='Send report via Telegram')
    parser.add_argument('--output', type=str, help='Output file path')
    args = parser.parse_args()

    monitor = PerformanceMonitor()
    try:
        # Generate full report
        report = monitor.generate_dashboard_report()
        print(report)

        # Save to file if requested
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            print(f"\n✅ Report saved to: {args.output}")

        # Send via Telegram if requested
        if args.telegram:
            monitor.send_telegram_report()

    finally:
        monitor.close()


if __name__ == "__main__":
    main()
