#!/usr/bin/env python3
"""
Analyze trades from the last 24 hours
"""

import sys
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker
from models import Trade, Account
from decimal import Decimal

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db = Session()

# Get trades from last 24 hours
now = datetime.utcnow()
yesterday = now - timedelta(hours=24)

trades = db.query(Trade).filter(
    and_(
        Trade.created_at >= yesterday,
        Trade.status == 'closed'
    )
).order_by(Trade.close_time.desc()).all()

print(f'=== TRADES DER LETZTEN 24 STUNDEN ===')
print(f'Zeitraum: {yesterday.strftime("%Y-%m-%d %H:%M")} bis {now.strftime("%Y-%m-%d %H:%M")} UTC')
print(f'Anzahl Trades: {len(trades)}\n')

if not trades:
    print('⚠️  Keine geschlossenen Trades in den letzten 24 Stunden gefunden.')

    # Check for open trades
    open_trades = db.query(Trade).filter(
        and_(
            Trade.created_at >= yesterday,
            Trade.status == 'open'
        )
    ).all()

    if open_trades:
        print(f'\n📊 Aber {len(open_trades)} offene Trades gefunden:')
        for t in open_trades:
            profit_pips = float(t.pips_captured) if t.pips_captured else 0
            print(f'  • Ticket #{t.ticket}: {t.direction.upper()} {t.symbol} @ {t.open_price} (Offen seit {t.open_time.strftime("%H:%M")} UTC, {profit_pips:+.1f} pips)')
else:
    # Calculate statistics
    winning_trades = [t for t in trades if float(t.profit) > 0]
    losing_trades = [t for t in trades if float(t.profit) < 0]
    breakeven = [t for t in trades if float(t.profit) == 0]

    total_profit = sum(float(t.profit) for t in winning_trades)
    total_loss = sum(float(t.profit) for t in losing_trades)
    net_profit = total_profit + total_loss

    win_rate = len(winning_trades) / len(trades) * 100 if trades else 0

    print(f'📈 PERFORMANCE ÜBERSICHT:')
    print(f'├─ Gewinnende Trades: {len(winning_trades)} ({win_rate:.1f}%)')
    print(f'├─ Verlierende Trades: {len(losing_trades)} ({100-win_rate:.1f}%)')
    print(f'├─ Breakeven: {len(breakeven)}')
    print(f'├─ Gewinn: +${total_profit:.2f}')
    print(f'├─ Verlust: ${total_loss:.2f}')
    print(f'└─ Netto P/L: ${net_profit:+.2f}')

    # Group by symbol
    symbols = {}
    for t in trades:
        if t.symbol not in symbols:
            symbols[t.symbol] = {'trades': [], 'profit': 0}
        symbols[t.symbol]['trades'].append(t)
        symbols[t.symbol]['profit'] += float(t.profit)

    print(f'\n💹 PERFORMANCE PRO SYMBOL:')
    for symbol, data in sorted(symbols.items(), key=lambda x: x[1]['profit'], reverse=True):
        sym_wins = len([t for t in data['trades'] if float(t.profit) > 0])
        sym_total = len(data['trades'])
        sym_wr = sym_wins / sym_total * 100 if sym_total > 0 else 0
        print(f'  • {symbol}: {sym_total} Trades, {sym_wr:.0f}% WR, ${data["profit"]:+.2f}')

    print(f'\n📋 TRADE DETAILS:')
    for i, t in enumerate(trades[:10], 1):  # Show last 10 trades
        profit_pips = float(t.pips_captured) if t.pips_captured else 0
        duration = t.hold_duration_minutes if t.hold_duration_minutes else 0
        close_reason = t.close_reason or 'N/A'
        confidence = float(t.entry_confidence) if t.entry_confidence else 0

        status_emoji = '✅' if float(t.profit) > 0 else '❌'
        print(f'{i:2d}. {status_emoji} Ticket #{t.ticket}: {t.direction.upper()} {t.symbol}')
        print(f'    Entry: {t.open_price} @ {t.open_time.strftime("%Y-%m-%d %H:%M")} UTC')
        print(f'    Exit:  {t.close_price} @ {t.close_time.strftime("%Y-%m-%d %H:%M")} UTC ({close_reason})')
        print(f'    P/L: ${float(t.profit):+.2f} ({profit_pips:+.1f} pips) | Dauer: {duration}min | Confidence: {confidence:.0f}%')

    if len(trades) > 10:
        print(f'\n... und {len(trades) - 10} weitere Trades')

db.close()
