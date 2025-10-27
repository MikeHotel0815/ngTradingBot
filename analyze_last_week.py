#!/usr/bin/env python3
"""
Analyse der letzten Handelswoche mit aktuellen Features und Parametern
"""

import sys
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, and_, func, case
from sqlalchemy.orm import sessionmaker
from models import Trade, Account, SymbolTradingConfig, TradingSignal
from decimal import Decimal
from collections import defaultdict

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db = Session()

# Zeitraum: letzte 7 Handelstage
now = datetime.utcnow()
week_ago = now - timedelta(days=7)

print('=' * 100)
print(f'📊 HANDELSWOCHE ANALYSE: {week_ago.strftime("%Y-%m-%d %H:%M")} bis {now.strftime("%Y-%m-%d %H:%M")} UTC')
print('=' * 100)

# 1. AKTUELLE KONFIGURATION
print('\n⚙️  AKTUELLE SYMBOL-KONFIGURATION:')
print('-' * 100)
configs = db.query(SymbolTradingConfig).order_by(SymbolTradingConfig.symbol).all()
print(f'{"Symbol":<10} {"Status":<10} {"MinConf":<10} {"Risk":<10} {"BUY":<8} {"SELL":<8} {"MaxSpread":<12}')
print('-' * 100)
for cfg in configs:
    buy_str = '✓' if cfg.buy_enabled else '✗'
    sell_str = '✓' if cfg.sell_enabled else '✗'
    risk_mult = float(cfg.risk_multiplier) if cfg.risk_multiplier else 1.0
    min_conf = float(cfg.min_confidence) if cfg.min_confidence else 0
    max_spread = float(cfg.max_spread) if cfg.max_spread else 0
    print(f'{cfg.symbol:<10} {cfg.status:<10} {min_conf:>9.1f}% {risk_mult:>9.2f}x {buy_str:^8} {sell_str:^8} {max_spread:>11.1f}')

# 2. GESCHLOSSENE TRADES ANALYSE
print('\n\n📈 GESCHLOSSENE TRADES (letzte 7 Tage):')
print('-' * 100)

closed_trades = db.query(Trade).filter(
    and_(
        Trade.close_time >= week_ago,
        Trade.status == 'closed'
    )
).all()

if not closed_trades:
    print('⚠️  Keine geschlossenen Trades gefunden.')
else:
    # Gruppierung nach Symbol
    symbol_stats = defaultdict(lambda: {
        'trades': [],
        'wins': 0,
        'losses': 0,
        'total_profit': 0,
        'win_sum': 0,
        'loss_sum': 0,
        'max_win': 0,
        'max_loss': 0,
        'pips_total': 0,
        'duration_total': 0
    })

    for trade in closed_trades:
        symbol = trade.symbol
        profit = float(trade.profit) if trade.profit else 0
        pips = float(trade.pips_captured) if trade.pips_captured else 0
        duration = trade.hold_duration_minutes if trade.hold_duration_minutes else 0

        symbol_stats[symbol]['trades'].append(trade)
        symbol_stats[symbol]['total_profit'] += profit
        symbol_stats[symbol]['pips_total'] += pips
        symbol_stats[symbol]['duration_total'] += duration

        if profit > 0:
            symbol_stats[symbol]['wins'] += 1
            symbol_stats[symbol]['win_sum'] += profit
            symbol_stats[symbol]['max_win'] = max(symbol_stats[symbol]['max_win'], profit)
        else:
            symbol_stats[symbol]['losses'] += 1
            symbol_stats[symbol]['loss_sum'] += profit
            symbol_stats[symbol]['max_loss'] = min(symbol_stats[symbol]['max_loss'], profit)

    # Header
    print(f'{"Symbol":<10} {"Trades":<8} {"WR%":<8} {"P/L (€)":<12} {"Avg P/L":<10} {"Best":<10} {"Worst":<10} {"Avg Pips":<10}')
    print('-' * 100)

    # Sortiert nach Profit
    total_trades = 0
    total_profit = 0
    total_wins = 0
    total_losses = 0

    for symbol in sorted(symbol_stats.keys(), key=lambda s: symbol_stats[s]['total_profit'], reverse=True):
        stats = symbol_stats[symbol]
        num_trades = len(stats['trades'])
        win_rate = (stats['wins'] / num_trades * 100) if num_trades > 0 else 0
        avg_profit = stats['total_profit'] / num_trades if num_trades > 0 else 0
        avg_pips = stats['pips_total'] / num_trades if num_trades > 0 else 0

        total_trades += num_trades
        total_profit += stats['total_profit']
        total_wins += stats['wins']
        total_losses += stats['losses']

        profit_str = f'+{stats["total_profit"]:.2f}' if stats['total_profit'] > 0 else f'{stats["total_profit"]:.2f}'

        print(f'{symbol:<10} {num_trades:>7} {win_rate:>7.1f} {profit_str:>11} {avg_profit:>9.2f} {stats["max_win"]:>9.2f} {stats["max_loss"]:>9.2f} {avg_pips:>9.1f}')

    # Gesamt-Zeile
    print('-' * 100)
    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
    profit_str = f'+{total_profit:.2f}' if total_profit > 0 else f'{total_profit:.2f}'
    print(f'{"GESAMT":<10} {total_trades:>7} {overall_wr:>7.1f} {profit_str:>11} {"":>9} {"":>9} {"":>9} {"":>9}')

# 3. DETAILLIERTE PERFORMANCE-METRIKEN
print('\n\n💹 DETAILLIERTE PERFORMANCE-METRIKEN:')
print('=' * 100)

for symbol in sorted(symbol_stats.keys(), key=lambda s: symbol_stats[s]['total_profit'], reverse=True):
    stats = symbol_stats[symbol]
    num_trades = len(stats['trades'])

    if num_trades == 0:
        continue

    win_rate = (stats['wins'] / num_trades * 100) if num_trades > 0 else 0
    avg_win = stats['win_sum'] / stats['wins'] if stats['wins'] > 0 else 0
    avg_loss = stats['loss_sum'] / stats['losses'] if stats['losses'] > 0 else 0

    # Risk/Reward Ratio
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # Profit Factor
    gross_profit = stats['win_sum']
    gross_loss = abs(stats['loss_sum'])
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    # Durchschnittliche Haltedauer
    avg_duration = stats['duration_total'] / num_trades if num_trades > 0 else 0
    avg_duration_hours = avg_duration / 60

    # Durchschnittliche Confidence
    avg_confidence = sum(float(t.entry_confidence) if t.entry_confidence else 0 for t in stats['trades']) / num_trades

    print(f'\n{symbol}:')
    print(f'  ├─ Trades: {num_trades} | Wins: {stats["wins"]} | Losses: {stats["losses"]} | WR: {win_rate:.1f}%')
    print(f'  ├─ Total P/L: {stats["total_profit"]:+.2f} EUR | Avg P/L: {stats["total_profit"]/num_trades:+.2f} EUR')
    print(f'  ├─ Avg Win: +{avg_win:.2f} EUR | Avg Loss: {avg_loss:.2f} EUR')
    print(f'  ├─ Best Trade: +{stats["max_win"]:.2f} EUR | Worst Trade: {stats["max_loss"]:.2f} EUR')
    print(f'  ├─ R/R Ratio: {rr_ratio:.2f} | Profit Factor: {profit_factor:.2f}')
    print(f'  ├─ Avg Duration: {avg_duration_hours:.1f}h ({avg_duration:.0f}min)')
    print(f'  └─ Avg Confidence: {avg_confidence:.1f}%')

# 4. TÄGLICHE PERFORMANCE
print('\n\n📅 TÄGLICHE PERFORMANCE:')
print('-' * 100)

# Gruppierung nach Tag
daily_stats = defaultdict(lambda: {'trades': 0, 'profit': 0, 'wins': 0})

for trade in closed_trades:
    day = trade.close_time.date() if trade.close_time else None
    if day:
        profit = float(trade.profit) if trade.profit else 0
        daily_stats[day]['trades'] += 1
        daily_stats[day]['profit'] += profit
        if profit > 0:
            daily_stats[day]['wins'] += 1

print(f'{"Datum":<15} {"Trades":<10} {"P/L (EUR)":<15} {"Win Rate":<10}')
print('-' * 100)

for day in sorted(daily_stats.keys(), reverse=True):
    stats = daily_stats[day]
    wr = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
    profit_str = f'+{stats["profit"]:.2f}' if stats['profit'] > 0 else f'{stats["profit"]:.2f}'
    print(f'{day.strftime("%Y-%m-%d")} {stats["trades"]:>9} {profit_str:>14} {wr:>9.1f}%')

# 5. OFFENE POSITIONEN
print('\n\n📊 OFFENE POSITIONEN:')
print('-' * 100)

open_trades = db.query(Trade).filter(Trade.status == 'open').all()

if not open_trades:
    print('Keine offenen Positionen.')
else:
    open_stats = defaultdict(lambda: {'count': 0, 'unrealized': 0})

    for trade in open_trades:
        symbol = trade.symbol
        unrealized = float(trade.current_profit) if trade.current_profit else 0
        open_stats[symbol]['count'] += 1
        open_stats[symbol]['unrealized'] += unrealized

    print(f'{"Symbol":<10} {"Offene":<10} {"Unrealisiert (EUR)":<20}')
    print('-' * 100)

    total_open = 0
    total_unrealized = 0

    for symbol in sorted(open_stats.keys()):
        stats = open_stats[symbol]
        total_open += stats['count']
        total_unrealized += stats['unrealized']

        unrealized_str = f'+{stats["unrealized"]:.2f}' if stats['unrealized'] > 0 else f'{stats["unrealized"]:.2f}'
        print(f'{symbol:<10} {stats["count"]:>9} {unrealized_str:>19}')

    print('-' * 100)
    unrealized_str = f'+{total_unrealized:.2f}' if total_unrealized > 0 else f'{total_unrealized:.2f}'
    print(f'{"GESAMT":<10} {total_open:>9} {unrealized_str:>19}')

# 6. STOP-LOSS ENFORCEMENT STATUS
print('\n\n🛡️  STOP-LOSS ENFORCEMENT STATUS:')
print('-' * 100)

sl_stats = defaultdict(lambda: {'total': 0, 'with_sl': 0, 'without_sl': 0})

for trade in closed_trades:
    symbol = trade.symbol
    sl_stats[symbol]['total'] += 1

    if trade.stop_loss and float(trade.stop_loss) != 0:
        sl_stats[symbol]['with_sl'] += 1
    else:
        sl_stats[symbol]['without_sl'] += 1

print(f'{"Symbol":<10} {"Trades":<10} {"Mit SL":<10} {"Ohne SL":<10} {"SL Rate":<10}')
print('-' * 100)

for symbol in sorted(sl_stats.keys()):
    stats = sl_stats[symbol]
    sl_rate = (stats['with_sl'] / stats['total'] * 100) if stats['total'] > 0 else 0
    print(f'{symbol:<10} {stats["total"]:>9} {stats["with_sl"]:>9} {stats["without_sl"]:>9} {sl_rate:>9.1f}%')

# Check auf doppelte offene Positionen pro Symbol
duplicate_check = db.query(
    Trade.symbol,
    func.count(Trade.id).label('count')
).filter(
    Trade.status == 'open'
).group_by(
    Trade.symbol
).having(
    func.count(Trade.id) > 1
).all()

if duplicate_check:
    print(f'\n⚠️  WARNUNG: Duplikate gefunden!')
    for symbol, count in duplicate_check:
        print(f'  • {symbol}: {count} offene Positionen')
else:
    print(f'\n✓ Keine Duplikate bei offenen Positionen')

# 7. SIGNAL-GENERIERUNG
print('\n\n🎯 SIGNAL-GENERIERUNG (letzte 7 Tage):')
print('-' * 100)

signals = db.query(TradingSignal).filter(TradingSignal.timestamp >= week_ago).all()

if not signals:
    print('Keine Signale gefunden.')
else:
    signal_stats = defaultdict(lambda: {
        'total': 0,
        'qualified': 0,
        'confidence_sum': 0,
        'max_confidence': 0
    })

    for signal in signals:
        symbol = signal.symbol
        confidence = float(signal.confidence) if signal.confidence else 0

        # Get min_confidence für dieses Symbol
        cfg = db.query(SymbolTradingConfig).filter_by(symbol=symbol).first()
        min_conf = float(cfg.min_confidence) if cfg and cfg.min_confidence else 60.0

        signal_stats[symbol]['total'] += 1
        signal_stats[symbol]['confidence_sum'] += confidence
        signal_stats[symbol]['max_confidence'] = max(signal_stats[symbol]['max_confidence'], confidence)

        if confidence >= min_conf:
            signal_stats[symbol]['qualified'] += 1

    print(f'{"Symbol":<10} {"Signale":<10} {"Qualifiziert":<15} {"Conversion":<12} {"Avg Conf":<10} {"Max Conf":<10}')
    print('-' * 100)

    total_signals = 0
    total_qualified = 0

    for symbol in sorted(signal_stats.keys()):
        stats = signal_stats[symbol]
        avg_conf = stats['confidence_sum'] / stats['total'] if stats['total'] > 0 else 0
        conversion = (stats['qualified'] / stats['total'] * 100) if stats['total'] > 0 else 0

        total_signals += stats['total']
        total_qualified += stats['qualified']

        print(f'{symbol:<10} {stats["total"]:>9} {stats["qualified"]:>14} {conversion:>11.1f}% {avg_conf:>9.1f}% {stats["max_confidence"]:>9.1f}%')

    print('-' * 100)
    overall_conv = (total_qualified / total_signals * 100) if total_signals > 0 else 0
    print(f'{"GESAMT":<10} {total_signals:>9} {total_qualified:>14} {overall_conv:>11.1f}%')

# 8. GESAMTBILANZ
print('\n\n💰 GESAMTBILANZ (letzte 7 Tage):')
print('=' * 100)
print(f'Realisierter Gewinn:   {total_profit:+.2f} EUR')
print(f'Unrealisierter Gewinn: {total_unrealized:+.2f} EUR')
print(f'Gesamtbilanz:          {total_profit + total_unrealized:+.2f} EUR')
print(f'\nTrades gesamt:         {total_trades}')
print(f'Win Rate:              {overall_wr:.1f}%')
print(f'Offene Positionen:     {total_open}')

# Account Info
account = db.query(Account).first()
if account:
    balance = float(account.balance) if account.balance else 0
    equity = float(account.equity) if account.equity else 0
    print(f'\n📊 Account Status:')
    print(f'Balance:               {balance:.2f} EUR')
    print(f'Equity:                {equity:.2f} EUR')
    print(f'Wöchentliche Rendite:  {(total_profit / balance * 100):.2f}%' if balance > 0 else 'N/A')

print('\n' + '=' * 100)

db.close()
