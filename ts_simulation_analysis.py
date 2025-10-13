#!/usr/bin/env python3
"""
Trailing Stop Simulation Analysis
Simulates how trades would have performed with TS enabled vs actual manual closes
"""

# Trailing Stop Configuration (from trailing_stop_manager.py)
TS_CONFIG = {
    'breakeven_trigger_percent': 30.0,  # Move to BE at 30% of TP distance
    'partial_trailing_trigger_percent': 50.0,  # Start trailing at 50%
    'aggressive_trailing_trigger_percent': 75.0,  # Aggressive at 75%
    'near_tp_trigger_percent': 90.0,  # Near TP at 90%

    # Symbol-specific settings
    'XAUUSD': {
        'breakeven_trigger_percent': 25.0,
    },
    'DE40.c': {
        # Uses defaults
    },
    'EURUSD': {
        'aggressive_trailing_trigger_percent': 70.0,
    },
    'GBPUSD': {
        # Uses defaults
    }
}

# Real trades data from Monday 13.10.2025
TRADES = [
    {
        'ticket': 16387491,
        'symbol': 'EURUSD',
        'direction': 'BUY',
        'entry': 1.16172,
        'sl_signal': 1.15713,
        'tp_signal': 1.16340,
        'actual_close': 1.16180,
        'actual_profit': 0.07,
        'close_time_min': 1.25,  # 1.25 minutes
        'max_price_after': 1.16300,  # From OHLC analysis
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16387492,
        'symbol': 'GBPUSD',
        'direction': 'BUY',
        'entry': 1.33503,
        'sl_signal': 1.33091,
        'tp_signal': 1.33913,
        'actual_close': 1.33583,
        'actual_profit': 0.69,
        'close_time_min': 54,
        'max_price_after': 1.33664,
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16391130,
        'symbol': 'GBPUSD',
        'direction': 'BUY',
        'entry': 1.33661,
        'sl_signal': 1.33091,
        'tp_signal': 1.33913,
        'actual_close': 1.33206,  # SL HIT
        'actual_profit': -3.93,
        'close_time_min': 115,
        'close_reason': 'SL_HIT'
    },
    {
        'ticket': 16391131,
        'symbol': 'EURUSD',
        'direction': 'BUY',
        'entry': 1.16261,
        'sl_signal': 1.15713,
        'tp_signal': 1.16340,
        'actual_close': 1.15922,  # SL HIT
        'actual_profit': -2.92,
        'close_time_min': 114,
        'close_reason': 'SL_HIT'
    },
    {
        'ticket': 16392069,
        'symbol': 'DE40.c',
        'direction': 'SELL',
        'entry': 24394.20,
        'sl_signal': 24515.70,
        'tp_signal': 24175.40,
        'actual_close': 24278.40,
        'actual_profit': 11.58,
        'close_time_min': 401,  # 6.7 hours
        'max_price_after': 24268.05,  # Could have gotten more
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16396290,
        'symbol': 'DE40.c',
        'direction': 'SELL',
        'entry': 24373.60,
        'sl_signal': 24515.70,
        'tp_signal': 24175.40,
        'actual_close': 24278.30,
        'actual_profit': 9.53,
        'close_time_min': 321,  # 5.35 hours
        'max_price_after': 24268.05,
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16399470,
        'symbol': 'DE40.c',
        'direction': 'BUY',
        'entry': 24361.25,
        'sl_signal': 24254.24,
        'tp_signal': 24456.00,
        'actual_close': 24285.55,  # Manual loss
        'actual_profit': -7.57,
        'close_time_min': 109,
        'max_price_after': 24430.15,  # Would have recovered!
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16399690,
        'symbol': 'DE40.c',
        'direction': 'BUY',
        'entry': 24354.30,
        'sl_signal': 24254.24,
        'tp_signal': 24456.00,
        'actual_close': 24277.10,  # Manual loss
        'actual_profit': -7.72,
        'close_time_min': 192,
        'max_price_after': 24430.15,  # Would have recovered!
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16405194,
        'symbol': 'XAUUSD',
        'direction': 'BUY',
        'entry': 4082.84,
        'sl_signal': 4072.33,
        'tp_signal': 4155.80,
        'actual_close': 4088.73,
        'actual_profit': 5.09,
        'close_time_min': 76,
        'max_price_after': 4116.93,  # Much more potential!
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16410011,
        'symbol': 'GBPUSD',
        'direction': 'SELL',
        'entry': 1.33290,
        'sl_signal': 1.33572,
        'tp_signal': 1.32778,
        'actual_close': 1.33243,
        'actual_profit': 0.41,
        'close_time_min': 31,
        'max_price_after': 1.33196,
        'close_reason': 'MANUAL'
    },
    {
        'ticket': 16410675,
        'symbol': 'EURUSD',
        'direction': 'BUY',
        'entry': 1.15671,
        'sl_signal': 1.15658,
        'tp_signal': 1.15984,
        'actual_close': 1.15717,
        'actual_profit': 0.40,
        'close_time_min': 267,
        'max_price_after': 1.15741,
        'close_reason': 'MANUAL'
    },
]


def simulate_trailing_stop_on_trade(trade):
    """
    Simulate how TS would have behaved on a single trade

    Returns dict with:
    - would_breakeven: If trade would have moved to BE
    - breakeven_price: Calculated BE price
    - would_hit_sl_at_be: If SL would have been hit at BE level
    - estimated_final_profit: Estimated profit with TS enabled
    """
    symbol = trade['symbol']
    direction = trade['direction']
    entry = trade['entry']
    sl = trade['sl_signal']
    tp = trade['tp_signal']

    # Get symbol-specific config
    config = TS_CONFIG.copy()
    if symbol in TS_CONFIG:
        config.update(TS_CONFIG[symbol])

    # Calculate TP distance
    if direction == 'BUY':
        tp_distance = tp - entry
    else:
        tp_distance = entry - tp

    # Calculate breakeven trigger point
    be_trigger_price = None
    be_percent = config['breakeven_trigger_percent']

    if direction == 'BUY':
        be_trigger_price = entry + (tp_distance * be_percent / 100)
        be_sl_price = entry + 0.00020  # Entry + 2 pips spread protection
    else:
        be_trigger_price = entry - (tp_distance * be_percent / 100)
        be_sl_price = entry - 0.00020  # Entry - 2 pips

    # Check if trade would have triggered BE
    would_trigger_be = False
    if 'max_price_after' in trade:
        max_price = trade['max_price_after']
        if direction == 'BUY':
            would_trigger_be = max_price >= be_trigger_price
        else:
            would_trigger_be = max_price <= be_trigger_price

    # Simulate outcome
    result = {
        'ticket': trade['ticket'],
        'symbol': symbol,
        'direction': direction,
        'entry': entry,
        'actual_profit': trade['actual_profit'],
        'actual_close': trade['actual_close'],
        'close_reason': trade['close_reason'],
        'tp_distance': round(tp_distance, 5),
        'be_trigger_percent': be_percent,
        'be_trigger_price': round(be_trigger_price, 5),
        'be_sl_price': round(be_sl_price, 5),
        'would_trigger_be': would_trigger_be,
    }

    # Estimate TS outcome
    if trade['close_reason'] == 'SL_HIT':
        # SL hit - would TS have prevented this?
        if would_trigger_be:
            # TS would have moved SL to BE, limiting loss
            result['ts_outcome'] = 'BE_PROTECTED'
            result['ts_profit'] = 0.0  # Break-even
            result['improvement'] = abs(trade['actual_profit'])  # Loss prevented
        else:
            # TS wouldn't have helped, SL was hit before BE trigger
            result['ts_outcome'] = 'SL_HIT_ANYWAY'
            result['ts_profit'] = trade['actual_profit']
            result['improvement'] = 0.0

    elif trade['close_reason'] == 'MANUAL':
        if trade['actual_profit'] < 0:
            # Manual loss - would TS have helped?
            if would_trigger_be:
                # TS would have moved to BE
                # Check if price went back below BE
                actual_close = trade['actual_close']
                if direction == 'BUY':
                    if actual_close < be_sl_price:
                        # Would have hit BE SL
                        result['ts_outcome'] = 'BE_HIT'
                        result['ts_profit'] = 0.0
                        result['improvement'] = abs(trade['actual_profit'])
                    else:
                        # Still open or would have closed higher
                        result['ts_outcome'] = 'STILL_OPEN'
                        result['ts_profit'] = 0.0  # Unknown, but at least BE
                        result['improvement'] = abs(trade['actual_profit'])
                else:
                    if actual_close > be_sl_price:
                        result['ts_outcome'] = 'BE_HIT'
                        result['ts_profit'] = 0.0
                        result['improvement'] = abs(trade['actual_profit'])
                    else:
                        result['ts_outcome'] = 'STILL_OPEN'
                        result['ts_profit'] = 0.0
                        result['improvement'] = abs(trade['actual_profit'])
            else:
                # TS wouldn't have triggered, same loss
                result['ts_outcome'] = 'NO_HELP'
                result['ts_profit'] = trade['actual_profit']
                result['improvement'] = 0.0

        else:
            # Manual profit - would TS have captured more?
            if would_trigger_be:
                # TS would have been active
                # Estimate: TS would trail and likely capture more
                max_price = trade.get('max_price_after', trade['actual_close'])
                if direction == 'BUY':
                    potential_gain = max_price - entry
                else:
                    potential_gain = entry - max_price

                # Assume TS captures 80% of max potential (conservative)
                result['ts_outcome'] = 'CAPTURED_MORE'
                result['ts_profit'] = potential_gain * 0.8 * 10  # Rough EUR estimate
                result['improvement'] = result['ts_profit'] - trade['actual_profit']
            else:
                # TS not triggered yet, same profit
                result['ts_outcome'] = 'NOT_TRIGGERED'
                result['ts_profit'] = trade['actual_profit']
                result['improvement'] = 0.0

    return result


def main():
    print("=" * 80)
    print("TRAILING STOP SIMULATION ANALYSIS")
    print("=" * 80)
    print()

    results = []
    total_actual_profit = 0
    total_ts_profit = 0
    total_improvement = 0

    for trade in TRADES:
        result = simulate_trailing_stop_on_trade(trade)
        results.append(result)
        total_actual_profit += result['actual_profit']
        total_ts_profit += result.get('ts_profit', result['actual_profit'])
        total_improvement += result.get('improvement', 0)

    # Print individual results
    print("INDIVIDUAL TRADE ANALYSIS:")
    print("-" * 80)

    for r in results:
        print(f"\nTicket {r['ticket']} - {r['symbol']} {r['direction']}")
        print(f"  Entry: {r['entry']:.5f}")
        print(f"  Actual: {r['actual_profit']:.2f} EUR ({r['close_reason']})")
        print(f"  Closed: {r['actual_close']:.5f}")
        print(f"  TP Distance: {r['tp_distance']:.5f}")
        print(f"  BE Trigger: {r['be_trigger_percent']:.0f}% = {r['be_trigger_price']:.5f}")
        print(f"  BE SL: {r['be_sl_price']:.5f}")
        print(f"  Would trigger BE: {'YES' if r['would_trigger_be'] else 'NO'}")
        print(f"  TS Outcome: {r['ts_outcome']}")
        print(f"  TS Profit: {r.get('ts_profit', 0):.2f} EUR")
        print(f"  Improvement: {r.get('improvement', 0):.2f} EUR")

    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("-" * 80)
    print(f"Total Actual Profit: {total_actual_profit:.2f} EUR")
    print(f"Total TS Profit:     {total_ts_profit:.2f} EUR")
    print(f"Total Improvement:   {total_improvement:.2f} EUR")
    print(f"Improvement %:       {(total_improvement / abs(total_actual_profit) * 100) if total_actual_profit != 0 else 0:.1f}%")
    print()

    # Count outcomes
    be_protected = sum(1 for r in results if r.get('ts_outcome') == 'BE_PROTECTED')
    captured_more = sum(1 for r in results if r.get('ts_outcome') == 'CAPTURED_MORE')
    no_help = sum(1 for r in results if r.get('ts_outcome') in ['NO_HELP', 'NOT_TRIGGERED'])

    print(f"Trades protected by BE: {be_protected}")
    print(f"Trades captured more:   {captured_more}")
    print(f"Trades unchanged:       {no_help}")
    print()

    print("=" * 80)
    print("CONCLUSION:")
    print("-" * 80)

    if total_improvement > 5:
        print("✅ Trailing Stop would have SIGNIFICANTLY IMPROVED performance!")
        print(f"   - Prevented {be_protected} losses")
        print(f"   - Captured more profit on {captured_more} trades")
        print(f"   - Net improvement: +{total_improvement:.2f} EUR")
    elif total_improvement > 0:
        print("✅ Trailing Stop would have SLIGHTLY IMPROVED performance")
        print(f"   - Net improvement: +{total_improvement:.2f} EUR")
    elif total_improvement < -5:
        print("❌ Trailing Stop would have WORSENED performance!")
        print(f"   - Net loss: {total_improvement:.2f} EUR")
    else:
        print("⚠️  Trailing Stop would have had MINIMAL IMPACT")
        print(f"   - Net change: {total_improvement:.2f} EUR")

    print()


if __name__ == '__main__':
    main()
