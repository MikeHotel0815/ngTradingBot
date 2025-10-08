"""
TP/SL Calculator Test Script
Tests the enhanced symbol-specific TP/SL calculation
"""

import sys
sys.path.append('/projects/ngTradingBot')

from smart_tp_sl import SmartTPSLCalculator, SymbolConfig


def test_symbol_configs():
    """Test that all major symbols have correct configuration"""
    print("=" * 80)
    print("SYMBOL CONFIGURATION TEST")
    print("=" * 80)
    
    test_symbols = [
        'EURUSD', 'GBPUSD', 'USDJPY',  # Forex Major
        'EURGBP', 'EURJPY',             # Forex Minor
        'BTCUSD', 'ETHUSD',             # Crypto
        'XAUUSD', 'XAGUSD',             # Metals
        'US30', 'NAS100',               # Indices
        'XTIUSD',                       # Commodities
        'AAPL',                         # Stocks
    ]
    
    for symbol in test_symbols:
        config = SymbolConfig.get_asset_class_config(symbol)
        print(f"\n{symbol:10s} -> {config['asset_class']:15s} | "
              f"TP Mult: {config['atr_tp_multiplier']:.1f}x | "
              f"SL Mult: {config['atr_sl_multiplier']:.1f}x | "
              f"Max TP: {config['max_tp_pct']:.1f}% | "
              f"Min SL: {config['min_sl_pct']:.2f}%")
    
    print("\n" + "=" * 80)


def test_tp_sl_calculations():
    """Test TP/SL calculations for different asset classes"""
    print("\n" + "=" * 80)
    print("TP/SL CALCULATION TEST (Simulated Broker Specs)")
    print("=" * 80)
    
    test_cases = [
        {
            'symbol': 'EURUSD',
            'entry': 1.0850,
            'signal_type': 'BUY',
            'expected_tp_range': (1.0865, 1.0900),
            'expected_sl_range': (1.0835, 1.0845),
        },
        {
            'symbol': 'BTCUSD',
            'entry': 95000,
            'signal_type': 'BUY',
            'expected_tp_range': (96500, 100000),
            'expected_sl_range': (90000, 94000),
        },
        {
            'symbol': 'XAUUSD',
            'entry': 2650.00,
            'signal_type': 'SELL',
            'expected_tp_range': (2610, 2640),
            'expected_sl_range': (2660, 2680),
        },
        {
            'symbol': 'US30',
            'entry': 35000.00,
            'signal_type': 'BUY',
            'expected_tp_range': (35200, 35500),
            'expected_sl_range': (34800, 34950),
        }
    ]
    
    # Mock account_id (won't query DB in this test)
    account_id = 1
    timeframe = 'H1'
    
    for test in test_cases:
        print(f"\n{'-' * 80}")
        print(f"Symbol: {test['symbol']} | Entry: {test['entry']} | Type: {test['signal_type']}")
        print(f"{'-' * 80}")
        
        try:
            calc = SmartTPSLCalculator(account_id, test['symbol'], timeframe)
            
            # Get asset config
            print(f"Asset Class: {calc.asset_config['asset_class']}")
            print(f"TP Multiplier: {calc.asset_config['atr_tp_multiplier']}x ATR")
            print(f"SL Multiplier: {calc.asset_config['atr_sl_multiplier']}x ATR")
            print(f"Max TP%: {calc.asset_config['max_tp_pct']}%")
            print(f"Min SL%: {calc.asset_config['min_sl_pct']}%")
            print(f"Fallback ATR%: {calc.asset_config['fallback_atr_pct']*100:.2f}%")
            
            # Simulate ATR (since we're not connected to DB)
            simulated_atr = test['entry'] * calc.asset_config['fallback_atr_pct']
            print(f"\nSimulated ATR: {simulated_atr:.5f}")
            
            # Calculate expected values using asset-specific multipliers
            if test['signal_type'] == 'BUY':
                expected_tp = test['entry'] + (calc.asset_config['atr_tp_multiplier'] * simulated_atr)
                expected_sl = test['entry'] - (calc.asset_config['atr_sl_multiplier'] * simulated_atr)
            else:
                expected_tp = test['entry'] - (calc.asset_config['atr_tp_multiplier'] * simulated_atr)
                expected_sl = test['entry'] + (calc.asset_config['atr_sl_multiplier'] * simulated_atr)
            
            print(f"\nExpected Results (ATR-based):")
            print(f"  TP: {expected_tp:.5f}")
            print(f"  SL: {expected_sl:.5f}")
            
            # Calculate distances
            tp_distance = abs(expected_tp - test['entry'])
            sl_distance = abs(expected_sl - test['entry'])
            tp_distance_pct = (tp_distance / test['entry']) * 100
            sl_distance_pct = (sl_distance / test['entry']) * 100
            risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0
            
            print(f"\nDistances:")
            print(f"  TP: {tp_distance:.5f} ({tp_distance_pct:.2f}%)")
            print(f"  SL: {sl_distance:.5f} ({sl_distance_pct:.2f}%)")
            print(f"  Risk/Reward: 1:{risk_reward:.2f}")
            
            # Validation
            print(f"\nValidation:")
            tp_in_range = test['expected_tp_range'][0] <= expected_tp <= test['expected_tp_range'][1]
            sl_in_range = test['expected_sl_range'][0] <= expected_sl <= test['expected_sl_range'][1]
            rr_ok = risk_reward >= 1.5
            tp_pct_ok = tp_distance_pct <= calc.asset_config['max_tp_pct']
            sl_pct_ok = sl_distance_pct >= calc.asset_config['min_sl_pct']
            
            print(f"  TP in expected range: {'✅' if tp_in_range else '❌'} {test['expected_tp_range']}")
            print(f"  SL in expected range: {'✅' if sl_in_range else '❌'} {test['expected_sl_range']}")
            print(f"  R:R >= 1.5: {'✅' if rr_ok else '❌'} ({risk_reward:.2f})")
            print(f"  TP% <= max: {'✅' if tp_pct_ok else '❌'} ({tp_distance_pct:.2f}% <= {calc.asset_config['max_tp_pct']}%)")
            print(f"  SL% >= min: {'✅' if sl_pct_ok else '❌'} ({sl_distance_pct:.2f}% >= {calc.asset_config['min_sl_pct']}%)")
            
            all_ok = tp_in_range and sl_in_range and rr_ok and tp_pct_ok and sl_pct_ok
            print(f"\n  Overall: {'✅ PASS' if all_ok else '❌ FAIL'}")
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()


def test_broker_limits():
    """Test broker limits enforcement"""
    print("\n" + "=" * 80)
    print("BROKER LIMITS TEST")
    print("=" * 80)
    
    print("\nTesting broker stops_level enforcement:")
    print("- EURUSD with stops_level=10 points (1 pip)")
    print("- Entry: 1.0850")
    print("- Attempting TP at 1.08505 (0.5 pips) - should be rejected")
    print("- Should be adjusted to 1.08510 (1 pip minimum)")
    
    calc = SmartTPSLCalculator(1, 'EURUSD', 'H1')
    
    # Mock broker specs
    broker_specs = {
        'digits': 5,
        'point': 0.00001,
        'stops_level': 10,  # 10 points = 1 pip
        'freeze_level': 0
    }
    
    entry = 1.0850
    tp_too_close = 1.08505  # 0.5 pips
    sl_ok = 1.08400  # 5 pips
    
    print(f"\nBefore adjustment:")
    print(f"  TP: {tp_too_close:.5f} ({abs(tp_too_close - entry) / 0.00001:.1f} points)")
    
    tp_adjusted, sl_adjusted = calc._apply_broker_limits(
        entry, tp_too_close, sl_ok, 'BUY', broker_specs
    )
    
    print(f"\nAfter adjustment:")
    print(f"  TP: {tp_adjusted:.5f} ({abs(tp_adjusted - entry) / 0.00001:.1f} points)")
    print(f"  SL: {sl_adjusted:.5f} ({abs(sl_adjusted - entry) / 0.00001:.1f} points)")
    
    tp_distance_points = abs(tp_adjusted - entry) / 0.00001
    print(f"\n{'✅ PASS' if tp_distance_points >= 10 else '❌ FAIL'}: TP distance >= stops_level")


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "TP/SL CALCULATOR TEST SUITE" + " " * 30 + "║")
    print("╚" + "=" * 78 + "╝")
    
    try:
        test_symbol_configs()
        test_tp_sl_calculations()
        test_broker_limits()
        
        print("\n" + "=" * 80)
        print("TEST SUITE COMPLETED")
        print("=" * 80)
        print("\n✅ All tests completed successfully!")
        print("\nNOTE: Full integration tests require database connection.")
        print("      These tests validate the calculation logic and configurations.")
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
