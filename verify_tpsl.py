#!/usr/bin/env python3
"""
TP/SL Verification Script
Checks if all open trades have valid TP/SL set
"""

import os
import sys
from sqlalchemy import create_engine, text
from datetime import datetime

# Database connection (using Docker network)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@ngtradingbot_db:5432/ngtradingbot')

def check_trades_tpsl():
    """Check all open trades for TP/SL"""
    engine = create_engine(DATABASE_URL)

    with engine.connect() as conn:
        # Get all open trades
        result = conn.execute(text("""
            SELECT
                id,
                ticket,
                symbol,
                direction,
                open_price,
                tp,
                sl,
                open_time,
                status,
                source
            FROM trades
            WHERE status = 'open'
            ORDER BY open_time DESC
        """))

        trades = result.fetchall()

        if not trades:
            print("✅ No open trades found")
            return True

        print(f"\n{'='*80}")
        print(f"OPEN TRADES TP/SL VERIFICATION")
        print(f"{'='*80}\n")
        print(f"Found {len(trades)} open trade(s)\n")

        all_valid = True

        for trade in trades:
            ticket = trade.ticket
            symbol = trade.symbol
            direction = trade.direction
            open_price = float(trade.open_price) if trade.open_price else 0
            tp = float(trade.tp) if trade.tp else 0
            sl = float(trade.sl) if trade.sl else 0
            open_time = trade.open_time
            source = trade.source

            # Check if TP/SL are set
            has_tp = tp != 0
            has_sl = sl != 0

            status_icon = "✅" if (has_tp and has_sl) else "❌"

            print(f"{status_icon} Trade #{ticket} - {symbol} {direction}")
            print(f"   Opened: {open_time} ({source})")
            print(f"   Entry:  {open_price:.5f}")
            print(f"   TP:     {tp:.5f if has_tp else 'NOT SET'}")
            print(f"   SL:     {sl:.5f if has_sl else 'NOT SET'}")

            if not has_tp or not has_sl:
                all_valid = False
                print(f"   ⚠️  WARNING: Missing TP/SL!")

                # Suggest values based on 2:1 RR
                if direction.upper() == 'BUY':
                    suggested_sl = open_price * 0.995  # 0.5% below
                    suggested_tp = open_price * 1.010  # 1.0% above (2:1)
                else:
                    suggested_sl = open_price * 1.005  # 0.5% above
                    suggested_tp = open_price * 0.990  # 1.0% below (2:1)

                print(f"   💡 Suggested SL: {suggested_sl:.5f}")
                print(f"   💡 Suggested TP: {suggested_tp:.5f}")

            print()

        print(f"{'='*80}")

        if all_valid:
            print("✅ ALL TRADES HAVE VALID TP/SL SET")
            return True
        else:
            print("❌ SOME TRADES ARE MISSING TP/SL!")
            print("\n⚠️  Action required:")
            print("   1. Set TP/SL manually in MT5")
            print("   2. Or run: python3 fix_missing_tpsl.py")
            return False


def main():
    try:
        all_good = check_trades_tpsl()
        sys.exit(0 if all_good else 1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()
