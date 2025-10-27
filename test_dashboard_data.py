#!/usr/bin/env python3
"""
Test script to verify dashboard data loading
"""

import urllib.request
import json

BASE_URL = "http://localhost:9905"

def test_endpoint(name, url):
    """Test an API endpoint"""
    try:
        response = urllib.request.urlopen(f"{BASE_URL}{url}")
        data = json.loads(response.read())
        print(f"✅ {name}: OK")
        return data
    except Exception as e:
        print(f"❌ {name}: {e}")
        return None

print("=" * 60)
print("Dashboard Data Test")
print("=" * 60)

# Test all endpoints
status = test_endpoint("Dashboard Status", "/api/dashboard/status")
symbols = test_endpoint("Dashboard Symbols", "/api/dashboard/symbols")
stats = test_endpoint("Statistics", "/api/dashboard/statistics")
info = test_endpoint("System Info", "/api/dashboard/info")

print("\n" + "=" * 60)
print("Data Summary")
print("=" * 60)

if status and 'account' in status:
    acc = status['account']
    print(f"Balance: €{acc.get('balance', 0):.2f}")
    print(f"Equity: €{acc.get('equity', 0):.2f}")
    print(f"Today P&L: €{acc.get('profit_today', 0):.2f}")
    print(f"Account: {acc.get('number', 'N/A')}")
    print(f"Broker: {acc.get('broker', 'N/A')}")

if symbols and 'symbols' in symbols:
    print(f"\nSymbols: {len(symbols['symbols'])}")
    for sym in symbols['symbols'][:5]:
        print(f"  - {sym['symbol']}: {sym.get('bid', 'N/A')} / {sym.get('ask', 'N/A')}")

if stats and 'statistics' in stats:
    today = stats['statistics'].get('today', {})
    print(f"\nToday's Stats:")
    print(f"  Trades: {today.get('total_trades', 0)}")
    print(f"  Win Rate: {today.get('win_rate', 0):.1f}%")
    print(f"  Profit Factor: {today.get('profit_factor', 'N/A')}")

if info and 'info' in info:
    inf = info['info']
    print(f"\nSystem Info:")
    print(f"  DB Size: {inf.get('db_size', 'N/A')}")
    print(f"  Date: {inf.get('date', 'N/A')}")
    print(f"  Time: {inf.get('local_time', 'N/A')}")

print("\n" + "=" * 60)
