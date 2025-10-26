#!/usr/bin/env python3
"""
Quick test script for dashboard components
"""

import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_dashboard_core():
    """Test dashboard core functionality"""
    logger.info("Testing dashboard core...")

    try:
        from monitoring.dashboard_core import DashboardCore

        with DashboardCore() as dashboard:
            # Test Section 1
            logger.info("Testing real-time trading overview...")
            trading = dashboard.get_realtime_trading_overview()
            assert 'symbols' in trading, "Missing 'symbols' in trading overview"
            assert 'total' in trading, "Missing 'total' in trading overview"
            logger.info(f"✅ Trading overview: {len(trading['symbols'])} symbols, {trading['total']['open_positions']} open positions")

            # Test Section 3
            logger.info("Testing risk management status...")
            risk = dashboard.get_risk_management_status()
            assert 'daily_drawdown' in risk, "Missing 'daily_drawdown' in risk status"
            logger.info(f"✅ Risk management: Drawdown €{risk['daily_drawdown']['current']:.2f}, Status: {risk['daily_drawdown']['status']}")

            # Test Section 4
            logger.info("Testing live positions...")
            positions = dashboard.get_live_positions()
            assert 'positions' in positions, "Missing 'positions' in positions data"
            logger.info(f"✅ Live positions: {len(positions['positions'])} open")

            # Test Section 7
            logger.info("Testing system health...")
            health = dashboard.get_system_health()
            assert 'mt5_connection' in health, "Missing 'mt5_connection' in health data"
            logger.info(f"✅ System health: MT5 {'connected' if health['mt5_connection']['connected'] else 'disconnected'}")

            # Test Section 8
            logger.info("Testing performance analytics...")
            perf = dashboard.get_performance_analytics(hours=24)
            assert 'summary' in perf, "Missing 'summary' in performance data"
            logger.info(f"✅ Performance (24h): {perf['summary']['total_trades']} trades, {perf['summary']['win_rate']:.1f}% WR, €{perf['summary']['total_pnl']:.2f}")

            # Test complete dashboard
            logger.info("Testing complete dashboard...")
            complete = dashboard.get_complete_dashboard()
            assert 'section_1_trading_overview' in complete, "Missing section 1"
            assert 'section_8_performance_24h' in complete, "Missing section 8"
            logger.info("✅ Complete dashboard: All sections present")

        logger.info("✅ Dashboard core tests PASSED")
        return True

    except Exception as e:
        logger.error(f"❌ Dashboard core tests FAILED: {e}", exc_info=True)
        return False


def test_terminal_dashboard():
    """Test terminal dashboard (non-interactive)"""
    logger.info("Testing terminal dashboard...")

    try:
        from monitoring.dashboard_terminal import TerminalDashboard

        dashboard = TerminalDashboard()

        # Test format methods
        logger.info("Testing formatting methods...")
        pnl_str = dashboard.format_pnl(12.34)
        status_str = dashboard.format_status('active')

        logger.info("Testing dashboard generation (once)...")
        dashboard.run_once()

        logger.info("✅ Terminal dashboard tests PASSED")
        return True

    except Exception as e:
        logger.error(f"❌ Terminal dashboard tests FAILED: {e}", exc_info=True)
        return False


def test_telegram_dashboard():
    """Test telegram dashboard (report generation only, no sending)"""
    logger.info("Testing Telegram dashboard...")

    try:
        from monitoring.dashboard_telegram import TelegramDashboardReporter

        reporter = TelegramDashboardReporter()

        logger.info("Testing lightweight report generation...")
        lightweight = reporter.generate_lightweight_report()
        assert len(lightweight) > 0, "Lightweight report is empty"
        assert "ngTradingBot" in lightweight, "Missing title in lightweight report"
        logger.info(f"✅ Lightweight report generated ({len(lightweight)} chars)")

        logger.info("Testing full report generation...")
        full = reporter.generate_full_report()
        assert len(full) > 0, "Full report is empty"
        assert "ngTradingBot" in full, "Missing title in full report"
        logger.info(f"✅ Full report generated ({len(full)} chars)")

        logger.info("✅ Telegram dashboard tests PASSED")
        return True

    except Exception as e:
        logger.error(f"❌ Telegram dashboard tests FAILED: {e}", exc_info=True)
        return False


def test_chart_generator():
    """Test chart generator"""
    logger.info("Testing chart generator...")

    try:
        from monitoring.chart_generator import ChartGenerator

        with ChartGenerator() as generator:
            logger.info("Testing win rate chart...")
            fig = generator.generate_winrate_chart(days_back=7)
            assert fig is not None, "Win rate chart is None"
            logger.info("✅ Win rate chart generated")

            logger.info("Testing P&L curve...")
            fig = generator.generate_pnl_curve(days_back=7)
            assert fig is not None, "P&L curve is None"
            logger.info("✅ P&L curve generated")

            logger.info("Testing symbol performance chart...")
            fig = generator.generate_symbol_performance_chart(days_back=7)
            assert fig is not None, "Symbol performance chart is None"
            logger.info("✅ Symbol performance chart generated")

        logger.info("✅ Chart generator tests PASSED")
        return True

    except Exception as e:
        logger.error(f"❌ Chart generator tests FAILED: {e}", exc_info=True)
        return False


def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("ngTradingBot Dashboard Component Tests")
    logger.info("=" * 60)

    results = {}

    results['core'] = test_dashboard_core()
    print()

    results['terminal'] = test_terminal_dashboard()
    print()

    results['telegram'] = test_telegram_dashboard()
    print()

    results['charts'] = test_chart_generator()
    print()

    logger.info("=" * 60)
    logger.info("Test Summary:")
    logger.info("=" * 60)

    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"  {name.upper()}: {status}")

    all_passed = all(results.values())

    if all_passed:
        logger.info("\n🎉 All tests PASSED!")
        sys.exit(0)
    else:
        logger.error("\n❌ Some tests FAILED")
        sys.exit(1)


if __name__ == '__main__':
    main()
