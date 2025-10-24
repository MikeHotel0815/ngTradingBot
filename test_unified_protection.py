#!/usr/bin/env python3
"""
Test Unified Daily Loss Protection System

Tests:
1. Database model (DailyDrawdownLimit)
2. Protection settings loading
3. API endpoints
"""

import sys
sys.path.insert(0, '/app')

from database import get_db
from daily_drawdown_protection import DailyDrawdownLimit, get_drawdown_protection


def test_database_model():
    """Test that new columns exist in database"""
    print("\n" + "="*60)
    print("TEST 1: Database Model & Columns")
    print("="*60)

    db = next(get_db())
    try:
        limit = db.query(DailyDrawdownLimit).filter_by(account_id=3).first()

        if not limit:
            print("❌ FAIL: No record found for account 3")
            return False

        print(f"✅ Record found for account {limit.account_id}")
        print(f"   - protection_enabled: {limit.protection_enabled}")
        print(f"   - max_daily_loss_percent: {limit.max_daily_loss_percent}%")
        print(f"   - auto_pause_enabled: {limit.auto_pause_enabled}")
        print(f"   - pause_after_consecutive_losses: {limit.pause_after_consecutive_losses}")
        print(f"   - max_total_drawdown_percent: {limit.max_total_drawdown_percent}%")
        print(f"   - circuit_breaker_tripped: {limit.circuit_breaker_tripped}")
        print(f"   - daily_pnl: €{limit.daily_pnl}")

        return True

    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False
    finally:
        db.close()


def test_protection_manager():
    """Test DailyDrawdownProtection class methods"""
    print("\n" + "="*60)
    print("TEST 2: Protection Manager Methods")
    print("="*60)

    try:
        protection = get_drawdown_protection(account_id=3)

        # Test get status
        db = next(get_db())
        try:
            limit = db.query(DailyDrawdownLimit).filter_by(account_id=3).first()
            print(f"✅ Protection instance created for account 3")
            print(f"   - Current settings loaded from DB")

            # Test update config
            result = protection.update_full_config(
                notes="Test run from unified protection test script"
            )

            if result['success']:
                print(f"✅ Config update successful: {result['message']}")
            else:
                print(f"❌ Config update failed: {result['message']}")
                return False

            return True

        finally:
            db.close()

    except Exception as e:
        print(f"❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_auto_trader_loading():
    """Test that auto_trader loads protection settings from DB"""
    print("\n" + "="*60)
    print("TEST 3: Auto-Trader Protection Loading")
    print("="*60)

    try:
        from auto_trader import AutoTrader

        trader = AutoTrader()

        print(f"✅ AutoTrader initialized")
        print(f"   - protection_enabled: {trader.protection_enabled}")
        print(f"   - max_daily_loss_percent: {trader.max_daily_loss_percent}%")
        print(f"   - max_total_drawdown_percent: {trader.max_total_drawdown_percent}%")
        print(f"   - circuit_breaker_tripped: {trader.circuit_breaker_tripped}")
        print(f"   - auto_pause_enabled: {trader.auto_pause_enabled}")

        return True

    except Exception as e:
        print(f"❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🧪 UNIFIED DAILY LOSS PROTECTION SYSTEM TEST")
    print("="*60)

    results = []

    results.append(("Database Model", test_database_model()))
    results.append(("Protection Manager", test_protection_manager()))
    results.append(("AutoTrader Loading", test_auto_trader_loading()))

    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False

    print("="*60)

    if all_passed:
        print("🎉 ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
