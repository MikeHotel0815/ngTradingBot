#!/usr/bin/env python3
"""
Analyze trades from the last 36 hours with detailed evaluation
"""

import sys
import os
from datetime import datetime, timedelta
from sqlalchemy import create_engine, and_, or_
from sqlalchemy.orm import sessionmaker
from models import Trade, Account
from decimal import Decimal

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db = Session()

# Get trades from last 36 hours
now = datetime.utcnow()
cutoff = now - timedelta(hours=36)

trades = db.query(Trade).filter(
    and_(
        Trade.created_at >= cutoff,
        Trade.status == 'closed'
    )
).order_by(Trade.close_time.desc()).all()

print(f'═══════════════════════════════════════════════════════════════')
print(f'    TRADING BOT PERFORMANCE REPORT - LETZTE 36 STUNDEN')
print(f'═══════════════════════════════════════════════════════════════')
print(f'Zeitraum: {cutoff.strftime("%Y-%m-%d %H:%M")} bis {now.strftime("%Y-%m-%d %H:%M")} UTC')
print(f'Anzahl geschlossener Trades: {len(trades)}\n')

if not trades:
    print('⚠️  Keine geschlossenen Trades in den letzten 36 Stunden gefunden.')

    # Check for open trades
    open_trades = db.query(Trade).filter(
        and_(
            Trade.created_at >= cutoff,
            Trade.status == 'open'
        )
    ).all()

    if open_trades:
        print(f'\n📊 Aber {len(open_trades)} offene Trades gefunden:')
        for t in open_trades:
            profit_pips = float(t.pips_captured) if t.pips_captured else 0
            print(f'  • Ticket #{t.ticket}: {t.direction.upper()} {t.symbol} @ {t.open_price}')
            print(f'    Offen seit: {t.open_time.strftime("%Y-%m-%d %H:%M")} UTC ({profit_pips:+.1f} pips)')
else:
    # Calculate statistics
    winning_trades = [t for t in trades if float(t.profit) > 0]
    losing_trades = [t for t in trades if float(t.profit) < 0]
    breakeven = [t for t in trades if float(t.profit) == 0]

    total_profit = sum(float(t.profit) for t in winning_trades)
    total_loss = sum(float(t.profit) for t in losing_trades)
    net_profit = total_profit + total_loss

    win_rate = len(winning_trades) / len(trades) * 100 if trades else 0

    # Calculate average metrics
    avg_win = total_profit / len(winning_trades) if winning_trades else 0
    avg_loss = total_loss / len(losing_trades) if losing_trades else 0
    profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float('inf')
    risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # Calculate pips
    total_pips = sum(float(t.pips_captured or 0) for t in trades)
    avg_pips = total_pips / len(trades) if trades else 0

    # Calculate average duration
    durations = [t.hold_duration_minutes for t in trades if t.hold_duration_minutes]
    avg_duration = sum(durations) / len(durations) if durations else 0

    print(f'📈 PERFORMANCE ÜBERSICHT:')
    print(f'╔═══════════════════════════════════════════════════════════╗')
    print(f'║ Gewinnende Trades: {len(winning_trades):>3} ({win_rate:>5.1f}%)                           ║')
    print(f'║ Verlierende Trades: {len(losing_trades):>2} ({100-win_rate:>5.1f}%)                           ║')
    print(f'║ Breakeven: {len(breakeven):>2}                                              ║')
    print(f'╠═══════════════════════════════════════════════════════════╣')
    print(f'║ Gewinn:         ${total_profit:>8.2f}                              ║')
    print(f'║ Verlust:        ${total_loss:>8.2f}                              ║')
    print(f'║ Netto P/L:      ${net_profit:>+8.2f}                              ║')
    print(f'╠═══════════════════════════════════════════════════════════╣')
    print(f'║ Ø Gewinn:       ${avg_win:>8.2f}                              ║')
    print(f'║ Ø Verlust:      ${avg_loss:>8.2f}                              ║')
    print(f'║ Profit Factor:  {profit_factor:>8.2f}                              ║')
    print(f'║ Risk/Reward:    {risk_reward:>8.2f}                              ║')
    print(f'╠═══════════════════════════════════════════════════════════╣')
    print(f'║ Total Pips:     {total_pips:>+8.1f}                              ║')
    print(f'║ Ø Pips/Trade:   {avg_pips:>+8.1f}                              ║')
    print(f'║ Ø Dauer:        {avg_duration:>8.0f} min                           ║')
    print(f'╚═══════════════════════════════════════════════════════════╝')

    # Bewertung
    print(f'\n🎯 BEWERTUNG & ANALYSE:')
    print(f'─────────────────────────────────────────────────────────────')

    # Win Rate Bewertung
    if win_rate >= 60:
        wr_rating = "AUSGEZEICHNET ✅"
    elif win_rate >= 50:
        wr_rating = "GUT ✓"
    elif win_rate >= 40:
        wr_rating = "AKZEPTABEL ⚠"
    else:
        wr_rating = "VERBESSERUNGSBEDÜRFTIG ❌"
    print(f'Win Rate ({win_rate:.1f}%): {wr_rating}')

    # Profit Factor Bewertung
    if profit_factor >= 2.0:
        pf_rating = "AUSGEZEICHNET ✅"
    elif profit_factor >= 1.5:
        pf_rating = "GUT ✓"
    elif profit_factor >= 1.0:
        pf_rating = "PROFITABEL ⚠"
    else:
        pf_rating = "VERLUSTREICH ❌"
    print(f'Profit Factor ({profit_factor:.2f}): {pf_rating}')

    # Risk/Reward Bewertung
    if risk_reward >= 2.0:
        rr_rating = "AUSGEZEICHNET ✅"
    elif risk_reward >= 1.5:
        rr_rating = "GUT ✓"
    elif risk_reward >= 1.0:
        rr_rating = "AKZEPTABEL ⚠"
    else:
        rr_rating = "VERBESSERUNGSBEDÜRFTIG ❌"
    print(f'Risk/Reward ({risk_reward:.2f}): {rr_rating}')

    # Netto P/L Bewertung
    if net_profit > 50:
        pl_rating = "SEHR PROFITABEL ✅"
    elif net_profit > 0:
        pl_rating = "PROFITABEL ✓"
    elif net_profit > -50:
        pl_rating = "KLEINER VERLUST ⚠"
    else:
        pl_rating = "SIGNIFIKANTER VERLUST ❌"
    print(f'Netto P/L (${net_profit:+.2f}): {pl_rating}')

    # Group by symbol
    symbols = {}
    for t in trades:
        if t.symbol not in symbols:
            symbols[t.symbol] = {'trades': [], 'profit': 0, 'pips': 0, 'wins': 0}
        symbols[t.symbol]['trades'].append(t)
        symbols[t.symbol]['profit'] += float(t.profit)
        symbols[t.symbol]['pips'] += float(t.pips_captured or 0)
        if float(t.profit) > 0:
            symbols[t.symbol]['wins'] += 1

    print(f'\n💹 PERFORMANCE PRO SYMBOL:')
    print(f'─────────────────────────────────────────────────────────────')
    for symbol, data in sorted(symbols.items(), key=lambda x: x[1]['profit'], reverse=True):
        sym_wins = data['wins']
        sym_total = len(data['trades'])
        sym_wr = sym_wins / sym_total * 100 if sym_total > 0 else 0

        # Symbol Rating
        if data['profit'] > 0 and sym_wr >= 50:
            sym_status = "✅"
        elif data['profit'] > 0:
            sym_status = "✓"
        elif data['profit'] > -10:
            sym_status = "⚠"
        else:
            sym_status = "❌"

        print(f'{sym_status} {symbol:8}: {sym_total:2} Trades | {sym_wr:5.0f}% WR | ${data["profit"]:>+8.2f} | {data["pips"]:>+7.1f} pips')

    # Close reasons analysis
    close_reasons = {}
    for t in trades:
        reason = t.close_reason or 'N/A'
        if reason not in close_reasons:
            close_reasons[reason] = {'count': 0, 'profit': 0, 'wins': 0}
        close_reasons[reason]['count'] += 1
        close_reasons[reason]['profit'] += float(t.profit)
        if float(t.profit) > 0:
            close_reasons[reason]['wins'] += 1

    print(f'\n🎯 EXIT GRÜNDE ANALYSE:')
    print(f'─────────────────────────────────────────────────────────────')
    for reason, data in sorted(close_reasons.items(), key=lambda x: x[1]['count'], reverse=True):
        wr = data['wins'] / data['count'] * 100 if data['count'] > 0 else 0
        print(f'  • {reason:20}: {data["count"]:2} Trades | {wr:5.0f}% WR | ${data["profit"]:>+8.2f}')

    # Confidence analysis
    high_conf_trades = [t for t in trades if t.entry_confidence and float(t.entry_confidence) >= 85]
    low_conf_trades = [t for t in trades if t.entry_confidence and float(t.entry_confidence) < 85]

    if high_conf_trades:
        high_conf_wins = len([t for t in high_conf_trades if float(t.profit) > 0])
        high_conf_wr = high_conf_wins / len(high_conf_trades) * 100
        high_conf_profit = sum(float(t.profit) for t in high_conf_trades)
    else:
        high_conf_wr = 0
        high_conf_profit = 0

    if low_conf_trades:
        low_conf_wins = len([t for t in low_conf_trades if float(t.profit) > 0])
        low_conf_wr = low_conf_wins / len(low_conf_trades) * 100
        low_conf_profit = sum(float(t.profit) for t in low_conf_trades)
    else:
        low_conf_wr = 0
        low_conf_profit = 0

    print(f'\n📊 CONFIDENCE LEVEL ANALYSE:')
    print(f'─────────────────────────────────────────────────────────────')
    print(f'  High Confidence (≥85%): {len(high_conf_trades):2} Trades | {high_conf_wr:5.1f}% WR | ${high_conf_profit:>+8.2f}')
    print(f'  Low Confidence (<85%):  {len(low_conf_trades):2} Trades | {low_conf_wr:5.1f}% WR | ${low_conf_profit:>+8.2f}')

    print(f'\n📋 DETAILLIERTE TRADE-LISTE:')
    print(f'═════════════════════════════════════════════════════════════')
    for i, t in enumerate(trades, 1):
        profit_pips = float(t.pips_captured) if t.pips_captured else 0
        duration = t.hold_duration_minutes if t.hold_duration_minutes else 0
        close_reason = t.close_reason or 'N/A'
        confidence = float(t.entry_confidence) if t.entry_confidence else 0

        status_emoji = '✅' if float(t.profit) > 0 else '❌'
        print(f'{i:2d}. {status_emoji} #{t.ticket}: {t.direction.upper()} {t.symbol}')
        print(f'    Entry: {t.open_price} @ {t.open_time.strftime("%m-%d %H:%M")} UTC')
        print(f'    Exit:  {t.close_price} @ {t.close_time.strftime("%m-%d %H:%M")} UTC ({close_reason})')
        print(f'    P/L: ${float(t.profit):>+7.2f} ({profit_pips:>+6.1f} pips) | {duration:>4.0f}min | Conf: {confidence:>3.0f}%')
        if i < len(trades):
            print(f'    ─────────────────────────────────────────────────────────')

# Check for currently open trades
print(f'\n\n📊 AKTUELL OFFENE TRADES:')
print(f'═════════════════════════════════════════════════════════════')
open_trades = db.query(Trade).filter(Trade.status == 'open').all()

if not open_trades:
    print('Keine offenen Trades.')
else:
    print(f'Anzahl: {len(open_trades)}\n')
    total_open_profit = 0
    for t in open_trades:
        profit_pips = float(t.pips_captured) if t.pips_captured else 0
        unrealized_profit = float(t.profit) if t.profit else 0
        total_open_profit += unrealized_profit
        duration_min = int((datetime.utcnow() - t.open_time).total_seconds() / 60) if t.open_time else 0
        confidence = float(t.entry_confidence) if t.entry_confidence else 0

        status = "🟢" if unrealized_profit > 0 else "🔴" if unrealized_profit < 0 else "⚪"
        print(f'{status} #{t.ticket}: {t.direction.upper()} {t.symbol} @ {t.open_price}')
        print(f'   Offen seit: {t.open_time.strftime("%Y-%m-%d %H:%M")} UTC ({duration_min}min)')
        print(f'   Aktuell: ${unrealized_profit:>+7.2f} USD | {profit_pips:>+6.1f} pips | Conf: {confidence:.0f}%')
        if t.stop_loss:
            print(f'   SL: {t.stop_loss} | TP: {t.take_profit or "N/A"}')
        print(f'   ─────────────────────────────────────────────────────────')

    print(f'\nGesamt unrealisierter P/L: ${total_open_profit:+.2f}')

print(f'\n═════════════════════════════════════════════════════════════')
print(f'                    REPORT ENDE')
print(f'═════════════════════════════════════════════════════════════')

db.close()
