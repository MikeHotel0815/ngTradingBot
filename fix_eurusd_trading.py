#!/usr/bin/env python3
"""
Fix EURUSD Auto-Trading
Identifies and fixes why EURUSD signals are not being traded
"""

import os
import sys
from database import SessionLocal
from sqlalchemy import text
from datetime import datetime

def main():
    db = SessionLocal()
    fixes_applied = []
    issues_found = []

    print("=" * 80)
    print("🔧 EURUSD AUTO-TRADING FIX SCRIPT")
    print("=" * 80)
    print()

    try:
        # ========================================================================
        # CHECK 1: Global Auto-Trading Enabled?
        # ========================================================================
        print("📋 CHECK 1: Global Auto-Trading Status")
        print("-" * 80)

        result = db.execute(text(
            "SELECT autotrade_enabled, autotrade_risk_profile, autotrade_min_confidence FROM global_settings LIMIT 1"
        )).fetchone()

        if result:
            enabled, risk_profile, min_conf = result
            print(f"✓ Global Settings found")
            print(f"  - Auto-Trading Enabled: {enabled}")
            print(f"  - Risk Profile: {risk_profile or 'normal'}")
            print(f"  - Min Confidence: {min_conf or 50}%")

            if not enabled:
                issues_found.append("Global auto-trading is DISABLED")
                print(f"\n❌ PROBLEM: Auto-Trading is globally disabled!")
                print(f"🔧 FIXING: Enabling auto-trading...")

                db.execute(text("UPDATE global_settings SET autotrade_enabled = TRUE"))
                db.commit()
                fixes_applied.append("Enabled global auto-trading")
                print(f"✅ FIXED: Auto-trading enabled globally")
        else:
            print("⚠️  No global settings found - creating defaults...")
            issues_found.append("No global settings")

            db.execute(text("""
                INSERT INTO global_settings (autotrade_enabled, autotrade_risk_profile, autotrade_min_confidence)
                VALUES (TRUE, 'normal', 50.0)
            """))
            db.commit()
            fixes_applied.append("Created global settings with auto-trading enabled")
            print("✅ Created global settings with auto-trading ENABLED")

        print()

        # ========================================================================
        # CHECK 2: EURUSD Symbol Configuration
        # ========================================================================
        print("📋 CHECK 2: EURUSD Symbol Configuration")
        print("-" * 80)

        # Check if symbol_trading_config table exists
        tables = db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE '%symbol%'"
        )).fetchall()

        table_names = [t[0] for t in tables]
        print(f"✓ Symbol tables found: {', '.join(table_names)}")

        # Try symbol_trading_config
        if 'symbol_trading_config' in table_names:
            result = db.execute(text(
                "SELECT symbol, enabled, autotrade_enabled, max_open_positions FROM symbol_trading_config WHERE symbol = 'EURUSD'"
            )).fetchone()

            if result:
                symbol, enabled, autotrade, max_pos = result
                print(f"✓ EURUSD config found in symbol_trading_config")
                print(f"  - Enabled: {enabled}")
                print(f"  - Autotrade Enabled: {autotrade}")
                print(f"  - Max Open Positions: {max_pos}")

                if not enabled:
                    issues_found.append("EURUSD is disabled in symbol_trading_config")
                    print(f"\n❌ PROBLEM: EURUSD is disabled!")
                    print(f"🔧 FIXING: Enabling EURUSD...")

                    db.execute(text("UPDATE symbol_trading_config SET enabled = TRUE WHERE symbol = 'EURUSD'"))
                    db.commit()
                    fixes_applied.append("Enabled EURUSD in symbol_trading_config")
                    print(f"✅ FIXED: EURUSD enabled")

                if not autotrade:
                    issues_found.append("EURUSD autotrade is disabled")
                    print(f"\n❌ PROBLEM: EURUSD autotrade is disabled!")
                    print(f"🔧 FIXING: Enabling EURUSD autotrade...")

                    db.execute(text("UPDATE symbol_trading_config SET autotrade_enabled = TRUE WHERE symbol = 'EURUSD'"))
                    db.commit()
                    fixes_applied.append("Enabled EURUSD autotrade")
                    print(f"✅ FIXED: EURUSD autotrade enabled")

            else:
                issues_found.append("EURUSD not found in symbol_trading_config")
                print(f"⚠️  EURUSD not in symbol_trading_config - creating entry...")

                db.execute(text("""
                    INSERT INTO symbol_trading_config (symbol, enabled, autotrade_enabled, max_open_positions)
                    VALUES ('EURUSD', TRUE, TRUE, 5)
                    ON CONFLICT (symbol) DO UPDATE SET enabled = TRUE, autotrade_enabled = TRUE
                """))
                db.commit()
                fixes_applied.append("Created EURUSD entry in symbol_trading_config")
                print(f"✅ Created EURUSD configuration with autotrade ENABLED")

        print()

        # ========================================================================
        # CHECK 3: Recent EURUSD Signals
        # ========================================================================
        print("📋 CHECK 3: Recent EURUSD Signals")
        print("-" * 80)

        signals = db.execute(text("""
            SELECT id, generated_at, signal_type, confidence, entry_price, sl_price, tp_price, status, executed
            FROM trading_signals
            WHERE symbol = 'EURUSD'
              AND confidence >= 70
              AND generated_at >= NOW() - INTERVAL '12 hours'
            ORDER BY generated_at DESC
            LIMIT 5
        """)).fetchall()

        if signals:
            print(f"✓ Found {len(signals)} high-confidence EURUSD signals (70%+, last 12h):")
            for sig in signals:
                sig_id, gen_at, sig_type, conf, entry, sl, tp, status, executed = sig
                print(f"\n  Signal #{sig_id}:")
                print(f"    - Time: {gen_at}")
                print(f"    - Type: {sig_type}, Confidence: {conf}%")
                print(f"    - Entry: {entry}, SL: {sl}, TP: {tp}")
                print(f"    - Status: {status}, Executed: {executed}")

                # Check if signal has all required fields
                if not entry or not sl or not tp:
                    issues_found.append(f"Signal #{sig_id} missing entry/SL/TP")
                    print(f"    ❌ PROBLEM: Missing entry/SL/TP prices!")

                if not executed and status == 'pending':
                    issues_found.append(f"Signal #{sig_id} not executed despite being pending")
                    print(f"    ⚠️  Signal is pending but not executed")
        else:
            print(f"⚠️  No high-confidence EURUSD signals found in last 12 hours")
            print(f"    This might explain why no trades were opened")

        print()

        # ========================================================================
        # CHECK 4: Open EURUSD Trades
        # ========================================================================
        print("📋 CHECK 4: Open EURUSD Trades")
        print("-" * 80)

        open_count = db.execute(text(
            "SELECT COUNT(*) FROM trades WHERE symbol = 'EURUSD' AND status = 'open'"
        )).fetchone()[0]

        print(f"✓ Open EURUSD trades: {open_count}")

        if open_count > 0:
            trades = db.execute(text("""
                SELECT ticket, direction, volume, entry_price, current_profit
                FROM trades
                WHERE symbol = 'EURUSD' AND status = 'open'
                LIMIT 5
            """)).fetchall()

            for trade in trades:
                ticket, direction, volume, entry, profit = trade
                print(f"  - Ticket #{ticket}: {direction} {volume} lots @ {entry}, P/L: ${profit}")

        print()

        # ========================================================================
        # SUMMARY
        # ========================================================================
        print("=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)

        if issues_found:
            print(f"\n❌ Issues Found ({len(issues_found)}):")
            for i, issue in enumerate(issues_found, 1):
                print(f"   {i}. {issue}")
        else:
            print(f"\n✅ No configuration issues found!")

        if fixes_applied:
            print(f"\n🔧 Fixes Applied ({len(fixes_applied)}):")
            for i, fix in enumerate(fixes_applied, 1):
                print(f"   {i}. {fix}")

            print(f"\n✅ EURUSD auto-trading should now be ENABLED!")
            print(f"\n🔄 Please restart the workers container for changes to take effect:")
            print(f"   docker restart ngtradingbot_workers")
        else:
            print(f"\n✓ No fixes were needed")

            if not issues_found:
                print(f"\n🤔 Configuration looks correct but signals not trading?")
                print(f"   Possible reasons:")
                print(f"   - Check auto_trader.py logs for rejection reasons")
                print(f"   - Verify signal has valid entry/SL/TP prices")
                print(f"   - Check if max open positions limit reached")
                print(f"   - Check spread validation")
                print(f"   - Check dynamic confidence threshold")

        print()
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()

    return 0

if __name__ == '__main__':
    sys.exit(main())
