#!/usr/bin/env python3
"""Test backtest signal generation"""

import numpy as np
from datetime import datetime
from database import ScopedSession
from models import OHLCData
from sqlalchemy import and_

# Get historical bars (OHLC is global - no account_id)
db = ScopedSession()
historical_bars = db.query(OHLCData).filter(
    and_(
        OHLCData.symbol == 'BTCUSD',
        OHLCData.timeframe == 'H1',
        OHLCData.timestamp >= '2025-09-28'
    )
).order_by(OHLCData.timestamp.desc()).limit(100).all()

print(f"Found {len(historical_bars)} bars")

if len(historical_bars) >= 50:
    bars = list(reversed(historical_bars))
    closes = np.array([float(bar.close) for bar in bars])

    print(f"\nClose prices (last 10): {closes[-10:]}")

    # Calculate EMA 20
    def calculate_ema(data, period):
        ema = np.zeros_like(data)
        ema[0] = data[0]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        return ema

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)

    print(f"\nEMA20 (last 5): {ema20[-5:]}")
    print(f"EMA50 (last 5): {ema50[-5:]}")
    print(f"\nPrice vs EMAs:")
    print(f"  Close[-1]: {closes[-1]:.2f}")
    print(f"  EMA20[-1]: {ema20[-1]:.2f}")
    print(f"  EMA50[-1]: {ema50[-1]:.2f}")

    if closes[-1] > ema20[-1] and closes[-1] > ema50[-1]:
        print("  → SIGNAL: BUY (Price above both EMAs)")
    elif closes[-1] < ema20[-1] and closes[-1] < ema50[-1]:
        print("  → SIGNAL: SELL (Price below both EMAs)")

    # Calculate RSI
    if len(closes) >= 14:
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            print(f"\nRSI: {rsi:.2f}")

            if rsi < 40:
                print(f"  → SIGNAL: BUY (RSI oversold)")
            elif rsi > 60:
                print(f"  → SIGNAL: SELL (RSI overbought)")

db.close()
