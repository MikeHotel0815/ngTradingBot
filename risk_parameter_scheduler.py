#!/usr/bin/env python3
"""
Risk Parameter Scheduler - Automatically updates risk parameters

Runs periodically to adjust:
1. SL Limits (daily)
2. R:R Ratios (weekly)
3. Position sizes (based on account growth)

This ensures risk is ALWAYS appropriate for current account state.
"""

import logging
import time
from datetime import datetime, timedelta
from database import get_db
from dynamic_risk_manager import (
    update_sl_enforcement_limits,
    update_smart_tpsl_ratios,
    get_risk_manager
)
from models import Account
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RiskParameterScheduler:
    """Schedules automatic risk parameter updates"""

    def __init__(self, account_id: int, risk_profile: str = 'moderate'):
        """
        Initialize scheduler

        Args:
            account_id: Account ID
            risk_profile: 'conservative', 'moderate', 'aggressive'
        """
        self.account_id = account_id
        self.risk_profile = risk_profile
        self.last_daily_update = None
        self.last_weekly_update = None

        # Update intervals
        self.daily_update_interval = timedelta(days=1)
        self.weekly_update_interval = timedelta(days=7)

    def should_run_daily_update(self) -> bool:
        """Check if daily update should run"""
        if not self.last_daily_update:
            return True

        return datetime.utcnow() - self.last_daily_update >= self.daily_update_interval

    def should_run_weekly_update(self) -> bool:
        """Check if weekly update should run"""
        if not self.last_weekly_update:
            return True

        return datetime.utcnow() - self.last_weekly_update >= self.weekly_update_interval

    def run_daily_update(self):
        """
        Daily update: SL Limits based on account balance
        """
        logger.info("=" * 70)
        logger.info("DAILY RISK PARAMETER UPDATE")
        logger.info("=" * 70)

        db = next(get_db())
        try:
            risk_manager = get_risk_manager(self.account_id, self.risk_profile)

            # Get current account state
            current_balance, initial_balance = risk_manager._get_account_info(db)
            growth_factor = risk_manager.get_account_growth_factor(db)
            performance_factor = risk_manager.get_recent_performance_factor(db, days=7)

            logger.info(f"📊 Account State:")
            logger.info(f"   Balance: ${current_balance:.2f} (Initial: ${initial_balance:.2f})")
            logger.info(f"   Growth Factor: {growth_factor:.2f}x")
            logger.info(f"   Performance Factor (7d): {performance_factor:.2f}x")

            # Check daily loss limit
            is_exceeded, daily_loss, limit = risk_manager.check_daily_loss_limit(db)
            if is_exceeded:
                logger.warning(f"⚠️  DAILY LOSS LIMIT EXCEEDED: ${abs(daily_loss):.2f} / ${limit:.2f}")
            else:
                logger.info(f"✅ Daily Loss OK: ${daily_loss:+.2f} / ${limit:.2f} limit")

            # Update SL Limits
            update_sl_enforcement_limits(db, self.account_id, self.risk_profile)

            # Get updated limits for logging
            dynamic_limits = risk_manager.get_dynamic_sl_limits(db)
            logger.info(f"✅ SL Limits Updated:")
            for symbol in ['XAUUSD', 'AUDUSD', 'BTCUSD', 'US500.c']:
                logger.info(f"   {symbol:10}: ${dynamic_limits.get(symbol, 0):.2f}")

            self.last_daily_update = datetime.utcnow()

        except Exception as e:
            logger.error(f"❌ Error in daily update: {e}", exc_info=True)
        finally:
            db.close()

    def run_weekly_update(self):
        """
        Weekly update: R:R Ratios based on recent performance
        """
        logger.info("=" * 70)
        logger.info("WEEKLY RISK PARAMETER UPDATE")
        logger.info("=" * 70)

        db = next(get_db())
        try:
            risk_manager = get_risk_manager(self.account_id, self.risk_profile)

            # Get performance metrics
            performance_factor = risk_manager.get_recent_performance_factor(db, days=7)

            logger.info(f"📈 Performance Review (7 days):")
            logger.info(f"   Performance Factor: {performance_factor:.2f}x")

            if performance_factor > 1.2:
                logger.info("   Status: 🟢 EXCELLENT - Scaling risk UP")
            elif performance_factor > 1.0:
                logger.info("   Status: ✅ GOOD - Maintaining risk")
            elif performance_factor > 0.8:
                logger.info("   Status: ⚠️  SUBPAR - Scaling risk DOWN slightly")
            else:
                logger.info("   Status: 🔴 POOR - Scaling risk DOWN significantly")

            # Update R:R Ratios
            update_smart_tpsl_ratios(db, self.account_id, self.risk_profile)

            # Get updated ratios for logging
            dynamic_ratios = risk_manager.get_dynamic_rr_ratios(db)
            logger.info(f"✅ R:R Ratios Updated:")

            forex_config = dynamic_ratios['FOREX_MAJOR']
            forex_rr = forex_config['atr_tp_multiplier'] / forex_config['atr_sl_multiplier']
            logger.info(
                f"   FOREX: TP={forex_config['atr_tp_multiplier']:.2f}x, "
                f"SL={forex_config['atr_sl_multiplier']:.2f}x (R:R {forex_rr:.2f}:1)"
            )

            metals_config = dynamic_ratios['METALS']
            metals_rr = metals_config['atr_tp_multiplier'] / metals_config['atr_sl_multiplier']
            logger.info(
                f"   METALS: TP={metals_config['atr_tp_multiplier']:.2f}x, "
                f"SL={metals_config['atr_sl_multiplier']:.2f}x (R:R {metals_rr:.2f}:1)"
            )

            self.last_weekly_update = datetime.utcnow()

            # Calculate 30-day performance for comprehensive report
            result = db.execute(text("""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) as total_profit,
                    SUM(CASE WHEN profit < 0 THEN profit ELSE 0 END) as total_loss,
                    AVG(profit) as avg_pnl
                FROM trades
                WHERE account_id = :account_id
                    AND created_at >= NOW() - INTERVAL '30 days'
                    AND status = 'closed'
            """), {'account_id': self.account_id}).fetchone()

            if result and result.total_trades > 0:
                win_rate = (result.wins / result.total_trades) * 100
                profit_factor = abs(result.total_profit / result.total_loss) if result.total_loss < 0 else 0
                net_pnl = result.total_profit + result.total_loss

                logger.info(f"\n📊 30-Day Performance Summary:")
                logger.info(f"   Trades: {result.total_trades}")
                logger.info(f"   Win Rate: {win_rate:.1f}%")
                logger.info(f"   Profit Factor: {profit_factor:.2f}")
                logger.info(f"   Net P/L: ${net_pnl:+.2f}")
                logger.info(f"   Avg P/L: ${result.avg_pnl:+.2f}")

        except Exception as e:
            logger.error(f"❌ Error in weekly update: {e}", exc_info=True)
        finally:
            db.close()

    def run_once(self):
        """Run both updates once (for manual testing)"""
        logger.info("🚀 Running manual risk parameter update...")
        self.run_daily_update()
        time.sleep(2)
        self.run_weekly_update()
        logger.info("✅ Manual update complete")

    def run(self):
        """Main loop - check and run updates as needed"""
        logger.info(f"🚀 Risk Parameter Scheduler started")
        logger.info(f"   Account ID: {self.account_id}")
        logger.info(f"   Risk Profile: {self.risk_profile}")
        logger.info(f"   Daily updates: Every {self.daily_update_interval}")
        logger.info(f"   Weekly updates: Every {self.weekly_update_interval}")

        # Run initial updates
        self.run_daily_update()
        time.sleep(5)
        self.run_weekly_update()

        # Main loop
        while True:
            try:
                # Check if updates are due
                if self.should_run_daily_update():
                    self.run_daily_update()

                if self.should_run_weekly_update():
                    self.run_weekly_update()

                # Sleep for 1 hour before checking again
                time.sleep(3600)

            except KeyboardInterrupt:
                logger.info("⛔ Scheduler stopped by user")
                break
            except Exception as e:
                logger.error(f"❌ Error in scheduler loop: {e}", exc_info=True)
                time.sleep(60)  # Wait 1 minute before retrying


if __name__ == "__main__":
    import sys

    # Get account ID and risk profile from command line
    account_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    risk_profile = sys.argv[2] if len(sys.argv) > 2 else 'moderate'

    # Validate risk profile
    valid_profiles = ['conservative', 'moderate', 'aggressive']
    if risk_profile not in valid_profiles:
        logger.error(f"Invalid risk profile: {risk_profile}")
        logger.error(f"Valid options: {', '.join(valid_profiles)}")
        sys.exit(1)

    # Check for --once flag (manual test run)
    if '--once' in sys.argv:
        scheduler = RiskParameterScheduler(account_id, risk_profile)
        scheduler.run_once()
    else:
        # Start continuous scheduler
        scheduler = RiskParameterScheduler(account_id, risk_profile)
        scheduler.run()
