#!/usr/bin/env python3
"""
Analyse: Trailing Stop vs. TP Analysis
Prüft welche Trades die per TS geschlossen wurden, tatsächlich ins TP gelaufen wären
"""

import logging
from datetime import datetime, timedelta
from database import ScopedSession
from models import Trade, OHLCData
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_max_price_after_entry(db, trade):
    """
    Holt den höchsten/niedrigsten Preis nach Trade Entry bis zum Close
    
    Returns:
        (max_favorable_price, min_unfavorable_price)
    """
    if not trade.open_time or not trade.close_time:
        return None, None
    
    # M1 Candles zwischen Entry und Exit holen
    candles = db.query(OHLCData).filter(
        OHLCData.symbol == trade.symbol,
        OHLCData.timeframe == 'M1',
        OHLCData.timestamp >= trade.open_time,
        OHLCData.timestamp <= trade.close_time
    ).order_by(OHLCData.timestamp.asc()).all()
    
    if not candles:
        logger.warning(f"No OHLC data for {trade.symbol} between {trade.open_time} and {trade.close_time}")
        return None, None
    
    if trade.direction == 'BUY':
        # Für BUY: Höchster High (TP Richtung) und niedrigster Low (SL Richtung)
        max_favorable = max(float(c.high) for c in candles)
        min_unfavorable = min(float(c.low) for c in candles)
    else:  # SELL
        # Für SELL: Niedrigster Low (TP Richtung) und höchster High (SL Richtung)
        max_favorable = min(float(c.low) for c in candles)
        min_unfavorable = max(float(c.high) for c in candles)
    
    return max_favorable, min_unfavorable


def analyze_ts_trades():
    """Analysiere alle TRAILING_STOP und MANUAL Trades"""
    
    db = ScopedSession()
    
    try:
        # Hole alle Trades mit close_reason='TRAILING_STOP' ODER 'MANUAL'
        ts_trades = db.query(Trade).filter(
            Trade.status == 'closed',
            Trade.close_reason.in_(['TRAILING_STOP', 'MANUAL'])
        ).order_by(Trade.close_time.desc()).limit(50).all()  # Limitiere auf letzte 50
        
        if not ts_trades:
            logger.info("❌ Keine TRAILING_STOP oder MANUAL Trades gefunden")
            return
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Analyse von {len(ts_trades)} Trades (TRAILING_STOP + MANUAL)")
        logger.info(f"{'='*80}\n")
        
        results = []
        
        for trade in ts_trades:
            # TP/SL prüfen
            if not trade.tp or not trade.sl:
                logger.warning(f"Trade #{trade.ticket}: Kein TP/SL gesetzt - überspringe")
                continue
            
            entry = float(trade.open_price)
            tp = float(trade.tp)
            sl = float(trade.sl)
            close_price = float(trade.close_price) if trade.close_price else None
            
            # Max/Min Price während Trade ermitteln
            max_favorable, min_unfavorable = get_max_price_after_entry(db, trade)
            
            if max_favorable is None:
                logger.warning(f"Trade #{trade.ticket}: Keine OHLC Daten verfügbar - überspringe")
                continue
            
            # Prüfe ob TP erreicht wurde
            tp_reached = False
            if trade.direction == 'BUY':
                tp_reached = max_favorable >= tp
                tp_distance = tp - entry
                max_distance = max_favorable - entry
            else:  # SELL
                tp_reached = max_favorable <= tp
                tp_distance = entry - tp
                max_distance = entry - max_favorable
            
            # Profit Berechnung
            actual_profit = float(trade.profit) if trade.profit else 0.0
            
            # Geschätzter TP Profit (wenn TP erreicht worden wäre)
            if trade.direction == 'BUY':
                estimated_tp_profit = (tp - entry) * float(trade.volume) * 100000  # Vereinfachte Berechnung
            else:
                estimated_tp_profit = (entry - tp) * float(trade.volume) * 100000
            
            # Verpasster Profit
            missed_profit = estimated_tp_profit - actual_profit if tp_reached else 0
            
            result = {
                'ticket': trade.ticket,
                'symbol': trade.symbol,
                'direction': trade.direction,
                'close_reason': trade.close_reason,  # TS oder MANUAL
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'close_price': close_price,
                'max_favorable': max_favorable,
                'tp_reached': tp_reached,
                'actual_profit': actual_profit,
                'estimated_tp_profit': estimated_tp_profit if tp_reached else None,
                'missed_profit': missed_profit if tp_reached else 0,
                'open_time': trade.open_time,
                'close_time': trade.close_time,
                'duration': (trade.close_time - trade.open_time) if trade.close_time and trade.open_time else None
            }
            
            results.append(result)
        
        # Statistiken
        tp_would_hit_count = sum(1 for r in results if r['tp_reached'])
        total_ts_trades = len(results)
        manual_count = sum(1 for r in results if r['close_reason'] == 'MANUAL')
        ts_count = sum(1 for r in results if r['close_reason'] == 'TRAILING_STOP')
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📈 ERGEBNISSE")
        logger.info(f"{'='*80}")
        logger.info(f"Total Trades analysiert: {total_ts_trades}")
        logger.info(f"  - MANUAL: {manual_count}")
        logger.info(f"  - TRAILING_STOP: {ts_count}")
        logger.info(f"Davon hätten TP erreicht: {tp_would_hit_count} ({tp_would_hit_count/total_ts_trades*100:.1f}%)")
        logger.info(f"Geschlossen VOR TP: {total_ts_trades - tp_would_hit_count} ({(total_ts_trades - tp_would_hit_count)/total_ts_trades*100:.1f}%)")
        
        # Verpasster Profit
        total_missed_profit = sum(r['missed_profit'] for r in results if r['missed_profit'])
        logger.info(f"\n💸 Verpasster Profit (hätte TP erreicht): €{total_missed_profit:.2f}")
        
        # Detail-Ausgabe für Trades die TP erreicht hätten
        if tp_would_hit_count > 0:
            logger.info(f"\n{'='*80}")
            logger.info(f"🎯 TRADES DIE TP ERREICHT HÄTTEN:")
            logger.info(f"{'='*80}\n")
            
            for r in results:
                if r['tp_reached']:
                    duration_str = str(r['duration']).split('.')[0] if r['duration'] else 'N/A'
                    logger.info(f"#{r['ticket']} | {r['symbol']} {r['direction']} | Close: {r['close_reason']}")
                    logger.info(f"  Entry: {r['entry']:.5f} → TP: {r['tp']:.5f}")
                    logger.info(f"  Max erreicht: {r['max_favorable']:.5f} ✅ (TP wurde erreicht!)")
                    logger.info(f"  Geschlossen bei: {r['close_price']:.5f}")
                    logger.info(f"  Actual P/L: €{r['actual_profit']:.2f}")
                    logger.info(f"  TP P/L wäre: €{r['estimated_tp_profit']:.2f}")
                    logger.info(f"  Verpasst: €{r['missed_profit']:.2f}")
                    logger.info(f"  Duration: {duration_str}")
                    logger.info("")
        
        # Trades die NICHT TP erreicht hätten
        ts_correct_count = total_ts_trades - tp_would_hit_count
        if ts_correct_count > 0:
            logger.info(f"\n{'='*80}")
            logger.info(f"✅ TS WAR RICHTIG (TP nicht erreicht):")
            logger.info(f"{'='*80}\n")
            
            for r in results:
                if not r['tp_reached']:
                    duration_str = str(r['duration']).split('.')[0] if r['duration'] else 'N/A'
                    logger.info(f"#{r['ticket']} | {r['symbol']} {r['direction']}")
                    logger.info(f"  Entry: {r['entry']:.5f} → TP: {r['tp']:.5f}")
                    logger.info(f"  Max erreicht: {r['max_favorable']:.5f} ❌ (TP NICHT erreicht)")
                    logger.info(f"  Geschlossen bei: {r['close_price']:.5f} (TS)")
                    logger.info(f"  Actual P/L: €{r['actual_profit']:.2f}")
                    logger.info(f"  Duration: {duration_str}")
                    logger.info(f"  → TS war hier RICHTIG! Hätte sonst umgedreht.")
                    logger.info("")
        
        # Zusammenfassung
        logger.info(f"\n{'='*80}")
        logger.info(f"📋 ZUSAMMENFASSUNG")
        logger.info(f"{'='*80}")
        logger.info(f"TS Trades Total: {total_ts_trades}")
        logger.info(f"TP hätte getroffen: {tp_would_hit_count} ({tp_would_hit_count/total_ts_trades*100:.1f}%)")
        logger.info(f"TS war richtig (kein TP): {ts_correct_count} ({ts_correct_count/total_ts_trades*100:.1f}%)")
        logger.info(f"Verpasster Profit: €{total_missed_profit:.2f}")
        
        if total_ts_trades > 0:
            avg_missed = total_missed_profit / tp_would_hit_count if tp_would_hit_count > 0 else 0
            logger.info(f"Ø Verpasst pro Trade: €{avg_missed:.2f}")
        
        logger.info(f"{'='*80}\n")
        
    except Exception as e:
        logger.error(f"Fehler bei der Analyse: {e}", exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    analyze_ts_trades()
